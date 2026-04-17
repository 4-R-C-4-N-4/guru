"""
migrate_to_sqlite_embeddings.py — Phase 1 one-shot migration.

Creates data/guru.db::chunk_embeddings and backfills it from the existing
ChromaDB store at data/vectordb/. After this runs successfully, the two
stores hold equivalent data and Phase 2 can switch embed_corpus.py over
to writing SQLite directly.

Storage format for vectors: float32 little-endian blob (`np.asarray(v,
dtype=np.float32).tobytes()`), with the dim and model name stored per
row so partial re-embeds remain self-describing.

Reconciliation: prints Chroma vector count, SQLite chunk-node count,
and chunk_embeddings count. Exits non-zero if any pair disagrees or if
ChromaDB references chunk_ids not present in the `nodes` table.

Usage: python3 scripts/migrate_to_sqlite_embeddings.py [--db PATH]
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_DB = PROJECT_ROOT / "data" / "guru.db"

logger = logging.getLogger(__name__)


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS chunk_embeddings (
    chunk_id TEXT PRIMARY KEY REFERENCES nodes(id) ON DELETE CASCADE,
    dim      INTEGER NOT NULL,
    model    TEXT NOT NULL,
    vector   BLOB NOT NULL
)
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(CREATE_TABLE_SQL)
    conn.commit()


def load_chroma_vectors() -> tuple[list[tuple[str, list[float]]], str]:
    """Return [(chunk_id, vector), ...] plus the model name from config."""
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    import tomllib
    from vector_store import VectorStore

    with open(PROJECT_ROOT / "config" / "embedding.toml", "rb") as f:
        cfg = tomllib.load(f)
    model_name = cfg.get("model", {}).get("model_name", "unknown")

    vs = VectorStore()
    if vs._backend_type != "chromadb":
        raise SystemExit(
            f"Expected chromadb backend, got {vs._backend_type!r}. "
            "This script is a one-shot Chroma→SQLite migration."
        )
    result = vs._collection.get(include=["embeddings"])
    ids = result["ids"]
    embeddings = result["embeddings"]
    return list(zip(ids, embeddings)), model_name


def backfill(conn: sqlite3.Connection, pairs, model: str) -> int:
    """Insert/replace each (chunk_id, vector) into chunk_embeddings."""
    inserted = 0
    for chunk_id, vec in pairs:
        arr = np.asarray(vec, dtype=np.float32)
        conn.execute(
            "INSERT OR REPLACE INTO chunk_embeddings "
            "(chunk_id, dim, model, vector) VALUES (?, ?, ?, ?)",
            (chunk_id, int(arr.shape[0]), model, arr.tobytes()),
        )
        inserted += 1
    conn.commit()
    return inserted


def reconcile(conn: sqlite3.Connection, chroma_ids: list[str]) -> int:
    """Print reconciliation summary. Returns an exit code (0 = clean)."""
    chroma_count = len(chroma_ids)
    n_chunks = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE type='chunk'"
    ).fetchone()[0]
    n_emb = conn.execute("SELECT COUNT(*) FROM chunk_embeddings").fetchone()[0]

    placeholders = ",".join("?" * len(chroma_ids)) if chroma_ids else "NULL"
    orphan_ids: list[str] = []
    if chroma_ids:
        rows = conn.execute(
            f"SELECT id FROM nodes WHERE type='chunk' AND id IN ({placeholders})",
            chroma_ids,
        ).fetchall()
        known = {r[0] for r in rows}
        orphan_ids = [cid for cid in chroma_ids if cid not in known]

    unembedded = conn.execute(
        "SELECT COUNT(*) FROM nodes n "
        "LEFT JOIN chunk_embeddings e ON e.chunk_id = n.id "
        "WHERE n.type='chunk' AND e.chunk_id IS NULL"
    ).fetchone()[0]

    print("── Reconciliation ──")
    print(f"  ChromaDB vectors              : {chroma_count}")
    print(f"  SQLite nodes(type='chunk')    : {n_chunks}")
    print(f"  SQLite chunk_embeddings rows  : {n_emb}")
    print(f"  Chunks without an embedding   : {unembedded}")
    print(f"  Chroma IDs missing from nodes : {len(orphan_ids)}")

    problems: list[str] = []
    if chroma_count != n_emb:
        problems.append(
            f"Chroma count ({chroma_count}) != chunk_embeddings "
            f"count ({n_emb}) — insert loop dropped rows."
        )
    if orphan_ids:
        problems.append(
            f"{len(orphan_ids)} Chroma vectors reference chunk_ids "
            f"not present in nodes (sample: {orphan_ids[:3]})."
        )
    if unembedded:
        problems.append(
            f"{unembedded} chunk nodes have no embedding. "
            f"Run Phase 3 embed_corpus.py to fix."
        )

    if not problems:
        print("  OK — stores agree.")
        return 0

    print("\n── Problems ──")
    for p in problems:
        print(f"  - {p}")
    # Chroma-vs-SQLite insert drift, or orphan refs, is a hard error;
    # "chunks without an embedding" is expected on partial corpora and
    # is also surfaced as non-zero so the operator sees it explicitly.
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--db", default=str(DEFAULT_DB), type=Path)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stderr,
    )

    if not args.db.exists():
        raise SystemExit(f"Database not found: {args.db}")

    conn = sqlite3.connect(args.db)
    try:
        ensure_schema(conn)
        pairs, model = load_chroma_vectors()
        logger.info(
            "Loaded %d vectors from ChromaDB (model=%s)", len(pairs), model
        )
        inserted = backfill(conn, pairs, model)
        logger.info("Inserted/updated %d rows into chunk_embeddings", inserted)
        sys.exit(reconcile(conn, [cid for cid, _ in pairs]))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
