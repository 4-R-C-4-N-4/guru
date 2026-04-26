import { describe, expect, it } from 'vitest';
import Database from 'better-sqlite3';
import { applySchema, validateSchemaFingerprint } from './schema.js';

function seedLiveTables(db: Database.Database): void {
  // Mimic the live schema's tables (without their full DDL — just the names).
  for (const t of [
    '_export_state',
    'chunk_embeddings',
    'edges',
    'nodes',
    'staged_concepts',
    'staged_edges',
    'staged_tags',
    'tagging_progress',
  ]) {
    db.exec(`CREATE TABLE ${t} (id INTEGER PRIMARY KEY)`);
  }
  // staged_tags needs the columns review_actions FK references AND the v3
  // provenance columns the partial UNIQUE index targets.
  db.exec(
    "DROP TABLE staged_tags; " +
    "CREATE TABLE staged_tags (" +
      "id INTEGER PRIMARY KEY, status TEXT, chunk_id TEXT, " +
      "concept_id TEXT, model TEXT, prompt_version TEXT)",
  );
}

describe('schema', () => {
  it('applySchema is idempotent', () => {
    const db = new Database(':memory:');
    seedLiveTables(db);
    applySchema(db);
    applySchema(db); // second apply must not throw
    const row = db
      .prepare("SELECT name FROM sqlite_master WHERE type='table' AND name='review_actions'")
      .get();
    expect(row).toBeDefined();
  });

  it('compound index idx_staged_tags_status_chunk is created', () => {
    const db = new Database(':memory:');
    seedLiveTables(db);
    applySchema(db);
    const idx = db
      .prepare(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_staged_tags_status_chunk'",
      )
      .get();
    expect(idx).toBeDefined();
  });

  it('validateSchemaFingerprint passes when all expected tables present', () => {
    const db = new Database(':memory:');
    seedLiveTables(db);
    applySchema(db);
    expect(() => validateSchemaFingerprint(db)).not.toThrow();
  });

  it('validateSchemaFingerprint fails on missing upstream table', () => {
    const db = new Database(':memory:');
    seedLiveTables(db);
    applySchema(db);
    db.exec('DROP TABLE chunk_embeddings');
    expect(() => validateSchemaFingerprint(db)).toThrow(/chunk_embeddings/);
  });

  it('CHECK constraint enforces reassign_to required iff action=reassign', () => {
    const db = new Database(':memory:');
    seedLiveTables(db);
    applySchema(db);
    db.exec("INSERT INTO staged_tags(id, status, chunk_id) VALUES (1, 'pending', 'x.y.001')");
    // accept with reassign_to set → should fail
    expect(() =>
      db
        .prepare(
          'INSERT INTO review_actions(staged_tag_id, action, reassign_to, reviewer, client_action_id) VALUES (?, ?, ?, ?, ?)',
        )
        .run(1, 'accept', 'wrong', 'test', 'id-1'),
    ).toThrow();
    // reassign without reassign_to → should fail
    expect(() =>
      db
        .prepare(
          'INSERT INTO review_actions(staged_tag_id, action, reassign_to, reviewer, client_action_id) VALUES (?, ?, ?, ?, ?)',
        )
        .run(1, 'reassign', null, 'test', 'id-2'),
    ).toThrow();
    // accept with reassign_to=null → ok
    db.prepare(
      'INSERT INTO review_actions(staged_tag_id, action, reassign_to, reviewer, client_action_id) VALUES (?, ?, ?, ?, ?)',
    ).run(1, 'accept', null, 'test', 'id-3');
  });
});
