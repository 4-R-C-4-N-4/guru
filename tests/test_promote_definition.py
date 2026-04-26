"""Regression tests for review_tags.py:
  - promote_to_expresses populating nodes.definition (todo:bdbdccd5)
  - tier='verified' on every human accept regardless of score (todo:f21b6baf)
  - reject_tag retracts auto-promoted edges (todo:f21b6baf)
  - reassign_tag retracts the original-concept edge (todo:f21b6baf)
"""
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from review_tags import promote_to_expresses, reject_tag, reassign_tag  # noqa: E402


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
        INSERT INTO nodes(id, type, label) VALUES ('gnosticism', 'tradition', 'Gnosticism');
        INSERT INTO nodes(id, type, tradition_id, label)
            VALUES ('gnosticism.gospel-of-thomas.001', 'chunk', 'gnosticism', 'Logion 1');
    """)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    _seed_schema(c)
    yield c
    c.close()


# ── promote_to_expresses ──────────────────────────────────────────────


def test_new_concept_accept_populates_definition(conn: sqlite3.Connection) -> None:
    promote_to_expresses(
        conn, "gnosticism.gospel-of-thomas.001", "ineffable_truth",
        "matches the apophatic move",
        new_concept_def="Truth that cannot be expressed in words.",
    )
    row = conn.execute(
        "SELECT label, definition FROM nodes WHERE id='concept.ineffable_truth'"
    ).fetchone()
    assert (row["label"], row["definition"]) == (
        "Ineffable Truth", "Truth that cannot be expressed in words.",
    )


def test_existing_concept_definition_not_clobbered(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO nodes(id, type, label, definition) VALUES (?, 'concept', ?, ?)",
        ("concept.gnosis", "Gnosis", "Direct experiential knowledge of the divine."),
    )
    promote_to_expresses(
        conn, "gnosticism.gospel-of-thomas.001", "gnosis", "this is gnosis",
        new_concept_def="A different definition that should NOT win.",
    )
    row = conn.execute(
        "SELECT definition FROM nodes WHERE id='concept.gnosis'"
    ).fetchone()
    assert row["definition"] == "Direct experiential knowledge of the divine."


def test_is_new_concept_zero_accept_leaves_definition_null(conn: sqlite3.Connection) -> None:
    promote_to_expresses(
        conn, "gnosticism.gospel-of-thomas.001", "kenoma",
        "world of becoming", new_concept_def=None,
    )
    row = conn.execute(
        "SELECT label, definition FROM nodes WHERE id='concept.kenoma'"
    ).fetchone()
    assert (row["label"], row["definition"]) == ("Kenoma", None)


def test_existing_null_definition_gets_backfilled(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO nodes(id, type, label) VALUES (?, 'concept', ?)",
        ("concept.aeons", "Aeons"),
    )
    promote_to_expresses(
        conn, "gnosticism.gospel-of-thomas.001", "aeons", "the divine emanations",
        new_concept_def="Eternal divine emanations from the Pleroma.",
    )
    row = conn.execute(
        "SELECT definition FROM nodes WHERE id='concept.aeons'"
    ).fetchone()
    assert row["definition"] == "Eternal divine emanations from the Pleroma."


def test_accept_always_writes_verified_regardless_of_score(conn: sqlite3.Connection) -> None:
    """Editorial overlay rule: any human accept = verified. Score is no longer
    consulted for tier — that distinction is auto-promote's job."""
    # Three chunks accepted at three different model-confidence levels —
    # all land at tier='verified' because each was a human accept.
    promote_to_expresses(conn, "gnosticism.gospel-of-thomas.001", "kenoma", "score-2 accept")
    promote_to_expresses(conn, "gnosticism.gospel-of-thomas.001", "demiurge", "score-1 accept")
    promote_to_expresses(conn, "gnosticism.gospel-of-thomas.001", "pleroma", "score-3 accept")
    rows = conn.execute(
        "SELECT target_id, tier FROM edges WHERE source_id='gnosticism.gospel-of-thomas.001' "
        "AND type='EXPRESSES' ORDER BY target_id"
    ).fetchall()
    tiers = {r["target_id"]: r["tier"] for r in rows}
    assert tiers == {
        "concept.demiurge": "verified",
        "concept.kenoma":   "verified",
        "concept.pleroma":  "verified",
    }


