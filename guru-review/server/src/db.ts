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

  // apply transaction (rw side — touch staged_tags + edges + nodes)
  selectQueuedActions: Database.Statement;
  selectStagedTag: Database.Statement;
  ensureConceptNode: Database.Statement;
  insertOrUpdateEdge: Database.Statement;
  updateStagedTagStatus: Database.Statement;
  updateStagedTagConcept: Database.Statement;
  insertReassignedTag: Database.Statement;
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
        (staged_tag_id, action, reassign_to, reviewer, client_action_id)
      VALUES (?, ?, ?, ?, ?)
    `),

    deleteUnappliedAction: rw.prepare(`
      DELETE FROM review_actions
      WHERE client_action_id = ? AND applied_at IS NULL
    `),

    selectStagedTagExists: ro.prepare(`
      SELECT id FROM staged_tags WHERE id = ?
    `),

    selectQueuedActions: rw.prepare(`
      SELECT id, staged_tag_id, action, reassign_to, reviewer, client_action_id, created_at
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

    ensureConceptNode: rw.prepare(`
      INSERT INTO nodes(id, type, label, definition)
      VALUES(?, 'concept', ?, ?)
      ON CONFLICT(id) DO UPDATE SET
        definition = COALESCE(nodes.definition, excluded.definition)
    `),

    insertOrUpdateEdge: rw.prepare(`
      INSERT INTO edges(source_id, target_id, type, tier, justification)
      VALUES(?, ?, 'EXPRESSES', ?, ?)
      ON CONFLICT(source_id, target_id, type) DO UPDATE SET
        tier=excluded.tier, justification=excluded.justification
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

    markActionApplied: rw.prepare(`
      UPDATE review_actions SET applied_at = strftime('%Y-%m-%dT%H:%M:%SZ','now'), error = ?
      WHERE id = ?
    `),

    selectQueueWithContext: ro.prepare(`
      SELECT
        ra.id              AS action_id,
        ra.client_action_id,
        ra.action,
        ra.reassign_to,
        ra.reviewer,
        ra.created_at,
        st.id              AS staged_tag_id,
        st.chunk_id,
        st.concept_id,
        st.score,
        st.is_new_concept,
        n.label            AS section_label,
        n.tradition_id
      FROM review_actions ra
      JOIN staged_tags st ON st.id = ra.staged_tag_id
      JOIN nodes n ON n.id = st.chunk_id
      WHERE ra.applied_at IS NULL
      ORDER BY ra.id DESC
    `),

    countQueuedByAction: ro.prepare(`
      SELECT action, COUNT(*) AS n
      FROM review_actions
      WHERE applied_at IS NULL
      GROUP BY action
    `),
  };
}
