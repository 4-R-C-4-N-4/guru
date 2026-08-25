import { Router } from 'express';
import type Database from 'better-sqlite3';
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

export function tagsRouter(stmts: PreparedStmts, rw: Database.Database): Router {
  const r = Router();

  // Shared per-item queue logic for the single and bulk endpoints. Same
  // validation, same review_actions row shape, same idempotency — the bulk
  // endpoint is purely transport (todo:37dd43de); the human apply gate
  // (POST /api/apply) remains the only promotion path.
  type ItemOutcome =
    | { status: 'queued' }
    | { status: 'idempotent' }
    | { status: 'unknown' }
    | { status: 'invalid'; error: unknown }
    | { status: 'error'; error: string };

  function queueOne(
    targetId: number,
    body: unknown,
  ): ItemOutcome {
    if (!Number.isFinite(targetId) || targetId <= 0) {
      return { status: 'invalid', error: 'invalid target_id' };
    }

    const parsed = ActionSchema.safeParse(body);
    if (!parsed.success) {
      return { status: 'invalid', error: parsed.error.flatten() };
    }
    const { action, reassign_to, client_action_id, reviewer } = parsed.data;

    // Existence check (fast unknown-id report for bogus ids — not a
    // staleness check; apply transaction re-checks per row at apply time).
    const exists = stmts.selectStagedTagExists.get(targetId);
    if (!exists) {
      return { status: 'unknown' };
    }

    try {
      stmts.insertReviewAction.run(
        targetId,
        'staged_tags',
        action,
        action === 'reassign' ? reassign_to : null,
        null,                  // reclassify_to — staged_tags branch never sets this
        reviewer,
        client_action_id,
      );
      return { status: 'queued' };
    } catch (e) {
      const msg = (e as Error).message ?? '';
      // Idempotency: replay of same client_action_id = success no-op.
      if (msg.includes('UNIQUE constraint failed: review_actions.client_action_id')) {
        return { status: 'idempotent' };
      }
      return { status: 'error', error: msg };
    }
  }

  r.post('/tags/:target_id/action', (req, res) => {
    const id = Number.parseInt(req.params.target_id, 10);
    if (!Number.isFinite(id) || id <= 0) {
      res.status(400).json({ error: 'invalid target_id' });
      return;
    }

    const outcome = queueOne(id, req.body);
    switch (outcome.status) {
      case 'invalid':
        res.status(400).json({ error: outcome.error });
        break;
      case 'unknown':
        res.status(404).json({ error: `staged_tag ${id} not found` });
        break;
      case 'queued':
        res.json({ ok: true, queued: true });
        break;
      case 'idempotent':
        res.json({ ok: true, queued: false, idempotent: true });
        break;
      case 'error': {
        const msg = outcome.error;
        // CHECK constraint failures (e.g. action/reassign_to mismatch — should
        // be caught by zod first but defense in depth)
        if (msg.includes('CHECK constraint')) {
          res.status(400).json({ error: 'action/reassign_to combination violates DB CHECK' });
          return;
        }
        res.status(500).json({ error: msg });
      }
    }
  });

  // Bulk variant (todo:ee0b6136): accepts [{target_id, action, ...}] so a
  // scripted reviewer can queue an entire batch in one call and reconcile
  // counts against the response instead of looping per-tag HTTP calls.
  // Per-item outcomes never fail the batch: one bad row is reported, not
  // fatal. The whole insert loop runs inside one transaction.
  const BulkItemSchema = z.object({
    target_id: z.number().int().positive(),
    action: z.string(),
    reassign_to: z.string().optional().nullable(),
    client_action_id: z.string().min(1),
    reviewer: z.string().min(1),
  });

  r.post('/tags/bulk', (req, res) => {
    const items = req.body;
    if (!Array.isArray(items)) {
      res.status(400).json({ error: 'body must be an array of {target_id, action}' });
      return;
    }
    if (items.length === 0) {
      res.status(400).json({ error: 'empty batch' });
      return;
    }
    if (items.length > 50000) {
      res.status(413).json({ error: `batch too large (${items.length}); split into batches of <= 50000` });
      return;
    }

    let queued = 0;
    let skipped = 0;       // idempotent replays + invalid items
    const unknown_ids: number[] = [];
    const invalid_items: Array<{ index: number; error: unknown }> = [];
    const errored_items: Array<{ index: number; error: string }> = [];

    // Per-item result map (todo:37dd43de review): request index -> outcome,
    // so a client reconciles EVERY request row against the server in one
    // array — including zod-invalid rows, which have no target_id to key by.
    // Keying by target_id (the original shape) lost invalid rows entirely and
    // collapsed distinct rows sharing a target_id to one entry.
    type ItemStatus = 'queued' | 'skipped' | 'unknown' | 'error';
    const results: Array<{ index: number; status: ItemStatus }> = [];

    const prevalidated = items.map((item, index) => ({
      item: BulkItemSchema.safeParse(item),
      index,
    }));

    const queueBatch = rw.transaction(() => {
      for (const { item, index } of prevalidated) {
        if (!item.success) {
          skipped++;
          results.push({ index, status: 'skipped' });
          invalid_items.push({ index, error: item.error.flatten() });
          continue;
        }
        const outcome = queueOne(
          item.data.target_id,
          items[index],
        );
        switch (outcome.status) {
          case 'queued':
            queued++;
            results.push({ index, status: 'queued' });
            break;
          case 'idempotent':
            skipped++;
            results.push({ index, status: 'skipped' });
            break;
          case 'unknown':
            unknown_ids.push(item.data.target_id);
            results.push({ index, status: 'unknown' });
            break;
          case 'invalid':
            skipped++;
            results.push({ index, status: 'skipped' });
            invalid_items.push({ index, error: outcome.error });
            break;
          case 'error':
            results.push({ index, status: 'error' });
            errored_items.push({ index, error: outcome.error });
            break;
        }
      }
    });

    try {
      queueBatch();
    } catch (e) {
      res.status(500).json({ error: (e as Error).message ?? 'bulk queue failed' });
      return;
    }

    res.json({
      ok: true,
      queued,
      skipped,
      unknown_ids,
      results,   // per request row: {index, status: queued|skipped|unknown|error}
      ...(invalid_items.length > 0 ? { invalid_items } : {}),
      ...(errored_items.length > 0 ? { errored_items } : {}),
    });
  });

  return r;
}
