"""Regression tests for promote_to_expresses populating nodes.definition
on is_new_concept accept (todo:bdbdccd5).

When a tag with is_new_concept=1 is accepted, the LLM-proposed
new_concept_def must land in nodes.definition. Existing definitions
must never be clobbered by a re-accept.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from review_tags import promote_to_expresses  # noqa: E402


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


def test_new_concept_accept_populates_definition(conn: sqlite3.Connection) -> None:
    promote_to_expresses(
        conn, "gnosticism.gospel-of-thomas.001", "ineffable_truth",
        "matches the apophatic move", 3,
        new_concept_def="Truth that cannot be expressed in words.",
    )
    row = conn.execute(
        "SELECT label, definition FROM nodes WHERE id='concept.ineffable_truth'"
    ).fetchone()
    assert row == ("Ineffable Truth", "Truth that cannot be expressed in words.")


def test_existing_concept_definition_not_clobbered(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO nodes(id, type, label, definition) VALUES (?, 'concept', ?, ?)",
        ("concept.gnosis", "Gnosis", "Direct experiential knowledge of the divine."),
    )
    promote_to_expresses(
        conn, "gnosticism.gospel-of-thomas.001", "gnosis",
        "this is gnosis", 3,
        new_concept_def="A different definition that should NOT win.",
    )
    row = conn.execute(
        "SELECT definition FROM nodes WHERE id='concept.gnosis'"
    ).fetchone()
    assert row == ("Direct experiential knowledge of the divine.",)


def test_is_new_concept_zero_accept_leaves_definition_null(conn: sqlite3.Connection) -> None:
    """is_new_concept=0 callers pass new_concept_def=None; node lands with NULL definition."""
    promote_to_expresses(
        conn, "gnosticism.gospel-of-thomas.001", "kenoma",
        "world of becoming", 2, new_concept_def=None,
    )
    row = conn.execute(
        "SELECT label, definition FROM nodes WHERE id='concept.kenoma'"
    ).fetchone()
    assert row == ("Kenoma", None)


def test_existing_null_definition_gets_backfilled(conn: sqlite3.Connection) -> None:
    """Concept node with NULL definition + is_new_concept=1 accept fills it in."""
    conn.execute(
        "INSERT INTO nodes(id, type, label) VALUES (?, 'concept', ?)",
        ("concept.aeons", "Aeons"),
    )
    promote_to_expresses(
        conn, "gnosticism.gospel-of-thomas.001", "aeons",
        "the divine emanations", 3,
        new_concept_def="Eternal divine emanations from the Pleroma.",
    )
    row = conn.execute(
        "SELECT definition FROM nodes WHERE id='concept.aeons'"
    ).fetchone()
    assert row == ("Eternal divine emanations from the Pleroma.",)


def test_edge_inserted_with_correct_tier(conn: sqlite3.Connection) -> None:
    """Sanity: edge insert path still works alongside the upsert change."""
    promote_to_expresses(
        conn, "gnosticism.gospel-of-thomas.001", "kenoma",
        "world of becoming", 2,
    )
    edge = conn.execute(
        "SELECT source_id, target_id, type, tier, justification FROM edges"
    ).fetchone()
    assert edge == (
        "gnosticism.gospel-of-thomas.001",
        "concept.kenoma",
        "EXPRESSES",
        "verified",
        "world of becoming",
    )

    promote_to_expresses(
        conn, "gnosticism.gospel-of-thomas.001", "demiurge",
        "shaper of the cosmos", 1,
    )
    tier = conn.execute(
        "SELECT tier FROM edges WHERE target_id='concept.demiurge'"
    ).fetchone()
    assert tier == ("proposed",)
