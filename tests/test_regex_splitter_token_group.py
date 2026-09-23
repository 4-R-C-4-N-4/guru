"""group_by="tokens" packs sections to the token ceiling on section boundaries.

Added for verse-addressed scripture (docs/ingest/decisions/genesis-asv.md): the
citation unit is the verse but the retrieval unit is a ceiling-sized run of
verses, labelled by range. This asserts the mode's three guarantees and that the
default (fixed-count) path is unchanged.

Run with: PYTHONPATH=scripts/chunkers pytest tests/test_regex_splitter_token_group.py
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "chunkers"))
import regex_splitter  # noqa: E402
from tokens import count_tokens  # noqa: E402

# 30 verses of ~equal length, marked like the USX extractor's output.
VERSES = [f"[{c}:{v}] " + ("word " * 20).strip()
          for c in (1, 2) for v in range(1, 16)]
TEXT = "\n\n".join(VERSES) + "\n"

# Zero-width lookahead: marker stays in the body, group(1) captures C:V.
CFG = {
    "strategy": "regex-section-split",
    "pattern": r"(?=^\[(\d+:\d+)\])",
    "group_by": "tokens",
    "max_tokens": 120,
    "section_label_format": "{n}",
}


def test_no_chunk_exceeds_the_ceiling_and_none_is_empty():
    chunks = regex_splitter.split(TEXT, CFG)
    assert len(chunks) > 1  # 30 verses must not collapse to one chunk
    for c in chunks:
        assert count_tokens(c.body) <= CFG["max_tokens"], c.section_label


def test_labels_are_first_last_verse_ranges_and_body_keeps_the_marker():
    chunks = regex_splitter.split(TEXT, CFG)
    for c in chunks:
        first = c.section_label.split("-")[0]
        assert c.body.lstrip().startswith(f"[{first}]"), c.section_label
    # A multi-verse chunk is labelled as a range; ranges tile without overlap.
    assert chunks[0].section_label.startswith("1:1")
    assert chunks[-1].section_label.endswith("2:15")


def test_verses_tile_exactly_once_across_all_chunks():
    import re
    chunks = regex_splitter.split(TEXT, CFG)
    seen = [m for c in chunks for m in re.findall(r"\[(\d+:\d+)\]", c.body)]
    assert seen == [v.split("]")[0][1:] for v in VERSES]  # order preserved, no dup/gap


def test_boundaries_never_fall_mid_section():
    # Every chunk body starts at a marker and ends before the next one.
    chunks = regex_splitter.split(TEXT, CFG)
    for c in chunks:
        assert c.body.lstrip().startswith("[")
        assert not c.body.rstrip().endswith("[")


def test_default_group_by_count_is_unchanged():
    # Without group_by, group_size bundling is the (backward-compatible) path.
    cfg = {**CFG, "group_size": 5}
    del cfg["group_by"]
    chunks = regex_splitter.split(TEXT, cfg)
    assert len(chunks) == 6  # 30 verses / 5
    assert chunks[0].section_label == "1:1-1:5"
