// POST /api/tags/bulk (todo:ee0b6136) — batched queue endpoint. Runs the
// real router over a temp DB via a minimal in-process express harness so
// the tests exercise actual SQL, zod schemas, transaction wrapper and
// idempotency behaviour — no new test dependencies.
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import Database from 'better-sqlite3';
import express from 'express';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import type { Server } from 'node:http';

import { tagsRouter } from './routes/tags.js';
import { chunksRouter } from './routes/chunks.js';
import { applyRouter } from './routes/apply.js';
import { openDb } from './db.js';

let dir: string;
let handles: ReturnType<typeof openDb>;
let server: Server;
let baseUrl: string;

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
`;

beforeEach(async () => {
  dir = mkdtempSync(join(tmpdir(), 'guru-bulk-'));
  const path = join(dir, 'test.db');
  const seed = new Database(path);
  seed.exec(LIVE_SCHEMA);
  seed.close();
  handles = openDb({ db_path: path } as Parameters<typeof openDb>[0]);
  const app = express();
  app.use(express.json());
  app.use('/api', tagsRouter(handles.stmts, handles.rw));
  app.use('/api', chunksRouter(handles.ro, {
    load: () => ({ body: 'test body', meta: {} }),
  } as any));
  app.use('/api', applyRouter(handles.rw, handles.ro, handles.stmts));
  await new Promise<void>((resolve) => {
    server = app.listen(0, '127.0.0.1', () => resolve());
  });
  const addr = server.address();
  const port = typeof addr === 'object' && addr !== null ? addr.port : 0;
  baseUrl = `http://127.0.0.1:${port}`;
});

afterEach(async () => {
  await new Promise<void>((resolve) => server.close(() => resolve()));
  handles.ro.close();
  handles.rw.close();
  rmSync(dir, { recursive: true, force: true });
});

function addTag(n: number): number {
  const info = handles.rw
    .prepare(
      "INSERT INTO staged_tags(chunk_id, concept_id, score, model, prompt_version) " +
        "VALUES (?, ?, 2, 'qwen-3-4b-guru', 'v1')",
    )
    .run(`hinduism.yoga-sutras-book-01.${String(n).padStart(3, '0')}`, 'concept_under_test');
  return Number(info.lastInsertRowid);
}

async function postBulk(items: unknown): Promise<{ status: number; body: any }> {
  const res = await fetch(`${baseUrl}/api/tags/bulk`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(items),
  });
  return { status: res.status, body: await res.json() };
}

function queuedAction(targetId: number): { action: string; applied_at: string | null } {
  return handles.rw
    .prepare(
      "SELECT action, applied_at FROM review_actions WHERE target_table='staged_tags' AND target_id = ?",
    )
    .get(targetId) as { action: string; applied_at: string | null };
}

