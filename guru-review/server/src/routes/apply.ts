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
    const counts = stmts.countQueuedByAction.all() as {
      target_table: 'staged_tags' | 'staged_edges';
      action: string;
      n: number;
    }[];
    const total = counts.reduce((acc, c) => acc + c.n, 0);
    const by_action = counts.reduce<Record<string, number>>((acc, c) => {
      acc[c.action] = (acc[c.action] ?? 0) + c.n;
      return acc;
    }, {});
    const by_target_table = counts.reduce<Record<string, number>>((acc, c) => {
      acc[c.target_table] = (acc[c.target_table] ?? 0) + c.n;
      return acc;
    }, {});
    const affected = ro
      .prepare(
        `SELECT target_table, COUNT(DISTINCT target_id) AS n
         FROM review_actions WHERE applied_at IS NULL
         GROUP BY target_table`,
      )
      .all() as { target_table: 'staged_tags' | 'staged_edges'; n: number }[];
    res.json({
      total_queued: total,
      by_action,
      by_target_table,
      affected_staged_tags: affected.find((a) => a.target_table === 'staged_tags')?.n ?? 0,
      affected_staged_edges: affected.find((a) => a.target_table === 'staged_edges')?.n ?? 0,
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
