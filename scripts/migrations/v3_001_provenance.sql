-- ============================================================================
-- v3_001_provenance.sql
--
-- v3 Phase 1 migration: add (model, prompt_version) provenance columns to
-- staged_tags + a partial UNIQUE index that mechanically prevents the
-- re-tag dupe class we cleaned up on 2026-04-26.
--
-- Idempotent. All-or-nothing (BEGIN/COMMIT). Applied with .bail on so any
-- failure aborts before COMMIT.
--
-- Backfill rationale (post-dedupe analysis 2026-04-26):
--   id  < 1000 → 'Carnice-9b'   — early Carnice 9b run (qwen 9b finetune).
--                Known quality issues (~13 malformed rows; 216 dupes of
--                newer tags removed in cleanup_dupes). Marking explicitly
--                so future fine-tune training-data exports can filter out
--                without forensic work. (Initially backfilled as
--                'Carnice-9b'; renamed to 'Carnice-9b' same day per
--                operator confirmation.)
--   id >= 1000 → 'qwen3.5-27b'  — production tagger run. Uniform quality
--                post-dedupe.
--
-- Partial UNIQUE rationale: only enforce on status='pending'. Once a row
-- transitions to accepted/rejected/reassigned it is frozen audit history;
-- a future re-tag must not UNIQUE-violate against settled past. Within
-- pending, this index makes silent re-tag duplication impossible.
--
-- Usage:
--   sqlite3 data/guru.db < scripts/migrations/v3_001_provenance.sql
-- ============================================================================

PRAGMA foreign_keys = ON;
.bail on
.headers on
.mode column

BEGIN TRANSACTION;

-- ----- columns (idempotent: ADD COLUMN errors are tolerated below via the
-- WHERE model IS NULL guard on the UPDATE; running this script twice is safe
-- only if the first run committed successfully.) ---------------------------

ALTER TABLE staged_tags ADD COLUMN model TEXT;
ALTER TABLE staged_tags ADD COLUMN prompt_version TEXT;

-- ----- backfill, split by id range -----------------------------------------

UPDATE staged_tags
   SET model = 'Carnice-9b', prompt_version = 'v1'
 WHERE id < 1000 AND model IS NULL;

UPDATE staged_tags
   SET model = 'qwen3.5-27b', prompt_version = 'v1'
 WHERE id >= 1000 AND model IS NULL;

-- ----- partial UNIQUE index ------------------------------------------------

CREATE UNIQUE INDEX IF NOT EXISTS idx_staged_tags_provenance_unique
    ON staged_tags(chunk_id, concept_id, model, prompt_version)
    WHERE status = 'pending';

-- ----- verification: must come back with zero null rows --------------------

SELECT 'verify: rows missing provenance after backfill (must be 0)' AS check_name,
       COUNT(*) AS null_rows
  FROM staged_tags
 WHERE model IS NULL OR prompt_version IS NULL;

SELECT 'verify: provenance distribution by status' AS check_name;
SELECT model, prompt_version, status, COUNT(*) AS rows
  FROM staged_tags
 GROUP BY model, prompt_version, status
 ORDER BY model, status;

SELECT 'verify: index created' AS check_name,
       name FROM sqlite_master
 WHERE type='index' AND name='idx_staged_tags_provenance_unique';

COMMIT;
