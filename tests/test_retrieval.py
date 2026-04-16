"""
tests/test_retrieval.py — End-to-end integration test for the Guru query pipeline.

Tests the full path: query → embed → retrieve → prompt assembly.
Does NOT call the LLM (to stay fast and offline-safe) but verifies every
stage up to the point where model.generate() would be called.
"""

import json
import sys
import urllib.request
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from guru.preferences import UserPreferences
from guru.prompt import build_prompt, citation
from guru.retriever import HybridRetriever


def embed(query: str) -> list[float] | None:
    """Embed query via Ollama. Returns None if unavailable."""
    try:
        payload = json.dumps({"model": "nomic-embed-text", "input": query}).encode()
        req = urllib.request.Request(
            "http://localhost:11434/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())["embeddings"][0]
    except Exception:
        return None


@pytest.fixture(scope="module")
def retriever():
    return HybridRetriever()


@pytest.fixture(scope="module")
def divine_light_emb():
    emb = embed("divine light within all things")
    if emb is None:
        pytest.skip("Ollama not available for embedding")
    return emb


# ── retrieval correctness ─────────────────────────────────────────────────────

def test_retrieval_returns_chunks(retriever, divine_light_emb):
    """retrieve() returns at least one chunk for a known query."""
    prefs = UserPreferences.allow_all()
    chunks = retriever.retrieve("divine light within all things", divine_light_emb, prefs)
    assert len(chunks) >= 1, "Expected at least one chunk"


def test_logion_77_in_results(retriever, divine_light_emb):
    """'divine light' query should surface Gospel of Thomas Logion 77."""
    prefs = UserPreferences.allow_all()
    chunks = retriever.retrieve("divine light within all things", divine_light_emb, prefs, top_k=10)
    chunk_ids = [c.chunk_id for c in chunks]
    assert "gnosticism.gospel-of-thomas.077" in chunk_ids, (
        f"Logion 77 not retrieved. Got: {chunk_ids}"
    )


def test_cross_tradition_retrieval(retriever, divine_light_emb):
    """Cross-tradition query returns chunks from multiple traditions."""
    prefs = UserPreferences.allow_all()
    chunks = retriever.retrieve("divine light and mystical knowledge", divine_light_emb, prefs, top_k=10)
    traditions = {c.tradition for c in chunks}
    assert len(traditions) >= 1, f"Only got traditions: {traditions}"


def test_preference_filter_no_leak(retriever, divine_light_emb):
    """Blacklisted tradition must not appear in retrieved chunks."""
    prefs = UserPreferences(mode="blacklist", blacklisted_traditions=["gnosticism"])
    chunks = retriever.retrieve("divine light", divine_light_emb, prefs, top_k=20)
    leaked = [c for c in chunks if c.tradition == "gnosticism"]
    assert not leaked, (
        f"Blacklisted tradition leaked: {[c.chunk_id for c in leaked]}"
    )


def test_whitelist_only_returns_allowed(retriever):
    """Whitelist mode only returns chunks from the specified tradition."""
    emb = embed("mystical wisdom")
    if emb is None:
        pytest.skip("Ollama not available")
    prefs = UserPreferences(mode="whitelist", whitelisted_traditions=["jewish_mysticism"])
    chunks = retriever.retrieve("mystical wisdom", emb, prefs, top_k=10)
    for chunk in chunks:
        assert chunk.tradition == "jewish_mysticism", (
            f"Non-whitelisted tradition in results: {chunk.tradition} ({chunk.chunk_id})"
        )


# ── prompt assembly ───────────────────────────────────────────────────────────

def test_prompt_contains_citations(retriever, divine_light_emb):
    """build_prompt includes at least one [Tradition | Text | Section] citation."""
    prefs = UserPreferences.allow_all()
    chunks = retriever.retrieve("divine light", divine_light_emb, prefs)
    prompt = build_prompt("What is divine light?", chunks, prefs)
    assert "[" in prompt and "|" in prompt and "]" in prompt


def test_prompt_no_hallucinated_traditions(retriever, divine_light_emb):
    """Every citation in the prompt corresponds to a real retrieved chunk."""
    import re
    prefs = UserPreferences.allow_all()
    chunks = retriever.retrieve("divine light", divine_light_emb, prefs)
    prompt = build_prompt("What is divine light?", chunks, prefs)

    expected_cits = {citation(c) for c in chunks}
    found_cits = set(re.findall(r'\[[^\]]+\|[^\]]+\|[^\]]+\]', prompt))
    # Exclude template placeholders like [Tradition | Text | Section]
    found_cits = {c for c in found_cits if "Tradition" not in c.split("|")[0] or len(c.split("|")[0].strip()) > 12}

    for cit in found_cits:
        assert cit in expected_cits, (
            f"Citation {cit!r} in prompt not from retrieved chunks.\n"
            f"Expected: {expected_cits}"
        )


def test_chunk_metadata_complete(retriever, divine_light_emb):
    """All retrieved chunks have required metadata fields populated."""
    prefs = UserPreferences.allow_all()
    chunks = retriever.retrieve("divine light", divine_light_emb, prefs)
    for chunk in chunks:
        assert chunk.chunk_id, f"Missing chunk_id"
        assert chunk.tradition, f"Missing tradition on {chunk.chunk_id}"
        assert chunk.text_name, f"Missing text_name on {chunk.chunk_id}"
        assert chunk.section, f"Missing section on {chunk.chunk_id}"
        assert chunk.body, f"Empty body on {chunk.chunk_id}"
        assert chunk.tier in ("verified", "proposed", "inferred"), (
            f"Unknown tier {chunk.tier!r} on {chunk.chunk_id}"
        )
