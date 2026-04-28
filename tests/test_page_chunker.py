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

from page_chunker import DEFAULT_TITLE_MAX_LEN, _extract_title  # noqa: E402


# Same pattern in chunking/greek_mystery/orphic-hymns.toml
ORPHIC_PATTERN = r'^(?:(?:[IVXLCDM]+|SECT)\.\s+)?(?:TO\s+)?(.+?)[\.\*]?\s*$'


def test_short_title_line_matched_normally():
    """The happy path — a real title line on its own."""
    content = "XV. TO JUNO.\nO Royal Juno of majestic mien...\n"
    assert _extract_title(content, {"title_pattern": ORPHIC_PATTERN}) == "JUNO"


def test_single_line_blob_falls_back_to_no_title():
    """Pre-fix: this returned the entire body. Now: skipped because >80 chars,
    no other line, returns None — caller formats label as 'Hymn N' only."""
    body = (
        "Sacred Texts Classics Index Previous Next XXII. TO NEREUS. "
        "The FUMIGATION from MYRRH. O Thou, who dost the roots of Ocean keep "
        "In seats cærulean, dæmon of the deep..."
    )
    assert len(body) > DEFAULT_TITLE_MAX_LEN  # premise of the fix
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
    # With the override, the long line is admitted and the regex matches.
    title = _extract_title(body, cfg)
    assert title is not None and "JUNO" in title


def test_no_pattern_returns_none():
    assert _extract_title("anything", {}) is None


def test_empty_content_returns_none():
    assert _extract_title("", {"title_pattern": ORPHIC_PATTERN}) is None
    assert _extract_title("   \n\n   ", {"title_pattern": ORPHIC_PATTERN}) is None


def test_default_cap_constant_is_80():
    """If this changes, callers need to know — bake the contract into the test."""
    assert DEFAULT_TITLE_MAX_LEN == 80
