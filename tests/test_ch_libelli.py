"""Regression for c59758f3: CH 15/16 were acquired as duplicate libellus XVI
(stale gnosis.org mirror, off-by-one pages) and the th2-sourced labels were
shifted one tractate back. Locks the corrected page->libellus mapping."""

import json
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
CH_DIR = ROOT / "corpus" / "hermeticism"

# Mead's TGH Vol. 2 canon: the corpus skips XV, so slots 14-17 hold XIV(XV),
# (XVI), (XVII), (XVIII). Ids are stable acquisition slots, labels carry canon.
TH2_TEXTS = {
    "corpus-hermeticum-14": ("th229.htm", "CORPUS HERMETICUM XIV"),
    "corpus-hermeticum-15": ("th231.htm", "CORPUS HERMETICUM (XVI.)"),
    "corpus-hermeticum-16": ("th233.htm", "CORPUS HERMETICUM (XVII.)"),
    "corpus-hermeticum-17": ("th235.htm", "CORPUS HERMETICUM (XVIII.)"),
}


def _first_body(text_id: str) -> str:
    p = CH_DIR / text_id / "chunks" / "001.toml"
    return tomllib.load(open(p, "rb"))["content"]["body"]


def test_th2_texts_hold_distinct_libelli():
    """No two th2-sourced CH texts may contain the same tractate."""
    openings = {tid: " ".join(_first_body(tid).split())[:400] for tid in TH2_TEXTS}
    for tid, (_, marker) in TH2_TEXTS.items():
        assert marker in openings[tid], f"{tid}: expected {marker!r} in opening"


def test_th2_bodies_not_duplicated():
    bodies = {tid: _first_body(tid) for tid in TH2_TEXTS}
    ids = list(bodies)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            assert bodies[a] != bodies[b], f"{a} and {b} share chunk 001 body"


def test_manifest_urls_match_mead_toc():
    manifest = tomllib.load(open(ROOT / "sources" / "manifest.toml", "rb"))
    by_id = {s["id"]: s for s in manifest["source"]}
    for tid, (page, _) in TH2_TEXTS.items():
        assert by_id[tid]["url"].endswith(page), \
            f"{tid}: manifest url {by_id[tid]['url']} != Mead TOC page {page}"


def test_no_gated_works_in_plan():
    plan = json.loads((ROOT / "docs" / "summary" / "span-plan-c1.json").read_text())
    gated = [w["work_id"] for w in plan["works"] if w["gated_by"]]
    assert gated == [], f"plan still gates {gated}"
