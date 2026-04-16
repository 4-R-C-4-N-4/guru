"""
Guru Corpus Chunking Orchestrator

Walks raw/{tradition}/{text_id}.txt, applies chunking/{tradition}/{text_id}.toml,
and writes corpus/{tradition}/{text_id}/chunks/{NNN}.toml per chunk, plus
corpus/{tradition}/{text_id}/metadata.toml.

Idempotent: re-runs produce identical output.

Usage:
    python3 scripts/chunk.py [--dry-run] [--only <id>] [--tradition <name>]
"""

import argparse
import importlib
import logging
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

STRATEGY_MODULES = {
    "regex": "regex_splitter",
    "heading": "heading_splitter",
    "paragraph": "paragraph_splitter",
}


def _ensure_chunkers_on_path():
    p = str(CHUNKERS_DIR)
    if p not in sys.path:
        sys.path.insert(0, p)


def load_chunking_config(tradition: str, text_id: str) -> dict | None:
    path = CHUNKING_DIR / tradition / f"{text_id}.toml"
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


def process_text(
    tradition: str,
    text_id: str,
    dry_run: bool = False,
) -> bool:
    """Chunk one raw text. Returns True on success."""
    _ensure_chunkers_on_path()
    from tokens import count_tokens

    raw_path = RAW_DIR / tradition / f"{text_id}.txt"
    if not raw_path.exists():
        logger.warning(f"[{text_id}] raw file not found: {raw_path}")
        return False

    cfg_full = load_chunking_config(tradition, text_id)
    if cfg_full is None:
        logger.warning(f"[{text_id}] no chunking config at chunking/{tradition}/{text_id}.toml — skipping")
        return False

    cfg = cfg_full.get("chunking", {})
    meta_cfg = cfg_full.get("metadata", {})
    strategy = cfg.get("strategy", "paragraph")
    max_tokens = int(cfg.get("max_tokens", 800))

    module_name = STRATEGY_MODULES.get(strategy)
    if not module_name:
        logger.error(f"[{text_id}] unknown strategy '{strategy}'")
        return False

    splitter = importlib.import_module(module_name)

    text = raw_path.read_text(encoding="utf-8")
    logger.info(f"[{text_id}] Chunking with strategy={strategy} ...")

    raw_chunks = splitter.split(text, cfg)

    # Fill token counts and sub-split oversized chunks
    from regex_splitter import subsplit

    final_chunks = []
    for chunk in raw_chunks:
        chunk.token_count = count_tokens(chunk.body)
        if chunk.token_count > max_tokens:
            subs = subsplit(chunk, max_tokens, count_tokens)
            final_chunks.extend(subs)
        else:
            final_chunks.append(chunk)

    logger.info(f"[{text_id}] → {len(final_chunks)} chunks")

    # Write chunk files
    chunk_dir = CORPUS_DIR / tradition / text_id / "chunks"
    tradition_val = meta_cfg.get("tradition", tradition)
    text_name = meta_cfg.get("text_name", text_id)
    translator = meta_cfg.get("translator", "")
    sections_format = meta_cfg.get("sections_format", "section")

    # Load provenance from raw .meta.toml if present
    meta_toml_path = RAW_DIR / tradition / f"{text_id}.meta.toml"
    source_url = ""
    if meta_toml_path.exists():
        with open(meta_toml_path, "rb") as f:
            raw_meta = tomllib.load(f)
        source_url = raw_meta.get("provenance", {}).get("source_url", "")

    for idx, chunk in enumerate(final_chunks):
        chunk_id = f"{tradition_val}.{text_id}.{idx + 1:03d}"
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

    # Write text-level metadata
    metadata = {
        "tradition": tradition_val,
        "text_id": text_id,
        "text_name": text_name,
        "translator": translator,
        "source_url": source_url,
        "sections_format": sections_format,
        "chunk_count": len(final_chunks),
    }
    meta_path = CORPUS_DIR / tradition / text_id / "metadata.toml"
    write_metadata_file(meta_path, metadata, dry_run=dry_run)

    return True


def collect_raw_texts() -> list[tuple[str, str]]:
    """Return (tradition, text_id) pairs for all raw/*.txt files."""
    pairs = []
    if not RAW_DIR.exists():
        return pairs
    for trad_dir in sorted(RAW_DIR.iterdir()):
        if not trad_dir.is_dir():
            continue
        for txt_file in sorted(trad_dir.glob("*.txt")):
            pairs.append((trad_dir.name, txt_file.stem))
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

    pairs = collect_raw_texts()
    ok = skipped = failed = 0

    for tradition, text_id in pairs:
        if args.only and text_id != args.only:
            continue
        if args.tradition and tradition != args.tradition:
            continue

        success = process_text(tradition, text_id, dry_run=args.dry_run)
        if success:
            ok += 1
        else:
            skipped += 1

    print(f"\nDone: {ok} chunked, {skipped} skipped/failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
