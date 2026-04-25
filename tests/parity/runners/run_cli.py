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

from review_tags import promote_to_expresses  # noqa: E402

REVIEWER = "parity-harness"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def apply_action(conn: sqlite3.Connection, action: dict) -> None:
    sid = action["staged_tag_id"]
    kind = action["action"]
    row = conn.execute(
        "SELECT chunk_id, concept_id, score, justification, is_new_concept, new_concept_def "
        "FROM staged_tags WHERE id=?",
        (sid,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"seed missing staged_tag id={sid}")
    chunk_id, concept_id, score, justification, _is_new, new_concept_def = row

    if kind == "accept":
        promote_to_expresses(
            conn, chunk_id, concept_id, justification or "", score,
            new_concept_def=new_concept_def,
        )
        conn.execute(
            "UPDATE staged_tags SET status='accepted', reviewed_by=?, reviewed_at=? WHERE id=?",
            (REVIEWER, now_iso(), sid),
        )
    elif kind == "reject":
        conn.execute(
            "UPDATE staged_tags SET status='rejected', reviewed_by=?, reviewed_at=? WHERE id=?",
            (REVIEWER, now_iso(), sid),
        )
    elif kind == "skip":
        # No-op, by design.
        pass
    elif kind == "reassign":
        new_id = action["reassign_to"]
        conn.execute(
            "UPDATE staged_tags SET status='reassigned', concept_id=?, reviewed_by=?, reviewed_at=? WHERE id=?",
            (new_id, REVIEWER, now_iso(), sid),
        )
        conn.execute(
            """INSERT INTO staged_tags(chunk_id, concept_id, score, justification, is_new_concept)
               VALUES(?,?,?,?,0)""",
            (chunk_id, new_id, score, f"Reassigned from {concept_id}"),
        )
    else:
        raise RuntimeError(f"unknown action: {kind}")


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
