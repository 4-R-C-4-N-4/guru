#!/usr/bin/env python3
"""todo:aaaa5258 — freeze staged_edges: settle Pass C's pending rows as history.

Pass C (LLM pair classification via propose_edges.py / review_edges.py) is
retired — docs/ingest/16-derive-parallels.md replaces it with a derived
table; decision record todo:c3f479ff. No new staged_edges proposals are
coming, and node 14 (the reviewer) is retired too, so the rows still sitting
at status='pending' will never be reviewed.

"Terminal historical status", not deletion: a pending row silently dropped
records nothing happened to it. One flipped to 'retired_passc' records that a
decision WAS made — Pass C was retired before this pair was judged — without
inventing a verdict (accept/reject) nobody actually rendered. staged_edges has
no separate note/reason column, so the status value itself is the provenance
record; this migration additionally stamps reviewed_by/reviewed_at so each row
also carries who/when, mirroring the 'model-negative' sentinel convention
(v3_010_model_negative_dedup.sql).

Two parts, bundled behind one --dry-run/--apply switch:

  1. Schema: extend the `status` CHECK to allow 'retired_passc'. SQLite has no
     ALTER TABLE ... ADD CONSTRAINT / DROP CONSTRAINT, so this is the same
     recreate-table pattern as v3_003_edge_review.sql /
     v3_004_normalize_chunk_ids.sql: CREATE staged_edges_v2 with the new
     CHECK, copy every row verbatim, drop the old table, rename v2 into
     place, recreate the four plain indexes and two partial-unique indexes
     lost when the old table was dropped. Column list and every other
     constraint mirror scripts/schema.sql exactly — only the status CHECK
     gains one value.

  2. Data: UPDATE staged_edges SET status='retired_passc' ... WHERE
     status='pending'. accepted / rejected / reclassified rows are untouched.

Idempotent: a re-run against an already-migrated DB finds the CHECK already
carries 'retired_passc' and zero rows pending, and no-ops. A DB whose CHECK
was already extended by a prior partial run (schema step done, data step not)
skips straight to the data step rather than re-running CREATE TABLE.

Does NOT drop staged_edges and does NOT delete a single row — status
transition only, per the ticket's hard constraint. A post-transaction guard
compares total row counts before/after and rolls back on any mismatch.

Usage:
    python3 scripts/migrations/v3_011_staged_edges_retire_pending.py            # dry-run (default)
    python3 scripts/migrations/v3_011_staged_edges_retire_pending.py --apply
    python3 scripts/migrations/v3_011_staged_edges_retire_pending.py --db PATH --apply
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB = PROJECT_ROOT / "data" / "guru.db"

NEW_STATUS = "retired_passc"
REVIEWED_BY = "pass-c-retirement"  # sentinel, mirrors 'model-negative' (v3_010)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _has_new_status(con: sqlite3.Connection) -> bool:
    row = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='staged_edges'"
    ).fetchone()
    return bool(row) and NEW_STATUS in (row[0] or "")


def _rebuild_table(con: sqlite3.Connection) -> None:
    """Recreate staged_edges with the extended status CHECK."""
    con.execute("""
        CREATE TABLE staged_edges_v2 (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            source_chunk    TEXT NOT NULL REFERENCES nodes(id),
            target_chunk    TEXT NOT NULL REFERENCES nodes(id),
            edge_type       TEXT NOT NULL CHECK(edge_type IN ('PARALLELS','CONTRASTS','surface_only','unrelated')),
            confidence      REAL NOT NULL DEFAULT 0.0,
            justification   TEXT,
            status          TEXT NOT NULL DEFAULT 'pending'
                                CHECK(status IN ('pending','accepted','rejected','reclassified','retired_passc')),
            tier            TEXT NOT NULL DEFAULT 'proposed'
                                CHECK(tier IN ('verified','proposed')),
            reviewed_by     TEXT,
            reviewed_at     TEXT,
            model           TEXT,
            prompt_version  TEXT,
            similarity      REAL,
            presentation_order TEXT CHECK(presentation_order IN ('ab','ba'))
        )
    """)
    con.execute("""
        INSERT INTO staged_edges_v2
        SELECT id, source_chunk, target_chunk, edge_type, confidence, justification,
               status, tier, reviewed_by, reviewed_at, model, prompt_version,
               similarity, presentation_order
        FROM staged_edges
    """)
    con.execute("DROP TABLE staged_edges")
    con.execute("ALTER TABLE staged_edges_v2 RENAME TO staged_edges")

    con.execute("CREATE INDEX idx_staged_edges_source ON staged_edges(source_chunk)")
    con.execute("CREATE INDEX idx_staged_edges_target ON staged_edges(target_chunk)")
    con.execute("CREATE INDEX idx_staged_edges_status ON staged_edges(status)")
    con.execute("CREATE INDEX idx_staged_edges_type   ON staged_edges(edge_type)")
    con.execute("""
        CREATE UNIQUE INDEX idx_staged_edges_provenance_unique
            ON staged_edges(source_chunk, target_chunk, model, prompt_version)
            WHERE status = 'pending'
    """)
    con.execute("""
        CREATE UNIQUE INDEX idx_staged_edges_model_negative_unique
            ON staged_edges(source_chunk, target_chunk, model, prompt_version)
            WHERE status = 'rejected' AND reviewed_by = 'model-negative'
    """)


def _counts(con: sqlite3.Connection) -> dict[str, int]:
    return dict(con.execute(
        "SELECT status, COUNT(*) FROM staged_edges GROUP BY status").fetchall())


def run(db_path: Path, apply: bool) -> int:
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys=OFF")

    before = _counts(con)
    pending = before.get("pending", 0)
    schema_done = _has_new_status(con)

    print(f"staged_edges status counts (before): {before}")

    if schema_done and pending == 0:
        print("already migrated: CHECK includes 'retired_passc' and 0 rows "
              "pending — nothing to do")
        con.close()
        return 0

    print(f"plan: {'extend the status CHECK, then ' if not schema_done else ''}"
          f"transition {pending} pending row(s) -> '{NEW_STATUS}'")

    if not apply:
        print("(dry-run — re-run with --apply to write)")
        con.close()
        return 0

    total_before = sum(before.values())
    con.execute("BEGIN")
    if not schema_done:
        _rebuild_table(con)

    now = _now_iso()
    con.execute(
        "UPDATE staged_edges SET status=?, "
        "reviewed_by=COALESCE(reviewed_by, ?), reviewed_at=COALESCE(reviewed_at, ?) "
        "WHERE status='pending'",
        (NEW_STATUS, REVIEWED_BY, now),
    )

    after = _counts(con)
    total_after = sum(after.values())
    if after.get("pending", 0) != 0 or total_after != total_before:
        con.execute("ROLLBACK")
        con.close()
        sys.exit(f"ABORT: rolled back — pending={after.get('pending', 0)} "
                 f"(expected 0), total {total_after} (expected {total_before})")

    con.execute("COMMIT")
    con.close()
    print(f"staged_edges status counts (after):  {after}")
    print(f"committed: {pending} row(s) pending -> {NEW_STATUS}; "
          f"0 rows deleted, table not dropped")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", type=Path, default=DB)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                       help="print the plan, write nothing (default)")
    mode.add_argument("--apply", action="store_true",
                       help="extend the CHECK and transition pending rows")
    args = ap.parse_args()
    return run(args.db, apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
