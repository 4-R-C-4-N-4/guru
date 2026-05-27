"""tests/test_export_hierarchy.py — export.py concept-hierarchy emitters (todo:89c9ee47).

Covers the four new loaders and the load_concepts family enrichment (design.md
§10.3), plus prefix_ddl handling of the ALTER/COMMENT the v3 schema adds.
COPY-format details (t/f booleans, column lists, FK ordering) are validated
against the real artifact in the export run done at implement time.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import export  # noqa: E402

SCHEMA = """
CREATE TABLE nodes (id TEXT PRIMARY KEY, type TEXT, label TEXT, definition TEXT);
CREATE TABLE concept_families (id TEXT PRIMARY KEY, parent_id TEXT, label TEXT, definition TEXT);
CREATE TABLE concept_family_membership (concept_id TEXT, family_id TEXT, is_primary INTEGER, PRIMARY KEY(concept_id,family_id));
CREATE TABLE concept_aliases (concept_id TEXT, alias TEXT, PRIMARY KEY(concept_id,alias));
CREATE TABLE family_aliases (family_id TEXT, alias TEXT, PRIMARY KEY(family_id,alias));
"""


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    c.executescript("""
        INSERT INTO concept_families VALUES
          ('cosmology', NULL, 'Cosmology', 'Origin and structure.'),
          ('cosmology.divine_structure', 'cosmology', 'Divine Structure', 'Highest realms.');
        INSERT INTO nodes VALUES
          ('concept.monad','concept','Monad','db-def'),
          ('concept.logos','concept','Logos','db-def');
        INSERT INTO concept_family_membership VALUES
          ('concept.monad','cosmology.divine_structure',1),
          ('concept.logos','cosmology.divine_structure',1);
        INSERT INTO concept_aliases VALUES ('concept.monad','the one');
        INSERT INTO family_aliases VALUES ('cosmology','cosmos');
    """)
    c.commit()
    yield c
    c.close()


def test_load_families_orders_domains_first(conn):
    rows = export.load_families(conn)
    # domain (parent NULL) must precede its family for the self-FK COPY
    assert rows[0]["parent_id"] is None
    assert rows[0]["id"] == "cosmology"
    assert rows[1]["id"] == "cosmology.divine_structure"
    assert rows[1]["parent_id"] == "cosmology"


def test_load_membership_is_primary_is_bool(conn):
    rows = export.load_concept_family_membership(conn)
    assert all(isinstance(r["is_primary"], bool) for r in rows)
    assert all(r["is_primary"] is True for r in rows)


def test_load_aliases(conn):
    assert export.load_concept_aliases(conn) == [{"concept_id": "concept.monad", "alias": "the one"}]
    assert export.load_family_aliases(conn) == [{"family_id": "cosmology", "alias": "cosmos"}]


def test_load_concepts_enriched(conn, tmp_path, monkeypatch):
    toml = tmp_path / "taxonomy.toml"
    toml.write_text(
        '[concepts.cosmology.divine_structure]\n'
        'monad = "The first principle."\n'
        'logos = "The ordering word."\n'
    )
    monkeypatch.setattr(export, "TAXONOMY_TOML", toml)
    rows = {r["id"]: r for r in export.load_concepts(conn)}
    monad = rows["concept.monad"]
    assert monad["family_id"] == "cosmology.divine_structure"
    assert monad["domain"] == "cosmology"          # derived from the family's parent
    assert monad["definition"] == "The first principle."  # from TOML, three-tier walk


def test_load_concepts_handles_unclustered(conn, tmp_path, monkeypatch):
    conn.execute("INSERT INTO nodes VALUES ('concept.orphan','concept','Orphan',NULL)")
    toml = tmp_path / "t.toml"
    toml.write_text('[concepts.cosmology.divine_structure]\nmonad = "x"\nlogos = "y"\n')
    monkeypatch.setattr(export, "TAXONOMY_TOML", toml)
    orphan = {r["id"]: r for r in export.load_concepts(conn)}["concept.orphan"]
    assert orphan["family_id"] is None and orphan["domain"] is None


# ── prefix_ddl handles the v3 ALTER / COMMENT constructs ─────────────────────


def test_prefix_ddl_alter_and_comment():
    ddl = (
        "ALTER TABLE concepts ADD COLUMN family_id TEXT REFERENCES concept_families(id);\n"
        "COMMENT ON COLUMN concepts.family_id IS 'note';\n"
    )
    out = export.prefix_ddl(ddl, "corpus_new")
    assert "ALTER TABLE corpus_new.concepts" in out
    assert "REFERENCES corpus_new.concept_families(id)" in out
    assert "COMMENT ON COLUMN corpus_new.concepts.family_id" in out


def test_schema_version_is_3():
    assert export.SCHEMA_VERSION == 3
