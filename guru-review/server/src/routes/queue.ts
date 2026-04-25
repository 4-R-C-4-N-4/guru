import { Router } from 'express';
import type Database from 'better-sqlite3';
import type { PreparedStmts } from '../db.js';

export function queueRouter(_ro: Database.Database, stmts: PreparedStmts): Router {
  const r = Router();

  r.get('/queue', (_req, res) => {
    const rows = stmts.selectQueueWithContext.all();
    res.json({ actions: rows });
  });

  r.delete('/queue/:client_action_id', (req, res) => {
    const id = req.params.client_action_id;
    if (!id || id.length === 0) {
      res.status(400).json({ error: 'client_action_id required' });
      return;
    }
    const result = stmts.deleteUnappliedAction.run(id);
    if (result.changes === 0) {
      // Either not found OR already applied. Distinguish so the UI can
      // show a meaningful message.
      res.status(404).json({
        error: 'no unapplied action with that client_action_id (already applied or never queued)',
      });
      return;
    }
    res.json({ ok: true, deleted: result.changes });
  });

  return r;
}
