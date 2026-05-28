"""
Gnosis.org Downloader

Downloads Nag Hammadi texts from gnosis.org.
Handles single-page format with clean HTML structure.
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def normalize_whitespace(text: str) -> str:
    """Normalize whitespace while PRESERVING paragraph breaks.

    Collapses runs of spaces/tabs and trims each line, but keeps blank-line
    (\\n\\n) separators so downstream paragraph-group chunking has real
    boundaries to work with. (The earlier version collapsed *all* whitespace
    to single spaces, flattening the page into one line — which left
    paragraph-group with a single blob to letter-suffix subsplit.)
    """
    import re

    # Collapse spaces/tabs only — not newlines.
    text = re.sub(r"[ \t]+", " ", text)
    # Strip trailing/leading whitespace per line.
    text = "\n".join(line.strip() for line in text.split("\n"))
    # Collapse 3+ newlines to a single blank-line separator.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def content_hash(text: str) -> str:
    """Calculate SHA256 hash of text content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def download(source: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """
    Download and extract text from gnosis.org source.
    
    Args:
        source: Dict with id, url, tradition, format, translator, license, notes
        
    Returns:
        Tuple of (clean_text, metadata_dict)
    """
    source_id = source["id"]
    url = source["url"]
    translator = source.get("translator", "Unknown")
    license_info = source.get("license", "public_domain")
    
    logger.info(f"[{source_id}] Downloading from {url}")
    
    # Configure request with headers to avoid blocking
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    
    # Fetch page
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    
    # Detect encoding
    response.encoding = response.apparent_encoding
    
    soup = BeautifulSoup(response.text, "html.parser")
    
    # Find main content container
    # gnosis.org typically uses div with class "content" or similar
    main = None
    
    # Try various content containers
    main = soup.find("div", class_="content")
    if not main:
        main = soup.find("div", class_="main-content")
    if not main:
        main = soup.find("div", class_="text")
    if not main:
        main = soup.find("main")
    if not main:
        # Try by ID
        main = soup.find(id="content")
    if not main:
        main = soup.find(id="main")
    
    # Fallback: remove header/footer/nav and use body
    if not main:
        for element in soup.find_all(["header", "footer", "nav", "aside"]):
            element.decompose()
        main = soup.body
    
    if not main:
        logger.error(f"[{source_id}] No content container found")
        raise ValueError(f"[{source_id}] No content container found in {url}")
    
    # Remove unwanted elements
    for element in main.find_all(["script", "style"]):
        element.decompose()
    
    # Remove ads and navigation
    for element in main.find_all(class_=["ad", "advertisement", "nav", "navigation", "menu"]):
        element.decompose()

    # Extract text, preserving paragraph structure. gnosis.org pages use one
    # <p> per verse/paragraph; join the block-level elements with blank lines
    # so the chunker receives real paragraph boundaries. Fall back to a flat
    # get_text() for pages without block markup.
    blocks = main.find_all("p")
    if blocks:
        parts = [b.get_text(separator=" ", strip=True) for b in blocks]
        text = "\n\n".join(p for p in parts if p)
    else:
        text = main.get_text(separator="\n")
    text = normalize_whitespace(text)
    
    if not text:
        logger.error(f"[{source_id}] No text extracted")
        raise ValueError(f"[{source_id}] No text extracted from {url}")
    
    logger.info(f"[{source_id}] Extracted {len(text)} characters")
    
    # Build metadata
    metadata = {
        "provenance": {
            "source_url": url,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "content_sha256": content_hash(text),
            "format": "html",
            "extractor": "gnosis_org",
            "license": license_info,
            "translator": translator,
        }
    }
    
    return text, metadata


if __name__ == "__main__":
    # Test with Gospel of Thomas
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    
    # Test Gospel of Thomas
    test_source = {
        "id": "gospel-of-thomas",
        "url": "http://gnosis.org/naghamm/gthlamb.html",
        "tradition": "gnosticism",
        "format": "html",
        "translator": "Thomas O. Lambdin",
        "license": "public_domain",
        "notes": "Full Coptic-to-English translation"
    }
    
    try:
        text, meta = download(test_source)
        print(f"\nExtracted {len(text)} characters")
        print(f"SHA256: {meta['provenance']['content_sha256']}")
        print(f"Translator: {meta['provenance']['translator']}")
        print("\nFirst 500 characters:")
        print(text[:500])
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