def test_accept_upgrades_auto_promoted_edge_to_verified(conn: sqlite3.Connection) -> None:
    """If auto-promote already wrote a 'proposed' edge, a subsequent human
    accept must upgrade it via ON CONFLICT DO UPDATE."""
    # Simulate auto-promote first: insert a 'proposed' edge directly.
    conn.execute(
        "INSERT INTO nodes(id, type, label) VALUES ('concept.gnosis', 'concept', 'Gnosis')"
    )
    conn.execute(
        "INSERT INTO edges(source_id, target_id, type, tier, justification) "
        "VALUES (?, ?, 'EXPRESSES', 'proposed', '[auto] model said it')",
        ("gnosticism.gospel-of-thomas.001", "concept.gnosis"),
    )
    # Human accepts the same row.
    promote_to_expresses(
        conn, "gnosticism.gospel-of-thomas.001", "gnosis", "human-curated text",
    )
    row = conn.execute(
        "SELECT tier, justification FROM edges WHERE target_id='concept.gnosis'"
    ).fetchone()
    assert row["tier"] == "verified"
    assert row["justification"] == "human-curated text"


# ── reject_tag ─────────────────────────────────────────────────────────


def _seed_staged_tag(conn, **overrides):
    defaults = dict(
        chunk_id="gnosticism.gospel-of-thomas.001",
        concept_id="gnosis",
        score=3,
        justification="model-asserted",
        is_new_concept=0,
        new_concept_def=None,
        model="Qwen3.5-27B-UD-Q4_K_XL.gguf",
        prompt_version="v1",
    )
    defaults.update(overrides)
    conn.execute(
        """INSERT INTO staged_tags(chunk_id, concept_id, score, justification,
                                   is_new_concept, new_concept_def, model, prompt_version)
           VALUES(?,?,?,?,?,?,?,?)""",
        tuple(defaults[k] for k in
              ("chunk_id", "concept_id", "score", "justification",
               "is_new_concept", "new_concept_def", "model", "prompt_version")),
    )
    return conn.execute(
        "SELECT * FROM staged_tags WHERE id = last_insert_rowid()"
    ).fetchone()


def test_reject_tag_deletes_auto_promoted_edge(conn: sqlite3.Connection) -> None:
    row = _seed_staged_tag(conn)
    # Auto-promote earlier wrote a 'proposed' edge.
    conn.execute("INSERT INTO nodes(id,type,label) VALUES('concept.gnosis','concept','Gnosis')")
    conn.execute(
        "INSERT INTO edges(source_id, target_id, type, tier, justification) "
        "VALUES (?, ?, 'EXPRESSES', 'proposed', '[auto] x')",
        (row["chunk_id"], "concept.gnosis"),
    )
    reject_tag(conn, row)

    edge = conn.execute(
        "SELECT * FROM edges WHERE source_id=? AND target_id='concept.gnosis'",
        (row["chunk_id"],),
    ).fetchone()
    assert edge is None, "rejected row's edge must be deleted"
    status = conn.execute(
        "SELECT status FROM staged_tags WHERE id=?", (row["id"],)
    ).fetchone()
    assert status["status"] == "rejected"


def test_reject_tag_no_existing_edge_is_safe(conn: sqlite3.Connection) -> None:
    """Reject must work cleanly even when no edge exists (auto-promote
    hadn't run, or this row was sub-threshold)."""
    row = _seed_staged_tag(conn)
    reject_tag(conn, row)  # no edge to delete — must not raise
    status = conn.execute(
        "SELECT status FROM staged_tags WHERE id=?", (row["id"],)
    ).fetchone()
    assert status["status"] == "rejected"


