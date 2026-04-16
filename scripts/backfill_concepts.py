"""
backfill_concepts.py — Sync accepted EXPRESSES edges from guru.db to vector metadata.

Runs after each Stage 3 review wave to keep vector store concept metadata
aligned with the live graph. Idempotent: skips vectors already up-to-date.

NOTE: Requires Stage 4 (embed_corpus.py + vector_store.py) to have run.

Usage:
    python3 scripts/backfill_concepts.py [--db PATH] [--dry-run]
"""

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_DB = PROJECT_ROOT / "data" / "guru.db"


def get_vector_store():
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from vector_store import VectorStore
        return VectorStore()
    except ImportError:
        logger.warning("vector_store.py not found — Stage 4 not yet complete.")
        return None


def load_chunk_concepts(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """
    Return {chunk_id: [concept_id, ...]} for all chunks.
    Chunks with no EXPRESSES edges get an empty list.
    """
    # All chunk IDs
    all_chunks = {
        r[0]
        for r in conn.execute("SELECT id FROM nodes WHERE type='chunk'").fetchall()
    }

    # Accepted EXPRESSES edges
    rows = conn.execute(
        """SELECT source_id, target_id FROM edges
           WHERE type='EXPRESSES'""",
    ).fetchall()

    concepts_by_chunk: dict[str, list[str]] = {cid: [] for cid in all_chunks}
    for source_id, target_id in rows:
        concept_id = target_id.removeprefix("concept.")
        concepts_by_chunk.setdefault(source_id, []).append(concept_id)

    return concepts_by_chunk


def run_backfill(db_path: Path, dry_run: bool) -> None:
    vs = get_vector_store()
    if vs is None:
        print("ERROR: Vector store not available. Run scripts/embed_corpus.py first.")
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    chunk_concepts = load_chunk_concepts(conn)
    conn.close()

    updated = skipped = errors = 0

    for chunk_id, concepts in chunk_concepts.items():
        try:
            current = vs.get_metadata(chunk_id).get("concepts", [])
            if sorted(current) == sorted(concepts):
                skipped += 1
                continue

            if dry_run:
                logger.info(f"  [dry-run] would update {chunk_id}: {concepts}")
            else:
                vs.update_metadata(chunk_id, {"concepts": concepts})
                logger.debug(f"  updated {chunk_id}: {concepts}")

            updated += 1

        except Exception as e:
            logger.error(f"  {chunk_id} FAILED: {e}")
            errors += 1

    print(f"\nDone: {updated} updated, {skipped} already up-to-date, {errors} errors")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync concept tags to vector store")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stderr,
    )

    run_backfill(Path(args.db), args.dry_run)


if __name__ == "__main__":
    main()
