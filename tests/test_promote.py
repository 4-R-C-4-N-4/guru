"""Promotion assembly tests (todo:66e9e5a2, implementation G6) — temp-DB fixtures."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
import promote_dossiers as pd

MIGRATION = (Path(__file__).parent.parent / "scripts" / "migrations"
             / "v3_007_document_knowledge.sql").read_text()


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(MIGRATION)
    c.executescript("""
        CREATE TABLE nodes (id TEXT PRIMARY KEY, type TEXT);
        CREATE TABLE edges (id INTEGER PRIMARY KEY, source_id TEXT, target_id TEXT,
                            type TEXT, tier TEXT);
    """)
    return c


def _field(conn, work, field, span, payload, status="accepted", pv="x-v1", rid=None):
    conn.execute(
        "INSERT INTO staged_dossier_fields (id, work_id, field, section_span, payload_json,"
        " status, model, prompt_version) VALUES (?,?,?,?,?,?,'m',?)",
        (rid, work, field, span, json.dumps(payload), status, pv))


def _summary(conn, sid, work, text, level, span, chunks, body, status="accepted", pv="l1-v1"):
    conn.execute(
        "INSERT INTO staged_summaries (summary_id, work_id, text_id, level, section_span,"
        " child_chunk_ids, body, token_count, status, model, prompt_version)"
        " VALUES (?,?,?,?,?,?,?,10,?, 'm', ?)",
        (sid, work, text, level, span, json.dumps(chunks) if chunks else None, body, status, pv))


WP = {
    "work_id": "w1", "degenerate": False,
    "spans": [
        {"text_id": "t1", "label": "S1", "slug": "s1",
         "chunk_ids": ["mesopotamian.enuma-elish.001"], "token_count": 100},
        {"text_id": "t1", "label": "S2", "slug": "s2",
         "chunk_ids": ["mesopotamian.enuma-elish.002"], "token_count": 100},
    ],
}


def _seed_complete(conn):
    _field(conn, "w1", "summary", None, {"body": "intro"})
    _field(conn, "w1", "context", None, {"body": "ctx"})
    _field(conn, "w1", "structure_entry", "S1", {"title": "One", "synopsis": "a."})
    _field(conn, "w1", "structure_entry", "S2", {"title": "Two", "synopsis": "b."})
    _summary(conn, "sum:t1:s1", "w1", "t1", 1, "S1", ["mesopotamian.enuma-elish.001"], "l1 one")
    _summary(conn, "sum:t1:s2", "w1", "t1", 1, "S2", ["mesopotamian.enuma-elish.002"], "l1 two")
    _summary(conn, "sum:w1", "w1", "t1", 2, None, None, "the whole work", pv="l2-v1")


def test_partial_dossiers_never_go_live(conn):
    _seed_complete(conn)
    conn.execute("DELETE FROM staged_dossier_fields WHERE field='context'")
    reason = pd.promote_work(conn, WP, ("enuma-elish",))
    assert reason == "missing accepted context"
    assert conn.execute("SELECT COUNT(*) FROM work_dossiers").fetchone()[0] == 0


def test_assembly_order_and_chunk_ids(conn):
    _seed_complete(conn)
    assert pd.promote_work(conn, WP, ("enuma-elish",)) is None
    row = conn.execute("SELECT * FROM work_dossiers").fetchone()
    structure = json.loads(row["structure_json"])
    assert [e["section_span"] for e in structure] == ["S1", "S2"]  # span order
    assert structure[0]["chunk_ids"] == ["mesopotamian.enuma-elish.001"]
    nodes = conn.execute("SELECT * FROM summary_nodes ORDER BY level, id").fetchall()
    assert [n["level"] for n in nodes] == [1, 1, 2]
    l2 = nodes[-1]
    assert json.loads(l2["child_chunk_ids"]) == [
        "mesopotamian.enuma-elish.001", "mesopotamian.enuma-elish.002"]


def test_manual_rows_outrank_newer_template_rows(conn):
    _seed_complete(conn)
    # a manual summary row OLDER than a later template row must still win
    _field(conn, "w1", "summary", None, {"body": "MANUAL"}, pv="summary-manual", rid=500)
    _field(conn, "w1", "summary", None, {"body": "newer template"}, pv="summary-v9", rid=900)
    assert pd.promote_work(conn, WP, ("enuma-elish",)) is None
    row = conn.execute("SELECT summary FROM work_dossiers").fetchone()
    assert row["summary"] == "MANUAL"


def test_themes_floor_and_tier_weighting(conn):
    _seed_complete(conn)
    # below the floor -> []
    for i in range(pd.THEMES_MIN_TAGS - 1):
        conn.execute("INSERT INTO edges (source_id, target_id, type, tier) VALUES"
                     " ('mesopotamian.enuma-elish.001', ?, 'EXPRESSES', 'verified')", (f"c{i}",))
    assert pd.derive_themes(conn, ["mesopotamian.enuma-elish.001"]) == []
    # at the floor: verified outranks proposed at equal counts
    conn.execute("INSERT INTO edges (source_id, target_id, type, tier) VALUES"
                 " ('mesopotamian.enuma-elish.001', 'cP', 'EXPRESSES', 'proposed')")
    themes = pd.derive_themes(conn, ["mesopotamian.enuma-elish.001"])
    assert themes and themes[-1] == "cP"


def test_children_hash_stability_and_flip():
    h1 = pd.children_hash(["mesopotamian.enuma-elish.001", "mesopotamian.enuma-elish.002"])
    h2 = pd.children_hash(["mesopotamian.enuma-elish.002", "mesopotamian.enuma-elish.001"])
    assert h1 == h2  # order-insensitive (sorted by chunk id)
    h3 = pd.children_hash(["mesopotamian.enuma-elish.001"])
    assert h3 != h1  # different child set flips

    # body change flips: monkeypatch the body reader
    orig = pd.chunk_body
    try:
        pd.chunk_body = lambda cid: orig(cid) + " EDITED"
        assert pd.children_hash(["mesopotamian.enuma-elish.001"]) != h3
    finally:
        pd.chunk_body = orig


def test_degenerate_work_promotes_without_structure(conn):
    wp = {"work_id": "w2", "degenerate": True,
          "spans": [{"text_id": "t2", "label": "All", "slug": "all",
                     "chunk_ids": ["mesopotamian.enuma-elish.001"], "token_count": 50}]}
    _field(conn, "w2", "summary", None, {"body": "intro"})
    _field(conn, "w2", "context", None, {"body": "ctx"})
    _summary(conn, "sum:w2", "w2", "t2", 2, None, ["mesopotamian.enuma-elish.001"], "whole", pv="l1-v1")
    assert pd.promote_work(conn, wp, ("t2",)) is None
    assert json.loads(conn.execute("SELECT structure_json FROM work_dossiers"
                                   " WHERE work_id='w2'").fetchone()[0]) == []
    nodes = conn.execute("SELECT level FROM summary_nodes WHERE work_id='w2'").fetchall()
    assert [n["level"] for n in nodes] == [2]


def test_echo_guard_catches_trailing_verbatim_tail():
    """Review finding: the 7-stride shingle loop skipped the final window,
    letting a verbatim tail (<~21 words) through. The tail window must be
    checked explicitly."""
    import sys
    sys.path.insert(0, "scripts")
    from generate_dossiers import _v_prose
    import pytest

    src = " ".join(f"w{i}" for i in enumerate(range(60))) if False else " ".join(f"w{i}" for i in range(60))
    # 40 original words + the source's last 15 words copied verbatim
    body = " ".join(f"x{i}" for i in range(40)) + " " + " ".join(f"w{i}" for i in range(45, 60))
    with pytest.raises(ValueError, match="verbatim echo"):
        _v_prose(body, 40, 60, src)
