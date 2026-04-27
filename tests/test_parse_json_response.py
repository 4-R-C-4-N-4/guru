"""tests/test_parse_json_response.py — robustness of LLM JSON extraction.

Regression tests for two issues:

  a46658be: parse_json_response anchored on '\\[.*' which mangled top-level
    JSON objects (the inner '[' of any array field would be greedily picked
    up as the start of the response). Now matches '[' or '{' at the first
    bracket-like character.

  7676537c: dead 'and not escape_next' check on the quote branch — at that
    point escape_next has already been reset two lines up. Removed.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from llm import parse_json_response  # noqa: E402


def test_top_level_object_parses():
    assert parse_json_response('{"a": 1, "b": [2, 3]}') == {"a": 1, "b": [2, 3]}


def test_top_level_array_parses():
    assert parse_json_response('[{"a": 1}, {"b": 2}]') == [{"a": 1}, {"b": 2}]


def test_object_with_inner_array_not_mangled():
    """Pre-fix: re.search(r'\\[.*') matched the inner '[' and replaced raw
    with '[2, 3]}', which is invalid JSON, returning [] instead of the
    original object."""
    raw = '{"results": [2, 3], "ok": true}'
    assert parse_json_response(raw) == {"results": [2, 3], "ok": True}


def test_thinking_preamble_before_object():
    raw = "Here is your answer:\n\n{\"a\": 1}\n"
    assert parse_json_response(raw) == {"a": 1}


def test_thinking_preamble_before_array():
    raw = "Sure! Here it is:\n[{\"a\": 1}]"
    assert parse_json_response(raw) == [{"a": 1}]


def test_markdown_fence_with_object():
    raw = '```json\n{"a": 1}\n```'
    assert parse_json_response(raw) == {"a": 1}


def test_markdown_fence_with_array():
    raw = '```json\n[{"a": 1}]\n```'
    assert parse_json_response(raw) == [{"a": 1}]


def test_truncated_array_repaired():
    """Common thinking-model failure mode: ran out of tokens mid-array.
    Repair should keep the complete objects."""
    raw = '[{"a": 1}, {"b": 2}, {"c":'
    out = parse_json_response(raw)
    assert out == [{"a": 1}, {"b": 2}]


def test_truncated_object_returns_empty():
    """We don't try to repair truncated objects — caller should bump
    max_tokens. Returning [] preserves the previous fail-soft contract."""
    raw = '{"a": 1, "b": {"nested":'
    assert parse_json_response(raw) == []


def test_empty_input_returns_empty():
    assert parse_json_response("") == []
    assert parse_json_response("   ") == []


def test_quote_inside_string_does_not_break_repair():
    """The depth tracker must respect that an escaped quote does not toggle
    in_string. A previous incarnation of the loop had a dead `and not
    escape_next` guard that papered over the same intent; the loop now
    handles this directly."""
    raw = '[{"msg": "hello \\"world\\""}, {"msg": "ok"}, {"x":'
    out = parse_json_response(raw)
    assert out == [{"msg": 'hello "world"'}, {"msg": "ok"}]


def test_escaped_brace_inside_string_does_not_inflate_depth():
    raw = '[{"s": "} } }"}, {"s": "ok"}, {"trunc":'
    out = parse_json_response(raw)
    assert out == [{"s": "} } }"}, {"s": "ok"}]
