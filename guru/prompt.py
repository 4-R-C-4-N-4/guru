"""
guru/prompt.py — Format retrieved chunks and assemble the Guru system prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from guru.preferences import UserPreferences


# Provenance version for the tagging-time prompt (scripts/tag_concepts.py:
# build_prompt and SYSTEM_PROMPT). Bump whenever the tagging prompt template,
# the score scale, the JSON schema, or the system prompt changes — this is
# what tells the bench harness and any future fine-tune export whether two
# tagging runs are comparable.
#
# NOTE: this constant governs the tagging prompt in scripts/tag_concepts.py,
# not the retrieval-side build_prompt() defined further down this module.
# Those are different prompts for different sides of the pipeline. The
# constant lives here per docs/v3.md §4.1.
PROMPT_VERSION = "v1"


TIER_LABELS = {
    "verified": "✓ Verified",
    "proposed": "◇ Proposed",
    "inferred": "~ Inferred",
}

TIER_HEDGE = {
    "proposed": (
        "Note: the cross-tradition connection supporting this claim is a "
        "◇ Proposed edge — treat with appropriate uncertainty."
    ),
    "inferred": (
        "Note: this connection is ~ Inferred from corpus structure and has not "
        "been human-verified."
    ),
}


@dataclass
class RetrievedChunk:
    chunk_id: str
    tradition: str
    text_name: str
    section: str
    translator: str
    body: str
    token_count: int = 0
    similarity: float = 0.0
    tier: str = "inferred"          # verified | proposed | inferred
    concepts: list[str] = field(default_factory=list)
    source_url: str = ""


def citation(chunk: RetrievedChunk) -> str:
    """Return the canonical [Tradition | Text | Section] citation string."""
    trad = chunk.tradition.replace("_", " ").title()
    return f"[{trad} | {chunk.text_name} | {chunk.section}]"


def format_chunk(chunk: RetrievedChunk) -> str:
    """Format a single retrieved chunk for inclusion in the prompt context."""
    tier_label = TIER_LABELS.get(chunk.tier, chunk.tier)
    concepts_str = ", ".join(chunk.concepts) if chunk.concepts else "none tagged"
    lines = [
        "---",
        citation(chunk),
        f"Translator: {chunk.translator}" if chunk.translator else "",
        f"Concepts: {concepts_str}",
        f"Confidence: {tier_label}",
        "",
        chunk.body,
        "---",
    ]
    return "\n".join(line for line in lines if line is not None)


def format_chunks(chunks: list[RetrievedChunk]) -> str:
    """Format all retrieved chunks into the RETRIEVED CONTEXT block."""
    if not chunks:
        return "(No relevant passages retrieved.)"
    return "\n\n".join(format_chunk(c) for c in chunks)


SYSTEM_TEMPLATE = """\
You are Guru, a scholar of comparative esoteric and religious traditions. \
Your role is to provide accurate, citation-grounded answers about mystical, \
gnostic, kabbalistic, hermetic, and other esoteric traditions.

ACTIVE TRADITIONS: {active_traditions}

CITATION RULES (mandatory):
1. Every substantive claim must be followed by a [Tradition | Text | Section] citation.
2. Direct quotes must use quotation marks and cite the source immediately after.
3. Cross-tradition parallels must cite all relevant traditions.
4. When a connection is marked ◇ Proposed, use hedging language (e.g. "may parallel", "possibly related to").
5. When a connection is marked ~ Inferred, note it is algorithmically inferred.
6. If no retrieved passage supports a claim, explicitly state this — never fabricate citations.
7. Never reference traditions outside the active scope listed above.

RETRIEVED CONTEXT:
{context}

USER QUERY: {query}

Answer the query using only the retrieved context above. \
Cite every factual claim. If the context is insufficient, say so directly.
"""


def build_prompt(
    query: str,
    chunks: list[RetrievedChunk],
    prefs: "UserPreferences",
) -> str:
    """
    Assemble the full Guru system prompt with context and query.

    Returns the complete prompt string ready to send to the LLM.
    """
    context = format_chunks(chunks)
    active = prefs.active_tradition_summary()

    # Append hedging warnings for any proposed/inferred chunks
    hedge_notes = []
    for chunk in chunks:
        hedge = TIER_HEDGE.get(chunk.tier)
        if hedge and hedge not in hedge_notes:
            hedge_notes.append(hedge)

    if hedge_notes:
        context += "\n\nEDGE TIER NOTES:\n" + "\n".join(f"- {h}" for h in hedge_notes)

    return SYSTEM_TEMPLATE.format(
        active_traditions=active,
        context=context,
        query=query,
    )
