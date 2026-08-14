"""tests/test_derive_parallels.py — pure-logic coverage for
scripts/derive_parallels.py (todo:5620391a).

Covers the parts ported from rellm tools/derived_parallels.py (partner-score
ranking, via round-robin, annotation formatting) plus the two knobs this
ticket adds (per-work panel cap, deterministic ordering) — all against
fixture score dicts, no model and no DB required.

Determinism matters here specifically because the prototype built its
round-robin and per-chunk panels by iterating Python `set`/`dict` objects
whose order is not guaranteed stable across runs (string hash randomization).
The ported version replaces every such iteration with an explicit sort key;
these tests pin the resulting order, not just set membership, so a
regression back to unordered iteration would show up as a flaky test rather
than a silent reshuffle in production output.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import derive_parallels as dp  # noqa: E402
from derive_parallels import (  # noqa: E402
    build_edges,
    build_panels,
    build_ranked,
    cache_key,
    chunk_text_id,
    content_hash,
    exclude_apparatus_chunks,
    first_sentence,
    format_label,
    score_needed_pairs,
)


# ── formatting helpers ──────────────────────────────────────────────────────

def test_first_sentence_splits_on_first_period():
    assert first_sentence("First bit. Second bit.") == "First bit"


def test_first_sentence_no_period_returns_whole_string():
    assert first_sentence("No terminal punctuation here") == "No terminal punctuation here"


def test_format_label_title_cases_and_strips_prefix():
    assert format_label("concept.emanation_hierarchy") == "Emanation Hierarchy"


def test_chunk_text_id_middle_segment():
    assert chunk_text_id("gnosticism.gospel-of-thomas.001") == "gospel-of-thomas"


# ── score cache ──────────────────────────────────────────────────────────────

def test_content_hash_stable_for_same_inputs():
    assert content_hash("def", "body") == content_hash("def", "body")


def test_content_hash_changes_with_body():
    assert content_hash("def", "body one") != content_hash("def", "body two")


def test_content_hash_changes_with_definition():
    assert content_hash("def one", "body") != content_hash("def two", "body")


def test_cache_key_format():
    assert cache_key("concept.x", "trad.text.001") == "concept.x|trad.text.001"


# ── ranking ──────────────────────────────────────────────────────────────────

def test_build_ranked_orders_by_score_desc_then_id():
    bycon = {"concept.x": {"b.t.001", "a.t.001", "c.t.001"}}
    score = {
        ("concept.x", "a.t.001"): 1.0,
        ("concept.x", "b.t.001"): 3.0,
        ("concept.x", "c.t.001"): 3.0,  # ties with b -> id tiebreak
    }
    ranked = build_ranked(bycon, score)
    assert ranked["concept.x"] == ["b.t.001", "c.t.001", "a.t.001"]


def test_build_ranked_missing_score_sorts_last():
    bycon = {"concept.x": {"scored.t.001", "unscored.t.001"}}
    score = {("concept.x", "scored.t.001"): -10.0}
    ranked = build_ranked(bycon, score)
    assert ranked["concept.x"] == ["scored.t.001", "unscored.t.001"]


# ── panels: anchor gate, round-robin, tradition/self exclusion ──────────────

ANCHOR = "trad_a.anchor.001"
SAME_TRAD = "trad_a.other.001"   # higher score than every real partner, but excluded (same tradition)
P1 = "trad_b.p.001"
P2 = "trad_b.p.002"
Q1 = "trad_c.q.001"
Q2 = "trad_c.q.002"


def _round_robin_fixture():
    bycon = {
        "concept.x": {ANCHOR, SAME_TRAD, P1, P2},
        "concept.y": {ANCHOR, Q1, Q2},
        "concept.z": {ANCHOR, "trad_d.r.001"},  # anchor fails the gate on z
    }
    bychunk = {ANCHOR: {"concept.x", "concept.y", "concept.z"}}
    score = {
        ("concept.x", ANCHOR): 2.0,      # clears min_grade -> concept.x is a via
        ("concept.x", SAME_TRAD): 6.0,   # best score of all, but same tradition as anchor
        ("concept.x", P1): 5.0,
        ("concept.x", P2): 4.0,
        ("concept.y", ANCHOR): 2.0,      # clears min_grade -> concept.y is a via
        ("concept.y", Q1): 3.0,
        ("concept.y", Q2): 2.5,
        ("concept.z", ANCHOR): 0.0,      # below min_grade -> concept.z is NOT a via
        ("concept.z", "trad_d.r.001"): 9.0,  # would dominate the panel if the gate didn't hold
    }
    trad_of = {
        ANCHOR: "trad_a", SAME_TRAD: "trad_a",
        P1: "trad_b", P2: "trad_b",
        Q1: "trad_c", Q2: "trad_c",
        "trad_d.r.001": "trad_d",
    }
    ranked = build_ranked(bycon, score)
    return bychunk, ranked, score, trad_of


def test_build_panels_round_robin_alternates_via_concepts_deterministically():
    bychunk, ranked, score, trad_of = _round_robin_fixture()
    panels = build_panels(
        bychunk, ranked, score, trad_of, work_of_chunk=chunk_text_id,
        min_grade=1.0, top_k=2, per_work_cap=10,
    )
    got = panels[ANCHOR]
    partners = [p for p, _via, _g in got]
    # SAME_TRAD never appears (same tradition as anchor) despite the highest
    # raw score; ANCHOR itself never appears; concept.z contributes nothing
    # (anchor's own z-score is below min_grade, so z never becomes a via).
    assert SAME_TRAD not in partners
    assert ANCHOR not in partners
    assert "trad_d.r.001" not in partners
    # Weight-desc order with a stable tiebreak, drawn round-robin across
    # both surviving via concepts (x and y interleave rather than draining
    # one concept before the other is touched).
    assert got == [
        (P1, "concept.x", 5.0),
        (P2, "concept.x", 4.0),
        (Q1, "concept.y", 3.0),
        (Q2, "concept.y", 2.5),
    ]


def test_build_panels_per_work_cap_thins_a_monoculture():
    w1c1, w1c2, w1c3, w2c1 = (
        "trad_b.w1.001", "trad_b.w1.002", "trad_b.w1.003", "trad_b.w2.001",
    )
    bycon = {"concept.x": {ANCHOR, w1c1, w1c2, w1c3, w2c1}}
    bychunk = {ANCHOR: {"concept.x"}}
    score = {
        ("concept.x", ANCHOR): 5.0,
        ("concept.x", w1c1): 9.0,
        ("concept.x", w1c2): 8.0,
        ("concept.x", w1c3): 7.0,  # same work as w1c1/w1c2 -> capped out
        ("concept.x", w2c1): 6.0,
    }
    trad_of = {ANCHOR: "trad_a", w1c1: "trad_b", w1c2: "trad_b",
               w1c3: "trad_b", w2c1: "trad_b"}
    ranked = build_ranked(bycon, score)

    # w1c1/w1c2/w1c3 share a work; w2c1 is its own work.
    work_map = {w1c1: "w1", w1c2: "w1", w1c3: "w1", w2c1: "w2"}

    panels = build_panels(
        bychunk, ranked, score, trad_of, work_of_chunk=work_map.get,
        min_grade=1.0, top_k=4, per_work_cap=2,
    )
    partners = [p for p, _via, _g in panels[ANCHOR]]
    assert partners == [w1c1, w1c2, w2c1]  # w1c3 dropped: work "w1" already at cap
    assert w1c3 not in partners


# ── edges: dedup + annotation formatting + final ordering ───────────────────

def test_build_edges_shape_annotation_and_dedup():
    defs = {
        "concept.x": "Definition of x is short. Second sentence ignored.",
        "concept.y": "Y def, one sentence",
    }
    a, b, c = "trad_a.t1.001", "trad_b.t2.001", "trad_c.t3.001"
    panels = {
        a: [(b, "concept.x", 5.0), (c, "concept.y", 3.0)],
        b: [(a, "concept.x", 5.0)],  # symmetric duplicate of the a->b pair
    }
    rows = build_edges(panels, defs)

    assert rows == [
        {
            "source": a, "target": b, "edge_type": "PARALLELS",
            "tier": "inferred", "weight": 5.0,
            "annotation": "Shared concept: X — Definition of x is short. (derived)",
        },
        {
            "source": a, "target": c, "edge_type": "PARALLELS",
            "tier": "inferred", "weight": 3.0,
            "annotation": "Shared concept: Y — Y def, one sentence. (derived)",
        },
    ]


# ── apparatus exclusion (todo:495577b7) ──────────────────────────────────────


def test_exclude_apparatus_chunks_drops_from_bychunk():
    bycon = {"concept.x": {"a.t.001", "a.t.002"}}
    bychunk = {"a.t.001": {"concept.x"}, "a.t.002": {"concept.x"}}
    got_bycon, got_bychunk = exclude_apparatus_chunks(bycon, bychunk, {"a.t.001"})
    assert "a.t.001" not in got_bychunk
    assert "a.t.002" in got_bychunk


def test_exclude_apparatus_chunks_drops_from_bycon_partner_pool():
    """An apparatus chunk must never be pickable as anyone else's partner,
    even though it isn't itself an anchor."""
    bycon = {"concept.x": {"good.t.001", "apparatus.t.001"}}
    bychunk = {"good.t.001": {"concept.x"}}
    got_bycon, got_bychunk = exclude_apparatus_chunks(bycon, bychunk, {"apparatus.t.001"})
    assert got_bycon["concept.x"] == {"good.t.001"}


