import { Router } from 'express';
import type Database from 'better-sqlite3';
import { z } from 'zod';
import { ChunkBodyCache } from '../chunkBody.js';
import { CountCache } from '../cache.js';

const QuerySchema = z.object({
  tradition: z.string().optional(),
  text: z.string().optional(),
  concept: z.string().optional(),
  min_score: z.coerce.number().int().min(0).max(3).default(1),
  cursor: z.string().optional(),
  limit: z.coerce.number().int().min(1).max(20).default(8),
});

interface CursorShape {
  trad: string;
  chunk: string;
}

function decodeCursor(s: string | undefined): CursorShape | null {
  if (!s) return null;
  try {
    const decoded = Buffer.from(s, 'base64').toString('utf8');
    const arr = JSON.parse(decoded) as [string, string];
    if (Array.isArray(arr) && arr.length === 2) return { trad: arr[0], chunk: arr[1] };
    return null;
  } catch {
    return null;
  }
}

function encodeCursor(c: CursorShape): string {
  return Buffer.from(JSON.stringify([c.trad, c.chunk])).toString('base64');
}

interface OuterRow {
  chunk_id: string;
  tradition_id: string;
  section_label: string;
  text_id: string | null;
}

interface InnerRow {
  target_id: number;
  chunk_id: string;
  concept_id: string;
  score: number;
  justification: string | null;
  is_new_concept: number;
  new_concept_def: string | null;
}

interface ConceptInfo {
  label: string;
  definition: string | null;
}

export function chunksRouter(ro: Database.Database, body: ChunkBodyCache): Router {
  const r = Router();
  const counts = new CountCache(30_000);

  // Concept lookup is small (~44 rows) — load once and refresh per-request via a single query.
  const conceptList = ro.prepare(
    "SELECT id, label, definition FROM nodes WHERE type='concept'",
  );

  r.get('/chunks', (req, res) => {
    const parsed = QuerySchema.safeParse(req.query);
    if (!parsed.success) {
      res.status(400).json({ error: parsed.error.flatten() });
      return;
    }
    const { tradition, text, concept, min_score, cursor, limit } = parsed.data;
    const cursorObj = decodeCursor(cursor);

    // Build outer query (chunks page) ----------------------------------
    const outerWhere: string[] = [
      "st.status = 'pending'",
      'st.score >= ?',
      "NOT EXISTS (SELECT 1 FROM review_actions ra WHERE ra.target_id = st.id AND ra.target_table = 'staged_tags' AND ra.applied_at IS NULL)",
    ];
    const outerParams: unknown[] = [min_score];

    if (tradition) {
      outerWhere.push('n.tradition_id = ?');
      outerParams.push(tradition);
    }
    if (text) {
      outerWhere.push("json_extract(n.metadata_json, '$.text_id') = ?");
      outerParams.push(text);
    }
    if (concept) {
      outerWhere.push('st.concept_id = ?');
      outerParams.push(concept);
    }
    if (cursorObj) {
      outerWhere.push('(n.tradition_id, n.id) > (?, ?)');
      outerParams.push(cursorObj.trad, cursorObj.chunk);
    }

    const outerSql = `
      SELECT DISTINCT
        n.id            AS chunk_id,
        n.tradition_id  AS tradition_id,
        n.label         AS section_label,
        json_extract(n.metadata_json, '$.text_id') AS text_id
      FROM nodes n
      JOIN staged_tags st ON st.chunk_id = n.id
      WHERE ${outerWhere.join(' AND ')}
      ORDER BY n.tradition_id ASC, n.id ASC
      LIMIT ?
    `;
    outerParams.push(limit);
    const outerRows = ro.prepare(outerSql).all(...outerParams) as OuterRow[];

    // Build inner query (tags for those chunks) ------------------------
    const chunks: ReturnType<typeof buildChunk>[] = [];
    if (outerRows.length > 0) {
      const placeholders = outerRows.map(() => '?').join(',');
      const innerSql = `
        SELECT id AS target_id, chunk_id, concept_id, score, justification,
               is_new_concept, new_concept_def
        FROM staged_tags
        WHERE chunk_id IN (${placeholders})
          AND status = 'pending'
          AND score >= ?
          AND NOT EXISTS (
              SELECT 1 FROM review_actions ra
              WHERE ra.target_id = staged_tags.id
                AND ra.target_table = 'staged_tags'
                AND ra.applied_at IS NULL
          )
        ORDER BY chunk_id, score DESC, id ASC
      `;
      const innerParams = [...outerRows.map((r) => r.chunk_id), min_score];
      const innerRows = ro.prepare(innerSql).all(...innerParams) as InnerRow[];

      const concepts = new Map<string, ConceptInfo>();
      for (const c of conceptList.all() as { id: string; label: string; definition: string | null }[]) {
        // map by bare concept_id (id minus 'concept.' prefix)
        concepts.set(c.id.startsWith('concept.') ? c.id.slice(8) : c.id, {
          label: c.label,
          definition: c.definition,
        });
      }

      const tagsByChunk = new Map<string, InnerRow[]>();
      for (const t of innerRows) {
        const arr = tagsByChunk.get(t.chunk_id) ?? [];
        arr.push(t);
        tagsByChunk.set(t.chunk_id, arr);
      }

      for (const c of outerRows) {
        const tags = tagsByChunk.get(c.chunk_id) ?? [];
        chunks.push(buildChunk(c, tags, concepts, body));
      }
    }

    // Counts (cached) --------------------------------------------------
    const countKey = CountCache.keyFor({ tradition, text, concept, min_score });
    let cached = counts.get<{ pending_chunks_in_filter: number; pending_tags_in_filter: number }>(countKey);
    if (!cached) {
      cached = computeCounts(ro, { tradition, text, concept, min_score });
      counts.set(countKey, cached);
    }

    const last = outerRows[outerRows.length - 1];
    const next_cursor =
      outerRows.length === limit && last ? encodeCursor({ trad: last.tradition_id, chunk: last.chunk_id }) : null;

    res.json({
      chunks,
      next_cursor,
      pending_chunks_in_filter: cached.pending_chunks_in_filter,
      pending_tags_in_filter: cached.pending_tags_in_filter,
    });
  });

  return r;
}

