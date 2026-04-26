import { Router } from 'express';
import { z } from 'zod';
import type { PreparedStmts } from '../db.js';

const ActionSchema = z.discriminatedUnion('action', [
  z.object({
    action: z.literal('accept'),
    reassign_to: z.undefined().or(z.null()),
    client_action_id: z.string().min(1),
    reviewer: z.string().min(1),
  }),
  z.object({
    action: z.literal('reject'),
    reassign_to: z.undefined().or(z.null()),
    client_action_id: z.string().min(1),
    reviewer: z.string().min(1),
  }),
  z.object({
    action: z.literal('skip'),
    reassign_to: z.undefined().or(z.null()),
    client_action_id: z.string().min(1),
    reviewer: z.string().min(1),
  }),
  z.object({
    action: z.literal('reassign'),
    reassign_to: z.string().min(1),
    client_action_id: z.string().min(1),
    reviewer: z.string().min(1),
  }),
]);

export function tagsRouter(stmts: PreparedStmts): Router {
  const r = Router();

  r.post('/tags/:target_id/action', (req, res) => {
    const id = Number.parseInt(req.params.target_id, 10);
    if (!Number.isFinite(id) || id <= 0) {
      res.status(400).json({ error: 'invalid target_id' });
      return;
    }

    const parsed = ActionSchema.safeParse(req.body);
    if (!parsed.success) {
      res.status(400).json({ error: parsed.error.flatten() });
      return;
    }
    const { action, reassign_to, client_action_id, reviewer } = parsed.data;

    // Existence check (fast 404 for bogus ids — not a staleness check;
    // apply transaction re-checks per row at apply time).
    const exists = stmts.selectStagedTagExists.get(id);
    if (!exists) {
      res.status(404).json({ error: `staged_tag ${id} not found` });
      return;
    }

    try {
      stmts.insertReviewAction.run(
        id,
        action,
        action === 'reassign' ? reassign_to : null,
        reviewer,
        client_action_id,
      );
      res.json({ ok: true, queued: true });
    } catch (e) {
      const msg = (e as Error).message ?? '';
      // Idempotency: replay of same client_action_id = success no-op.
      if (msg.includes('UNIQUE constraint failed: review_actions.client_action_id')) {
        res.json({ ok: true, queued: false, idempotent: true });
        return;
      }
      // CHECK constraint failures (e.g. action/reassign_to mismatch — should
      // be caught by zod first but defense in depth)
      if (msg.includes('CHECK constraint')) {
        res.status(400).json({ error: 'action/reassign_to combination violates DB CHECK' });
        return;
      }
      res.status(500).json({ error: msg });
    }
  });

  return r;
}
