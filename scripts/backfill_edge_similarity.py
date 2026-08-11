"""
backfill_edge_similarity.py — Recover the retrieval score behind each
staged_edge into staged_edges.similarity.

propose_edges.py never persisted the vector similarity that triggered a
proposal, so --min-similarity was never tunable against outcomes. Every chunk
embedding is still present (nomic-embed-text, 768d, L2-normalised), so the
score is recoverable after the fact: cosine == dot product.

Requires the similarity column from v3_009_edge_provenance.sql.

Guarantees, enforced and verified in-script:
  - fills NULL similarity only; never overwrites a non-NULL value
  - no rows inserted or deleted — row count and scored count are checked
    inside the write transaction, which rolls back if either fails, so a
    failed run leaves the database untouched rather than needing a restore
  - recoverable regardless: the column is derived data, recomputable from
    chunk_embeddings at any time (re-NULL and re-run)

Rows whose source or target has no embedding are left NULL and reported.

This is the guru-side port of rellm's tools/edge_similarity_backfill.py,
which refuses to write to this database by design (see the edge roadmap,
Phase 0.2). The rellm guard stays; this script is the sanctioned write path.

Usage:
    python3 scripts/backfill_edge_similarity.py              # dry-run
    python3 scripts/backfill_edge_similarity.py --apply      # commit
    python3 scripts/backfill_edge_similarity.py --db PATH    # e.g. a copy-test
"""

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_DB = PROJECT_ROOT / "data" / "guru.db"


def load_embeddings(conn: sqlite3.Connection) -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    for cid, dim, blob in conn.execute(
        "SELECT chunk_id, dim, vector FROM chunk_embeddings"
    ):
        v = np.frombuffer(blob, dtype=np.float32)
        if v.shape[0] != dim:
            continue
        n = np.linalg.norm(v)
        out[cid] = v / n if n > 0 else v
    return out


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--apply", action="store_true",
                    help="write similarity values (default: dry-run)")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB,
                    help=f"database path (default: {DEFAULT_DB})")
    args = ap.parse_args()

    if not args.db.exists():
        sys.exit(f"DB not found: {args.db}")

    conn = sqlite3.connect(str(args.db))
    conn.isolation_level = None  # explicit BEGIN/COMMIT below, no implicit txn
    cols = {r[1] for r in conn.execute("PRAGMA table_info(staged_edges)")}
    if "similarity" not in cols:
        sys.exit("staged_edges.similarity missing — run "
                 "scripts/migrations/v3_009_edge_provenance.sql first")

    total_before = conn.execute("SELECT COUNT(*) FROM staged_edges").fetchone()[0]
    already = conn.execute(
        "SELECT COUNT(*) FROM staged_edges WHERE similarity IS NOT NULL"
    ).fetchone()[0]

    emb = load_embeddings(conn)
    print(f"db: {args.db}")
    print(f"staged_edges: {total_before:,}   already scored: {already:,}   "
          f"embeddings: {len(emb):,}")

    updates: list[tuple[float, int]] = []
    missing = 0
    for eid, src, tgt in conn.execute(
        "SELECT id, source_chunk, target_chunk FROM staged_edges "
        "WHERE similarity IS NULL"
    ):
        va, vb = emb.get(src), emb.get(tgt)
        if va is None or vb is None:
            missing += 1
            continue
        updates.append((float(np.dot(va, vb)), eid))

    print(f"to fill: {len(updates):,}   missing embedding (left NULL): {missing:,}")

    if not args.apply:
        print("dry-run — nothing written (use --apply)")
        conn.close()
        return

    # Verify inside the transaction, commit only if the counts hold — a
    # failed check rolls back rather than leaving the operator to restore
    # from backup.
    conn.execute("BEGIN")
    conn.executemany(
        "UPDATE staged_edges SET similarity = ? WHERE id = ? AND similarity IS NULL",
        updates,
    )

    total_after = conn.execute("SELECT COUNT(*) FROM staged_edges").fetchone()[0]
    scored_after = conn.execute(
        "SELECT COUNT(*) FROM staged_edges WHERE similarity IS NOT NULL"
    ).fetchone()[0]
    null_after = total_after - scored_after

    ok_rows = total_after == total_before
    ok_scored = scored_after == already + len(updates)
    print(f"verify: row count {total_before:,} -> {total_after:,} "
          f"({'ok' if ok_rows else 'MISMATCH'})")
    print(f"verify: scored {already:,} -> {scored_after:,}, expected "
          f"{already + len(updates):,} ({'ok' if ok_scored else 'MISMATCH'})")
    print(f"verify: still NULL {null_after:,} (missing-embedding rows)")

    if not (ok_rows and ok_scored):
        conn.rollback()
        conn.close()
        sys.exit("VERIFICATION FAILED — rolled back, nothing written")

    conn.commit()
    conn.close()
    print(f"wrote {len(updates):,} rows")


if __name__ == "__main__":
    main()
