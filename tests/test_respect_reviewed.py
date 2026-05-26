"""Coverage for the persistence-layer policy flags on upsert_staged_tag.

Two flags, both off by default at the function level (CLI sets them on):

  respect_reviewed   — skip insert if any prior row for
                       (chunk_id, concept_id, model) has status != 'pending'.
                       Scope is same-model; different models always emit.

  supersede_pending  — delete any prior pending row for
                       (chunk_id, concept_id, model) inside the same transaction
                       before inserting. Latest-pending wins.

These flags exist so that re-running the teacher against an expanded taxonomy
does not force the reviewer to re-adjudicate cells they have already decided.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT))
from tag_concepts import upsert_staged_tag  # noqa: E402
from guru.prompt import PROMPT_VERSION  # noqa: E402


def _seed_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE nodes (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL CHECK(type IN ('tradition','concept','chunk')),
            tradition_id TEXT REFERENCES nodes(id),
            label TEXT NOT NULL,
            definition TEXT,
            metadata_json TEXT DEFAULT '{}'
        );
        CREATE TABLE staged_tags (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            chunk_id        TEXT NOT NULL REFERENCES nodes(id),
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
        INSERT INTO nodes(id, type, label) VALUES ('gnosticism', 'tradition', 'Gnosticism');
        INSERT INTO nodes(id, type, tradition_id, label)
            VALUES ('gnosticism.gospel-of-thomas.001', 'chunk', 'gnosticism', 'Logion 1');
    """)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    _seed_schema(c)
    yield c
    c.close()


CHUNK = "gnosticism.gospel-of-thomas.001"
MODEL = "qwen3.5-27b"


def _tag(concept_id: str, score: int) -> dict:
    return {
        "concept_id": concept_id,
        "score": score,
        "justification": f"test for {concept_id}",
        "is_new_concept": False,
        "new_concept_def": None,
    }


def _seed_prior(conn: sqlite3.Connection, concept: str, score: int,
                status: str, model: str = MODEL,
                prompt_version: str = "v1") -> None:
    """Insert a row directly with the given status, bypassing upsert."""
    conn.execute(
        """INSERT INTO staged_tags
               (chunk_id, concept_id, score, justification, is_new_concept,
                model, prompt_version, status)
           VALUES (?, ?, ?, 'prior', 0, ?, ?, ?)""",
        (CHUNK, concept, score, model, prompt_version, status),
    )


# ── respect_reviewed ──────────────────────────────────────────────────


@pytest.mark.parametrize("status", ["accepted", "rejected", "reassigned"])
def test_respect_reviewed_skips_when_prior_is_human_touched(
    conn: sqlite3.Connection, status: str,
) -> None:
    """Any non-pending status from the same model means a human decided.
    Filter on the negation, not an allowlist, so future statuses inherit
    the right behavior."""
    _seed_prior(conn, "gnosis", score=3, status=status)
    outcome = upsert_staged_tag(
        conn, CHUNK, _tag("gnosis", 2), model=MODEL,
        respect_reviewed=True,
    )
    assert outcome == "skipped_reviewed"
    rows = conn.execute(
        "SELECT status, score FROM staged_tags WHERE concept_id='gnosis'"
    ).fetchall()
    assert rows == [(status, 3)], "no new row should land"


def test_respect_reviewed_emits_for_different_model(conn: sqlite3.Connection) -> None:
    """A human's rejection of model A's tag was based on model A's justification;
    a different model's proposal of the same pair deserves a fresh look."""
    _seed_prior(conn, "gnosis", score=3, status="rejected", model="qwen3.5-27b")
    outcome = upsert_staged_tag(
        conn, CHUNK, _tag("gnosis", 2), model="student-v1",
        respect_reviewed=True,
    )
    assert outcome == "inserted"
    rows = conn.execute(
        "SELECT model, status FROM staged_tags WHERE concept_id='gnosis' ORDER BY id"
    ).fetchall()
    assert rows == [("qwen3.5-27b", "rejected"), ("student-v1", "pending")]


