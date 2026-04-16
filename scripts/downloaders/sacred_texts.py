"""
Sacred Texts Downloader

Handles sacred-texts.com sources with index pages and individual text pages.
Supports multi-part texts like Corpus Hermeticum (17 tractates).
"""

import hashlib
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def normalize_whitespace(text: str) -> str:
    """Normalize whitespace in extracted text."""
    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text)
    # Collapse multiple newlines to max 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip leading/trailing whitespace per line
    text = "\n".join([line.strip() for line in text.split("\n")])
    # Remove empty lines at start/end
    text = text.strip()
    return text


def generate_text_id(tradition: str, title: str, index: int = 0, base_id: str = None) -> str:
    """
    Generate consistent text_id from tradition and title.
    
    Args:
        tradition: Tradition category (e.g., "hermeticism")
        title: Title from the page
        index: Index for multi-part texts
        base_id: Optional base ID from manifest
        
    Returns:
        Text ID like "corpus-hermeticum-01"
    """
    if base_id:
        # Use manifest ID as base
        if index > 0:
            # Extract number from base_id if present
            match = re.search(r"-(\d+)$", base_id)
            if match:
                # Increment existing number
                num = int(match.group(1)) + index
                return re.sub(r"-\d+$", f"-{num}", base_id)
            else:
                return f"{base_id}-{index:02d}"
        return base_id
    
    # Clean title: lowercase, replace spaces/special chars with hyphens
    clean = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower())
    clean = re.sub(r"-+", "-", clean)  # collapse multiple hyphens
    clean = clean.strip("-")
    
    # Add index for multi-part texts
    if index > 0:
        clean = f"{clean}-{index:02d}"
    
    return clean


def fetch_index(url: str) -> list[dict]:
    """
    Fetch index page and extract links to individual texts.
    
    Args:
        url: Index page URL
        
    Returns:
        List of dicts: {url, title, text_id}
    """
    logger.info(f"Fetching index page: {url}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://www.google.com/",
    }
    
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    
    # Find all text links (usually in a list or specific container)
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Filter for text pages
        if href.endswith(".htm") or href.endswith(".html"):
            # Skip index links
            if "index" in href.lower():
                continue
            # Convert relative to absolute URL
            if not href.startswith("http"):
                href = urljoin(url, href)
            links.append({
                "url": href,
                "title": a.get_text(strip=True)
            })
    
    logger.info(f"Found {len(links)} text links on index page")
    return links


def extract_text_page(html: str, source_id: str) -> str:
    """
    Extract main content from sacred-texts.com page layout.
    
    Their pages typically have:
    - Left sidebar navigation
    - Main content in div.content or similar
    - Footer with links
    - Ads
    """
    soup = BeautifulSoup(html, "html.parser")
    
    # Try to find main content container (priority order)
    main = None
    
    # Try class="content"
    main = soup.find("div", class_="content")
    if main:
        logger.debug(f"[{source_id}] Found content div")
    
    # Try id="content"
    if not main:
        main = soup.find("div", id="content")
        if main:
            logger.debug(f"[{source_id}] Found content div by ID")
    
    # Try main element
    if not main:
        main = soup.find("main")
        if main:
            logger.debug(f"[{source_id}] Found main element")
    
    # Try body as fallback
    if not main:
        # Remove sidebar and footer
        for element in soup.find_all(["nav", "aside", "footer", "header"]):
            element.decompose()
        main = soup.body
        logger.debug(f"[{source_id}] Using body as fallback")
    
    if not main:
        logger.warning(f"[{source_id}] No content container found")
        return ""
    
    # Remove footnotes (often in div.footnotes or similar)
    for element in main.find_all(class_=["footnotes", "notes", "fn"]):
        element.decompose()
    
    # Remove ads
    for element in main.find_all(class_=["ad", "advertisement", "adsense"]):
        element.decompose()
    
    # Remove navigation links
    for element in main.find_all(class_=["nav", "navigation", "menu"]):
        element.decompose()
    
    # Remove image captions and credits
    for element in main.find_all(class_=["caption", "credit", "source"]):
        element.decompose()
    
    # Get text
    text = main.get_text(separator="\n")
    
    # Clean up extracted text
    text = normalize_whitespace(text)
    
    return text


