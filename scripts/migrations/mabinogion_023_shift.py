#!/usr/bin/env python3
"""todo:1360a074 — shift mabinogion chunk ids after the closing-formula re-chunk.

The Lady of the Fountain ends with "And this is the tale of THE LADY OF
THE FOUNTAIN." — the regex-section-split alternation matched the all-caps
title inside that sentence, splitting a spurious 1-token "." chunk
(celtic.mabinogion.023) and truncating 022 mid-sentence. The chunker fix
(negative lookbehind) restores the sentence into 022 and drops the junk
chunk, so the corpus renumbers 024–192 → 023–191.

This migration mirrors that renumber into the live DB:
  1. delete 023's rows (node, embedding, its inferred BELONGS_TO edge,
     tagging_progress — it had no staged/curated rows, verified at capture)
  2. shift 024..192 down by one, ascending so the freed slot absorbs each
     collision, in: nodes, chunk_embeddings, edges (both sides),
     staged_tags, staged_edges, tagging_progress
  3. remap chunk-id JSON arrays: summary_nodes.child_chunk_ids,
     staged_summaries.child_chunk_ids, work_dossiers.structure_json

children_hash is NOT touched by the shift pass: bodies are final only
after clean_bodies.py --apply --text mabinogion re-runs. Invoke with
--rehash afterwards to recompute summary_nodes.children_hash from the
cleaned corpus (expected: only the span containing 022/023 changes).

Single transaction; guard aborts on any surviving .192 reference or on a
count mismatch. DB backed up beforehand (guru-*-pre-mabinogion-rechunk.db).
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

DB = PROJECT_ROOT / "data" / "guru.db"
PREFIX = "celtic.mabinogion."
DEAD = f"{PREFIX}023"

EXPECT = {  # post-migration counts, from the pre-migration audit
    "nodes": 191,
    "chunk_embeddings": 191,
    "edges_src": 1048,   # 1049 minus 023's BELONGS_TO
    "staged_tags": 782,
    "staged_edges": 592,
    "tagging_progress": 191,
}


def cid(n: int) -> str:
    return f"{PREFIX}{n:03d}"


def remap_id(chunk_id: str) -> str | None:
    """New id for a chunk ref; None if the ref is the dead chunk."""
    if not chunk_id.startswith(PREFIX):
        return chunk_id
    n = int(chunk_id.rsplit(".", 1)[1])
    if n == 23:
        return None
    return cid(n - 1) if n > 23 else chunk_id


def remap_list(ids: list[str]) -> list[str]:
    return [new for c in ids if (new := remap_id(c)) is not None]


def shift(con: sqlite3.Connection) -> None:
    con.execute("BEGIN")

    # 1. the dead chunk
    con.execute("DELETE FROM edges WHERE source_id=? OR target_id=?", (DEAD, DEAD))
    con.execute("DELETE FROM chunk_embeddings WHERE chunk_id=?", (DEAD,))
    con.execute("DELETE FROM tagging_progress WHERE chunk_id=?", (DEAD,))
    con.execute("DELETE FROM staged_tags WHERE chunk_id=?", (DEAD,))
    con.execute("DELETE FROM staged_edges WHERE source_chunk=? OR target_chunk=?", (DEAD, DEAD))
    con.execute("DELETE FROM nodes WHERE id=?", (DEAD,))

    # 2. ascending shift — each iteration moves into the slot the previous freed
    for n in range(24, 193):
        old, new = cid(n), cid(n - 1)
        con.execute("UPDATE nodes SET id=? WHERE id=?", (new, old))
        con.execute("UPDATE chunk_embeddings SET chunk_id=? WHERE chunk_id=?", (new, old))
        con.execute("UPDATE edges SET source_id=? WHERE source_id=?", (new, old))
        con.execute("UPDATE edges SET target_id=? WHERE target_id=?", (new, old))
        con.execute("UPDATE staged_tags SET chunk_id=? WHERE chunk_id=?", (new, old))
        con.execute("UPDATE staged_edges SET source_chunk=? WHERE source_chunk=?", (new, old))
        con.execute("UPDATE staged_edges SET target_chunk=? WHERE target_chunk=?", (new, old))
        con.execute("UPDATE tagging_progress SET chunk_id=? WHERE chunk_id=?", (new, old))

    # 3. JSON chunk-id arrays
    for row in con.execute(
            "SELECT id, child_chunk_ids FROM summary_nodes"
            " WHERE child_chunk_ids LIKE ?", (f"%{PREFIX}%",)).fetchall():
        con.execute("UPDATE summary_nodes SET child_chunk_ids=? WHERE id=?",
                    (json.dumps(remap_list(json.loads(row[1]))), row[0]))
    for row in con.execute(
            "SELECT id, child_chunk_ids FROM staged_summaries"
            " WHERE child_chunk_ids LIKE ?", (f"%{PREFIX}%",)).fetchall():
        con.execute("UPDATE staged_summaries SET child_chunk_ids=? WHERE id=?",
                    (json.dumps(remap_list(json.loads(row[1]))), row[0]))
    for row in con.execute(
            "SELECT work_id, structure_json FROM work_dossiers"
            " WHERE structure_json LIKE ?", (f"%{PREFIX}%",)).fetchall():
        structure = json.loads(row[1])
        for section in structure:
            if section.get("chunk_ids"):
                section["chunk_ids"] = remap_list(section["chunk_ids"])
        con.execute("UPDATE work_dossiers SET structure_json=? WHERE work_id=?",
                    (json.dumps(structure), row[0]))

    # guards
    got = {
        "nodes": con.execute("SELECT COUNT(*) FROM nodes WHERE id LIKE ? AND type='chunk'", (f"{PREFIX}%",)).fetchone()[0],
        "chunk_embeddings": con.execute("SELECT COUNT(*) FROM chunk_embeddings WHERE chunk_id LIKE ?", (f"{PREFIX}%",)).fetchone()[0],
        "edges_src": con.execute("SELECT COUNT(*) FROM edges WHERE source_id LIKE ?", (f"{PREFIX}%",)).fetchone()[0],
        "staged_tags": con.execute("SELECT COUNT(*) FROM staged_tags WHERE chunk_id LIKE ?", (f"{PREFIX}%",)).fetchone()[0],
        "staged_edges": con.execute(
            "SELECT COUNT(*) FROM staged_edges WHERE source_chunk LIKE ? OR target_chunk LIKE ?",
            (f"{PREFIX}%", f"{PREFIX}%")).fetchone()[0],
        "tagging_progress": con.execute("SELECT COUNT(*) FROM tagging_progress WHERE chunk_id LIKE ?", (f"{PREFIX}%",)).fetchone()[0],
    }
    ghost = f"{PREFIX}192"
    residual = sum(con.execute(q, (ghost,)).fetchone()[0] for q in (
        "SELECT COUNT(*) FROM nodes WHERE id=?",
        "SELECT COUNT(*) FROM chunk_embeddings WHERE chunk_id=?",
        "SELECT COUNT(*) FROM edges WHERE source_id=? OR target_id=?".replace("?", "?1"),
        "SELECT COUNT(*) FROM staged_tags WHERE chunk_id=?",
        "SELECT COUNT(*) FROM tagging_progress WHERE chunk_id=?",
    ))
    residual += con.execute(
        "SELECT COUNT(*) FROM summary_nodes WHERE child_chunk_ids LIKE ?",
        (f"%{ghost}%",)).fetchone()[0]
    if got != EXPECT or residual:
        con.execute("ROLLBACK")
        sys.exit(f"ABORT: rolled back — counts {got} (expected {EXPECT}), {residual} residual .192 refs")
    con.execute("COMMIT")
    print("shift committed:", got)


def rehash(con: sqlite3.Connection) -> None:
    """Recompute children_hash from the (cleaned) corpus TOMLs."""
    from promote_dossiers import children_hash

    changed = []
    con.execute("BEGIN")
    for sid, ids_json, old_hash in con.execute(
            "SELECT id, child_chunk_ids, children_hash FROM summary_nodes"
            " WHERE child_chunk_ids LIKE ?", (f"%{PREFIX}%",)).fetchall():
        new_hash = children_hash(json.loads(ids_json))
        if new_hash != old_hash:
            con.execute("UPDATE summary_nodes SET children_hash=? WHERE id=?", (new_hash, sid))
            changed.append(sid)
    con.execute("COMMIT")
    print(f"rehash: {len(changed)} of touched summaries changed:")
    for sid in changed:
        print(f"  {sid}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rehash", action="store_true",
                    help="recompute mabinogion children_hash (run AFTER clean_bodies)")
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys=OFF")
    if args.rehash:
        rehash(con)
    else:
        if con.execute("SELECT COUNT(*) FROM nodes WHERE id=?", (DEAD,)).fetchone()[0] == 0 \
                and con.execute("SELECT COUNT(*) FROM nodes WHERE id=?", (f"{PREFIX}192",)).fetchone()[0] == 0:
            sys.exit("already migrated: 023 gone and no .192 node — nothing to do")
        shift(con)
    con.close()


if __name__ == "__main__":
    main()
