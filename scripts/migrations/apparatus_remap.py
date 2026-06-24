#!/usr/bin/env python3
"""todo:2957d758 — body-matched chunk-id remap after an apparatus re-chunk.

Generic form of the Plotinus migration: when a re-chunk drops whole-page
apparatus and renumbers the survivors, the kept chunks have byte-identical
bodies to old chunks, so all curation (tags, edges, embeddings) is preserved by
renaming old chunk-id -> new chunk-id (matched by exact body) and deleting only
the dropped chunks' rows — no re-tag / re-propose.

Two-phase rename (TMP-prefix every ref, remap the matched, delete the rest) so
the overlapping old/new id spaces never collide on a PK. Single transaction.
Run scripts/graph_bootstrap.py afterwards to refresh node metadata.

Usage:  apparatus_remap.py <tradition>/<source_id>
        (old bodies are read from git HEAD; new bodies from the working tree)
"""
import sqlite3, subprocess, tomllib, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "guru.db"
TMP = "\x01TMP\x01"
COLS = [("nodes", "id"), ("edges", "source_id"), ("edges", "target_id"),
        ("staged_tags", "chunk_id"), ("tagging_progress", "chunk_id"),
        ("chunk_embeddings", "chunk_id"),
        ("staged_edges", "source_chunk"), ("staged_edges", "target_chunk")]


def _new_bodies(rel):
    g = defaultdict(list)
    for f in sorted((ROOT / "corpus" / rel / "chunks").glob("*.toml")):
        d = tomllib.load(open(f, "rb"))
        g[d["content"]["body"].strip()].append(d["chunk"]["id"])
    return g


def _old_bodies(rel):
    ls = subprocess.run(["git", "ls-tree", "-r", "--name-only", "HEAD",
                         f"corpus/{rel}/chunks/"], capture_output=True, text=True,
                        cwd=ROOT).stdout.split()
    g = defaultdict(list); allids = set()
    for p in ls:
        blob = subprocess.run(["git", "show", f"HEAD:{p}"], capture_output=True,
                              text=True, cwd=ROOT).stdout
        d = tomllib.loads(blob)
        g[d["content"]["body"].strip()].append(d["chunk"]["id"]); allids.add(d["chunk"]["id"])
    return g, allids


def main():
    rel = sys.argv[1].strip("/")
    prefix = rel.replace("/", ".") + "."
    new = _new_bodies(rel); old, allold = _old_bodies(rel)
    n_new = sum(len(v) for v in new.values())

    remap = {}
    for body, olds in old.items():
        news = sorted(new.get(body, []))
        for i, oid in enumerate(sorted(olds)):
            if i < len(news):
                remap[oid] = news[i]
    deletes = sorted(allold - set(remap))
    print(f"{prefix}  remap={len(remap)}  delete={len(deletes)}  "
          f"(old={len(allold)}, new_files={n_new})")
    assert len(remap) == n_new, "every new chunk must map to a distinct old body"
    assert len(set(remap.values())) == len(remap), "remap not injective"

    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys=OFF")
    con.execute("BEGIN")
    con.execute("CREATE TEMP TABLE _m(old TEXT PRIMARY KEY, new TEXT NOT NULL)")
    con.executemany("INSERT INTO _m VALUES(?,?)", list(remap.items()))

    for t, c in COLS:  # Phase A: prefix every ref for this text
        con.execute(f'UPDATE "{t}" SET "{c}"=?||"{c}" WHERE "{c}" LIKE ?', (TMP, prefix + "%"))
    for t, c in COLS:  # Phase B: matched -> new id
        con.execute(
            f'UPDATE "{t}" SET "{c}"=(SELECT new FROM _m WHERE ?||old="{t}"."{c}") '
            f'WHERE "{c}" IN (SELECT ?||old FROM _m)', (TMP, TMP))
    deld = {}                                       # Phase C: delete dropped chunks' rows
    for t, c in COLS:
        cur = con.execute(f'DELETE FROM "{t}" WHERE "{c}" LIKE ?', (TMP + prefix + "%",))
        if cur.rowcount:
            deld[f"{t}.{c}"] = cur.rowcount

    resid = sum(con.execute(f'SELECT COUNT(*) FROM "{t}" WHERE "{c}" LIKE ?', (TMP + "%",)).fetchone()[0]
                for t, c in COLS)
    if resid:
        con.execute("ROLLBACK"); sys.exit(f"ABORT: {resid} residual TMP refs — rolled back")
    con.execute("COMMIT")
    print("rows deleted:", deld)
    print("final nodes:", con.execute("SELECT COUNT(*) FROM nodes WHERE id LIKE ?", (prefix + "%",)).fetchone()[0])


if __name__ == "__main__":
    main()
