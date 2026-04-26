"""
auto_promote.py — Promote high-confidence LLM-tagged staged_tags into
the live `edges` table without per-row human review.

Per docs/autopromote/design.md. Tier rule per row:
  score=3 → tier='proposed'
  score=2 → tier='proposed'
  score=1 → tier='inferred'   (only reached if --score 1 is passed)

The `verified` tier stays behind the human gate (review_tags.py).
This script never writes verified.

Default invocation is dry-run with summary; --apply commits inside a
transaction. is_new_concept=1 rows are excluded (taxonomy decisions
stay manual). Existing live edges are not touched (ON CONFLICT DO
NOTHING; re-run safe).

Usage:
    python3 scripts/auto_promote.py                    # dry-run, --score 3
    python3 scripts/auto_promote.py --score 2          # dry-run, lowers floor
    python3 scripts/auto_promote.py --score 3 --apply  # commit
    python3 scripts/auto_promote.py --model X --apply  # different model

Recommended path: scripts/auto_promote.sh, which adds snapshot +
integrity_check before --apply (mirrors cleanup_dupes.sh).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_DB = PROJECT_ROOT / "data" / "guru.db"
DEFAULT_MODEL = "Qwen3.5-27B-UD-Q4_K_XL.gguf"


# ── core SQL: candidate selection + tier mapping ──────────────────────

def _candidate_sql() -> str:
    """Single SELECT that emits one row per (staged_tag → would-be edge),
    filtered by score floor / model / is_new_concept / not-already-an-edge.
    Used by both the dry-run summary and the --apply INSERT.
    """
    return """
        SELECT
            st.id            AS staged_tag_id,
            st.chunk_id      AS chunk_id,
            st.concept_id    AS concept_id,
            'concept.' || st.concept_id AS concept_node_id,
            st.score         AS score,
            CASE st.score
                WHEN 3 THEN 'proposed'
                WHEN 2 THEN 'proposed'
                WHEN 1 THEN 'inferred'
            END              AS target_tier,
            st.justification AS justification,
            n.tradition_id   AS tradition_id
        FROM staged_tags st
        JOIN nodes n ON n.id = st.chunk_id
        WHERE st.status = 'pending'
          AND st.score >= ?
          AND st.is_new_concept = 0
          AND st.model = ?
          AND NOT EXISTS (
              SELECT 1 FROM edges e
              WHERE e.source_id = st.chunk_id
                AND e.target_id = 'concept.' || st.concept_id
                AND e.type = 'EXPRESSES'
          )
    """


def fetch_candidates(conn: sqlite3.Connection, score_floor: int, model: str) -> list[dict]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(_candidate_sql(), (score_floor, model)).fetchall()
    return [dict(r) for r in rows]


def summarize(candidates: Iterable[dict]) -> dict:
    by_tier: dict[str, int] = defaultdict(int)
    by_tradition: dict[str, int] = defaultdict(int)
    sample: dict | None = None
    total = 0
    for c in candidates:
        total += 1
        by_tier[c["target_tier"]] += 1
        by_tradition[c["tradition_id"]] += 1
        if sample is None:
            sample = c
    return {
        "total": total,
        "by_tier": dict(by_tier),
        "by_tradition": dict(by_tradition),
        "sample": sample,
    }


def print_summary(s: dict, score_floor: int, model: str, apply: bool) -> None:
    mode = "APPLY" if apply else "DRY RUN"
    print(f"auto-promote {mode}")
    print(f"  filter:           score >= {score_floor}, model = {model}, is_new_concept = 0")
    print(f"  would-promote:    {s['total']:,}")
    print(f"  by tier:          " + "  ".join(
        f"{t}={n:,}" for t, n in sorted(s['by_tier'].items())
    ) or "  by tier:          (none)")
    if s["by_tradition"]:
        print(f"  by tradition:     " + "  ".join(
            f"{t}={n}" for t, n in sorted(
                s["by_tradition"].items(), key=lambda x: -x[1]
            )
        ))
    if s["sample"]:
        sm = s["sample"]
        just = sm["justification"] or ""
        if len(just) > 80:
            just = just[:77] + "..."
        print(
            f"  sample row:       {sm['chunk_id']} → {sm['concept_node_id']} "
            f"(score={sm['score']} → {sm['target_tier']})\n"
            f"                    \"[auto] {just}\""
        )
    if not apply:
        print()
        print("(no DB writes — re-run with --apply to commit)")
        print("(verified tier is reserved for human-reviewed edges; this run will not write any.)")


# ── apply path ────────────────────────────────────────────────────────

def apply_promotion(
    conn: sqlite3.Connection, score_floor: int, model: str,
) -> dict:
    """Inside an explicit transaction. Returns counts of inserts."""
    candidates = fetch_candidates(conn, score_floor, model)
    summary = summarize(candidates)

    # Ensure target concept nodes exist (matches review_tags.py
    # promote_to_expresses upsert; defensive even though is_new_concept=0
    # filter means most should already be there).
    ensure_node = """
        INSERT INTO nodes(id, type, label, definition)
        VALUES(?, 'concept', ?, NULL)
        ON CONFLICT(id) DO UPDATE SET
          definition = COALESCE(nodes.definition, excluded.definition)
    """
    insert_edge = """
        INSERT INTO edges(source_id, target_id, type, tier, justification)
        VALUES(?, ?, 'EXPRESSES', ?, ?)
        ON CONFLICT(source_id, target_id, type) DO NOTHING
    """

    inserted = 0
    for c in candidates:
        label = c["concept_id"].replace("_", " ").title()
        conn.execute(ensure_node, (c["concept_node_id"], label))
        cursor = conn.execute(
            insert_edge,
            (
                c["chunk_id"],
                c["concept_node_id"],
                c["target_tier"],
                f"[auto] {c['justification'] or ''}",
            ),
        )
        inserted += cursor.rowcount
    summary["inserted"] = inserted
    return summary


# ── CLI ───────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--score", type=int, default=3, choices=[1, 2, 3],
                   help="score floor — promote rows with score >= this. Default 3.")
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help=f"only promote rows tagged by this model. Default {DEFAULT_MODEL}.")
    p.add_argument("--db", default=str(DEFAULT_DB),
                   help=f"path to SQLite DB. Default {DEFAULT_DB}.")
    p.add_argument("--apply", action="store_true",
                   help="actually write edges (otherwise dry-run summary only).")
    args = p.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"DB not found: {db}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(db))
    try:
        if not args.apply:
            candidates = fetch_candidates(conn, args.score, args.model)
            s = summarize(candidates)
            print_summary(s, args.score, args.model, apply=False)
            return 0

        # --apply path: inside a transaction
        conn.execute("BEGIN")
        try:
            s = apply_promotion(conn, args.score, args.model)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        print_summary(s, args.score, args.model, apply=True)
        print(f"\ninserted: {s['inserted']:,} new EXPRESSES edges")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
