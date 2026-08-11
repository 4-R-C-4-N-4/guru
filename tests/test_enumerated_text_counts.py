"""
Texts whose source carries its own canonical numbering must emit exactly that
many chunks, labelled in order (todo:7725dcb1).

The Yoga Sutras shipped 192 chunks against a 195-sutra canon. Three sutra
boundaries were not detected — the node 05 pattern required a period after the
number and the sacred-texts pages omit it in exactly three places — so each of
those sutras was absorbed into the chunk before it. No text was lost, and every
other chunk was correct, which is why nothing caught it: the node 05 gate is
that the config parses and produces chunks, and 192 vs 195 is invisible to that.
It surfaced during a post-hoc read, and by then ids had already been tagged.

That is a citation-integrity defect and not a cosmetic one. AGENTS.md: "a chunk
id is a promise that a specific passage says a specific thing." Three ids were
delivering two sutras while naming one.

This is the missing count. Nothing between nodes 05 and 14 compares emitted
units against the source's own numbering, so it is asserted here, per text,
from the printed edition rather than from the corpus.

Adding a text is one row in ENUMERATED. It only makes sense for texts where the
source numbers its own units and the chunker is configured 1:1 against that
numbering — not for prose split on headings or token budget.

Run with: pytest tests/test_enumerated_text_counts.py
"""

import tomllib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = PROJECT_ROOT / "corpus"

# (text_id, tradition, unit count in the printed edition, label template)
#
# Yoga Sutras: Charles Johnston's translation, counts per book from the
# edition's own sutra numbering; 51 + 55 + 55 + 34 = 195.
ENUMERATED = [
    ("yoga-sutras-book-01", "hinduism", 51, "Sutra {n}"),
    ("yoga-sutras-book-02", "hinduism", 55, "Sutra {n}"),
    ("yoga-sutras-book-03", "hinduism", 55, "Sutra {n}"),
    ("yoga-sutras-book-04", "hinduism", 34, "Sutra {n}"),
]


def _labels(tradition: str, text_id: str) -> list[str]:
    chunks = CORPUS_DIR / tradition / text_id / "chunks"
    out = []
    for path in sorted(chunks.glob("*.toml")):
        with open(path, "rb") as f:
            out.append(tomllib.load(f)["chunk"]["section"])
    return out


@pytest.mark.parametrize("text_id,tradition,expected,template", ENUMERATED)
def test_chunk_count_matches_the_printed_edition(text_id, tradition, expected, template):
    labels = _labels(tradition, text_id)
    assert len(labels) == expected, (
        f"{text_id}: {len(labels)} chunks against a {expected}-unit canon. "
        f"A shortfall means undetected boundaries — units merged into the "
        f"chunk before them, each id then naming one unit and delivering two."
    )


@pytest.mark.parametrize("text_id,tradition,expected,template", ENUMERATED)
def test_labels_track_the_file_ordinal(text_id, tradition, expected, template):
    """The count alone is not enough: it can be right while the mapping is
    off. Before the fix, book-02 file 046 was labelled "Sutra 47" and the last
    file, 053, was "Sutra 55" — label and ordinal had silently diverged, so a
    reader resolving a citation by file position landed on the wrong sutra."""
    mismatched = [
        f"{i:03d}.toml is {label!r}, expected {template.format(n=i)!r}"
        for i, label in enumerate(_labels(tradition, text_id), 1)
        if label != template.format(n=i)
    ]
    assert not mismatched, (
        f"{text_id}: label/ordinal divergence\n  " + "\n  ".join(mismatched[:5])
    )
