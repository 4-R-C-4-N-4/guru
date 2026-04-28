"""
Guru Corpus Chunking Orchestrator

Walks chunking/{tradition}/{source_id}.toml configs, applies the named strategy
to raw/{tradition}/ files, and writes corpus/{tradition}/{text_id}/chunks/{NNN}.toml
per chunk, plus corpus/{tradition}/{text_id}/metadata.toml.

Three strategies:
  - regex-section-split: split on regex boundary markers
  - page-as-chunk: one raw file per chunk (multi-page downloads)
  - paragraph-group: greedy paragraph grouping within token budget

Idempotent: re-runs produce identical output.

Usage:
    python3 scripts/chunk.py [--dry-run] [--only <id>] [--tradition <name>] [-v]
"""

import argparse
import logging
import re
import sys
from pathlib import Path

import tomllib
import tomli_w

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
RAW_DIR = PROJECT_ROOT / "raw"
CHUNKING_DIR = PROJECT_ROOT / "chunking"
CORPUS_DIR = PROJECT_ROOT / "corpus"
CHUNKERS_DIR = Path(__file__).parent / "chunkers"

# Strategy types: "single" reads one raw file, "multi" reads {id}-NN.txt files
STRATEGY_TYPES = {
    "regex-section-split": "single",
    "page-as-chunk": "multi",
    "paragraph-group": "single",
    # backward compat
    "regex": "single",
    "paragraph": "single",
    "heading": "single",
}


def _ensure_chunkers_on_path():
    p = str(CHUNKERS_DIR)
    if p not in sys.path:
        sys.path.insert(0, p)


def load_chunking_config(tradition: str, source_id: str) -> dict | None:
    path = CHUNKING_DIR / tradition / f"{source_id}.toml"
    if not path.exists():
        return None
    with open(path, "rb") as f:
        return tomllib.load(f)


