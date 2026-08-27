"""Regression tests for fold-path degradation (todo:6d141319).

Live evidence (blavatsky-sd c12): 25 spans hard-fail generate->compress —
the compressor itself returns 1000+ tokens against a [120, 720] band. The
fix splits the span at chunk boundaries into sub-batches, L1-summarizes
each, merges through compress-v1, and stages under '{L1_TPL}-folded' so D3
reviewers see the degraded provenance.

Note on scopes: tests calling _fold_l1 directly supply ONLY the fold's own
calls — the outer generate->compress failure has already happened by then.
"""
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

import build_dossiers as bd  # noqa: E402  (already on sys.path via gd's imports)

OVER = "word " * 800          # always outside every sanity band
SUB_OK = ("Sub summary prose about the section. ") * 20   # ~100 words
MERGED = ("Merged final summary of all parts. ") * 40     # ~280 words


# ── fixtures ──────────────────────────────────────────────────────────────────

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
    """Generator stand-in with canned _llm responses; no real provider."""

    def __init__(self, responses, conn):
        self.cfg = {"provider": "test", "model": "test-model"}
        self.conn = conn
        self.plan = {"works": []}
        self.limit = 0
        self.calls = 0
        self.prompts = []
        self.responses = list(responses)
        self.inserted = []

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
        self.inserted.append((summary_id, pv))
        super()._insert_summary(summary_id, {"work_id": "w"}, text_id, level,
                                span, chunk_ids, child_sids, body, pv)


SPAN = {"text_id": "t", "slug": "s1", "label": "Sec I",
        "chunk_ids": ["x.t.001", "x.t.002", "x.t.003", "x.t.004"],
        "token_count": 4800}   # budget 300 → n=16 → packed to 4 parts
WP = {"work_id": "w", "label": "Work W", "tradition": "x",
      "degenerate": False, "spans": [SPAN], "gated_by": None}


def patch_corpus(monkeypatch):
    monkeypatch.setattr(bd, "load_text_chunks",
                        lambda trad, tid: [bd.Chunk(f"x.t.{i:03d}", None, 1200,
                                                    f"p{i}") for i in range(1, 5)])
    # keep _budget_pack REAL — it is a primitive under reuse
    monkeypatch.setattr(gd, "_chunk_bodies", lambda ids, **_: "body text " * 50)
    # Deterministic stand-in for the prose contract: word-count band only.
    # The real _v_prose depends on the tokenizer, which makes canned fixtures
    # brittle; the machinery under test only needs a band and an echo source.
    monkeypatch.setattr(gd, "_v_prose", _fake_v_prose)


def _fake_v_prose(raw, lo, hi, source=None):
    body = raw.strip()
    n = len(body.split())
    if not (lo * 0.5 <= n <= hi * 2):
        raise ValueError(f"prose length {n} outside sanity band [{lo}, {hi}]")
    return body


def sid_of(span):
    return f"sum:{span['text_id']}:{span['slug']}"


# ── tests ─────────────────────────────────────────────────────────────────────

def test_fold_triggers_and_stages_folded_pv(db, monkeypatch):
    """_fold_l1 splits into sub-batches, L1s each, merges once, and stages
    under '{L1_TPL}-folded' with the full original chunk list."""
    patch_corpus(monkeypatch)
    gen = FakeGen([SUB_OK, SUB_OK, SUB_OK, SUB_OK, MERGED], db)  # 4 subs + merge
    ok = gen._fold_l1(WP, SPAN, sid_of(SPAN))
    assert ok is True
    assert gen.inserted == [(sid_of(SPAN), "l1-v3-folded")]
    assert gen.calls == 5
    # merge call carries all sub-summaries labeled Part n through compress tpl
    merge_prompt = gen.prompts[-1]
    assert "Part 1:" in merge_prompt and "Part 3:" in merge_prompt
    row = db.execute("SELECT * FROM staged_summaries").fetchone()
    assert row["prompt_version"] == "l1-v3-folded"
    assert json.loads(row["child_chunk_ids"]) == SPAN["chunk_ids"]


def test_fold_actually_splits_at_chunk_boundaries(db, monkeypatch):
    patch_corpus(monkeypatch)
    gen = FakeGen([SUB_OK] * 4 + [MERGED], db)
    assert gen._fold_l1(WP, SPAN, sid_of(SPAN))
    sub_prompts = [p for p in gen.prompts if "INPUT:" in p]
    assert len(sub_prompts) == 4  # really split at chunk boundaries


def test_single_chunk_span_gives_up_without_folding(db, monkeypatch):
    """No split point → no fold attempt, returns False (matches the
    one-degradation-level guardrail from the ticket)."""
    patch_corpus(monkeypatch)
    span = dict(SPAN, chunk_ids=["x.t.001"])
    gen = FakeGen([], db)
    assert gen._fold_l1(WP, span, sid_of(span)) is False
    assert gen.calls == 0
    assert db.execute("SELECT COUNT(*) FROM staged_summaries").fetchone()[0] == 0


def test_failed_subbatch_aborts_without_staging(db, monkeypatch):
    """A sub-batch that itself fails terminates the fold; nothing staged."""
    patch_corpus(monkeypatch)
    gen = FakeGen([OVER, OVER], db)  # sub 1 fails generate -> compress
    ok = gen._fold_l1(WP, SPAN, sid_of(SPAN))
    assert ok is False
    assert db.execute("SELECT COUNT(*) FROM staged_summaries").fetchone()[0] == 0


