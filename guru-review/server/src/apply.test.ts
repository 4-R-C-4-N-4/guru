// Apply-transaction behaviour that is only observable end to end: what a
// reassign leaves behind (todo:a8bb7213), and what order the queue drains in
// (the premise todo:6c78047b rests on).
//
// These run against the real openDb / buildApply over a temp database rather
// than a hand-rolled mirror of the statements, because both facts under test
// are properties of the actual SQL and its ordering.
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import Database from 'better-sqlite3';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { buildApply } from './apply.js';
import { openDb } from './db.js';

let dir: string;
let handles: ReturnType<typeof openDb>;

// The live tables the review schema expects, with the columns these tests
// touch. review_actions and its indexes come from applySchema (openDb).
const LIVE_SCHEMA = `
CREATE TABLE nodes (
  id TEXT PRIMARY KEY, type TEXT, label TEXT, tradition_id TEXT,
  definition TEXT, metadata_json TEXT);
CREATE TABLE edges (
  source_id TEXT, target_id TEXT, type TEXT, tier TEXT, justification TEXT,
  PRIMARY KEY (source_id, target_id, type));
CREATE TABLE staged_tags (
  id INTEGER PRIMARY KEY AUTOINCREMENT, chunk_id TEXT, concept_id TEXT,
  score INTEGER DEFAULT 2, justification TEXT, is_new_concept INTEGER DEFAULT 0,
  new_concept_def TEXT, status TEXT DEFAULT 'pending', reviewed_by TEXT,
  reviewed_at TEXT, model TEXT, prompt_version TEXT);
CREATE TABLE staged_edges (
  id INTEGER PRIMARY KEY AUTOINCREMENT, source_chunk TEXT, target_chunk TEXT,
  edge_type TEXT, confidence REAL, justification TEXT,
  status TEXT DEFAULT 'pending', tier TEXT, reviewed_by TEXT, reviewed_at TEXT);
CREATE TABLE staged_cleanups (
  id INTEGER PRIMARY KEY, chunk_id TEXT, words_preserved INTEGER,
  signal_score REAL, status TEXT DEFAULT 'pending', reviewed_by TEXT,
  reviewed_at TEXT, cleaned_body TEXT);
CREATE TABLE staged_concepts (id INTEGER PRIMARY KEY);
CREATE TABLE chunk_embeddings (chunk_id TEXT PRIMARY KEY);
CREATE TABLE tagging_progress (chunk_id TEXT PRIMARY KEY);
CREATE TABLE _export_state (id INTEGER PRIMARY KEY);
-- The partial provenance index is what a colliding reassign trips.
CREATE UNIQUE INDEX idx_staged_tags_provenance_unique
  ON staged_tags(chunk_id, concept_id, model, prompt_version)
  WHERE status = 'pending';
`;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), 'guru-apply-'));
  const path = join(dir, 'test.db');
  const seed = new Database(path);
  seed.exec(LIVE_SCHEMA);
  seed.close();
  handles = openDb({ db_path: path } as Parameters<typeof openDb>[0]);
});

afterEach(() => {
  handles.ro.close();
  handles.rw.close();
  rmSync(dir, { recursive: true, force: true });
});

function addTag(chunkId: string, conceptId: string): number {
  const info = handles.rw
    .prepare(
      "INSERT INTO staged_tags(chunk_id, concept_id, score, model, prompt_version) " +
        "VALUES (?, ?, 2, 'qwen-3-4b-guru', 'v1')",
    )
    .run(chunkId, conceptId);
  return Number(info.lastInsertRowid);
}

function queue(targetId: number, action: string, reassignTo: string | null = null): void {
  handles.stmts.insertReviewAction.run(
    targetId,
    'staged_tags',
    action,
    reassignTo,
    null,
    'tester',
    `cid-${action}-${targetId}-${Math.random()}`,
  );
}

function tag(id: number) {
  return handles.rw.prepare('SELECT * FROM staged_tags WHERE id = ?').get(id) as {
    concept_id: string;
    status: string;
    justification: string | null;
  };
}

describe('reassign provenance (todo:a8bb7213)', () => {
  it('leaves the donor recording the concept the model actually proposed', () => {
    const donor = addTag('hinduism.yoga-sutras-book-01.015', 'paradox_as_teaching');
    queue(donor, 'reassign', 'inner_silence');

    buildApply(handles.rw, handles.stmts)();

    const after = tag(donor);
    expect(after.status).toBe('reassigned');
    // The bug: updateStagedTagConcept overwrote this with 'inner_silence', so
    // the target was stored twice and the proposal was stored nowhere. The
    // donor row is the only record that the tagger over-applied this concept
    // here, which is what node 11 review exists to accumulate.
    expect(after.concept_id).toBe('paradox_as_teaching');
  });

  it('records the target exactly once, on the new pending row', () => {
    const donor = addTag('hinduism.yoga-sutras-book-01.015', 'paradox_as_teaching');
    queue(donor, 'reassign', 'inner_silence');

    buildApply(handles.rw, handles.stmts)();

    const rows = handles.rw
      .prepare("SELECT concept_id, status, justification FROM staged_tags ORDER BY id")
      .all() as Array<{ concept_id: string; status: string; justification: string | null }>;
    expect(rows).toHaveLength(2);
    expect(rows.map((r) => r.concept_id)).toEqual(['paradox_as_teaching', 'inner_silence']);
    expect(rows[1].status).toBe('pending');
    expect(rows[1].justification).toBe('Reassigned from paradox_as_teaching');
  });

  it('retains the donor concept without tripping the partial unique index', () => {
    // The donor keeps (chunk, paradox_as_teaching, model, version) — the same
    // key it already had. Safe only because it leaves status='pending' first.
    const donor = addTag('hinduism.yoga-sutras-book-01.015', 'paradox_as_teaching');
    queue(donor, 'reassign', 'inner_silence');
    const result = buildApply(handles.rw, handles.stmts)();
    expect(result.errors).toEqual([]);
  });
});

describe('queue drain order', () => {
  // selectQueuedActions is ORDER BY id ASC and buildApply iterates it
  // directly, so the queue applies in insertion order. The DESC ordering in
  // db.ts belongs to selectQueueWithContext, which only feeds the queue
  // display route. scripts/validate_queue.py replays DESC and cites "mirror
  // the server", so its collision findings are inverted — see todo.
  it('applies in insertion order, so an earlier reject clears the way', () => {
    const donor = addTag('c.001', 'paradox_as_teaching');
    const occupant = addTag('c.001', 'inner_silence');

    queue(occupant, 'reject'); // lower id → applies FIRST
    queue(donor, 'reassign', 'inner_silence'); // higher id → applies second

    const result = buildApply(handles.rw, handles.stmts)();
    expect(result.errors).toEqual([]);
    expect(tag(occupant).status).toBe('rejected');
    expect(tag(donor).status).toBe('reassigned');
  });

  it('collides when the clearing reject is queued after the reassign', () => {
    const donor = addTag('c.001', 'paradox_as_teaching');
    const occupant = addTag('c.001', 'inner_silence');

    queue(donor, 'reassign', 'inner_silence'); // lower id → applies FIRST
    queue(occupant, 'reject'); // higher id → too late

    // The insert hits idx_staged_tags_provenance_unique while the occupant is
    // still pending. buildApply wraps the whole drain in one transaction, so
    // this is the case that discards an entire review pass.
    expect(() => buildApply(handles.rw, handles.stmts)()).toThrow(/UNIQUE constraint failed/);
  });
});
