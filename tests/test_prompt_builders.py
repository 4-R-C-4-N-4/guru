"""Regression tests for LLM-prompt builders (todo:11e80be4).

Two scripts had silent body truncations baked into their prompt builders:
  - scripts/propose_edges.py:build_pair_prompt — body[:600]
  - scripts/tag_concepts.py:build_prompt        — chunk_body[:1200]

At the live corpus distribution (median 2,660 chars, p99 3,825), 76-85%
of chunks were truncated and the LLM was making judgments on partial
content with no operator signal. The fix drops the slices and exposes
an optional --max-body-chars flag for future tightening.

These tests assert:
  1. A 5,000-char body survives the prompt builder verbatim (default).
  2. The optional max_body_chars cap clips when set.
  3. Setting max_body_chars=0 / None is treated as unlimited.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from propose_edges import build_pair_prompt  # noqa: E402
from tag_concepts import build_prompt  # noqa: E402


# A long body — easily exceeds the 600/1200 caps that used to be hardcoded.
LONG_BODY_A = "alpha " * 1000   # 6000 chars
LONG_BODY_B = "bravo " * 1000   # 6000 chars
LONG_CHUNK_BODY = "delta " * 1000  # 6000 chars

CONCEPTS = [
    {"id": "gnosis", "definition": "direct experiential knowledge"},
    {"id": "kenoma", "definition": "world of becoming"},
]


# ── propose_edges: build_pair_prompt ───────────────────────────────────


def test_pair_prompt_passes_full_body_by_default() -> None:
    """The default builder must NOT truncate. Both passages survive verbatim."""
    chunk_a = {"citation": "Tradition A — Section 1", "body": LONG_BODY_A}
    chunk_b = {"citation": "Tradition B — Section 1", "body": LONG_BODY_B}
    prompt = build_pair_prompt(chunk_a, chunk_b)
    assert LONG_BODY_A in prompt, "passage A's full body must appear in the prompt"
    assert LONG_BODY_B in prompt, "passage B's full body must appear in the prompt"
    # And no sneaky truncation: the body lengths in the prompt match the inputs.
    assert prompt.count("alpha ") == 1000
    assert prompt.count("bravo ") == 1000


def test_pair_prompt_max_body_chars_clips_when_set() -> None:
    chunk_a = {"citation": "A", "body": LONG_BODY_A}
    chunk_b = {"citation": "B", "body": LONG_BODY_B}
    prompt = build_pair_prompt(chunk_a, chunk_b, max_body_chars=500)
    # 500 chars of "alpha " (each 6 chars) = ~83 occurrences before the
    # cap mid-token. Easier assertion: the full 1000-occurrence body
    # is no longer present.
    assert LONG_BODY_A not in prompt
    assert LONG_BODY_B not in prompt
    # And the prompt is bounded near 2 × 500 chars body content.
    assert prompt.count("alpha ") < 100
    assert prompt.count("bravo ") < 100


def test_pair_prompt_max_body_chars_zero_is_unlimited() -> None:
    """0 (the CLI's default) is treated as 'no cap', matching None."""
    chunk_a = {"citation": "A", "body": LONG_BODY_A}
    chunk_b = {"citation": "B", "body": LONG_BODY_B}
    prompt_default = build_pair_prompt(chunk_a, chunk_b)
    prompt_zero = build_pair_prompt(chunk_a, chunk_b, max_body_chars=0)
    assert prompt_default == prompt_zero


# ── tag_concepts: build_prompt ─────────────────────────────────────────


def test_concept_prompt_passes_full_body_by_default() -> None:
    """The default builder must NOT truncate the chunk body."""
    prompt = build_prompt(LONG_CHUNK_BODY, "Some Citation", CONCEPTS)
    assert LONG_CHUNK_BODY in prompt, "full chunk body must appear in the prompt"
    assert prompt.count("delta ") == 1000


def test_concept_prompt_max_body_chars_clips_when_set() -> None:
    prompt = build_prompt(LONG_CHUNK_BODY, "X", CONCEPTS, max_body_chars=500)
    assert LONG_CHUNK_BODY not in prompt
    assert prompt.count("delta ") < 100


def test_concept_prompt_max_body_chars_zero_is_unlimited() -> None:
    prompt_default = build_prompt(LONG_CHUNK_BODY, "X", CONCEPTS)
    prompt_zero = build_prompt(LONG_CHUNK_BODY, "X", CONCEPTS, max_body_chars=0)
    assert prompt_default == prompt_zero


# ── direct regression catches against the old hardcoded numbers ───────


def test_pair_prompt_no_hardcoded_600() -> None:
    """If anyone re-introduces body[:600] the test above already catches
    it; this is an extra sanity check that a body of exactly 5,000 chars
    survives — which would be impossible under any cap < 5,000."""
    body = "x" * 5000
    chunk_a = {"citation": "A", "body": body}
    chunk_b = {"citation": "B", "body": body}
    prompt = build_pair_prompt(chunk_a, chunk_b)
    assert prompt.count("x" * 5000) == 2  # one for A, one for B


def test_concept_prompt_no_hardcoded_1200() -> None:
    body = "y" * 5000
    prompt = build_prompt(body, "X", CONCEPTS)
    assert "y" * 5000 in prompt
