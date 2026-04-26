import { Router } from 'express';
import type Database from 'better-sqlite3';
import { z } from 'zod';
import { ChunkBodyCache } from '../chunkBody.js';
import { CountCache } from '../cache.js';
import type { PreparedStmts } from '../db.js';

// ── filter / paging schema ────────────────────────────────────────────

const EdgeTypeFilter = z.enum(['PARALLELS', 'CONTRASTS']);
const QuerySchema = z.object({
  edge_type: EdgeTypeFilter.optional(),
  min_confidence: z.coerce.number().min(0).max(1).default(0),
  tradition_a: z.string().optional(),
  tradition_b: z.string().optional(),
  cursor: z.coerce.number().int().min(0).optional(),
  limit: z.coerce.number().int().min(1).max(20).default(8),
});

// ── action schema (POST /api/edges/:id/action) ────────────────────────

const ReclassifyTo = z.enum(['PARALLELS', 'CONTRASTS', 'surface_only', 'unrelated']);
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

interface EdgeRow {
  id: number;
  source_chunk: string;
  target_chunk: string;
  edge_type: 'PARALLELS' | 'CONTRASTS' | 'surface_only' | 'unrelated';
  confidence: number;
  justification: string | null;
  tier: string;
  source_tradition: string;
  source_label: string;
  source_text_id: string | null;
  target_tradition: string;
  target_label: string;
  target_text_id: string | null;
}

interface EnrichedChunk {
  chunk_id: string;
  tradition_id: string;
  section_label: string;
  text_id: string | null;
  body: string;
}

interface EnrichedEdge {
  target_id: number;
  edge_type: string;
  confidence: number;
  justification: string;
  tier: string;
  a: EnrichedChunk;
  b: EnrichedChunk;
}

function enrich(row: EdgeRow, body: ChunkBodyCache): EnrichedEdge {
  return {
    target_id: row.id,
    edge_type: row.edge_type,
    confidence: row.confidence,
    justification: row.justification ?? '',
    tier: row.tier,
    a: {
      chunk_id: row.source_chunk,
      tradition_id: row.source_tradition,
      section_label: row.source_label,
      text_id: row.source_text_id,
      body: body.load(row.source_chunk).body,
    },
    b: {
      chunk_id: row.target_chunk,
      tradition_id: row.target_tradition,
      section_label: row.target_label,
      text_id: row.target_text_id,
      body: body.load(row.target_chunk).body,
    },
  };
}

// ── filter SQL builder (shared by list + count queries) ───────────────

interface Filters {
  edge_type?: 'PARALLELS' | 'CONTRASTS';
  min_confidence: number;
  tradition_a?: string;
  tradition_b?: string;
}

function buildFilterClause(f: Filters): { where: string[]; params: unknown[] } {
  const where: string[] = [
    "se.status = 'pending'",
    'se.confidence >= ?',
    "NOT EXISTS (SELECT 1 FROM review_actions ra WHERE ra.target_id = se.id AND ra.target_table = 'staged_edges' AND ra.applied_at IS NULL)",
  ];
  const params: unknown[] = [f.min_confidence];

  if (f.edge_type) {
    where.push('se.edge_type = ?');
    params.push(f.edge_type);
  }
  // Tradition filters are symmetric: tradition_a and tradition_b can each
  // match either side of the edge. Mirrors review_edges.py.
  if (f.tradition_a && f.tradition_b) {
    where.push(
      '((na.tradition_id = ? AND nb.tradition_id = ?) OR (na.tradition_id = ? AND nb.tradition_id = ?))',
    );
    params.push(f.tradition_a, f.tradition_b, f.tradition_b, f.tradition_a);
  } else if (f.tradition_a) {
    where.push('(na.tradition_id = ? OR nb.tradition_id = ?)');
    params.push(f.tradition_a, f.tradition_a);
  } else if (f.tradition_b) {
    where.push('(na.tradition_id = ? OR nb.tradition_id = ?)');
    params.push(f.tradition_b, f.tradition_b);
  }

  return { where, params };
}

