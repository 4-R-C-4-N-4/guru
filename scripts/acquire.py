"""
Guru Corpus Acquisition Orchestrator

Reads sources/manifest.toml, dispatches each source to the appropriate
downloader, and writes output to raw/{tradition}/{id}.txt + .meta.toml.

Idempotent: skips files whose on-disk content hash already matches.

Usage:
    python3 scripts/acquire.py [--dry-run] [--only <id>] [--tradition <name>]
"""

import argparse
import hashlib
import importlib
import logging
import sys
from pathlib import Path
from typing import Any

import tomllib
import tomli_w

logger = logging.getLogger(__name__)

# Project root is one level up from scripts/
PROJECT_ROOT = Path(__file__).parent.parent
MANIFEST_PATH = PROJECT_ROOT / "sources" / "manifest.toml"
RAW_DIR = PROJECT_ROOT / "raw"
DOWNLOADERS_DIR = Path(__file__).parent / "downloaders"

# Format → downloader module name (in scripts/downloaders/)
FORMAT_DISPATCH: dict[str, str] = {
    "html": "generic_html",
    "html_multi": "sacred_texts",
    "sefaria_api": "sefaria",
    "access_to_insight": "access_to_insight",
}


def load_manifest(path: Path) -> list[dict[str, Any]]:
    """Load and return the list of sources from manifest.toml."""
    with open(path, "rb") as f:
        data = tomllib.load(f)
    sources = data.get("source", [])
    logger.info(f"Loaded {len(sources)} sources from {path}")
    return sources


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_downloader(format_name: str):
    """
    Dynamically import the downloader module for a given format.

    Returns the module (must have a `download(source)` function).
    Raises KeyError if format is unknown, ImportError if module missing.
    """
    module_name = FORMAT_DISPATCH.get(format_name)
    if not module_name:
        raise KeyError(
            f"Unknown format '{format_name}'. "
            f"Known formats: {list(FORMAT_DISPATCH.keys())}"
        )

    # Add downloaders dir to path for relative import
    downloaders_str = str(DOWNLOADERS_DIR)
    if downloaders_str not in sys.path:
        sys.path.insert(0, downloaders_str)

    return importlib.import_module(module_name)


def should_skip(txt_path: Path, meta_path: Path, expected_hash: str | None) -> bool:
    """
    Return True if the file already exists and content hash matches.

    If expected_hash is None, skips whenever both files exist.
    """
    if not txt_path.exists() or not meta_path.exists():
        return False

    if expected_hash is None:
        logger.debug(f"  Skipping {txt_path.name} (exists, no hash to check)")
        return True

    # Read existing file and compare hashes
    existing_text = txt_path.read_text(encoding="utf-8")
    if content_hash(existing_text) == expected_hash:
        logger.debug(f"  Skipping {txt_path.name} (hash matches)")
        return True

    return False


def write_outputs(
    source_id: str,
    tradition: str,
    text: str,
    metadata: dict[str, Any],
    dry_run: bool = False,
) -> tuple[Path, Path]:
    """
    Write text and metadata to raw/{tradition}/{source_id}.txt and .meta.toml.

    Returns (txt_path, meta_path).
    """
    out_dir = RAW_DIR / tradition
    txt_path = out_dir / f"{source_id}.txt"
    meta_path = out_dir / f"{source_id}.meta.toml"

    if dry_run:
        logger.info(f"  [dry-run] Would write {txt_path} ({len(text)} chars)")
        return txt_path, meta_path

    out_dir.mkdir(parents=True, exist_ok=True)
    txt_path.write_text(text, encoding="utf-8")

    # Write metadata as TOML
    with open(meta_path, "wb") as f:
        tomli_w.dump(metadata, f)

    logger.info(f"  Wrote {txt_path} ({len(text)} chars)")
    return txt_path, meta_path


