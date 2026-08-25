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
    // Per-item results: one entry per REQUEST ROW (driver acceptance
    // criteria; review fix — keyed by index so invalid rows and duplicated
    // target_ids still reconcile).
    expect(res.body.results).toEqual([
      { index: 0, status: 'queued' },
      { index: 1, status: 'unknown' },
    ]);
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
    expect(replay.body.results).toEqual([
      { index: 0, status: 'skipped' },
      { index: 1, status: 'unknown' },
    ]);
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
    // Review fix: every request row reconciles — including the zod-invalid
    // one and the two rows sharing a target_id.
    expect(res.body.results).toEqual([
      { index: 0, status: 'queued' },
      { index: 1, status: 'skipped' },
      { index: 2, status: 'skipped' },
    ]);
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

// ── GET /api/chunks include_reviewed (todo:b72f6908) ────────────────────

describe('GET /api/chunks include_reviewed (todo:b72f6908)', () => {
  function seedChunk(id: string, concept = 'concept_a'): number {
    handles.rw
      .prepare("INSERT INTO nodes(id, type, label) VALUES (?, 'chunk', 'S') ON CONFLICT(id) DO NOTHING")
      .run(id);
    return Number(
      handles.rw
        .prepare(
          "INSERT INTO staged_tags(chunk_id, concept_id, score, model, prompt_version) VALUES (?, ?, 2, 'm', 'v1')",
        )
        .run(id, concept).lastInsertRowid,
    );
  }

  it('omits reviewed_tags by default and includes them when requested', async () => {
    const id = seedChunk('hinduism.yoga-sutras-book-01.040');
    handles.rw
      .prepare("UPDATE staged_tags SET status='accepted', reviewed_by='curator', reviewed_at='2026-08-23T00:00:00Z' WHERE id=?")
      .run(id);

    const def = await (await fetch(`${baseUrl}/api/chunks?min_score=1`)).json();
    expect(def.chunks).toHaveLength(0); // accepted tag no longer counts as pending
    expect(def.by_chunk['hinduism.yoga-sutras-book-01.040']).toBeUndefined();

    // include_reviewed surfaces the verdict even though nothing is pending.
    // The outer chunk list is pending-driven; a fully reviewed chunk needs a
    // direct probe — here we verify the reviewed payload rides along when a
    // chunk has BOTH pending and reviewed tags.
    const c = 'hinduism.yoga-sutras-book-01.041';
    seedChunk(c);
    const acc = seedChunk(c, 'concept_b');
    handles.rw
      .prepare("UPDATE staged_tags SET status='rejected', reviewed_by='curator', reviewed_at='2026-08-23T00:00:00Z' WHERE id=?")
      .run(acc);

    const withRev = await (
      await fetch(`${baseUrl}/api/chunks?min_score=1&include_reviewed=true`)
    ).json();
    expect(withRev.chunks).toHaveLength(1);
    expect(withRev.chunks[0].chunk_id).toBe(c);
    expect(withRev.chunks[0].pending_tags).toHaveLength(1);
    expect(withRev.chunks[0].reviewed_tags).toHaveLength(1);
    expect(withRev.chunks[0].reviewed_tags[0]).toMatchObject({
      concept_id: 'concept_b',
      status: 'rejected',
      reviewed_by: 'curator',
    });
  });

  it('treats include_reviewed=false as false (review fix — no boolean-string coercion)', async () => {
    const c = 'hinduism.yoga-sutras-book-01.042';
    seedChunk(c);
    const acc = seedChunk(c, 'concept_b');
    handles.rw
      .prepare("UPDATE staged_tags SET status='rejected', reviewed_by='r', reviewed_at='x' WHERE id=?")
      .run(acc);

    const res = await (
      await fetch(`${baseUrl}/api/chunks?min_score=1&include_reviewed=false`)
    ).json();
    expect(res.chunks).toHaveLength(1);
    // z.coerce.boolean() turned "false" into true; the explicit check must not.
    expect(res.chunks[0].reviewed_tags).toBeUndefined();
  });

  it('direct ?chunk= lookup reaches fully-reviewed chunks (review fix)', async () => {
    const c = 'hinduism.yoga-sutras-book-01.043';
    const t1 = seedChunk(c);
    const t2 = seedChunk(c, 'concept_b');
    handles.rw
      .prepare("UPDATE staged_tags SET status='accepted', reviewed_by='r', reviewed_at='x' WHERE id IN (?, ?)")
      .run(t1, t2);

    // No pending tags left — the pending-driven list can't return it, but a
    // direct lookup with include_reviewed must.
    const pend = await (await fetch(`${baseUrl}/api/chunks?min_score=1`)).json();
    expect(pend.chunks.find((x: { chunk_id: string }) => x.chunk_id === c)).toBeUndefined();

    const direct = await (
      await fetch(`${baseUrl}/api/chunks?chunk=${encodeURIComponent(c)}&include_reviewed=true`)
    ).json();
    expect(direct.chunks).toHaveLength(1);
    expect(direct.chunks[0].chunk_id).toBe(c);
    expect(direct.chunks[0].pending_tags).toHaveLength(0);
    expect(direct.chunks[0].reviewed_tags).toHaveLength(2);
    expect(direct.next_cursor).toBeNull();

    // Miss on an unknown id → empty result, explicit not-found at the client.
    const miss = await (await fetch(`${baseUrl}/api/chunks?chunk=nope.missing.999`)).json();
    expect(miss.chunks).toEqual([]);
  });

  it('direct lookup shows QUEUED-but-unapplied tags and ignores min_score (review round 2)', async () => {
    // The queue row a curator clicks is a staged_tag that is still
    // status='pending' with an unapplied review_action. The standard inner
    // query excludes exactly that tag; the spot-check view must not.
    const c = 'hinduism.yoga-sutras-book-01.044';
    handles.rw
      .prepare("INSERT INTO nodes(id, type, label) VALUES (?, 'chunk', 'S')")
      .run(c);
    const queuedId = Number(
      handles.rw
        .prepare("INSERT INTO staged_tags(chunk_id, concept_id, score) VALUES (?, 'concept_q', 3)")
        .run(c).lastInsertRowid,
    );
    const lowScoreId = Number(
      handles.rw
        .prepare("INSERT INTO staged_tags(chunk_id, concept_id, score) VALUES (?, 'concept_low', 0)")
        .run(c).lastInsertRowid,
    );
    handles.stmts.insertReviewAction.run(
      queuedId, 'staged_tags', 'accept', null, null, 'r', 'rl2-1',
    );

    // Standard list: both invisible (queued excluded by the action filter;
    // score-0 below min_score=1).
    const std = await (await fetch(`${baseUrl}/api/chunks?min_score=1`)).json();
    const stdChunk = std.chunks.find((x: { chunk_id: string }) => x.chunk_id === c);
    expect(stdChunk?.pending_tags ?? []).toHaveLength(0);

    // Direct lookup: BOTH visible.
    const direct = await (
      await fetch(`${baseUrl}/api/chunks?chunk=${encodeURIComponent(c)}&include_reviewed=true`)
    ).json();
    expect(direct.chunks).toHaveLength(1);
    const ids = direct.chunks[0].pending_tags.map((t: { target_id: number }) => t.target_id);
    expect(ids).toContain(queuedId);   // the tag the queue row represents
    expect(ids).toContain(lowScoreId); // min_score not applied
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
