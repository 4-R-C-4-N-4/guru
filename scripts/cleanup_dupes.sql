-- ============================================================================
-- cleanup_dupes.sql
--
-- Two-step pending-pool cleanup based on inspect_dupes.sql findings:
--
--   STEP 1: Delete 13 malformed early-era rows (id<1000 with empty
--           concept_id or empty justification). Pure garbage from the
--           less-tuned early-LLM run; would never form valid edges.
--
--   STEP 2: Apply "newest-wins" dedupe per (chunk_id, concept_id).
--           Drops 215 rows — every one of them in the early-era (id<1000),
--           leaving the qwen-pass middle/late rows untouched.
--
--   Net: pending pool 15,263 → ~15,035 (≈228 rows removed).
--
-- ----------------------------------------------------------------------------
-- DRY RUN BY DEFAULT — the script ends in ROLLBACK so this file is always
-- safe to run by hand. To commit, use the wrapper:
--
--   scripts/cleanup_dupes.sh             # dry-run (this file unchanged)
--   scripts/cleanup_dupes.sh --apply     # snapshot + sed ROLLBACK→COMMIT
--
-- Before --apply, read the safety-check row at the top. A non-zero
-- queued_action_conflicts means: handle those queued review_actions first
-- (apply or DELETE /api/queue) before re-running with --apply.
-- ============================================================================

PRAGMA foreign_keys = ON;
.headers on
.mode column
.bail on

-- ============================================================================
-- SAFETY CHECK: are any cleanup targets currently bound to a queued
-- review_actions row? (Applied review_actions can't conflict — their
-- staged_tag is by definition no longer 'pending'.) A non-zero conflict
-- count means: handle those queued actions first (apply or delete via
-- /api/queue) before running the cleanup.
-- ============================================================================

WITH targets AS (
  -- step 1 targets: malformed early-era rows
  SELECT id FROM staged_tags
   WHERE status='pending'
     AND id < 1000
     AND (concept_id = '' OR justification IS NULL OR justification = '')
  UNION
  -- step 2 targets: every row with rn > 1 in (chunk, concept) partition
  SELECT id FROM (
    SELECT id, ROW_NUMBER() OVER (
      PARTITION BY chunk_id, concept_id ORDER BY id DESC
    ) AS rn
    FROM staged_tags WHERE status='pending'
  ) WHERE rn > 1
)
SELECT
  COUNT(*) AS queued_action_conflicts,
  CASE WHEN COUNT(*) = 0
       THEN 'OK — no queued review_actions reference cleanup targets'
       ELSE 'ABORT — resolve these queued actions first (apply or DELETE /api/queue)'
  END AS safety
FROM review_actions
WHERE applied_at IS NULL
  AND target_id IN (SELECT id FROM targets);

-- ============================================================================
-- BEFORE: counts
-- ============================================================================

SELECT 'BEFORE' AS phase,
  (SELECT COUNT(*) FROM staged_tags WHERE status='pending')                                       AS pending,
  (SELECT COUNT(*) FROM staged_tags WHERE status='pending' AND id < 1000)                         AS early_pending,
  (SELECT COUNT(*) FROM staged_tags WHERE status='pending' AND concept_id='')                     AS empty_concept,
  (SELECT COUNT(*) FROM staged_tags WHERE status='pending' AND (justification IS NULL OR justification='')) AS empty_just,
  (SELECT COUNT(*) FROM (
       SELECT 1 FROM staged_tags WHERE status='pending'
        GROUP BY chunk_id, concept_id HAVING COUNT(*) > 1
   ))                                                                                              AS dup_groups;

-- ============================================================================
-- TRANSACTION
-- ============================================================================

BEGIN TRANSACTION;

-- ----------------------------------------------------------------------------
-- STEP 1: delete malformed early-era rows
-- ----------------------------------------------------------------------------
DELETE FROM staged_tags
 WHERE status = 'pending'
   AND id < 1000
   AND (concept_id = '' OR justification IS NULL OR justification = '');

SELECT 'step 1 (malformed)' AS step, changes() AS rows_deleted;

-- ----------------------------------------------------------------------------
-- STEP 2: newest-wins dedupe per (chunk_id, concept_id)
--   Keep the row with the highest id in each (chunk_id, concept_id) group;
--   delete everything else. Per the diagnostic this surgically targets the
--   under-tuned early-LLM duplicates and leaves middle/late runs untouched.
-- ----------------------------------------------------------------------------
DELETE FROM staged_tags
 WHERE status = 'pending'
   AND id IN (
     SELECT id FROM (
       SELECT id, ROW_NUMBER() OVER (
         PARTITION BY chunk_id, concept_id ORDER BY id DESC
       ) AS rn
       FROM staged_tags WHERE status='pending'
     ) WHERE rn > 1
   );

SELECT 'step 2 (dedupe)' AS step, changes() AS rows_deleted;

-- ============================================================================
-- AFTER (still inside the transaction): verify expected end state
-- ============================================================================

SELECT 'AFTER (in-tx)' AS phase,
  (SELECT COUNT(*) FROM staged_tags WHERE status='pending')                                       AS pending,
  (SELECT COUNT(*) FROM staged_tags WHERE status='pending' AND id < 1000)                         AS early_pending,
  (SELECT COUNT(*) FROM staged_tags WHERE status='pending' AND concept_id='')                     AS empty_concept,
  (SELECT COUNT(*) FROM staged_tags WHERE status='pending' AND (justification IS NULL OR justification='')) AS empty_just,
  (SELECT COUNT(*) FROM (
       SELECT 1 FROM staged_tags WHERE status='pending'
        GROUP BY chunk_id, concept_id HAVING COUNT(*) > 1
   ))                                                                                              AS dup_groups;

-- Expected end-state: empty_concept=0, empty_just=0, dup_groups=0,
-- pending decreased by ≈228, the middle (1k-14k) and late (≥14k) row
-- counts unchanged.

-- ============================================================================
-- DRY-RUN BARRIER — change to COMMIT; only after reading output above and
-- confirming the safety check returned OK and the AFTER counts look right.
-- ============================================================================
ROLLBACK;
-- COMMIT;

SELECT 'transaction rolled back — dry-run only' AS result;