def test_reject_tag_does_not_touch_other_edges(conn: sqlite3.Connection) -> None:
    """The DELETE must scope to (chunk_id, concept_id, EXPRESSES) only.
    Other edges on the same chunk or to the same concept must survive."""
    row = _seed_staged_tag(conn)
    conn.execute("INSERT INTO nodes(id,type,label) VALUES('concept.gnosis','concept','Gnosis')")
    conn.execute("INSERT INTO nodes(id,type,label) VALUES('concept.aeons','concept','Aeons')")
    conn.execute(
        "INSERT INTO nodes(id,type,tradition_id,label) "
        "VALUES('gnosticism.gospel-of-thomas.002','chunk','gnosticism','Logion 2')"
    )
    # Three live edges. Only the (.001, gnosis) one should die on reject.
    conn.execute(
        "INSERT INTO edges(source_id,target_id,type,tier,justification) VALUES "
        "(?, 'concept.gnosis', 'EXPRESSES', 'proposed', 'x')",
        (row["chunk_id"],),
    )
    conn.execute(
        "INSERT INTO edges(source_id,target_id,type,tier,justification) VALUES "
        "(?, 'concept.aeons', 'EXPRESSES', 'verified', 'x')",
        (row["chunk_id"],),
    )
    conn.execute(
        "INSERT INTO edges(source_id,target_id,type,tier,justification) "
        "VALUES('gnosticism.gospel-of-thomas.002','concept.gnosis','EXPRESSES','verified','x')"
    )

    reject_tag(conn, row)

    surviving = conn.execute(
        "SELECT source_id, target_id FROM edges ORDER BY source_id, target_id"
    ).fetchall()
    assert [(e["source_id"], e["target_id"]) for e in surviving] == [
        ("gnosticism.gospel-of-thomas.001", "concept.aeons"),       # other concept on same chunk
        ("gnosticism.gospel-of-thomas.002", "concept.gnosis"),      # same concept on other chunk
    ]


# ── reassign_tag ───────────────────────────────────────────────────────


def test_reassign_tag_deletes_original_concept_edge(conn: sqlite3.Connection) -> None:
    row = _seed_staged_tag(conn, concept_id="archon")
    conn.execute("INSERT INTO nodes(id,type,label) VALUES('concept.archon','concept','Archon')")
    conn.execute(
        "INSERT INTO edges(source_id,target_id,type,tier,justification) VALUES "
        "(?, 'concept.archon', 'EXPRESSES', 'proposed', '[auto] wrong concept')",
        (row["chunk_id"],),
    )
    reassign_tag(conn, row, "demiurge")

    # Original-concept edge gone
    edge = conn.execute(
        "SELECT * FROM edges WHERE source_id=? AND target_id='concept.archon'",
        (row["chunk_id"],),
    ).fetchone()
    assert edge is None, "original-concept edge must be deleted on reassign"

    # Status mutated
    status = conn.execute(
        "SELECT status, concept_id FROM staged_tags WHERE id=?", (row["id"],)
    ).fetchone()
    assert (status["status"], status["concept_id"]) == ("reassigned", "demiurge")


def test_reassign_tag_spawns_pending_row_carrying_provenance(conn: sqlite3.Connection) -> None:
    row = _seed_staged_tag(conn, concept_id="archon", score=2)
    reassign_tag(conn, row, "demiurge")

    spawned = conn.execute(
        "SELECT chunk_id, concept_id, score, justification, status, "
        "       is_new_concept, model, prompt_version "
        "FROM staged_tags WHERE id != ? ORDER BY id DESC LIMIT 1",
        (row["id"],),
    ).fetchone()
    assert spawned is not None
    assert spawned["chunk_id"]       == "gnosticism.gospel-of-thomas.001"
    assert spawned["concept_id"]     == "demiurge"
    assert spawned["score"]          == 2
    assert spawned["justification"]  == "Reassigned from archon"
    assert spawned["status"]         == "pending"
    assert spawned["is_new_concept"] == 0
    assert spawned["model"]          == "Qwen3.5-27B-UD-Q4_K_XL.gguf"
    assert spawned["prompt_version"] == "v1"


def test_reassign_tag_does_not_touch_unrelated_edges(conn: sqlite3.Connection) -> None:
    row = _seed_staged_tag(conn, concept_id="archon")
    conn.execute("INSERT INTO nodes(id,type,label) VALUES('concept.archon','concept','Archon')")
    conn.execute("INSERT INTO nodes(id,type,label) VALUES('concept.gnosis','concept','Gnosis')")
    # Edge for the wrong concept (must die) and an unrelated edge (must survive)
    conn.execute(
        "INSERT INTO edges(source_id,target_id,type,tier,justification) VALUES "
        "(?, 'concept.archon', 'EXPRESSES', 'proposed', 'wrong')",
        (row["chunk_id"],),
    )
    conn.execute(
        "INSERT INTO edges(source_id,target_id,type,tier,justification) VALUES "
        "(?, 'concept.gnosis', 'EXPRESSES', 'verified', 'right')",
        (row["chunk_id"],),
    )

    reassign_tag(conn, row, "demiurge")

    surviving_targets = [
        r["target_id"] for r in
        conn.execute(
            "SELECT target_id FROM edges WHERE source_id=? ORDER BY target_id",
            (row["chunk_id"],),
        ).fetchall()
    ]
    assert surviving_targets == ["concept.gnosis"]
