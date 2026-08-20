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

        # Opt-in: strip appended editorial commentary (translator's footnotes /
        # essays) that trails the primary text on the page. Runs for EVERY page
        # carrying the marker, not just oversized ones — most orphic-hymns
        # pages fit in max_tokens as verse-only, but their raw bodies STILL
        # contain the footnotes, and embedding that prose pollutes retrieval.
        # Truncate at the first '<marker> <n>:' line: the verse is the leading
        # block, the marker never appears inside a verse, and no verse follows
        # it on the page, so the cut keeps exactly the verse. No-op unless the
        # key is set, so other page-as-chunk texts keep their behavior.
        cmarker = config.get("strip_appended_commentary")
        if cmarker:
            cm = re.compile(r"\n*" + re.escape(str(cmarker)) + r"\s+\d+:", re.DOTALL)
            cut = cm.split(content, 1)
            if len(cut) > 1:
                content = cut[0].strip()
                if not content:
                    # The marker is at the very start of the page: this is a
                    # standalone commentary/essay page with no leading verse.
                    # Stripping leaves an empty body — emit nothing rather than
                    # a 0-token chunk that would still be written and embedded
                    # (PR #87 review round 3).
                    logger.info(
                        f"[{filename}] dropped page: pure commentary, no verse "
                        f"before marker '{cmarker}'"
                    )
                    continue
                chunk.body = content
                logger.info(
                    f"[{filename}] stripped appended commentary "
                    f"(marker '{cmarker}')"
                )

        chunk.token_count = count_tokens(content)

        if chunk.token_count > max_tokens:
            # Sub-split on paragraph boundaries. subsplit() builds fresh Chunk
            # objects and doesn't know about page_meta, so carry it over here
            # rather than in the shared splitter.
            subs = subsplit(chunk, max_tokens, count_tokens)
            # Opt-in: after commentary is stripped, any page that STILL exceeds
            # max_tokens sub-splits, and trailing parts that do NOT open with
            # this page's OWN hymn number are dropped (commentary overflow, not
            # verse continuation). No-op unless the key is set.
            if config.get("drop_trailing_nonprimary_subsplits"):
                # The drop trigger is "does this sub open with the page's OWN
                # primary marker?" — knowable only when number_source='content'
                # matched a primary number AT THE PAGE LEVEL. Two inert cases:
                #   (a) number_source != 'content' (e.g. 'filename'): every sub
                #       would be tested against the page's file number, not a
                #       content hymn number — meaningless, so the drop
                #       silently does nothing useful (finding 3). Warn, don't
                #       raise, and skip: the feature is opt-in, so an inert
                #       config is harmless as long as it's flagged.
                #   (b) number_matched is False (this page has no content hymn
                #       number — front matter, apparatus): it isn't a primary
                #       unit at all, so there's nothing to drop. drop_before_marker
                #       handles such pages later; skip here.
                if config.get("number_source") != "content":
                    logger.warning(
                        f"[{filename}] drop_trailing_nonprimary_subsplits is "
                        f"inert with number_source='{config.get('number_source')}'"
                        f" (needs 'content') — skipping the drop for this page"
                    )
                elif not number_matched:
                    pass  # not a primary unit; handled by _apply_config_drops
                else:
                    keep = [subs[0]]
                    for sub in subs[1:]:
                        # Finding 4: a footnote that quotes another hymn's
                        # incipit ("XV. TO SATURN.") must NOT be retained as a
                        # verse part. The check is the page's OWN number, not
                        # "any Roman numeral" — _extract_number on a sub returns
                        # the first number it finds, which for a footnote-
                        # quoting sub is the QUOTED hymn's number, not this
                        # page's. Match against the page's verified primary
                        # number instead.
                        if _extract_number(filename, sub.body, config) == number:
                            keep.append(sub)
                    if len(keep) != len(subs):
                        logger.info(
                            f"[{filename}] dropped {len(subs) - len(keep)} trailing "
                            f"non-primary sub-split part(s)"
                        )
                    subs = keep
            for sub in subs:
                sub.metadata = page_meta
            # Relabel sub-chunks with part numbers. UNCONDITIONAL — this is the
            # pre-PR behavior that every page-as-chunk source relied on: a lone
            # sub gets the plain page label (subsplit otherwise suffixes '-a'),
            # and multi-subs get "Page X (part N)". The opt-in editorial keys
            # (strip_appended_commentary / drop_trailing_nonprimary_subsplits)
            # control COMMENTARY handling only; they must not alter labeling,
            # or the other 14 page-as-chunk corpora (e.g.
            # life-and-doctrines-boehme, ~1626 chunks) would flip from
            # "(part N)" to subsplit's raw "-a"/"-b" on re-chunk (regression
            # on PR #87 review round 2, finding 2).
            if len(subs) == 1:
                subs[0].section_label = label
            elif len(subs) > 1:
                for i, sub in enumerate(subs):
                    sub.section_label = f"{label} (part {i + 1})"
            chunks.extend(subs)
        else:
            chunks.append(chunk)

    return chunks
