"""tests/test_graph_walk_dedup.py — _graph_walk emits cross-tradition partner only.

Regression: the PARALLELS/CONTRASTS branch of _graph_walk used to append
both endpoints of every edge, including the anchor chunk that was already
emitted by the EXPRESSES branch. In _merge_and_rank that re-emission only
deduped at the chunk_id level but still raised graph_score via max(),
biasing the ranker toward chunks that happened to be edge endpoints.

This test builds a synthetic concept graph with one anchor + one cross-
tradition partner and verifies _graph_walk now emits each chunk exactly
once.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from guru.preferences import UserPreferences
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


def test_partner_emitted_anchor_not_doubled(retriever):
    """Query 'gnosis' matches concept.gnosis_direct_knowledge. Walk should
    return:
      - anchor (trad_a.text.001) once via EXPRESSES
      - partner (trad_b.text.001) once via PARALLELS
    Anchor must not appear a second time as the source endpoint of its own
    PARALLELS edge."""
    out = retriever._graph_walk("what is gnosis?", UserPreferences.allow_all())
    chunk_ids = [r["chunk_id"] for r in out]

    assert chunk_ids.count("trad_a.text.001") == 1, (
        f"Anchor emitted {chunk_ids.count('trad_a.text.001')} times — "
        f"expected exactly 1. Full results: {chunk_ids}"
    )
    assert chunk_ids.count("trad_b.text.001") == 1, (
        f"Partner missing or duplicated. Full results: {chunk_ids}"
    )
    assert len(chunk_ids) == 2, f"Expected exactly 2 emissions, got {chunk_ids}"


def test_intra_tradition_parallels_skipped(tmp_path):
    """If both endpoints of a PARALLELS edge express the concept (intra-
    tradition link), the EXPRESSES branch covers them and the
    PARALLELS branch should not re-emit either endpoint."""
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
    conn.close()

    cfg = tmp_path / "model.toml"
    cfg.write_text("""
[retrieval]
top_k = 10
max_concept_walks = 5
concept_match_min_word_len = 3
""")
    r = HybridRetriever(db_path=db, config_path=cfg, vector_store=_StubVectorStore())
    out = r._graph_walk("gnosis", UserPreferences.allow_all())
    chunk_ids = [x["chunk_id"] for x in out]
    # Each chunk should appear exactly once (from EXPRESSES). PARALLELS
    # branch should skip both endpoints since both are anchors.
    assert chunk_ids.count("a.t.001") == 1
    assert chunk_ids.count("a.t.002") == 1
    assert len(chunk_ids) == 2
