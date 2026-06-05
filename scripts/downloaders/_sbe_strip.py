"""
Shared SBE (Sacred Books of the East) apparatus-strip helper.

The original sacred-texts.com SBE markup (Mills SBE31, West SBE5, Müller SBE10/15/49)
wraps inline footnote-ref superscripts in `<font size="1">` and appends a trailing
apparatus block headed by `<h3 align="CENTER">Footnotes</h3>`. Without stripping
these, BeautifulSoup's `get_text()` flattens the superscripts to bare digits glued
to surrounding words ("Svetâsva 1", "neuter 1 .") and concatenates the full
Footnotes apparatus onto the translation body.

This helper is consumed by BOTH `generic_html.py` (for `format = "html"` sources —
the bulk of SBE entries: Yasnas, Bundahishn, Heart Sutra, Dhammapada, etc.) AND
`sacred_texts.py` (for `format = "html_multi"` sources like Aradia, Yoruba).

Selectors are CSS-attribute-precise and SBE-shaped; non-SBE pages (gnosis.org,
ccel, gutenberg, plain sacred-texts non-SBE) carry no `font[size="1"]` and no
`<h3>Footnotes</h3>`, so they pass through unaffected. This was verified against
the existing corpus before generalising the patch.

History: the strip logic was originally implemented in `sacred_texts.extract_text_page`
(todo:5a794b5e) but never actually fired for the targeted sources because
`acquire.py` routes `format = "html"` URLs to `generic_html` — `sacred_texts` is
only invoked for `format = "html_multi"`. The dry-run for todo:79801268 surfaced
the routing gap (todo:ca88b09c), at which point the logic was extracted here so
both modules apply it identically.
"""

from bs4 import BeautifulSoup, Tag


def strip_sbe_apparatus(soup: BeautifulSoup | Tag) -> None:
    """
    In-place mutate `soup` (or a sub-Tag of it) to remove SBE inline-footnote
    and trailing-apparatus markup.

    1. Decompose `<font size="1">` elements (inline footnote-ref superscripts).
    2. Decompose `<sup>` elements (other inline superscripts; also SBE-style).
    3. Decompose any anchor `<a>` whose only child was one of the above (now
       empty), AND any pre-existing empty anchors used as page markers
       (`<a name="page_xliv"></a>`).
    4. Find any `<h3>` whose visible text is "Footnotes" (case-insensitive)
       and decompose it together with all of its following siblings within
       the same parent — that's the trailing apparatus block.

    Idempotent: safe to call multiple times. No-op on non-SBE pages.

    Args:
        soup: a BeautifulSoup document or any Tag node to clean.
    """
    # 1. Strip inline <font size="1"> footnote-ref superscripts.
    for element in soup.select('font[size="1"]'):
        element.decompose()

    # 2. Strip <sup> superscripts.
    for element in soup.find_all("sup"):
        element.decompose()

    # 3. Decompose now-empty anchors (footnote-ref wrappers AND page-marker anchors).
    for anchor in soup.find_all("a"):
        if not anchor.get_text(strip=True) and not anchor.find(True):
            anchor.decompose()

    # 4. Drop the trailing apparatus block: <h3>Footnotes</h3> + following siblings.
    for h3 in soup.find_all("h3"):
        if h3.get_text(strip=True).lower() == "footnotes":
            for sibling in list(h3.find_next_siblings()):
                sibling.decompose()
            h3.decompose()
