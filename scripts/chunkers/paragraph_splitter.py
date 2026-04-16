"""
Paragraph-grouping splitter for prose texts lacking explicit section markers.

Used for: mystical treatises, sermon prose, texts with no numbered divisions.
"""

from dataclasses import dataclass, field

from regex_splitter import Chunk  # reuse Chunk dataclass


def split(text: str, config: dict) -> list[Chunk]:
    """
    Split text on blank-line paragraph boundaries, bundling group_size paragraphs
    per chunk.

    Args:
        text: Raw plaintext.
        config: Chunking config dict.
                Optional: section_label_format (default "Section {n}"),
                          max_tokens (default 800),
                          group_size (default 3).

    Returns:
        List of Chunk objects.
    """
    label_fmt = config.get("section_label_format", "Section {n}")
    group_size = int(config.get("group_size", 3))

    # Split on blank lines
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    if not paragraphs:
        return [Chunk(section_label="Section 1", body=text.strip())]

    chunks: list[Chunk] = []
    section_counter = 1

    for i in range(0, len(paragraphs), group_size):
        group = paragraphs[i: i + group_size]
        body = "\n\n".join(group)
        label = label_fmt.format(n=section_counter, heading=f"Section {section_counter}")
        chunks.append(Chunk(section_label=label, body=body))
        section_counter += 1

    return chunks
