#!/usr/bin/env python3
"""todo:2957d758 — remap Plotinus curation across the apparatus re-chunk.

Re-chunking plotinus-select-works-index dropped 76 whole-page apparatus chunks
(title/Life/TOC front matter + tractate dividers) and renumbered the rest. The
752 kept chunks have byte-identical bodies to old chunks, so all curation
(tags, edges, embeddings) is preserved by renaming old chunk id -> new chunk id
(matched by exact body) and deleting only the 76 apparatus chunks' rows.

Two-phase rename (TMP-prefix all plotinus refs, remap matched, delete the rest)
so the overlapping old/new id spaces never collide on a PK. Run once, in a
single transaction. Re-run graph_bootstrap afterwards to refresh node metadata.
"""
import sqlite3, subprocess, tomllib, glob, sys
from collections import defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / "data" / "guru.db"
CORPUS = Path(__file__).resolve().parents[2] / "corpus/neoplatonism/plotinus-select-works-index/chunks"
PREFIX = "neoplatonism.plotinus-select-works-index."
TMP = "\x01TMP\x01"
COLS = [("nodes", "id"), ("edges", "source_id"), ("edges", "target_id"),
        ("staged_tags", "chunk_id"), ("tagging_progress", "chunk_id"),
        ("chunk_embeddings", "chunk_id"),
        ("staged_edges", "source_chunk"), ("staged_edges", "target_chunk")]


def body_groups_new():
    g = defaultdict(list)
    for f in sorted(CORPUS.glob("*.toml")):
        d = tomllib.load(open(f, "rb"))
        g[d["content"]["body"].strip()].append(d["chunk"]["id"])
    return g


def body_groups_old():
    ls = subprocess.run(["git", "ls-tree", "-r", "--name-only", "HEAD",
                         "corpus/neoplatonism/plotinus-select-works-index/chunks/"],
                        capture_output=True, text=True, cwd=DB.parents[1]).stdout.split()
    g = defaultdict(list); allids = set()
    for path in ls:
        blob = subprocess.run(["git", "show", f"HEAD:{path}"], capture_output=True,
                              text=True, cwd=DB.parents[1]).stdout
        d = tomllib.loads(blob)
        g[d["content"]["body"].strip()].append(d["chunk"]["id"]); allids.add(d["chunk"]["id"])
    return g, allids


def build_remap():
    new = body_groups_new(); old, allold = body_groups_old()
    remap = {}
    for body, olds in old.items():
        news = sorted(new.get(body, []))
        for i, oid in enumerate(sorted(olds)):
            if i < len(news):
                remap[oid] = news[i]
    deletes = sorted(allold - set(remap))
    return remap, deletes


def main():
    remap, deletes = build_remap()
    print(f"remap pairs: {len(remap)}   apparatus deletes: {len(deletes)}")
    assert len(remap) == 752, len(remap)
    assert len(deletes) == 76, len(deletes)
    assert len(set(remap.values())) == len(remap), "remap not injective"

    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys=OFF")
    con.execute("BEGIN")
    con.execute("CREATE TEMP TABLE _m(old TEXT PRIMARY KEY, new TEXT NOT NULL)")
    con.executemany("INSERT INTO _m VALUES(?,?)", list(remap.items()))

    # Phase A — prefix every plotinus reference (matched + apparatus)
    for t, c in COLS:
        con.execute(f'UPDATE "{t}" SET "{c}"=?||"{c}" WHERE "{c}" LIKE ?', (TMP, PREFIX + "%"))
    # Phase B — matched refs -> new id
    for t, c in COLS:
        con.execute(
            f'UPDATE "{t}" SET "{c}"=(SELECT new FROM _m WHERE ?||old="{t}"."{c}") '
            f'WHERE "{c}" IN (SELECT ?||old FROM _m)', (TMP, TMP))
    # Phase C — delete apparatus rows (still TMP-prefixed)
    deld = {}
    for t, c in COLS:
        cur = con.execute(f'DELETE FROM "{t}" WHERE "{c}" LIKE ?', (TMP + PREFIX + "%",))
        if cur.rowcount:
            deld[f"{t}.{c}"] = cur.rowcount

    # guard: no residual TMP prefix anywhere
    resid = 0
    for t, c in COLS:
        resid += con.execute(f'SELECT COUNT(*) FROM "{t}" WHERE "{c}" LIKE ?', (TMP + "%",)).fetchone()[0]
    if resid:
        con.execute("ROLLBACK"); sys.exit(f"ABORT: {resid} residual TMP refs — rolled back")

    con.execute("COMMIT")
    print("apparatus rows deleted:", deld)
    print("final plotinus nodes:",
          con.execute("SELECT COUNT(*) FROM nodes WHERE id LIKE ?", (PREFIX + "%",)).fetchone()[0])


if __name__ == "__main__":
    main()
