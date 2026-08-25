"""tests/test_review_family_context.py — family context in the tag-view surface (todo:79dac19d).

view_staged_tags.print_tag_row shows the concept's primary family (design.md §9).
(The former review_edges.print_edge_row family analog was removed with the edge
CLI: Pass C is retired and cross-tradition edges are derived, not reviewed.)
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


view_staged_tags = _load("view_staged_tags")

SCHEMA = """
CREATE TABLE nodes (id TEXT PRIMARY KEY, type TEXT NOT NULL, label TEXT NOT NULL, definition TEXT);
CREATE TABLE edges (id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT, target_id TEXT, type TEXT, tier TEXT, justification TEXT);
CREATE TABLE concept_families (id TEXT PRIMARY KEY, parent_id TEXT, label TEXT NOT NULL, definition TEXT NOT NULL);
CREATE TABLE concept_family_membership (concept_id TEXT, family_id TEXT, is_primary INTEGER, PRIMARY KEY(concept_id, family_id));
"""


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(SCHEMA)
    c.executescript("""
        INSERT INTO concept_families VALUES
          ('cosmology', NULL, 'Cosmology', 'Origin and structure of the universe.'),
          ('cosmology.divine_structure', 'cosmology', 'Divine Structure', 'The architecture of the highest realms.'),
          ('theology', NULL, 'Theology', 'The nature of the divine.'),
          ('theology.divine_nature', 'theology', 'Divine Nature', 'What God is, including via negation.');
        INSERT INTO nodes VALUES
          ('concept.monad','concept','Monad','def'),
          ('concept.apophatic_theology','concept','Apophatic Theology','def'),
          ('concept.brand_new','concept','Brand New', NULL),
          ('chunk.x','chunk','X',NULL);
        INSERT INTO concept_family_membership VALUES
          ('concept.monad','cosmology.divine_structure',1),
          ('concept.apophatic_theology','theology.divine_nature',1);
        INSERT INTO edges(source_id,target_id,type,tier) VALUES
          ('chunk.x','concept.monad','EXPRESSES','verified'),
          ('chunk.x','concept.apophatic_theology','EXPRESSES','verified');
    """)
    c.commit()
    yield c
    c.close()


# ── view_staged_tags: concept → primary family ───────────────────────────────


def test_get_concept_family(conn):
    fam = view_staged_tags.get_concept_family(conn, "monad")
    assert fam == {"domain": "cosmology", "family": "divine_structure",
                   "definition": "The architecture of the highest realms."}


def test_get_concept_family_none_for_unclustered(conn):
    assert view_staged_tags.get_concept_family(conn, "brand_new") is None


def test_print_tag_row_renders_family(conn, capsys):
    row = {"chunk_id": "chunk.x", "label": "Sec", "concept_id": "monad",
           "score": 3, "justification": "j", "is_new_concept": 0, "new_concept_def": None}
    view_staged_tags.print_tag_row(row, "the concept def", "body text",
                              view_staged_tags.get_concept_family(conn, "monad"))
    out = capsys.readouterr().out
    assert "FAMILY:  cosmology → divine_structure" in out
    assert "— The architecture of the highest realms." in out


def test_print_tag_row_omits_family_when_none(conn, capsys):
    row = {"chunk_id": "c", "label": "S", "concept_id": "brand_new",
           "score": 2, "justification": "j", "is_new_concept": 0, "new_concept_def": None}
    view_staged_tags.print_tag_row(row, "d", "b", None)
    assert "FAMILY:" not in capsys.readouterr().out
