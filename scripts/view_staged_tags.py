"""
view_staged_tags.py — Read-only viewer for pending staged concept tags (Pass B).

Lists the staged_tags a curator would review at ingest node 11 and prints the
full context for each — chunk body, concept, primary family, definition, score,
and the tagger's justification. This is a *viewing* helper only: it never writes.

Queuing accept / reject / reassign decisions and applying them is the job of the
guru-review web app's HTTP API (the `guru-review-tags` skill drives it); the
judgement rubric lives in prompts/ingest/tag-review.md. There is no unattended
promotion path, by design — see AGENTS.md "Standing constraints".

Usage:
    python3 scripts/view_staged_tags.py [--tradition X] [--text Y]
        [--concept C] [--min-score N] [--db PATH]
"""

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from guru.corpus import resolve_chunk_path  # noqa: E402

DEFAULT_DB = PROJECT_ROOT / "data" / "guru.db"


def load_chunk_body(db_path: Path, chunk_id: str) -> str:
    """Load chunk body from corpus file given chunk node id."""
    chunk_file = resolve_chunk_path(chunk_id)
    if chunk_file is None:
        return ""
    import tomllib
    with open(chunk_file, "rb") as f:
        d = tomllib.load(f)
    return d["content"]["body"]


def print_tag_row(row: dict, concept_def: str, body: str,
                  family: dict | None = None) -> None:
    print()
    print("=" * 70)
    print(f"CHUNK:   {row['chunk_id']}")
    print(f"SECTION: {row['label']}")
    print("-" * 70)
    print(f"BODY:    {body[:400]}{'...' if len(body) > 400 else ''}")
    print("-" * 70)
    print(f"CONCEPT: {row['concept_id']}")
    if family:
        print(f"FAMILY:  {family['domain']} → {family['family']}")
        if family['definition']:
            print(f"         — {family['definition']}")
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


def get_concept_family(conn: sqlite3.Connection, concept_id: str) -> dict | None:
    """Primary-family context for a concept: {domain, family, definition}, in
    id-style (e.g. 'anthropology' → 'spiritual_completion'). Returns None if the
    concept has no primary family (e.g. a brand-new, unclustered concept)."""
    row = conn.execute(
        """SELECT m.family_id, f.definition, f.parent_id
             FROM concept_family_membership m
             JOIN concept_families f ON f.id = m.family_id
            WHERE m.concept_id = ? AND m.is_primary = 1""",
        (f"concept.{concept_id}",),
    ).fetchone()
    if not row:
        return None
    family_id, family_def, domain_id = row[0], row[1], row[2]
    family_short = family_id.split(".", 1)[1] if "." in family_id else family_id
    return {"domain": domain_id or "?", "family": family_short, "definition": family_def or ""}


def view_tags(
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
               st.score, st.justification, st.is_new_concept, st.new_concept_def,
               st.model, st.prompt_version
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

    print(f"\n{len(rows)} pending tags. This is a read-only view — queue "
          f"decisions via the guru-review web app, not here.\n")

    for row in rows:
        row = dict(row)
        concept_def = get_concept_def(conn, row["concept_id"])
        family = get_concept_family(conn, row["concept_id"])
        body = load_chunk_body(db_path, row["chunk_id"])
        print_tag_row(row, concept_def, body, family)

    conn.close()
    print(f"\n{len(rows)} pending tags shown.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="View staged concept tags (read-only)")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--tradition")
    parser.add_argument("--text")
    parser.add_argument("--concept")
    parser.add_argument("--min-score", type=int, default=1)
    args = parser.parse_args()

    view_tags(
        db_path=Path(args.db),
        tradition=args.tradition,
        text_id=args.text,
        concept_filter=args.concept,
        min_score=args.min_score,
    )


if __name__ == "__main__":
    main()
