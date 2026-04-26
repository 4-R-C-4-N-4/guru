// Parity-harness web runner — applies the decision_sequence.json fixture
// to a shadow DB via the production apply transaction. Lives inside the
// server tree so module resolution finds better-sqlite3 et al. naturally.
//
// Invoked from tests/parity/orchestrator.sh:
//   node guru-review/server/dist/parity/web_runner.js --db <shadow.db> --fixture <json>

import { argv } from 'node:process';
import { readFileSync } from 'node:fs';
import Database from 'better-sqlite3';
import { buildApply } from '../apply.js';
import { applySchema } from '../schema.js';

interface Action {
  target_id: number;
  action: 'accept' | 'reject' | 'skip' | 'reassign';
  reassign_to?: string;
  client_action_id: string;
}

function parseArgs(): { db: string; fixture: string } {
  const args = argv.slice(2);
  const out = { db: '', fixture: '' };
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--db') out.db = args[++i];
    else if (args[i] === '--fixture') out.fixture = args[++i];
  }
  if (!out.db || !out.fixture) throw new Error('usage: web_runner --db <path> --fixture <path>');
  return out;
}

const { db: dbPath, fixture: fixturePath } = parseArgs();
const fixture = JSON.parse(readFileSync(fixturePath, 'utf8')) as {
  reviewer: string;
  actions: Action[];
};

const rw = new Database(dbPath);
rw.pragma('journal_mode = WAL');
rw.pragma('foreign_keys = ON');
applySchema(rw);

const stmts = {
  insertReviewAction: rw.prepare(
    'INSERT INTO review_actions(target_id, action, reassign_to, reviewer, client_action_id) VALUES (?, ?, ?, ?, ?)',
  ),
  deleteUnappliedAction: rw.prepare(
    'DELETE FROM review_actions WHERE client_action_id = ? AND applied_at IS NULL',
  ),
  selectStagedTagExists: rw.prepare('SELECT id FROM staged_tags WHERE id = ?'),
  selectQueuedActions: rw.prepare(
    'SELECT id, target_id, action, reassign_to, reviewer, client_action_id, created_at FROM review_actions WHERE applied_at IS NULL ORDER BY id ASC',
  ),
  selectStagedTag: rw.prepare(
    'SELECT id, chunk_id, concept_id, score, justification, is_new_concept, new_concept_def, status, model, prompt_version FROM staged_tags WHERE id = ?',
  ),
  ensureConceptNode: rw.prepare(
    "INSERT INTO nodes(id, type, label, definition) VALUES(?, 'concept', ?, ?) ON CONFLICT(id) DO UPDATE SET definition = COALESCE(nodes.definition, excluded.definition)",
  ),
  insertOrUpdateEdge: rw.prepare(
    "INSERT INTO edges(source_id, target_id, type, tier, justification) VALUES(?, ?, 'EXPRESSES', ?, ?) ON CONFLICT(source_id, target_id, type) DO UPDATE SET tier=excluded.tier, justification=excluded.justification",
  ),
  deleteExpressesEdge: rw.prepare(
    "DELETE FROM edges WHERE source_id = ? AND target_id = ? AND type = 'EXPRESSES'",
  ),
  updateStagedTagStatus: rw.prepare(
    'UPDATE staged_tags SET status=?, reviewed_by=?, reviewed_at=? WHERE id=?',
  ),
  updateStagedTagConcept: rw.prepare('UPDATE staged_tags SET concept_id=? WHERE id=?'),
  insertReassignedTag: rw.prepare(
    'INSERT INTO staged_tags(chunk_id, concept_id, score, justification, is_new_concept, model, prompt_version) VALUES(?, ?, ?, ?, 0, ?, ?)',
  ),
  markActionApplied: rw.prepare(
    "UPDATE review_actions SET applied_at = strftime('%Y-%m-%dT%H:%M:%SZ','now'), error = ? WHERE id = ?",
  ),
  selectQueueWithContext: rw.prepare('SELECT 1'),
  countQueuedByAction: rw.prepare('SELECT 1'),
};

for (const a of fixture.actions) {
  stmts.insertReviewAction.run(
    a.target_id,
    a.action,
    a.action === 'reassign' ? a.reassign_to ?? null : null,
    fixture.reviewer,
    a.client_action_id,
  );
}

const apply = buildApply(rw, stmts as never);
const result = apply();
console.log(JSON.stringify(result, null, 2));
rw.close();
