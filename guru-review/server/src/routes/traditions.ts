import { Router } from 'express';
import type Database from 'better-sqlite3';

export function traditionsRouter(ro: Database.Database): Router {
  const r = Router();

  const list = ro.prepare(`
    SELECT DISTINCT tradition_id AS id
    FROM nodes
    WHERE type='chunk' AND tradition_id IS NOT NULL
    ORDER BY tradition_id
  `);

  r.get('/traditions', (_req, res) => {
    res.json(list.all());
  });

  return r;
}
