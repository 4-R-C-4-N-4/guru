"""Tests for scripts/auto_promote.py (todo:225546a1).

In-memory DB fixture covers the full filter and tier-mapping rules
documented in docs/autopromote/design.md §5.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from auto_promote import (  # noqa: E402
    DEFAULT_MODEL,
    apply_promotion,
    fetch_candidates,
    summarize,
)


# ── fixture ───────────────────────────────────────────────────────────


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
        CREATE TABLE staged_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chunk_id TEXT NOT NULL REFERENCES nodes(id),
            concept_id TEXT NOT NULL,
            score INTEGER NOT NULL CHECK(score BETWEEN 0 AND 3),
            justification TEXT,
            is_new_concept INTEGER NOT NULL DEFAULT 0,
            new_concept_def TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','accepted','rejected','reassigned')),
            reviewed_by TEXT,
            reviewed_at TEXT,
            model TEXT,
            prompt_version TEXT
        );
        CREATE UNIQUE INDEX idx_staged_tags_provenance_unique
            ON staged_tags(chunk_id, concept_id, model, prompt_version)
            WHERE status='pending';
        INSERT INTO nodes(id, type, label) VALUES ('gnosticism', 'tradition', 'Gnosticism');
        INSERT INTO nodes(id, type, tradition_id, label) VALUES
            ('gnosticism.gospel-of-thomas.001', 'chunk', 'gnosticism', 'Logion 1'),
            ('gnosticism.gospel-of-thomas.002', 'chunk', 'gnosticism', 'Logion 2'),
            ('gnosticism.gospel-of-thomas.003', 'chunk', 'gnosticism', 'Logion 3');
    """)


