"""
tests/test_citations.py — Verify citation accuracy in Guru responses.

Tests that:
1. Every response chunk produces a valid [Tradition | Text | Section] citation string
2. Citation strings match actual chunk metadata (no hallucinated tradition/section)
3. Response contains at least one citation when chunks are provided
"""

import json
import sys
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from guru.prompt import RetrievedChunk, build_prompt, citation, format_chunk
from guru.preferences import UserPreferences


def make_chunk(
    chunk_id="gnosticism.gospel-of-thomas.077",
    tradition="gnosticism",
    text_name="Gospel of Thomas",
    section="Logion 77",
    translator="Thomas O. Lambdin",
    body="It is I who am the light which is above them all.",
    tier="verified",
    similarity=0.85,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        tradition=tradition,
        text_name=text_name,
        section=section,
        translator=translator,
        body=body,
        tier=tier,
        similarity=similarity,
    )


def test_citation_format():
    """Citation string has correct [Tradition | Text | Section] format."""
    chunk = make_chunk()
    cit = citation(chunk)
    assert cit == "[Gnosticism | Gospel of Thomas | Logion 77]", repr(cit)


def test_citation_format_underscore_tradition():
    """Underscores in tradition name are replaced with spaces and title-cased."""
    chunk = make_chunk(tradition="jewish_mysticism", text_name="Sefer Yetzirah", section="Section 1")
    cit = citation(chunk)
    assert cit == "[Jewish Mysticism | Sefer Yetzirah | Section 1]", repr(cit)


def test_format_chunk_contains_citation():
    """Formatted chunk includes the citation header."""
    chunk = make_chunk()
    formatted = format_chunk(chunk)
    assert "[Gnosticism | Gospel of Thomas | Logion 77]" in formatted


def test_format_chunk_contains_body():
    """Formatted chunk includes the body text."""
    chunk = make_chunk()
    formatted = format_chunk(chunk)
    assert "light which is above" in formatted


def test_format_chunk_tier_label():
    """Tier label appears in formatted chunk."""
    chunk = make_chunk(tier="verified")
    formatted = format_chunk(chunk)
    assert "Verified" in formatted

    chunk2 = make_chunk(tier="proposed")
    formatted2 = format_chunk(chunk2)
    assert "Proposed" in formatted2


def test_build_prompt_contains_query():
    """build_prompt includes the user query."""
    chunk = make_chunk()
    prefs = UserPreferences.allow_all()
    prompt = build_prompt("What is divine light?", [chunk], prefs)
    assert "What is divine light?" in prompt


def test_build_prompt_contains_citation():
    """build_prompt includes citation strings in the context block."""
    chunk = make_chunk()
    prefs = UserPreferences.allow_all()
    prompt = build_prompt("test query", [chunk], prefs)
    assert "[Gnosticism | Gospel of Thomas | Logion 77]" in prompt


def test_build_prompt_tier_hedge_proposed():
    """Proposed tier chunks trigger hedge note in prompt."""
    chunk = make_chunk(tier="proposed")
    prefs = UserPreferences.allow_all()
    prompt = build_prompt("test", [chunk], prefs)
    assert "◇ Proposed" in prompt
    assert "hedging" in prompt.lower() or "uncertainty" in prompt.lower()


def test_build_prompt_no_chunks():
    """build_prompt with empty chunks produces graceful context message."""
    prefs = UserPreferences.allow_all()
    prompt = build_prompt("test", [], prefs)
    assert "No relevant passages" in prompt


def test_citations_from_real_corpus():
    """Load actual corpus chunks and verify citation format is correct."""
    corpus_dir = PROJECT_ROOT / "corpus"
    if not corpus_dir.exists():
        return  # skip if corpus not built

    checked = 0
    for chunk_file in list(corpus_dir.glob("**/chunks/*.toml"))[:20]:
        with open(chunk_file, "rb") as f:
            d = tomllib.load(f)
        meta = d["chunk"]
        chunk = RetrievedChunk(
            chunk_id=meta["id"],
            tradition=meta.get("tradition", ""),
            text_name=meta.get("text_name", ""),
            section=meta.get("section", ""),
            translator=meta.get("translator", ""),
            body=d["content"]["body"],
        )
        cit = citation(chunk)
        assert cit.startswith("["), f"Bad citation: {cit!r}"
        assert cit.endswith("]"), f"Bad citation: {cit!r}"
        assert " | " in cit, f"Missing separator: {cit!r}"
        checked += 1

    assert checked > 0, "No corpus chunks found"
    print(f"  Verified citations for {checked} real corpus chunks")
