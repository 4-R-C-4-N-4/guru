"""tests/test_propose_edges_negatives.py — Phase 0.1 negative persistence.

The footgun this exists for: idx_staged_edges_provenance_unique is partial on
status='pending', so rows written straight to status='rejected' bypass it and
a re-run could silently duplicate them — quiet, cumulative, and polluting the
training set the negatives are persisted for. v3_010 adds a sentinel-scoped
unique index; the double-run tests here are the proof it closes the gap.

Also pins the semantics agreed in the edge roadmap:
  - model negatives never appear in the review queue (status='pending' filter)
  - a curated rejection and a model negative may coexist for the same
    (pair, model, prompt_version) — the index is sentinel-scoped, not a
    widening over all rejected rows
  - presentation_order records the presented order relative to canonical
  - edge_progress marking is idempotent
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from propose_edges import (  # noqa: E402
    MODEL_NEGATIVE,
    insert_model_negative,
    mark_edge_progress,
    upsert_staged_edge,
)

MIGRATION_V3_010 = PROJECT_ROOT / "scripts" / "migrations" / "v3_010_model_negative_dedup.sql"

# Live-shape staged_edges: v3_005 table + v3_009 columns.
SCHEMA = """
CREATE TABLE nodes (
    id   TEXT PRIMARY KEY,
    type TEXT NOT NULL
);
CREATE TABLE staged_edges (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_chunk    TEXT NOT NULL REFERENCES nodes(id),
    target_chunk    TEXT NOT NULL REFERENCES nodes(id),
    edge_type       TEXT NOT NULL CHECK(edge_type IN ('PARALLELS','CONTRASTS','surface_only','unrelated')),
    confidence      REAL NOT NULL DEFAULT 0.0,
    justification   TEXT,
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending','accepted','rejected','reclassified')),
    tier            TEXT NOT NULL DEFAULT 'proposed'
                        CHECK(tier IN ('verified','proposed')),
    reviewed_by     TEXT,
    reviewed_at     TEXT,
    model           TEXT,
    prompt_version  TEXT,
    similarity      REAL,
    presentation_order TEXT CHECK(presentation_order IN ('ab','ba'))
);
CREATE UNIQUE INDEX idx_staged_edges_provenance_unique
    ON staged_edges(source_chunk, target_chunk, model, prompt_version)
    WHERE status = 'pending';
CREATE TABLE edge_progress (
    chunk_id        TEXT PRIMARY KEY REFERENCES nodes(id),
    model           TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    completed_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
"""


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.executescript(SCHEMA)
    # Apply v3_010 minus the sqlite3-CLI dot-commands.
    sql = "\n".join(
        line for line in MIGRATION_V3_010.read_text().splitlines()
        if not line.startswith(".")
    )
    c.executescript(sql)
    for cid in ("trad_a.text1.001", "trad_b.text2.001"):
        c.execute("INSERT INTO nodes(id, type) VALUES(?, 'chunk')", (cid,))
    yield c
    c.close()


A = "trad_a.text1.001"
B = "trad_b.text2.001"
M = "test-model.gguf"
V = "v2"


def negative_rows(conn):
    return conn.execute(
        "SELECT * FROM staged_edges WHERE status='rejected' AND reviewed_by=?",
        (MODEL_NEGATIVE,),
    ).fetchall()


def test_double_run_does_not_duplicate_negatives(conn):
    """THE footgun: rejected-on-arrival rows bypass the pending-only index."""
    for _ in range(3):
        insert_model_negative(conn, A, B, "unrelated", 0.9, "no link", M, V,
                              similarity=0.71)
    assert len(negative_rows(conn)) == 1


def test_double_run_does_not_duplicate_negatives_order_swapped(conn):
    """pair_key canonicalises, so B→A on a later sweep is the same pair."""
    insert_model_negative(conn, A, B, "unrelated", 0.9, "no link", M, V)
    insert_model_negative(conn, B, A, "surface_only", 0.8, "shared word", M, V)
    assert len(negative_rows(conn)) == 1


def test_pending_double_run_still_deduped(conn):
    for _ in range(2):
        upsert_staged_edge(conn, A, B, "PARALLELS", 0.85, "same insight", M, V,
                           similarity=0.80)
    rows = conn.execute(
        "SELECT * FROM staged_edges WHERE status='pending'").fetchall()
    assert len(rows) == 1


def test_negative_invisible_to_review_queue(conn):
    """The review app filters status='pending' everywhere; apply refuses
    non-pending. A model negative must never surface there."""
    insert_model_negative(conn, A, B, "unrelated", 0.9, "no link", M, V)
    pending = conn.execute(
        "SELECT COUNT(*) FROM staged_edges WHERE status='pending'"
    ).fetchone()[0]
    assert pending == 0


def test_curated_rejection_coexists_with_model_negative(conn):
    """The v3_010 index is sentinel-scoped, not a widening over all rejected
    rows — curated history and a model negative may share (pair, model, v)."""
    conn.execute(
        """INSERT INTO staged_edges
               (source_chunk, target_chunk, edge_type, status,
                reviewed_by, model, prompt_version)
           VALUES(?,?,?,'rejected','agent-claude',?,?)""",
        (A, B, "surface_only", M, V),
    )
    insert_model_negative(conn, A, B, "unrelated", 0.9, "no link", M, V)
    rejected = conn.execute(
        "SELECT COUNT(*) FROM staged_edges WHERE status='rejected'"
    ).fetchone()[0]
    assert rejected == 2


def test_presentation_order_recorded(conn):
    """A < B canonically: presenting A first is 'ab', B first is 'ba'."""
    insert_model_negative(conn, A, B, "unrelated", 0.9, "", M, V)
    assert conn.execute(
        "SELECT presentation_order FROM staged_edges").fetchone()[0] == "ab"
    conn.execute("DELETE FROM staged_edges")
    insert_model_negative(conn, B, A, "unrelated", 0.9, "", M, V)
    assert conn.execute(
        "SELECT presentation_order FROM staged_edges").fetchone()[0] == "ba"


def test_negative_carries_provenance(conn):
    insert_model_negative(conn, A, B, "surface_only", 0.7, "shared word", M, V,
                          similarity=0.66)
    row = conn.execute(
        """SELECT edge_type, confidence, similarity, model, prompt_version,
                  reviewed_at IS NOT NULL
           FROM staged_edges""").fetchone()
    assert row == ("surface_only", 0.7, 0.66, M, V, 1)


def test_edge_progress_idempotent(conn):
    for _ in range(2):
        mark_edge_progress(conn, A, M, V)
    rows = conn.execute("SELECT chunk_id, model FROM edge_progress").fetchall()
    assert rows == [(A, M)]
