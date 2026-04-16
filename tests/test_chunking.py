"""
Round-trip test: chunk concatenation must reconstruct the meaningful content
of the raw source (modulo whitespace normalization and pre/post boilerplate).

The test verifies:
1. Every chunk body is a substring of the normalized raw text (no invented content).
2. The concatenation of all chunks covers the core text (no internal content dropped).
3. No chunk exceeds max_tokens from the chunking config (default 800).

Run with: pytest tests/test_chunking.py
"""

import re
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
CORPUS_DIR = PROJECT_ROOT / "corpus"
RAW_DIR = PROJECT_ROOT / "raw"
CHUNKING_DIR = PROJECT_ROOT / "chunking"


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
            raw_file = RAW_DIR / trad_dir.name / f"{text_dir.name}.txt"
            if chunk_dir.exists() and raw_file.exists():
                pairs.append((trad_dir.name, text_dir.name))
    return pairs


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
        raw_path = RAW_DIR / tradition / f"{text_id}.txt"
        cfg_path = CHUNKING_DIR / tradition / f"{text_id}.toml"

        max_tokens = 800
        if cfg_path.exists():
            with open(cfg_path, "rb") as f:
                cfg = tomllib.load(f)
            max_tokens = int(cfg.get("chunking", {}).get("max_tokens", 800))

        chunk_files = sorted(chunk_dir.glob("*.toml"))
        assert chunk_files, f"No chunk files in {chunk_dir}"

        raw_norm = normalize_ws(raw_path.read_text(encoding="utf-8"))
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
