"""
Paragraph-grouping splitter for prose texts lacking explicit section markers.

Groups consecutive paragraphs into chunks within a token budget, splitting
on blank lines. paragraphs_per_chunk is a soft target; actual grouping
respects max_tokens.

Strategy name: paragraph-group (legacy: paragraph)
"""

from regex_splitter import Chunk  # reuse Chunk dataclass


def split(text: str, config: dict) -> list[Chunk]:
    """
    Split text on blank-line paragraph boundaries, grouping paragraphs
    greedily within the token budget.

    Args:
        text: Raw plaintext.
        config: Chunking config dict.
                Optional: section_label_format (default "Section {n}"),
                          max_tokens (default 800),
                          paragraphs_per_chunk (soft target, default 3),
                          group_size (legacy alias for paragraphs_per_chunk).

    Returns:
        List of Chunk objects.
    """
    label_fmt = config.get("section_label_format", "Section {n}")
    max_tokens = int(config.get("max_tokens", 800))
    # paragraphs_per_chunk is the soft target; fall back to group_size for compat
    target = int(config.get("paragraphs_per_chunk",
                            config.get("group_size", 3)))

    # Lazy import to avoid circular dependency at module level
    try:
        from tokens import count_tokens
    except ImportError:
        def count_tokens(t):
            return len(t) // 4

    # Split on blank lines
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    if not paragraphs:
        return [Chunk(section_label="Section 1", body=text.strip())]

    chunks: list[Chunk] = []
    section_counter = 1
    current_paras: list[str] = []

    def flush():
        nonlocal current_paras, section_counter
        if not current_paras:
            return
        body = "\n\n".join(current_paras)
        label = label_fmt.format(n=section_counter, heading=f"Section {section_counter}")
        chunks.append(Chunk(section_label=label, body=body))
        current_paras = []
        section_counter += 1

    for para in paragraphs:
        candidate = "\n\n".join(current_paras + [para])
        candidate_tokens = count_tokens(candidate)

        # Start a new chunk if adding this paragraph would exceed the budget
        # AND we already have at least one paragraph in the current chunk
        if current_paras and candidate_tokens > max_tokens:
            flush()

        current_paras.append(para)

        # Also flush if we hit the soft target and the next paragraph
        # would likely push us over (heuristic: flush at target boundary)
        if len(current_paras) >= target:
            flush()

    flush()
    return chunks
