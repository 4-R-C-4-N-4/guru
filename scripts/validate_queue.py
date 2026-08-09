#!/usr/bin/env python3
"""Pre-apply validation for the guru-review action queue.

`POST /api/apply` drains every unapplied row in `review_actions` inside a
single `rw.transaction`. One raised error rolls back the whole batch, so a
2,500-action queue is an all-or-nothing bet placed without a way to look at
the cards. `GET /api/apply/preview` counts actions; it does not validate
them.

This replays the queue against the current database without writing, in the
order the server actually uses (`ORDER BY ra.id DESC` — reverse insertion),
and reports what would fail or silently destroy live state.

    python3 scripts/validate_queue.py            # human summary
    python3 scripts/validate_queue.py --json     # machine
    python3 scripts/validate_queue.py -v         # list every finding

Exit 0 clean, 1 if any ERROR, 0 with warnings otherwise.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from guru.paths import DEFAULT_DB  # noqa: E402


def validate(conn: sqlite3.Connection) -> list[dict]:
    """Replay the unapplied queue and return findings, worst first."""
    conn.row_factory = sqlite3.Row

    # The partial unique index only covers status='pending', so that is the
    # only state that can collide.  Key it exactly as the index does.
    pending: dict[tuple, int] = {}
    for r in conn.execute(
        "SELECT id, chunk_id, concept_id, model, prompt_version "
        "FROM staged_tags WHERE status = 'pending'"
    ):
        pending[(r["chunk_id"], r["concept_id"], r["model"], r["prompt_version"])] = r["id"]

    live_edges = {
        (r["source_id"], r["target_id"])
        for r in conn.execute(
            "SELECT source_id, target_id FROM edges WHERE type = 'EXPRESSES'"
        )
    }

    findings: list[dict] = []

    # Mirror the server: ORDER BY ra.id DESC.  Reverse insertion order means a
    # reject queued *earlier* than a reassign is applied *later*, so it cannot
    # clear the way for it.  Replaying in the wrong order would hide exactly
    # the collisions this script exists to find.
    queue = conn.execute(
        """
        SELECT ra.id, ra.action, ra.reassign_to, ra.target_id,
               st.chunk_id, st.concept_id, st.model, st.prompt_version, st.status
          FROM review_actions ra
          LEFT JOIN staged_tags st ON st.id = ra.target_id
         WHERE ra.applied_at IS NULL AND ra.target_table = 'staged_tags'
         ORDER BY ra.id DESC
        """
    ).fetchall()

    for q in queue:
        if q["chunk_id"] is None:
            findings.append({
                "level": "ERROR", "action_id": q["id"], "kind": "orphaned_target",
                "detail": f"action {q['id']} targets staged_tag {q['target_id']}, which does not exist",
            })
            continue

        # The server skips non-pending tags rather than failing on them, so
        # this is informational: the verdict is silently discarded.
        if q["status"] != "pending":
            findings.append({
                "level": "INFO", "action_id": q["id"], "kind": "already_resolved",
                "detail": f"{q['chunk_id']} / {q['concept_id']} is already "
                          f"'{q['status']}'; this verdict will be skipped",
            })
            continue

        key = (q["chunk_id"], q["concept_id"], q["model"], q["prompt_version"])
        edge = (q["chunk_id"], f"concept.{q['concept_id']}")

        if q["action"] == "accept":
            pending.pop(key, None)

        elif q["action"] == "reject":
            pending.pop(key, None)
            if edge in live_edges:
                findings.append({
                    "level": "WARN", "action_id": q["id"], "kind": "reject_deletes_live_edge",
                    "detail": f"reject on {q['chunk_id']} / {q['concept_id']} deletes a "
                              f"live EXPRESSES edge that was already promoted",
                })
                live_edges.discard(edge)

        elif q["action"] == "reassign":
            target = q["reassign_to"]
            if not target:
                findings.append({
                    "level": "ERROR", "action_id": q["id"], "kind": "reassign_missing_target",
                    "detail": f"action {q['id']} is a reassign with no reassign_to; apply raises",
                })
                continue

            # Donor is marked 'reassigned' before the insert, so it leaves the
            # partial index first and cannot collide with its own new row.
            pending.pop(key, None)
            if edge in live_edges:
                findings.append({
                    "level": "WARN", "action_id": q["id"], "kind": "reassign_deletes_live_edge",
                    "detail": f"reassign on {q['chunk_id']} / {q['concept_id']} deletes a "
                              f"live EXPRESSES edge that was already promoted",
                })
                live_edges.discard(edge)

            new_key = (q["chunk_id"], target, q["model"], q["prompt_version"])
            if new_key in pending:
                findings.append({
                    "level": "ERROR", "action_id": q["id"], "kind": "reassign_collision",
                    "detail": f"reassign to '{target}' on {q['chunk_id']} collides with pending "
                              f"staged_tag {pending[new_key]} at the same (model, prompt_version). "
                              f"UNIQUE constraint raises and rolls back the ENTIRE batch",
                })
            else:
                pending[new_key] = -q["id"]  # negative marks a row this replay invented

    order = {"ERROR": 0, "WARN": 1, "INFO": 2}
    findings.sort(key=lambda f: (order[f["level"]], f["action_id"]))
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(DEFAULT_DB), help="path to guru.db")
    ap.add_argument("--json", action="store_true", help="emit findings as JSON")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="list every finding, not just a sample")
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        findings = validate(conn)
    finally:
        conn.close()

    errors = [f for f in findings if f["level"] == "ERROR"]

    if args.json:
        print(json.dumps({
            "ok": not errors,
            "counts": {lvl: sum(1 for f in findings if f["level"] == lvl)
                       for lvl in ("ERROR", "WARN", "INFO")},
            "findings": findings,
        }, indent=2))
        return 1 if errors else 0

    counts = {lvl: sum(1 for f in findings if f["level"] == lvl)
              for lvl in ("ERROR", "WARN", "INFO")}
    print(f"queue validation — {counts['ERROR']} error, "
          f"{counts['WARN']} warn, {counts['INFO']} info")

    for lvl in ("ERROR", "WARN", "INFO"):
        group = [f for f in findings if f["level"] == lvl]
        if not group:
            continue
        shown = group if args.verbose else group[:5]
        print(f"\n{lvl}")
        for f in shown:
            print(f"  [{f['kind']}] {f['detail']}")
        if len(group) > len(shown):
            print(f"  … {len(group) - len(shown)} more (-v to list)")

    if errors:
        print("\nApply would roll back. Fix the errors above first.")
    else:
        print("\nNo errors — the batch would apply as one transaction.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
