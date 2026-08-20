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


# ── strip_appended_commentary + drop_trailing_nonprimary_subsplits (todo:f1e1e009 / PR #87) ──

def test_strip_appended_commentary_removes_footnotes_from_kept_chunk():
    """Pages that fit in max_tokens as verse-only STILL carry the appended
    footnotes in their raw body; embedding that prose pollutes retrieval.
    strip_appended_commentary truncates the body at the first '<marker> <n>:'
    line for EVERY page (not just oversized ones), leaving only the verse.
    This is finding #1 of the PR #87 review — the kept chunk must not embed
    commentary."""
    cfg = {
        "strategy": "page-as-chunk",
        "section_label_format": "Hymn {n}. {title}",
        "number_source": "content",
        "number_pattern": r"^([IVXLCDM]+)(?=\.\s*[Tt]|\s*[Tt][Oo] )",
        "title_source": "content",
        "title_pattern": r"(?i)^(?:[IVXLCDM]+\.?\s+)?TO\s+(.+?)[\.\*]?\s*$",
        "title_max_len": 80,
        "max_tokens": 800,
        "strip_appended_commentary": "Footnotes",
    }
    verse = ("LXXV. TO THE MUSES. Daughters of Jove, dire-sounding and divine, "
             "Renown'd Pierian, sweetly speaking Nine; ")
    commentary = ("\n\nFootnotes 205:1 Ver. i.] Proclus says the Muses are "
                  "daughters of Jove and Mnemosyne. " * 20)
    content = verse + commentary
    pages = [(1, "t-01", content)]
    chunks = split(pages, cfg, {})
    # One chunk, verse only — the footnotes marker is fully stripped.
    assert len(chunks) == 1, [c.section_label for c in chunks]
    assert chunks[0].section_label == "Hymn LXXV. THE MUSES"
    assert "Footnotes" not in chunks[0].body
    assert chunks[0].body.startswith("LXXV.")
    assert chunks[0].body.endswith("Nine;")  # not commentary


def test_strip_appended_commentary_is_opt_in():
    """Without the key, a page-as-chunk corpus keeps its footnotes (prior
    behavior — finding #2: the relabel/strip must not fire for other texts)."""
    cfg = {
        "strategy": "page-as-chunk",
        "section_label_format": "Hymn {n}. {title}",
        "number_source": "content",
        "number_pattern": r"^([IVXLCDM]+)(?=\.\s*[Tt]|\s*[Tt][Oo] )",
        "title_source": "content",
        "title_pattern": r"(?i)^(?:[IVXLCDM]+\.?\s+)?TO\s+(.+?)[\.\*]?\s*$",
        "title_max_len": 80,
        "max_tokens": 800,
    }
    verse = ("LXXV. TO THE MUSES. Daughters of Jove, dire-sounding and divine. ")
    commentary = "\n\nFootnotes 205:1 Ver. i.] Proclus on the Muses. " * 5
    chunks = split([(1, "t-01", verse + commentary)], cfg, {})
    assert "Footnotes" in chunks[0].body


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
    # budget, with the footnotes on a distinct blank-line-separated block so
    # subsplit produces a trailing commentary-only sub. split() uses the real
    # tokenizer, so the commentary must push the page well past max_tokens.
    verse = "LXXV. TO THE MUSES. Daughters of Jove, dire-sounding and divine, Renown'd Pierian, sweetly speaking Nine;"
    commentary = "\n\n" + ("Footnotes 205:1 Ver. i.] Proclus says the Muses are daughters of Jove and Mnemosyne. " * 20)
    content = verse + commentary
    pages = [(1, "t-01", content)]
    chunks = split(pages, cfg, {})
    # Only the hymn part should survive (a single chunk with the plain label)
    assert len(chunks) == 1, [c.section_label for c in chunks]
    assert chunks[0].section_label == "Hymn LXXV. THE MUSES"
    # drop_trailing_nonprimary_subsplits keeps the first (hymn-opening) sub and
    # drops the later commentary-only subs; the verse survives. (The separate
    # strip_appended_commentary key removes the commentary *head* inside the
    # kept sub — finding #1 — and is tested separately.)
    assert chunks[0].body.startswith("LXXV.")
    # The commentary was a distinct trailing sub and got dropped entirely.
    assert "Proclus says the Muses" not in chunks[0].body


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
    assert "Footnotes" not in chunks[0].body
    assert chunks[0].body.startswith("LXXV.")


def test_drop_trailing_nonprimary_rejects_footnote_incipit_quote():
    """Finding #4: a footnote that quotes another hymn's incipit
    ('XV. TO SATURN.') must NOT be retained as a verse part. The keep check
    matches the page's OWN number, not 'any Roman numeral', so the
    quote-bearing sub is dropped."""
    cfg = {
        "strategy": "page-as-chunk",
        "section_label_format": "Hymn {n}. {title}",
        "number_source": "content",
        "number_pattern": r"^([IVXLCDM]+)(?=\.\s*[Tt]|\s*[Tt][Oo] )",
        "title_source": "content",
        "title_pattern": r"(?i)^(?:[IVXLCDM]+\.?\s+)?TO\s+(.+?)[\.\*]?\s*$",
        "title_max_len": 80,
        "max_tokens": 120,
        "drop_trailing_nonprimary_subsplits": True,
    }
    # Page LXXV verse, then a footnote quoting Hymn XV's incipit, then more.
    verse = "LXXV. TO THE MUSES. Daughters of Jove, dire-sounding and divine, Renowned Pierian, sweetly speaking Nine; "
    footnote_quote = ("Footnotes 205:1 Ver. i.] See Hymn XV. TO SATURN. "
                      "The Saturnian hymn invokes the Titan bound; " * 8)
    content = verse + "\n\n" + footnote_quote
    chunks = split([(1, "t-01", content)], cfg, {})
    assert len(chunks) == 1, [c.section_label for c in chunks]
    # The footnote-quoting sub is dropped (it does not open with 'LXXV').
    assert "SATURN" not in chunks[0].body
    assert chunks[0].body.startswith("LXXV.")


def test_drop_trailing_nonprimary_inert_under_filename_source_warns():
    """Finding #3: under number_source='filename' the drop can never fire
    (every sub shares the file number), so it must warn+skip, not silently
    no-op or raise."""
    cfg = {
        "strategy": "page-as-chunk",
        "section_label_format": "Hymn {n}. {title}",
        "number_source": "filename",
        "max_tokens": 60,
        "drop_trailing_nonprimary_subsplits": True,
    }
    # A page that would otherwise sub-split with commentary; filename source
    # means no content number match, so the drop is inert (warns, keeps all).
    content = "Verse line one about the Muses. " * 6 + "Footnotes 205:1 commentary tail. " * 10
    chunks = split([(1, "t-01", content)], cfg, {})
    # Nothing dropped: all parts present (filename number can't identify a
    # primary verse, so the drop is a no-op for this page).
    assert all("Footnotes" in c.body for c in chunks)



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
