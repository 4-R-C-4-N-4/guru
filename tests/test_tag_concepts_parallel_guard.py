"""Tests for todo:5955d038 — guarding --parallel N>1 to the 4B finetune and
pre-flighting the llama.cpp server's actual slot count.

Two independent checks:
  check_parallel_model_guard — model-id policy, no network.
  preflight_server_slots     — HTTP query via llm.query_llamacpp_slots,
                                stubbed here with a fake urllib.request.urlopen.
                                No real sockets are opened anywhere in this file.
"""

from __future__ import annotations

import json
import sys
import urllib.error
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT))

import tag_concepts  # noqa: E402
import llm  # noqa: E402


# ── check_parallel_model_guard ───────────────────────────────────────────────


def test_guard_allows_parallel_1_for_any_model():
    tag_concepts.check_parallel_model_guard("Qwen3.5-27B-UD-Q4_K_XL.gguf", parallel=1)


def test_guard_accepts_the_finetune_model_id():
    tag_concepts.check_parallel_model_guard("qwen-3-4b-guru-v3-Q4_K_M.gguf", parallel=4)


def test_guard_accepts_a_future_finetune_infix():
    # -vN- varies by training run; the prefix is what's load-bearing.
    tag_concepts.check_parallel_model_guard("qwen-3-4b-guru-v7-Q8_0.gguf", parallel=8)


def test_guard_refuses_the_27b_teacher():
    with pytest.raises(tag_concepts.ParallelModelNotAllowedError, match="27B|think-on|qwen-3-4b-guru"):
        tag_concepts.check_parallel_model_guard("Qwen3.5-27B-UD-Q4_K_XL.gguf", parallel=4)


def test_guard_refuses_an_unrelated_model_id():
    with pytest.raises(tag_concepts.ParallelModelNotAllowedError):
        tag_concepts.check_parallel_model_guard("llama3", parallel=2)


def test_guard_override_bypasses_the_refusal():
    tag_concepts.check_parallel_model_guard(
        "Qwen3.5-27B-UD-Q4_K_XL.gguf", parallel=4, allow_parallel_any_model=True,
    )


def test_guard_is_wired_into_the_cli_parser():
    parser = tag_concepts.build_parser()
    assert parser.parse_args([]).allow_parallel_any_model is False
    assert parser.parse_args(["--allow-parallel-any-model"]).allow_parallel_any_model is True


# ── query_llamacpp_slots (llm.py) — stubbed HTTP, no sockets ────────────────


class _FakeHTTPResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _install_fake_urlopen(monkeypatch, by_path: dict[str, object]):
    """by_path maps a URL suffix ("/props", "/slots") to either:
      - a dict/list  -> served as a 200 JSON response
      - bytes        -> served as the raw response body
      - an Exception instance -> raised when that path is requested
    Any path not present in by_path raises URLError (connection refused).
    """

    def _fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        for suffix, spec in by_path.items():
            if url.endswith(suffix):
                if isinstance(spec, Exception):
                    raise spec
                if isinstance(spec, (bytes, bytearray)):
                    return _FakeHTTPResponse(bytes(spec))
                return _FakeHTTPResponse(json.dumps(spec).encode())
        raise urllib.error.URLError("connection refused (no stub for this path)")

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)


def test_query_slots_reads_total_slots_from_props(monkeypatch):
    _install_fake_urlopen(monkeypatch, {"/props": {"total_slots": 4}})
    assert llm.query_llamacpp_slots(base_url="http://fake:8080") == 4


def test_query_slots_reads_n_parallel_from_props(monkeypatch):
    _install_fake_urlopen(monkeypatch, {"/props": {"n_parallel": 2}})
    assert llm.query_llamacpp_slots(base_url="http://fake:8080") == 2


def test_query_slots_falls_back_to_slots_endpoint(monkeypatch):
    # /props exists but has neither key llama.cpp might use; /slots array
    # of 3 objects should still be counted.
    _install_fake_urlopen(monkeypatch, {
        "/props": {"model_path": "whatever"},
        "/slots": [{"id": 0}, {"id": 1}, {"id": 2}],
    })
    assert llm.query_llamacpp_slots(base_url="http://fake:8080") == 3


