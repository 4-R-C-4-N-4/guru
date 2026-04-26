import Database from 'better-sqlite3';
import type { Config } from './config.js';
import { applySchema } from './schema.js';

export interface DbHandles {
  ro: Database.Database;
  rw: Database.Database;
  stmts: PreparedStmts;
}

export interface PreparedStmts {
  // writes (review_actions only)
  insertReviewAction: Database.Statement;
  deleteUnappliedAction: Database.Statement;
  selectStagedTagExists: Database.Statement;
  selectStagedEdgeExists: Database.Statement;

  // apply transaction (rw side — touch staged_tags / staged_edges / edges / nodes)
  selectQueuedActions: Database.Statement;
  selectStagedTag: Database.Statement;
  selectStagedEdge: Database.Statement;
  ensureConceptNode: Database.Statement;
  upsertEdge: Database.Statement;          // generic — type passed at runtime
  deleteEdge: Database.Statement;          // generic — type passed at runtime
  updateStagedTagStatus: Database.Statement;
  updateStagedTagConcept: Database.Statement;
  insertReassignedTag: Database.Statement;
  updateStagedEdgeStatus: Database.Statement;
  updateStagedEdgeStatusType: Database.Statement;
  markActionApplied: Database.Statement;

  // reads (queue + apply preview)
  selectQueueWithContext: Database.Statement;
  countQueuedByAction: Database.Statement;
}

export function openDb(cfg: Config): DbHandles {
  const ro = new Database(cfg.db_path, { readonly: true, fileMustExist: true });
  ro.pragma('busy_timeout = 5000');

  const rw = new Database(cfg.db_path);
  rw.pragma('journal_mode = WAL');
  rw.pragma('foreign_keys = ON');
  rw.pragma('busy_timeout = 5000');

  applySchema(rw);

  const stmts = prepareStatements(ro, rw);
  return { ro, rw, stmts };
}

function prepareStatements(ro: Database.Database, rw: Database.Database): PreparedStmts {
  return {
    insertReviewAction: rw.prepare(`
      INSERT INTO review_actions
        (target_id, target_table, action, reassign_to, reclassify_to,
         reviewer, client_action_id)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `),

    deleteUnappliedAction: rw.prepare(`
      DELETE FROM review_actions
      WHERE client_action_id = ? AND applied_at IS NULL
    `),

    selectStagedTagExists: ro.prepare(`
      SELECT id FROM staged_tags WHERE id = ?
    `),

    selectStagedEdgeExists: ro.prepare(`
      SELECT id FROM staged_edges WHERE id = ?
    `),

    selectQueuedActions: rw.prepare(`
      SELECT id, target_id, target_table, action, reassign_to, reclassify_to,
             reviewer, client_action_id, created_at
      FROM review_actions
      WHERE applied_at IS NULL
      ORDER BY id ASC
    `),

    selectStagedTag: rw.prepare(`
      SELECT id, chunk_id, concept_id, score, justification,
             is_new_concept, new_concept_def, status,
             model, prompt_version
      FROM staged_tags
      WHERE id = ?
    `),

    selectStagedEdge: rw.prepare(`
      SELECT id, source_chunk, target_chunk, edge_type, confidence,
             justification, status, tier
      FROM staged_edges
      WHERE id = ?
    `),

    ensureConceptNode: rw.prepare(`
      INSERT INTO nodes(id, type, label, definition)
      VALUES(?, 'concept', ?, ?)
      ON CONFLICT(id) DO UPDATE SET
        definition = COALESCE(nodes.definition, excluded.definition)
    `),

    // Generic upsert — type is passed at runtime so the same statement
    // serves EXPRESSES (staged_tags accept) and PARALLELS/CONTRASTS
    // (staged_edges accept + reclassify).
    upsertEdge: rw.prepare(`
      INSERT INTO edges(source_id, target_id, type, tier, justification)
      VALUES(?, ?, ?, ?, ?)
      ON CONFLICT(source_id, target_id, type) DO UPDATE SET
        tier=excluded.tier, justification=excluded.justification
    `),

    // Generic delete — type passed at runtime. Used by reject/reassign
    // (staged_tags) and reject/reclassify-old-type (staged_edges) to
    // retract auto-promoted edges. DELETE on a non-existent row is a
    // no-op, so callers don't need to check.
    deleteEdge: rw.prepare(`
      DELETE FROM edges
      WHERE source_id = ? AND target_id = ? AND type = ?
    `),

    updateStagedTagStatus: rw.prepare(`
      UPDATE staged_tags SET status=?, reviewed_by=?, reviewed_at=? WHERE id=?
    `),

    updateStagedTagConcept: rw.prepare(`
      UPDATE staged_tags SET concept_id=? WHERE id=?
    `),

    insertReassignedTag: rw.prepare(`
      INSERT INTO staged_tags(chunk_id, concept_id, score, justification,
                              is_new_concept, model, prompt_version)
      VALUES(?, ?, ?, ?, 0, ?, ?)
    `),

    updateStagedEdgeStatus: rw.prepare(`
      UPDATE staged_edges SET status=?, tier=?, reviewed_by=?, reviewed_at=? WHERE id=?
    `),

    // Used by reclassify — sets new edge_type alongside status/tier.
    updateStagedEdgeStatusType: rw.prepare(`
      UPDATE staged_edges SET status=?, edge_type=?, tier=?,
        reviewed_by=?, reviewed_at=? WHERE id=?
    `),

    markActionApplied: rw.prepare(`
      UPDATE review_actions SET applied_at = strftime('%Y-%m-%dT%H:%M:%SZ','now'), error = ?
      WHERE id = ?
    `),

    selectQueueWithContext: ro.prepare(`
      SELECT
        ra.id              AS action_id,
        ra.client_action_id,
        ra.target_table,
        ra.action,
        ra.reassign_to,
        ra.reclassify_to,
        ra.reviewer,
        ra.created_at,
        st.id              AS target_id,
        st.chunk_id,
        st.concept_id,
        st.score,
        st.is_new_concept,
        n.label            AS section_label,
        n.tradition_id
      FROM review_actions ra
      JOIN staged_tags st ON st.id = ra.target_id AND ra.target_table = 'staged_tags'
      JOIN nodes n ON n.id = st.chunk_id
      WHERE ra.applied_at IS NULL
      ORDER BY ra.id DESC
    `),

    countQueuedByAction: ro.prepare(`
      SELECT target_table, action, COUNT(*) AS n
      FROM review_actions
      WHERE applied_at IS NULL
      GROUP BY target_table, action
    `),
  };
}
