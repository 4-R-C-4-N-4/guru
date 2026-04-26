"""Regression test for embed_ollama batching (todo:0633fb4a).

The previous implementation looped one HTTP request per chunk, silently
ignoring the outer batch_size. The fix sends the entire `texts` list as
a single ollama /api/embed call. This test mocks urllib so it runs
without a live ollama, asserting:

  1. ONE HTTP call is made for N inputs (not N).
  2. The payload's `input` field is the array, not a single string.
  3. The function returns embeddings in the same order as the inputs.
  4. Empty input is a no-op (no HTTP call) — guards against the
     never-batch-zero edge case.
  5. A length mismatch in the response surfaces as a RuntimeError.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from embed_corpus import embed_ollama  # noqa: E402


def _mock_response(payload_obj: dict) -> MagicMock:
    """Build a MagicMock that quacks like urlopen's context manager."""
    body = json.dumps(payload_obj).encode()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=io.BytesIO(body))
    cm.__exit__ = MagicMock(return_value=False)
    return cm


def test_batched_embed_makes_one_http_call() -> None:
    texts = [f"chunk {i}" for i in range(8)]
    fake_vectors = [[float(i)] * 4 for i in range(8)]

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_response({"embeddings": fake_vectors})
        result = embed_ollama(texts, "nomic-embed-text")

    # 1. exactly one HTTP request — not N
    assert mock_urlopen.call_count == 1, "must batch into a single request, not loop"

    # 2. payload `input` is the full array, not a single string
    request = mock_urlopen.call_args.args[0]
    sent = json.loads(request.data)
    assert sent["model"] == "nomic-embed-text"
    assert sent["input"] == texts, "input must be the full text array"
    assert isinstance(sent["input"], list), "input must be a list, not a string"

    # 3. order preserved
    assert result == fake_vectors


def test_empty_input_skips_http() -> None:
    with patch("urllib.request.urlopen") as mock_urlopen:
        result = embed_ollama([], "nomic-embed-text")
    assert result == []
    assert mock_urlopen.call_count == 0


def test_length_mismatch_raises() -> None:
    texts = ["a", "b", "c"]
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_response({"embeddings": [[0.1], [0.2]]})  # only 2!
        with pytest.raises(RuntimeError, match="2 embeddings for 3 inputs"):
            embed_ollama(texts, "nomic-embed-text")


def test_single_input_still_uses_array_form() -> None:
    """Even for one input, the API call must use the array form so the
    code path is consistent and the regression to per-call looping
    can't sneak back."""
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_response({"embeddings": [[1.0, 2.0]]})
        embed_ollama(["one chunk"], "nomic-embed-text")

    sent = json.loads(mock_urlopen.call_args.args[0].data)
    assert sent["input"] == ["one chunk"], "single input must still be wrapped in a list"
