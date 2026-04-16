"""
Heading-based splitter for texts segmented by titled or numbered heading lines.

Used for: Corpus Hermeticum tractates, Sefer Yetzirah chapters, sermon collections.
"""

import re
from dataclasses import dataclass, field

from regex_splitter import Chunk, subsplit  # reuse Chunk dataclass and subsplit


def split(text: str, config: dict) -> list[Chunk]:
    """
    Split text at lines matching heading_pattern.

    Args:
        text: Raw plaintext.
        config: Chunking config dict. Required: heading_pattern.
                Optional: section_label_format (default "{heading}"),
                          max_tokens (default 800), group_size (default 1).

    Returns:
        List of Chunk objects.
    """
    heading_pattern = config["heading_pattern"]
    label_fmt = config.get("section_label_format", "{heading}")
    group_size = int(config.get("group_size", 1))

    lines = text.splitlines()
    sections: list[tuple[str, list[str]]] = []  # (heading_text, body_lines)
    current_heading: str | None = None
    current_body: list[str] = []

    for line in lines:
        if re.match(heading_pattern, line.strip()):
            if current_heading is not None or current_body:
                # Save previous section
                h = current_heading or ""
                sections.append((h, current_body))
            current_heading = line.strip()
            current_body = []
        else:
            current_body.append(line)

    # Flush last section
    if current_heading is not None or current_body:
        sections.append((current_heading or "", current_body))

    if not sections:
        return [Chunk(section_label="1", body=text.strip())]

    # Bundle and format
    chunks: list[Chunk] = []
    for i in range(0, len(sections), group_size):
        group = sections[i: i + group_size]
        if not group:
            continue

        first_heading = group[0][0]
        formatted_label = label_fmt.format(
            heading=first_heading,
            n=str(i // group_size + 1),
        )
        body_parts = []
        for heading_text, body_lines in group:
            body_text = "\n".join(body_lines).strip()
            if body_text:
                body_parts.append(body_text)
        body = "\n\n".join(body_parts)

        chunks.append(Chunk(section_label=formatted_label, body=body))

    return chunks
