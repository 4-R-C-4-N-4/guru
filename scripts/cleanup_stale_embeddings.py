"""
cleanup_stale_embeddings.py — Delete chunk_embeddings rows whose chunk_id
no longer exists in corpus/**/chunks/*.toml.

After re-chunking a source (e.g. once duplicates were removed at acquire),
the chunk count and per-chunk numbering shifts, so the chunk_embeddings
table accumulates rows pointing at chunk_ids that the current corpus no
longer produces. This script reconciles by listing those rows and, with
--apply, deleting them.

Default invocation is dry-run with a summary. --apply commits the DELETE.

Usage:
    python3 scripts/cleanup_stale_embeddings.py            # dry-run
    python3 scripts/cleanup_stale_embeddings.py --apply    # commit
    python3 scripts/cleanup_stale_embeddings.py --tradition X
    python3 scripts/cleanup_stale_embeddings.py --text Y

Note: this only touches chunk_embeddings. The same stale chunk_ids may
also linger in `nodes` (chunk-type rows), `staged_tags`, `staged_edges`,
`staged_concepts`, `tagging_progress`, and `edges` — those are out of
scope here. If those matter, a broader graph-prune script would be
the right place.
"""

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

import tomllib

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
CORPUS_DIR = PROJECT_ROOT / "corpus"
DEFAULT_DB = PROJECT_ROOT / "data" / "guru.db"


def collect_corpus_chunk_ids(
    tradition_filter: str | None = None,
    text_filter: str | None = None,
) -> set[str]:
    """Walk corpus/{tradition}/{text_id}/chunks/*.toml and return the set
    of chunk_ids defined there (the canonical truth)."""
    ids: set[str] = set()
    if not CORPUS_DIR.exists():
        return ids
    for trad_dir in sorted(CORPUS_DIR.iterdir()):
        if not trad_dir.is_dir() or trad_dir.name.endswith(".toml"):
            continue
        if tradition_filter and trad_dir.name != tradition_filter:
            continue
        for text_dir in sorted(trad_dir.iterdir()):
            if not text_dir.is_dir():
                continue
            if text_filter and text_dir.name != text_filter:
                continue
            chunks_dir = text_dir / "chunks"
            if not chunks_dir.exists():
                continue
            for chunk_file in sorted(chunks_dir.glob("*.toml")):
                with open(chunk_file, "rb") as f:
                    d = tomllib.load(f)
                cid = d.get("chunk", {}).get("id")
                if cid:
                    ids.add(cid)
    return ids


def db_chunk_ids(
    conn: sqlite3.Connection,
    tradition_filter: str | None = None,
    text_filter: str | None = None,
) -> set[str]:
    """Return chunk_ids from chunk_embeddings, optionally narrowed by
    matching on the chunk_id naming convention {tradition}.{text}.NNN.
    Filtering here is a prefix match — the corpus walker is the
    authoritative source of truth, this just lets a partial run not
    accidentally delete other traditions' embeddings."""
    rows = conn.execute("SELECT chunk_id FROM chunk_embeddings").fetchall()
    ids = {r[0] for r in rows}
    if tradition_filter:
        ids = {i for i in ids if i.startswith(f"{tradition_filter}.")}
    if text_filter:
        # text_filter applies AFTER tradition (segment 2 of the dotted id)
        ids = {i for i in ids if i.split(".", 2)[1:2] == [text_filter]}
    return ids


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--apply", action="store_true",
                        help="Commit the DELETE. Default is dry-run.")
    parser.add_argument("--tradition", metavar="NAME",
                        help="Only consider embeddings whose chunk_id starts "
                             "with '{NAME}.'. Useful for targeted cleanup.")
    parser.add_argument("--text", metavar="ID",
                        help="Only consider embeddings whose chunk_id has "
                             "this text_id as its second segment.")
    parser.add_argument("--db", default=str(DEFAULT_DB), type=Path,
                        help=f"path to SQLite DB. Default {DEFAULT_DB}.")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stderr,
    )

    if not args.db.exists():
        logger.error(f"Database not found: {args.db}")
        sys.exit(1)

    corpus_ids = collect_corpus_chunk_ids(args.tradition, args.text)
    logger.info(f"Corpus chunk_ids in scope: {len(corpus_ids)}")

    conn = sqlite3.connect(args.db)
    try:
        embedded_ids = db_chunk_ids(conn, args.tradition, args.text)
        logger.info(f"chunk_embeddings rows in scope: {len(embedded_ids)}")

        stale = embedded_ids - corpus_ids
        print(f"\nStale embeddings (in DB, not in corpus): {len(stale)}")

        if not stale:
            print("Nothing to clean up.")
            return

        # Group stale ids by tradition.text for the summary
        from collections import Counter
        groups: Counter = Counter()
        for cid in stale:
            parts = cid.split(".", 2)
            key = ".".join(parts[:2]) if len(parts) >= 2 else cid
            groups[key] += 1
        print("\nBy source:")
        for key, count in sorted(groups.items()):
            print(f"  {key}: {count}")

        if args.verbose:
            print("\nFull list:")
            for cid in sorted(stale):
                print(f"  {cid}")

        if not args.apply:
            print("\n(no DB writes — re-run with --apply to commit)")
            return

        # Apply: parameterized DELETE in a single transaction
        with conn:
            cur = conn.cursor()
            cur.executemany(
                "DELETE FROM chunk_embeddings WHERE chunk_id = ?",
                [(cid,) for cid in stale],
            )
            deleted = cur.rowcount
        print(f"\nDeleted {deleted} stale row(s) from chunk_embeddings.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
