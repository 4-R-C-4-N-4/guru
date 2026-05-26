"""tests/test_migration_v3_006.py — concept-hierarchy schema migration (todo:ad1c2299).

Applies scripts/migrations/v3_006_concept_families.sql to an in-memory DB that
already has a minimal `nodes` table (the FK target for concept rows), then
asserts the four new tables + five indexes exist and that every constraint
from design.md §5 actually enforces:

  - is_primary CHECK rejects values outside {0,1}
  - the partial UNIQUE index allows many is_primary=0 rows but only one =1 per concept
  - CHECK(alias = LOWER(alias)) rejects mixed-case ASCII aliases
  - ON DELETE CASCADE cleans up membership + alias rows when a concept node is deleted
  - the family_id → concept_families FK on membership stays RESTRICT
  - parent_id self-reference (domain ← family) works
  - re-running the migration is a no-op (IF NOT EXISTS everywhere)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
MIGRATION = PROJECT_ROOT / "scripts" / "migrations" / "v3_006_concept_families.sql"

# Minimal slice of the real schema: just the FK target the new tables reference.
SCHEMA = """
CREATE TABLE nodes (
    id            TEXT PRIMARY KEY,
    type          TEXT NOT NULL,
    tradition_id  TEXT REFERENCES nodes(id),
    label         TEXT NOT NULL
);
"""


def _seed(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    # Two concept nodes to hang memberships/aliases off of.
    conn.executemany(
        "INSERT INTO nodes(id, type, label) VALUES(?, 'concept', ?)",
        [("monad", "Monad"), ("logos", "Logos")],
    )
    conn.commit()


def _apply_migration(conn: sqlite3.Connection) -> None:
    conn.executescript(MIGRATION.read_text())


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    # The new tables only enforce their FKs / CASCADE with FKs on.
    c.execute("PRAGMA foreign_keys = ON")
    _seed(c)
    _apply_migration(c)
    yield c
    c.close()


def _seed_hierarchy(conn: sqlite3.Connection) -> None:
    """A domain, a family under it, and primary memberships for both concepts."""
    conn.execute(
        "INSERT INTO concept_families(id, parent_id, label, definition) "
        "VALUES('cosmology', NULL, 'Cosmology', 'origin and structure of the universe')"
    )
    conn.execute(
        "INSERT INTO concept_families(id, parent_id, label, definition) "
        "VALUES('cosmology.cosmic_agents', 'cosmology', 'Cosmic Agents', 'divine actors')"
    )
    conn.executemany(
        "INSERT INTO concept_family_membership(concept_id, family_id, is_primary) VALUES(?, ?, 1)",
        [("monad", "cosmology.cosmic_agents"), ("logos", "cosmology.cosmic_agents")],
    )
    conn.commit()


# ── structure ────────────────────────────────────────────────────────────────


def test_creates_four_tables(conn):
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {
        "concept_families",
        "concept_family_membership",
        "concept_aliases",
        "family_aliases",
    } <= tables


def test_creates_five_indexes(conn):
    indexes = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
    }
    assert {
        "idx_concept_families_parent",
        "idx_concept_primary_family",
        "idx_concept_family_membership_family",
        "idx_concept_aliases_alias",
        "idx_family_aliases_alias",
    } <= indexes


def test_parent_id_self_reference(conn):
    """A family points at its domain via parent_id within the same table."""
    _seed_hierarchy(conn)
    parent = conn.execute(
        "SELECT parent_id FROM concept_families WHERE id='cosmology.cosmic_agents'"
    ).fetchone()[0]
    assert parent == "cosmology"
    domain_parent = conn.execute(
        "SELECT parent_id FROM concept_families WHERE id='cosmology'"
    ).fetchone()[0]
    assert domain_parent is None


# ── is_primary constraints ─────────────────────────────────────────────────────


def test_is_primary_check_rejects_out_of_range(conn):
    _seed_hierarchy(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO concept_family_membership(concept_id, family_id, is_primary) "
            "VALUES('monad', 'cosmology', 2)"
        )


def test_partial_unique_allows_one_primary_many_secondary(conn):
    """A concept may have one is_primary=1 row but unlimited is_primary=0 rows."""
    _seed_hierarchy(conn)  # monad primary in cosmic_agents
    # A second *secondary* affiliation is fine.
    conn.execute(
        "INSERT INTO concept_family_membership(concept_id, family_id, is_primary) "
        "VALUES('monad', 'cosmology', 0)"
    )
    conn.commit()
    # A second *primary* for the same concept violates the partial unique index.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO concept_family_membership(concept_id, family_id, is_primary) "
            "VALUES('monad', 'cosmology', 1)"
        )


def test_distinct_concepts_each_get_a_primary(conn):
    """The partial unique index is per-concept, not global."""
    _seed_hierarchy(conn)  # both monad and logos are primary in cosmic_agents
    n = conn.execute(
        "SELECT COUNT(*) FROM concept_family_membership WHERE is_primary=1"
    ).fetchone()[0]
    assert n == 2


# ── alias case constraints ─────────────────────────────────────────────────────


def test_concept_alias_check_rejects_mixed_case(conn):
    _seed_hierarchy(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO concept_aliases(concept_id, alias) VALUES('monad', 'The One')"
        )


def test_family_alias_check_rejects_mixed_case(conn):
    _seed_hierarchy(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO family_aliases(family_id, alias) VALUES('cosmology', 'Cosmos')"
        )


def test_lowercase_aliases_accepted(conn):
    _seed_hierarchy(conn)
    conn.execute("INSERT INTO concept_aliases(concept_id, alias) VALUES('monad', 'the one')")
    conn.execute("INSERT INTO family_aliases(family_id, alias) VALUES('cosmology', 'cosmos')")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM concept_aliases").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM family_aliases").fetchone()[0] == 1


# ── cascade / restrict behaviour ────────────────────────────────────────────────


def test_delete_concept_cascades_membership_and_aliases(conn):
    _seed_hierarchy(conn)
    conn.execute("INSERT INTO concept_aliases(concept_id, alias) VALUES('monad', 'the one')")
    conn.commit()
    conn.execute("DELETE FROM nodes WHERE id='monad'")
    conn.commit()
    assert conn.execute(
        "SELECT COUNT(*) FROM concept_family_membership WHERE concept_id='monad'"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM concept_aliases WHERE concept_id='monad'"
    ).fetchone()[0] == 0


def test_delete_family_cascades_family_aliases(conn):
    _seed_hierarchy(conn)
    # cosmic_agents has members, so delete the leaf-free domain alias path:
    conn.execute("INSERT INTO family_aliases(family_id, alias) VALUES('cosmology', 'cosmos')")
    conn.commit()
    # Remove memberships referencing cosmic_agents first, then delete it.
    conn.execute("DELETE FROM concept_family_membership WHERE family_id='cosmology.cosmic_agents'")
    conn.execute("DELETE FROM concept_families WHERE id='cosmology.cosmic_agents'")
    conn.commit()
    # Deleting the domain cascades its family_aliases.
    conn.execute("DELETE FROM concept_families WHERE id='cosmology'")
    conn.commit()
    assert conn.execute(
        "SELECT COUNT(*) FROM family_aliases WHERE family_id='cosmology'"
    ).fetchone()[0] == 0


def test_delete_family_with_members_is_restricted(conn):
    """membership.family_id → concept_families is default RESTRICT: deleting a
    family that still has members must fail rather than orphan the rows."""
    _seed_hierarchy(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM concept_families WHERE id='cosmology.cosmic_agents'")


# ── idempotency ────────────────────────────────────────────────────────────────


def test_migration_is_idempotent(conn):
    """Re-running the migration over the already-migrated DB is a clean no-op,
    and leaves seeded data intact."""
    _seed_hierarchy(conn)
    before = conn.execute("SELECT COUNT(*) FROM concept_family_membership").fetchone()[0]
    _apply_migration(conn)  # second application
    after = conn.execute("SELECT COUNT(*) FROM concept_family_membership").fetchone()[0]
    assert before == after == 2
