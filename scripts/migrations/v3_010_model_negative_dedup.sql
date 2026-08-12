-- ============================================================================
-- v3_010_model_negative_dedup.sql
--
-- Phase 0.1 of the edge pipeline roadmap (rellm docs/edges/edge-roadmap.md):
-- dedup support for persisted model negatives.
--
-- propose_edges.py now writes the judge's negative verdicts (surface_only /
-- unrelated) as staged_edges rows with status='rejected' and
-- reviewed_by='model-negative', so re-runs stop re-paying for known negatives
-- and the training set gains its missing easy negatives.
--
-- Those rows bypass idx_staged_edges_provenance_unique, which is partial on
-- status='pending' — so without this index a re-run could silently duplicate
-- them (the one corruption mode in Phase 0). This index closes it, scoped to
-- the sentinel:
--
--   WHERE status='rejected' AND reviewed_by='model-negative'
--
-- Deliberately NOT a widening of the pending index to all rejected rows.
-- v3_005's rationale stands: curated rejections are frozen audit history, and
-- a future re-propose must not UNIQUE-violate against settled past. Scoping
-- to the sentinel keeps that intact — a curated rejection and a model
-- negative for the same (pair, model, prompt_version) can coexist.
--
-- No existing rows are in the index domain (the sentinel is new with this
-- migration), so creation cannot fail on prior data.
--
-- Idempotent: yes (IF NOT EXISTS).
--
-- Usage:
--   sqlite3 data/guru.db < scripts/migrations/v3_010_model_negative_dedup.sql
-- ============================================================================

PRAGMA foreign_keys = OFF;
.bail on
.headers on
.mode column

BEGIN TRANSACTION;

CREATE UNIQUE INDEX IF NOT EXISTS idx_staged_edges_model_negative_unique
    ON staged_edges(source_chunk, target_chunk, model, prompt_version)
    WHERE status = 'rejected' AND reviewed_by = 'model-negative';

-- ----- verification --------------------------------------------------------

SELECT 'verify: index exists' AS check_name;
SELECT name FROM sqlite_master
 WHERE type='index' AND tbl_name='staged_edges'
   AND name='idx_staged_edges_model_negative_unique';

SELECT 'verify: rows already in index domain (must be 0 at migration time)' AS check_name,
       COUNT(*) AS rows
  FROM staged_edges
 WHERE status='rejected' AND reviewed_by='model-negative';

COMMIT;

PRAGMA foreign_keys = ON;