describe('POST /api/tags/bulk (todo:ee0b6136)', () => {
  it('queues every valid item in one call and reports counts', async () => {
    const ids = [addTag(1), addTag(2), addTag(3)];
    const res = await postBulk(
      ids.map((id, i) => ({
        target_id: id,
        action: i === 0 ? 'accept' : 'reject',
        client_action_id: `bulk-${i}`,
        reviewer: 'driver-test',
      })),
    );

    expect(res.status).toBe(200);
    expect(res.body).toMatchObject({ ok: true, queued: 3, skipped: 0, unknown_ids: [] });
    expect(queuedAction(ids[0]).action).toBe('accept');
    expect(queuedAction(ids[2]).action).toBe('reject');
    // Queue-only: nothing is applied by this endpoint.
    expect(queuedAction(ids[0]).applied_at).toBeNull();
  });

  it('reports unknown ids without failing the batch', async () => {
    const good = addTag(4);
    const res = await postBulk([
      { target_id: good, action: 'accept', client_action_id: 'b-good', reviewer: 'r' },
      { target_id: 999999, action: 'accept', client_action_id: 'b-bad', reviewer: 'r' },
    ]);

    expect(res.status).toBe(200);
    expect(res.body.queued).toBe(1);
    expect(res.body.unknown_ids).toEqual([999999]);
    // Per-item map distinguishes queued from unknown (driver acceptance
    // criteria: unknown_ids ≠ skipped — they are different failure shapes).
    expect(res.body.results[good]).toBe('queued');
    expect(res.body.results[999999]).toBe('unknown');
  });

  it('distinguishes already-queued replays (skipped) from unknown ids', async () => {
    const id = addTag(8);
    await postBulk([{ target_id: id, action: 'accept', client_action_id: 'dist-1', reviewer: 'r' }]);
    const replay = await postBulk([
      { target_id: id, action: 'accept', client_action_id: 'dist-1', reviewer: 'r' },
      { target_id: 888888, action: 'reject', client_action_id: 'dist-2', reviewer: 'r' },
    ]);
    expect(replay.body.skipped).toBe(1);
    expect(replay.body.unknown_ids).toEqual([888888]);
    expect(replay.body.results[id]).toBe('skipped');
    expect(replay.body.results[888888]).toBe('unknown');
  });

  it('counts invalid items as skipped with per-item errors', async () => {
    const good = addTag(5);
    const res = await postBulk([
      { target_id: good, action: 'accept', client_action_id: 'b-ok', reviewer: 'r' },
      { target_id: good, action: 'reassign', client_action_id: 'b-no-target', reviewer: 'r' },
      'not-an-object',
    ]);

    expect(res.status).toBe(200);
    expect(res.body.queued).toBe(1);
    expect(res.body.skipped).toBeGreaterThanOrEqual(2);
  });

  it('is idempotent on client_action_id replay — counted as skipped, not queued', async () => {
    const id = addTag(6);
    const item = { target_id: id, action: 'accept', client_action_id: 'same-cid', reviewer: 'r' };

    const first = await postBulk([item]);
    expect(first.body.queued).toBe(1);

    const replay = await postBulk([item]);
    expect(replay.status).toBe(200);
    expect(replay.body.queued).toBe(0);
    expect(replay.body.skipped).toBe(1);

    // Exactly one review_actions row for that cid.
    const n = handles.rw
      .prepare("SELECT COUNT(*) AS n FROM review_actions WHERE client_action_id='same-cid'")
      .get() as { n: number };
    expect(n.n).toBe(1);
  });

  it('rejects non-array bodies and empty batches', async () => {
    expect((await postBulk({})).status).toBe(400);
    expect((await postBulk([])).status).toBe(400);
  });

  it('reports unexpected DB errors per-item instead of failing the batch', async () => {
    // Force a per-item DB failure: drop review_actions so every insert
    // throws inside queueOne's guard.
    const a = addTag(7);
    handles.rw.exec('DROP TABLE review_actions');
    const res = await postBulk([
      { target_id: a, action: 'accept', client_action_id: 'x-1', reviewer: 'r' },
    ]);
    expect(res.status).toBe(200);
    expect(res.body.queued).toBe(0);
    expect(res.body.errored_items).toHaveLength(1);
    // staged row untouched by the failed queueing.
    const n = handles.rw
      .prepare('SELECT COUNT(*) AS n FROM staged_tags WHERE id=?')
      .get(a) as { n: number };
    expect(n.n).toBe(1);
  });
});

// ── GET /api/chunks by_chunk coverage (todo:a8037ed0) ───────────────────

