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


def _candidate_lines(content: str, max_len: int) -> list[str]:
    """Yield short candidate strings to try the title pattern against.

    First tries newline-split lines (works for sources with line breaks).
    Then, for the first ~max_len*4 chars of content, also tries the
    sentence-ish heads — split on '. ', '? ', '! ' — to catch sources
    that come back as one long line where the title is the leading
    sentence (e.g. sacred-texts.com page scrapes)."""
    out: list[str] = []
    for line in content.split("\n")[:10]:
        s = line.strip()
        if s and len(s) <= max_len:
            out.append(s)
    head = content[: max_len * 4]
    for sent in re.split(r'(?<=[.\?!])\s+', head):
        s = sent.strip().rstrip('.?!')
        if s and len(s) <= max_len and s not in out:
            out.append(s)
    return out


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
    for candidate in _candidate_lines(content, max_len):
        m = re.match(pattern, candidate)
        if m:
            return m.group(1).strip() if m.lastindex and m.lastindex >= 1 else candidate.strip()
    return None


def _apply_pre_strip(content: str, patterns: list[str]) -> str:
    """Run each regex through re.sub('') in order. Used to strip source
    navigation cruft (e.g. 'Sacred Texts Classics Index Previous Next ...
    Next: XXIII: To the Nereids') before chunking, so the body that gets
    embedded is the actual text. DOTALL so multi-line patterns work."""
    for pat in patterns:
        content = re.sub(pat, "", content, flags=re.DOTALL)
    return content.strip()


def split(pages: list[tuple[int, str, str]], config: dict) -> list[Chunk]:
    """
    Process multi-page source files into chunks.

    Args:
        pages: List of (page_number, filename_stem, content) tuples,
               sorted by page_number.
        config: Chunking config dict (from [chunking] section of TOML).
                Optional keys: section_label_format (default "Page {n}"),
                               number_source ("filename" or "content"),
                               number_pattern (regex w/ capture group, used when number_source='content'),
                               title_source ("content"),
                               title_pattern (regex),
                               title_max_len (int, default 80),
                               pre_strip_patterns (list[regex], applied in order before chunking),
                               max_tokens (default 800).

    Returns:
        List of Chunk objects.
    """
    label_fmt = config.get("section_label_format", "Page {n}")
    # Fallback used when number_source='content' but number_pattern didn't
    # match (e.g. front-matter pages with no Roman numeral). Without this,
    # those pages get labeled with the same prefix ("Hymn N") as real hymns
    # despite not being hymns. Defaults to "Page {n}".
    label_fmt_no_match = config.get("section_label_format_no_number_match", "Page {n}")
    max_tokens = int(config.get("max_tokens", 800))
    pre_strip = list(config.get("pre_strip_patterns", []))

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

        if pre_strip:
            content = _apply_pre_strip(content, pre_strip)
            if not content:
                continue

        # Extract number
        number = _extract_number(filename, content, config)
        number_matched = number is not None
        if number is None:
            number = str(page_num)

        # Extract title
        title = None
        if config.get("title_source") == "content":
            title = _extract_title(content, config)

        # Pick the label format: if number_source='content' was configured
        # but the pattern did not match, this page has no canonical id of
        # the primary kind (e.g. no hymn number → it's front matter), so
        # fall back to a more honest label format.
        primary_format_active = (
            number_matched or config.get("number_source") != "content"
        )
        active_fmt = label_fmt if primary_format_active else label_fmt_no_match

        # When title is empty, drop the title placeholder + any trailing
        # punctuation/whitespace from the format string so we don't emit
        # "Hymn N. " with dangling separators.
        try:
            if title:
                label = active_fmt.format(n=number, title=title)
            else:
                no_title_fmt = re.sub(r'[\.\-:,\s]*\{title\}[\.\-:,\s]*$', '', active_fmt)
                label = no_title_fmt.format(n=number) if "{n}" in no_title_fmt else active_fmt.format(n=number, title="").rstrip(" .,-:")
        except (KeyError, IndexError):
            label = active_fmt.format(n=number)

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