def test_respect_reviewed_emits_when_only_prior_is_pending(
    conn: sqlite3.Connection,
) -> None:
    """A pending prior was not adjudicated by a human; the filter must not
    suppress fresher pending output."""
    _seed_prior(conn, "gnosis", score=1, status="pending", prompt_version="v0")
    outcome = upsert_staged_tag(
        conn, CHUNK, _tag("gnosis", 3), model=MODEL,
        respect_reviewed=True,
        supersede_pending=False,
    )
    assert outcome == "inserted"


def test_respect_reviewed_off_inserts_alongside_accepted(
    conn: sqlite3.Connection,
) -> None:
    """Default function-level behavior is unchanged when the flag is off."""
    _seed_prior(conn, "gnosis", score=3, status="accepted")
    outcome = upsert_staged_tag(
        conn, CHUNK, _tag("gnosis", 1), model=MODEL,
        respect_reviewed=False,
    )
    assert outcome == "inserted"
    rows = conn.execute(
        "SELECT status, score FROM staged_tags WHERE concept_id='gnosis' ORDER BY id"
    ).fetchall()
    assert rows == [("accepted", 3), ("pending", 1)]


# ── supersede_pending ─────────────────────────────────────────────────


def test_supersede_pending_replaces_old_pending_row(conn: sqlite3.Connection) -> None:
    """Old pending row is deleted in the same transaction; new pending lands."""
    _seed_prior(conn, "gnosis", score=1, status="pending", prompt_version="v0")
    outcome = upsert_staged_tag(
        conn, CHUNK, _tag("gnosis", 3), model=MODEL,
        supersede_pending=True,
    )
    assert outcome == "superseded"
    rows = conn.execute(
        "SELECT score, prompt_version, status FROM staged_tags WHERE concept_id='gnosis'"
    ).fetchall()
    assert rows == [(3, PROMPT_VERSION, "pending")], "old pending replaced by new pending"


def test_supersede_pending_scoped_to_same_model(conn: sqlite3.Connection) -> None:
    """Different-model pending row must not be deleted by a supersede."""
    _seed_prior(conn, "gnosis", score=1, status="pending", model="qwen3.5-27b")
    outcome = upsert_staged_tag(
        conn, CHUNK, _tag("gnosis", 3), model="student-v1",
        supersede_pending=True,
    )
    assert outcome == "inserted"
    rows = conn.execute(
        "SELECT model, score FROM staged_tags WHERE concept_id='gnosis' ORDER BY id"
    ).fetchall()
    assert rows == [("qwen3.5-27b", 1), ("student-v1", 3)]


def test_supersede_pending_does_not_touch_non_pending_rows(
    conn: sqlite3.Connection,
) -> None:
    """Accepted/rejected/reassigned rows are settled audit history; supersede
    must only target pending."""
    _seed_prior(conn, "gnosis", score=3, status="accepted")
    outcome = upsert_staged_tag(
        conn, CHUNK, _tag("gnosis", 1), model=MODEL,
        supersede_pending=True,
    )
    assert outcome == "inserted"
    rows = conn.execute(
        "SELECT status, score FROM staged_tags WHERE concept_id='gnosis' ORDER BY id"
    ).fetchall()
    assert rows == [("accepted", 3), ("pending", 1)]


# ── interaction ───────────────────────────────────────────────────────


def test_respect_reviewed_wins_over_supersede_pending(
    conn: sqlite3.Connection,
) -> None:
    """When both an accepted and a pending row exist for the same triple,
    respect_reviewed must short-circuit before supersede touches the pending row.
    The accepted verdict is authoritative; the pending row stays untouched."""
    _seed_prior(conn, "gnosis", score=3, status="accepted")
    _seed_prior(conn, "gnosis", score=1, status="pending", prompt_version="v0")
    outcome = upsert_staged_tag(
        conn, CHUNK, _tag("gnosis", 2), model=MODEL,
        respect_reviewed=True,
        supersede_pending=True,
    )
    assert outcome == "skipped_reviewed"
    rows = conn.execute(
        "SELECT status, score FROM staged_tags WHERE concept_id='gnosis' ORDER BY id"
    ).fetchall()
    assert rows == [("accepted", 3), ("pending", 1)], (
        "no row should be deleted, no row should be inserted"
    )
