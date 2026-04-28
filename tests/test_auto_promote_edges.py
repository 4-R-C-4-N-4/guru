"""Tests for scripts/auto_promote_edges.py (todo:e0030982).

In-memory DB fixture covers the filter and tier rules from the script's
docstring. Mirrors tests/test_auto_promote.py (the staged_tags variant).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from auto_promote_edges import (  # noqa: E402
    DEFAULT_CONFIDENCE,
    PROMOTABLE_EDGE_TYPES,
    apply_promotion,
    fetch_candidates,
    summarize,
)


# ── fixture ───────────────────────────────────────────────────────────


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
            ('a.t.002', 'chunk', 'a', 'A2'),
            ('b.t.001', 'chunk', 'b', 'B1'),
            ('b.t.002', 'chunk', 'b', 'B2'),
            ('c.t.001', 'chunk', 'c', 'C1');
    """)


def _seed_edge(conn, *, src, tgt, edge_type, conf, status="pending", just="proposal"):
    conn.execute(
        """INSERT INTO staged_edges(source_chunk, target_chunk, edge_type, confidence, justification, status)
           VALUES(?,?,?,?,?,?)""",
        (src, tgt, edge_type, conf, just, status),
    )


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    _seed_schema(c)
    yield c
    c.close()


# ── filter rules ──────────────────────────────────────────────────────


def test_default_confidence_floor_promotes_at_or_above(conn):
    _seed_edge(conn, src="a.t.001", tgt="b.t.001", edge_type="PARALLELS", conf=0.90)
    _seed_edge(conn, src="a.t.002", tgt="b.t.002", edge_type="PARALLELS", conf=0.85)  # boundary
    _seed_edge(conn, src="a.t.001", tgt="b.t.002", edge_type="PARALLELS", conf=0.84)
    candidates = fetch_candidates(conn, DEFAULT_CONFIDENCE)
    assert {(c["source_chunk"], c["target_chunk"]) for c in candidates} == {
        ("a.t.001", "b.t.001"),
        ("a.t.002", "b.t.002"),
    }


def test_lower_floor_admits_more_rows(conn):
    _seed_edge(conn, src="a.t.001", tgt="b.t.001", edge_type="PARALLELS", conf=0.90)
    _seed_edge(conn, src="a.t.002", tgt="b.t.002", edge_type="PARALLELS", conf=0.70)
    assert len(fetch_candidates(conn, 0.85)) == 1
    assert len(fetch_candidates(conn, 0.65)) == 2


def test_surface_only_and_unrelated_are_skipped(conn):
    """staged_edges allows surface_only/unrelated values, but the live
    edges.type CHECK rejects them — promoting either would error."""
    _seed_edge(conn, src="a.t.001", tgt="b.t.001", edge_type="PARALLELS", conf=0.90)
    _seed_edge(conn, src="a.t.002", tgt="b.t.002", edge_type="surface_only", conf=0.95)
    _seed_edge(conn, src="a.t.001", tgt="c.t.001", edge_type="unrelated", conf=0.99)
    candidates = fetch_candidates(conn, DEFAULT_CONFIDENCE)
    assert len(candidates) == 1
    assert candidates[0]["edge_type"] == "PARALLELS"


def test_contrasts_promotes_alongside_parallels(conn):
    _seed_edge(conn, src="a.t.001", tgt="b.t.001", edge_type="PARALLELS", conf=0.90)
    _seed_edge(conn, src="a.t.002", tgt="b.t.002", edge_type="CONTRASTS", conf=0.90)
    types = {c["edge_type"] for c in fetch_candidates(conn, DEFAULT_CONFIDENCE)}
    assert types == {"PARALLELS", "CONTRASTS"}


def test_non_pending_status_skipped(conn):
    _seed_edge(conn, src="a.t.001", tgt="b.t.001", edge_type="PARALLELS", conf=0.95, status="accepted")
    _seed_edge(conn, src="a.t.002", tgt="b.t.002", edge_type="PARALLELS", conf=0.95, status="rejected")
    _seed_edge(conn, src="a.t.001", tgt="c.t.001", edge_type="PARALLELS", conf=0.95, status="reclassified")
    _seed_edge(conn, src="a.t.002", tgt="c.t.001", edge_type="PARALLELS", conf=0.95, status="pending")
    candidates = fetch_candidates(conn, DEFAULT_CONFIDENCE)
    assert len(candidates) == 1
    # Only the (a.t.002, c.t.001) row survives — the others are accepted/rejected/reclassified.
    assert (candidates[0]["source_chunk"], candidates[0]["target_chunk"]) == ("a.t.002", "c.t.001")


def test_existing_live_edge_skipped(conn):
    """Re-run safety: a row whose live edge already exists is filtered out."""
    _seed_edge(conn, src="a.t.001", tgt="b.t.001", edge_type="PARALLELS", conf=0.95)
    conn.execute(
        "INSERT INTO edges(source_id, target_id, type, tier, justification) "
        "VALUES('a.t.001','b.t.001','PARALLELS','verified','human-promoted')"
    )
    candidates = fetch_candidates(conn, DEFAULT_CONFIDENCE)
    assert candidates == []