def write_chunk_file(path: Path, chunk_data: dict, dry_run: bool = False) -> None:
    if dry_run:
        logger.info(f"  [dry-run] Would write {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        tomli_w.dump(chunk_data, f)


def write_metadata_file(path: Path, data: dict, dry_run: bool = False) -> None:
    if dry_run:
        logger.info(f"  [dry-run] Would write {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        tomli_w.dump(data, f)


def _find_multi_raw_files(tradition: str, source_id: str) -> list[tuple[int, str, str]]:
    """Find and read multi-page raw files for a source.

    Looks for files matching raw/{tradition}/{source_id}-NN.txt,
    sorted by page number.

    Returns:
        List of (page_number, filename_stem, content) tuples.
    """
    trad_dir = RAW_DIR / tradition
    if not trad_dir.exists():
        return []

    pattern = re.compile(rf'^{re.escape(source_id)}-(\d+)\.txt$')
    pages = []
    for f in sorted(trad_dir.iterdir()):
        m = pattern.match(f.name)
        if m:
            page_num = int(m.group(1))
            content = f.read_text(encoding="utf-8")
            pages.append((page_num, f.stem, content))

    # Sort by page number
    pages.sort(key=lambda x: x[0])
    return pages


def process_source(
    tradition: str,
    source_id: str,
    dry_run: bool = False,
) -> dict | None:
    """Chunk one source. Returns stats dict on success, None on failure."""
    _ensure_chunkers_on_path()
    from tokens import count_tokens
    from regex_splitter import subsplit

    cfg_full = load_chunking_config(tradition, source_id)
    if cfg_full is None:
        logger.warning(f"[{source_id}] no chunking config — skipping")
        return None

    cfg = cfg_full.get("chunking", {})
    meta_cfg = cfg_full.get("metadata", {})
    strategy = cfg.get("strategy", "paragraph-group")
    max_tokens = int(cfg.get("max_tokens", 800))

    strategy_type = STRATEGY_TYPES.get(strategy)
    if not strategy_type:
        logger.error(f"[{source_id}] unknown strategy '{strategy}'")
        return None

    logger.info(f"[{source_id}] Chunking with strategy={strategy} ...")

    # Dispatch to strategy
    if strategy_type == "single":
        raw_path = RAW_DIR / tradition / f"{source_id}.txt"
        if not raw_path.exists():
            logger.warning(f"[{source_id}] raw file not found: {raw_path}")
            return None

        text = raw_path.read_text(encoding="utf-8")

        if strategy in ("regex-section-split", "regex"):
            import regex_splitter
            raw_chunks = regex_splitter.split(text, cfg)
        elif strategy == "heading":
            import heading_splitter
            raw_chunks = heading_splitter.split(text, cfg)
        else:  # paragraph-group, paragraph
            import paragraph_splitter
            raw_chunks = paragraph_splitter.split(text, cfg)

        # Fill token counts and sub-split oversized chunks
        final_chunks = []
        for chunk in raw_chunks:
            chunk.token_count = count_tokens(chunk.body)
            if chunk.token_count > max_tokens:
                subs = subsplit(chunk, max_tokens, count_tokens)
                final_chunks.extend(subs)
            else:
                final_chunks.append(chunk)

    elif strategy_type == "multi":
        pages = _find_multi_raw_files(tradition, source_id)
        if not pages:
            logger.warning(f"[{source_id}] no multi-page raw files found for {tradition}/{source_id}-*.txt")
            return None

        import page_chunker
        final_chunks = page_chunker.split(pages, cfg)

        # Ensure all token counts are filled
        for chunk in final_chunks:
            if chunk.token_count == 0:
                chunk.token_count = count_tokens(chunk.body)

    logger.info(f"[{source_id}] → {len(final_chunks)} chunks")

    # Write chunk files
    chunk_dir = CORPUS_DIR / tradition / source_id / "chunks"
    tradition_val = meta_cfg.get("tradition", tradition)
    text_name = meta_cfg.get("text_name", source_id)
    translator = meta_cfg.get("translator", "")
    sections_format = meta_cfg.get("sections_format", "section")

    # Load provenance from raw .meta.toml if present
    source_url = _find_source_url(tradition, source_id)

    total_tokens = 0
    for idx, chunk in enumerate(final_chunks):
        # chunk_id uses the snake_case directory name (machine-readable, URL-safe).
        # The display name lives in chunk_data["chunk"]["tradition"] below for
        # citation rendering. Older corpora used tradition_val here, which
        # produced "Greek Mystery.foo.001" style IDs that diverged from the
        # on-disk path — see scripts/migrations/v3_004_normalize_chunk_ids.sql.
        chunk_id = f"{tradition}.{source_id}.{idx + 1:03d}"
        chunk_data = {
            "chunk": {
                "id": chunk_id,
                "tradition": tradition_val,
                "text_name": text_name,
                "section": chunk.section_label,
                "translator": translator,
                "source_url": source_url,
                "token_count": chunk.token_count,
            },
            "content": {
                "body": chunk.body,
            },
            "annotations": {
                "concepts": [],
                "related_chunks": [],
            },
        }
        chunk_path = chunk_dir / f"{idx + 1:03d}.toml"
        write_chunk_file(chunk_path, chunk_data, dry_run=dry_run)
        total_tokens += chunk.token_count

    # Write text-level metadata
    metadata = {
        "tradition": tradition_val,
        "text_id": source_id,
        "text_name": text_name,
        "translator": translator,
        "source_url": source_url,
        "sections_format": sections_format,
        "chunk_count": len(final_chunks),
    }
    meta_path = CORPUS_DIR / tradition / source_id / "metadata.toml"
    write_metadata_file(meta_path, metadata, dry_run=dry_run)

    avg_tokens = total_tokens // len(final_chunks) if final_chunks else 0
    return {
        "source_id": source_id,
        "chunk_count": len(final_chunks),
        "total_tokens": total_tokens,
        "avg_tokens": avg_tokens,
    }


def _find_source_url(tradition: str, source_id: str) -> str:
    """Find source URL from raw .meta.toml files."""
    # Try exact match first
    meta_path = RAW_DIR / tradition / f"{source_id}.meta.toml"
    if meta_path.exists():
        with open(meta_path, "rb") as f:
            return tomllib.load(f).get("provenance", {}).get("source_url", "")

    # Try first page for multi-page sources
    meta_path = RAW_DIR / tradition / f"{source_id}-01.meta.toml"
    if meta_path.exists():
        with open(meta_path, "rb") as f:
            return tomllib.load(f).get("provenance", {}).get("source_url", "")

    return ""


def collect_chunking_configs() -> list[tuple[str, str]]:
    """Return (tradition, source_id) pairs for all chunking configs."""
    pairs = []
    if not CHUNKING_DIR.exists():
        return pairs
    for trad_dir in sorted(CHUNKING_DIR.iterdir()):
        if not trad_dir.is_dir():
            continue
        for cfg_file in sorted(trad_dir.glob("*.toml")):
            pairs.append((trad_dir.name, cfg_file.stem))
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser(description="Chunk raw corpus texts")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", metavar="ID")
    parser.add_argument("--tradition", metavar="NAME")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stderr,
    )

    pairs = collect_chunking_configs()
    ok = skipped = 0
    summary: list[dict] = []

    for tradition, source_id in pairs:
        if args.only and source_id != args.only:
            continue
        if args.tradition and tradition != args.tradition:
            continue

        stats = process_source(tradition, source_id, dry_run=args.dry_run)
        if stats:
            ok += 1
            summary.append(stats)
        else:
            skipped += 1

    # Print summary
    print()
    if summary:
        for s in summary:
            print(f"  {s['source_id']}: {s['chunk_count']} chunks "
                  f"({s['total_tokens']} tokens total, avg {s['avg_tokens']}/chunk)")
    print(f"\nDone: {ok} chunked, {skipped} skipped/failed")


if __name__ == "__main__":
    main()
