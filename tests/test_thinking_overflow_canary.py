"""Tests for the thinking-budget-overflow canary in scripts/llm.py.

The canary surfaces silent failures shaped like the 2026-05 teacher run,
where thinking-model responses filled max_tokens with reasoning prose and
never emitted JSON. parse_json_response returned [] and the pipeline
treated it as "no concepts matched."
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from llm import _looks_like_thinking_overflow, parse_json_response  # noqa: E402


# ── _looks_like_thinking_overflow heuristic ──────────────────────────────────


def test_short_response_is_not_overflow():
    """Below the length floor, even a missing bracket is not a budget issue."""
    assert _looks_like_thinking_overflow("Thinking Process: nothing here") is False


def test_long_clean_response_is_not_overflow():
    """A long response that closes its array is fine, marker or not."""
    body = "Thinking Process: " + "x" * 6000 + "\n[]"
    assert _looks_like_thinking_overflow(body) is False


def test_long_without_marker_is_not_overflow():
    """No reasoning markers → don't fire the canary; could be any other shape."""
    body = "x" * 6000  # no brackets, no markers
    assert _looks_like_thinking_overflow(body) is False


def test_long_thinking_no_close_fires():
    """The classic 2026-05 shape: long, marker, no closing bracket."""
    body = "Thinking Process:\n\n1. Analyze the Request\n" + "x" * 6000
    assert _looks_like_thinking_overflow(body) is True


def test_marker_at_tail_also_fires():
    """The model's final list may appear near the end after a long prelude."""
    body = "x" * 6000 + "\nFinal list:\n1. foo (2)\n2. bar (1)"
    assert _looks_like_thinking_overflow(body) is True


# ── canary integration with parse_json_response ──────────────────────────────


def test_parse_emits_warning_on_thinking_overflow(caplog):
    """A real-shape thinking overflow returns [] AND emits a warning."""
    raw = "Thinking Process:\n\n1. Analyze the Request\n" + ("x" * 6000)
    with caplog.at_level(logging.WARNING, logger="llm"):
        result = parse_json_response(raw)
    assert result == []
    assert any("thinking-budget overflow" in r.message for r in caplog.records)


def test_parse_silent_on_legitimate_empty_array(caplog):
    """An honest [] response must not trigger the canary."""
    with caplog.at_level(logging.WARNING, logger="llm"):
        result = parse_json_response("[]")
    assert result == []
    assert not any("thinking-budget overflow" in r.message for r in caplog.records)


def test_parse_silent_on_short_failure(caplog):
    """A short malformed response is a parse failure, not a budget overflow."""
    with caplog.at_level(logging.WARNING, logger="llm"):
        result = parse_json_response("not even close to JSON")
    assert result == []
    assert not any("thinking-budget overflow" in r.message for r in caplog.records)
