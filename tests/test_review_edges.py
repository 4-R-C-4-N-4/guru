"""Regression tests for review_edges.py editorial-overlay helpers (todo:90c79a3f).

Mirrors the structure of tests/test_promote_definition.py:
  - accept_edge writes verified + retains existing-edge upgrade
  - reject_edge DELETEs the live edge if any
  - reclassify_edge DELETEs the old-type edge then upserts new-type for
    PARALLELS / CONTRASTS, or routes through reject for surface_only /
    unrelated (typed reject path per docs/web-review/edges.md §4)
"""
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from review_edges import accept_edge, reject_edge, reclassify_edge  # noqa: E402


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
        CREATE TABLE edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL REFERENCES nodes(id),
            target_id TEXT NOT NULL REFERENCES nodes(id),
            type TEXT NOT NULL CHECK(type IN ('BELONGS_TO','EXPRESSES','PARALLELS','CONTRASTS','DERIVES_FROM')),
            tier TEXT NOT NULL DEFAULT 'inferred' CHECK(tier IN ('verified','proposed','inferred')),
            justification TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        );
        CREATE UNIQUE INDEX idx_edges_unique ON edges(source_id, target_id, type);
        CREATE TABLE staged_edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_chunk TEXT NOT NULL REFERENCES nodes(id),
            target_chunk TEXT NOT NULL REFERENCES nodes(id),
            edge_type TEXT NOT NULL CHECK(edge_type IN ('PARALLELS','CONTRASTS','surface_only','unrelated')),
            confidence REAL NOT NULL DEFAULT 0.0,
            justification TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','accepted','rejected','reclassified')),
            tier TEXT NOT NULL DEFAULT 'proposed'
                CHECK(tier IN ('verified','proposed')),
            reviewed_by TEXT,
            reviewed_at TEXT,
            UNIQUE(source_chunk, target_chunk)
        );
        INSERT INTO nodes(id, type, label) VALUES
            ('gnosticism', 'tradition', 'Gnosticism'),
            ('neoplatonism', 'tradition', 'Neoplatonism');
        INSERT INTO nodes(id, type, tradition_id, label) VALUES
            ('gnosticism.gospel-of-thomas.077', 'chunk', 'gnosticism', 'Logion 77'),
            ('neoplatonism.enneads.v.1.7', 'chunk', 'neoplatonism', 'Enneads V.1.7');
    """)


def _seed_staged(conn, *, edge_type="PARALLELS", confidence=0.85,
                 status="pending", tier="proposed") -> dict:
    """Insert a staged_edge and return the row as a dict shaped how the
    review loop hands it to the helpers (sqlite3.Row equivalent)."""
    cur = conn.execute(
        """INSERT INTO staged_edges(source_chunk, target_chunk, edge_type,
                                    confidence, justification, status, tier)
           VALUES(?,?,?,?,?,?,?)""",
        ("gnosticism.gospel-of-thomas.077", "neoplatonism.enneads.v.1.7",
         edge_type, confidence, "test justification", status, tier),
    )
    sid = cur.lastrowid
    return {
        "id": sid,
        "source_chunk": "gnosticism.gospel-of-thomas.077",
        "target_chunk": "neoplatonism.enneads.v.1.7",
        "edge_type": edge_type,
        "confidence": confidence,
        "justification": "test justification",
    }


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    _seed_schema(c)
    yield c
    c.close()


# ── accept_edge ────────────────────────────────────────────────────────


def test_accept_writes_verified_and_marks_status(conn):
    row = _seed_staged(conn)
    accept_edge(conn, row)

    edge = conn.execute(
        "SELECT tier, justification FROM edges "
        "WHERE source_id=? AND target_id=? AND type='PARALLELS'",
        (row["source_chunk"], row["target_chunk"]),
    ).fetchone()
    assert edge["tier"] == "verified"
    assert edge["justification"] == "test justification"

    staged = conn.execute(
        "SELECT status, tier FROM staged_edges WHERE id=?", (row["id"],)
    ).fetchone()
    assert (staged["status"], staged["tier"]) == ("accepted", "verified")


def test_accept_upgrades_pre_existing_proposed_edge(conn):
    """Auto-promote-edges (future) might write tier=proposed first.
    Accept upgrades that to verified via ON CONFLICT DO UPDATE."""
    row = _seed_staged(conn)
    conn.execute(
        "INSERT INTO edges(source_id, target_id, type, tier, justification) "
        "VALUES(?,?, 'PARALLELS', 'proposed', '[auto] model said it')",
        (row["source_chunk"], row["target_chunk"]),
    )
    accept_edge(conn, row)
    edge = conn.execute(
        "SELECT tier, justification FROM edges "
        "WHERE source_id=? AND target_id=? AND type='PARALLELS'",
        (row["source_chunk"], row["target_chunk"]),
    ).fetchone()
    assert edge["tier"] == "verified"
    assert edge["justification"] == "test justification"


# ── reject_edge ────────────────────────────────────────────────────────


def test_reject_with_no_existing_edge_is_safe(conn):
    row = _seed_staged(conn)
    reject_edge(conn, row)  # no live edge to delete — must not raise
    status = conn.execute(
        "SELECT status FROM staged_edges WHERE id=?", (row["id"],)
    ).fetchone()
    assert status["status"] == "rejected"


def test_reject_deletes_existing_live_edge(conn):
    row = _seed_staged(conn)
    # Pre-existing edge (e.g. an auto-promote that the curator now disagrees with)
    conn.execute(
        "INSERT INTO edges(source_id, target_id, type, tier, justification) "
        "VALUES(?,?, 'PARALLELS', 'proposed', '[auto] x')",
        (row["source_chunk"], row["target_chunk"]),
    )
    reject_edge(conn, row)
    edge = conn.execute(
        "SELECT * FROM edges WHERE source_id=? AND target_id=? AND type='PARALLELS'",
        (row["source_chunk"], row["target_chunk"]),
    ).fetchone()
    assert edge is None, "rejected edge must be deleted from edges table"


def test_reject_scoped_to_specific_edge_type(conn):
    """The DELETE filters on (source, target, edge_type). A different-type
    edge on the same chunk-pair must survive."""
    row = _seed_staged(conn, edge_type="PARALLELS")
    # Same chunk-pair, different edge type — should not be touched
    conn.execute(
        "INSERT INTO edges(source_id, target_id, type, tier, justification) "
        "VALUES(?,?, 'CONTRASTS', 'verified', 'unrelated curated')",
        (row["source_chunk"], row["target_chunk"]),
    )
    reject_edge(conn, row)
    survivors = conn.execute(
        "SELECT type FROM edges WHERE source_id=? AND target_id=?",
        (row["source_chunk"], row["target_chunk"]),
    ).fetchall()
    assert [r["type"] for r in survivors] == ["CONTRASTS"]


# ── reclassify_edge ────────────────────────────────────────────────────


def test_reclassify_parallels_to_contrasts_swaps_edge(conn):
    row = _seed_staged(conn, edge_type="PARALLELS")
    # Pre-existing PARALLELS edge from auto-promote
    conn.execute(
        "INSERT INTO edges(source_id, target_id, type, tier, justification) "
        "VALUES(?,?, 'PARALLELS', 'proposed', '[auto] wrong type')",
        (row["source_chunk"], row["target_chunk"]),
    )
    reclassify_edge(conn, row, "CONTRASTS")

    # Old-type gone
    old = conn.execute(
        "SELECT * FROM edges WHERE source_id=? AND target_id=? AND type='PARALLELS'",
        (row["source_chunk"], row["target_chunk"]),
    ).fetchone()
    assert old is None

    # New-type at verified
    new = conn.execute(
        "SELECT tier, justification FROM edges "
        "WHERE source_id=? AND target_id=? AND type='CONTRASTS'",
        (row["source_chunk"], row["target_chunk"]),
    ).fetchone()
    assert new["tier"] == "verified"
    assert new["justification"] == "test justification"

    # staged_edges status + edge_type updated
    staged = conn.execute(
        "SELECT status, edge_type, tier FROM staged_edges WHERE id=?", (row["id"],)
    ).fetchone()
    assert staged["status"] == "reclassified"
    assert staged["edge_type"] == "CONTRASTS"
    assert staged["tier"] == "verified"


def test_reclassify_to_surface_only_routes_through_reject(conn):
    """surface_only and unrelated can't appear in the edges.type CHECK,
    so the reclassify path treats them as typed rejects: DELETE the
    old-type live edge, mark status='rejected', record the new edge_type
    on the staged row (audit trail of what the curator classified)."""
    row = _seed_staged(conn, edge_type="PARALLELS")
    conn.execute(
        "INSERT INTO edges(source_id, target_id, type, tier, justification) "
        "VALUES(?,?, 'PARALLELS', 'proposed', '[auto] x')",
        (row["source_chunk"], row["target_chunk"]),
    )
    reclassify_edge(conn, row, "surface_only")

    # Old-type live edge gone
    edge = conn.execute(
        "SELECT * FROM edges WHERE source_id=? AND target_id=?",
        (row["source_chunk"], row["target_chunk"]),
    ).fetchone()
    assert edge is None

    # staged_edges status='rejected', edge_type recorded
    staged = conn.execute(
        "SELECT status, edge_type FROM staged_edges WHERE id=?", (row["id"],)
    ).fetchone()
    assert staged["status"] == "rejected"
    assert staged["edge_type"] == "surface_only"


def test_reclassify_to_unrelated_routes_through_reject(conn):
    row = _seed_staged(conn, edge_type="CONTRASTS")
    reclassify_edge(conn, row, "unrelated")
    staged = conn.execute(
        "SELECT status, edge_type FROM staged_edges WHERE id=?", (row["id"],)
    ).fetchone()
    assert staged["status"] == "rejected"
    assert staged["edge_type"] == "unrelated"


def test_reclassify_with_unknown_type_raises(conn):
    row = _seed_staged(conn)
    with pytest.raises(ValueError, match="unknown edge_type"):
        reclassify_edge(conn, row, "BOGUS")


def test_reclassify_with_no_existing_edge_is_safe(conn):
    """The DELETE of the old-type edge is a no-op when none exists.
    Reclassify still proceeds to the new-type upsert."""
    row = _seed_staged(conn, edge_type="PARALLELS")
    reclassify_edge(conn, row, "CONTRASTS")
    new = conn.execute(
        "SELECT tier FROM edges WHERE source_id=? AND target_id=? AND type='CONTRASTS'",
        (row["source_chunk"], row["target_chunk"]),
    ).fetchone()
    assert new["tier"] == "verified"
