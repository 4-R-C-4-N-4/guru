"""
tests/test_preferences.py — Verify UserPreferences filtering is leak-proof.

Tests that excluded traditions never appear in results, and that
to_vector_filters() and is_chunk_allowed() agree with each other.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from guru.preferences import UserPreferences


# ── allow_all ────────────────────────────────────────────────────────────────

def test_allow_all_permits_everything():
    prefs = UserPreferences.allow_all()
    assert prefs.is_chunk_allowed("gnosticism")
    assert prefs.is_chunk_allowed("hermeticism")
    assert prefs.is_chunk_allowed("buddhism")
    assert prefs.to_vector_filters() is None


# ── blacklist ─────────────────────────────────────────────────────────────────

def test_blacklist_blocks_excluded_tradition():
    prefs = UserPreferences(mode="blacklist", blacklisted_traditions=["gnosticism"])
    assert not prefs.is_chunk_allowed("gnosticism")
    assert prefs.is_chunk_allowed("hermeticism")
    assert prefs.is_chunk_allowed("jewish_mysticism")


def test_blacklist_blocks_excluded_text():
    prefs = UserPreferences(mode="blacklist", blacklisted_texts=["gospel-of-thomas"])
    assert not prefs.is_chunk_allowed("gnosticism", "gospel-of-thomas")
    assert prefs.is_chunk_allowed("gnosticism", "gospel-of-philip")


def test_blacklist_vector_filter_single():
    prefs = UserPreferences(mode="blacklist", blacklisted_traditions=["gnosticism"])
    filt = prefs.to_vector_filters()
    assert filt is not None
    assert filt == {"tradition": {"$ne": "gnosticism"}}


def test_blacklist_vector_filter_multiple():
    prefs = UserPreferences(
        mode="blacklist",
        blacklisted_traditions=["gnosticism", "hermeticism"],
    )
    filt = prefs.to_vector_filters()
    assert filt is not None
    assert "$and" in filt
    conditions = filt["$and"]
    excluded = [c["tradition"]["$ne"] for c in conditions if "tradition" in c]
    assert "gnosticism" in excluded
    assert "hermeticism" in excluded


def test_blacklist_empty_returns_none():
    prefs = UserPreferences(mode="blacklist")
    assert prefs.to_vector_filters() is None


# ── whitelist ─────────────────────────────────────────────────────────────────

def test_whitelist_only_allows_listed():
    prefs = UserPreferences(mode="whitelist", whitelisted_traditions=["gnosticism"])
    assert prefs.is_chunk_allowed("gnosticism")
    assert not prefs.is_chunk_allowed("hermeticism")
    assert not prefs.is_chunk_allowed("buddhism")


def test_whitelist_allows_listed_text():
    prefs = UserPreferences(mode="whitelist", whitelisted_texts=["gospel-of-thomas"])
    assert prefs.is_chunk_allowed("gnosticism", "gospel-of-thomas")
    assert not prefs.is_chunk_allowed("gnosticism", "gospel-of-philip")


def test_whitelist_vector_filter():
    prefs = UserPreferences(mode="whitelist", whitelisted_traditions=["gnosticism", "hermeticism"])
    filt = prefs.to_vector_filters()
    assert filt is not None
    assert "tradition" in filt
    assert "$in" in filt["tradition"]
    assert "gnosticism" in filt["tradition"]["$in"]
    assert "hermeticism" in filt["tradition"]["$in"]


def test_whitelist_empty_returns_none():
    prefs = UserPreferences(mode="whitelist")
    assert prefs.to_vector_filters() is None


# ── from_dict ────────────────────────────────────────────────────────────────

def test_from_dict_roundtrip():
    d = {
        "mode": "blacklist",
        "blacklisted_traditions": ["buddhism"],
        "blacklisted_texts": [],
        "whitelisted_traditions": [],
        "whitelisted_texts": [],
    }
    prefs = UserPreferences.from_dict(d)
    assert prefs.mode == "blacklist"
    assert "buddhism" in prefs.blacklisted_traditions
    assert not prefs.is_chunk_allowed("buddhism")
    assert prefs.is_chunk_allowed("gnosticism")


# ── active_tradition_summary ─────────────────────────────────────────────────

def test_summary_all():
    assert "All" in UserPreferences.allow_all().active_tradition_summary()


def test_summary_blacklist():
    prefs = UserPreferences(mode="blacklist", blacklisted_traditions=["gnosticism"])
    summary = prefs.active_tradition_summary()
    assert "gnosticism" in summary
    assert "except" in summary.lower()


def test_summary_whitelist():
    prefs = UserPreferences(mode="whitelist", whitelisted_traditions=["hermeticism"])
    summary = prefs.active_tradition_summary()
    assert "hermeticism" in summary
    assert "Only" in summary


# ── no-leak integration with live vector store ───────────────────────────────

def test_vector_store_respects_blacklist():
    """End-to-end: excluded tradition must not appear in vector query results."""
    try:
        from vector_store import VectorStore
        vs = VectorStore()
        if vs.count() == 0:
            print("  Vector store empty — skipping integration test")
            return
    except Exception as e:
        print(f"  Vector store not available: {e} — skipping")
        return

    import json
    import urllib.request

    # Embed a generic query
    payload = json.dumps({"model": "nomic-embed-text", "input": "divine light"}).encode()
    req = urllib.request.Request(
        "http://localhost:11434/api/embed",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            emb = json.loads(resp.read())["embeddings"][0]
    except Exception:
        print("  Ollama not available — skipping integration test")
        return

    prefs = UserPreferences(mode="blacklist", blacklisted_traditions=["gnosticism"])
    results = vs.query(embedding=emb, top_n=20, where=prefs.to_vector_filters())

    leaked = [r for r in results if r["metadata"].get("tradition") == "gnosticism"]
    assert not leaked, f"Blacklisted tradition leaked into results: {[r['chunk_id'] for r in leaked]}"
    print(f"  No-leak check PASSED ({len(results)} results, 0 gnosticism)")
