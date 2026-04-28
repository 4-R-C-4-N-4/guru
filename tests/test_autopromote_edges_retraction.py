"""End-to-end retraction proofs for auto_promote_edges.py + review_edges.py.

Bridges the two halves of the cross-tradition edge workflow:
  1. auto_promote_edges.py creates a tier='proposed' live edge from a
     high-confidence staged_edges row.
  2. review_edges.py reject / reclassify actions DELETE that live edge,
     so a human curator can retract the model's call.

The CLI-side retraction primitives are unit-tested in tests/test_review_edges.py
and the web-side branch is covered by guru-review/server/src/schema.test.ts.
This module asserts they compose: an edge introduced by auto-promote can be
rolled back by review_edges with no leftover state.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from auto_promote_edges import apply_promotion  # noqa: E402
from review_edges import reject_edge, reclassify_edge  # noqa: E402


def _seed_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE nodes (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            tradition_id TEXT,
            label TEXT NOT NULL,
            definition TEXT,
            metadata_json TEXT DEFAULT '{}'
        );
        CREATE TABLE edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('BELONGS_TO','EXPRESSES','PARALLELS','CONTRASTS','DERIVES_FROM')),
            tier TEXT NOT NULL DEFAULT 'inferred' CHECK(tier IN ('verified','proposed','inferred')),
            justification TEXT
        );
        CREATE UNIQUE INDEX idx_edges_unique ON edges(source_id, target_id, type);
        CREATE TABLE staged_edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_chunk TEXT NOT NULL,
            target_chunk TEXT NOT NULL,
            edge_type TEXT NOT NULL CHECK(edge_type IN ('PARALLELS','CONTRASTS','surface_only','unrelated')),
            confidence REAL NOT NULL DEFAULT 0.0,
            justification TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','accepted','rejected','reclassified')),
            tier TEXT NOT NULL DEFAULT 'proposed',
            reviewed_by TEXT,
            reviewed_at TEXT,
            UNIQUE(source_chunk, target_chunk)
        );
        INSERT INTO nodes(id, type, tradition_id, label) VALUES
            ('a.t.001', 'chunk', 'a', 'A1'),
            ('b.t.001', 'chunk', 'b', 'B1');
    """)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    _seed_schema(c)
    yield c
    c.close()


def _staged_row(conn, edge_id) -> dict:
    return dict(conn.execute("SELECT * FROM staged_edges WHERE id=?", (edge_id,)).fetchone())


def _seed_high_conf_edge(conn, *, src, tgt, edge_type="PARALLELS", conf=0.95) -> int:
    cur = conn.execute(
        "INSERT INTO staged_edges(source_chunk, target_chunk, edge_type, confidence, justification) "
        "VALUES(?,?,?,?,?)",
        (src, tgt, edge_type, conf, "model said they correspond"),
    )
    return cur.lastrowid


# ── round-trip: auto-promote → reject ────────────────────────────────


def test_reject_after_auto_promote_deletes_live_edge(conn):
    eid = _seed_high_conf_edge(conn, src="a.t.001", tgt="b.t.001", edge_type="PARALLELS")

    # Step 1: auto-promote creates the live edge at tier='proposed'.
    s = apply_promotion(conn, 0.85)
    assert s["inserted"] == 1
    live_after_promote = conn.execute(
        "SELECT tier, justification FROM edges "
        "WHERE source_id='a.t.001' AND target_id='b.t.001' AND type='PARALLELS'"
    ).fetchone()
    assert live_after_promote["tier"] == "proposed"
    assert live_after_promote["justification"].startswith("[auto] ")

    # Step 2: human curator rejects the staged_edges row.
    reject_edge(conn, _staged_row(conn, eid))

    # The live edge must be gone (retraction primitive fired).
    assert conn.execute(
        "SELECT COUNT(*) FROM edges "
        "WHERE source_id='a.t.001' AND target_id='b.t.001' AND type='PARALLELS'"
    ).fetchone()[0] == 0

    # Staged row is rejected, not pending.
    assert conn.execute(
        "SELECT status FROM staged_edges WHERE id=?", (eid,)
    ).fetchone()["status"] == "rejected"


# ── round-trip: auto-promote → reclassify ────────────────────────────


def test_reclassify_after_auto_promote_swaps_edge_type(conn):
    eid = _seed_high_conf_edge(conn, src="a.t.001", tgt="b.t.001", edge_type="PARALLELS")
    apply_promotion(conn, 0.85)

    # Curator reclassifies PARALLELS → CONTRASTS.
    reclassify_edge(conn, _staged_row(conn, eid), "CONTRASTS")

    # Old PARALLELS edge gone, new CONTRASTS edge present at verified tier.
    assert conn.execute(
        "SELECT COUNT(*) FROM edges WHERE type='PARALLELS' "
        "AND source_id='a.t.001' AND target_id='b.t.001'"
    ).fetchone()[0] == 0
    new_row = conn.execute(
        "SELECT tier FROM edges WHERE type='CONTRASTS' "
        "AND source_id='a.t.001' AND target_id='b.t.001'"
    ).fetchone()
    assert new_row is not None
    assert new_row["tier"] == "verified"


def test_reclassify_to_surface_only_after_auto_promote_drops_live_edge(conn):
    """Reclassifying to a non-promotable type (surface_only/unrelated) routes
    through reject — the live edge must be dropped, status flipped, no new
    live edge created (CHECK would forbid it)."""
    eid = _seed_high_conf_edge(conn, src="a.t.001", tgt="b.t.001", edge_type="PARALLELS")
    apply_promotion(conn, 0.85)
    reclassify_edge(conn, _staged_row(conn, eid), "surface_only")

    assert conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 0
    assert conn.execute(
        "SELECT status, edge_type FROM staged_edges WHERE id=?", (eid,)
    ).fetchone()["status"] == "rejected"


# ── reverse direction: human-promoted edge survives auto-promote ─────


def test_human_verified_edge_not_clobbered_by_subsequent_autopromote(conn):
    """If a human accepted an edge first (tier=verified), a later auto-promote
    pass on a re-staged version of the same row must leave the verified tier
    intact via ON CONFLICT DO NOTHING."""
    _seed_high_conf_edge(conn, src="a.t.001", tgt="b.t.001", edge_type="PARALLELS")
    conn.execute(
        "INSERT INTO edges(source_id, target_id, type, tier, justification) "
        "VALUES('a.t.001','b.t.001','PARALLELS','verified','human-signed')"
    )
    # Reset the staged row to pending so it would re-qualify (simulates a re-propose run).
    conn.execute("UPDATE staged_edges SET status='pending'")

    s = apply_promotion(conn, 0.85)
    assert s["inserted"] == 0  # NOT EXISTS filter caught it

    row = conn.execute(
        "SELECT tier, justification FROM edges "
        "WHERE source_id='a.t.001' AND target_id='b.t.001' AND type='PARALLELS'"
    ).fetchone()
    assert row["tier"] == "verified"
    assert row["justification"] == "human-signed"
