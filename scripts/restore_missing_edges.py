#!/usr/bin/env python3
"""Restore the 55 missing EXPRESSES edges for accepted tags whose edges were
deleted by the reject path deleting shared edges.

The bug: when Carnice-9b's tag for a (chunk, concept) pair was rejected,
review_tags.py:137 unconditionally ran:
    DELETE FROM edges WHERE source_id=? AND target_id=? AND type='EXPRESSES'
This deleted the edge even if Qwen3.5 (or another model) had an accepted tag
for the same pair.

Fix: for each of the 55 missing-edge accepted tags, recreate the EXPRESSES edge
at concept.$concept_id with tier=verified (matching the original apply).
"""
import sqlite3, sys, os, shutil

DB_PATH = '/home/ivy/Work/guru/data/guru.db'
BACKUP_DIR = os.path.expanduser('~/guru-backups')

def main():
    dry_run = '--apply' not in sys.argv

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Find the 55 accepted tags with bare concept IDs missing their EXPRESSES edges
    missing = c.execute("""
        SELECT st.chunk_id, st.concept_id, st.id, NULL, NULL
        FROM staged_tags st
        WHERE st.status='accepted'
        AND st.concept_id IS NOT NULL
        AND st.concept_id != ''
        AND NOT EXISTS (
            SELECT 1 FROM edges e
            WHERE e.source_id = st.chunk_id
            AND e.target_id = 'concept.' || st.concept_id
            AND e.type = 'EXPRESSES'
        )
        ORDER BY st.chunk_id, st.concept_id
    """).fetchall()

    print(f"Accepted tags missing EXPRESSES edges: {len(missing)}")
    print(f"Dry run: {dry_run}")

    for chunk_id, concept_id, tag_id, reviewed_by, scored_by in missing[:10]:
        # Check what's there
        edge_exists = c.execute("SELECT 1 FROM edges WHERE source_id=? AND target_id='concept.'||? AND type='EXPRESSES'", (chunk_id, concept_id)).fetchone()
        concept_exists = c.execute("SELECT 1 FROM nodes WHERE id='concept.'||?", (concept_id,)).fetchone()
        print(f"  {chunk_id} → concept.{concept_id}: edge_exists={bool(edge_exists)}, concept_exists={bool(concept_exists)}")

    if not dry_run and missing:
        backup_name = f"{BACKUP_DIR}/restore_edges_{os.getpid()}.db"
        os.makedirs(BACKUP_DIR, exist_ok=True)
        shutil.copy2(DB_PATH, backup_name)
        print(f"Backup: {backup_name}")

        c.execute("BEGIN;")
        for chunk_id, concept_id, tag_id, _, _ in missing:
            c.execute("""
                INSERT OR IGNORE INTO edges (source_id, target_id, type, tier, created_at)
                VALUES (?, 'concept.'||?, 'EXPRESSES', 'verified', datetime('now'))
            """, (chunk_id, concept_id))
        c.execute("COMMIT;")
        print(f"Restored {c.rowcount} edges")

    conn.close()
    if dry_run:
        print("\nDry run only. Run with --apply to execute.")

if __name__ == '__main__':
    main()