// ── router ────────────────────────────────────────────────────────────

export function edgesRouter(
  ro: Database.Database,
  stmts: PreparedStmts,
  body: ChunkBodyCache,
): Router {
  const r = Router();
  const counts = new CountCache(30_000);

  const SELECT_CORE = `
    SELECT
      se.id,
      se.source_chunk, se.target_chunk,
      se.edge_type, se.confidence, se.justification, se.tier,
      na.tradition_id AS source_tradition,
      na.label        AS source_label,
      json_extract(na.metadata_json, '$.text_id') AS source_text_id,
      nb.tradition_id AS target_tradition,
      nb.label        AS target_label,
      json_extract(nb.metadata_json, '$.text_id') AS target_text_id
    FROM staged_edges se
    JOIN nodes na ON na.id = se.source_chunk
    JOIN nodes nb ON nb.id = se.target_chunk
  `;

  // GET /api/edges --------------------------------------------------------
  r.get('/edges', (req, res) => {
    const parsed = QuerySchema.safeParse(req.query);
    if (!parsed.success) {
      res.status(400).json({ error: parsed.error.flatten() });
      return;
    }
    const { edge_type, min_confidence, tradition_a, tradition_b, cursor, limit } = parsed.data;

    const { where, params } = buildFilterClause({ edge_type, min_confidence, tradition_a, tradition_b });
    if (cursor !== undefined) {
      where.push('se.id > ?');
      params.push(cursor);
    }

    const sql = `${SELECT_CORE} WHERE ${where.join(' AND ')} ORDER BY se.id ASC LIMIT ?`;
    params.push(limit);

    const rows = ro.prepare(sql).all(...params) as EdgeRow[];
    const edges = rows.map((row) => enrich(row, body));

    const countKey = CountCache.keyFor({ edge_type, min_confidence, tradition_a, tradition_b });
    let cached = counts.get<{ pending_edges_in_filter: number }>(countKey);
    if (!cached) {
      const cf = buildFilterClause({ edge_type, min_confidence, tradition_a, tradition_b });
      const countRow = ro
        .prepare(
          `SELECT COUNT(*) AS n
           FROM staged_edges se
           JOIN nodes na ON na.id = se.source_chunk
           JOIN nodes nb ON nb.id = se.target_chunk
           WHERE ${cf.where.join(' AND ')}`,
        )
        .get(...cf.params) as { n: number };
      cached = { pending_edges_in_filter: countRow.n };
      counts.set(countKey, cached);
    }

    const last = rows[rows.length - 1];
    const next_cursor = rows.length === limit && last ? last.id : null;

    res.json({
      edges,
      next_cursor,
      pending_edges_in_filter: cached.pending_edges_in_filter,
    });
  });

  // GET /api/edges/:id ----------------------------------------------------
  r.get('/edges/:id', (req, res) => {
    const id = Number.parseInt(req.params.id, 10);
    if (!Number.isFinite(id) || id <= 0) {
      res.status(400).json({ error: 'invalid id' });
      return;
    }
    const row = ro.prepare(`${SELECT_CORE} WHERE se.id = ?`).get(id) as EdgeRow | undefined;
    if (!row) {
      res.status(404).json({ error: `staged_edge ${id} not found` });
      return;
    }
    res.json({ edge: enrich(row, body) });
  });

  // POST /api/edges/:id/action -------------------------------------------
  r.post('/edges/:id/action', (req, res) => {
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

    const exists = stmts.selectStagedEdgeExists.get(id);
    if (!exists) {
      res.status(404).json({ error: `staged_edge ${id} not found` });
      return;
    }

    try {
      stmts.insertReviewAction.run(
        id,
        'staged_edges',
        action,
        null,             // reassign_to — staged_edges branch never sets this
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
