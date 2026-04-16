"""
Access to Insight Downloader

Downloads Pali Canon texts from accesstoinsight.org.
Handles the site's consistent layout with header, main content div, and footer.
"""

import hashlib
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def normalize_whitespace(text: str) -> str:
    """Normalize whitespace in extracted text."""
    text = re.sub(r" +", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join([line.strip() for line in text.split("\n")])
    text = text.strip()
    return text


def content_hash(text: str) -> str:
    """Calculate SHA256 hash of text content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fetch_html(url: str, max_retries: int = 3) -> str:
    """
    Fetch HTML from a URL with retry logic and rate-limit handling.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    base_delay = 1.0

    for attempt in range(max_retries):
        try:
            response = requests.get(
                url, headers=headers, timeout=30, allow_redirects=True
            )

            if response.status_code == 429:
                delay = base_delay * (2**attempt)
                logger.warning(f"Rate limited. Retrying in {delay:.1f}s...")
                time.sleep(delay)
                continue

            response.raise_for_status()
            return response.text

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


def extract_text(html: str, source_id: str) -> str:
    """
    Extract main content from an accesstoinsight.org HTML page.

    accesstoinsight.org structure:
      - Primary content: <div class="print"> (print-optimized view)
      - Fallback: <div class="main-content">, <div id="content">, <main>
      - Remove: nav, header, footer, sidebar, .sutta-nav, .backmatter

    Returns cleaned plaintext.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove noise elements universally
    noise_tags = ["script", "style", "nav", "header", "footer", "aside", "iframe"]
    for tag in noise_tags:
        for el in soup(tag):
            el.decompose()

    # Remove ATI-specific navigation and wrapper elements
    noise_classes = [
        "sutta-nav",
        "backmatter",
        "copyright",
        "navigation",
        "sidebar",
        "breadcrumb",
        "page-nav",
    ]
    for cls in noise_classes:
        for el in soup(class_=cls):
            el.decompose()

    # Try content containers in priority order (ATI-specific first)
    # ATI structure confirmed via HTML inspection:
    #   div.chapter  = main sutta/text content
    #   div.notes    = footnotes / backmatter (strip before extracting)
    container = None

    # 1. ATI primary: div.chapter holds the sutta text
    container = soup.find("div", class_="chapter")

    # 2. Generic semantic/class fallbacks for other ATI page types
    if not container:
        for cls in ("main-content", "content", "text", "article-body"):
            container = soup.find("div", class_=cls)
            if container:
                break

    # 3. Semantic HTML5 elements
    if not container:
        container = soup.find("main") or soup.find("article")

    # 4. ID-based selectors
    if not container:
        for id_val in ("content", "main", "text", "article"):
            container = soup.find(id=id_val)
            if container:
                break

    # 5. Ultimate fallback: full body
    if not container:
        container = soup.body or soup

    # Strip footnotes / backmatter within the container
    for el in container.find_all("div", class_="notes"):
        el.decompose()

    text = container.get_text(separator="\n")
    text = normalize_whitespace(text)

    if text:
        logger.info(f"[{source_id}] Extracted {len(text)} characters")
    else:
        logger.warning(f"[{source_id}] No text extracted from {html[:200]!r}")

    return text


def download(source: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """
    Download and extract text from accesstoinsight.org.

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

    html = fetch_html(url)
    clean_text = extract_text(html, source_id)

    if not clean_text:
        raise ValueError(f"[{source_id}] No text extracted from {url}")

    metadata = {
        "provenance": {
            "source_url": url,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "content_sha256": content_hash(clean_text),
            "format": "html",
            "extractor": "access_to_insight",
            "license": license_info,
            "translator": translator,
        }
    }

    logger.info(f"[{source_id}] Successfully extracted {len(clean_text)} characters")

    return clean_text, metadata


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Test with the Dhammacakkappavattana Sutta (First Discourse of the Buddha)
    test_source = {
        "id": "setting-wheel-in-motion",
        "url": "https://www.accesstoinsight.org/tipitaka/sn/sn56/sn56.011.than.html",
        "tradition": "buddhism",
        "format": "access_to_insight",
        "translator": "Thanissaro Bhikkhu",
        "license": "public_domain",
        "notes": "First discourse of the Buddha",
    }

    try:
        text, meta = download(test_source)
        print(f"\nExtracted {len(text)} characters")
        print(f"SHA256: {meta['provenance']['content_sha256']}")
        print(f"Source URL: {meta['provenance']['source_url']}")
        print("\nFirst 600 characters:")
        print(text[:600])
        print("\n...OK")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)
