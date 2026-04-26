import { Router } from 'express';
import { z } from 'zod';
import type Database from 'better-sqlite3';
import type { PreparedStmts } from '../db.js';
import { buildApply } from '../apply.js';

const ApplyBody = z.object({
  client_action_id: z.string().min(1),
});

export function applyRouter(rw: Database.Database, ro: Database.Database, stmts: PreparedStmts): Router {
  const r = Router();

  const apply = buildApply(rw, stmts);

  r.get('/apply/preview', (_req, res) => {
    const counts = stmts.countQueuedByAction.all() as { action: string; n: number }[];
    const total = counts.reduce((acc, c) => acc + c.n, 0);
    const distinctChunks = ro
      .prepare(
        `SELECT COUNT(DISTINCT target_id) AS n
         FROM review_actions WHERE applied_at IS NULL`,
      )
      .get() as { n: number };
    res.json({
      total_queued: total,
      by_action: counts.reduce<Record<string, number>>((acc, c) => {
        acc[c.action] = c.n;
        return acc;
      }, {}),
      affected_staged_tags: distinctChunks.n,
    });
  });

  r.post('/apply', (req, res) => {
    const parsed = ApplyBody.safeParse(req.body);
    if (!parsed.success) {
      res.status(400).json({ error: parsed.error.flatten() });
      return;
    }

    try {
      const result = apply();
      // If queue was empty, surface that as a sentinel for the UI per §10 #5.
      if (result.applied === 0 && result.skipped_already_resolved === 0) {
        res.json({ ...result, status: 'already_applied' });
        return;
      }
      res.json({ ...result, status: 'applied' });
    } catch (e) {
      const msg = (e as Error).message ?? String(e);
      res.status(500).json({ error: msg, rolled_back: true });
    }
  });

  return r;
}
