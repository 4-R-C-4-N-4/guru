"""
Page-as-chunk strategy for multi-page books where each raw file
represents one natural chunk (hymn, chapter, tractate, etc.).

Each page becomes one chunk, with optional sub-splitting on paragraph
boundaries if it exceeds the token budget.

Strategy name: page-as-chunk
"""

import re

from regex_splitter import Chunk, subsplit  # reuse Chunk dataclass and subsplit


def _extract_number(filename: str, content: str, config: dict) -> str | None:
    """Extract the page/section number from filename or content."""
    source = config.get("number_source", "filename")
    if source == "filename":
        # Extract trailing integer from filename like "orphic-hymns-03" → 3
        m = re.search(r'(\d+)$', filename)
        return str(int(m.group(1))) if m else None
    elif source == "content":
        pattern = config.get("number_pattern", r'(\d+)')
        m = re.search(pattern, content)
        return m.group(1).strip() if m else None
    return None


DEFAULT_TITLE_MAX_LEN = 80


def _extract_title(content: str, config: dict) -> str | None:
    """Extract a title string from the content using title_pattern.

    A title is, by definition, short. We cap candidate-line length so a
    single-line source (e.g. a scraped page where the entire hymn is on
    one line with no newlines) doesn't end up matching the whole body
    via a permissive pattern. Override with `title_max_len` in config.
    """
    pattern = config.get("title_pattern")
    if not pattern:
        return None
    max_len = int(config.get("title_max_len", DEFAULT_TITLE_MAX_LEN))
    # Search in the first few lines for the title
    for line in content.split("\n")[:10]:
        line = line.strip()
        if not line or len(line) > max_len:
            continue
        m = re.match(pattern, line)
        if m:
            return m.group(1).strip() if m.lastindex and m.lastindex >= 1 else line.strip()
    return None


def split(pages: list[tuple[int, str, str]], config: dict) -> list[Chunk]:
    """
    Process multi-page source files into chunks.

    Args:
        pages: List of (page_number, filename_stem, content) tuples,
               sorted by page_number.
        config: Chunking config dict (from [chunking] section of TOML).
                Optional keys: section_label_format (default "Page {n}"),
                               number_source ("filename" or "content"),
                               title_source ("content"),
                               title_pattern (regex),
                               max_tokens (default 800).

    Returns:
        List of Chunk objects.
    """
    label_fmt = config.get("section_label_format", "Page {n}")
    max_tokens = int(config.get("max_tokens", 800))

    try:
        from tokens import count_tokens
    except ImportError:
        def count_tokens(t):
            return len(t) // 4

    chunks: list[Chunk] = []

    for page_num, filename, content in pages:
        content = content.strip()
        if not content:
            continue

        # Extract number
        number = _extract_number(filename, content, config)
        if number is None:
            number = str(page_num)

        # Extract title
        title = None
        if config.get("title_source") == "content":
            title = _extract_title(content, config)

        # Format the section label
        try:
            if title:
                label = label_fmt.format(n=number, title=title)
            else:
                label = label_fmt.format(n=number, title="")
        except (KeyError, IndexError):
            label = label_fmt.format(n=number)

        chunk = Chunk(section_label=label, body=content)
        chunk.token_count = count_tokens(content)

        if chunk.token_count > max_tokens:
            # Sub-split on paragraph boundaries
            subs = subsplit(chunk, max_tokens, count_tokens)
            # Relabel sub-chunks with part numbers
            if len(subs) > 1:
                for i, sub in enumerate(subs):
                    sub.section_label = f"{label} (part {i + 1})"
            chunks.extend(subs)
        else:
            chunks.append(chunk)

    return chunks