def test_exclude_apparatus_chunks_drops_concept_with_no_survivors():
    bycon = {"concept.x": {"apparatus.t.001"}}
    bychunk = {}
    got_bycon, _ = exclude_apparatus_chunks(bycon, bychunk, {"apparatus.t.001"})
    assert "concept.x" not in got_bycon


def test_exclude_apparatus_chunks_empty_set_is_a_no_op():
    bycon = {"concept.x": {"a.t.001"}}
    bychunk = {"a.t.001": {"concept.x"}}
    got_bycon, got_bychunk = exclude_apparatus_chunks(bycon, bychunk, set())
    assert got_bycon == bycon
    assert got_bychunk == bychunk


def test_load_apparatus_chunks_gates_on_applied_status_only():
    """'pending' is queue-only (owner hasn't applied yet) and must not gate
    the generator; only status='apparatus' is a fact."""
    import sqlite3

    from derive_parallels import load_apparatus_chunks

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE staged_cleanups (chunk_id TEXT, status TEXT)")
    conn.execute("INSERT INTO staged_cleanups VALUES ('a.t.001', 'apparatus')")
    conn.execute("INSERT INTO staged_cleanups VALUES ('a.t.002', 'pending')")
    conn.execute("INSERT INTO staged_cleanups VALUES ('a.t.003', 'rejected')")
    conn.commit()
    assert load_apparatus_chunks(conn) == {"a.t.001"}


