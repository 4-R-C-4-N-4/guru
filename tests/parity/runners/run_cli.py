"""Apply the decision_sequence.json fixture to a shadow DB via the CLI's
exact code paths (review_tags.promote_to_expresses for accepts; the
inline UPDATE/INSERT statements from review_tags.py:163-189 for reject
and reassign).

Reads:  fixture path, shadow DB path
Writes: shadow DB rows (staged_tags, edges, nodes)
Output: nothing on success; nonzero exit + stderr on error
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from review_tags import promote_to_expresses, reject_tag, reassign_tag  # noqa: E402
from review_edges import accept_edge, reject_edge, reclassify_edge  # noqa: E402

REVIEWER = "parity-harness"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def apply_tag_action(conn: sqlite3.Connection, action: dict) -> None:
    sid = action["target_id"]
    kind = action["action"]
    # Use sqlite3.Row for kw-style access, mirroring review_tags.py's
    # in-loop row dict so the helpers receive the same shape they expect.
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM staged_tags WHERE id=?", (sid,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"seed missing staged_tag id={sid}")

    if kind == "accept":
        promote_to_expresses(
            conn, row["chunk_id"], row["concept_id"], row["justification"] or "",
            new_concept_def=row["new_concept_def"],
        )
        conn.execute(
            "UPDATE staged_tags SET status='accepted', reviewed_by=?, reviewed_at=? WHERE id=?",
            (REVIEWER, now_iso(), sid),
        )
    elif kind == "reject":
        reject_tag(conn, row)
    elif kind == "skip":
        # No-op, by design.
        pass
    elif kind == "reassign":
        reassign_tag(conn, row, action["reassign_to"])
    else:
        raise RuntimeError(f"unknown tag action: {kind}")


def apply_edge_action(conn: sqlite3.Connection, action: dict) -> None:
    sid = action["target_id"]
    kind = action["action"]
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM staged_edges WHERE id=?", (sid,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"seed missing staged_edge id={sid}")

    if kind == "accept":
        accept_edge(conn, row)
    elif kind == "reject":
        reject_edge(conn, row)
    elif kind == "skip":
        pass
    elif kind == "reclassify":
        reclassify_edge(conn, row, action["reclassify_to"])
    else:
        raise RuntimeError(f"unknown edge action: {kind}")


def apply_action(conn: sqlite3.Connection, action: dict) -> None:
    target_table = action.get("target_table", "staged_tags")
    if target_table == "staged_tags":
        apply_tag_action(conn, action)
    elif target_table == "staged_edges":
        apply_edge_action(conn, action)
    else:
        raise RuntimeError(f"unknown target_table: {target_table}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="shadow DB path")
    ap.add_argument("--fixture", required=True, help="decision_sequence.json path")
    args = ap.parse_args()

    fixture = json.loads(Path(args.fixture).read_text())
    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        for action in fixture["actions"]:
            apply_action(conn, action)
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
