"""Regression tests for hierarchical L2 (todo:64c54b6c).

Naive stage_l2 joined every accepted L1 into one prompt. blavatsky-sd's
192 L1s are 101k tokens against a 24k ctx. The fix partitions by the
work's natural structure (source_url /sd1- vs /sd2- — NOT span-plan
order, which interleaves volumes), stages intermediate l2-v2-part rows,
budget-packs leftovers as level-0 folds, then synthesizes sum:{work_id}.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location(
    "generate_dossiers", PROJECT_ROOT / "scripts" / "generate_dossiers.py")
gd = importlib.util.module_from_spec(_spec)
sys.modules["generate_dossiers"] = gd
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
_spec.loader.exec_module(gd)

L2_OK = "Whole-work synthesis covering every named section in order."
PART_OK = "Volume-level summary of these consecutive sections."
FOLD_OK = "Folded stretch of consecutive section summaries."


@pytest.fixture()
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE staged_summaries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        summary_id TEXT, work_id TEXT, text_id TEXT, level INTEGER,
        section_span TEXT, child_chunk_ids TEXT, child_summary_ids TEXT,
        body TEXT, token_count INTEGER, model TEXT, prompt_version TEXT,
        status TEXT DEFAULT 'pending')""")
    yield conn


class FakeGen(gd.Generator):
    def __init__(self, responses, conn):
        self.cfg = {"provider": "test", "model": "test-model"}
        self.conn = conn
        self.plan = {"works": []}
        self.limit = 0
        self.calls = 0
        self.prompts = []
        self.inserted = []
        self.responses = list(responses)

    def _llm(self, system, prompt):
        self.calls += 1
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("ran out of canned responses")
        return self.responses.pop(0)

    def _preamble(self, wp):
        return "PREAMBLE"

    def _insert_summary(self, summary_id, wp, text_id, level, span, chunk_ids,
                        child_sids, body, pv):
        self.inserted.append((summary_id, pv, level, span,
                              list(child_sids) if child_sids else None))
        super()._insert_summary(summary_id, {"work_id": "w"}, text_id, level,
                                span, chunk_ids, child_sids, body, pv)


def _fake_v_prose(raw, lo, hi, source=None):
    body = raw.strip()
    if not body:
        raise ValueError("empty prose")
    return body


def _tok(s: str) -> int:
    return len(s.split())


def _input_tok(prompt: str) -> int:
    marker = "---\nINPUT:\n\n"
    if marker not in prompt:
        return 0
    return _tok(prompt.split(marker, 1)[1])


def _body(n: int) -> str:
    return " ".join(f"w{i}" for i in range(n))


def _span(i: int, cid: str) -> dict:
    return {"text_id": "t", "slug": f"s{i}", "label": f"S{i}",
            "chunk_ids": [cid], "token_count": 100}


def _l1(db, i: int, cid: str, words: int = 40, status: str = "accepted"):
    db.execute(
        "INSERT INTO staged_summaries (summary_id, work_id, text_id, level,"
        " section_span, child_chunk_ids, body, token_count, model,"
        " prompt_version, status)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (f"sum:t:s{i}", "w", "t", 1, f"S{i}", json.dumps([cid]),
         _body(words), words, "test-model", "l1-v3", status))


def _url_for(cid: str) -> str:
    num = cid.rsplit(".", 1)[-1]
    if num in {"001", "003", "005"}:
        return "https://www.sacred-texts.com/the/sd/sd1-1-01.htm"
    if num in {"002", "004", "006"}:
        return "https://www.sacred-texts.com/the/sd/sd2-1-01.htm"
    return ""


def patch_common(monkeypatch, budget: int = 100):
    monkeypatch.setattr(gd, "L2_INPUT_BUDGET", budget)
    monkeypatch.setattr(gd, "count_tokens", _tok)
    monkeypatch.setattr(gd, "_v_prose", _fake_v_prose)
    monkeypatch.setattr(gd, "_chunk_source_url", _url_for)


def _wp(*cids: str) -> dict:
    spans = [_span(i, cid) for i, cid in enumerate(cids, 1)]
    return {"work_id": "w", "label": "Work W", "tradition": "x",
            "degenerate": False, "spans": spans, "gated_by": None}


def test_small_work_keeps_naive_single_l2(db, monkeypatch):
    patch_common(monkeypatch, budget=16_000)
    _l1(db, 1, "x.t.001", words=5)
    _l1(db, 2, "x.t.002", words=5)
    gen = FakeGen([L2_OK], db)
    gen.stage_l2(_wp("x.t.001", "x.t.002"))
    assert gen.calls == 1
    assert gen.inserted == [("sum:w", "l2-v2", 2, None, ["sum:t:s1", "sum:t:s2"])]
    row = db.execute("SELECT * FROM staged_summaries WHERE summary_id='sum:w'").fetchone()
    assert row["prompt_version"] == "l2-v2"
    assert row["level"] == 2


