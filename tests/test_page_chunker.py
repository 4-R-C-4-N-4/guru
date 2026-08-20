"""Tests for scripts/chunkers/page_chunker._extract_title (todo:8b4f303d).

Regression: previously _extract_title scanned the first 10 lines without
any length cap. For sources that come back as a single line (e.g. the
sacred-texts.com Orphic Hymns scrape), the loop ran once with line=full_body,
matched a permissive title_pattern, and returned the whole body as the title.
The chunk's section header then became "Hymn N. <entire hymn body>".
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "chunkers"))

from page_chunker import DEFAULT_TITLE_MAX_LEN, _extract_title, split  # noqa: E402


# Same pattern as chunking/greek_mystery/orphic-hymns.toml — requires
# literal "TO X" to avoid matching bare Roman numerals.
ORPHIC_PATTERN = r'^(?:[IVXLCDM]+\.\s+)?TO\s+(.+?)[\.\*]?\s*$'


def test_short_title_line_matched_normally():
    """The happy path — a real title line on its own."""
    content = "XV. TO JUNO.\nO Royal Juno of majestic mien...\n"
    assert _extract_title(content, {"title_pattern": ORPHIC_PATTERN}) == "JUNO"


def test_single_line_blob_extracts_title_via_sentence_head():
    """Single-line scraped page (post pre_strip) has the title as the
    leading sentence. Sentence-head candidate extraction finds it
    because 'TO NEREUS' is short and matches the strict pattern."""
    body = (
        "XXII. TO NEREUS. The FUMIGATION from MYRRH. O Thou, who dost "
        "the roots of Ocean keep In seats cærulean, dæmon of the deep..."
    )
    assert len(body) > DEFAULT_TITLE_MAX_LEN
    assert _extract_title(body, {"title_pattern": ORPHIC_PATTERN}) == "NEREUS"


def test_single_line_blob_with_unstripped_nav_falls_back_to_none():
    """If the source still has 'Sacred Texts Classics Index Previous Next' nav
    and the title pattern is strict (requires 'TO X'), no candidate matches —
    pre_strip must run first for the orphic case to work end-to-end."""
    body = (
        "Sacred Texts Classics Index Previous Next The FUMIGATION from MYRRH. "
        "O Thou, who dost the roots of Ocean keep..."
    )
    # No "TO X" sentence in this fragment — strict pattern returns None.
    assert _extract_title(body, {"title_pattern": ORPHIC_PATTERN}) is None


def test_long_first_line_short_second_line_uses_second():
    """If a long noisy header line precedes a clean short title, prefer
    the short one — the cap pushes us past the noise."""
    content = (
        "Sacred Texts Classics Index Previous Next p. 145 (a long preamble line, > 80 chars)\n"
        "XX. TO THE CLOUDS.\n"
        "The FUMIGATION from MYRRH.\n"
        "Aerial Clouds, thro' heaven's resplendent plains...\n"
    )
    assert _extract_title(content, {"title_pattern": ORPHIC_PATTERN}) == "THE CLOUDS"


def test_title_max_len_override_via_config():
    """Per-source override is honored."""
    body = "XV. TO JUNO." + " (footnote: " + "x" * 100 + ")"  # ~120 chars
    cfg = {"title_pattern": ORPHIC_PATTERN, "title_max_len": 200}
    title = _extract_title(body, cfg)
    assert title is not None and "JUNO" in title


def test_bare_roman_numeral_does_not_become_title():
    """Regression for the chunker output 'Hymn XXII. XXII' bug — strict
    title pattern requires literal 'TO', so a bare 'XXII' fragment does
    not match as title."""
    body = "XXII"
    assert _extract_title(body, {"title_pattern": ORPHIC_PATTERN}) is None


def test_no_pattern_returns_none():
    assert _extract_title("anything", {}) is None


def test_empty_content_returns_none():
    assert _extract_title("", {"title_pattern": ORPHIC_PATTERN}) is None
    assert _extract_title("   \n\n   ", {"title_pattern": ORPHIC_PATTERN}) is None


def test_default_cap_constant_is_80():
    """If this changes, callers need to know — bake the contract into the test."""
    assert DEFAULT_TITLE_MAX_LEN == 80


# ── drop_trailing_nonprimary_subsplits (todo:f1e1e009) ──────────────────────

def test_drop_trailing_nonprimary_subsplits_drops_commentary_tails():
    """A page whose verse fits in max_tokens but whose appended commentary
    overflows must emit ONLY the hymn part. The first sub-chunk opens with the
    page's hymn number; trailing parts that do NOT open with a number are
    editorial overflow (Taylor's footnotes/essays), not verse continuation."""
    # orphic-hymns-style config: number_pattern + title_pattern + opt-in drop
    cfg = {
        "strategy": "page-as-chunk",
        "section_label_format": "Hymn {n}. {title}",
        "number_source": "content",
        "number_pattern": r"^([IVXLCDM]+)(?=\.\s*[Tt]|\s*[Tt][Oo] )",
        "title_source": "content",
        "title_pattern": r"(?i)^(?:[IVXLCDM]+\.?\s+)?TO\s+(.+?)[\.\*]?\s*$",
        "title_max_len": 80,
        "max_tokens": 100,
        "drop_trailing_nonprimary_subsplits": True,
    }
    # Build a page that would sub-split: short verse + long commentary past the
    # budget. split() uses the real tokenizer, so the commentary must push the
    # page well past max_tokens.
    verse = "LXXV. TO THE MUSES. Daughters of Jove, dire-sounding and divine, Renown'd Pierian, sweetly speaking Nine;"
    commentary = " " + ("Footnotes 205:1 Ver. i.] Proclus says the Muses are daughters of Jove and Mnemosyne. " * 20)
    content = verse + commentary
    pages = [(1, "t-01", content)]
    chunks = split(pages, cfg, {})
    # Only the hymn part should survive (a single chunk with the plain label)
    assert len(chunks) == 1, [c.section_label for c in chunks]
    assert chunks[0].section_label == "Hymn LXXV. THE MUSES"
    assert "Footnotes" in chunks[0].body  # the first part still carries the verse + comment start
    assert chunks[0].body.startswith("LXXV.")  # the hymn opening survives


def test_drop_trailing_nonprimary_subsplits_keeps_hymn_opening_sub():
    """The FIRST sub-chunk always survives the drop: it opens with the page's
    own hymn number (number_matched at the page level), so it is primary text
    even when the page also carries commentary past the budget."""
    cfg = {
        "strategy": "page-as-chunk",
        "section_label_format": "Hymn {n}. {title}",
        "number_source": "content",
        "number_pattern": r"^([IVXLCDM]+)(?=\.\s*[Tt]|\s*[Tt][Oo] )",
        "title_source": "content",
        "title_pattern": r"(?i)^(?:[IVXLCDM]+\.?\s+)?TO\s+(.+?)[\.\*]?\s*$",
        "title_max_len": 80,
        "max_tokens": 100,
        "drop_trailing_nonprimary_subsplits": True,
    }
    # Verse + long commentary. The drop keeps only the first (hymn-opening) part.
    content = ("LXXV. TO THE MUSES.\n\nDaughters of Jove, dire-sounding and divine, Renowned Pierian, sweetly speaking Nine; "
               + ("The Muses sing of all that was, and is, and shall be. " * 15) + "\n\n"
               + ("Footnotes 205:1 Ver. i.] Proclus says the Muses are daughters of Jove and Mnemosyne. " * 20))
    chunks = split([(1, "t-01", content)], cfg, {})
    # The hymn part survives with the plain label; the commentary tail is gone.
    assert len(chunks) == 1, [c.section_label for c in chunks]
    assert chunks[0].section_label == "Hymn LXXV. THE MUSES"
    assert chunks[0].body.startswith("LXXV.")


def test_drop_trailing_nonprimary_subsplits_optout_is_noop():
    """Without the opt-in key, the pre-existing behavior is unchanged: all
    sub-split parts are emitted."""
    cfg = {
        "strategy": "page-as-chunk",
        "number_source": "content",
        "number_pattern": r"^([IVXLCDM]+)(?=\.\s*[Tt]|\s*[Tt][Oo] )",
        "title_source": "content",
        "title_pattern": r"(?i)^(?:[IVXLCDM]+\.?\s+)?TO\s+(.+?)[\.\*]?\s*$",
        "title_max_len": 80,
        "max_tokens": 100,
        # no drop_trailing_nonprimary_subsplits
    }
    content = ("LXXV. TO THE MUSES. Daughters of Jove, dire-sounding and divine, "
               "Renown'd Pierian, sweetly speaking Nine; "
               + ("Footnotes 205:1 Ver. i.] Proclus says the Muses are daughters of Jove and Mnemosyne. " * 20))
    chunks = split([(1, "t-01", content)], cfg, {})
    assert len(chunks) >= 2, [c.section_label for c in chunks]  # tail parts survive when opt-out
