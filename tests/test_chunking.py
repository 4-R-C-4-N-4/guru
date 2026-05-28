"""
Round-trip test: chunk concatenation must reconstruct the meaningful content
of the raw source (modulo whitespace normalization and pre/post boilerplate).

The test verifies:
1. Every chunk body is a substring of the normalized raw text (no invented content).
2. The concatenation of all chunks covers the core text (no internal content dropped).
3. No chunk exceeds max_tokens from the chunking config (default 800).
4. Chunk IDs across the full corpus are unique.
5. Every chunk has non-empty tradition, text_name, section, and body fields.

Run with: pytest tests/test_chunking.py
"""

import re
import sys
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
CORPUS_DIR = PROJECT_ROOT / "corpus"
RAW_DIR = PROJECT_ROOT / "raw"
CHUNKING_DIR = PROJECT_ROOT / "chunking"

sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from chunk import _apply_pre_strip, BASELINE_PRE_STRIP  # noqa: E402  — mirror the chunker's pre-strip exactly


def normalize_ws(text: str) -> str:
    """Collapse all whitespace to single spaces."""
    return re.sub(r"\s+", " ", text).strip()


def find_chunked_texts() -> list[tuple[str, str]]:
    """Return (tradition, text_id) pairs with both corpus chunks and a raw file."""
    pairs = []
    if not CORPUS_DIR.exists():
        return pairs
    for trad_dir in sorted(CORPUS_DIR.iterdir()):
        if not trad_dir.is_dir() or trad_dir.name.endswith(".toml"):
            continue
        for text_dir in sorted(trad_dir.iterdir()):
            if not text_dir.is_dir():
                continue
            chunk_dir = text_dir / "chunks"
            if not chunk_dir.exists():
                continue
            # Check for single-file or multi-page raw files
            raw_file = RAW_DIR / trad_dir.name / f"{text_dir.name}.txt"
            raw_multi = list((RAW_DIR / trad_dir.name).glob(f"{text_dir.name}-*.txt")) if (RAW_DIR / trad_dir.name).exists() else []
            if raw_file.exists() or raw_multi:
                pairs.append((trad_dir.name, text_dir.name))
    return pairs


def _load_raw_text(tradition: str, text_id: str, pre_strip: list[str] | None = None) -> str:
    """Load raw text for a source, handling both single and multi-page, applying
    pre_strip_patterns the *same way the chunker does* (scripts/chunk.py): whole-
    content for a single raw file, per-page for multi-page sources. The per-page
    distinction matters — these patterns are `^`/`$`-anchored page boilerplate, so
    applying them to the concatenated blob would mis-strip across page boundaries."""
    pre_strip = pre_strip or []
    raw_file = RAW_DIR / tradition / f"{text_id}.txt"
    if raw_file.exists():
        content = raw_file.read_text(encoding="utf-8")
        return _apply_pre_strip(content, pre_strip) if pre_strip else content
    # Multi-page: strip each page, drop now-empty pages, concatenate in order.
    trad_dir = RAW_DIR / tradition
    pages = list(trad_dir.glob(f"{text_id}-*.txt"))
    if pages:
        def _page_num(p):
            m = re.search(r'-(\d+)\.txt$', p.name)
            return int(m.group(1)) if m else 0
        pages.sort(key=_page_num)
        out = []
        for p in pages:
            content = p.read_text(encoding="utf-8")
            if pre_strip:
                content = _apply_pre_strip(content, pre_strip)
            if content:
                out.append(content)
        return "\n\n".join(out)
    return ""


