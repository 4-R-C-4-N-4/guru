"""
Sefaria API Downloader (v3)

Downloads Jewish texts from the Sefaria API v3.
Supports full books by fetching chapter-by-chapter using the index endpoint.
"""

import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

SEFARIA_API_BASE = "https://www.sefaria.org/api"


def normalize_whitespace(text: str) -> str:
    """Normalize whitespace in extracted text."""
    import re

    text = re.sub(r" +", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join([line.strip() for line in text.split("\n")])
    text = text.strip()
    return text


def content_hash(text: str) -> str:
    """Calculate SHA256 hash of text content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _get_json(url: str, params: dict | None = None, max_retries: int = 3) -> dict:
    """
    Fetch JSON from a URL with retry logic and rate-limit handling.
    """
    headers = {
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (compatible; guru-corpus-downloader/1.0; "
            "+https://github.com/4-R-C-4-N-4/guru)"
        ),
    }
    base_delay = 1.0

    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)

            if response.status_code == 429:
                delay = base_delay * (2**attempt)
                logger.warning(f"Rate limited. Retrying in {delay:.1f}s...")
                time.sleep(delay)
                continue

            response.raise_for_status()
            return response.json()

        except requests.RequestException as e:
            if attempt == max_retries - 1:
                logger.error(f"Failed to fetch {url} after {max_retries} attempts: {e}")
                raise
            delay = base_delay * (2**attempt)
            logger.warning(
                f"Attempt {attempt + 1} failed for {url}: {e}. Retrying in {delay:.1f}s..."
            )
            time.sleep(delay)

    raise RuntimeError(f"Failed to fetch {url} after {max_retries} attempts")


def get_book_structure(text_key: str) -> dict:
    """
    Fetch book index metadata (structure, chapter count, lengths).

    Returns the index dict which contains 'lengths' (chapters) and 'sectionNames'.
    """
    url = f"{SEFARIA_API_BASE}/v2/raw/index/{text_key}"
    return _get_json(url)


def get_text_section(ref: str, language: str = "english") -> list[str]:
    """
    Fetch a single section (chapter) from Sefaria v3 API.

    Returns a list of verse/mishnah strings for that section.
    """
    url = f"{SEFARIA_API_BASE}/v3/texts/{ref}"
    params = {
        "version": language,
        "return_format": "text_only",
    }
    data = _get_json(url, params=params)

    # versions is a list; find the first with text
    versions = data.get("versions", [])
    if not versions:
        # Check for warnings about missing versions
        warnings = data.get("warnings", [])
        if warnings:
            logger.warning(f"[{ref}] Sefaria warnings: {warnings}")
        logger.warning(f"[{ref}] No versions returned")
        return []

    text = versions[0].get("text", [])

    # text may be a string (single segment) or list of strings (section)
    if isinstance(text, str):
        return [text] if text.strip() else []
    elif isinstance(text, list):
        # Flatten nested lists (some texts have 3D structure)
        flat = []
        for item in text:
            if isinstance(item, list):
                flat.extend([s for s in item if isinstance(s, str) and s.strip()])
            elif isinstance(item, str) and item.strip():
                flat.append(item)
        return flat
    return []


def fetch_full_text(text_key: str) -> str:
    """
    Fetch the complete text of a book by iterating over all chapters.

    Returns combined plaintext with chapters separated by double newlines.
    """
    logger.info(f"Fetching book structure for: {text_key}")
    index = get_book_structure(text_key)

    lengths = index.get("lengths", [])
    section_names = index.get("sectionNames", ["Chapter"])

    if not lengths:
        # Single-section or non-structured text — just fetch directly
        logger.info(f"Fetching {text_key} as single unit")
        verses = get_text_section(text_key)
        return "\n".join(verses)

    num_chapters = lengths[0]
    logger.info(f"Book has {num_chapters} {section_names[0]}s")

    chapter_texts = []
    for chapter_num in range(1, num_chapters + 1):
        ref = f"{text_key}.{chapter_num}"
        logger.info(f"  Fetching {ref}...")
        verses = get_text_section(ref)
        if verses:
            chapter_header = f"[{section_names[0]} {chapter_num}]"
            chapter_body = "\n".join(verses)
            chapter_texts.append(f"{chapter_header}\n{chapter_body}")
        else:
            logger.warning(f"  No text returned for {ref}")
        # Be polite to the API
        time.sleep(0.2)

    return "\n\n".join(chapter_texts)


def _extract_text_key_from_url(url: str) -> str:
    """
    Extract the Sefaria text key from a sefaria.org URL.

    e.g. https://www.sefaria.org/Sefer_Yetirah -> Sefer_Yetzirah
    """
    # Get the path component after the last /
    path = url.rstrip("/").split("/")[-1]
    return path


# Canonical text key mapping for known manifest IDs
# Maps source id -> Sefaria text key (corrects typos, provides canonical names)
CANONICAL_KEYS = {
    "sefer-yetirah": "Sefer_Yetzirah",
    "zohar-leid": "Zohar",
}


def download(source: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """
    Download and extract text from Sefaria API.

    Args:
        source: Dict with id, url, tradition, format, translator, license, notes

    Returns:
        Tuple of (clean_text, metadata_dict)
    """
    source_id = source["id"]
    url = source.get("url", "")
    translator = source.get("translator", "Sefaria Community Translation")
    license_info = source.get("license", "public_domain")

    # Resolve text key: prefer canonical map, fall back to URL extraction
    text_key = CANONICAL_KEYS.get(source_id) or _extract_text_key_from_url(url)

    logger.info(f"[{source_id}] Fetching from Sefaria API: {text_key}")

    try:
        text = fetch_full_text(text_key)

        if not text.strip():
            raise ValueError(f"[{source_id}] No text content returned for {text_key}")

        # Normalize whitespace
        text = normalize_whitespace(text)

        logger.info(f"[{source_id}] Extracted {len(text)} characters")

        metadata = {
            "provenance": {
                "source_url": url or f"https://www.sefaria.org/{text_key}",
                "text_key": text_key,
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
                "content_sha256": content_hash(text),
                "format": "sefaria_api",
                "extractor": "sefaria",
                "license": license_info,
                "translator": translator,
            }
        }

        return text, metadata

    except Exception as e:
        logger.error(f"[{source_id}] Error fetching {text_key}: {e}")
        raise


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Test with Sefer Yetzirah
    test_source = {
        "id": "sefer-yetirah",
        "url": "https://www.sefaria.org/Sefer_Yetirah",
        "tradition": "jewish_mysticism",
        "format": "sefaria_api",
        "translator": "Sefaria Community Translation",
        "license": "public_domain",
        "notes": "Key Kabbalistic text",
    }

    try:
        text, meta = download(test_source)
        print(f"\nExtracted {len(text)} characters")
        print(f"SHA256: {meta['provenance']['content_sha256']}")
        print(f"Source URL: {meta['provenance']['source_url']}")
        print(f"Text Key: {meta['provenance']['text_key']}")
        print("\nFirst 600 characters:")
        print(text[:600])
        print("\n...OK")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)
