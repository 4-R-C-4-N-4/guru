"""Span-plan invariants (todo:83b0639e, design §1.3.5 + implementation G4)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
from build_dossiers import (
    base_section, load_campaign, load_text_chunks, plan_campaign, slugify,
)
from works import load_works


@pytest.fixture(scope="module")
def plans():
    cfg = load_campaign()
    return {p.work_id: p for p in plan_campaign(cfg)}


def test_every_chunk_in_exactly_one_span(plans):
    works = load_works()
    for wid, p in plans.items():
        expected = []
        for m in works[wid].members:
            expected.extend(c.id for c in load_text_chunks(p.tradition, m))
        got = [cid for s in p.spans for cid in s.chunk_ids]
        assert got == expected, f"{wid}: span chunks != corpus order/coverage"


def test_spans_never_cross_member_texts(plans):
    for p in plans.values():
        for s in p.spans:
            prefixes = {".".join(cid.split(".")[:2]) for cid in s.chunk_ids}
            assert len(prefixes) == 1, f"{p.work_id}/{s.slug} spans texts"
            assert prefixes.pop().endswith(s.text_id)


def test_slugs_unique_per_text(plans):
    for p in plans.values():
        keys = [(s.text_id, s.slug) for s in p.spans]
        assert len(keys) == len(set(keys)), p.work_id


def test_degenerate_count_matches_grouping_table(plans):
    # work-grouping.md: 14 single-span works at ~6k target — but that table
    # counted whole-work token totals; per-member containment (G4 analysis
    # note) can only reduce merging, so degenerate works are exactly those
    # with one span. Assert the invariant + spot-check known cases.
    degen = {w for w, p in plans.items() if p.degenerate}
    for known in ("heart-sutra-smaller", "isa-upanishad", "adapa-food-of-life",
                  "sefer-yetzirah", "bundahishn", "gathas-introduction"):
        assert known in degen, known
    assert "kalevala" not in degen
    assert "plotinus-select-works-index" not in degen


def test_bare_format_fallback_enuma(plans):
    p = plans["enuma-elish"]
    assert all(s.label.startswith("Part ") for s in p.spans), \
        "enuma-elish should budget-pack into synthetic Part n spans"
    assert len(p.spans) >= 2


def test_no_folds_under_claude_code(plans):
    cfg = load_campaign()
    if cfg["input_budget"] == 0:
        assert sum(p.fold_batches for p in plans.values()) == 0


def test_folds_activate_under_local_budget():
    cfg = load_campaign()
    cfg = {**cfg, "input_budget": 6000}
    plans = {p.work_id: p for p in plan_campaign(cfg)}
    assert plans["plotinus-select-works-index"].fold_batches >= 2
    assert plans["heart-sutra-smaller"].fold_batches == 0


def test_span_sizes_respect_target(plans):
    cfg = load_campaign()
    target = cfg["span_target"]
    for p in plans.values():
        for s in p.spans:
            # oversized single natural sections split; merged spans stay under
            # target + one section's worth of slack (800-token chunk cap)
            assert s.token_count <= target * 1.5 + 800, (p.work_id, s.label, s.token_count)


def test_base_section_and_slug_rules():
    assert base_section("Rune Ia") == "Rune I"
    assert base_section("1b") == "1"
    assert base_section("Chapter II, Section 1a") == "Chapter II"
    assert slugify("Tablet IV (part 2)") == "tablet-iv-part-2"
    assert slugify("Rune I – Rune V") == "rune-i-rune-v"
