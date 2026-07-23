"""Tests for scripts/clean_bodies.py pattern classes P7-P9 (todo:d5ad220f).

The readability audit (docs/summary/readability-audit.md) added three strip
classes. The load-bearing invariants: the paragraph-split {p. roman} marker
dies without gluing its neighbors together, ONLY digit brackets are treated
as footnote refs (bracketed words are translator reconstructions and must
survive), and clean prose passes through byte-identical.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from clean_bodies import clean_body  # noqa: E402


def test_clean_prose_is_untouched():
    body = (
        "The One is beyond being, and naming fails it.\n\n"
        "Therefore the soul ascends not by adding knowledge but by letting go."
    )
    assert clean_body(body) == body


def test_p7_inline_curly_page_marker():
    assert clean_body("native {p. vi} Egyptian sources") == "native Egyptian sources"


def test_p7_paragraph_split_curly_marker_rejoins_without_gluing():
    body = 'and thou hast lifted it {p.\n\nxcli} given unto thee'
    out = clean_body(body)
    assert "{p." not in out and "xcli" not in out
    assert "it given" in out  # single space, not "itgiven"


def test_p7_ocr_digit_roman_numeral():
    out = clean_body('simply "blessed." {p.\n\n1xxv} and his ka is triumphant')
    assert "1xxv" not in out and "{p." not in out


def test_p7b_leading_orphan_from_cross_chunk_split_marker():
    # Chunking split "{p.\n\nlxvii}" across two chunks: the previous chunk
    # got "{p." (P7 eats it) and this one starts with the orphaned "lxvii}".
    out = clean_body("lxvii} supported by a passage in the Book of the Dead")
    assert out.startswith("supported by")


def test_p7b_only_strips_at_body_start():
    body = "The king said: lxvii} is not a marker here."
    assert "lxvii}" in clean_body(body)


def test_p8_standalone_page_number_paragraph_dropped():
    body = "In the name of the Great Life.\n\np. 81\n\nThe sleeper awoke."
    out = clean_body(body)
    assert "p. 81" not in out
    assert "Great Life" in out and "sleeper awoke" in out


def test_p8_does_not_drop_prose_starting_with_p():
    body = "p. 81 is the folio where the hymn begins, say the scribes."
    assert "folio" in clean_body(body)


def test_p9_numeric_footnote_refs_stripped():
    out = clean_body("he took away one part of the whole [1], and in the grove of Geta[2], he sat.")
    assert "[1]" not in out and "[2]" not in out
    assert "whole, and" in out  # no orphaned space before the comma
    assert "Geta," in out


def test_p9_reconstruction_brackets_survive():
    body = "Unto me hearken, O Elders, to me [shall ye listen], here [offer] a cake."
    out = clean_body(body)
    assert "[shall ye listen]" in out
    assert "[offer]" in out


def test_p9_year_brackets_survive():
    # 4-digit brackets are dates ("[1895]"), not footnote refs.
    assert "[1895]" in clean_body("published from the Museum copy [1895] in London.")


def test_p9_can_be_disabled_for_excluded_texts():
    # Timaeus harmonic-proportion glosses ([1]..[27]) are content; main()
    # disables P9 for P9_EXCLUDE_TEXTS while other classes still run.
    body = "he took away one part of the whole [1], and a seventh part [27].\n\np. 12"
    out = clean_body(body, strip_footnote_refs=False)
    assert "[1]" in out and "[27]" in out
    assert "p. 12" not in out  # P8 still applies
