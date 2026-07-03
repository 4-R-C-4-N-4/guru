#!/usr/bin/env python3
"""todo:50438e23 — remap CH-11.006 curation onto CH-11.005 after the apparatus re-chunk.

Stripping the Mead/Greer apparatus shrank Corpus Hermeticum XI ("Mind Unto
Hermes") enough that it re-chunked 6 -> 5 sub-chunks: the old chunk
hermeticism.corpus-hermeticum-11.006 disappeared, its text folding into the new
.005. That orphaned 006's curation (12 EXPRESSES tags incl. 7 verified, a
verified PARALLELS to gnosticism.gospel-of-thomas.005, 13 staged_tags, 1
staged_edge). Since .005 now contains .006's text, we re-point those references
006 -> 005 (the apparatus_remap body-match pattern), deduping against rows .005
already holds, then drop the dead 006 node.

UPDATE OR IGNORE re-points the non-conflicting rows and skips any that would
violate a UNIQUE index (edges: source_id,target_id,type; staged_*: provenance);
the trailing DELETE clears the skipped duplicates. Single transaction; user
chose this (remap) over delete / re-tag / leave. DB backed up beforehand.
"""
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / "data" / "guru.db"
OLD = "hermeticism.corpus-hermeticum-11.006"
NEW = "hermeticism.corpus-hermeticum-11.005"


def main():
    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys=OFF")
    before = {
        "edges": con.execute("SELECT COUNT(*) FROM edges WHERE source_id=? OR target_id=?", (OLD, OLD)).fetchone()[0],
        "staged_tags": con.execute("SELECT COUNT(*) FROM staged_tags WHERE chunk_id=?", (OLD,)).fetchone()[0],
        "staged_edges": con.execute("SELECT COUNT(*) FROM staged_edges WHERE source_chunk=? OR target_chunk=?", (OLD, OLD)).fetchone()[0],
        "nodes": con.execute("SELECT COUNT(*) FROM nodes WHERE id=?", (OLD,)).fetchone()[0],
    }
    con.execute("BEGIN")
    # edges: 006 appears as source (EXPRESSES, BELONGS_TO) and target (PARALLELS).
    con.execute("UPDATE OR IGNORE edges SET source_id=? WHERE source_id=?", (NEW, OLD))
    con.execute("UPDATE OR IGNORE edges SET target_id=? WHERE target_id=?", (NEW, OLD))
    con.execute("DELETE FROM edges WHERE source_id=? OR target_id=?", (OLD, OLD))  # skipped dups + BELONGS_TO
    # staged_tags / staged_edges: re-point chunk refs, dedup on provenance index.
    con.execute("UPDATE OR IGNORE staged_tags SET chunk_id=? WHERE chunk_id=?", (NEW, OLD))
    con.execute("DELETE FROM staged_tags WHERE chunk_id=?", (OLD,))
    con.execute("UPDATE OR IGNORE staged_edges SET source_chunk=? WHERE source_chunk=?", (NEW, OLD))
    con.execute("UPDATE OR IGNORE staged_edges SET target_chunk=? WHERE target_chunk=?", (NEW, OLD))
    con.execute("DELETE FROM staged_edges WHERE source_chunk=? OR target_chunk=?", (OLD, OLD))
    # the dead chunk node
    con.execute("DELETE FROM nodes WHERE id=?", (OLD,))

    # guard: no reference to OLD may survive
    resid = (
        con.execute("SELECT COUNT(*) FROM edges WHERE source_id=? OR target_id=?", (OLD, OLD)).fetchone()[0]
        + con.execute("SELECT COUNT(*) FROM staged_tags WHERE chunk_id=?", (OLD,)).fetchone()[0]
        + con.execute("SELECT COUNT(*) FROM staged_edges WHERE source_chunk=? OR target_chunk=?", (OLD, OLD)).fetchone()[0]
        + con.execute("SELECT COUNT(*) FROM nodes WHERE id=?", (OLD,)).fetchone()[0]
    )
    if resid:
        con.execute("ROLLBACK")
        sys.exit(f"ABORT: {resid} residual references to {OLD} — rolled back")
    con.execute("COMMIT")

    print("before (rows referencing 006):", before)
    print("005 EXPRESSES now:", con.execute("SELECT COUNT(*) FROM edges WHERE source_id=? AND type='EXPRESSES'", (NEW,)).fetchone()[0])
    print("005 PARALLELS to thomas.005:",
          con.execute("SELECT COUNT(*) FROM edges WHERE type='PARALLELS' AND ((source_id='gnosticism.gospel-of-thomas.005' AND target_id=?) OR (target_id='gnosticism.gospel-of-thomas.005' AND source_id=?))", (NEW, NEW)).fetchone()[0])
    print("residual 006 refs:", resid)


if __name__ == "__main__":
    main()