def test_existing_edge_of_different_type_does_not_block(conn):
    """A live PARALLELS edge does not block promotion of a CONTRASTS staged_edge
    on the same chunk pair (and vice versa) — type is part of the conflict key."""
    _seed_edge(conn, src="a.t.001", tgt="b.t.001", edge_type="CONTRASTS", conf=0.95)
    conn.execute(
        "INSERT INTO edges(source_id, target_id, type, tier) "
        "VALUES('a.t.001','b.t.001','PARALLELS','proposed')"
    )
    candidates = fetch_candidates(conn, DEFAULT_CONFIDENCE)
    assert len(candidates) == 1
    assert candidates[0]["edge_type"] == "CONTRASTS"


# ── apply path ────────────────────────────────────────────────────────


def test_apply_writes_proposed_tier_and_auto_prefix(conn):
    _seed_edge(conn, src="a.t.001", tgt="b.t.001", edge_type="PARALLELS",
               conf=0.95, just="cosmic correspondence")
    summary = apply_promotion(conn, DEFAULT_CONFIDENCE)
    assert summary["inserted"] == 1
    row = conn.execute(
        "SELECT tier, justification FROM edges WHERE source_id='a.t.001' AND target_id='b.t.001'"
    ).fetchone()
    assert row["tier"] == "proposed"
    assert row["justification"].startswith("[auto] ")
    assert "cosmic correspondence" in row["justification"]


def test_apply_never_writes_verified(conn):
    """Even at confidence=1.0, the script must never write tier='verified'."""
    _seed_edge(conn, src="a.t.001", tgt="b.t.001", edge_type="PARALLELS", conf=1.0)
    apply_promotion(conn, DEFAULT_CONFIDENCE)
    tiers = {r["tier"] for r in conn.execute("SELECT tier FROM edges").fetchall()}
    assert tiers == {"proposed"}


def test_apply_is_idempotent(conn):
    _seed_edge(conn, src="a.t.001", tgt="b.t.001", edge_type="PARALLELS", conf=0.95)
    s1 = apply_promotion(conn, DEFAULT_CONFIDENCE)
    s2 = apply_promotion(conn, DEFAULT_CONFIDENCE)
    assert s1["inserted"] == 1
    assert s2["inserted"] == 0
    assert conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 1


def test_apply_does_not_downgrade_existing_verified_edge(conn):
    """If a verified human-reviewed edge exists, ON CONFLICT DO NOTHING leaves it untouched."""
    _seed_edge(conn, src="a.t.001", tgt="b.t.001", edge_type="PARALLELS", conf=0.99)
    conn.execute(
        "INSERT INTO edges(source_id, target_id, type, tier, justification) "
        "VALUES('a.t.001','b.t.001','PARALLELS','verified','human-signed')"
    )
    apply_promotion(conn, DEFAULT_CONFIDENCE)
    row = conn.execute(
        "SELECT tier, justification FROM edges "
        "WHERE source_id='a.t.001' AND target_id='b.t.001' AND type='PARALLELS'"
    ).fetchone()
    assert row["tier"] == "verified"
    assert row["justification"] == "human-signed"


def test_apply_skips_surface_only_at_db_level(conn):
    """Even though the SQL filter excludes them, double-confirm via apply
    that surface_only / unrelated never reach edges (CHECK would fail)."""
    _seed_edge(conn, src="a.t.001", tgt="b.t.001", edge_type="surface_only", conf=0.99)
    _seed_edge(conn, src="a.t.002", tgt="b.t.002", edge_type="unrelated", conf=0.99)
    apply_promotion(conn, DEFAULT_CONFIDENCE)
    assert conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 0


# ── summary shape ─────────────────────────────────────────────────────


def test_summary_groups_by_type_and_tradition_pair(conn):
    _seed_edge(conn, src="a.t.001", tgt="b.t.001", edge_type="PARALLELS", conf=0.90)
    _seed_edge(conn, src="a.t.002", tgt="b.t.002", edge_type="CONTRASTS", conf=0.90)
    _seed_edge(conn, src="a.t.001", tgt="c.t.001", edge_type="PARALLELS", conf=0.90)
    s = summarize(fetch_candidates(conn, DEFAULT_CONFIDENCE))
    assert s["total"] == 3
    assert s["by_type"] == {"PARALLELS": 2, "CONTRASTS": 1}
    assert s["by_tradition_pair"] == {("a", "b"): 2, ("a", "c"): 1}
    assert s["sample"] is not None


def test_dry_run_does_not_write(conn):
    """fetch_candidates + summarize is the dry-run path; no rows in edges."""
    _seed_edge(conn, src="a.t.001", tgt="b.t.001", edge_type="PARALLELS", conf=0.95)
    fetch_candidates(conn, DEFAULT_CONFIDENCE)
    assert conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 0


def test_promotable_edge_types_constant():
    """Sanity: the constant matches the live edges.type CHECK promotable subset."""
    assert PROMOTABLE_EDGE_TYPES == ("PARALLELS", "CONTRASTS")
