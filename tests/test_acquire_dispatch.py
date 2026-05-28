"""Regression tests for acquire.py download dispatch (todo:73c83a22).

The dispatch was format-only: html_multi resolved to the sacred_texts crawler
unconditionally. The gnosis.org Mandaean John-Book (then mislabeled html_multi)
therefore had no working downloader and never landed. Dispatch is now
domain-aware — gnosis.org routes to the gnosis_org extractor regardless of
`format`, and gnosis_org actually yields substantial primary text.
"""
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "downloaders"))

import acquire  # noqa: E402

FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "gnosis_gjb-2-1.htm"


def test_gnosis_routes_to_gnosis_org_regardless_of_format():
    # The bug: html_multi → sacred_texts unconditionally, so this gnosis URL
    # had no working crawler. Domain now wins over format.
    assert acquire._module_for(
        "html_multi",
        "http://gnosis.org/library/grs-mead/gnostic_john_baptist/gjb-2-1.htm",
    ) == "gnosis_org"
    assert acquire._module_for(
        "html", "http://gnosis.org/naghamm/gthlamb.html"
    ) == "gnosis_org"
    # https + www. variants resolve the same
    assert acquire._module_for("html", "https://www.gnosis.org/x.htm") == "gnosis_org"


def test_non_gnosis_dispatch_unchanged():
    # Domain-awareness must not perturb the existing format routing.
    assert acquire._module_for(
        "html_multi", "https://sacred-texts.com/cla/plotenn/index.htm"
    ) == "sacred_texts"
    assert acquire._module_for("html", "https://sacred-texts.com/x.htm") == "generic_html"
    assert acquire._module_for("sefaria_api", "https://www.sefaria.org/x") == "sefaria"
    assert acquire._module_for("bogus_format", "https://example.com") is None


def test_gnosis_org_extracts_mandaean_john_book(monkeypatch):
    """gnosis_org must extract substantial Mandaean primary text from a real
    John-Book leaf page — the content that previously never landed — and the
    chunking config's pre_strip must remove the leading nav header."""
    import gnosis_org

    html = FIXTURE.read_text(encoding="utf-8")

    class _Resp:
        status_code = 200
        text = html
        apparent_encoding = "utf-8"
        encoding = "utf-8"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(gnosis_org.requests, "get", lambda *a, **k: _Resp())

    text, meta = gnosis_org.download(
        {
            "id": "gnostic-john-baptizer-1",
            "url": "http://gnosis.org/library/grs-mead/gnostic_john_baptist/gjb-2-1.htm",
            "tradition": "mandaean",
            "translator": "G.R.S. Mead",
            "license": "public_domain",
        }
    )

    # Substantial primary text, not the 80-2KB stub the broken path produced.
    assert len(text) > 20_000
    # Mandaean John-Book signature content.
    assert "Great Life" in text
    assert "JOHN" in text.upper()
    assert meta["provenance"]["extractor"] == "gnosis_org"

    # The actual chunking config's pre_strip pattern must strip the nav header
    # ("Gnostic John the Baptizer: by G. R. S. Mead Index Previous Next ") and
    # reveal the first print-page marker that regex-section-split keys on.
    cfg = tomllib.load(
        open(PROJECT_ROOT / "chunking" / "mandaean" / "gnostic-john-baptizer-1.toml", "rb")
    )
    pattern = cfg["chunking"]["pre_strip_patterns"][0]
    stripped = re.sub(pattern, "", text, flags=re.DOTALL).lstrip()
    assert stripped.startswith("p. 35"), stripped[:60]
