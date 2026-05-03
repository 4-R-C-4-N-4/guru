"""
Guru Chunking Config Scaffolder

Reads sources/manifest.toml, inspects raw/{tradition}/, and writes a
scaffolded chunking/{tradition}/{id}.toml that pre-fills:
  - [metadata] from manifest (tradition, text_name, translator)
  - [chunking].strategy from raw layout
      (multi-file → page-as-chunk, single-file → paragraph-group)
  - [chunking].pre_strip_patterns and friends from a small extractor
    profile keyed on raw/{tradition}/{id}*.meta.toml's `extractor` field
    plus the manifest URL (Project Gutenberg detection)

Never clobbers existing configs unless --force.

Usage:
    python3 scripts/chunk_init.py [--only <id>] [--tradition <name>]
                                  [--force] [--dry-run] [-v]
"""

import argparse
import logging
import re
import sys
from pathlib import Path
from typing import Any

import tomllib
import tomli_w

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
MANIFEST_PATH = PROJECT_ROOT / "sources" / "manifest.toml"
RAW_DIR = PROJECT_ROOT / "raw"
CHUNKING_DIR = PROJECT_ROOT / "chunking"

SCAFFOLD_HEADER = (
    "# Generated scaffold from scripts/chunk_init.py — review the strategy,\n"
    "# regex patterns, and any extractor-specific defaults before chunking.\n"
)

SACRED_TEXTS_PRE_STRIP = [
    r"^Sacred Texts.*?at sacred-texts\.com",
    r"Previous Next[^\n]*",
    r"Next:[^\n]*$",
    r"Click to enlarge[^\n]*",
]

GUTENBERG_PRE_STRIP = [
    # Front matter through the START marker. Non-greedy `.*?` between START
    # and the closing `***` is required: when the raw file is a single line
    # (generic_html extraction collapses HTML to one line), `[^\n]*` is
    # unbounded and the trailing `***` backtracks all the way to the END
    # marker, eating the entire book body.
    r"^.*?\*\*\* START OF .*?\*\*\*",
    # END marker through the rest of the file (license boilerplate).
    r"\*\*\* END OF .*",
]


def detect_layout(tradition: str, source_id: str) -> str | None:
    """Return 'single' if {id}.txt exists, 'multi' if {id}-NN.txt exists,
    None if neither (acquire hasn't run for this source)."""
    trad_dir = RAW_DIR / tradition
    if not trad_dir.exists():
        return None
    if (trad_dir / f"{source_id}.txt").exists():
        return "single"
    pattern = re.compile(rf"^{re.escape(source_id)}-\d+\.txt$")
    for f in trad_dir.iterdir():
        if pattern.match(f.name):
            return "multi"
    return None


def detect_extractor(tradition: str, source_id: str) -> str | None:
    """Read provenance.extractor from the matching .meta.toml, if present."""
    trad_dir = RAW_DIR / tradition
    candidates = [
        trad_dir / f"{source_id}.meta.toml",
        trad_dir / f"{source_id}-01.meta.toml",
    ]
    for path in candidates:
        if path.exists():
            with open(path, "rb") as f:
                data = tomllib.load(f)
            return data.get("provenance", {}).get("extractor")
    return None


def build_config(source: dict, layout: str, extractor: str | None) -> dict:
    """Assemble the full TOML structure (chunking + metadata) for a source."""
    tradition = source["tradition"]
    text_name = source.get("label", source["id"])
    translator = source.get("translator", "")
    url = source.get("url", "")

    chunking: dict[str, Any] = {}
    if layout == "multi":
        chunking["strategy"] = "page-as-chunk"
        chunking["section_label_format"] = "Chapter {n}: {title}"
        chunking["section_label_format_no_number_match"] = "Page {n}"
        chunking["title_source"] = "content"
        chunking["title_pattern"] = r"^([A-Z][A-Z' .,\-]{4,80})"
        chunking["max_tokens"] = 800
    else:  # single
        chunking["strategy"] = "paragraph-group"
        chunking["section_label_format"] = "Section {n}"
        chunking["max_tokens"] = 800
        chunking["group_size"] = 2

    pre_strip: list[str] = []
    if extractor == "sacred_texts":
        pre_strip.extend(SACRED_TEXTS_PRE_STRIP)
    if "gutenberg.org" in url:
        pre_strip.extend(GUTENBERG_PRE_STRIP)
    if pre_strip:
        chunking["pre_strip_patterns"] = pre_strip

    metadata = {
        "tradition": tradition,
        "text_name": text_name,
        "translator": translator,
        "sections_format": "chapter" if layout == "multi" else "section",
    }

    return {"chunking": chunking, "metadata": metadata}


def write_config(path: Path, data: dict, dry_run: bool, force: bool) -> str:
    """Return one of: 'wrote', 'skipped', 'dry-run'."""
    if path.exists() and not force:
        return "skipped"
    if dry_run:
        return "dry-run"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = tomli_w.dumps(data)
    path.write_text(SCAFFOLD_HEADER + body, encoding="utf-8")
    return "wrote"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scaffold chunking configs from manifest + raw layout"
    )
    parser.add_argument("--only", metavar="ID",
                        help="Process only the source with this id")
    parser.add_argument("--tradition", metavar="NAME",
                        help="Process only sources with this tradition")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing chunking config files")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be written without writing")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stderr,
    )

    with open(MANIFEST_PATH, "rb") as f:
        sources = tomllib.load(f).get("source", [])

    wrote = skipped = dry = no_raw = 0
    for source in sources:
        sid = source.get("id")
        tradition = source.get("tradition")
        if not sid or not tradition:
            continue
        if args.only and sid != args.only:
            continue
        if args.tradition and tradition != args.tradition:
            continue

        layout = detect_layout(tradition, sid)
        if layout is None:
            logger.warning(
                f"[{sid}] no raw files at raw/{tradition}/ — run acquire first"
            )
            no_raw += 1
            continue

        extractor = detect_extractor(tradition, sid)
        cfg = build_config(source, layout, extractor)

        out_path = CHUNKING_DIR / tradition / f"{sid}.toml"
        result = write_config(out_path, cfg, args.dry_run, args.force)
        rel = out_path.relative_to(PROJECT_ROOT)
        if result == "wrote":
            logger.info(
                f"[{sid}] wrote {rel} (layout={layout}, extractor={extractor})"
            )
            wrote += 1
        elif result == "skipped":
            logger.info(f"[{sid}] skipped {rel} — already exists (use --force)")
            skipped += 1
        else:
            print(f"\n--- {rel} (dry-run, layout={layout}, extractor={extractor}) ---")
            print(SCAFFOLD_HEADER + tomli_w.dumps(cfg))
            dry += 1

    print(
        f"\nDone: {wrote} written, {skipped} skipped (exists), "
        f"{dry} dry-run, {no_raw} missing raw"
    )


if __name__ == "__main__":
    main()
