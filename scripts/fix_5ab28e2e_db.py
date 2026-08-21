#!/usr/bin/env python3
"""Fix 5ab28e2e: Remap concept.sephirot_tree → concept.sefirot_tree and delete orphan.

Steps:
1. Retarget 1 edge from target_id='concept.sephirot_tree' → 'concept.sefirot_tree'
2. Retarget 5 staged_tags from concept_id='sephirot_tree' → 'sefirot_tree'
3. Delete orphan node 'concept.sephirot_tree'
4. Add the alias to concept_aliases table (if not present)
"""
import sqlite3, sys, os, shutil

DB_PATH = '/home/ivy/Work/guru/data/guru.db'
BACKUP_DIR = os.path.expanduser('~/guru-backups')
dry_run = '--apply' not in sys.argv

def main():
    if not dry_run:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        backup_name = f"{BACKUP_DIR}/fix_5ab28e2e_{os.getpid()}.db"
        shutil.copy2(DB_PATH, backup_name)
        print(f"Backup: {backup_name}")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Before state
    edge = c.execute("""
        SELECT id, target_id FROM edges 
        WHERE target_id='concept.sephirot_tree' AND type='EXPRESSES'
    """).fetchone()
    print(f"Edge to retarget: {edge}")

    tags = c.execute("SELECT id, chunk_id, concept_id FROM staged_tags WHERE concept_id='sephirot_tree'").fetchall()
    print(f"Tags to remap: {len(tags)}")
    for t in tags:
        print(f"  id={t[0]}: {t[1]} → {t[2]}")

    node = c.execute("SELECT definition FROM nodes WHERE id='concept.sephirot_tree'").fetchone()
    print(f"Orphan node definition: {node}")

    # Check alias table
    alias = c.execute("SELECT * FROM concept_aliases WHERE concept_id='sefirot_tree'").fetchall()
    print(f"Existing sefirot_tree aliases: {alias}")

    if dry_run:
        print("\n--- DRY RUN ---")
        print("Would:")
        print("  1. UPDATE edges SET target_id='concept.sefirot_tree' WHERE target_id='concept.sephirot_tree'")
        print("  2. UPDATE staged_tags SET concept_id='sefirot_tree' WHERE concept_id='sephirot_tree'")
        print("  3. INSERT INTO concept_aliases (concept_id, alias) VALUES ('sefirot_tree', 'sephirot_tree')")
        print("  4. DELETE FROM nodes WHERE id='concept.sephirot_tree'")
    else:
        c.execute("BEGIN; -- fix 5ab28e2e")
        c.execute("UPDATE edges SET target_id='concept.sefirot_tree' WHERE target_id='concept.sephirot_tree'")
        print(f"  Edges retargeted: {c.rowcount}")
        c.execute("UPDATE staged_tags SET concept_id='sefirot_tree' WHERE concept_id='sephirot_tree'")
        print(f"  Tags remapped: {c.rowcount}")
        c.execute("INSERT OR IGNORE INTO concept_aliases (concept_id, alias) VALUES ('sefirot_tree', 'sephirot_tree')")
        print(f"  Aliases inserted: {c.rowcount}")
        c.execute("DELETE FROM nodes WHERE id='concept.sephirot_tree'")
        print(f"  Orphan node deleted: {c.rowcount}")
        c.execute("COMMIT;")

    conn.close()
    if dry_run:
        print("\nDry run only. Run with --apply to execute.")

if __name__ == '__main__':
    main()
