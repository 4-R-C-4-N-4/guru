-- ============================================================================
-- v3_002_rename_target_id.sql
--
-- Cosmetic rename: review_actions.staged_tag_id → review_actions.target_id.
--
-- Prerequisite for the edge-review work in docs/web-review/edges.md. Under
-- polymorphism the column points at either staged_tags.id OR staged_edges.id;
-- 'target_id' is the honest name. This ticket does the rename ONLY.
-- Polymorphism (drop FK + add target_table + add reclassify_to + new CHECK)
-- comes later via scripts/migrations/v3_003_edge_review.sql per
-- docs/web-review/edges.md §5 Migration #2.
--
-- ALTER TABLE … RENAME COLUMN is in-place since SQLite 3.25 (2018):
--   - All existing rows preserved (104 today, all from ivy-android phone sessions).
--   - The dependent partial index `idx_review_actions_unapplied` is rewritten
--     automatically to reference the new column name.
--   - The FK to staged_tags(id) is preserved; this ticket does NOT make the
--     column polymorphic.
--
-- Pre-migration discipline (from operator, before running this):
--   1. Stop the guru-review server (it has prepared statements bound to the
--      old column name; would fail until rebuilt + restarted).
--   2. Take a labeled snapshot:
--        scripts/backup_db.sh pre-target-id-rename
--   3. Verify integrity_check ok in the snapshot's manifest.
--   4. Then: sqlite3 data/guru.db < scripts/migrations/v3_002_rename_target_id.sql
--   5. Rebuild + restart the server.
-- ============================================================================

BEGIN TRANSACTION;

ALTER TABLE review_actions RENAME COLUMN staged_tag_id TO target_id;

-- Verification queries (output for the operator to eyeball before COMMIT)
SELECT 'verify: column renamed' AS check_name;
SELECT name FROM pragma_table_info('review_actions') WHERE name IN ('staged_tag_id', 'target_id');
-- Expect exactly one row: 'target_id'. If 'staged_tag_id' shows up, ABORT.

SELECT 'verify: row count preserved' AS check_name, COUNT(*) AS rows FROM review_actions;
-- Expect 104 (matches pre-migration canary).

SELECT 'verify: partial index points at new column' AS check_name;
SELECT sql FROM sqlite_master
 WHERE type='index' AND name='idx_review_actions_unapplied';
-- Expect "...ON review_actions(target_id) WHERE applied_at IS NULL".

COMMIT;