def test_two_volume_parts_then_final(db, monkeypatch):
    """Interleaved plan order still clusters by source_url volume."""
    patch_common(monkeypatch, budget=100)
    for i, cid in enumerate(("x.t.001", "x.t.002", "x.t.003", "x.t.004"), 1):
        _l1(db, i, cid, words=40)
    gen = FakeGen([PART_OK, PART_OK, L2_OK], db)
    gen.stage_l2(_wp("x.t.001", "x.t.002", "x.t.003", "x.t.004"))
    assert gen.calls == 3
    sids = [t[0] for t in gen.inserted]
    assert sids == ["sum:w:vol-1", "sum:w:vol-2", "sum:w"]
    pvs = {t[0]: t[1] for t in gen.inserted}
    assert pvs["sum:w:vol-1"] == "l2-v2-part"
    assert pvs["sum:w"] == "l2-v2"
    vol1 = next(t for t in gen.inserted if t[0] == "sum:w:vol-1")
    assert vol1[3] == "Vol 1 Cosmogenesis"
    assert vol1[4] == ["sum:t:s1", "sum:t:s3"]  # not plan-adjacent s1,s2
    final = next(t for t in gen.inserted if t[0] == "sum:w")
    assert final[4] == ["sum:w:vol-1", "sum:w:vol-2"]
    for p in gen.prompts:
        assert _input_tok(p) <= 100


def test_overbudget_volume_gets_inner_folds(db, monkeypatch):
    patch_common(monkeypatch, budget=100)
    # vol-1: three 40-word L1s → two folds then a part L2
    # vol-2: one 40-word L1 → direct part L2
    for i, cid in enumerate(("x.t.001", "x.t.003", "x.t.005", "x.t.002"), 1):
        _l1(db, i, cid, words=40)
    gen = FakeGen([FOLD_OK, FOLD_OK, PART_OK, PART_OK, L2_OK], db)
    gen.stage_l2(_wp("x.t.001", "x.t.003", "x.t.005", "x.t.002"))
    by_id = {t[0]: t for t in gen.inserted}
    assert "fold:w:vol-1:1" in by_id and "fold:w:vol-1:2" in by_id
    assert by_id["fold:w:vol-1:1"][2] == 0
    assert by_id["fold:w:vol-1:1"][1] == "fold-v1"
    assert by_id["sum:w:vol-1"][4] == ["fold:w:vol-1:1", "fold:w:vol-1:2"]
    assert by_id["sum:w:vol-2"][4] == ["sum:t:s4"]
    assert by_id["sum:w"][4] == ["sum:w:vol-1", "sum:w:vol-2"]
    for p in gen.prompts:
        assert _input_tok(p) <= 100


def test_stage_l2_skips_when_final_already_exists(db, monkeypatch):
    patch_common(monkeypatch, budget=100)
    for i, cid in enumerate(("x.t.001", "x.t.002"), 1):
        _l1(db, i, cid, words=40)
    db.execute(
        "INSERT INTO staged_summaries (summary_id, work_id, text_id, level,"
        " section_span, body, token_count, model, prompt_version, status)"
        " VALUES ('sum:w','w','t',2,NULL,'final',10,'test-model','l2-v2','pending')")
    gen = FakeGen([], db)
    gen.stage_l2(_wp("x.t.001", "x.t.002"))
    assert gen.calls == 0
    assert gen.inserted == []


def test_idempotent_rerun_does_not_regenerate_parts(db, monkeypatch):
    patch_common(monkeypatch, budget=100)
    for i, cid in enumerate(("x.t.001", "x.t.002", "x.t.003", "x.t.004"), 1):
        _l1(db, i, cid, words=40)
    gen = FakeGen([PART_OK, PART_OK, L2_OK], db)
    wp = _wp("x.t.001", "x.t.002", "x.t.003", "x.t.004")
    gen.stage_l2(wp)
    n = db.execute("SELECT COUNT(*) FROM staged_summaries WHERE level!=1").fetchone()[0]
    gen2 = FakeGen([PART_OK, PART_OK, L2_OK], db)
    gen2.stage_l2(wp)
    assert gen2.calls == 0
    n2 = db.execute("SELECT COUNT(*) FROM staged_summaries WHERE level!=1").fetchone()[0]
    assert n2 == n


def test_accepted_l2_pins_to_final_not_volume_part(db):
    db.execute(
        "INSERT INTO staged_summaries (summary_id, work_id, text_id, level,"
        " section_span, body, token_count, model, prompt_version, status)"
        " VALUES ('sum:w:vol-1','w','t',2,'Vol 1','volume body',10,"
        " 'test-model','l2-v2-part','accepted')")
    db.execute(
        "INSERT INTO staged_summaries (summary_id, work_id, text_id, level,"
        " section_span, body, token_count, model, prompt_version, status)"
        " VALUES ('sum:w','w','t',2,NULL,'final body',10,"
        " 'test-model','l2-v2','accepted')")
    row = gd._accepted_l2(db, "w")
    assert row["summary_id"] == "sum:w"
    assert row["body"] == "final body"


def test_stage_l2_defers_when_l1s_incomplete(db, monkeypatch):
    patch_common(monkeypatch, budget=100)
    _l1(db, 1, "x.t.001", words=40)
    gen = FakeGen([L2_OK], db)
    gen.stage_l2(_wp("x.t.001", "x.t.002"))
    assert gen.calls == 0
    assert db.execute(
        "SELECT COUNT(*) FROM staged_summaries WHERE level=2").fetchone()[0] == 0
