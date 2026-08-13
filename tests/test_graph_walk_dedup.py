"""tests/test_graph_walk_dedup.py — the edge leg emits the partner only, once.

Regression: the PARALLELS/CONTRASTS branch used to append both endpoints of
every edge, including the anchor already emitted by the EXPRESSES branch. In
_merge_and_rank that re-emission deduped by chunk_id but still raised
graph_score via max(), biasing the ranker toward chunks that happened to be
edge endpoints.

That branch now lives in guru.retrieval_legs.edge_partners and is opt-in via
EDGE_LEG=on — guru-web has never had a chunk↔chunk leg, so the pilot
traversing it unconditionally was the largest behavioural gap between the two
systems. The invariants are unchanged and still asserted here, against the
new home.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from guru.preferences import UserPreferences
from guru import retrieval_legs as legs
from guru.retriever import HybridRetriever


SCHEMA_SQL = """
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
    type TEXT NOT NULL,
    tier TEXT NOT NULL DEFAULT 'inferred'
);
"""


class _StubVectorStore:
    def query(self, *a, **kw):
        return []


def _seed_db(db_path: Path) -> None:
    """One concept, one anchor chunk in tradition A, one partner in tradition B,
    linked by a single PARALLELS edge."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)
    conn.executemany(
        "INSERT INTO nodes(id, type, tradition_id, label) VALUES(?,?,?,?)",
        [
            ("concept.gnosis_direct_knowledge", "concept", None, "gnosis"),
            ("trad_a.text.001", "chunk", "trad_a", "anchor"),
            ("trad_b.text.001", "chunk", "trad_b", "partner"),
        ],
    )
    conn.executemany(
        "INSERT INTO edges(source_id, target_id, type, tier) VALUES(?,?,?,?)",
        [
            # Only the anchor expresses the concept.
            ("trad_a.text.001", "concept.gnosis_direct_knowledge", "EXPRESSES", "verified"),
            # Anchor PARALLELS partner.
            ("trad_a.text.001", "trad_b.text.001", "PARALLELS", "proposed"),
        ],
    )
    conn.commit()
    conn.close()


@pytest.fixture
def retriever(tmp_path):
    db = tmp_path / "graph.db"
    _seed_db(db)

    cfg = tmp_path / "model.toml"
    cfg.write_text("""
[retrieval]
top_k = 10
min_similarity = 0.5
max_per_tradition = 3
max_concept_walks = 5
concept_match_min_word_len = 3

[ranking]
tier_verified = 1.0
tier_proposed = 0.7
tier_inferred = 0.4
diversity_boost = 0.0
vector_weight = 0.7
graph_weight = 0.3
""")
    return HybridRetriever(db_path=db, config_path=cfg, vector_store=_StubVectorStore())


def test_partner_emitted_anchor_not_doubled(tmp_path, monkeypatch):
    """From the anchor, the edge leg returns the cross-tradition partner once
    and never re-emits the anchor itself."""
    monkeypatch.setenv("EDGE_LEG", "on")
    db = tmp_path / "graph.db"
    _seed_db(db)
    conn = sqlite3.connect(str(db))
    out = legs.edge_partners(conn, {"trad_a.text.001"})
    conn.close()
    chunk_ids = [r["chunk_id"] for r in out]

    assert chunk_ids.count("trad_a.text.001") == 0, (
        f"Anchor re-emitted as its own partner. Full results: {chunk_ids}")
    assert chunk_ids.count("trad_b.text.001") == 1, (
        f"Partner missing or duplicated. Full results: {chunk_ids}")
    assert len(chunk_ids) == 1, f"Expected exactly 1 emission, got {chunk_ids}"


def test_edge_leg_off_by_default(tmp_path):
    """Parity with guru-web: no chunk↔chunk traversal unless asked for."""
    db = tmp_path / "graph.db"
    _seed_db(db)
    conn = sqlite3.connect(str(db))
    out = legs.edge_partners(conn, {"trad_a.text.001"})
    conn.close()
    assert out == [], "edge leg must be off unless EDGE_LEG=on"


def test_concept_leg_returns_expressing_chunk(retriever):
    """The concept leg still resolves a query to the chunks that express it."""
    conn = sqlite3.connect(str(retriever._db_path))
    conn.row_factory = sqlite3.Row
    out = retriever._graph_walk("what is gnosis?", UserPreferences.allow_all(), conn)
    conn.close()
    assert [r["chunk_id"] for r in out] == ["trad_a.text.001"]


def test_intra_tradition_parallels_skipped(tmp_path, monkeypatch):
    """A PARALLELS edge whose endpoints share a tradition is not a
    cross-tradition partner and must not be emitted by the edge leg."""
    monkeypatch.setenv("EDGE_LEG", "on")
    db = tmp_path / "g.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(SCHEMA_SQL)
    conn.executemany(
        "INSERT INTO nodes(id, type, tradition_id, label) VALUES(?,?,?,?)",
        [
            ("concept.gnosis_direct_knowledge", "concept", None, "gnosis"),
            ("a.t.001", "chunk", "a", "x"),
            ("a.t.002", "chunk", "a", "y"),
        ],
    )
    conn.executemany(
        "INSERT INTO edges(source_id, target_id, type, tier) VALUES(?,?,?,?)",
        [
            ("a.t.001", "concept.gnosis_direct_knowledge", "EXPRESSES", "verified"),
            ("a.t.002", "concept.gnosis_direct_knowledge", "EXPRESSES", "verified"),
            ("a.t.001", "a.t.002", "PARALLELS", "proposed"),
        ],
    )
    conn.commit()

    out = legs.edge_partners(conn, {"a.t.001", "a.t.002"})
    conn.close()
    assert out == [], f"intra-tradition parallel emitted: {out}"
