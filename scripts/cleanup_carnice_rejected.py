#!/usr/bin/env python3
"""Cleanup: Remove rejected Carnice-9b tags that have accepted siblings.

When Carnice-9b's tag is rejected (after initial acceptance), the review app
unconditionally deletes the EXPRESSES edge — even if Qwen3.5 or qwen-3-4b-guru
has an accepted tag for the same (chunk, concept) pair. The stale rejected
Carnice-9b rows in staged_tags are safe to remove once there's an accepted
sibling that justifies keeping the concept on that chunk.

This script:
1. Finds all rejected Carnice-9b tags that have at least one accepted sibling
2. Reports what would be deleted (dry-run by default)
3. On --apply: deletes the rejected Carnice-9b rows

IMPORTANT: This does NOT restore the deleted EXPRESSES edges. That requires
a separate edge-recreation migration (see ticket d9bb3b9a). Removing these
tags just cleans up the staging table.

Per constraint: this script writes to the DB. Run via the user's apply gate.
"""
import sqlite3, sys, os

DB_PATH = '/home/ivy/Work/guru/data/guru.db'
BACKUP_DIR = os.path.expanduser('~/guru-backups')

def main():
    dry_run = '--apply' not in sys.argv

    # Safety check
    if not dry_run:
        # Create backup
        os.makedirs(BACKUP_DIR, exist_ok=True)
        backup_name = f"{BACKUP_DIR}/cleanup_carnice_{os.getpid()}.db"
        import shutil
        shutil.copy2(DB_PATH, backup_name)
        print(f"Backup created: {backup_name}")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Find rejected Carnice-9b tags with accepted siblings
    c.execute("""
        SELECT st.chunk_id, st.concept_id, st.id, st.score
        FROM staged_tags st
        WHERE st.status='rejected' AND st.model='Carnice-9b'
        AND EXISTS (
            SELECT 1 FROM staged_tags st2
            WHERE st2.chunk_id = st.chunk_id
            AND st2.concept_id = st.concept_id
            AND st2.status='accepted'
        )
        ORDER BY st.chunk_id
    """)

    to_delete = c.fetchall()
    print(f"\nRejected Carnice-9b tags with accepted siblings: {len(to_delete)}")
    print(f"Would delete (dry run: {dry_run})")

    for chunk, concept, tag_id, score in to_delete:
        print(f"  id={tag_id}: {chunk} → {concept} (score={score})")

    if not dry_run and to_delete:
        # Build the IN clause
        ids = [r[2] for r in to_delete]
        placeholders = ','.join('?' * len(ids))

        c.execute("BEGIN; -- cleanup_carnice_rejected")
        c.execute(f"DELETE FROM staged_tags WHERE id IN ({placeholders})", ids)
        deleted = c.rowcount
        c.execute("COMMIT;")
        print(f"\nDeleted {deleted} rows")

    conn.close()

    if dry_run:
        print("\nDry run only. Run with --apply to execute.")
        print("Remember to back up the DB first: scripts/backup_db.sh corpus-quality-<id>")

if __name__ == '__main__':
    main()
