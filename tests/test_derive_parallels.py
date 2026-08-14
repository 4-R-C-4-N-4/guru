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

from derive_parallels import (  # noqa: E402
    build_edges,
    build_panels,
    build_ranked,
    cache_key,
    chunk_text_id,
    content_hash,
    first_sentence,
    format_label,
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