def _seed_tag(conn, *, chunk, concept, score, model=DEFAULT_MODEL,
              is_new=False, new_def=None, status="pending") -> int:
    cur = conn.execute(
        """INSERT INTO staged_tags(chunk_id, concept_id, score, justification,
                                   is_new_concept, new_concept_def, status,
                                   model, prompt_version)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (chunk, concept, score, f"justification for {concept}",
         1 if is_new else 0, new_def, status, model, "v1"),
    )
    return cur.lastrowid


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    _seed_schema(c)
    yield c
    c.close()


# ── filter rules ──────────────────────────────────────────────────────


def test_score_floor_default_3_only_promotes_score_3(conn):
    _seed_tag(conn, chunk="gnosticism.gospel-of-thomas.001", concept="a", score=3)
    _seed_tag(conn, chunk="gnosticism.gospel-of-thomas.002", concept="b", score=2)
    _seed_tag(conn, chunk="gnosticism.gospel-of-thomas.003", concept="c", score=1)

    cands = fetch_candidates(conn, score_floor=3, model=DEFAULT_MODEL)
    assert {c["concept_id"] for c in cands} == {"a"}


def test_score_floor_2_promotes_score_2_and_3_only(conn):
    _seed_tag(conn, chunk="gnosticism.gospel-of-thomas.001", concept="a", score=3)
    _seed_tag(conn, chunk="gnosticism.gospel-of-thomas.002", concept="b", score=2)
    _seed_tag(conn, chunk="gnosticism.gospel-of-thomas.003", concept="c", score=1)

    cands = fetch_candidates(conn, score_floor=2, model=DEFAULT_MODEL)
    assert {c["concept_id"] for c in cands} == {"a", "b"}


def test_score_floor_1_promotes_all_pending(conn):
    _seed_tag(conn, chunk="gnosticism.gospel-of-thomas.001", concept="a", score=3)
    _seed_tag(conn, chunk="gnosticism.gospel-of-thomas.002", concept="b", score=2)
    _seed_tag(conn, chunk="gnosticism.gospel-of-thomas.003", concept="c", score=1)

    cands = fetch_candidates(conn, score_floor=1, model=DEFAULT_MODEL)
    assert {c["concept_id"] for c in cands} == {"a", "b", "c"}


def test_is_new_concept_rows_excluded(conn):
    """Taxonomy-altering rows stay manual; auto-promote skips is_new_concept=1."""
    _seed_tag(conn, chunk="gnosticism.gospel-of-thomas.001", concept="known", score=3)
    _seed_tag(conn, chunk="gnosticism.gospel-of-thomas.002", concept="new_idea",
              score=3, is_new=True, new_def="model coined this")

    cands = fetch_candidates(conn, score_floor=3, model=DEFAULT_MODEL)
    assert {c["concept_id"] for c in cands} == {"known"}


def test_non_default_model_rows_excluded(conn):
    """Carnice-9b rows are skipped under the default --model filter."""
    _seed_tag(conn, chunk="gnosticism.gospel-of-thomas.001", concept="qwen_one", score=3)
    _seed_tag(conn, chunk="gnosticism.gospel-of-thomas.002", concept="carnice_one",
              score=3, model="Carnice-9b")

    cands = fetch_candidates(conn, score_floor=3, model=DEFAULT_MODEL)
    assert {c["concept_id"] for c in cands} == {"qwen_one"}


def test_carnice_9b_promoted_when_explicitly_targeted(conn):
    """The model filter is just a string equality; pass --model Carnice-9b
    to promote that bucket if the operator opts in."""
    _seed_tag(conn, chunk="gnosticism.gospel-of-thomas.001", concept="qwen_one", score=3)
    _seed_tag(conn, chunk="gnosticism.gospel-of-thomas.002", concept="carnice_one",
              score=3, model="Carnice-9b")

    cands = fetch_candidates(conn, score_floor=3, model="Carnice-9b")
    assert {c["concept_id"] for c in cands} == {"carnice_one"}


def test_non_pending_status_excluded(conn):
    """Already-reviewed rows (accepted/rejected/reassigned) are out of scope."""
    _seed_tag(conn, chunk="gnosticism.gospel-of-thomas.001", concept="pending_one", score=3)
    _seed_tag(conn, chunk="gnosticism.gospel-of-thomas.002", concept="accepted_one",
              score=3, status="accepted")
    _seed_tag(conn, chunk="gnosticism.gospel-of-thomas.003", concept="rejected_one",
              score=3, status="rejected")

    cands = fetch_candidates(conn, score_floor=3, model=DEFAULT_MODEL)
    assert {c["concept_id"] for c in cands} == {"pending_one"}


def test_existing_edge_blocks_promotion(conn):
    """NOT EXISTS guard: if the (chunk, concept, EXPRESSES) edge already
    exists at any tier, auto-promote leaves it alone — re-run safety
    AND human-verified rows are never downgraded."""
    chunk = "gnosticism.gospel-of-thomas.001"
    _seed_tag(conn, chunk=chunk, concept="already_live", score=3)
    conn.execute(
        "INSERT INTO nodes(id,type,label) VALUES('concept.already_live','concept','Already Live')"
    )
    conn.execute(
        "INSERT INTO edges(source_id,target_id,type,tier,justification) "
        "VALUES(?, 'concept.already_live', 'EXPRESSES', 'verified', 'human accepted earlier')",
        (chunk,),
    )
    cands = fetch_candidates(conn, score_floor=3, model=DEFAULT_MODEL)
    assert cands == [], "must not propose to promote a row that already has a live edge"


# ── per-row tier mapping ──────────────────────────────────────────────


def test_tier_mapping_score_3_to_proposed(conn):
    _seed_tag(conn, chunk="gnosticism.gospel-of-thomas.001", concept="a", score=3)
    cands = fetch_candidates(conn, score_floor=1, model=DEFAULT_MODEL)
    assert cands[0]["target_tier"] == "proposed"


def test_tier_mapping_score_2_to_proposed(conn):
    _seed_tag(conn, chunk="gnosticism.gospel-of-thomas.001", concept="a", score=2)
    cands = fetch_candidates(conn, score_floor=1, model=DEFAULT_MODEL)
    assert cands[0]["target_tier"] == "proposed"


def test_tier_mapping_score_1_to_inferred(conn):
    _seed_tag(conn, chunk="gnosticism.gospel-of-thomas.001", concept="a", score=1)
    cands = fetch_candidates(conn, score_floor=1, model=DEFAULT_MODEL)
    assert cands[0]["target_tier"] == "inferred"


def test_verified_tier_is_never_assigned_by_auto_promote(conn):
    """The whole point: verified stays human-reviewed-only."""
    _seed_tag(conn, chunk="gnosticism.gospel-of-thomas.001", concept="a", score=3)
    _seed_tag(conn, chunk="gnosticism.gospel-of-thomas.002", concept="b", score=2)
    _seed_tag(conn, chunk="gnosticism.gospel-of-thomas.003", concept="c", score=1)
    cands = fetch_candidates(conn, score_floor=1, model=DEFAULT_MODEL)
    assert all(c["target_tier"] != "verified" for c in cands)


# ── apply path ────────────────────────────────────────────────────────


def test_apply_writes_proposed_edges_and_concept_nodes(conn):
    chunk = "gnosticism.gospel-of-thomas.001"
    _seed_tag(conn, chunk=chunk, concept="kenoma", score=3)

    s = apply_promotion(conn, score_floor=3, model=DEFAULT_MODEL)
    assert s["inserted"] == 1

    edge = conn.execute(
        "SELECT tier, justification FROM edges "
        "WHERE source_id=? AND target_id='concept.kenoma' AND type='EXPRESSES'",
        (chunk,),
    ).fetchone()
    assert edge["tier"] == "proposed"
    assert edge["justification"].startswith("[auto] ")

    # concept node was created (defensive upsert from auto_promote.py)
    node = conn.execute(
        "SELECT label FROM nodes WHERE id='concept.kenoma'"
    ).fetchone()
    assert node["label"] == "Kenoma"


def test_apply_does_not_overwrite_existing_edge(conn):
    """ON CONFLICT DO NOTHING on the edge insert. A pre-existing
    'verified' edge must survive a subsequent auto-promote run unchanged."""
    chunk = "gnosticism.gospel-of-thomas.001"
    _seed_tag(conn, chunk=chunk, concept="gnosis", score=3)
    conn.execute(
        "INSERT INTO nodes(id,type,label,definition) "
        "VALUES('concept.gnosis','concept','Gnosis','human-curated def')"
    )
    conn.execute(
        "INSERT INTO edges(source_id,target_id,type,tier,justification) "
        "VALUES(?,'concept.gnosis','EXPRESSES','verified','human-curated text')",
        (chunk,),
    )
    s = apply_promotion(conn, score_floor=3, model=DEFAULT_MODEL)
    assert s["inserted"] == 0, "candidate set should be empty when edge already exists"

    edge = conn.execute(
        "SELECT tier, justification FROM edges WHERE target_id='concept.gnosis'"
    ).fetchone()
    assert edge["tier"] == "verified"
    assert edge["justification"] == "human-curated text"


def test_apply_re_run_is_idempotent(conn):
    """Running auto_promote.py twice with same inputs lands the same edges;
    the second run inserts zero rows."""
    chunk = "gnosticism.gospel-of-thomas.001"
    _seed_tag(conn, chunk=chunk, concept="kenoma", score=3)

    s1 = apply_promotion(conn, score_floor=3, model=DEFAULT_MODEL)
    s2 = apply_promotion(conn, score_floor=3, model=DEFAULT_MODEL)
    assert s1["inserted"] == 1
    assert s2["inserted"] == 0

    edges = conn.execute(
        "SELECT COUNT(*) AS n FROM edges WHERE target_id='concept.kenoma'"
    ).fetchone()
    assert edges["n"] == 1


def test_apply_does_not_touch_staged_tags_status(conn):
    """staged_tags stays 'pending' so future human review can still upgrade
    the auto-promoted edge."""
    chunk = "gnosticism.gospel-of-thomas.001"
    sid = _seed_tag(conn, chunk=chunk, concept="kenoma", score=3)

    apply_promotion(conn, score_floor=3, model=DEFAULT_MODEL)

    status = conn.execute(
        "SELECT status FROM staged_tags WHERE id=?", (sid,)
    ).fetchone()
    assert status["status"] == "pending"


def test_auto_prefix_lands_on_justification(conn):
    """The [auto] marker on edges.justification is the disclosure to the
    answering LLM (and to retrieval debugging) that this association is
    model-asserted not human-curated."""
    chunk = "gnosticism.gospel-of-thomas.001"
    _seed_tag(conn, chunk=chunk, concept="kenoma", score=3)

    apply_promotion(conn, score_floor=3, model=DEFAULT_MODEL)

    edge = conn.execute(
        "SELECT justification FROM edges WHERE target_id='concept.kenoma'"
    ).fetchone()
    assert edge["justification"].startswith("[auto] ")
    assert "justification for kenoma" in edge["justification"]


def test_apply_handles_null_justification(conn):
    """If staged_tag.justification is NULL, the edge gets '[auto] ' (empty
    body). Defensive — prod data always has justification but unit tests
    shouldn't crash."""
    conn.execute(
        """INSERT INTO staged_tags(chunk_id, concept_id, score, justification,
                                   is_new_concept, model, prompt_version)
           VALUES(?,?,?,NULL,0,?,'v1')""",
        ("gnosticism.gospel-of-thomas.001", "kenoma", 3, DEFAULT_MODEL),
    )
    apply_promotion(conn, score_floor=3, model=DEFAULT_MODEL)
    edge = conn.execute(
        "SELECT justification FROM edges WHERE target_id='concept.kenoma'"
    ).fetchone()
    assert edge["justification"] == "[auto] "


# ── summary ───────────────────────────────────────────────────────────


def test_summarize_groups_by_tier_and_tradition(conn):
    conn.execute(
        "INSERT INTO nodes(id,type,label) VALUES('christian_mysticism','tradition','Christian Mysticism')"
    )
    conn.execute(
        "INSERT INTO nodes(id,type,tradition_id,label) "
        "VALUES('christian_mysticism.boehme.001','chunk','christian_mysticism','Boehme 1')"
    )
    _seed_tag(conn, chunk="gnosticism.gospel-of-thomas.001", concept="a", score=3)
    _seed_tag(conn, chunk="gnosticism.gospel-of-thomas.002", concept="b", score=2)
    _seed_tag(conn, chunk="christian_mysticism.boehme.001", concept="c", score=1)

    cands = fetch_candidates(conn, score_floor=1, model=DEFAULT_MODEL)
    s = summarize(cands)

    assert s["total"] == 3
    assert s["by_tier"] == {"proposed": 2, "inferred": 1}
    assert s["by_tradition"] == {"gnosticism": 2, "christian_mysticism": 1}
    # sample is one of the candidates
    assert s["sample"] is not None
    assert s["sample"]["target_tier"] in {"proposed", "inferred"}
