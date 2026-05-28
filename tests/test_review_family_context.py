"""tests/test_review_family_context.py — family context in review surfaces (todo:79dac19d).

review_tags.print_tag_row shows the concept's primary family (design.md §9);
review_edges.print_edge_row shows each linked chunk's expressed concept-families
(the only sensible analog, since edges carry no concept of their own).
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


review_tags = _load("review_tags")
review_edges = _load("review_edges")

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


# ── review_tags: concept → primary family ────────────────────────────────────


def test_get_concept_family(conn):
    fam = review_tags.get_concept_family(conn, "monad")
    assert fam == {"domain": "cosmology", "family": "divine_structure",
                   "definition": "The architecture of the highest realms."}


def test_get_concept_family_none_for_unclustered(conn):
    assert review_tags.get_concept_family(conn, "brand_new") is None


def test_print_tag_row_renders_family(conn, capsys):
    row = {"chunk_id": "chunk.x", "label": "Sec", "concept_id": "monad",
           "score": 3, "justification": "j", "is_new_concept": 0, "new_concept_def": None}
    review_tags.print_tag_row(row, "the concept def", "body text",
                              review_tags.get_concept_family(conn, "monad"))
    out = capsys.readouterr().out
    assert "FAMILY:  cosmology → divine_structure" in out
    assert "— The architecture of the highest realms." in out


def test_print_tag_row_omits_family_when_none(conn, capsys):
    row = {"chunk_id": "c", "label": "S", "concept_id": "brand_new",
           "score": 2, "justification": "j", "is_new_concept": 0, "new_concept_def": None}
    review_tags.print_tag_row(row, "d", "b", None)
    assert "FAMILY:" not in capsys.readouterr().out


# ── review_edges: chunk → expressed families ─────────────────────────────────


def test_chunk_families(conn):
    fams = review_edges.chunk_families(conn, "chunk.x")
    assert fams == ["cosmology→divine_structure", "theology→divine_nature"]


def test_chunk_families_empty(conn):
    assert review_edges.chunk_families(conn, "chunk.nonexistent") == []


def test_print_edge_row_renders_families(conn, capsys):
    row = {"edge_type": "PARALLELS", "confidence": 0.9, "justification": "j"}
    review_edges.print_edge_row(
        row, "body a", "Cite A", "body b", "Cite B",
        review_edges.chunk_families(conn, "chunk.x"), [],
    )
    out = capsys.readouterr().out
    assert "FAMILIES A: cosmology→divine_structure, theology→divine_nature" in out
    assert "FAMILIES B: (none)" in out
