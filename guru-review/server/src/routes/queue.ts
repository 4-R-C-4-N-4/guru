import { Router } from 'express';
import type Database from 'better-sqlite3';
import type { PreparedStmts } from '../db.js';

interface QueueRow {
  action_id: number;
  client_action_id: string;
  target_table: 'staged_tags' | 'staged_edges';
  action: string;
  reassign_to: string | null;
  reclassify_to: string | null;
  reviewer: string;
  created_at: string;
  target_id: number;
  tag_chunk_id: string | null;
  tag_concept_id: string | null;
  tag_score: number | null;
  tag_is_new_concept: number | null;
  tag_section_label: string | null;
  tag_tradition_id: string | null;
  edge_source_chunk: string | null;
  edge_target_chunk: string | null;
  edge_type: string | null;
  edge_confidence: number | null;
  edge_a_section_label: string | null;
  edge_a_tradition_id: string | null;
  edge_b_section_label: string | null;
  edge_b_tradition_id: string | null;
}

function shapeQueueAction(r: QueueRow): unknown {
  const header = {
    action_id: r.action_id,
    client_action_id: r.client_action_id,
    target_table: r.target_table,
    action: r.action,
    reassign_to: r.reassign_to,
    reclassify_to: r.reclassify_to,
    reviewer: r.reviewer,
    created_at: r.created_at,
    target_id: r.target_id,
  };
  if (r.target_table === 'staged_tags') {
    return {
      ...header,
      context: {
        kind: 'tag' as const,
        chunk_id: r.tag_chunk_id,
        concept_id: r.tag_concept_id,
        score: r.tag_score,
        is_new_concept: r.tag_is_new_concept === 1,
        section_label: r.tag_section_label,
        tradition_id: r.tag_tradition_id,
      },
    };
  }
  return {
    ...header,
    context: {
      kind: 'edge' as const,
      source_chunk: r.edge_source_chunk,
      target_chunk: r.edge_target_chunk,
      edge_type: r.edge_type,
      confidence: r.edge_confidence,
      a: {
        section_label: r.edge_a_section_label,
        tradition_id: r.edge_a_tradition_id,
      },
      b: {
        section_label: r.edge_b_section_label,
        tradition_id: r.edge_b_tradition_id,
      },
    },
  };
}

export function queueRouter(_ro: Database.Database, stmts: PreparedStmts): Router {
  const r = Router();

  r.get('/queue', (_req, res) => {
    const rows = stmts.selectQueueWithContext.all() as QueueRow[];
    res.json({ actions: rows.map(shapeQueueAction) });
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
