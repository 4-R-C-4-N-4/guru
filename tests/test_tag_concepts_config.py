"""Regression test for the LLM token budget in tag_concepts.

The 2026-05-15 → 2026-05-21 teacher run used max_tokens=6000 and lost ~12%
of chunks to thinking-budget overflow that surfaced as silent zero-tag
results. This pins the budget high enough to give thinking models room to
finish reasoning before emitting JSON.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import tag_concepts  # noqa: E402


def test_llm_max_tokens_has_thinking_budget():
    """Must leave room for ~4-6k tokens of reasoning preamble plus the JSON
    answer. 16k is the floor below which dense chunks risk silent overflow."""
    assert tag_concepts.LLM_MAX_TOKENS >= 16000, (
        f"LLM_MAX_TOKENS={tag_concepts.LLM_MAX_TOKENS} is too low to "
        f"accommodate a thinking model's reasoning preamble. Raising this "
        f"floor masks the 2026-05 silent-overflow regression."
    )


def test_resume_is_on_by_default():
    """--resume (skip chunks already in tagging_progress) defaults ON, so a
    re-run only tags never-seen chunks and won't redo or clobber prior work;
    --no-resume opts into a full re-tag. todo:ac43aca4."""
    parser = tag_concepts.build_parser()
    assert parser.parse_args([]).resume is True
    assert parser.parse_args(["--no-resume"]).resume is False
    assert parser.parse_args(["--resume"]).resume is True
