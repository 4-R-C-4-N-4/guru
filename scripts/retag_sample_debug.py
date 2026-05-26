"""
retag_sample_debug.py — one-off: re-tag a hand-picked sample of chunks
and persist the full LLM input/output for forensic inspection.

Reuses tag_concepts.build_prompt and parse_tags so this exercises the
exact same prompt/parse path as the production run. Writes one JSON
artifact per chunk to data/retag-debug/<chunk_id>.json. Does NOT touch
guru.db or staged_tags.

Used to investigate the zero-tag chunks from the 2026-05 teacher run
(see docs/80-concept-teacher-run-retro.md).
"""

import json
import sqlite3
import sys
import time
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from guru.corpus import resolve_chunk_path  # noqa: E402
from llm import call_llm, parse_json_response  # noqa: E402
from tag_concepts import (  # noqa: E402
    SYSTEM_PROMPT,
    build_prompt,
    load_taxonomy,
    parse_tags,
)

PROVIDER = "llamacpp"
MODEL = "Qwen3.5-27B-UD-Q4_K_XL.gguf"
MAX_TOKENS = 6000
OUT_DIR = PROJECT_ROOT / "data" / "retag-debug"
DB_PATH = PROJECT_ROOT / "data" / "guru.db"

SAMPLE_CHUNK_IDS = [
    "western_esoteric.tertium-organum.010",
    "western_esoteric.tertium-organum.030",
    "western_esoteric.tertium-organum.070",
    "western_esoteric.tertium-organum.090",
    "western_esoteric.tertium-organum.120",
    "western_esoteric.tertium-organum.130",
    "western_esoteric.tertium-organum.150",
    "western_esoteric.tertium-organum.190",
    "western_esoteric.tertium-organum.200",
    "western_esoteric.tertium-organum.210",
    "christian_mysticism.life-and-doctrines-boehme.010",
    "christian_mysticism.life-and-doctrines-boehme.025",
    "christian_mysticism.life-and-doctrines-boehme.035",
    "christian_mysticism.life-and-doctrines-boehme.055",
    "christian_mysticism.life-and-doctrines-boehme.065",
    "christian_mysticism.life-and-doctrines-boehme.080",
    "christian_mysticism.life-and-doctrines-boehme.100",
    "christian_mysticism.life-and-doctrines-boehme.115",
    "christian_mysticism.life-and-doctrines-boehme.135",
    "christian_mysticism.life-and-doctrines-boehme.155",
]


def load_chunk(chunk_id: str, conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        "SELECT label, metadata_json FROM nodes WHERE id = ? AND type = 'chunk'",
        (chunk_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"chunk not found in DB: {chunk_id}")
    label, meta_json = row
    chunk_file = resolve_chunk_path(chunk_id)
    if chunk_file is None:
        raise RuntimeError(f"chunk file not found on disk: {chunk_id}")
    with open(chunk_file, "rb") as f:
        cd = tomllib.load(f)
    return {
        "label": label,
        "meta": json.loads(meta_json),
        "body": cd["content"]["body"],
        "section": cd["chunk"].get("section"),
        "token_count": cd["chunk"].get("token_count"),
    }


def classify(raw: str, parsed, final_tags: list[dict]) -> str:
    """Map the response to one of four failure-mode buckets."""
    if not raw or not raw.strip():
        return "empty_response"
    if not isinstance(parsed, list):
        if isinstance(parsed, dict):
            return "parsed_object_not_array"
        return "parse_failure"
    if len(parsed) == 0:
        return "empty_array"
    # parsed has items but final_tags is empty → all items had score < 1
    if len(final_tags) == 0:
        return "all_below_threshold"
    return "tags_emitted"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    concepts = load_taxonomy()
    conn = sqlite3.connect(str(DB_PATH))

    print(f"Re-tagging {len(SAMPLE_CHUNK_IDS)} chunks with {PROVIDER}/{MODEL}")
    print(f"Output dir: {OUT_DIR}")
    print(f"Concepts loaded: {len(concepts)}")
    print()

    for i, chunk_id in enumerate(SAMPLE_CHUNK_IDS, 1):
        out_path = OUT_DIR / f"{chunk_id}.json"
        try:
            chunk = load_chunk(chunk_id, conn)
        except Exception as e:
            print(f"[{i:2d}/{len(SAMPLE_CHUNK_IDS)}] {chunk_id}: LOAD FAILED — {e}")
            continue

        prompt = build_prompt(chunk["body"], chunk["label"], concepts)
        t0 = time.time()
        error = None
        try:
            raw = call_llm(PROVIDER, MODEL, SYSTEM_PROMPT, prompt, max_tokens=MAX_TOKENS)
        except Exception as e:
            raw = ""
            error = repr(e)
        latency = time.time() - t0

        try:
            parsed = parse_json_response(raw) if raw else []
        except Exception as e:
            parsed = None
            if error is None:
                error = f"parse_json_response raised: {e!r}"

        try:
            final_tags = parse_tags(raw) if raw else []
        except Exception as e:
            final_tags = []
            if error is None:
                error = f"parse_tags raised: {e!r}"

        bucket = classify(raw, parsed, final_tags)

        artifact = {
            "chunk_id": chunk_id,
            "section": chunk["section"],
            "token_count": chunk["token_count"],
            "citation": chunk["label"],
            "provider": PROVIDER,
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "latency_seconds": round(latency, 3),
            "error": error,
            "classification": bucket,
            "raw_length": len(raw),
            "raw_response": raw,
            "parsed_json": parsed if isinstance(parsed, (list, dict)) else None,
            "final_tags": final_tags,
            "prompt": prompt,
            "system_prompt": SYSTEM_PROMPT,
            "body": chunk["body"],
        }
        with open(out_path, "w") as f:
            json.dump(artifact, f, indent=2, ensure_ascii=False)

        print(
            f"[{i:2d}/{len(SAMPLE_CHUNK_IDS)}] {chunk_id}: "
            f"{bucket:>22s} | raw={len(raw):5d} chars | "
            f"parsed_items={len(parsed) if isinstance(parsed, list) else 'n/a':>3} | "
            f"final_tags={len(final_tags):2d} | {latency:6.1f}s"
            + (f" | ERROR: {error}" if error else "")
        )

    conn.close()
    print()
    print(f"Done. Artifacts in {OUT_DIR}")


if __name__ == "__main__":
    main()
