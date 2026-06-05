"""Regression tests for SBE-volume cleanup in sacred_texts.extract_text_page().

Covers todo:5a794b5e. SBE pages (Müller's Upanishads SBE15, Mills' Gathas SBE31,
etc.) embed footnote-ref superscripts as inline ``<a href="#fn_N"><font size="1">N</font></a>``
and append the apparatus under ``<h3 align="CENTER">Footnotes</h3>``. The
unpatched extractor flattened the refs into bare digits glued to surrounding
words ("a worse 5 ,") and captured the whole apparatus block into the raw
text. Both must now be stripped without touching non-SBE markup.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "downloaders"))

from sacred_texts import extract_text_page  # noqa: E402


SBE_FIXTURE = """
<html>
  <body>
    <div class="content">
      <p>Svetâsvatara Upanishad, first verse<a href="#fn_5"><font size="1">5</font></a>: the
      qualifying words are all in the neuter<a href="#fn_6"><font size="1">6</font></a>.</p>
      <p>The seers beheld the self-power of the Divine Being hidden in its own qualities.</p>
      <h3 align="CENTER">Footnotes</h3>
      <p>5:1 some footnote text</p>
      <p>6:1 a second apparatus note that must not leak into the body.</p>
    </div>
  </body>
</html>
"""


def test_sbe_inline_font_refs_and_footnotes_block_are_stripped():
    text = extract_text_page(SBE_FIXTURE, source_id="test-sbe")

    # (a) Inline footnote-ref superscripts are gone — no bare " 5 " or " 6 "
    # left glued mid-sentence. (Search for the specific artifact shape rather
    # than the digit alone, which might legitimately appear in body prose.)
    assert " 5 " not in text, f"bare ref digit ' 5 ' still present: {text!r}"
    assert " 6 " not in text, f"bare ref digit ' 6 ' still present: {text!r}"
    assert "verse5" not in text and "verse 5" not in text
    assert "neuter6" not in text and "neuter 6" not in text

    # (b) The trailing Footnotes apparatus block (heading + notes) is gone.
    assert "5:1 some footnote text" not in text
    assert "6:1 a second apparatus note" not in text
    assert "Footnotes" not in text

    # (c) Substantive body text survives.
    assert "Svetâsvatara Upanishad, first verse" in text
    assert "qualifying words are all in the neuter" in text
    assert "self-power of the Divine Being" in text


NON_SBE_FIXTURE = """
<html>
  <body>
    <div class="content">
      <p>Whoever finds the interpretation of these sayings will not experience death.</p>
    </div>
  </body>
</html>
"""


def test_non_sbe_page_passes_through_unchanged():
    text = extract_text_page(NON_SBE_FIXTURE, source_id="test-non-sbe")

    # The SBE-specific selectors must not perturb pages that carry no
    # font[size="1"], no <sup>, and no "Footnotes" h3.
    assert (
        "Whoever finds the interpretation of these sayings will not experience death."
        in text
    )
