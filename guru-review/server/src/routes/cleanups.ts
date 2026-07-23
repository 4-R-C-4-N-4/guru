import { Router } from 'express';
import type Database from 'better-sqlite3';
import { z } from 'zod';
import { CountCache } from '../cache.js';
import type { PreparedStmts } from '../db.js';

// Third review queue (todo:b44966d0): model-proposed rewrites of malformed
// chunk bodies (hard-wrapped prose), reviewed as before/after diffs.
// Mirrors edges.ts one-to-one; the deck-facing differences are that a
// cleanup is self-contained (original vs proposed body on the same row —
// no ChunkBodyCache needed) and reclassify has exactly one target,
// 'apparatus_drop' (the "this whole chunk is editorial apparatus, route to
// todo:50438e23" escape hatch).

// ── filter / paging schema ────────────────────────────────────────────

const QuerySchema = z.object({
  tradition: z.string().optional(),
  text: z.string().optional(),
  min_signal: z.coerce.number().min(0).max(1).default(0),
  cursor: z.coerce.number().int().min(0).optional(),
  limit: z.coerce.number().int().min(1).max(20).default(8),
});

// ── action schema (POST /api/cleanups/:id/action) ─────────────────────

const ReclassifyTo = z.enum(['apparatus_drop']);
const ActionSchema = z.discriminatedUnion('action', [
  z.object({
    action: z.literal('accept'),
    reclassify_to: z.undefined().or(z.null()),
    client_action_id: z.string().min(1),
    reviewer: z.string().min(1),
  }),
  z.object({
    action: z.literal('reject'),
    reclassify_to: z.undefined().or(z.null()),
    client_action_id: z.string().min(1),
    reviewer: z.string().min(1),
  }),
  z.object({
    action: z.literal('skip'),
    reclassify_to: z.undefined().or(z.null()),
    client_action_id: z.string().min(1),
    reviewer: z.string().min(1),
  }),
  z.object({
    action: z.literal('reclassify'),
    reclassify_to: ReclassifyTo,
    client_action_id: z.string().min(1),
    reviewer: z.string().min(1),
  }),
]);

// ── row shapes ────────────────────────────────────────────────────────

interface CleanupRow {
  id: number;
  chunk_id: string;
  original_body: string;
  proposed_body: string;
  justification: string | null;
  signal_score: number;
  words_preserved: number;
  model: string | null;
  tradition_id: string;
  section_label: string;
  text_id: string | null;
}

function shape(row: CleanupRow) {
  return {
    target_id: row.id,
    chunk_id: row.chunk_id,
    tradition_id: row.tradition_id,
    section_label: row.section_label,
    text_id: row.text_id,
    original_body: row.original_body,
    proposed_body: row.proposed_body,
    justification: row.justification ?? '',
    signal_score: row.signal_score,
    words_preserved: row.words_preserved === 1,
    model: row.model ?? '',
  };
}

// ── filter SQL builder (shared by list + count queries) ───────────────

interface Filters {
  tradition?: string;
  text?: string;
  min_signal: number;
}

function buildFilterClause(f: Filters): { where: string[]; params: unknown[] } {
  const where: string[] = [
    "sc.status = 'pending'",
    'sc.signal_score >= ?',
    "NOT EXISTS (SELECT 1 FROM review_actions ra WHERE ra.target_id = sc.id AND ra.target_table = 'staged_cleanups' AND ra.applied_at IS NULL)",
  ];
  const params: unknown[] = [f.min_signal];

  if (f.tradition) {
    where.push('n.tradition_id = ?');
    params.push(f.tradition);
  }
  if (f.text) {
    where.push("json_extract(n.metadata_json, '$.text_id') = ?");
    params.push(f.text);
  }
  return { where, params };
}

// ── router ────────────────────────────────────────────────────────────

