import type Database from 'better-sqlite3';

const DDL = `
CREATE TABLE IF NOT EXISTS review_actions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    staged_tag_id     INTEGER NOT NULL REFERENCES staged_tags(id),
    action            TEXT NOT NULL CHECK(action IN ('accept','reject','skip','reassign')),
    reassign_to       TEXT,
    reviewer          TEXT NOT NULL,
    client_action_id  TEXT NOT NULL UNIQUE,
    applied_at        TEXT,
    error             TEXT,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    CHECK ((action = 'reassign' AND reassign_to IS NOT NULL)
        OR (action != 'reassign' AND reassign_to IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_review_actions_unapplied
    ON review_actions(staged_tag_id) WHERE applied_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_review_actions_client_id
    ON review_actions(client_action_id);

CREATE INDEX IF NOT EXISTS idx_staged_tags_status_chunk
    ON staged_tags(status, chunk_id);

-- v3 Phase 1 partial UNIQUE index: structural prevention against re-tag
-- duplication within same provenance. Idempotent. The migration script
-- scripts/migrations/v3_001_provenance.sql adds this on the live DB; this
-- repeated declaration is for shadow DBs and any future fresh boot.
CREATE UNIQUE INDEX IF NOT EXISTS idx_staged_tags_provenance_unique
    ON staged_tags(chunk_id, concept_id, model, prompt_version)
    WHERE status='pending';
`;

// Live table fingerprint as of 2026-04-25. Update when upstream schema changes.
// Note: 'traditions' and 'text' data live as type='tradition' rows in `nodes`,
// not as separate tables. `_export_state` is owned by scripts/export.py.
const EXPECTED_TABLES = [
  '_export_state',
  'chunk_embeddings',
  'edges',
  'nodes',
  'review_actions',
  'staged_concepts',
  'staged_edges',
  'staged_tags',
  'tagging_progress',
];

export function applySchema(db: Database.Database): void {
  db.exec(DDL);
}

export function validateSchemaFingerprint(db: Database.Database): void {
  const rows = db
    .prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    .all() as { name: string }[];
  const actual = rows.map((r) => r.name).filter((n) => !n.startsWith('idx_'));
  const missing = EXPECTED_TABLES.filter((t) => !actual.includes(t));
  if (missing.length > 0) {
    throw new Error(
      `schema fingerprint mismatch — missing tables: ${missing.join(', ')}.\n` +
        `actual tables: ${actual.join(', ')}\n` +
        `expected: ${EXPECTED_TABLES.join(', ')}\n` +
        'If the upstream schema changed, update server/src/schema.ts EXPECTED_TABLES.',
    );
  }
}
