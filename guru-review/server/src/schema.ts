import type Database from 'better-sqlite3';

const DDL = `
-- Polymorphic review queue. target_id points at staged_tags.id /
-- staged_edges.id / staged_cleanups.id per target_table; no FK because no
-- single FK satisfies them. The CHECK enforces that action is consistent
-- with target_table — reassign is staged_tags-only, reclassify serves
-- staged_edges (new edge_type) and staged_cleanups (apparatus_drop only).
-- Live DBs get this shape via scripts/migrations/v3_008_cleanup_review.sql;
-- this declaration covers shadow DBs and fresh boots.
CREATE TABLE IF NOT EXISTS review_actions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id         INTEGER NOT NULL,
    target_table      TEXT NOT NULL DEFAULT 'staged_tags'
                          CHECK(target_table IN ('staged_tags','staged_edges','staged_cleanups')),
    action            TEXT NOT NULL
                          CHECK(action IN ('accept','reject','skip','reassign','reclassify')),
    reassign_to       TEXT,
    reclassify_to     TEXT,
    reviewer          TEXT NOT NULL,
    client_action_id  TEXT NOT NULL UNIQUE,
    applied_at        TEXT,
    error             TEXT,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    CHECK (
      (target_table = 'staged_tags'  AND action IN ('accept','reject','skip','reassign')
                                     AND reclassify_to IS NULL
                                     AND ((action='reassign') = (reassign_to IS NOT NULL)))
      OR
      (target_table = 'staged_edges' AND action IN ('accept','reject','skip','reclassify')
                                     AND reassign_to IS NULL
                                     AND ((action='reclassify') = (reclassify_to IS NOT NULL)))
      OR
      (target_table = 'staged_cleanups'
                                     AND action IN ('accept','reject','skip','reclassify')
                                     AND reassign_to IS NULL
                                     AND ((action='reclassify') = (reclassify_to IS NOT NULL))
                                     AND (reclassify_to IS NULL OR reclassify_to = 'apparatus_drop'))
    )
);

CREATE INDEX IF NOT EXISTS idx_review_actions_unapplied
    ON review_actions(target_id) WHERE applied_at IS NULL;

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
  'staged_cleanups',
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
