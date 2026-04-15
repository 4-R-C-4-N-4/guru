"""
Generic HTML Downloader

Downloads single-page HTML sources using BeautifulSoup for text extraction.
Handles encoding normalization, HTML cleanup, and provenance metadata generation.
"""

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def normalize_whitespace(text: str) -> str:
    """
    Normalize whitespace in extracted text.
    
    - Collapses multiple spaces to single space
    - Collapses multiple newlines to max 2
    - Strips leading/trailing whitespace per line
    - Removes empty lines at start/end
    """
    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text)
    # Collapse multiple newlines to max 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip leading/trailing whitespace per line
    text = "\n".join([line.strip() for line in text.split("\n")])
    # Remove empty lines at start/end
    text = text.strip()
    return text


def is_mojibake(text: str) -> bool:
    """
    Detect common mojibake patterns (UTF-8 interpreted as Latin-1).
    
    Looks for characteristic byte sequences that indicate encoding errors.
    """
    # Common mojibake patterns from UTF-8 → Latin-1 misinterpretation
    mojibake_patterns = [
        r"[\xc0-\xff][\x80-\xbf]",  # Two-byte UTF-8 sequences
        r"Ã[\x80-\xbf]",  # Common A-umlaut pattern
        r"Ã©",  # é
        r"Ã¼",  # ü
        r"Ã¶",  # ö
        r"Ã¼",  # ü
    ]
    
    for pattern in mojibake_patterns:
        if re.search(pattern, text):
            return True
    return False


def normalize_encoding(html: str) -> str:
    """
    Try to detect and fix encoding issues in HTML content.
    
    Handles common mojibake patterns where UTF-8 was interpreted as Latin-1.
    """
    # Handle common mojibake patterns
    # UTF-8 interpreted as Latin-1
    if is_mojibake(html):
        try:
            html = html.encode("latin-1").decode("utf-8")
            logger.debug("Fixed encoding: Latin-1 → UTF-8")
        except (UnicodeEncodeError, UnicodeDecodeError) as e:
            logger.warning(f"Failed to fix encoding: {e}")
    
    return html


def extract_text(html: str, source_id: str) -> str:
    """
    Extract main content from HTML, stripping navigation, scripts, styles, ads.
    
    Args:
        html: Raw HTML content
        source_id: Identifier for logging purposes
        
    Returns:
        Cleaned plaintext content
    """
    soup = BeautifulSoup(html, "html.parser")
    
    # Remove unwanted elements
    unwanted_tags = ["script", "style", "nav", "footer", "header", "aside", "iframe"]
    for element in soup(unwanted_tags):
        element.decompose()
    
    # Remove common ad and navigation classes
    ad_classes = ["ad", "advertisement", "adsense", "sidebar", "menu", "navigation"]
    for cls in ad_classes:
        for element in soup(class_=cls):
            element.decompose()
    
    # Extract from main content containers (priority order)
    containers = []
    
    # Try specific content containers first
    for tag in ["main", "article"]:
        containers.extend(soup.find_all(tag))
    
    # Try divs with content-related classes
    content_classes = ["content", "main-content", "text", "body", "article-content"]
    for cls in content_classes:
        containers.extend(soup.find_all("div", class_=cls))
    
    # Try by ID
    content_ids = ["content", "main", "text", "article", "body"]
    for id_name in content_ids:
        el = soup.find(id=id_name)
        if el:
            containers.append(el)
    
    text = ""
    if containers:
        # Get text from containers, avoiding duplicates
        seen = set()
        texts = []
        for c in containers:
            c_id = id(c)
            if c_id not in seen:
                seen.add(c_id)
                text_content = c.get_text(separator="\n")
                if text_content.strip():
                    texts.append(text_content)
        
        text = "\n\n".join(texts)
    else:
        # Fallback: get body text
        if soup.body:
            text = soup.body.get_text(separator="\n")
        else:
            text = soup.get_text(separator="\n")
    
    # Normalize whitespace
    text = normalize_whitespace(text)
    
    # Log extraction stats
    if text:
        logger.info(f"[{source_id}] Extracted {len(text)} characters")
    else:
        logger.warning(f"[{source_id}] No text extracted from HTML")
    
    return text


def content_hash(text: str) -> str:
    """Calculate SHA256 hash of text content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def download(source: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """
    Download and extract text from a single-page HTML source.
    
    Args:
        source: Dict with id, url, tradition, format, translator, license, notes
        
    Returns:
        Tuple of (clean_text, metadata_dict)
        
    Raises:
        requests.RequestException: On download failure after retries
    """
    source_id = source["id"]
    url = source["url"]
    tradition = source["tradition"]
    translator = source.get("translator", "Unknown")
    license_info = source.get("license", "unknown")
    
    logger.info(f"[{source_id}] Downloading from {url}")
    
    # Configure request
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    
    # Retry logic with exponential backoff
    max_retries = 3
    base_delay = 1.0
    
    for attempt in range(max_retries):
        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=30,
                allow_redirects=True
            )
            response.raise_for_status()
            break
        except requests.RequestException as e:
            if attempt == max_retries - 1:
                logger.error(f"[{source_id}] Download failed after {max_retries} attempts: {e}")
                raise
            
            delay = base_delay * (2 ** attempt)
            logger.warning(f"[{source_id}] Attempt {attempt + 1} failed: {e}. Retrying in {delay:.1f}s...")
            import time
            time.sleep(delay)
    
    # Normalize encoding
    html = normalize_encoding(response.text)
    
    # Extract text
    clean_text = extract_text(html, source_id)
    
    if not clean_text:
        raise ValueError(f"[{source_id}] No text extracted from {url}")
    
    # Generate metadata
    metadata = {
        "provenance": {
            "source_url": url,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "content_sha256": content_hash(clean_text),
            "format": "html",
            "extractor": "generic_html",
            "license": license_info,
            "translator": translator,
        }
    }
    
    logger.info(f"[{source_id}] Successfully extracted {len(clean_text)} characters")
    
    return clean_text, metadata


if __name__ == "__main__":
    # Test with a sample source
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    
    # Sample source for testing
    test_source = {
        "id": "test-source",
        "url": "http://gnosis.org/naghamm/gthlamb.html",
        "tradition": "gnosticism",
        "format": "html",
        "translator": "Thomas O. Lambdin",
        "license": "public_domain",
        "notes": "Test source"
    }
    
    try:
        text, meta = download(test_source)
        print(f"Extracted {len(text)} characters")
        print(f"SHA256: {meta['provenance']['content_sha256']}")
        print("\nFirst 500 characters:")
        print(text[:500])
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
