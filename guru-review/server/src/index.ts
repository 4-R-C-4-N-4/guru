import express from 'express';
import { loadConfig } from './config.js';
import { openDb } from './db.js';
import { validateSchemaFingerprint } from './schema.js';
import { takeStartupSnapshot } from './snapshot.js';
import { ChunkBodyCache } from './chunkBody.js';
import { healthRouter } from './routes/health.js';
import { statsRouter } from './routes/stats.js';
import { traditionsRouter } from './routes/traditions.js';
import { textsRouter } from './routes/texts.js';
import { conceptsRouter } from './routes/concepts.js';
import { chunksRouter } from './routes/chunks.js';
import { tagsRouter } from './routes/tags.js';

async function main(): Promise<void> {
  const cfg = loadConfig();

  const snap = await takeStartupSnapshot(cfg.db_path, cfg.backup_dir, cfg.keep_backups);
  console.log(`[guru-review] snapshot: ${snap.target}`);
  console.log(
    `[guru-review] canary: staged_tags=${snap.staged_tags} pending=${snap.pending} accepted=${snap.accepted} edges=${snap.edges} nodes=${snap.nodes}`,
  );

  const { ro, rw, stmts } = openDb(cfg);
  validateSchemaFingerprint(rw);
  console.log(`[guru-review] schema applied to ${cfg.db_path}`);

  const corpusDir = `${cfg.guru_root}/corpus`;
  const body = new ChunkBodyCache(corpusDir);

  const app = express();
  app.use(express.json());

  app.use('/api', healthRouter());
  app.use('/api', statsRouter(ro));
  app.use('/api', traditionsRouter(ro));
  app.use('/api', textsRouter(ro));
  app.use('/api', conceptsRouter(ro));
  app.use('/api', chunksRouter(ro, body));
  app.use('/api', tagsRouter(stmts));

  app.listen(cfg.port, cfg.host, () => {
    console.log(`[guru-review] listening on http://${cfg.host}:${cfg.port}`);
    console.log(`[guru-review] dry_run=${cfg.dry_run}`);
  });

  // graceful shutdown closes both handles
  const shutdown = (sig: string): void => {
    console.log(`[guru-review] ${sig} received, closing`);
    ro.close();
    rw.close();
    process.exit(0);
  };
  process.on('SIGTERM', () => shutdown('SIGTERM'));
  process.on('SIGINT', () => shutdown('SIGINT'));
}

main().catch((e) => {
  console.error('[guru-review] boot failed:', e);
  process.exit(1);
});
