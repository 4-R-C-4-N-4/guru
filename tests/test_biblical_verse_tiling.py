"""Biblical (ASV) chunks must tile their book's verses exactly once.

The citation-integrity guard for verse-range-grouped scripture, the analogue of
test_enumerated_text_counts.py for token-budget grouping (which that test's own
docstring excludes). For each book it asserts: the right number of verses and
chapters, every verse present exactly once, ranges contiguous with only the known
textual gaps, and every chunk's label matching the first/last [C:V] marker in its
body (a label that names a range its body does not deliver is the exact broken
promise AGENTS.md warns about).

Run with: pytest tests/test_biblical_verse_tiling.py
"""

import re
import tomllib
from pathlib import Path

import pytest

CORPUS = Path(__file__).resolve().parents[1] / "corpus" / "biblical"

# (text_id, verses, chapters, known-absent "C:V" set)
# John: the ASV (critical text) relegates 5:4 to the margin — no verse milestone.
BOOKS = [
    ("genesis-asv", 1533, 50, set()),
    ("gospel-of-john-asv", 878, 21, {"5:4"}),
    ("revelation-asv", 404, 22, set()),
]

MARKER = re.compile(r"\[(\d+):(\d+)\]")


def _chunks(text_id):
    d = CORPUS / text_id / "chunks"
    rows = []
    for p in sorted(d.glob("*.toml")):
        c = tomllib.load(open(p, "rb"))["chunk"]
        rows.append((p.name, c["section"], c.get("body") or _body(p)))
    return rows


def _body(p):
    return tomllib.load(open(p, "rb")).get("content", {}).get("body", "")


@pytest.mark.parametrize("text_id,verses,chapters,absent", BOOKS)
def test_verses_tile_exactly_once(text_id, verses, chapters, absent):
    rows = _chunks(text_id)
    assert rows, f"{text_id}: no chunks on disk"
    seen = [f"{c}:{v}" for _, _, body in rows for c, v in MARKER.findall(body)]
    assert len(seen) == len(set(seen)), f"{text_id}: duplicate verse across chunks"
    assert len(seen) == verses, f"{text_id}: {len(seen)} verses, expected {verses}"
    chaps = {int(s.split(':')[0]) for s in seen}
    assert max(chaps) == chapters and min(chaps) == 1, f"{text_id}: chapters {min(chaps)}-{max(chaps)}"


@pytest.mark.parametrize("text_id,verses,chapters,absent", BOOKS)
def test_no_gaps_beyond_known_textual_omissions(text_id, verses, chapters, absent):
    rows = _chunks(text_id)
    by_ch = {}
    for _, _, body in rows:
        for c, v in MARKER.findall(body):
            by_ch.setdefault(int(c), set()).add(int(v))
    gaps = set()
    for c, vs in by_ch.items():
        gaps |= {f"{c}:{v}" for v in range(1, max(vs) + 1) if v not in vs}
    assert gaps == absent, f"{text_id}: unexpected gaps {gaps - absent}, missing-known {absent - gaps}"


@pytest.mark.parametrize("text_id,verses,chapters,absent", BOOKS)
def test_label_matches_body_first_and_last_verse(text_id, verses, chapters, absent):
    for name, label, body in _chunks(text_id):
        markers = MARKER.findall(body)
        assert markers, f"{text_id}/{name}: no verse markers in body"
        first = f"{markers[0][0]}:{markers[0][1]}"
        last = f"{markers[-1][0]}:{markers[-1][1]}"
        expected = first if first == last else f"{first}-{last}"
        assert label == expected, f"{text_id}/{name}: label {label!r} != body range {expected!r}"