def test_query_slots_returns_none_when_both_endpoints_missing(monkeypatch):
    _install_fake_urlopen(monkeypatch, {})  # every request raises URLError
    assert llm.query_llamacpp_slots(base_url="http://fake:8080") is None


def test_query_slots_returns_none_on_malformed_json(monkeypatch):
    _install_fake_urlopen(monkeypatch, {"/props": b"not json at all", "/slots": b"also not json"})
    assert llm.query_llamacpp_slots(base_url="http://fake:8080") is None


def test_query_slots_returns_none_on_unrecognized_shape(monkeypatch):
    # Valid JSON, but neither the /props keys nor a non-empty /slots array.
    _install_fake_urlopen(monkeypatch, {"/props": {"chat_template": "..."}, "/slots": []})
    assert llm.query_llamacpp_slots(base_url="http://fake:8080") is None


# ── preflight_server_slots — the tag_concepts.py-level policy wrapper ───────


def test_preflight_ok_when_slots_cover_parallel(monkeypatch):
    _install_fake_urlopen(monkeypatch, {"/props": {"total_slots": 4}})
    tag_concepts.preflight_server_slots("llamacpp", parallel=4, base_url="http://fake:8080")


def test_preflight_refuses_when_slots_are_too_few(monkeypatch):
    _install_fake_urlopen(monkeypatch, {"/props": {"total_slots": 1}})
    with pytest.raises(tag_concepts.InsufficientServerSlotsError, match="1 slot"):
        tag_concepts.preflight_server_slots("llamacpp", parallel=4, base_url="http://fake:8080")


def test_preflight_warns_and_continues_when_endpoint_missing(monkeypatch, caplog):
    _install_fake_urlopen(monkeypatch, {})  # neither /props nor /slots reachable
    with caplog.at_level("WARNING"):
        tag_concepts.preflight_server_slots("llamacpp", parallel=4, base_url="http://fake:8080")
    assert any("could not determine" in r.message for r in caplog.records)


def test_preflight_warns_and_continues_on_malformed_response(monkeypatch, caplog):
    _install_fake_urlopen(monkeypatch, {"/props": b"garbage", "/slots": b"garbage"})
    with caplog.at_level("WARNING"):
        tag_concepts.preflight_server_slots("llamacpp", parallel=4, base_url="http://fake:8080")
    assert any("could not determine" in r.message for r in caplog.records)


def test_preflight_skips_non_llamacpp_providers(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("query_llamacpp_slots must not be called for a non-llamacpp provider")

    monkeypatch.setattr(tag_concepts, "query_llamacpp_slots", _boom)
    # Would refuse if it ever queried (no stub installed => URLError => None
    # => warn-and-continue anyway), but the point is it must never even ask.
    tag_concepts.preflight_server_slots("anthropic", parallel=4, base_url="http://fake:8080")
    tag_concepts.preflight_server_slots("ollama", parallel=4, base_url="http://fake:8080")


def test_preflight_skips_entirely_for_parallel_1(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("must not query slots when --parallel is 1")

    monkeypatch.setattr(tag_concepts, "query_llamacpp_slots", _boom)
    tag_concepts.preflight_server_slots("llamacpp", parallel=1, base_url="http://fake:8080")


# ── run_tagging wires both checks in before doing any work ─────────────────


def test_run_tagging_raises_model_guard_before_touching_the_db(monkeypatch, tmp_path):
    """A bogus db path proves the guard fires before sqlite3.connect — if it
    didn't, this would raise sqlite3.OperationalError instead."""
    monkeypatch.setattr(tag_concepts, "load_taxonomy", lambda: [])
    with pytest.raises(tag_concepts.ParallelModelNotAllowedError):
        tag_concepts.run_tagging(
            db_path=tmp_path / "does" / "not" / "exist.db",
            provider_name="llamacpp",
            model="Qwen3.5-27B-UD-Q4_K_XL.gguf",
            batch_size=0,
            resume=False,
            tradition=None,
            text_id=None,
            delay=0.0,
            parallel=4,
        )
