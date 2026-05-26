"""tests/test_sync_taxonomy.py — taxonomy → SQLite sync (todo:0a25044c).

Exercises scripts/sync_taxonomy.py against an in-memory DB that has a minimal
`nodes` table plus the real v3_006 migration applied. Covers parse, apply,
demote-then-upsert on a primary move, alias lowercasing/replacement, the
dry-run no-write guarantee, idempotency, and the §7 promise that existing
is_primary=0 (secondary) rows are never touched.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
MIGRATION = PROJECT_ROOT / "scripts" / "migrations" / "v3_006_concept_families.sql"

spec = importlib.util.spec_from_file_location(
    "sync_taxonomy", PROJECT_ROOT / "scripts" / "sync_taxonomy.py"
)
sync_taxonomy = importlib.util.module_from_spec(spec)
sys.modules["sync_taxonomy"] = sync_taxonomy
spec.loader.exec_module(sync_taxonomy)

parse_taxonomy = sync_taxonomy.parse_taxonomy
sync = sync_taxonomy.sync

NODES_SCHEMA = """
CREATE TABLE nodes (
    id            TEXT PRIMARY KEY,
    type          TEXT NOT NULL,
    tradition_id  TEXT REFERENCES nodes(id),
    label         TEXT NOT NULL,
    definition    TEXT
);
"""


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.isolation_level = None
    c.execute("PRAGMA foreign_keys = ON")
    c.executescript(NODES_SCHEMA)
    c.executescript(MIGRATION.read_text())
    yield c
    c.close()


def _data():
    """A two-domain taxonomy with one family each and some aliases."""
    return {
        "families": {
            "cosmology": {
                "definition": "Origin and structure of the universe.",
                "aliases": ["The Cosmos", "Origin Of The Universe"],
                "divine_structure": {"definition": "The architecture of the highest realms."},
            },
            "ethics": {
                "definition": "Moral teaching and conduct.",
                "moral_teaching": {
                    "label": "Right Conduct",
                    "definition": "Right conduct and the pedagogy of insight.",
                },
            },
        },
        "concepts": {
            "cosmology": {"divine_structure": {"monad": "The One.", "logos": "The word."}},
            "ethics": {"moral_teaching": {"love_of_neighbour": "Care for others."}},
        },
        "concept_aliases": {"monad": ["The One", "First Principle"]},
    }


# ── parse ────────────────────────────────────────────────────────────────────


def test_parse_families_and_parents():
    plan = parse_taxonomy(_data())
    fams = {f[0]: f for f in plan["families"]}
    # domains have parent_id None; families point at their domain
    assert fams["cosmology"][1] is None
    assert fams["cosmology.divine_structure"][1] == "cosmology"
    assert fams["ethics.moral_teaching"][1] == "ethics"
    # a parent always precedes its child in the ordered list (FK-safe inserts)
    ids = [f[0] for f in plan["families"]]
    assert ids.index("cosmology") < ids.index("cosmology.divine_structure")


def test_parse_label_derivation_and_override():
    plan = parse_taxonomy(_data())
    fams = {f[0]: f[2] for f in plan["families"]}
    assert fams["cosmology.divine_structure"] == "Divine Structure"  # derived
    assert fams["ethics.moral_teaching"] == "Right Conduct"          # explicit override


def test_parse_concepts_use_node_ids():
    plan = parse_taxonomy(_data())
    by_node = {c[0]: c for c in plan["concepts"]}
    assert "concept.monad" in by_node
    assert by_node["concept.monad"][3] == "cosmology.divine_structure"
    assert by_node["concept.monad"][1] == "Monad"
    assert plan["concept_aliases"]["concept.monad"] == ["The One", "First Principle"]


def test_parse_rejects_undeclared_family():
    data = _data()
    data["concepts"]["cosmology"]["ghost_family"] = {"x": "y"}
    with pytest.raises(SystemExit):
        parse_taxonomy(data)


def test_parse_rejects_missing_definition():
    data = _data()
    del data["families"]["cosmology"]["divine_structure"]["definition"]
    with pytest.raises(SystemExit):
        parse_taxonomy(data)


# ── apply ──────────────────────────────────────────────────────────────────--


def test_apply_populates_all_tables(conn):
    sync(conn, parse_taxonomy(_data()), apply=True)
    # families: 2 domains + 2 families
    assert conn.execute("SELECT COUNT(*) FROM concept_families").fetchone()[0] == 4
    assert conn.execute(
        "SELECT parent_id FROM concept_families WHERE id='cosmology.divine_structure'"
    ).fetchone()[0] == "cosmology"
    # concept nodes created
    assert conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE type='concept'"
    ).fetchone()[0] == 3
    # primary memberships
    prim = dict(conn.execute(
        "SELECT concept_id, family_id FROM concept_family_membership WHERE is_primary=1"
    ).fetchall())
    assert prim["concept.monad"] == "cosmology.divine_structure"
    assert prim["concept.love_of_neighbour"] == "ethics.moral_teaching"


def test_apply_lowercases_aliases(conn):
    sync(conn, parse_taxonomy(_data()), apply=True)
    fam = sorted(r[0] for r in conn.execute(
        "SELECT alias FROM family_aliases WHERE family_id='cosmology'"
    ))
    assert fam == ["origin of the universe", "the cosmos"]
    con = sorted(r[0] for r in conn.execute(
        "SELECT alias FROM concept_aliases WHERE concept_id='concept.monad'"
    ))
    assert con == ["first principle", "the one"]


def test_dry_run_writes_nothing(conn):
    report = sync(conn, parse_taxonomy(_data()), apply=False)
    assert report["primaries_created"] == 3  # report still computed
    assert conn.execute("SELECT COUNT(*) FROM concept_families").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM concept_family_membership").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM family_aliases").fetchone()[0] == 0


def test_idempotent(conn):
    sync(conn, parse_taxonomy(_data()), apply=True)
    r2 = sync(conn, parse_taxonomy(_data()), apply=True)
    assert r2["primaries_created"] == 0
    assert r2["primaries_unchanged"] == 3
    assert r2["primaries_moved"] == 0
    # no duplicate rows
    assert conn.execute("SELECT COUNT(*) FROM concept_family_membership").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM family_aliases").fetchone()[0] == 2


# ── demote-then-upsert on a move ─────────────────────────────────────────────


def test_move_demotes_prior_primary(conn):
    # Seed monad's node + an existing primary in a different family.
    conn.execute("INSERT INTO nodes(id,type,label) VALUES('concept.monad','concept','Monad')")
    conn.execute(
        "INSERT INTO concept_families(id,parent_id,label,definition) "
        "VALUES('cosmology',NULL,'Cosmology','d')"
    )
    conn.execute(
        "INSERT INTO concept_families(id,parent_id,label,definition) "
        "VALUES('cosmology.old_home','cosmology','Old','d')"
    )
    conn.execute(
        "INSERT INTO concept_family_membership(concept_id,family_id,is_primary) "
        "VALUES('concept.monad','cosmology.old_home',1)"
    )

    report = sync(conn, parse_taxonomy(_data()), apply=True)
    assert report["primaries_moved"] == 1
    assert report["primaries_demoted"] == 1
    assert report["moves"] == [("concept.monad", "cosmology.old_home", "cosmology.divine_structure")]

    rows = dict(conn.execute(
        "SELECT family_id, is_primary FROM concept_family_membership WHERE concept_id='concept.monad'"
    ).fetchall())
    assert rows["cosmology.divine_structure"] == 1  # new primary
    assert rows["cosmology.old_home"] == 0           # demoted, not deleted
    # exactly one primary survives
    assert conn.execute(
        "SELECT COUNT(*) FROM concept_family_membership WHERE concept_id='concept.monad' AND is_primary=1"
    ).fetchone()[0] == 1


def test_secondary_rows_untouched(conn):
    # A pre-existing secondary affiliation must survive the sync verbatim.
    sync(conn, parse_taxonomy(_data()), apply=True)
    conn.execute(
        "INSERT INTO concept_family_membership(concept_id,family_id,is_primary) "
        "VALUES('concept.monad','ethics.moral_teaching',0)"
    )
    report = sync(conn, parse_taxonomy(_data()), apply=True)
    assert report["secondary_present"] == 1
    assert conn.execute(
        "SELECT is_primary FROM concept_family_membership "
        "WHERE concept_id='concept.monad' AND family_id='ethics.moral_teaching'"
    ).fetchone()[0] == 0


def test_single_primary_invariant_holds(conn):
    sync(conn, parse_taxonomy(_data()), apply=True)
    # every concept with any membership has at most one primary
    dupes = conn.execute(
        """SELECT concept_id, COUNT(*) c FROM concept_family_membership
           WHERE is_primary=1 GROUP BY concept_id HAVING c > 1"""
    ).fetchall()
    assert dupes == []
