"""
review_edges.py — Interactive CLI for reviewing staged cross-tradition edges (Pass C).

Usage:
    python3 scripts/review_edges.py [--edge-type PARALLELS] [--min-confidence 0.7]
        [--tradition-a X] [--tradition-b Y] [--db PATH]

Keys: [a]ccept  [r]eject  [c]lassify  [s]kip  [q]uit
"""

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import tomllib

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from guru.corpus import resolve_chunk_path  # noqa: E402

DEFAULT_DB = PROJECT_ROOT / "data" / "guru.db"
REVIEWER = "human"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_chunk_info(chunk_id: str) -> tuple[str, str]:
    """Returns (body, citation) for a chunk."""
    parts = chunk_id.split(".")
    if len(parts) < 3:
        return "", chunk_id
    raw_trad, tid = parts[0], parts[1]
    f = resolve_chunk_path(chunk_id)
    if f is None:
        return "", chunk_id
    with open(f, "rb") as fp:
        d = tomllib.load(fp)
    citation = d["chunk"].get("section", chunk_id)
    text_name = d["chunk"].get("text_name", tid)
    tradition = d["chunk"].get("tradition", raw_trad)
    return d["content"]["body"], f"{tradition} | {text_name} | {citation}"


def print_edge_row(row: dict, body_a: str, cite_a: str,
                   body_b: str, cite_b: str) -> None:
    w = 34
    print()
    print("=" * 70)
    print(f"EDGE:   {row['edge_type']}  (conf={row['confidence']:.2f})")
    print(f"LLM:    {row['justification']}")
    print("-" * 70)
    lines_a = [body_a[i:i+w] for i in range(0, min(len(body_a), 300), w)]
    lines_b = [body_b[i:i+w] for i in range(0, min(len(body_b), 300), w)]
    max_lines = max(len(lines_a), len(lines_b))
    print(f"{'A: ' + cite_a[:w-3]:<{w}}  {'B: ' + cite_b[:w-3]}")
    for i in range(max_lines):
        la = lines_a[i] if i < len(lines_a) else ""
        lb = lines_b[i] if i < len(lines_b) else ""
        print(f"{la:<{w}}  {lb}")
    print("-" * 70)


def promote_to_live(conn: sqlite3.Connection, row: dict, tier: str) -> None:
    conn.execute(
        """INSERT INTO edges(source_id, target_id, type, tier, justification)
           VALUES(?,?,?,?,?)
           ON CONFLICT(source_id, target_id, type) DO UPDATE SET
             tier=excluded.tier, justification=excluded.justification""",
        (row["source_chunk"], row["target_chunk"],
         row["edge_type"], tier, row["justification"]),
    )


def review_edges(
    db_path: Path,
    edge_type: str | None,
    min_confidence: float,
    tradition_a: str | None,
    tradition_b: str | None,
) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    sql = """
        SELECT se.id, se.source_chunk, se.target_chunk,
               se.edge_type, se.confidence, se.justification
        FROM staged_edges se
        WHERE se.status = 'pending'
          AND se.confidence >= ?
    """
    params: list = [min_confidence]

    if edge_type:
        sql += " AND se.edge_type = ?"
        params.append(edge_type)

    if tradition_a:
        sql += " AND (instr(se.source_chunk, ?) = 1 OR instr(se.target_chunk, ?) = 1)"
        params += [tradition_a + ".", tradition_a + "."]

    if tradition_b:
        sql += " AND (instr(se.source_chunk, ?) = 1 OR instr(se.target_chunk, ?) = 1)"
        params += [tradition_b + ".", tradition_b + "."]

    sql += " ORDER BY se.confidence DESC"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

    if not rows:
        print("No pending edges to review.")
        conn.close()
        return

    print(f"\n{len(rows)} edge proposals to review.")
    print("Keys: [a]ccept(verified)  [p]accept(proposed)  [r]eject  [c]lassify  [s]kip  [q]uit\n")

    accepted = rejected = skipped = 0

    for row in rows:
        body_a, cite_a = load_chunk_info(row["source_chunk"])
        body_b, cite_b = load_chunk_info(row["target_chunk"])
        print_edge_row(row, body_a, cite_a, body_b, cite_b)

        while True:
            try:
                key = input("Action [a/p/r/c/s/q]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nInterrupted.")
                conn.commit()
                conn.close()
                sys.exit(0)

            if key == "q":
                conn.commit()
                conn.close()
                print(f"\nDone: {accepted} accepted, {rejected} rejected, {skipped} skipped")
                return

            elif key in ("a", "p"):
                tier = "verified" if key == "a" else "proposed"
                promote_to_live(conn, row, tier)
                conn.execute(
                    "UPDATE staged_edges SET status='accepted', tier=?, reviewed_by=?, reviewed_at=? WHERE id=?",
                    (tier, REVIEWER, now_iso(), row["id"]),
                )
                conn.commit()
                accepted += 1
                break

            elif key == "r":
                conn.execute(
                    "UPDATE staged_edges SET status='rejected', reviewed_by=?, reviewed_at=? WHERE id=?",
                    (REVIEWER, now_iso(), row["id"]),
                )
                conn.commit()
                rejected += 1
                break

            elif key == "s":
                skipped += 1
                break

            elif key == "c":
                choices = ["PARALLELS", "CONTRASTS", "surface_only", "unrelated"]
                print(f"  Edge types: {', '.join(choices)}")
                new_type = input("  New type: ").strip()
                if new_type in choices:
                    row["edge_type"] = new_type
                    promote_to_live(conn, row, "verified")
                    conn.execute(
                        "UPDATE staged_edges SET status='reclassified', edge_type=?, reviewed_by=?, reviewed_at=? WHERE id=?",
                        (new_type, REVIEWER, now_iso(), row["id"]),
                    )
                    conn.commit()
                    accepted += 1
                    break
            else:
                print("  Unknown key. Use a/p/r/c/s/q.")

    conn.close()
    print(f"\nDone: {accepted} accepted, {rejected} rejected, {skipped} skipped")


def main() -> None:
    parser = argparse.ArgumentParser(description="Review staged cross-tradition edges")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--edge-type", choices=["PARALLELS", "CONTRASTS"])
    parser.add_argument("--min-confidence", type=float, default=0.0)
    parser.add_argument("--tradition-a")
    parser.add_argument("--tradition-b")
    args = parser.parse_args()

    review_edges(
        db_path=Path(args.db),
        edge_type=args.edge_type,
        min_confidence=args.min_confidence,
        tradition_a=args.tradition_a,
        tradition_b=args.tradition_b,
    )


if __name__ == "__main__":
    main()