def process_source(source: dict[str, Any], dry_run: bool = False) -> bool:
    """
    Process a single source: download and write output.

    Returns True on success, False on error.
    """
    source_id = source["id"]
    tradition = source["tradition"]
    fmt = source["format"]

    logger.info(f"[{source_id}] Processing (format={fmt}, tradition={tradition})")

    # Load downloader
    try:
        downloader = load_downloader(fmt)
    except KeyError as e:
        logger.error(f"[{source_id}] {e}")
        return False
    except ImportError as e:
        logger.error(f"[{source_id}] Failed to import downloader for '{fmt}': {e}")
        return False

    # Check idempotency before downloading
    # For multi-return downloaders we can't pre-check, so we check per-item after download
    out_dir = RAW_DIR / tradition
    txt_path = out_dir / f"{source_id}.txt"
    meta_path = out_dir / f"{source_id}.meta.toml"
    if txt_path.exists() and meta_path.exists() and fmt != "html_multi":
        existing = txt_path.read_text(encoding="utf-8")
        logger.info(f"[{source_id}] Already exists ({len(existing)} chars) — skipping")
        return True

    try:
        result = downloader.download(source)
    except Exception as e:
        logger.error(f"[{source_id}] Download failed: {e}")
        return False

    # Normalise result to list of (id, text, metadata) triples
    items: list[tuple[str, str, dict]] = []

    if isinstance(result, list):
        # Multi-result downloader (sacred_texts.py) returns list of (text, meta) tuples
        for i, item in enumerate(result):
            text, meta = item
            # Derive per-part id from metadata or use index suffix
            part_id = meta.get("provenance", {}).get("source_id", f"{source_id}-{i+1:02d}")
            items.append((part_id, text, meta))
    else:
        text, meta = result
        items.append((source_id, text, meta))

    success = True
    for item_id, text, meta in items:
        item_tradition = meta.get("tradition", tradition)
        item_out_dir = RAW_DIR / item_tradition
        item_txt = item_out_dir / f"{item_id}.txt"
        item_meta = item_out_dir / f"{item_id}.meta.toml"

        if item_txt.exists() and item_meta.exists():
            existing = item_txt.read_text(encoding="utf-8")
            if content_hash(existing) == content_hash(text):
                logger.info(f"  [{item_id}] Unchanged — skipping")
                continue

        try:
            write_outputs(item_id, item_tradition, text, meta, dry_run=dry_run)
        except Exception as e:
            logger.error(f"  [{item_id}] Write failed: {e}")
            success = False

    return success


def acquire(
    sources: list[dict[str, Any]],
    only_id: str | None = None,
    only_tradition: str | None = None,
    dry_run: bool = False,
) -> tuple[int, int, int]:
    """
    Run acquisition over all (or filtered) sources.

    Returns (ok, skipped, failed) counts.
    """
    ok = skipped = failed = 0

    for source in sources:
        source_id = source["id"]
        tradition = source["tradition"]

        # Filters
        if only_id and source_id != only_id:
            continue
        if only_tradition and tradition != only_tradition:
            continue

        # Quick skip check (single-result formats only)
        fmt = source["format"]
        if fmt != "html_multi":
            out_dir = RAW_DIR / tradition
            txt_path = out_dir / f"{source_id}.txt"
            meta_path = out_dir / f"{source_id}.meta.toml"
            if txt_path.exists() and meta_path.exists():
                existing = txt_path.read_text(encoding="utf-8")
                logger.info(f"[{source_id}] Already exists — skipping")
                skipped += 1
                continue

        success = process_source(source, dry_run=dry_run)
        if success:
            ok += 1
        else:
            failed += 1

    return ok, skipped, failed


def main() -> None:
    parser = argparse.ArgumentParser(description="Download corpus sources")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be downloaded without writing files",
    )
    parser.add_argument(
        "--only",
        metavar="ID",
        help="Process only the source with this ID",
    )
    parser.add_argument(
        "--tradition",
        metavar="NAME",
        help="Process only sources with this tradition",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stderr,
    )

    sources = load_manifest(MANIFEST_PATH)
    ok, skipped, failed = acquire(
        sources,
        only_id=args.only,
        only_tradition=args.tradition,
        dry_run=args.dry_run,
    )

    print(f"\nDone: {ok} downloaded, {skipped} skipped, {failed} failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
