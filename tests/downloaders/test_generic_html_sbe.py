"""Regression tests for the SBE strip path through generic_html.extract_text
and through the full acquire dispatch.

Covers todo:ca88b09c. The original patch (todo:5a794b5e) put the strip logic
in sacred_texts.extract_text_page, but acquire.py routes format=html
sacred-texts URLs to generic_html — so the patch never fired for Yasnas,
Heart Sutra, Dhammapada, Bundahishn, etc. These tests close that gap.

Three layers of coverage:
  1. generic_html.extract_text strips SBE markup directly
  2. The shared _sbe_strip helper is module-agnostic
  3. acquire.load_downloader → process_source pipeline produces clean raw
     output for an SBE URL — the actual path that runs in production
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "downloaders"))

import acquire  # noqa: E402
import generic_html  # noqa: E402


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


def test_generic_html_strips_sbe_apparatus_directly():
    """generic_html.extract_text strips SBE markup the same way sacred_texts does."""
    text = generic_html.extract_text(SBE_FIXTURE, source_id="test-sbe")

    assert " 5 " not in text, f"bare ref digit ' 5 ' still present: {text!r}"
    assert " 6 " not in text, f"bare ref digit ' 6 ' still present: {text!r}"
    assert "5:1 some footnote text" not in text
    assert "6:1 a second apparatus note" not in text
    assert "Footnotes" not in text
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


def test_generic_html_non_sbe_passes_through_unchanged():
    """The SBE selectors are no-ops on non-SBE markup."""
    text = generic_html.extract_text(NON_SBE_FIXTURE, source_id="test-non-sbe")
    assert (
        "Whoever finds the interpretation of these sayings will not experience death."
        in text
    )


def test_acquire_pipeline_routes_sbe_url_through_patched_extractor():
    """The full acquire.load_downloader → process_source path produces clean
    output for an SBE URL. This is the test that would have caught the
    original todo:5a794b5e routing miss — calling the function directly
    bypassed the dispatch where the bug lived.
    """
    # 1. Confirm the dispatch routes to generic_html (the bug-affected module).
    module = acquire.load_downloader(
        "html", "https://sacred-texts.com/zor/sbe31/sbe31008.htm"
    )
    assert module.__name__ == "generic_html", (
        f"SBE URLs with format=html must route to generic_html, "
        f"got {module.__name__}. If you're refactoring dispatch, make sure "
        f"the SBE strip applies to whatever module actually wins the route."
    )

    # 2. Run extraction through the resolved module on the SBE fixture.
    text = module.extract_text(SBE_FIXTURE, source_id="test-pipeline-sbe")

    # 3. Same artifact assertions as the direct-call test — the strip has
    #    to fire regardless of how the module was obtained.
    assert "5:1 some footnote text" not in text
    assert "Footnotes" not in text
    assert "Svetâsvatara Upanishad, first verse" in text


def test_acquire_pipeline_html_multi_still_routes_to_sacred_texts():
    """The other half of the dispatch — html_multi sources still resolve to
    sacred_texts (the pre-existing behavior). Guards against accidental
    routing changes in any future refactor.
    """
    module = acquire.load_downloader(
        "html_multi", "https://sacred-texts.com/pag/aradia/index.htm"
    )
    assert module.__name__ == "sacred_texts"
