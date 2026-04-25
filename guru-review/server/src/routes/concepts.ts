import { Router } from 'express';
import type Database from 'better-sqlite3';

export function conceptsRouter(ro: Database.Database): Router {
  const r = Router();

  // Returns both node_id (concept.<x>) and bare concept_id so the
  // reassign picker can send the bare form back per design §4.5.
  const list = ro.prepare(`
    SELECT id AS node_id,
           substr(id, 9) AS concept_id,
           label,
           definition
    FROM nodes
    WHERE type='concept'
    ORDER BY label
  `);

  r.get('/concepts', (_req, res) => {
    res.json(list.all());
  });

  return r;
}
