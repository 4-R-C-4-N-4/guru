"""Row-content equivalence check between two shadow DBs (todo:2cd9f9b5).

Per docs/web-review/design.md §10 #1 and impl.md P7b — compares
*content* on enumerated columns, excluding AUTOINCREMENT ids,
timestamp columns, and reviewer attribution.

Exit 0 = parity holds.
Exit 1 = mismatch. Diff printed to stderr.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys


# Columns compared per table (everything else is intentionally excluded).
COMPARE = {
    "staged_tags": (
        "chunk_id, concept_id, status, score, justification, is_new_concept, "
        "new_concept_def, model, prompt_version"
    ),
    "edges": "source_id, target_id, type, tier, justification",
    # nodes: include definition because todo:bdbdccd5 made the CLI populate it
    "nodes": "id, type, tradition_id, label, definition",
}


def fetch(db_path: str, table: str) -> list[tuple]:
    cols = COMPARE[table]
    conn = sqlite3.connect(db_path)
    conn.row_factory = None
    rows = conn.execute(f"SELECT {cols} FROM {table} ORDER BY {cols}").fetchall()
    conn.close()
    return rows


def diff(a_rows: list[tuple], b_rows: list[tuple]) -> tuple[list[tuple], list[tuple]]:
    """Returns (only_in_a, only_in_b)."""
    set_a = set(a_rows)
    set_b = set(b_rows)
    return sorted(set_a - set_b), sorted(set_b - set_a)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cli-db", required=True)
    ap.add_argument("--web-db", required=True)
    args = ap.parse_args()

    failed = False
    for table in COMPARE:
        a = fetch(args.cli_db, table)
        b = fetch(args.web_db, table)
        only_a, only_b = diff(a, b)
        if not only_a and not only_b:
            print(f"  {table}: parity ({len(a)} rows)")
            continue

        failed = True
        print(f"\n  {table}: MISMATCH", file=sys.stderr)
        print(f"    columns: ({COMPARE[table]})", file=sys.stderr)
        if only_a:
            print(f"    {len(only_a)} row(s) only in CLI shadow:", file=sys.stderr)
            for r in only_a:
                print(f"      {r}", file=sys.stderr)
        if only_b:
            print(f"    {len(only_b)} row(s) only in WEB shadow:", file=sys.stderr)
            for r in only_b:
                print(f"      {r}", file=sys.stderr)

    if failed:
        print("\nPARITY HARNESS FAILED", file=sys.stderr)
        return 1
    print("\nPARITY HARNESS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
