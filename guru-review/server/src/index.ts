// Boot harness — for P2 it just opens DB, applies schema, validates fingerprint, exits.
// Later phases extend this to mount Express routes and listen.

import { loadConfig } from './config.js';
import { openDb } from './db.js';
import { validateSchemaFingerprint } from './schema.js';

async function main(): Promise<void> {
  const cfg = loadConfig();
  const { ro, rw } = openDb(cfg);
  // Post-schema-apply: confirms upstream tables still match what we expect
  // AND that review_actions made it. A mismatch here means either upstream
  // dropped/renamed a table (refuse-to-run, prompt update) or our schema
  // apply silently failed.
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
