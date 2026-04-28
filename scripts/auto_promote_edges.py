"""
auto_promote_edges.py — Promote high-confidence LLM-proposed staged_edges
into the live `edges` table without per-row human review.

Per docs/autopromote/design.md §10. Mirror of auto_promote.py for tags,
but for staged_edges (PARALLELS / CONTRASTS proposals from
scripts/propose_edges.py).

Tier rule: every promoted row lands at tier='proposed'. The 'verified'
tier is reserved for human-reviewed edges (CLI scripts/review_edges.py +
the web edge-review path) — this script never writes verified.

Default invocation is dry-run with summary; --apply commits inside a
transaction. Rows with edge_type IN ('surface_only','unrelated') are
excluded — those values are valid in staged_edges but rejected by the
live `edges.type` CHECK constraint, so promoting them would fail.
Existing live edges are not touched (ON CONFLICT DO NOTHING; re-run safe).

Note on the model filter: unlike auto_promote.py for tags, staged_edges
has no `model` column (propose_edges.py records (source_chunk,
target_chunk, edge_type, confidence, justification) only). If
model-attributed promotion is ever needed, schema-add against
staged_edges first.

Usage:
    python3 scripts/auto_promote_edges.py                       # dry-run, --confidence 0.85
    python3 scripts/auto_promote_edges.py --confidence 0.75     # dry-run, lower floor
    python3 scripts/auto_promote_edges.py --apply               # commit @ 0.85
    python3 scripts/auto_promote_edges.py --confidence 0.9 --apply

Recommended path: scripts/auto_promote_edges.sh, which adds snapshot +
integrity_check before --apply (mirrors auto_promote.sh).
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
DEFAULT_CONFIDENCE = 0.85

PROMOTABLE_EDGE_TYPES = ("PARALLELS", "CONTRASTS")


# ── core SQL: candidate selection ─────────────────────────────────────


def _candidate_sql() -> str:
    """Single SELECT that emits one row per (staged_edge → would-be edge),
    filtered by confidence floor / edge_type / status / not-already-an-edge.
    Used by both the dry-run summary and the --apply INSERT.
    """
    placeholders = ",".join("?" for _ in PROMOTABLE_EDGE_TYPES)
    return f"""
        SELECT
            se.id              AS staged_edge_id,
            se.source_chunk    AS source_chunk,
            se.target_chunk    AS target_chunk,
            se.edge_type       AS edge_type,
            se.confidence      AS confidence,
            se.justification   AS justification,
            ns.tradition_id    AS source_tradition,
            nt.tradition_id    AS target_tradition
        FROM staged_edges se
        JOIN nodes ns ON ns.id = se.source_chunk
        JOIN nodes nt ON nt.id = se.target_chunk
        WHERE se.status = 'pending'
          AND se.confidence >= ?
          AND se.edge_type IN ({placeholders})
          AND NOT EXISTS (
              SELECT 1 FROM edges e
              WHERE e.source_id = se.source_chunk
                AND e.target_id = se.target_chunk
                AND e.type      = se.edge_type
          )
    """


def fetch_candidates(conn: sqlite3.Connection, confidence_floor: float) -> list[dict]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        _candidate_sql(),
        (confidence_floor, *PROMOTABLE_EDGE_TYPES),
    ).fetchall()
    return [dict(r) for r in rows]


def summarize(candidates: Iterable[dict]) -> dict:
    by_type: dict[str, int] = defaultdict(int)
    by_tradition_pair: dict[tuple[str, str], int] = defaultdict(int)
    sample: dict | None = None
    total = 0
    for c in candidates:
        total += 1
        by_type[c["edge_type"]] += 1
        pair = tuple(sorted((c["source_tradition"] or "?", c["target_tradition"] or "?")))
        by_tradition_pair[pair] += 1
        if sample is None:
            sample = c
    return {
        "total": total,
        "by_type": dict(by_type),
        "by_tradition_pair": dict(by_tradition_pair),
        "sample": sample,
    }


def print_summary(s: dict, confidence_floor: float, apply: bool) -> None:
    mode = "APPLY" if apply else "DRY RUN"
    print(f"auto-promote-edges {mode}")
    print(f"  filter:           confidence >= {confidence_floor}, "
          f"edge_type IN {PROMOTABLE_EDGE_TYPES}, status='pending'")
    print(f"  would-promote:    {s['total']:,}")
    if s["by_type"]:
        print("  by edge_type:     " + "  ".join(
            f"{t}={n:,}" for t, n in sorted(s["by_type"].items())
        ))
    if s["by_tradition_pair"]:
        # Top 8 tradition pairs by count
        top = sorted(s["by_tradition_pair"].items(), key=lambda x: -x[1])[:8]
        print("  top trad pairs:   " + "  ".join(
            f"{a}↔{b}={n}" for (a, b), n in top
        ))
    if s["sample"]:
        sm = s["sample"]
        just = sm["justification"] or ""
        if len(just) > 80:
            just = just[:77] + "..."
        print(
            f"  sample row:       {sm['source_chunk']} {sm['edge_type']} "
            f"{sm['target_chunk']} (conf={sm['confidence']:.2f} → proposed)\n"
            f"                    \"[auto] {just}\""
        )
    if not apply:
        print()
        print("(no DB writes — re-run with --apply to commit)")
        print("(verified tier is reserved for human-reviewed edges; this run will not write any.)")


# ── apply path ────────────────────────────────────────────────────────


def apply_promotion(conn: sqlite3.Connection, confidence_floor: float) -> dict:
    """Inside an explicit transaction. Returns counts including 'inserted'."""
    candidates = fetch_candidates(conn, confidence_floor)
    summary = summarize(candidates)

    insert_edge = """
        INSERT INTO edges(source_id, target_id, type, tier, justification)
        VALUES(?, ?, ?, 'proposed', ?)
        ON CONFLICT(source_id, target_id, type) DO NOTHING
    """

    inserted = 0
    for c in candidates:
        cursor = conn.execute(
            insert_edge,
            (
                c["source_chunk"],
                c["target_chunk"],
                c["edge_type"],
                f"[auto] {c['justification'] or ''}",
            ),
        )
        inserted += cursor.rowcount
    summary["inserted"] = inserted
    return summary


# ── CLI ───────────────────────────────────────────────────────────────


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--confidence", type=float, default=DEFAULT_CONFIDENCE,
                   help=f"confidence floor — promote rows with confidence >= this. "
                        f"Default {DEFAULT_CONFIDENCE}.")
    p.add_argument("--db", default=str(DEFAULT_DB),
                   help=f"path to SQLite DB. Default {DEFAULT_DB}.")
    p.add_argument("--apply", action="store_true",
                   help="actually write edges (otherwise dry-run summary only).")
    args = p.parse_args()

    if not (0.0 <= args.confidence <= 1.0):
        print(f"--confidence must be in [0, 1], got {args.confidence}", file=sys.stderr)
        return 1

    db = Path(args.db)
    if not db.exists():
        print(f"DB not found: {db}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(db))
    try:
        if not args.apply:
            candidates = fetch_candidates(conn, args.confidence)
            s = summarize(candidates)
            print_summary(s, args.confidence, apply=False)
            return 0

        conn.execute("BEGIN")
        try:
            s = apply_promotion(conn, args.confidence)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        print_summary(s, args.confidence, apply=True)
        print(f"\ninserted: {s['inserted']:,} new {'/'.join(PROMOTABLE_EDGE_TYPES)} edges")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
