-- ============================================================================
-- v3_003_edge_review.sql
--
-- Edge-review schema migration per docs/web-review/edges.md §5 Migration #2.
--
-- Three coupled changes that require dropping and recreating review_actions
-- (SQLite has no DROP CONSTRAINT, so removing the FK forces a table-recreate
-- regardless):
--
--   1. Drop the FK on target_id. The column is now polymorphic — it points
--      at staged_tags.id when target_table='staged_tags' and at
--      staged_edges.id when target_table='staged_edges'. No single FK
--      satisfies both.
--
--   2. Add target_table TEXT NOT NULL DEFAULT 'staged_tags'. Existing rows
--      backfill to the staged_tags interpretation (the only kind possible
--      under the prior schema).
--
--   3. Add reclassify_to TEXT (NULL for all existing rows; populated only
--      when a staged_edges 'reclassify' action sets a new edge_type).
--
--   4. Replace the CHECK constraint with a polymorphic version that enforces
--      action ↔ target_table consistency:
--          - staged_tags rows take action ∈ {accept, reject, skip, reassign}
--            with reassign_to required iff action='reassign'.
--          - staged_edges rows take action ∈ {accept, reject, skip, reclassify}
--            with reclassify_to required iff action='reclassify'.
--      Cross-pollination (e.g. staged_tags + reclassify) is rejected.
--
-- Operator pre-flight (before running):
--   1. Stop the running web-review server (its prepared statements still
--      bind to the pre-edge-review schema; would 500 on next phone tap
--      until rebuilt + restarted).
--   2. scripts/backup_db.sh pre-edge-review
--   3. Verify the snapshot's manifest shows expected canary counts.
--   4. Then: sqlite3 data/guru.db < scripts/migrations/v3_003_edge_review.sql
--   5. Rebuild + restart the server.
-- ============================================================================

PRAGMA foreign_keys = ON;
.bail on
.headers on
.mode column

BEGIN TRANSACTION;

-- ----- recreate the table without the FK + with new columns + new CHECK -----

CREATE TABLE review_actions_v2 (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id         INTEGER NOT NULL,                 -- polymorphic, no FK
    target_table      TEXT NOT NULL DEFAULT 'staged_tags'
                          CHECK(target_table IN ('staged_tags','staged_edges')),
    action            TEXT NOT NULL
                          CHECK(action IN ('accept','reject','skip','reassign','reclassify')),
    reassign_to       TEXT,                             -- iff staged_tags + reassign
    reclassify_to     TEXT,                             -- iff staged_edges + reclassify
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
    )
);

-- ----- copy rows from old table; existing data is all staged_tags ----------

INSERT INTO review_actions_v2(
    id, target_id, target_table, action, reassign_to, reclassify_to,
    reviewer, client_action_id, applied_at, error, created_at
)
SELECT id, target_id, 'staged_tags', action, reassign_to, NULL,
       reviewer, client_action_id, applied_at, error, created_at
FROM review_actions;

-- ----- swap tables ---------------------------------------------------------

DROP TABLE review_actions;
ALTER TABLE review_actions_v2 RENAME TO review_actions;

-- ----- recreate indexes (lost when the original table was dropped) ---------

CREATE INDEX idx_review_actions_unapplied
    ON review_actions(target_id) WHERE applied_at IS NULL;
CREATE INDEX idx_review_actions_client_id
    ON review_actions(client_action_id);

-- ----- verification --------------------------------------------------------

SELECT 'verify: row count preserved' AS check_name, COUNT(*) AS rows FROM review_actions;
-- Expect same count as the pre-migration baseline.

SELECT 'verify: every existing row backfilled to staged_tags' AS check_name;
SELECT target_table, COUNT(*) AS rows FROM review_actions GROUP BY target_table;
-- Expect a single row: staged_tags|<count>.

SELECT 'verify: no FK on target_id (polymorphic)' AS check_name;
SELECT name, sql FROM sqlite_master
 WHERE type='table' AND name='review_actions';
-- Expect the CREATE TABLE without "REFERENCES staged_tags(id)".

SELECT 'verify: indexes recreated' AS check_name;
SELECT name FROM sqlite_master
 WHERE type='index' AND name LIKE 'idx_review_actions_%'
 ORDER BY name;
-- Expect: idx_review_actions_client_id, idx_review_actions_unapplied.

COMMIT;
