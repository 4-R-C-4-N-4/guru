-- ============================================================================
-- inspect_dupes.sql
--
-- Diagnostic queries for staged_tags duplicates. Read-only. Run any/all.
--
--   sqlite3 data/guru.db < scripts/inspect_dupes.sql
--
-- Or interactively:
--   sqlite3 data/guru.db
--   .read scripts/inspect_dupes.sql
-- ============================================================================

.headers on
.mode column
.width 50 30 5 8

-- ----------------------------------------------------------------------------
-- 1. Headline scope: how many duplicate (chunk_id, concept_id) groups, how
--    many rows total are duplicates, what fraction of the pending pool.
-- ----------------------------------------------------------------------------
SELECT '=== HEADLINE SCOPE ===' AS section;

SELECT
    SUM(CASE WHEN dup_count > 1 THEN 1 ELSE 0 END) AS duplicate_groups,
    SUM(CASE WHEN dup_count > 1 THEN dup_count ELSE 0 END) AS rows_in_duplicate_groups,
    SUM(CASE WHEN dup_count > 1 THEN dup_count - 1 ELSE 0 END) AS removable_rows,
    (SELECT COUNT(*) FROM staged_tags WHERE status='pending') AS total_pending,
    ROUND(100.0 * SUM(CASE WHEN dup_count > 1 THEN dup_count - 1 ELSE 0 END)
          / NULLIF((SELECT COUNT(*) FROM staged_tags WHERE status='pending'), 0), 1) AS pct_removable
FROM (
    SELECT chunk_id, concept_id, COUNT(*) AS dup_count
    FROM staged_tags
    WHERE status = 'pending'
    GROUP BY chunk_id, concept_id
);

-- ----------------------------------------------------------------------------
-- 2. Worst-offender chunks: which chunks have the most duplicate concepts.
-- ----------------------------------------------------------------------------
SELECT '=== WORST-OFFENDER CHUNKS (top 20) ===' AS section;

SELECT
    chunk_id,
    COUNT(*) AS total_tags,
    COUNT(DISTINCT concept_id) AS unique_concepts,
    COUNT(*) - COUNT(DISTINCT concept_id) AS removable
FROM staged_tags
WHERE status = 'pending'
GROUP BY chunk_id
HAVING removable > 0
ORDER BY removable DESC, total_tags DESC
LIMIT 20;

-- ----------------------------------------------------------------------------
-- 3. id-range sanity check: for chunks with duplicates, do the ids cluster
--    in distinct ranges (suggesting sequential runs) or interleave (suggesting
--    parallel runs that may have produced inconsistent quality)?
--
--    A clean sequential pattern looks like: min_id and max_id far apart, and
--    the gap between them roughly matches the size of a full tagging run.
--    Interleaved suggests you cannot trust "newest wins."
-- ----------------------------------------------------------------------------
SELECT '=== ID RANGE PER DUPLICATE CHUNK (top 20 by spread) ===' AS section;

SELECT
    chunk_id,
    COUNT(*) AS tags,
    MIN(id) AS min_id,
    MAX(id) AS max_id,
    MAX(id) - MIN(id) AS id_spread
FROM staged_tags
WHERE status = 'pending'
  AND chunk_id IN (
      SELECT chunk_id FROM staged_tags
      WHERE status = 'pending'
      GROUP BY chunk_id, concept_id HAVING COUNT(*) > 1
  )
GROUP BY chunk_id
ORDER BY id_spread DESC
LIMIT 20;

-- ----------------------------------------------------------------------------
-- 4. Score-conflict cases: duplicate pairs where the OLDER row had a HIGHER
--    score than the newest. These are the rows where "newest wins" silently
--    discards a more confident judgement. Eyeball before running dedupe.
-- ----------------------------------------------------------------------------
SELECT '=== SCORE CONFLICTS: older row has higher score (top 30) ===' AS section;

WITH ranked AS (
    SELECT
        id, chunk_id, concept_id, score, justification,
        ROW_NUMBER() OVER (PARTITION BY chunk_id, concept_id ORDER BY id DESC) AS rn,
        COUNT(*) OVER (PARTITION BY chunk_id, concept_id) AS group_size
    FROM staged_tags
    WHERE status = 'pending'
)
SELECT
    newest.chunk_id,
    newest.concept_id,
    older.id    AS older_id, older.score   AS older_score,
    newest.id   AS newest_id, newest.score AS newest_score,
    older.score - newest.score AS score_drop
FROM ranked newest
JOIN ranked older
  ON newest.chunk_id   = older.chunk_id
 AND newest.concept_id = older.concept_id
 AND newest.rn = 1
 AND older.rn  > 1
WHERE older.score > newest.score
ORDER BY score_drop DESC, newest.chunk_id
LIMIT 30;

SELECT '=== SCORE CONFLICTS: total count ===' AS section;

WITH ranked AS (
    SELECT
        id, chunk_id, concept_id, score,
        ROW_NUMBER() OVER (PARTITION BY chunk_id, concept_id ORDER BY id DESC) AS rn
    FROM staged_tags
    WHERE status = 'pending'
)
SELECT COUNT(*) AS rows_where_older_is_higher_scored
FROM ranked newest
JOIN ranked older
  ON newest.chunk_id   = older.chunk_id
 AND newest.concept_id = older.concept_id
 AND newest.rn = 1
 AND older.rn  > 1
WHERE older.score > newest.score;

-- ----------------------------------------------------------------------------
-- 5. Sample inspection: show one full duplicate group so you can eyeball
--    whether justifications differ meaningfully between runs.
-- ----------------------------------------------------------------------------
SELECT '=== SAMPLE DUPLICATE GROUP ===' AS section;

.width 8 50 30 5 70
SELECT id, chunk_id, concept_id, score, substr(justification, 1, 70) AS justification_preview
FROM staged_tags
WHERE status = 'pending'
  AND (chunk_id, concept_id) = (
      SELECT chunk_id, concept_id
      FROM staged_tags
      WHERE status = 'pending'
      GROUP BY chunk_id, concept_id
      HAVING COUNT(*) > 1
      ORDER BY COUNT(*) DESC, chunk_id
      LIMIT 1
  )
ORDER BY id;
