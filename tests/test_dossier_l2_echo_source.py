"""Regression tests for the L2 echo-guard source (todo:84c46b2f).

The 15-word shingle guard in ``_v_prose`` exists to catch a content-filter
dodge at L1 — a "summary" that copies a raw chunk passage verbatim instead of
transforming it. At L2 the stage input is other summaries (already grounded,
condensed prose), so comparing the synthesis output's shingles against the
JOINED SUMMARIES rejected legitimate reuse of a grounded clause: the final
blavatsky-sd L2 failed 6+ attempts on "verbatim echo of input (15-word shingle
match)" before a manual pass with the guard relaxed.

The fix grounds each L2 summary-of-summaries stage against the raw chunk bodies
under the rows it actually synthesizes (``_span_chunk_bodies``) — the whole
work for the final synthesis, one volume for a part, one batch for a fold — so
reusing an input-summary clause is allowed while a raw-passage echo is caught.
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


# A 16-word run that appears in the L1 summaries but NOT in the raw chunk
# bodies — the legitimate paraphrase reuse the old guard wrongly rejected.
SHARED_CLAUSE = ("the primordial monad unfolds through seven successive planes "
                 "into the fully manifested living cosmos and returns")
# A 16-word run that appears in the raw chunk bodies — a genuine raw-passage
# echo the guard must still reject.
RAW_PASSAGE = ("verily the ancient tablet declares that the hidden fire sleeps "
               "beneath the sevenfold mountain until the appointed hour")


def _tok(s: str) -> int:
    return len(s.split())


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
        self.responses = list(responses)

    def _llm(self, system, prompt):
        self.calls += 1
        if not self.responses:
            raise AssertionError("ran out of canned responses")
        return self.responses.pop(0)

    def _preamble(self, wp):
        return "PREAMBLE"


def _l1(db, i: int, cid: str, body: str):
    db.execute(
        "INSERT INTO staged_summaries (summary_id, work_id, text_id, level,"
        " section_span, child_chunk_ids, body, token_count, model,"
        " prompt_version, status)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (f"sum:t:s{i}", "w", "t", 1, f"S{i}", json.dumps([cid]),
         body, _tok(body), "test-model", "l1-v3", "accepted"))


def _wp(*cids: str):
    spans = [{"text_id": "t", "slug": f"s{i}", "label": f"S{i}",
              "chunk_ids": [cid], "token_count": 100}
             for i, cid in enumerate(cids, 1)]
    return {"work_id": "w", "label": "Work W", "tradition": "x",
            "degenerate": False, "spans": spans, "gated_by": None}


def _prose(*, contains: str, filler: int = 100) -> str:
    """A well-formed ~prose synthesis: a 7-word capitalised lead-in, then the
    `contains` clause at a stride-aligned window (index 7, a multiple of the
    guard's stride of 7), then distinct filler that appears in no source."""
    lead = "Across the vast doctrine this synthesis surveys"  # 7 words, capitalised
    tail = " ".join(f"detail{i}" for i in range(filler))
    return f"{lead} {contains} {tail}"


def _ground_by_ids(monkeypatch):
    """Patch _chunk_bodies to a sentinel that records the (sorted, de-duped)
    ids it was asked for, so a test can assert which chunks a stage grounded
    against. The real _span_chunk_bodies (span→chunk-id mapping) still runs."""
    def fake(ids, *, strict=True):
        return "GROUND:" + ",".join(sorted(set(ids)))
    monkeypatch.setattr(gd, "_chunk_bodies", fake)


def test_l2_echo_source_is_the_chunk_bodies_not_the_summary_join(db, monkeypatch):
    """The mechanism: stage_l2 passes the raw chunk bodies to _v_prose as the
    echo source, never the joined input summaries."""
    monkeypatch.setattr(gd, "count_tokens", _tok)
    monkeypatch.setattr(gd, "L2_INPUT_BUDGET", 16_000)
    _ground_by_ids(monkeypatch)

    seen_sources = []

    def spy_v_prose(raw, lo, hi, source=None):
        seen_sources.append(source)
        return raw.strip()

    monkeypatch.setattr(gd, "_v_prose", spy_v_prose)

    _l1(db, 1, "x.t.001", body="Prelude clause. " + SHARED_CLAUSE + " and more.")
    _l1(db, 2, "x.t.002", body="A second grounded volume summary of its sections.")
    gen = FakeGen([_prose(contains=SHARED_CLAUSE)], db)
    gen.stage_l2(_wp("x.t.001", "x.t.002"))

    assert seen_sources == ["GROUND:x.t.001,x.t.002"]   # the work's chunks
    assert SHARED_CLAUSE not in seen_sources[0]          # never the summary join


def test_l2_synthesis_reusing_an_l1_clause_is_accepted(db, monkeypatch):
    """The ticket's exact failure, with the REAL _v_prose: an output that reuses
    a 15-word clause from its input summaries — but not from the raw chunks —
    passes on the first attempt instead of being rejected as a verbatim echo."""
    monkeypatch.setattr(gd, "count_tokens", _tok)
    monkeypatch.setattr(gd, "L2_INPUT_BUDGET", 16_000)
    monkeypatch.setattr(gd, "_chunk_bodies",
                        lambda ids, *, strict=True: "alpha beta gamma delta epsilon " * 40)

    _l1(db, 1, "x.t.001", body="Prelude clause. " + SHARED_CLAUSE + " and more.")
    _l1(db, 2, "x.t.002", body="A second grounded volume summary of its sections.")
    synthesis = _prose(contains=SHARED_CLAUSE)
    gen = FakeGen([synthesis], db)
    gen.stage_l2(_wp("x.t.001", "x.t.002"))

    assert gen.calls == 1                            # accepted first try, no retries
    row = db.execute(
        "SELECT * FROM staged_summaries WHERE summary_id='sum:w'").fetchone()
    assert row is not None and row["body"] == synthesis
    assert row["level"] == 2 and row["prompt_version"] == "l2-v2"


def test_l2_synthesis_echoing_a_raw_chunk_passage_is_still_rejected(db, monkeypatch):
    """The guard's original intent survives: a synthesis that reproduces a raw
    chunk passage verbatim is still caught, so every attempt is rejected and no
    final L2 is staged."""
    monkeypatch.setattr(gd, "count_tokens", _tok)
    monkeypatch.setattr(gd, "L2_INPUT_BUDGET", 16_000)
    monkeypatch.setattr(gd, "_chunk_bodies",
                        lambda ids, *, strict=True: "Chunk body opens. " + RAW_PASSAGE + " end.")

    _l1(db, 1, "x.t.001", body="A grounded first volume summary of its sections.")
    _l1(db, 2, "x.t.002", body="A grounded second volume summary of its sections.")
    # Every attempt echoes the raw passage; _attempt exhausts its retries.
    gen = FakeGen([_prose(contains=RAW_PASSAGE)] * 5, db)
    gen.stage_l2(_wp("x.t.001", "x.t.002"))

    assert gen.calls == gd.MAX_ATTEMPTS + 1          # generate loop, no give-up early
    assert db.execute(
        "SELECT COUNT(*) FROM staged_summaries WHERE summary_id='sum:w'"
    ).fetchone()[0] == 0


_TEST_VOLUMES = [
    {"key": "vol-1", "label": "Vol 1", "url_match": "/sd1-"},
    {"key": "vol-2", "label": "Vol 2", "url_match": "/sd2-"},
]


def _url_for(cid: str) -> str:
    num = cid.rsplit(".", 1)[-1]
    return ("https://x/sd1-.htm" if num in {"001", "003"}
            else "https://x/sd2-.htm" if num in {"002", "004"} else "")


def test_per_part_synthesis_grounds_against_only_its_own_volume(db, monkeypatch):
    """Each volume part is echo-checked against only that volume's chunks, and
    the whole-work final synthesis against every chunk — so a part is never
    rejected for a 15-word run that only appears in a sibling volume it was
    never given (the milder over-rejection the whole-work ground would allow)."""
    monkeypatch.setattr(gd, "count_tokens", _tok)
    monkeypatch.setattr(gd, "L2_INPUT_BUDGET", 100)
    monkeypatch.setattr(gd, "_chunk_source_url", _url_for)
    monkeypatch.setattr(gd, "PARTITION_RULES", {"w": _TEST_VOLUMES})
    _ground_by_ids(monkeypatch)

    seen_sources = []

    def spy_v_prose(raw, lo, hi, source=None):
        seen_sources.append(source)
        return raw.strip()

    monkeypatch.setattr(gd, "_v_prose", spy_v_prose)

    body = " ".join(f"w{i}" for i in range(40))  # 40 words → forces partition
    for i, cid in enumerate(("x.t.001", "x.t.002", "x.t.003", "x.t.004"), 1):
        _l1(db, i, cid, body=body)
    gen = FakeGen(["vol-1 part", "vol-2 part", "final synthesis"], db)
    gen.stage_l2(_wp("x.t.001", "x.t.002", "x.t.003", "x.t.004"))

    # vol-1 = {001,003}, vol-2 = {002,004}, final = all four — order-independent.
    assert sorted(seen_sources) == sorted([
        "GROUND:x.t.001,x.t.003",                       # vol-1 part
        "GROUND:x.t.002,x.t.004",                       # vol-2 part
        "GROUND:x.t.001,x.t.002,x.t.003,x.t.004",       # whole-work final
    ])


def test_chunk_bodies_is_best_effort_when_non_strict(tmp_path, monkeypatch):
    """A readable-but-malformed chunk (bad TOML, or a well-formed file missing
    content/body) must be SKIPPED under strict=False, not crash the synthesis
    stage — and must still be raised under strict=True (the L1 path)."""
    monkeypatch.setattr(gd, "CORPUS_DIR", tmp_path)
    monkeypatch.setattr(gd, "clean_body", lambda s: s)  # identity, assert raw body

    def _chunk(cid: str, text: str):
        trad, doc, num = cid.rsplit(".", 2)
        d = tmp_path / trad / doc / "chunks"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{num}.toml").write_text(text)

    _chunk("x.t.001", '[content]\nbody = "good body text"\n')   # valid
    _chunk("x.t.003", "this = = not valid toml\n")              # bad TOML → ValueError
    _chunk("x.t.004", '[meta]\nnote = "no content table"\n')    # missing content.body → KeyError
    # x.t.002 is never written → missing file → OSError

    ids = ["x.t.001", "x.t.002", "x.t.003", "x.t.004"]
    assert gd._chunk_bodies(ids, strict=False) == "good body text"  # only the good one

    # strict re-raises each failure class rather than silently dropping it.
    with pytest.raises(OSError):
        gd._chunk_bodies(["x.t.002"])          # missing file
    with pytest.raises(KeyError):
        gd._chunk_bodies(["x.t.004"])          # readable, missing content/body


def test_v_prose_warns_when_echo_ground_is_empty(caplog):
    """source="" (every chunk under this call's ground was unreadable) must
    log a warning rather than silently behave as 'no echo check requested' —
    the caller still gets its prose back, but the disabled backstop is
    surfaced instead of failing open in silence."""
    body = "Across the vast doctrine this synthesis surveys " + " ".join(
        f"detail{i}" for i in range(50))
    with caplog.at_level("WARNING"):
        result = gd._v_prose(body, 10, 400, "")
    assert result == body
    assert any("echo guard skipped" in r.message for r in caplog.records)


def test_v_prose_no_warning_when_echo_check_not_requested(caplog):
    """source=None (the default) is a genuine 'no echo check' call site, not a
    degraded one — no warning should fire."""
    body = "Across the vast doctrine this synthesis surveys " + " ".join(
        f"detail{i}" for i in range(50))
    with caplog.at_level("WARNING"):
        result = gd._v_prose(body, 10, 400, None)
    assert result == body
    assert not any("echo guard skipped" in r.message for r in caplog.records)


def test_lazy_ground_defers_and_caches():
    """_lazy_ground must not call its producer until first .get(), and must
    call it at most once even across repeated .get()s (the retry-loop case:
    _stage_l2_from/_stage_fold invoke echo_src() once per attempt)."""
    calls = []

    def producer():
        calls.append(1)
        return "the ground text"

    thunk = gd._lazy_ground(producer)
    assert calls == []                 # not called at wrap time
    assert thunk() == "the ground text"
    assert thunk() == "the ground text"
    assert thunk() == "the ground text"
    assert len(calls) == 1             # only ever read once


def test_stage_l2_from_over_budget_refusal_never_reads_the_ground(db, monkeypatch):
    """An echo_src producer wrapped in _lazy_ground must not run at all when
    _stage_l2_from refuses before ever consulting it (the over-budget early
    return) — the disk read this guards against must not happen."""
    monkeypatch.setattr(gd, "count_tokens", _tok)
    monkeypatch.setattr(gd, "L2_INPUT_BUDGET", 5)  # anything will overflow this

    def boom():
        raise AssertionError("echo ground was read despite the over-budget refusal")

    _l1(db, 1, "x.t.001", body="A first volume summary far past the tiny budget.")
    gen = FakeGen([], db)
    ok = gen._stage_l2_from(_wp("x.t.001"), "sum:w", None,
                            [db.execute("SELECT * FROM staged_summaries").fetchone()],
                            "l2-v2", level=2, echo_src=gd._lazy_ground(boom))
    assert ok is False
    assert gen.calls == 0
