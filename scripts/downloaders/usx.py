"""
USX downloader — public-domain Scripture from USX 3.0 files.

Built for the openbibleinfo American-Standard-Version-Bible distribution
(usx-english-only/, ASV 1901, public domain — the -aligned/ trees carry
CC-BY SBL/MACULA components and MUST NOT be used). Fetches one USX book file
and emits one verse per unit, each prefixed with a `[chapter:verse]` marker so
node 05 can group verses to the token ceiling and label chunks by verse range.

Output shape (raw/{tradition}/{id}.txt), verses blank-line separated:

    [1:1] In the beginning God created the heavens and the earth.

    [1:2] And the earth was waste and void; ...

Apparatus handling (workbook: apparatus is stripped BEFORE chunking):
  - <note> subtrees (translator/textual footnotes) are dropped entirely, but
    their tail text — the verse body that continues after the note — is kept.
  - <char> spans (style="add" translator additions, style="it" italics, etc.)
    are unwrapped: their text is ASV rendering and stays in the body.
  - Editorial section headings (<para style="s*">, "d", "r") carry no verse
    milestone, so their text falls outside any verse span and is dropped.

Verse text is the document-order run between a <verse sid="BOOK C:V"/> milestone
and its matching <verse eid="BOOK C:V"/>. The C:V marker is taken verbatim from
the sid, so chapter tracking is inherent.
"""

import hashlib
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _localname(tag: str) -> str:
    """Strip any XML namespace, e.g. '{ns}para' -> 'para'."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _walk(el):
    """Yield document-order tokens, skipping <note> subtrees.

    Tokens:
      ("vstart", "C:V") / ("vend", "C:V") — verse milestones (from sid/eid)
      ("text", str)                       — a run of body text
    """
    tag = _localname(el.tag)

    if tag == "note":
        # Apparatus: drop the subtree, keep the text that follows the note.
        if el.tail:
            yield ("text", el.tail)
        return

    if tag == "verse":
        sid, eid = el.get("sid"), el.get("eid")
        if sid:
            yield ("vstart", sid)
        elif eid:
            yield ("vend", eid)
        if el.tail:
            yield ("text", el.tail)
        return

    if tag in ("chapter", "book"):
        # Structural milestones carry no body text; keep any tail.
        if el.tail:
            yield ("text", el.tail)
        return

    # Generic container (usx, para, char, ...): text, then children, then tail.
    if el.text:
        yield ("text", el.text)
    for child in el:
        yield from _walk(child)
    if el.tail:
        yield ("text", el.tail)


def _cv(ref: str) -> str:
    """'JHN 1:1' -> '1:1' (book code dropped; C:V kept verbatim)."""
    return ref.split(" ", 1)[-1].strip()


def parse_usx(xml_text: str) -> tuple[str, int]:
    """Parse USX into blank-line-separated `[C:V] text` verses.

    Returns (raw_text, verse_count).
    """
    root = ET.fromstring(xml_text)

    verses: list[tuple[str, list[str]]] = []
    current: list[str] | None = None
    current_cv: str | None = None

    for kind, payload in _walk(root):
        if kind == "vstart":
            current_cv, current = _cv(payload), []
        elif kind == "vend":
            if current is not None and current_cv is not None:
                verses.append((current_cv, current))
            current, current_cv = None, None
        elif kind == "text" and current is not None:
            current.append(payload)

    lines = []
    for cv, frags in verses:
        body = re.sub(r"\s+", " ", "".join(frags)).strip()
        if body:
            lines.append(f"[{cv}] {body}")

    return "\n\n".join(lines) + "\n", len(verses)


def download(source: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Fetch a USX book file and return (raw_text, metadata)."""
    source_id = source["id"]
    url = source["url"]
    translator = source.get("translator", "Unknown")
    license_info = source.get("license", "unknown")

    if "usx-english-only" not in url:
        # Guard the licensing invariant: only the english-only tree is clean PD.
        logger.warning(
            f"[{source_id}] URL is not under usx-english-only/ — the aligned "
            f"trees carry CC-BY components. Verify the license before shipping."
        )

    logger.info(f"[{source_id}] Downloading USX from {url}")
    headers = {"User-Agent": "guru-ingest/usx (+public-domain scripture)"}

    last_err: Exception | None = None
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
            resp.raise_for_status()
            break
        except requests.RequestException as e:
            last_err = e
            if attempt == 2:
                logger.error(f"[{source_id}] Download failed after 3 attempts: {e}")
                raise
            delay = 1.0 * (2 ** attempt)
            logger.warning(f"[{source_id}] Attempt {attempt + 1} failed: {e}. Retrying in {delay:.1f}s...")
            time.sleep(delay)

    resp.encoding = resp.encoding or "utf-8"
    text, verse_count = parse_usx(resp.text)

    if not text.strip() or verse_count == 0:
        raise ValueError(f"[{source_id}] No verses extracted from {url}")

    logger.info(f"[{source_id}] Extracted {verse_count} verses ({len(text)} chars)")

    metadata = {
        "provenance": {
            "source_url": url,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "content_sha256": content_hash(text),
            "format": "usx",
            "extractor": "usx",
            "license": license_info,
            "translator": translator,
            "verse_count": verse_count,
        }
    }
    return text, metadata


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    test = {
        "id": "gospel-of-john-asv",
        "url": "https://raw.githubusercontent.com/openbibleinfo/American-Standard-Version-Bible/master/usx-english-only/43-JHN.usx",
        "tradition": "biblical",
        "translator": "American Standard Version (1901)",
        "license": "public_domain",
    }
    body, meta = download(test)
    print(meta["provenance"])
    print(body[:600])
    if len(sys.argv) > 1:
        print("...\n", body[-400:])