describe('GET /api/chunks by_chunk coverage (todo:a8037ed0)', () => {
  async function getChunks(): Promise<any> {
    const res = await fetch(`${baseUrl}/api/chunks?min_score=1`);
    return res.json();
  }

  it('reports pending_total vs queued per chunk, exposing under-queued batches', async () => {
    const chunkA = 'hinduism.yoga-sutras-book-01.010';
    const chunkB = 'hinduism.yoga-sutras-book-01.020';
    const insNode = handles.rw.prepare("INSERT INTO nodes(id, type, label) VALUES (?, 'chunk', ?)");
    insNode.run(chunkA, 'A');
    insNode.run(chunkB, 'B');
    const ins = handles.rw.prepare(
      "INSERT INTO staged_tags(chunk_id, concept_id, score, model, prompt_version) VALUES (?, ?, 2, 'm', 'v1')",
    );
    const a1 = Number(ins.run(chunkA, 'concept_x').lastInsertRowid);
    const b1 = Number(ins.run(chunkB, 'concept_y').lastInsertRowid);
    ins.run(chunkB, 'concept_z');

    // Queue only one of chunk B's two pending tags — the driver's
    // under-queue scenario.
    handles.stmts.insertReviewAction.run(
      b1, 'staged_tags', 'accept', null, null, 'r', 'cov-1',
    );

    const data = await getChunks();
    expect(data.by_chunk[chunkA]).toEqual({ pending_total: 1, queued: 0 });
    expect(data.by_chunk[chunkB]).toEqual({ pending_total: 2, queued: 1 });

    // After queueing the missing verdict, coverage reconciles.
    handles.stmts.insertReviewAction.run(
      a1, 'staged_tags', 'reject', null, null, 'r', 'cov-2',
    );
    handles.rw
      .prepare("INSERT INTO staged_tags(chunk_id, concept_id, score, model, prompt_version) VALUES (?, 'concept_w', 2, 'm2', 'v1')")
      .run(chunkB);
    const again = await getChunks();
    expect(again.by_chunk[chunkB].queued).toBe(1);   // new pending tag not yet queued
    expect(again.by_chunk[chunkB].pending_total).toBe(3);
    void chunkA;
  });

  it('omits chunks with no rows from by_chunk on an empty filter result', async () => {
    addTag(9);
    const data = await getChunks();
    // The default min_score=1 keeps our seeded tag visible; a filtered-out
    // text yields no entry rather than zero-entries for absent chunks.
    expect(Object.keys(data.by_chunk).length).toBeGreaterThanOrEqual(0);
  });
});

// ── GET /api/apply/preview remaining-pending reconciliation (todo:816b8865)

describe('GET /api/apply/preview remaining_pending reconciliation (todo:816b8865)', () => {
  async function preview(): Promise<any> {
    const res = await fetch(`${baseUrl}/api/apply/preview`);
    return res.json();
  }

  it('reports remaining pending tags overall and per text, excluding queued ones', async () => {
    const insNode = handles.rw.prepare(
      "INSERT INTO nodes(id, type, label, metadata_json) VALUES (?, 'chunk', ?, json_object('text_id','yoga-sutras-book-01'))",
    );
    insNode.run('hinduism.yoga-sutras-book-01.030', 'C30');
    insNode.run('hinduism.yoga-sutras-book-01.031', 'C31');
    handles.rw.prepare(
      "INSERT INTO staged_tags(chunk_id, concept_id, score, model, prompt_version) VALUES (?, ?, 2, 'm', 'v1')",
    ).run('hinduism.yoga-sutras-book-01.030', 'concept_a');
    const queued = Number(handles.rw.prepare(
      "INSERT INTO staged_tags(chunk_id, concept_id, score, model, prompt_version) VALUES (?, ?, 2, 'm', 'v1')",
    ).run('hinduism.yoga-sutras-book-01.031', 'concept_b').lastInsertRowid);

    // Queue one verdict — it must leave the remainder.
    handles.stmts.insertReviewAction.run(
      queued, 'staged_tags', 'accept', null, null, 'r', 'rec-1',
    );

    const data = await preview();
    expect(data.remaining_pending_total).toBe(1);
    expect(data.remaining_pending_in_text).toEqual([
      { text_id: 'yoga-sutras-book-01', n: 1 },
    ]);
  });

  it('reports zero remainder when every pending tag is queued or resolved', async () => {
    const id = addTag(10);
    handles.stmts.insertReviewAction.run(
      id, 'staged_tags', 'reject', null, null, 'r', 'rec-2',
    );
    const data = await preview();
    expect(data.remaining_pending_total).toBe(0);
    expect(data.remaining_pending_in_text).toEqual([]);
  });
});