def content_hash(text: str) -> str:
    """Calculate SHA256 hash of text content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def download(source: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """
    Download and extract texts from sacred-texts.com source.
    
    Handles both single-page and multi-page (index) sources.
    
    Args:
        source: Dict with id, url, tradition, format, translator, license, notes
        
    Returns:
        List of (clean_text, metadata_dict) tuples, one per text/tractate
    """
    source_id = source["id"]
    url = source["url"]
    tradition = source["tradition"]
    translator = source.get("translator", "Unknown")
    license_info = source.get("license", "unknown")
    format_type = source.get("format", "html")
    
    logger.info(f"[{source_id}] Processing sacred-texts.com source: {url}")
    
    results = []
    
    # Check if this is an index page (ends with index.htm or index.html)
    if "index" in url.lower():
        # Fetch index and extract individual text links
        text_links = fetch_index(url)
        
        # Extract text_id from source_id (e.g., "corpus-hermeticum-01")
        base_id = source_id
        
        for idx, link in enumerate(text_links):
            text_url = link["url"]
            title = link["title"]
            
            logger.info(f"[{source_id}] Fetching text {idx + 1}/{len(text_links)}: {text_url}")
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Referer": url,
            }
            
            try:
                response = requests.get(text_url, headers=headers, timeout=30)
                response.raise_for_status()
                
                # Extract text
                clean_text = extract_text_page(response.text, source_id)
                
                if not clean_text:
                    logger.warning(f"[{source_id}] No text extracted from {text_url}")
                    continue
                
                # Generate text_id
                text_id = generate_text_id(tradition, title, idx, base_id)
                
                # Generate metadata
                metadata = {
                    "provenance": {
                        "source_url": text_url,
                        "index_url": url,
                        "downloaded_at": datetime.now(timezone.utc).isoformat(),
                        "content_sha256": content_hash(clean_text),
                        "format": "html",
                        "extractor": "sacred_texts",
                        "license": license_info,
                        "translator": translator,
                        "tradition": tradition,
                    }
                }
                
                results.append((clean_text, metadata))
                logger.info(f"[{source_id}] Extracted {len(clean_text)} characters from {text_id}")
                
                # Rate limiting: 1 second between requests
                time.sleep(1)
                
            except requests.RequestException as e:
                logger.error(f"[{source_id}] Failed to fetch {text_url}: {e}")
                continue
    else:
        # Single page source
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://www.google.com/",
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            # Extract text
            clean_text = extract_text_page(response.text, source_id)
            
            if not clean_text:
                raise ValueError(f"[{source_id}] No text extracted from {url}")
            
            # Generate metadata
            metadata = {
                "provenance": {
                    "source_url": url,
                    "downloaded_at": datetime.now(timezone.utc).isoformat(),
                    "content_sha256": content_hash(clean_text),
                    "format": "html",
                    "extractor": "sacred_texts",
                    "license": license_info,
                    "translator": translator,
                    "tradition": tradition,
                }
            }
            
            results.append((clean_text, metadata))
            logger.info(f"[{source_id}] Extracted {len(clean_text)} characters")
            
        except requests.RequestException as e:
            logger.error(f"[{source_id}] Download failed: {e}")
            raise
    
    logger.info(f"[{source_id}] Completed: {len(results)} texts extracted")
    return results


if __name__ == "__main__":
    # Test with Corpus Hermeticum index
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    
    # Test Corpus Hermeticum index
    test_source = {
        "id": "corpus-hermeticum",
        "url": "https://www.sacred-texts.com/chr/herm/index.htm",
        "tradition": "hermeticism",
        "format": "html_multi",
        "translator": "G.R.S. Mead",
        "license": "public_domain",
        "notes": "Index of 17 tractates"
    }
    
    try:
        results = download(test_source)
        print(f"\nExtracted {len(results)} texts:")
        for i, (text, meta) in enumerate(results):
            print(f"  {i+1}. {len(text)} chars - SHA256: {meta['provenance']['content_sha256'][:16]}...")
        
        # Show first 500 chars of first text
        if results:
            print("\nFirst 500 characters of first text:")
            print(results[0][0][:500])
            
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
