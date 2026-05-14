"""
cleanup_stale_chunk_nodes.py — Delete chunk-type rows in `nodes` (and their
graph fan-out) whose chunk_id no longer exists in corpus/**/chunks/*.toml.

Sibling of cleanup_stale_embeddings.py: that script reconciles
chunk_embeddings against disk; this one reconciles `nodes` (and the tables
that point at chunk-type nodes) against disk. Together they cover the
graph-prune gap left after a re-chunk that produces fewer chunks than
the previous run, since graph_bootstrap.py only upserts and never deletes.

Cascade scope (in delete order, all in one transaction):
  - edges                 (source_id or target_id is a stale chunk_id)
  - staged_tags           (chunk_id)
  - staged_edges          (source_chunk or target_chunk)
  - staged_concepts       (motivating_chunk)
  - tagging_progress      (chunk_id)
  - chunk_embeddings      (chunk_id; FK is ON DELETE CASCADE, but we
                           delete explicitly so behavior is visible
                           regardless of PRAGMA foreign_keys)
  - nodes                 (id; last)

Out of scope: review_actions.target_id is polymorphic (INTEGER id of a
staged_tags/staged_edges row, no FK) — those rows are not cleaned here,
matching the existing pattern of leaving review provenance intact.

Default invocation is dry-run with a summary. --apply commits.

Usage:
    python3 scripts/cleanup_stale_chunk_nodes.py            # dry-run
    python3 scripts/cleanup_stale_chunk_nodes.py --apply    # commit
    python3 scripts/cleanup_stale_chunk_nodes.py --tradition X
    python3 scripts/cleanup_stale_chunk_nodes.py --text Y
"""

import argparse
import logging
import sqlite3
import sys
from collections import Counter
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


def db_chunk_node_ids(
    conn: sqlite3.Connection,
    tradition_filter: str | None = None,
    text_filter: str | None = None,
) -> set[str]:
    """Return chunk_ids from nodes WHERE type='chunk', narrowed by the same
    prefix-match scheme cleanup_stale_embeddings.py uses so partial runs
    don't reach across traditions."""
    rows = conn.execute(
        "SELECT id FROM nodes WHERE type='chunk'"
    ).fetchall()
    ids = {r[0] for r in rows}
    if tradition_filter:
        ids = {i for i in ids if i.startswith(f"{tradition_filter}.")}
    if text_filter:
        # text_filter applies AFTER tradition (segment 2 of the dotted id)
        ids = {i for i in ids if i.split(".", 2)[1:2] == [text_filter]}
    return ids


def fanout_counts(conn: sqlite3.Connection, stale: set[str]) -> dict[str, int]:
    """Count rows in dependent tables that reference any stale chunk_id."""
    if not stale:
        return {}
    placeholders = ",".join("?" * len(stale))
    params = tuple(stale)
    counts = {}
    counts["edges"] = conn.execute(
        f"SELECT COUNT(*) FROM edges "
        f"WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})",
        params + params,
    ).fetchone()[0]
    counts["staged_tags"] = conn.execute(
        f"SELECT COUNT(*) FROM staged_tags WHERE chunk_id IN ({placeholders})",
        params,
    ).fetchone()[0]
    counts["staged_edges"] = conn.execute(
        f"SELECT COUNT(*) FROM staged_edges "
        f"WHERE source_chunk IN ({placeholders}) OR target_chunk IN ({placeholders})",
        params + params,
    ).fetchone()[0]
    counts["staged_concepts"] = conn.execute(
        f"SELECT COUNT(*) FROM staged_concepts "
        f"WHERE motivating_chunk IN ({placeholders})",
        params,
    ).fetchone()[0]
    counts["tagging_progress"] = conn.execute(
        f"SELECT COUNT(*) FROM tagging_progress WHERE chunk_id IN ({placeholders})",
        params,
    ).fetchone()[0]
    counts["chunk_embeddings"] = conn.execute(
        f"SELECT COUNT(*) FROM chunk_embeddings WHERE chunk_id IN ({placeholders})",
        params,
    ).fetchone()[0]
    counts["nodes"] = len(stale)
    return counts


def cascade_delete(conn: sqlite3.Connection, stale: set[str]) -> dict[str, int]:
    """Delete dependents then nodes, in one transaction. Returns rowcount per table."""
    placeholders = ",".join("?" * len(stale))
    params = tuple(stale)
    deleted: dict[str, int] = {}

    # Order matters: dependents before parent so FK checks (if enabled)
    # don't fire on intermediate states.
    plans = [
        ("edges",
         f"DELETE FROM edges WHERE source_id IN ({placeholders}) "
         f"OR target_id IN ({placeholders})",
         params + params),
        ("staged_tags",
         f"DELETE FROM staged_tags WHERE chunk_id IN ({placeholders})",
         params),
        ("staged_edges",
         f"DELETE FROM staged_edges WHERE source_chunk IN ({placeholders}) "
         f"OR target_chunk IN ({placeholders})",
         params + params),
        ("staged_concepts",
         f"DELETE FROM staged_concepts WHERE motivating_chunk IN ({placeholders})",
         params),
        ("tagging_progress",
         f"DELETE FROM tagging_progress WHERE chunk_id IN ({placeholders})",
         params),
        ("chunk_embeddings",
         f"DELETE FROM chunk_embeddings WHERE chunk_id IN ({placeholders})",
         params),
        ("nodes",
         f"DELETE FROM nodes WHERE id IN ({placeholders}) AND type='chunk'",
         params),
    ]

    with conn:
        cur = conn.cursor()
        for table, sql, p in plans:
            cur.execute(sql, p)
            deleted[table] = cur.rowcount
    return deleted


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--apply", action="store_true",
                        help="Commit the cascade DELETE. Default is dry-run.")
    parser.add_argument("--tradition", metavar="NAME",
                        help="Only consider chunk nodes whose id starts "
                             "with '{NAME}.'. Useful for targeted cleanup.")
    parser.add_argument("--text", metavar="ID",
                        help="Only consider chunk nodes whose id has "
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
    # Foreign-key enforcement: cascade order above is correct either way,
    # but enabling FKs surfaces any stale reference we missed instead of
    # silently leaving an orphan.
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        node_ids = db_chunk_node_ids(conn, args.tradition, args.text)
        logger.info(f"chunk nodes in scope: {len(node_ids)}")

        stale = node_ids - corpus_ids
        print(f"\nStale chunk nodes (in DB, not in corpus): {len(stale)}")

        if not stale:
            print("Nothing to clean up.")
            return

        groups: Counter = Counter()
        for cid in stale:
            parts = cid.split(".", 2)
            key = ".".join(parts[:2]) if len(parts) >= 2 else cid
            groups[key] += 1
        print("\nBy source:")
        for key, count in sorted(groups.items()):
            print(f"  {key}: {count}")

        counts = fanout_counts(conn, stale)
        print("\nFan-out (rows that will be deleted with the nodes):")
        for table in ("edges", "staged_tags", "staged_edges",
                      "staged_concepts", "tagging_progress",
                      "chunk_embeddings", "nodes"):
            print(f"  {table}: {counts.get(table, 0)}")

        if args.verbose:
            print("\nFull list:")
            for cid in sorted(stale):
                print(f"  {cid}")

        if not args.apply:
            print("\n(no DB writes — re-run with --apply to commit)")
            return

        deleted = cascade_delete(conn, stale)
        print("\nDeleted:")
        for table in ("edges", "staged_tags", "staged_edges",
                      "staged_concepts", "tagging_progress",
                      "chunk_embeddings", "nodes"):
            print(f"  {table}: {deleted.get(table, 0)}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
