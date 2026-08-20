#!/usr/bin/env python3
"""Corpus-quality intake diagnostic sweep.

Reads from:
  - data/guru.db (nodes, staged_tags, edges, concept_families, etc.)
  - corpus/{tradition}/{text_id}/chunks/NNN.toml (chunk bodies)

Scenarios checked (mirrors the corpus-quality intake catalog):
  1. Apparatus in primary text — chunk bodies that are editorial matter
  2. Duplicate chunk bodies — byte-identical [content].body across chunk ids
  3. Duplicate pending tags — same (chunk, concept) pending from >= 2 model batches
  4. Blind / drifted tags — accepted tags whose concept was added later
  5. Novel-cell contamination — concept with >= 20 accepted tags elsewhere,
     zero prior presence in a tradition, suddenly tagged there
  6. Taxonomy redundancy — concepts near-duplicate enough to merge/split
  7. Dangling curation — tags/edges/embeddings pointing at non-existent chunk ids
  8. Works stuck mid-review — in corpus/ but no applied concept tags (export empty)

Usage:
  python3 scripts/intake_diagnostics.py

Output: human-readable report printed to stdout. NO tickets created.
This is a read-only diagnostic script.

NOTE: This script is a diagnostic harness. It should be re-run periodically
or as part of an intake sweep. If it starts producing useful results consistently,
consider lifting it into a repo doc under docs/ (harness-neutral).
"""

import sqlite3
import tomllib
import os
import json
import re
from pathlib import Path
from collections import defaultdict, Counter
from difflib import SequenceMatcher

DB_PATH = "data/guru.db"
CORPUS_ROOT = Path("corpus")

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
c = conn.cursor()


# ── Helpers ──────────────────────────────────────────────────────────────────

