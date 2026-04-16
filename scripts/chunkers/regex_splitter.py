"""
Regex-based splitter for texts with explicit section markers.

Used for: sayings gospels (logion numbers), numbered verse texts, tractate sections.
"""

import re
from dataclasses import dataclass, field


@dataclass
class Chunk:
    section_label: str
    body: str
    token_count: int = 0  # filled by orchestrator
    metadata: dict = field(default_factory=dict)


def split(text: str, config: dict) -> list[Chunk]:
    """
    Split text into chunks using a regex pattern to find section boundaries.

    Args:
        text: Raw plaintext of the source.
        config: Chunking config dict (from [chunking] section of TOML).
                Required keys: pattern
                Optional keys: section_label_format (default "{n}"),
                               max_tokens (default 800),
                               group_size (default 1)

    Returns:
        List of Chunk objects (token_count=0; fill with tokens.count_tokens() after).
    """
    pattern = config["pattern"]
    label_fmt = config.get("section_label_format", "{n}")
    group_size = int(config.get("group_size", 1))

    # Find all section boundaries: (start_pos, capture_group)
    matches = list(re.finditer(pattern, text, re.MULTILINE))

    if not matches:
        # No markers found — return entire text as one chunk
        return [Chunk(section_label="1", body=text.strip())]

    # Build raw sections: each section is the text between consecutive matches
    sections: list[tuple[str, str]] = []  # (raw_label, body)
    for i, m in enumerate(matches):
        label_raw = m.group(1).strip() if m.lastindex and m.lastindex >= 1 else str(i + 1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            sections.append((label_raw, body))

    # Bundle consecutive sections into groups
    chunks: list[Chunk] = []
    for i in range(0, len(sections), group_size):
        group = sections[i: i + group_size]
        if not group:
            continue

        # Section label: use first section's label (or range if group_size > 1)
        first_label = group[0][0]
        if group_size > 1 and len(group) > 1:
            last_label = group[-1][0]
            raw_label = f"{first_label}-{last_label}"
        else:
            raw_label = first_label

        formatted_label = label_fmt.format(n=raw_label, heading=raw_label)
        body = "\n\n".join(b for _, b in group)

        chunks.append(Chunk(section_label=formatted_label, body=body))

    return chunks


def subsplit(chunk: Chunk, max_tokens: int, count_fn) -> list[Chunk]:
    """
    Split an oversized chunk at paragraph boundaries, suffixing labels with a/b/c...

    Args:
        chunk: The oversized Chunk.
        max_tokens: Token budget.
        count_fn: Callable(str) -> int token counter.

    Returns:
        List of sub-chunks replacing the original.
    """
    paragraphs = [p.strip() for p in chunk.body.split("\n\n") if p.strip()]
    if len(paragraphs) <= 1:
        # Can't sub-split further — return as-is
        return [chunk]

    sub_chunks = []
    current_paras: list[str] = []
    suffix_idx = 0  # 0='a', 1='b', ...

    def flush():
        nonlocal current_paras, suffix_idx
        if not current_paras:
            return
        suffix = chr(ord("a") + suffix_idx)
        label = f"{chunk.section_label}{suffix}"
        body = "\n\n".join(current_paras)
        sub_chunks.append(Chunk(section_label=label, body=body, token_count=count_fn(body)))
        current_paras = []
        suffix_idx += 1

    for para in paragraphs:
        candidate = "\n\n".join(current_paras + [para])
        if current_paras and count_fn(candidate) > max_tokens:
            flush()
        current_paras.append(para)

    flush()
    return sub_chunks if sub_chunks else [chunk]