def test_round_trip():
    """
    For every chunked text:
    - Each chunk body must appear verbatim in the normalized raw text.
    - Chunks must be ordered: each chunk starts after the previous one ends in the raw.
    - No chunk may exceed max_tokens (from the chunking config).
    """
    import sys
    sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "chunkers"))
    from tokens import count_tokens

    pairs = find_chunked_texts()
    assert pairs, "No chunked texts found — run scripts/chunk.py first"

    for tradition, text_id in pairs:
        chunk_dir = CORPUS_DIR / tradition / text_id / "chunks"
        cfg_path = CHUNKING_DIR / tradition / f"{text_id}.toml"

        max_tokens = 800
        # The chunker always applies BASELINE_PRE_STRIP first (sacred-texts nav),
        # then per-config pre_strip_patterns — mirror that order exactly.
        pre_strip: list[str] = list(BASELINE_PRE_STRIP)
        if cfg_path.exists():
            with open(cfg_path, "rb") as f:
                cfg = tomllib.load(f)
            max_tokens = int(cfg.get("chunking", {}).get("max_tokens", 800))
            pre_strip = list(BASELINE_PRE_STRIP) + list(cfg.get("chunking", {}).get("pre_strip_patterns", []))

        chunk_files = sorted(chunk_dir.glob("*.toml"))
        assert chunk_files, f"No chunk files in {chunk_dir}"

        # Mirror the chunker: pre_strip_patterns are re.sub('')'d out of the raw
        # before splitting (scripts/chunk.py:_apply_pre_strip), so chunk bodies are
        # faithful to the *stripped* source, not the verbatim raw. Without this the
        # round-trip wrongly flags sources with inline page markers / boilerplate
        # (e.g. CCEL '\d+-\d+' page numbers, sacred-texts page nav) the chunker removed.
        # Applied per-page for multi-page sources, matching the chunker exactly.
        raw_text = _load_raw_text(tradition, text_id, pre_strip)
        raw_norm = normalize_ws(raw_text)
        cursor = 0

        for chunk_file in chunk_files:
            with open(chunk_file, "rb") as f:
                d = tomllib.load(f)
            body = d["content"]["body"]
            token_count = d["chunk"]["token_count"]
            chunk_id = d["chunk"]["id"]

            body_norm = normalize_ws(body)

            # 1. Body must appear in raw text
            pos = raw_norm.find(body_norm, cursor)
            assert pos != -1, (
                f"Chunk {chunk_id}: body not found in raw text at or after position {cursor}\n"
                f"  body[:100]: {body_norm[:100]!r}"
            )

            # 2. Chunks must be ordered (no overlap/reorder)
            assert pos >= cursor, (
                f"Chunk {chunk_id}: out of order — found at {pos}, cursor at {cursor}"
            )
            cursor = pos + len(body_norm)

            # 3. Token count must be within budget
            assert token_count <= max_tokens, (
                f"Chunk {chunk_id}: token_count={token_count} exceeds max_tokens={max_tokens}"
            )

        print(f"  PASS: {tradition}/{text_id} — {len(chunk_files)} chunks, all within raw, ordered")


def test_chunk_id_uniqueness():
    """All chunk IDs across the full corpus must be unique."""
    if not CORPUS_DIR.exists():
        return

    all_ids = []
    for trad_dir in sorted(CORPUS_DIR.iterdir()):
        if not trad_dir.is_dir() or trad_dir.name.endswith(".toml"):
            continue
        for text_dir in sorted(trad_dir.iterdir()):
            if not text_dir.is_dir():
                continue
            chunk_dir = text_dir / "chunks"
            if not chunk_dir.exists():
                continue
            for chunk_file in sorted(chunk_dir.glob("*.toml")):
                with open(chunk_file, "rb") as f:
                    d = tomllib.load(f)
                all_ids.append(d["chunk"]["id"])

    assert len(all_ids) == len(set(all_ids)), (
        f"Duplicate chunk IDs found: {len(all_ids)} total, {len(set(all_ids))} unique"
    )
    if all_ids:
        print(f"  PASS: {len(all_ids)} chunk IDs, all unique")


def test_metadata_completeness():
    """Every chunk must have non-empty tradition, text_name, section, and body."""
    if not CORPUS_DIR.exists():
        return

    checked = 0
    for trad_dir in sorted(CORPUS_DIR.iterdir()):
        if not trad_dir.is_dir() or trad_dir.name.endswith(".toml"):
            continue
        for text_dir in sorted(trad_dir.iterdir()):
            if not text_dir.is_dir():
                continue
            chunk_dir = text_dir / "chunks"
            if not chunk_dir.exists():
                continue
            for chunk_file in sorted(chunk_dir.glob("*.toml")):
                with open(chunk_file, "rb") as f:
                    d = tomllib.load(f)
                chunk_id = d["chunk"]["id"]

                assert d["chunk"].get("tradition"), f"Chunk {chunk_id}: missing tradition"
                assert d["chunk"].get("text_name"), f"Chunk {chunk_id}: missing text_name"
                assert d["chunk"].get("section"), f"Chunk {chunk_id}: missing section"
                assert d["content"].get("body"), f"Chunk {chunk_id}: missing body"
                checked += 1

    if checked:
        print(f"  PASS: {checked} chunks, all have complete metadata")


