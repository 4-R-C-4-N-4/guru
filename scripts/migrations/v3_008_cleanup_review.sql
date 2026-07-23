-- ============================================================================
-- v3_008_cleanup_review.sql
--
-- Third review queue: staged_cleanups (todo:b44966d0) — model-proposed
-- rewrites of malformed chunk bodies (hard-wrapped prose), reviewed as
-- diffs in guru-review behind the same apply gate as tags/edges.
--
-- Two changes:
--
--   1. CREATE staged_cleanups (same DDL as scripts/schema.sql; IF NOT
--      EXISTS so a fresh DB that already ran schema.sql no-ops).
--
--   2. Recreate review_actions to admit target_table='staged_cleanups'
--      (SQLite cannot ALTER a CHECK, so table-recreate, exactly like
--      v3_003). The cleanups CHECK branch:
--          - action ∈ {accept, reject, skip, reclassify}
--          - reassign_to always NULL
--          - reclassify_to = 'apparatus_drop' iff action='reclassify'
--            (the reviewer's "this is whole-chunk apparatus, route to
--            todo:50438e23" escape hatch — apply flips the staged row
--            to status='apparatus'; nothing is ever deleted by apply).
--
-- Operator pre-flight (before running):
--   1. Stop the running web-review server (prepared statements bind the
--      old schema; would 500 until rebuilt + restarted).
--   2. scripts/backup_db.sh pre-cleanup-review
--   3. Verify the snapshot's manifest shows expected canary counts.
--   4. Then: sqlite3 data/guru.db < scripts/migrations/v3_008_cleanup_review.sql
--   5. Rebuild + restart the server.
-- ============================================================================

PRAGMA foreign_keys = ON;

BEGIN;

-- ── 1. staged_cleanups ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS staged_cleanups (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id        TEXT NOT NULL REFERENCES nodes(id),
    original_body   TEXT NOT NULL,
    proposed_body   TEXT NOT NULL,
    justification   TEXT,
    signal_score    REAL NOT NULL DEFAULT 0.0,
    words_preserved INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending','accepted','rejected','apparatus')),
    reviewed_by     TEXT,
    reviewed_at     TEXT,
    applied_at      TEXT,
    model           TEXT,
    prompt_version  TEXT
);

CREATE INDEX IF NOT EXISTS idx_staged_cleanups_chunk  ON staged_cleanups(chunk_id);
CREATE INDEX IF NOT EXISTS idx_staged_cleanups_status ON staged_cleanups(status);

CREATE UNIQUE INDEX IF NOT EXISTS idx_staged_cleanups_provenance_unique
    ON staged_cleanups(chunk_id, model, prompt_version)
    WHERE status = 'pending';

-- ── 2. review_actions recreate with the third CHECK branch ─────────────────

-- Byte-for-byte the live v2 table (columns, defaults, index shapes from
-- `.schema review_actions`), changing ONLY the two CHECKs.
CREATE TABLE review_actions_v3 (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id         INTEGER NOT NULL,                 -- polymorphic, no FK
    target_table      TEXT NOT NULL DEFAULT 'staged_tags'
                          CHECK(target_table IN ('staged_tags','staged_edges','staged_cleanups')),
    action            TEXT NOT NULL
                          CHECK(action IN ('accept','reject','skip','reassign','reclassify')),
    reassign_to       TEXT,                             -- iff staged_tags + reassign
    reclassify_to     TEXT,                             -- iff staged_edges/cleanups + reclassify
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

INSERT INTO review_actions_v3
    (id, target_id, target_table, action, reassign_to, reclassify_to,
     reviewer, client_action_id, applied_at, error, created_at)
SELECT id, target_id, target_table, action, reassign_to, reclassify_to,
       reviewer, client_action_id, applied_at, error, created_at
FROM review_actions;

DROP TABLE review_actions;
ALTER TABLE review_actions_v3 RENAME TO review_actions;

CREATE INDEX idx_review_actions_unapplied
    ON review_actions(target_id) WHERE applied_at IS NULL;
CREATE INDEX idx_review_actions_client_id
    ON review_actions(client_action_id);

-- ── verification ────────────────────────────────────────────────────────────

SELECT 'review_actions rows: ' || COUNT(*) FROM review_actions;
SELECT 'staged_cleanups present: ' || COUNT(*)
  FROM sqlite_master WHERE type = 'table' AND name = 'staged_cleanups';

COMMIT;