def test_merged_output_still_overrun_gives_up(db, monkeypatch):
    """One degradation level only: merged output violating the band → give up,
    no recursive folding."""
    patch_corpus(monkeypatch)
    gen = FakeGen([SUB_OK, SUB_OK, SUB_OK, OVER, OVER], db)
    assert gen._fold_l1(WP, SPAN, sid_of(SPAN)) is False
    assert db.execute("SELECT COUNT(*) FROM staged_summaries").fetchone()[0] == 0
    assert gen.calls == 5  # 3 subs + 2 merge (generate -> compress -> give up)


def test_stage_l1_skips_already_folded_span_on_rerun(db):
    """Companion fix: the plain l1-v3 exists-check does NOT match a
    'l1-v3-folded' row — without the second probe every re-run repeats the
    full generate->compress->fold sequence for an already-folded span."""
    db.execute("INSERT INTO staged_summaries (summary_id, work_id, text_id,"
               " level, section_span, child_chunk_ids, body, token_count,"
               " model, prompt_version)"
               " VALUES ('sum:t:s1','w','t',1,'Sec I','[]','body',4,"
               " 'test-model','l1-v3-folded')")
    wp = {**WP, "spans": [dict(SPAN)]}
    gen = FakeGen([], db)
    gen.stage_l1(wp)
    assert gen.calls == 0  # skipped entirely — no regeneration of either kind


# A 15-word run that appears in every sub-summary — legitimate reuse in the
# merge, since it never appears in the raw chunk ground below.
SUB_CLAUSE = ("returns through veiled correspondences to the same primordial "
             "source of all creation before circling back")
# A 15-word run that appears in the raw chunk ground — a genuine echo the
# merge step must still reject regardless of its source.
RAW_CLAUSE = ("verily the ancient tablet declares that the hidden fire sleeps "
             "beneath the sevenfold mountain until the appointed hour arrives")


def _bump(clause: str, filler_n: int) -> str:
    # 7-word capitalised lead so `clause` lands at word index 7 — one of the
    # shingle guard's stride-7 check windows.
    lead = "Sub summary prose that surveys the section"
    tail = " ".join(f"detail{i}" for i in range(filler_n))
    return f"{lead} {clause} {tail}"


def patch_corpus_with_raw_ground(monkeypatch, raw_ground: str):
    monkeypatch.setattr(bd, "load_text_chunks",
                        lambda trad, tid: [bd.Chunk(f"x.t.{i:03d}", None, 1200,
                                                    f"p{i}") for i in range(1, 5)])
    monkeypatch.setattr(gd, "_chunk_bodies", lambda ids, **_: raw_ground)
    # real _v_prose (not the fake word-count stand-in) so the shingle guard
    # actually runs against the ground text this test cares about


def test_fold_merge_accepts_reuse_of_a_sub_summary_clause(db, monkeypatch):
    """The merge pass (todo:84c46b2f follow-up) echo-checks against the span's
    raw chunk bodies, not the joined sub-summaries: a clause repeated across
    the 4 canned sub-summaries — which would echo-match the OLD join-based
    ground — is legitimate synthesis reuse and must be accepted when it does
    not appear in the raw chunk ground."""
    raw_ground = "Chunk ground text with no overlap at all in this passage."
    patch_corpus_with_raw_ground(monkeypatch, raw_ground)
    sub_body = _bump(SUB_CLAUSE, filler_n=80)
    merged = _bump(SUB_CLAUSE, filler_n=220)
    gen = FakeGen([sub_body, sub_body, sub_body, sub_body, merged], db)
    assert gen._fold_l1(WP, SPAN, sid_of(SPAN)) is True
    assert gen.inserted == [(sid_of(SPAN), "l1-v3-folded")]


def test_fold_merge_still_rejects_a_genuine_raw_chunk_echo(db, monkeypatch):
    """The guard's original intent survives: a merged output that echoes a raw
    chunk passage verbatim is still caught, even though it never appeared in
    any sub-summary the merge was given."""
    raw_ground = "Chunk ground opens here. " + RAW_CLAUSE + " and the chunk ends."
    patch_corpus_with_raw_ground(monkeypatch, raw_ground)
    sub_body = _bump(SUB_CLAUSE, filler_n=80)
    merged_echo = _bump(RAW_CLAUSE, filler_n=220)
    gen = FakeGen([sub_body, sub_body, sub_body, sub_body,
                   merged_echo, merged_echo, merged_echo], db)
    assert gen._fold_l1(WP, SPAN, sid_of(SPAN)) is False
    assert db.execute("SELECT COUNT(*) FROM staged_summaries").fetchone()[0] == 0


def test_stage_l1_falls_through_to_fold_when_attempt_returns_none(db, monkeypatch):
    """stage_l1 wiring: outer generate->compress fails → _fold_l1 runs and
    stages the folded row."""
    patch_corpus(monkeypatch)
    gen = FakeGen([OVER, OVER,                 # outer generate -> compress fail
                   SUB_OK, SUB_OK, SUB_OK, SUB_OK, MERGED], db)
    gen.stage_l1({**WP, "spans": [dict(SPAN)]})
    rows = db.execute("SELECT summary_id, prompt_version FROM staged_summaries"
                      ).fetchall()
    assert [(r["summary_id"], r["prompt_version"]) for r in rows] \
        == [("sum:t:s1", "l1-v3-folded")]
