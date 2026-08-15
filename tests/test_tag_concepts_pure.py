"""Tests for the DB-free per-chunk tagging function and the single writer
that applies its results (todo:6950de58).

tag_one_chunk() does everything from resolving the chunk body through
parse_tags with no sqlite connection and never raises — errors come back on
the result instead, which is what makes it safe to call concurrently (the
concurrency itself lands in todo:0c34642e). apply_chunk_result() is the only
function that writes: it's exercised here as the thing a caller drives once
per result, in any order, to prove the split preserves the original
outcome-counter semantics.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT))

import tag_concepts  # noqa: E402
from tag_concepts import ChunkTagResult, apply_chunk_result, tag_one_chunk  # noqa: E402
from guru.prompt import PROMPT_VERSION  # noqa: E402


CONCEPTS = [{"id": "gnosis", "definition": "direct experiential knowledge"}]


def _chunk(chunk_id: str = "gnosticism.gospel-of-thomas.001") -> dict:
    # chunk_id deliberately does not resolve to a real corpus file (no
    # corpus/gnosticism/gospel-of-thomas/chunks/001.toml in the test tree),
    # so tag_one_chunk falls back to chunk["label"] as the body — same
    # fallback path get_chunks/run_tagging always had for a missing file.
    return {"id": chunk_id, "label": f"label:{chunk_id}", "meta": {}}


# ── tag_one_chunk ────────────────────────────────────────────────────────────


def test_tag_one_chunk_success(monkeypatch):
    calls = []

    def fake_call_llm(provider, model, system, prompt, max_tokens):
        calls.append((provider, model, max_tokens))
        return '[{"concept_id": "gnosis", "score": 3, "justification": "x"}]'

    monkeypatch.setattr(tag_concepts, "call_llm", fake_call_llm)

    result = tag_one_chunk(_chunk(), CONCEPTS, "llamacpp", "test-model")

    assert isinstance(result, ChunkTagResult)
    assert result.error is None
    assert result.chunk_id == "gnosticism.gospel-of-thomas.001"
    assert result.tags == [{
        "concept_id": "gnosis",
        "score": 3,
        "justification": "x",
        "is_new_concept": False,
        "new_concept_def": None,
    }]
    # provider/model/max_tokens are threaded through unchanged
    assert calls == [("llamacpp", "test-model", tag_concepts.LLM_MAX_TOKENS)]


def test_tag_one_chunk_parse_failure_yields_empty_tags_not_error(monkeypatch):
    """A response that doesn't parse as JSON is parse_tags' problem (it
    returns []), not an exception — the chunk is still 'done', just with no
    tags, exactly as the serial code always treated it."""
    monkeypatch.setattr(tag_concepts, "call_llm", lambda *a, **k: "not json at all")

    result = tag_one_chunk(_chunk(), CONCEPTS, "llamacpp", "test-model")

    assert result.error is None
    assert result.tags == []


def test_tag_one_chunk_llm_error_is_captured_not_raised(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(tag_concepts, "call_llm", boom)

    result = tag_one_chunk(_chunk("x.y.001"), CONCEPTS, "llamacpp", "test-model")

    assert result.chunk_id == "x.y.001"
    assert result.tags == []
    assert isinstance(result.error, RuntimeError)
    assert "connection refused" in str(result.error)


def test_tag_one_chunk_never_raises_and_is_pure(monkeypatch):
    """No sqlite connection is touched or required — the function's
    signature accepts none, and it must not import/open one implicitly."""

    def boom(*a, **k):
        raise ValueError("anything")

    monkeypatch.setattr(tag_concepts, "call_llm", boom)
    # Should not raise even though call_llm blows up.
    result = tag_one_chunk(_chunk(), CONCEPTS, "llamacpp", "m")
    assert result.error is not None


def test_tag_one_chunk_respects_max_body_chars(monkeypatch):
    """max_body_chars must be threaded through to build_prompt unchanged —
    verified at the plumbing level (build_prompt itself already truncates;
    see build_prompt's own tests for that behaviour)."""
    seen = {}

    def fake_build_prompt(body, citation, concepts, max_body_chars=None):
        seen["max_body_chars"] = max_body_chars
        return "prompt"

    monkeypatch.setattr(tag_concepts, "build_prompt", fake_build_prompt)
    monkeypatch.setattr(tag_concepts, "call_llm", lambda *a, **k: "[]")

    tag_one_chunk(_chunk(), CONCEPTS, "llamacpp", "m", max_body_chars=10)

    assert seen["max_body_chars"] == 10


# ── apply_chunk_result (the single writer) ───────────────────────────────────


def _seed_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE nodes (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            tradition_id TEXT,
            label TEXT NOT NULL,
            metadata_json TEXT DEFAULT '{}'
        );
        CREATE TABLE staged_tags (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            chunk_id        TEXT NOT NULL,
            concept_id      TEXT NOT NULL,
            score           INTEGER NOT NULL CHECK(score BETWEEN 0 AND 3),
            justification   TEXT,
            is_new_concept  INTEGER NOT NULL DEFAULT 0,
            new_concept_def TEXT,
            status          TEXT NOT NULL DEFAULT 'pending'
                                CHECK(status IN ('pending','accepted','rejected','reassigned')),
            reviewed_by     TEXT,
            reviewed_at     TEXT,
            model           TEXT,
            prompt_version  TEXT
        );
        CREATE UNIQUE INDEX idx_staged_tags_provenance_unique
            ON staged_tags(chunk_id, concept_id, model, prompt_version)
            WHERE status='pending';
        CREATE TABLE tagging_progress (chunk_id TEXT PRIMARY KEY);
        INSERT INTO nodes(id, type, label) VALUES ('t', 'tradition', 'T');
        INSERT INTO nodes(id, type, tradition_id, label) VALUES ('t.x.001', 'chunk', 't', 'C1');
        INSERT INTO nodes(id, type, tradition_id, label) VALUES ('t.x.002', 'chunk', 't', 'C2');
    """)
    return conn


def _tag(concept_id: str, score: int = 2) -> dict:
    return {
        "concept_id": concept_id,
        "score": score,
        "justification": "j",
        "is_new_concept": False,
        "new_concept_def": None,
    }


def test_apply_chunk_result_writes_tags_and_marks_complete():
    conn = _seed_db()
    outcomes = {"inserted": 0, "superseded": 0, "skipped_reviewed": 0, "conflict": 0}
    result = ChunkTagResult(chunk_id="t.x.001", tags=[_tag("gnosis"), _tag("light")])

    apply_chunk_result(conn, result, model="m", respect_reviewed=True,
                       supersede_pending=True, outcomes=outcomes)

    rows = conn.execute(
        "SELECT chunk_id, concept_id, model, prompt_version FROM staged_tags ORDER BY id"
    ).fetchall()
    assert rows == [
        ("t.x.001", "gnosis", "m", PROMPT_VERSION),
        ("t.x.001", "light", "m", PROMPT_VERSION),
    ]
    assert conn.execute(
        "SELECT chunk_id FROM tagging_progress"
    ).fetchall() == [("t.x.001",)]
    assert outcomes["inserted"] == 2


def test_apply_chunk_result_marks_complete_even_with_zero_tags():
    """An LLM legitimately returning no tags still completes the chunk —
    matches original run_tagging behaviour (mark_complete always ran on the
    non-error path, regardless of len(tags))."""
    conn = _seed_db()
    outcomes = {"inserted": 0, "superseded": 0, "skipped_reviewed": 0, "conflict": 0}
    result = ChunkTagResult(chunk_id="t.x.001", tags=[])

    apply_chunk_result(conn, result, model="m", respect_reviewed=True,
                       supersede_pending=True, outcomes=outcomes)

    assert conn.execute("SELECT COUNT(*) FROM staged_tags").fetchone() == (0,)
    assert conn.execute("SELECT chunk_id FROM tagging_progress").fetchall() == [("t.x.001",)]


def test_apply_chunk_result_accumulates_outcomes_across_multiple_results():
    """Driving apply_chunk_result once per result (the shape both the serial
    loop and the future pool writer use) must accumulate into one shared
    outcomes dict, in whatever order results arrive."""
    conn = _seed_db()
    outcomes = {"inserted": 0, "superseded": 0, "skipped_reviewed": 0, "conflict": 0}

    results = [
        ChunkTagResult(chunk_id="t.x.002", tags=[_tag("gnosis")]),
        ChunkTagResult(chunk_id="t.x.001", tags=[_tag("gnosis"), _tag("light")]),
    ]
    # Apply out of the chunks' natural id order — the writer must not care.
    for r in results:
        apply_chunk_result(conn, r, model="m", respect_reviewed=True,
                           supersede_pending=True, outcomes=outcomes)

    assert outcomes["inserted"] == 3
    completed = {r[0] for r in conn.execute("SELECT chunk_id FROM tagging_progress")}
    assert completed == {"t.x.001", "t.x.002"}


def test_apply_chunk_result_conflict_outcome_counted():
    conn = _seed_db()
    outcomes = {"inserted": 0, "superseded": 0, "skipped_reviewed": 0, "conflict": 0}
    result = ChunkTagResult(chunk_id="t.x.001", tags=[_tag("gnosis")])

    apply_chunk_result(conn, result, model="m", respect_reviewed=True,
                       supersede_pending=False, outcomes=outcomes)
    # Re-apply identical provenance with supersede off -> ON CONFLICT DO NOTHING
    apply_chunk_result(conn, result, model="m", respect_reviewed=True,
                       supersede_pending=False, outcomes=outcomes)

    assert outcomes["inserted"] == 1
    assert outcomes["conflict"] == 1