export function cleanupsRouter(ro: Database.Database, stmts: PreparedStmts): Router {
  const r = Router();
  const counts = new CountCache(30_000);

  const SELECT_CORE = `
    SELECT
      sc.id, sc.chunk_id,
      sc.original_body, sc.proposed_body, sc.justification,
      sc.signal_score, sc.words_preserved, sc.model,
      n.tradition_id,
      n.label AS section_label,
      json_extract(n.metadata_json, '$.text_id') AS text_id
    FROM staged_cleanups sc
    JOIN nodes n ON n.id = sc.chunk_id
  `;

  // GET /api/cleanups -----------------------------------------------------
  r.get('/cleanups', (req, res) => {
    const parsed = QuerySchema.safeParse(req.query);
    if (!parsed.success) {
      res.status(400).json({ error: parsed.error.flatten() });
      return;
    }
    const { tradition, text, min_signal, cursor, limit } = parsed.data;

    const { where, params } = buildFilterClause({ tradition, text, min_signal });
    if (cursor !== undefined) {
      where.push('sc.id > ?');
      params.push(cursor);
    }

    const sql = `${SELECT_CORE} WHERE ${where.join(' AND ')} ORDER BY sc.id ASC LIMIT ?`;
    params.push(limit);

    const rows = ro.prepare(sql).all(...params) as CleanupRow[];
    const cleanups = rows.map(shape);

    const countKey = CountCache.keyFor({ tradition, text, min_signal });
    let cached = counts.get<{ pending_cleanups_in_filter: number }>(countKey);
    if (!cached) {
      const cf = buildFilterClause({ tradition, text, min_signal });
      const countRow = ro
        .prepare(
          `SELECT COUNT(*) AS n
           FROM staged_cleanups sc
           JOIN nodes n ON n.id = sc.chunk_id
           WHERE ${cf.where.join(' AND ')}`,
        )
        .get(...cf.params) as { n: number };
      cached = { pending_cleanups_in_filter: countRow.n };
      counts.set(countKey, cached);
    }

    const last = rows[rows.length - 1];
    const next_cursor = rows.length === limit && last ? last.id : null;

    res.json({
      cleanups,
      next_cursor,
      pending_cleanups_in_filter: cached.pending_cleanups_in_filter,
    });
  });

  // GET /api/cleanups/:id --------------------------------------------------
  r.get('/cleanups/:id', (req, res) => {
    const id = Number.parseInt(req.params.id, 10);
    if (!Number.isFinite(id) || id <= 0) {
      res.status(400).json({ error: 'invalid id' });
      return;
    }
    const row = ro.prepare(`${SELECT_CORE} WHERE sc.id = ?`).get(id) as CleanupRow | undefined;
    if (!row) {
      res.status(404).json({ error: `staged_cleanup ${id} not found` });
      return;
    }
    res.json({ cleanup: shape(row) });
  });

  // POST /api/cleanups/:id/action ------------------------------------------
  r.post('/cleanups/:id/action', (req, res) => {
    const id = Number.parseInt(req.params.id, 10);
    if (!Number.isFinite(id) || id <= 0) {
      res.status(400).json({ error: 'invalid id' });
      return;
    }

    const parsed = ActionSchema.safeParse(req.body);
    if (!parsed.success) {
      res.status(400).json({ error: parsed.error.flatten() });
      return;
    }
    const { action, client_action_id, reviewer } = parsed.data;
    const reclassify_to = action === 'reclassify' ? parsed.data.reclassify_to : null;

    const exists = stmts.selectStagedCleanupExists.get(id);
    if (!exists) {
      res.status(404).json({ error: `staged_cleanup ${id} not found` });
      return;
    }

    try {
      stmts.insertReviewAction.run(
        id,
        'staged_cleanups',
        action,
        null,             // reassign_to — staged_cleanups branch never sets this
        reclassify_to,
        reviewer,
        client_action_id,
      );
      res.json({ ok: true, queued: true });
    } catch (e) {
      const msg = (e as Error).message ?? '';
      if (msg.includes('UNIQUE constraint failed: review_actions.client_action_id')) {
        res.json({ ok: true, queued: false, idempotent: true });
        return;
      }
      if (msg.includes('CHECK constraint')) {
        res.status(400).json({ error: 'action/reclassify_to combination violates DB CHECK' });
        return;
      }
      res.status(500).json({ error: msg });
    }
  });

  return r;
}