# ── score cache periodic flush (PR #64 review finding 3) ─────────────────

def test_score_needed_pairs_flushes_cache_periodically(monkeypatch, tmp_path):
    """An interrupted cold run must not lose everything: save_score_cache
    must be called from inside the scoring loop, not just once at the very
    end (which is run()'s job, not score_needed_pairs()'s)."""
    monkeypatch.setattr(dp, "SCORE_CACHE_FLUSH_EVERY", 2)

    def fake_score_pairs(query, bodies):
        return {ch: 1.0 for ch in bodies}
    monkeypatch.setattr("guru.rerank.score_pairs", fake_score_pairs)

    flush_calls = []
    def fake_save(path, cache):
        flush_calls.append((path, dict(cache)))
    monkeypatch.setattr(dp, "save_score_cache", fake_save)

    n = 5  # 5 concepts, one chunk each -> flushes after concepts 2 and 4
    need = [(f"concept.c{i}", f"trad.t.{i:03d}") for i in range(n)]
    defs = {f"concept.c{i}": f"def{i}" for i in range(n)}
    bodies = {f"trad.t.{i:03d}": f"body{i}" for i in range(n)}
    cache_path = tmp_path / "score_cache.json"

    score = score_needed_pairs(need, defs, bodies, {}, "model-path", cache_path=cache_path)

    assert len(score) == n
    assert len(flush_calls) == 2  # floor(5 / 2)
    for path, _cache in flush_calls:
        assert path == cache_path
    # the first flush caught only what had been scored by then, not everything
    assert len(flush_calls[0][1]) < n


def test_score_needed_pairs_no_cache_path_never_flushes_mid_loop(monkeypatch):
    """cache_path=None (the default) must not attempt to flush — callers
    that don't pass it (e.g. a future direct caller) get the old
    end-of-function-only behavior, not a crash on a None path."""
    monkeypatch.setattr(dp, "SCORE_CACHE_FLUSH_EVERY", 1)

    def fake_score_pairs(query, bodies):
        return {ch: 1.0 for ch in bodies}
    monkeypatch.setattr("guru.rerank.score_pairs", fake_score_pairs)

    flush_calls = []
    monkeypatch.setattr(dp, "save_score_cache", lambda *a: flush_calls.append(a))

    need = [("concept.c0", "trad.t.000")]
    defs = {"concept.c0": "def0"}
    bodies = {"trad.t.000": "body0"}

    score = score_needed_pairs(need, defs, bodies, {}, "model-path")  # no cache_path

    assert len(score) == 1
    assert flush_calls == []


def test_score_needed_pairs_fully_cached_skips_model_and_flush(monkeypatch, tmp_path):
    """A pair whose cache entry matches the current content hash must not
    hit the model or trigger a flush — flush only fires when there was
    something new to save."""
    monkeypatch.setattr(dp, "SCORE_CACHE_FLUSH_EVERY", 1)

    def _unreachable(*a, **k):
        raise AssertionError("model should not be called for a fully cached pair")
    monkeypatch.setattr("guru.rerank.score_pairs", _unreachable)
    flush_calls = []
    monkeypatch.setattr(dp, "save_score_cache", lambda *a: flush_calls.append(a))

    h = content_hash("def0", "body0")
    cache = {cache_key("concept.c0", "trad.t.000"): {"score": 9.0, "hash": h}}

    score = score_needed_pairs(
        [("concept.c0", "trad.t.000")], {"concept.c0": "def0"}, {"trad.t.000": "body0"},
        cache, "model-path", cache_path=tmp_path / "score_cache.json",
    )

    assert score == {("concept.c0", "trad.t.000"): 9.0}
    assert flush_calls == []
