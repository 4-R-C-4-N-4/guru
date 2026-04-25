import { Router } from 'express';
import type Database from 'better-sqlite3';
import { z } from 'zod';

const QuerySchema = z.object({ tradition: z.string().min(1) });

export function textsRouter(ro: Database.Database): Router {
  const r = Router();

  const list = ro.prepare(`
    SELECT DISTINCT json_extract(metadata_json, '$.text_id') AS id
    FROM nodes
    WHERE type='chunk' AND tradition_id = ?
      AND json_extract(metadata_json, '$.text_id') IS NOT NULL
    ORDER BY id
  `);

  r.get('/texts', (req, res) => {
    const parsed = QuerySchema.safeParse(req.query);
    if (!parsed.success) {
      res.status(400).json({ error: 'tradition query param required' });
      return;
    }
    res.json(list.all(parsed.data.tradition));
  });

  return r;
}
