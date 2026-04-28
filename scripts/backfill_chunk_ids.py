"""
backfill_chunk_ids.py — Rewrite the `chunk.id` field in every corpus
TOML file from display-name form ('Christian Mysticism.foo.001') to
snake_case form ('christian_mysticism.foo.001').

Companion to scripts/migrations/v3_004_normalize_chunk_ids.sql, which
does the same rewrite at the SQLite level. This script handles the
on-disk corpus side; together they bring the corpus and the DB into a
consistent chunk_id space.

Idempotent: a second run is a no-op (no rewrites needed). Deterministic:
the per-tradition prefix map is the single source of truth — same map
the SQL migration uses.

Usage:
    python3 scripts/backfill_chunk_ids.py            # dry-run, prints summary
    python3 scripts/backfill_chunk_ids.py --apply    # writes
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
CORPUS_DIR = PROJECT_ROOT / "corpus"


# Display name → snake_case directory name. Must match the per-tradition
# transforms in scripts/migrations/v3_004_normalize_chunk_ids.sql.
TRADITION_MAP: dict[str, str] = {
    "Neoplatonism":        "neoplatonism",
    "Egyptian":            "egyptian",
    "Taoism":              "taoism",
    "Greek Mystery":       "greek_mystery",
    "Christian Mysticism": "christian_mysticism",
    "Zoroastrianism":      "zoroastrianism",
    "Jewish Mysticism":    "jewish_mysticism",
    "Buddhism":            "buddhism",
    "Mesopotamian":        "mesopotamian",
}


def normalize_chunk_id(chunk_id: str) -> str | None:
    """Return the snake_case form, or None if already correct / not in map."""
    for display, snake in TRADITION_MAP.items():
        prefix = f"{display}."
        if chunk_id.startswith(prefix):
            return snake + chunk_id[len(display):]
    return None


def collect_chunk_files() -> list[Path]:
    if not CORPUS_DIR.exists():
        return []
    return sorted(CORPUS_DIR.glob("*/*/chunks/*.toml"))


def rewrite_one(path: Path) -> tuple[str, str] | None:
    """Read the TOML, swap chunk.id if it's a display-name form, write back.

    Uses textual line-oriented rewrite rather than a TOML round-trip so
    formatting (comments, quote style, key ordering) is preserved.
    Returns (old_id, new_id) if rewritten, None if no change.
    """
    text = path.read_text(encoding="utf-8")
    old: str | None = None
    new: str | None = None
    out_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("id = ") and old is None:
            # Inside [chunk] block — assumes the chunk.id is the FIRST 'id =' line
            # in the file (which it is in every corpus TOML; meta.toml and other
            # nested ids come later or in other files).
            value = stripped[len("id = "):].strip()
            if value.startswith('"') and value.endswith('"'):
                cid = value[1:-1]
                normalized = normalize_chunk_id(cid)
                if normalized is not None:
                    old, new = cid, normalized
                    line = line.replace(f'"{cid}"', f'"{normalized}"', 1)
        out_lines.append(line)
    if old is None:
        return None
    path.write_text("".join(out_lines), encoding="utf-8")
    return old, new


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true",
                   help="actually rewrite (default: dry-run)")
    args = p.parse_args()

    files = collect_chunk_files()
    if not files:
        print(f"No corpus TOML files found under {CORPUS_DIR}", file=sys.stderr)
        return 1

    print(f"Scanning {len(files)} corpus TOML files...")
    by_tradition: dict[str, int] = {}
    sample: tuple[Path, str, str] | None = None
    rewrite_count = 0

    for path in files:
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("id = "):
                value = s[len("id = "):].strip()
                if value.startswith('"') and value.endswith('"'):
                    cid = value[1:-1]
                    normalized = normalize_chunk_id(cid)
                    if normalized is not None:
                        rewrite_count += 1
                        trad = cid.split(".", 1)[0]
                        by_tradition[trad] = by_tradition.get(trad, 0) + 1
                        if sample is None:
                            sample = (path, cid, normalized)
                break  # only check the FIRST id = line per file

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"\n{mode}:")
    print(f"  files scanned:         {len(files):,}")
    print(f"  files needing rewrite: {rewrite_count:,}")
    if by_tradition:
        print(f"  by tradition:")
        for trad, n in sorted(by_tradition.items(), key=lambda x: -x[1]):
            print(f"    {trad:<22} {n:,}")
    if sample:
        path, old, new = sample
        print(f"  sample rewrite:")
        print(f"    {path.relative_to(PROJECT_ROOT)}")
        print(f"      {old}")
        print(f"    → {new}")

    if not args.apply:
        if rewrite_count == 0:
            print("\n(no rewrites needed — all chunk_ids already snake_case)")
        else:
            print(f"\n(dry-run only — re-run with --apply to commit)")
        return 0

    if rewrite_count == 0:
        print("\nno-op")
        return 0

    print(f"\nRewriting {rewrite_count:,} files...")
    written = 0
    for path in files:
        result = rewrite_one(path)
        if result:
            written += 1
    print(f"Done: {written:,} files rewritten.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