function buildChunk(
  outer: OuterRow,
  tags: InnerRow[],
  concepts: Map<string, ConceptInfo>,
  body: ChunkBodyCache,
): {
  chunk_id: string;
  tradition_id: string;
  section_label: string;
  text_id: string | null;
  body: string;
  pending_tags: Array<{
    target_id: number;
    concept_id: string;
    concept_label: string;
    concept_def: string;
    score: number;
    justification: string;
    is_new_concept: boolean;
    new_concept_def: string | null;
  }>;
} {
  return {
    chunk_id: outer.chunk_id,
    tradition_id: outer.tradition_id,
    section_label: outer.section_label,
    text_id: outer.text_id,
    body: body.load(outer.chunk_id).body,
    pending_tags: tags.map((t) => {
      const ci = concepts.get(t.concept_id);
      return {
        target_id: t.target_id,
        concept_id: t.concept_id,
        concept_label: ci?.label ?? t.concept_id,
        concept_def: ci?.definition ?? '',
        score: t.score,
        justification: t.justification ?? '',
        is_new_concept: t.is_new_concept === 1,
        new_concept_def: t.new_concept_def,
      };
    }),
  };
}

function computeCounts(
  ro: Database.Database,
  filters: { tradition?: string; text?: string; concept?: string; min_score: number },
): { pending_chunks_in_filter: number; pending_tags_in_filter: number } {
  const where: string[] = [
    "st.status = 'pending'",
    'st.score >= ?',
    "NOT EXISTS (SELECT 1 FROM review_actions ra WHERE ra.target_id = st.id AND ra.target_table = 'staged_tags' AND ra.applied_at IS NULL)",
  ];
  const params: unknown[] = [filters.min_score];

  if (filters.tradition) {
    where.push('n.tradition_id = ?');
    params.push(filters.tradition);
  }
  if (filters.text) {
    where.push("json_extract(n.metadata_json, '$.text_id') = ?");
    params.push(filters.text);
  }
  if (filters.concept) {
    where.push('st.concept_id = ?');
    params.push(filters.concept);
  }

  const tagsRow = ro
    .prepare(
      `SELECT COUNT(*) AS n
       FROM staged_tags st
       JOIN nodes n ON n.id = st.chunk_id
       WHERE ${where.join(' AND ')}`,
    )
    .get(...params) as { n: number };

  const chunksRow = ro
    .prepare(
      `SELECT COUNT(DISTINCT st.chunk_id) AS n
       FROM staged_tags st
       JOIN nodes n ON n.id = st.chunk_id
       WHERE ${where.join(' AND ')}`,
    )
    .get(...params) as { n: number };

  return { pending_chunks_in_filter: chunksRow.n, pending_tags_in_filter: tagsRow.n };
}
