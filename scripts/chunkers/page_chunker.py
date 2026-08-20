"""
Page-as-chunk strategy for multi-page books where each raw file
represents one natural chunk (hymn, chapter, tractate, etc.).

Each page becomes one chunk, with optional sub-splitting on paragraph
boundaries if it exceeds the token budget.

Strategy name: page-as-chunk
"""

import logging
import re

from regex_splitter import Chunk, subsplit  # reuse Chunk dataclass and subsplit

logger = logging.getLogger(__name__)


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


def split(
    pages: list[tuple[int, str, str]],
    config: dict,
    source_urls: dict[str, str] | None = None,
) -> list[Chunk]:
    """
    Process multi-page source files into chunks.

    Args:
        pages: List of (page_number, filename_stem, content) tuples,
               sorted by page_number. The orchestrator (chunk.py) is
               responsible for applying pre_strip_patterns before calling
               this function.
        config: Chunking config dict (from [chunking] section of TOML).
                Optional keys: section_label_format (default "Page {n}"),
                               number_source ("filename" or "content"),
                               number_pattern (regex w/ capture group, used when number_source='content'),
                               title_source ("content"),
                               title_pattern (regex),
                               title_max_len (int, default 80),
                               max_tokens (default 800).
        source_urls: Optional {filename_stem: source_url} map (from each
                      page's own raw .meta.toml), so each chunk records the
                      page it actually came from rather than the whole
                      work's single URL. Without it every chunk falls back
                      to that shared URL at the orchestrator level — correct
                      for `strategy_type == "single"`, wrong for multi-page:
                      every chunk beyond the first page would otherwise cite
                      the first page's URL (todo: found on the 2026-08-17
                      western_esoteric batch, confirmed pre-existing on the
                      already-applied tertium-organum corpus too).

    Returns:
        List of Chunk objects.
    """
    source_urls = source_urls or {}
    label_fmt = config.get("section_label_format", "Page {n}")
    # Fallback used when number_source='content' but number_pattern didn't
    # match (e.g. front-matter pages with no Roman numeral). Without this,
    # those pages get labeled with the same prefix ("Hymn N") as real hymns
    # despite not being hymns. Defaults to "Page {n}".
    label_fmt_no_match = config.get("section_label_format_no_number_match", "Page {n}")
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

        page_meta = {"source_url": source_urls.get(filename, "")}
        chunk = Chunk(section_label=label, body=content, metadata=page_meta)
        chunk.token_count = count_tokens(content)

        if chunk.token_count > max_tokens:
            # Sub-split on paragraph boundaries. subsplit() builds fresh Chunk
            # objects and doesn't know about page_meta, so carry it over here
            # rather than in the shared splitter.
            subs = subsplit(chunk, max_tokens, count_tokens)
            # Opt-in: drop trailing sub-split parts that are appended editorial
            # commentary rather than primary text. The trigger is the page's
            # own primary marker: the FIRST sub-chunk always opens with the
            # page's hymn number (number_pattern matched at the page level), so
            # a trailing part that does NOT open with a number is commentary
            # overflow (Taylor's footnotes/essays appended past max_tokens),
            # not verse continuation. Safe only when the primary unit is known
            # to fit in max_tokens (orphic-hymns: longest verse 567 < 800), so
            # it is opt-in per config and documented in the config comment.
            if config.get("drop_trailing_nonprimary_subsplits") and number_matched:
                keep = [subs[0]]
                for sub in subs[1:]:
                    if _extract_number(filename, sub.body, config) is not None:
                        keep.append(sub)
                if len(keep) != len(subs):
                    logger.info(
                        f"[{filename}] dropped {len(subs) - len(keep)} trailing "
                        f"non-primary sub-split part(s)"
                    )
                subs = keep
            for sub in subs:
                sub.metadata = page_meta
            # Relabel sub-chunks with part numbers. When the editorial-tail
            # drop leaves a single sub, restore the plain page label (subsplit
            # had suffixed it with '-a').
            if len(subs) == 1:
                subs[0].section_label = label
            elif len(subs) > 1:
                for i, sub in enumerate(subs):
                    sub.section_label = f"{label} (part {i + 1})"
            chunks.extend(subs)
        else:
            chunks.append(chunk)

    return chunks
