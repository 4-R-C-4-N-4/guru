// Boot harness — for P2 it just opens DB, applies schema, validates fingerprint, exits.
// Later phases extend this to mount Express routes and listen.

import { loadConfig } from './config.js';
import { openDb } from './db.js';
import { validateSchemaFingerprint } from './schema.js';
import { takeStartupSnapshot } from './snapshot.js';

async function main(): Promise<void> {
  const cfg = loadConfig();

  // Snapshot BEFORE opening rw — if backup or integrity_check fails,
  // we never touch the live DB.
  const snap = await takeStartupSnapshot(cfg.db_path, cfg.backup_dir, cfg.keep_backups);
  console.log(`[guru-review] snapshot: ${snap.target}`);
  console.log(
    `[guru-review] canary: staged_tags=${snap.staged_tags} pending=${snap.pending} accepted=${snap.accepted} edges=${snap.edges} nodes=${snap.nodes}`,
  );

  const { ro, rw } = openDb(cfg);
  validateSchemaFingerprint(rw);

  console.log(`[guru-review] schema applied to ${cfg.db_path}`);
  console.log(`[guru-review] dry_run=${cfg.dry_run}, port=${cfg.port}`);

  ro.close();
  rw.close();
}

main().catch((e) => {
  console.error('[guru-review] boot failed:', e);
  process.exit(1);
});