def load_chunk_bodies():
    """Scan corpus/*.toml files for chunk bodies, keyed by chunk_id."""
    bodies = {}
    chunk_files = {}
    for toml_file in CORPUS_ROOT.rglob("chunks/*.toml"):
        try:
            data = tomllib.loads(toml_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        chunk = data.get("chunk", {})
        cid = chunk.get("id")
        if not cid:
            continue
        body = data.get("content", {}).get("body", "")
        bodies[cid] = body
        chunk_files[cid] = str(toml_file)
    return bodies, chunk_files


def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()


# ── 1. Apparatus in primary text ─────────────────────────────────────────────

def check_apparatus(bodies):
    """Flag chunk bodies that look like editorial/apparatus matter."""
    findings = []
    apparatus_patterns = [
        (r"^\s*Translated by", "translator credit"),
        (r"^\s*Translation by", "translator credit"),
        (r"^\s*Translated from", "translator credit"),
        (r"^\s*[\[\(]?(note|preface|introduction)\b", "intro/note heading"),
        (r"^\s*Editor[,\s]'?s?\s+voice", "editor's voice"),
        (r"^\s*Editorial note", "editorial note"),
        (r"^\s*Errata[:\s]", "errata"),
        (r"^\s*Bibliography", "bibliography block"),
        (r"^\s*Footnotes[:\s]", "footnotes block"),
        (r"^\s*Transliteration[:\s]", "transliteration-only fragment"),
        (r"^\s*Greek text[:\s]", "Greek text only"),
        (r"^\s*Text[:\s]+by\b", "text-by attribution"),
        (r"^\s*\(?[A-Z][a-z]+ [A-Z][a-z]+\)\s*$", "bare translator name line"),
    ]

    for cid, body in bodies.items():
        if not body or len(body.strip()) < 10:
            continue
        for pat, label in apparatus_patterns:
            if re.search(pat, body, re.IGNORECASE | re.MULTILINE):
                findings.append({
                    "chunk_id": cid,
                    "apparatus_type": label,
                    "body_preview": body[:200],
                    "body_length": len(body),
                })
                break
    return findings


# ── 2. Duplicate chunk bodies ────────────────────────────────────────────────

def check_duplicate_bodies(bodies):
    """Find byte-identical chunk bodies across different chunk ids."""
    by_body = defaultdict(list)
    for cid, body in bodies.items():
        norm = body.strip()
        if norm:
            by_body[norm].append(cid)

    findings = []
    for body_text, cids in by_body.items():
        if len(cids) > 1:
            findings.append({
                "body_length": len(body_text),
                "chunk_ids": cids,
                "body_preview": body_text[:200],
            })
    return findings


# ── 3. Duplicate pending tags ────────────────────────────────────────────────

def check_duplicate_pending_tags():
    """Same (chunk_id, concept_id) pending from >= 2 different model batches."""
    rows = c.execute("""
        SELECT chunk_id, concept_id, model, COUNT(*) as cnt
        FROM staged_tags
        WHERE status = 'pending'
        GROUP BY chunk_id, concept_id, model
    """).fetchall()

    groups = defaultdict(list)
    for r in rows:
        groups[(r["chunk_id"], r["concept_id"])].append({
            "model": r["model"],
            "count": r["cnt"],
        })

    findings = []
    for (chunk_id, concept_id), batch_info in groups.items():
        if len(batch_info) > 1:
            findings.append({
                "chunk_id": chunk_id,
                "concept_id": concept_id,
                "batches": batch_info,
            })
    return findings


# ── 4. Blind / drifted tags ─────────────────────────────────────────────────

def check_blind_tags():
    """Accepted (verified) tags whose concept was defined AFTER the tag was created."""
    tag_rows = c.execute("""
        SELECT st.chunk_id, st.concept_id, st.reviewed_at, st.model
        FROM staged_tags st
        WHERE st.status = 'accepted'
        ORDER BY st.reviewed_at
    """).fetchall()

    concept_first_seen = {}
    for r in c.execute("SELECT id, type, metadata_json FROM nodes WHERE type='concept'"):
        meta = json.loads(r["metadata_json"]) if r["metadata_json"] else {}
        created = meta.get("created_at") or meta.get("added_at")
        if created:
            concept_first_seen[r["id"]] = created

    findings = []
    for r in tag_rows:
        cid = r["concept_id"]
        tag_time = r["reviewed_at"] or ""
        concept_time = concept_first_seen.get(cid, "")
        if concept_time and tag_time and tag_time < concept_time:
            findings.append({
                "chunk_id": r["chunk_id"],
                "concept_id": cid,
                "tag_reviewed_at": tag_time,
                "concept_created_at": concept_time,
                "model": r["model"],
            })

    orphan_concepts = c.execute("""
        SELECT DISTINCT concept_id FROM staged_tags
        WHERE status = 'accepted'
        AND concept_id NOT IN (SELECT id FROM nodes WHERE type = 'concept')
    """).fetchall()
    for r in orphan_concepts:
        findings.append({
            "chunk_id": "(various)",
            "concept_id": r["concept_id"],
            "tag_reviewed_at": "(n/a)",
            "concept_created_at": "(NO NODE — concept defined but never promoted)",
            "model": "(unknown)",
            "note": "accepted tag references a concept with no node — possible drift",
        })
    return findings


# ── 5. Novel-cell contamination ───────────────────────────────────────────────

def check_novel_cell_contamination():
    """
    A concept with >= 20 accepted tags elsewhere and zero prior presence in a
    tradition, suddenly tagged there.
    """
    chunk_to_trad = {}
    for r in c.execute("SELECT id, tradition_id FROM nodes WHERE type = 'chunk'"):
        chunk_to_trad[r["id"]] = r["tradition_id"]

    applied_counts = defaultdict(lambda: defaultdict(int))
    for r in c.execute("""
        SELECT chunk_id, concept_id FROM staged_tags WHERE status = 'accepted'
    """):
        tid = chunk_to_trad.get(r["chunk_id"], "")
        if tid:
            applied_counts[r["concept_id"]][tid] += 1

    all_trads = set(chunk_to_trad.values())

    findings = []
    for concept_id, trad_counts in applied_counts.items():
        total_elsewhere = sum(trad_counts.values())
        if total_elsewhere < 20:
            continue
        present_trads = set(trad_counts.keys())
        absent_trads = all_trads - present_trads
        if not absent_trads:
            continue
        for r in c.execute("""
            SELECT chunk_id FROM staged_tags
            WHERE concept_id = ? AND status IN ('pending', 'accepted')
        """, (concept_id,)):
            tid = chunk_to_trad.get(r["chunk_id"], "")
            if tid and tid in absent_trads:
                findings.append({
                    "concept_id": concept_id,
                    "novel_tradition": tid,
                    "tags_in_novel_tradition": "pending/accepted",
                    "total_tags_elsewhere": total_elsewhere,
                    "present_traditions": sorted(present_trads),
                    "absent_traditions": sorted(absent_trads),
                })
                break
    return findings


# ── 6. Taxonomy redundancy ──────────────────────────────────────────────────

def check_taxonomy_redundancy():
    """Concepts near-duplicate enough to merge or split."""
    concepts = c.execute(
        "SELECT id, label, definition FROM nodes WHERE type = 'concept'"
    ).fetchall()
    findings = []

    for i, c1 in enumerate(concepts):
        for c2 in concepts[i + 1:]:
            label_sim = similarity(c1["label"], c2["label"])
            if label_sim > 0.85 and label_sim < 1.0:
                findings.append({
                    "type": "label_similarity",
                    "concept_a": c1["id"],
                    "label_a": c1["label"],
                    "concept_b": c2["id"],
                    "label_b": c2["label"],
                    "similarity": round(label_sim, 3),
                })
            def_sim = 0
            if c1["definition"] and c2["definition"]:
                def_sim = similarity(c1["definition"], c2["definition"])
            elif c1["label"] == c2["label"]:
                def_sim = 1.0
            if def_sim > 0.90 and def_sim < 1.0 and label_sim <= 0.85:
                findings.append({
                    "type": "definition_similarity",
                    "concept_a": c1["id"],
                    "label_a": c1["label"],
                    "concept_b": c2["id"],
                    "label_b": c2["label"],
                    "similarity": round(def_sim, 3),
                })

    families = c.execute(
        "SELECT id, parent_id, label, definition FROM concept_families"
    ).fetchall()
    for i, f1 in enumerate(families):
        for f2 in families[i + 1:]:
            sim = (
                similarity(f1["label"], f2["label"])
                if f1["label"] and f2["label"]
                else 0
            )
            if sim > 0.85 and sim < 1.0:
                findings.append({
                    "type": "family_similarity",
                    "family_a": f1["id"],
                    "label_a": f1["label"],
                    "family_b": f2["id"],
                    "label_b": f2["label"],
                    "similarity": round(sim, 3),
                })

    return findings


# ── 7. Dangling curation ────────────────────────────────────────────────────

def check_dangling_curation(bodies):
    """Tags/edges/embeddings pointing at chunk ids that no longer exist."""
    db_chunk_ids = set(
        r[0] for r in c.execute("SELECT id FROM nodes WHERE type = 'chunk'")
    )

    findings = []

    # staged_tags pointing to non-existent chunks
    if db_chunk_ids:
        placeholders = ",".join("?" * len(db_chunk_ids))
        dangling_tags = c.execute(f"""
            SELECT chunk_id, COUNT(*) as cnt
            FROM staged_tags
            WHERE status IN ('pending', 'accepted')
            AND chunk_id NOT IN ({placeholders})
            GROUP BY chunk_id
        """, tuple(db_chunk_ids)).fetchall()
        for r in dangling_tags:
            findings.append({
                "type": "staged_tags_dangling",
                "chunk_id": r["chunk_id"],
                "count": r["cnt"],
            })

        # staging_cleanups pointing to non-existent chunks
        dangling_cleanups = c.execute(f"""
            SELECT chunk_id, COUNT(*) as cnt
            FROM staged_cleanups
            WHERE chunk_id NOT IN ({placeholders})
            GROUP BY chunk_id
        """, tuple(db_chunk_ids)).fetchall()
        for r in dangling_cleanups:
            findings.append({
                "type": "staged_cleanups_dangling",
                "chunk_id": r["chunk_id"],
                "count": r["cnt"],
            })

        # chunk_embeddings pointing to non-existent chunks
        dangling_emb = c.execute(f"""
            SELECT chunk_id, COUNT(*) as cnt
            FROM chunk_embeddings
            WHERE chunk_id NOT IN ({placeholders})
            GROUP BY chunk_id
        """, tuple(db_chunk_ids)).fetchall()
        for r in dangling_emb:
            findings.append({
                "type": "embeddings_dangling",
                "chunk_id": r["chunk_id"],
                "count": r["cnt"],
            })

        # tagging_progress pointing to non-existent chunks
        dangling_progress = c.execute(f"""
            SELECT chunk_id, COUNT(*) as cnt
            FROM tagging_progress
            WHERE chunk_id NOT IN ({placeholders})
            GROUP BY chunk_id
        """, tuple(db_chunk_ids)).fetchall()
        for r in dangling_progress:
            findings.append({
                "type": "tagging_progress_dangling",
                "chunk_id": r["chunk_id"],
                "count": r["cnt"],
            })

        # Edges pointing to non-existent chunks
        missing_edge_sources = c.execute(f"""
            SELECT source_id, COUNT(*) as cnt
            FROM edges
            WHERE source_id NOT IN ({placeholders})
            GROUP BY source_id
        """, tuple(db_chunk_ids)).fetchall()
        for r in missing_edge_sources:
            findings.append({
                "type": "edges_source_dangling",
                "chunk_id": r["source_id"],
                "count": r["cnt"],
            })

        missing_edge_targets = c.execute(f"""
            SELECT target_id, COUNT(*) as cnt
            FROM edges
            WHERE target_id NOT IN ({placeholders})
            GROUP BY target_id
        """, tuple(db_chunk_ids)).fetchall()
        for r in missing_edge_targets:
            findings.append({
                "type": "edges_target_dangling",
                "chunk_id": r["target_id"],
                "count": r["cnt"],
            })

    return findings


# ── 8. Works stuck mid-review (would export empty) ───────────────────────────

def check_stuck_works(bodies):
    """Works in corpus/ that have chunks but no applied concept tags."""
    chunk_to_text = {}
    for toml_file in CORPUS_ROOT.rglob("chunks/*.toml"):
        try:
            data = tomllib.loads(toml_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        chunk = data.get("chunk", {})
        cid = chunk.get("id")
        text_id = chunk.get("text_id", "") or cid.rsplit(".", 1)[0] if cid else ""
        if cid:
            chunk_to_text[cid] = text_id

    text_applied = defaultdict(int)
    for r in c.execute("""
        SELECT chunk_id, COUNT(*) as cnt
        FROM staged_tags
        WHERE status = 'accepted'
        GROUP BY chunk_id
    """):
        tid = chunk_to_text.get(r["chunk_id"], "")
        if tid:
            text_applied[tid] += r["cnt"]

    all_texts = set()
    for meta_file in CORPUS_ROOT.rglob("metadata.toml"):
        try:
            data = tomllib.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        tid = data.get("text", {}).get("id") or data.get("text_id")
        if not tid:
            parts = meta_file.parts
            if len(parts) >= 2:
                tid = parts[-2]
        if tid:
            all_texts.add(tid)

    text_chunk_counts = defaultdict(int)
    for r in c.execute("SELECT tradition_id, id FROM nodes WHERE type = 'chunk'"):
        cid = r["id"]
        tid = chunk_to_text.get(cid, "")
        if tid:
            text_chunk_counts[tid] += 1

    findings = []
    for tid in sorted(all_texts):
        chunk_count = text_chunk_counts.get(tid, 0)
        applied_count = text_applied.get(tid, 0)
        if chunk_count > 0 and applied_count == 0:
            findings.append({
                "text_id": tid,
                "chunk_count": chunk_count,
                "applied_tags": 0,
                "pct_tagged": 0,
            })
        elif chunk_count > 0 and applied_count > 0 and applied_count / chunk_count < 0.1:
            pct = round(applied_count / chunk_count * 100, 1)
            findings.append({
                "text_id": tid,
                "chunk_count": chunk_count,
                "applied_tags": applied_count,
                "pct_tagged": pct,
                "note": "severe under-tagging",
            })
    return findings


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 70)
    print("CORPUS-QUALITY INTAKE DIAGNOSTIC SWEEP")
    print("=" * 70)

    print("\n⏳ Loading chunk bodies from corpus/...")
    bodies, chunk_files = load_chunk_bodies()
    print(f"  Loaded {len(bodies)} chunk bodies from {len(chunk_files)} files.")

    # 1. Apparatus
    print("\n🔍 1. Apparatus in primary text")
    apparatus = check_apparatus(bodies)
    if apparatus:
        print(f"  Found {len(apparatus)} candidate apparatus chunks:")
        for f in apparatus[:20]:
            print(f"    • [{f['apparatus_type']}] {f['chunk_id']}")
            print(f"      body: {f['body_preview'][:120]}...")
    else:
        print("  None found.")

    # 2. Duplicate bodies
    print("\n🔍 2. Duplicate chunk bodies (byte-identical)")
    dups = check_duplicate_bodies(bodies)
    if dups:
        print(f"  Found {len(dups)} duplicate body groups:")
        for f in dups[:20]:
            print(f"    • {len(f['chunk_ids'])} chunks share body ({f['body_length']} chars):")
            for cid in f["chunk_ids"][:5]:
                print(f"      • {cid}")
            print(f"      body: {f['body_preview'][:100]}...")
    else:
        print("  None found.")

    # 3. Duplicate pending tags
    print("\n🔍 3. Duplicate pending tags (same chunk+concept, multiple model batches)")
    dup_tags = check_duplicate_pending_tags()
    if dup_tags:
        print(f"  Found {len(dup_tags)} duplicate pending tag sets:")
        for f in dup_tags[:20]:
            print(f"    • chunk={f['chunk_id']}, concept={f['concept_id']}")
            for b in f["batches"]:
                print(f"      • model={b['model']}, count={b['count']}")
    else:
        print("  None found.")

    # 4. Blind / drifted tags
    print("\n🔍 4. Blind / drifted tags (applied tags predating concept definition)")
    blind = check_blind_tags()
    if blind:
        print(f"  Found {len(blind)} drifted/applied-to-undefined tags:")
        for f in blind[:20]:
            print(f"    • chunk={f['chunk_id']}, concept={f['concept_id']}")
            print(f"      tag_time={f['tag_reviewed_at']}, concept_time={f['concept_created_at']}")
    else:
        print("  None found.")

    # 5. Novel-cell contamination
    print("\n🔍 5. Novel-cell contamination")
    novel = check_novel_cell_contamination()
    if novel:
        print(f"  Found {len(novel)} candidate novel-cell tags:")
        for f in novel[:20]:
            print(f"    • concept={f['concept_id']}, novel_tradition={f['novel_tradition']}")
            print(f"      tags_elsewhere={f['total_tags_elsewhere']}, present={f['present_traditions']}")
    else:
        print("  None found.")

    # 6. Taxonomy redundancy
    print("\n🔍 6. Taxonomy redundancy (near-duplicate concepts/families)")
    redundancy = check_taxonomy_redundancy()
    if redundancy:
        print(f"  Found {len(redundancy)} near-duplicate pairs:")
        for f in redundancy[:20]:
            print(f"    • [{f['type']}] {f['concept_a']} ~ {f['concept_b']} (sim={f['similarity']})")
            print(f"      labels: {f.get('label_a','')} | {f.get('label_b','')}")
    else:
        print("  None found.")

    # 7. Dangling curation
    print("\n🔍 7. Dangling curation (tags/edges/embeddings → non-existent chunks)")
    dangling = check_dangling_curation(bodies)
    if dangling:
        print(f"  Found {len(dangling)} dangling references:")
        for f in dangling[:20]:
            print(f"    • [{f['type']}] {f.get('chunk_id', 'N/A')}")
    else:
        print("  None found.")

    # 8. Stuck works
    print("\n🔍 8. Works stuck mid-review (would export empty)")
    stuck = check_stuck_works(bodies)
    if stuck:
        print(f"  Found {len(stuck)} under-tagged / stuck works:")
        for f in stuck[:20]:
            print(f"    • {f['text_id']}: {f['chunk_count']} chunks, {f['applied_tags']} applied tags ({f.get('pct_tagged',0)}%)")
            if "note" in f:
                print(f"      note: {f['note']}")
    else:
        print("  None found.")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  1. Apparatus in primary text:  {len(apparatus)}")
    print(f"  2. Duplicate chunk bodies:     {len(dups)}")
    print(f"  3. Duplicate pending tags:     {len(dup_tags)}")
    print(f"  4. Blind/drifted tags:         {len(blind)}")
    print(f"  5. Novel-cell contamination:   {len(novel)}")
    print(f"  6. Taxonomy redundancy:        {len(redundancy)}")
    print(f"  7. Dangling curation:          {len(dangling)}")
    print(f"  8. Stuck mid-review works:     {len(stuck)}")
    total = (
        len(apparatus) + len(dups) + len(dup_tags) + len(blind)
        + len(novel) + len(redundancy) + len(dangling) + len(stuck)
    )
    print(f"\n  TOTAL findings: {total}")