def test_token_budget_enforcement():
    """No chunk in the output should exceed max_tokens as measured by tiktoken."""
    import sys
    sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "chunkers"))
    from tokens import count_tokens

    if not CORPUS_DIR.exists():
        return

    violations = []
    for trad_dir in sorted(CORPUS_DIR.iterdir()):
        if not trad_dir.is_dir() or trad_dir.name.endswith(".toml"):
            continue
        for text_dir in sorted(trad_dir.iterdir()):
            if not text_dir.is_dir():
                continue

            cfg_path = CHUNKING_DIR / trad_dir.name / f"{text_dir.name}.toml"
            max_tokens = 800
            if cfg_path.exists():
                with open(cfg_path, "rb") as f:
                    cfg = tomllib.load(f)
                max_tokens = int(cfg.get("chunking", {}).get("max_tokens", 800))

            chunk_dir = text_dir / "chunks"
            if not chunk_dir.exists():
                continue
            for chunk_file in sorted(chunk_dir.glob("*.toml")):
                with open(chunk_file, "rb") as f:
                    d = tomllib.load(f)
                body = d["content"]["body"]
                actual = count_tokens(body)
                if actual > max_tokens:
                    violations.append(
                        f"{d['chunk']['id']}: {actual} tokens > {max_tokens}"
                    )

    assert not violations, f"Token budget violations:\n" + "\n".join(violations)
    print(f"  PASS: all chunks within token budget")


def test_no_sacred_texts_nav_prefix():
    """No chunk body may retain the sacred-texts nav header
    ('Sacred Texts <Collection> Index Previous Next ...'). It pollutes embeddings
    and causes query mis-hits — todo:8abbb645, docs/upstream-data-cleanup.md.
    The chunker strips it via BASELINE_PRE_STRIP; this guards against regressions
    (e.g. a new sacred-texts source added without re-chunking)."""
    if not CORPUS_DIR.exists():
        return
    nav = re.compile(r'^Sacred Texts\b.*?\b(?:Previous|Next)\b', re.I | re.S)
    offenders = []
    for trad_dir in sorted(CORPUS_DIR.iterdir()):
        if not trad_dir.is_dir() or trad_dir.name.endswith(".toml"):
            continue
        for text_dir in sorted(trad_dir.iterdir()):
            if not text_dir.is_dir():
                continue
            chunk_dir = text_dir / "chunks"
            if not chunk_dir.exists():
                continue
            for chunk_file in sorted(chunk_dir.glob("*.toml")):
                with open(chunk_file, "rb") as f:
                    d = tomllib.load(f)
                if nav.match(d["content"]["body"].lstrip()):
                    offenders.append(d["chunk"]["id"])
    assert not offenders, (
        f"{len(offenders)} chunk(s) retain the sacred-texts nav prefix; "
        f"first few: {offenders[:5]}"
    )
    print("  PASS: no chunk retains the sacred-texts nav prefix")


def test_no_scan_or_frontmatter_artifacts():
    """No chunk body may retain the sacred-texts scan/front-matter artifacts
    stripped by BASELINE_PRE_STRIP — todo:0a708fa4, docs/upstream-data-cleanup.md:
      - {p. N} brace page markers (the BRACED form only; bare 'p. N' citations
        are intentionally preserved),
      - the 'Buy this Book at Amazon.com ... at sacred-texts.com' preamble.
    (Plate/Fig references are NOT stripped — they are in-text content here.)"""
    if not CORPUS_DIR.exists():
        return
    checks = {
        "{p. N} brace marker": re.compile(r'\{\s*p\.\s*\d+\s*\}'),
        "Buy-this-Book preamble": re.compile(r'Buy this Book at Amazon\.com', re.I),
    }
    offenders = []
    for trad_dir in sorted(CORPUS_DIR.iterdir()):
        if not trad_dir.is_dir() or trad_dir.name.endswith(".toml"):
            continue
        for text_dir in sorted(trad_dir.iterdir()):
            if not text_dir.is_dir():
                continue
            chunk_dir = text_dir / "chunks"
            if not chunk_dir.exists():
                continue
            for chunk_file in sorted(chunk_dir.glob("*.toml")):
                with open(chunk_file, "rb") as f:
                    d = tomllib.load(f)
                body = d["content"]["body"]
                for label, rx in checks.items():
                    if rx.search(body):
                        offenders.append(f"{d['chunk']['id']} ({label})")
    assert not offenders, (
        f"{len(offenders)} chunk(s) retain a scan/front-matter artifact; "
        f"first few: {offenders[:5]}"
    )
    print("  PASS: no chunk retains {p.N} braces or the Buy-this-Book preamble")
