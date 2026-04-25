"""
review_tags.py — Interactive CLI for reviewing staged concept tags (Pass B).

Queries staged_tags, presents each row for accept/reject/reassign,
and promotes accepted tags (score >= 2) to live EXPRESSES edges.

Usage:
    python3 scripts/review_tags.py [--tradition X] [--text Y]
        [--concept C] [--min-score N] [--db PATH]
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from guru.corpus import resolve_chunk_path  # noqa: E402

DEFAULT_DB = PROJECT_ROOT / "data" / "guru.db"
REVIEWER = "human"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_chunk_body(db_path: Path, chunk_id: str) -> str:
    """Load chunk body from corpus file given chunk node id."""
    chunk_file = resolve_chunk_path(chunk_id)
    if chunk_file is None:
        return ""
    import tomllib
    with open(chunk_file, "rb") as f:
        d = tomllib.load(f)
    return d["content"]["body"]


def print_tag_row(row: dict, concept_def: str, body: str) -> None:
    print()
    print("=" * 70)
    print(f"CHUNK:   {row['chunk_id']}")
    print(f"SECTION: {row['label']}")
    print("-" * 70)
    print(f"BODY:    {body[:400]}{'...' if len(body) > 400 else ''}")
    print("-" * 70)
    print(f"CONCEPT: {row['concept_id']}")
    print(f"DEF:     {concept_def or '(new concept)'}")
    print(f"SCORE:   {row['score']}/3")
    print(f"LLM:     {row['justification']}")
    if row["is_new_concept"]:
        print(f"NEW DEF: {row['new_concept_def']}")
    print("-" * 70)


def get_concept_def(conn: sqlite3.Connection, concept_id: str) -> str:
    row = conn.execute(
        "SELECT definition FROM nodes WHERE id=?",
        (f"concept.{concept_id}",),
    ).fetchone()
    return row[0] if row else ""


def promote_to_expresses(conn: sqlite3.Connection,
                         chunk_id: str, concept_id: str,
                         justification: str, score: int) -> None:
    """Insert EXPRESSES edge into live edges table."""
    concept_node_id = f"concept.{concept_id}"
    # Ensure concept node exists (may be a new concept just promoted)
    conn.execute(
        """INSERT OR IGNORE INTO nodes(id, type, label)
           VALUES(?, 'concept', ?)""",
        (concept_node_id, concept_id.replace("_", " ").title()),
    )
    tier = "verified" if score >= 2 else "proposed"
    conn.execute(
        """INSERT INTO edges(source_id, target_id, type, tier, justification)
           VALUES(?, ?, 'EXPRESSES', ?, ?)
           ON CONFLICT(source_id, target_id, type) DO UPDATE SET
             tier=excluded.tier, justification=excluded.justification""",
        (chunk_id, concept_node_id, tier, justification),
    )


def review_tags(
    db_path: Path,
    tradition: str | None,
    text_id: str | None,
    concept_filter: str | None,
    min_score: int,
) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    sql = """
        SELECT st.id, st.chunk_id, n.label, st.concept_id,
               st.score, st.justification, st.is_new_concept, st.new_concept_def
        FROM staged_tags st
        JOIN nodes n ON n.id = st.chunk_id
        WHERE st.status = 'pending'
          AND st.score >= ?
    """
    params: list = [min_score]

    if tradition:
        sql += " AND n.tradition_id = ?"
        params.append(tradition)
    if text_id:
        sql += " AND json_extract(n.metadata_json, '$.text_id') = ?"
        params.append(text_id)
    if concept_filter:
        sql += " AND st.concept_id = ?"
        params.append(concept_filter)

    sql += " ORDER BY n.tradition_id, st.score DESC"
    rows = conn.execute(sql, params).fetchall()

    if not rows:
        print("No pending tags to review.")
        conn.close()
        return

    print(f"\n{len(rows)} tags to review. Keys: [a]ccept  [r]eject  [s]kip  [c]reassign  [q]uit\n")

    accepted = rejected = skipped = 0

    for row in rows:
        row = dict(row)
        concept_def = get_concept_def(conn, row["concept_id"])
        body = load_chunk_body(db_path, row["chunk_id"])
        print_tag_row(row, concept_def, body)

        while True:
            try:
                key = input("Action [a/r/s/c/q]: ").strip().lower()
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

            elif key == "a":
                promote_to_expresses(conn, row["chunk_id"], row["concept_id"],
                                     row["justification"] or "", row["score"])
                conn.execute(
                    "UPDATE staged_tags SET status='accepted', reviewed_by=?, reviewed_at=? WHERE id=?",
                    (REVIEWER, now_iso(), row["id"]),
                )
                conn.commit()
                accepted += 1
                break

            elif key == "r":
                conn.execute(
                    "UPDATE staged_tags SET status='rejected', reviewed_by=?, reviewed_at=? WHERE id=?",
                    (REVIEWER, now_iso(), row["id"]),
                )
                conn.commit()
                rejected += 1
                break

            elif key == "s":
                skipped += 1
                break

            elif key == "c":
                new_id = input("  New concept ID: ").strip()
                if new_id:
                    conn.execute(
                        "UPDATE staged_tags SET status='reassigned', concept_id=?, reviewed_by=?, reviewed_at=? WHERE id=?",
                        (new_id, REVIEWER, now_iso(), row["id"]),
                    )
                    # Create a new pending tag for the reassigned concept
                    conn.execute(
                        """INSERT INTO staged_tags(chunk_id, concept_id, score, justification, is_new_concept)
                           VALUES(?,?,?,?,0)""",
                        (row["chunk_id"], new_id, row["score"], f"Reassigned from {row['concept_id']}"),
                    )
                    conn.commit()
                break
            else:
                print("  Unknown key. Use a/r/s/c/q.")

    conn.close()
    print(f"\nDone: {accepted} accepted, {rejected} rejected, {skipped} skipped")


def main() -> None:
    parser = argparse.ArgumentParser(description="Review staged concept tags")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--tradition")
    parser.add_argument("--text")
    parser.add_argument("--concept")
    parser.add_argument("--min-score", type=int, default=1)
    args = parser.parse_args()

    review_tags(
        db_path=Path(args.db),
        tradition=args.tradition,
        text_id=args.text,
        concept_filter=args.concept,
        min_score=args.min_score,
    )


if __name__ == "__main__":
    main()
