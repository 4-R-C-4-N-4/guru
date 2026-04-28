-- ============================================================================
-- v3_004_normalize_chunk_ids.sql
--
-- Rewrite every chunk_id reference from the display-name form
-- ('Christian Mysticism.foo.001') to the snake_case directory-name form
-- ('christian_mysticism.foo.001'). Companion to scripts/chunk.py:191
-- (todo:4fd22c34) and scripts/backfill_chunk_ids.py.
--
-- Per docs/notes (todo:9ec1dcee). Affected traditions:
--   Neoplatonism → neoplatonism
--   Egyptian → egyptian
--   Taoism → taoism
--   Greek Mystery → greek_mystery
--   Christian Mysticism → christian_mysticism
--   Zoroastrianism → zoroastrianism
--   Jewish Mysticism → jewish_mysticism
--   Buddhism → buddhism
--   Mesopotamian → mesopotamian
--
-- Already-snake-case traditions (gnosticism, hermeticism, jewish_mysticism)
-- are no-ops — their chunk_ids stay unchanged.
--
-- Tables touched: nodes (PK), edges (source_id, target_id),
-- chunk_embeddings (PK), staged_tags (chunk_id), staged_edges
-- (source_chunk, target_chunk), tagging_progress (PK chunk_id),
-- staged_concepts (motivating_chunk — currently empty but dormant FK).
--
-- Pre-migration discipline (operator runs scripts/cleanup_chunk_ids.sh):
--   1. Stop the guru-review server.
--   2. Take a labeled snapshot.
--   3. Run this migration.
--   4. Run scripts/backfill_chunk_ids.py --apply to rewrite corpus TOML.
--   5. Validate parity (DB chunk_ids match disk chunk_ids).
--   6. Restart the server.
--
-- FK note: nodes.id is the PRIMARY KEY referenced by edges.source_id,
-- edges.target_id, chunk_embeddings.chunk_id, staged_tags.chunk_id, and
-- (logically) staged_edges.source_chunk / target_chunk. None of those FKs
-- are declared ON UPDATE CASCADE, so a naive UPDATE on nodes.id would
-- fail with a foreign-key violation. We disable FKs for the duration of
-- the migration and re-check at the end via PRAGMA foreign_key_check.
-- PRAGMA foreign_keys cannot be set inside a transaction in SQLite, so
-- the toggle lives outside the BEGIN…COMMIT.
-- ============================================================================

-- ── 1. Pre-migration audit (printed for the operator) ──────────────────────

SELECT '== pre-migration row counts (chunk_id-keyed, display-name form) ==' AS audit;

SELECT 'nodes (chunks)'               AS scope, COUNT(*) AS n FROM nodes
    WHERE type='chunk' AND (
        id GLOB 'Neoplatonism.*'        OR id GLOB 'Egyptian.*'
     OR id GLOB 'Taoism.*'              OR id GLOB 'Greek Mystery.*'
     OR id GLOB 'Christian Mysticism.*' OR id GLOB 'Zoroastrianism.*'
     OR id GLOB 'Jewish Mysticism.*'    OR id GLOB 'Buddhism.*'
     OR id GLOB 'Mesopotamian.*'
    )
UNION ALL
SELECT 'edges (source_id)',                COUNT(*) FROM edges WHERE
        source_id GLOB 'Neoplatonism.*' OR source_id GLOB 'Egyptian.*'
     OR source_id GLOB 'Taoism.*' OR source_id GLOB 'Greek Mystery.*'
     OR source_id GLOB 'Christian Mysticism.*' OR source_id GLOB 'Zoroastrianism.*'
     OR source_id GLOB 'Jewish Mysticism.*' OR source_id GLOB 'Buddhism.*'
     OR source_id GLOB 'Mesopotamian.*'
UNION ALL
SELECT 'edges (target_id)',                COUNT(*) FROM edges WHERE
        target_id GLOB 'Neoplatonism.*' OR target_id GLOB 'Egyptian.*'
     OR target_id GLOB 'Taoism.*' OR target_id GLOB 'Greek Mystery.*'
     OR target_id GLOB 'Christian Mysticism.*' OR target_id GLOB 'Zoroastrianism.*'
     OR target_id GLOB 'Jewish Mysticism.*' OR target_id GLOB 'Buddhism.*'
     OR target_id GLOB 'Mesopotamian.*'
UNION ALL
SELECT 'chunk_embeddings',               COUNT(*) FROM chunk_embeddings WHERE
        chunk_id GLOB 'Neoplatonism.*' OR chunk_id GLOB 'Egyptian.*'
     OR chunk_id GLOB 'Taoism.*' OR chunk_id GLOB 'Greek Mystery.*'
     OR chunk_id GLOB 'Christian Mysticism.*' OR chunk_id GLOB 'Zoroastrianism.*'
     OR chunk_id GLOB 'Jewish Mysticism.*' OR chunk_id GLOB 'Buddhism.*'
     OR chunk_id GLOB 'Mesopotamian.*'
UNION ALL
SELECT 'staged_tags',                    COUNT(*) FROM staged_tags WHERE
        chunk_id GLOB 'Neoplatonism.*' OR chunk_id GLOB 'Egyptian.*'
     OR chunk_id GLOB 'Taoism.*' OR chunk_id GLOB 'Greek Mystery.*'
     OR chunk_id GLOB 'Christian Mysticism.*' OR chunk_id GLOB 'Zoroastrianism.*'
     OR chunk_id GLOB 'Jewish Mysticism.*' OR chunk_id GLOB 'Buddhism.*'
     OR chunk_id GLOB 'Mesopotamian.*'
UNION ALL
SELECT 'staged_edges (source_chunk)',    COUNT(*) FROM staged_edges WHERE
        source_chunk GLOB 'Neoplatonism.*' OR source_chunk GLOB 'Egyptian.*'
     OR source_chunk GLOB 'Taoism.*' OR source_chunk GLOB 'Greek Mystery.*'
     OR source_chunk GLOB 'Christian Mysticism.*' OR source_chunk GLOB 'Zoroastrianism.*'
     OR source_chunk GLOB 'Jewish Mysticism.*' OR source_chunk GLOB 'Buddhism.*'
     OR source_chunk GLOB 'Mesopotamian.*'
UNION ALL
SELECT 'staged_edges (target_chunk)',    COUNT(*) FROM staged_edges WHERE
        target_chunk GLOB 'Neoplatonism.*' OR target_chunk GLOB 'Egyptian.*'
     OR target_chunk GLOB 'Taoism.*' OR target_chunk GLOB 'Greek Mystery.*'
     OR target_chunk GLOB 'Christian Mysticism.*' OR target_chunk GLOB 'Zoroastrianism.*'
     OR target_chunk GLOB 'Jewish Mysticism.*' OR target_chunk GLOB 'Buddhism.*'
     OR target_chunk GLOB 'Mesopotamian.*';

-- ── 2. Collision audit — abort if any rewrite would create a duplicate ──────
--
-- For each (display-name) chunk_id, check whether the snake_case form ALREADY
-- exists in nodes. If so, the migration would violate the PRIMARY KEY. The
-- operator must reconcile manually before re-running.

SELECT '== collision audit (must be empty before COMMIT) ==' AS audit;

SELECT id AS would_collide
FROM nodes
WHERE type='chunk' AND (
        id GLOB 'Neoplatonism.*' OR id GLOB 'Egyptian.*' OR id GLOB 'Taoism.*'
     OR id GLOB 'Greek Mystery.*' OR id GLOB 'Christian Mysticism.*'
     OR id GLOB 'Zoroastrianism.*' OR id GLOB 'Jewish Mysticism.*'
     OR id GLOB 'Buddhism.*' OR id GLOB 'Mesopotamian.*'
)
AND (CASE
    WHEN id GLOB 'Neoplatonism.*'         THEN REPLACE(id, 'Neoplatonism.',         'neoplatonism.')
    WHEN id GLOB 'Egyptian.*'             THEN REPLACE(id, 'Egyptian.',             'egyptian.')
    WHEN id GLOB 'Taoism.*'               THEN REPLACE(id, 'Taoism.',               'taoism.')
    WHEN id GLOB 'Greek Mystery.*'        THEN REPLACE(id, 'Greek Mystery.',        'greek_mystery.')
    WHEN id GLOB 'Christian Mysticism.*'  THEN REPLACE(id, 'Christian Mysticism.',  'christian_mysticism.')
    WHEN id GLOB 'Zoroastrianism.*'       THEN REPLACE(id, 'Zoroastrianism.',       'zoroastrianism.')
    WHEN id GLOB 'Jewish Mysticism.*'     THEN REPLACE(id, 'Jewish Mysticism.',     'jewish_mysticism.')
    WHEN id GLOB 'Buddhism.*'             THEN REPLACE(id, 'Buddhism.',             'buddhism.')
    WHEN id GLOB 'Mesopotamian.*'         THEN REPLACE(id, 'Mesopotamian.',         'mesopotamian.')
END) IN (SELECT id FROM nodes WHERE type='chunk');

-- ── 3. Disable FKs (must be outside the transaction in SQLite) ──────────────

PRAGMA foreign_keys = OFF;

-- ── 4. The migration ────────────────────────────────────────────────────────

BEGIN TRANSACTION;

-- nodes.id (PK on chunk rows)
UPDATE nodes SET id = CASE
    WHEN id GLOB 'Neoplatonism.*'         THEN REPLACE(id, 'Neoplatonism.',         'neoplatonism.')
    WHEN id GLOB 'Egyptian.*'             THEN REPLACE(id, 'Egyptian.',             'egyptian.')
    WHEN id GLOB 'Taoism.*'               THEN REPLACE(id, 'Taoism.',               'taoism.')
    WHEN id GLOB 'Greek Mystery.*'        THEN REPLACE(id, 'Greek Mystery.',        'greek_mystery.')
    WHEN id GLOB 'Christian Mysticism.*'  THEN REPLACE(id, 'Christian Mysticism.',  'christian_mysticism.')
    WHEN id GLOB 'Zoroastrianism.*'       THEN REPLACE(id, 'Zoroastrianism.',       'zoroastrianism.')
    WHEN id GLOB 'Jewish Mysticism.*'     THEN REPLACE(id, 'Jewish Mysticism.',     'jewish_mysticism.')
    WHEN id GLOB 'Buddhism.*'             THEN REPLACE(id, 'Buddhism.',             'buddhism.')
    WHEN id GLOB 'Mesopotamian.*'         THEN REPLACE(id, 'Mesopotamian.',         'mesopotamian.')
    ELSE id
END
WHERE type='chunk' AND (
        id GLOB 'Neoplatonism.*' OR id GLOB 'Egyptian.*' OR id GLOB 'Taoism.*'
     OR id GLOB 'Greek Mystery.*' OR id GLOB 'Christian Mysticism.*'
     OR id GLOB 'Zoroastrianism.*' OR id GLOB 'Jewish Mysticism.*'
     OR id GLOB 'Buddhism.*' OR id GLOB 'Mesopotamian.*'
);

-- edges.source_id
UPDATE edges SET source_id = CASE
    WHEN source_id GLOB 'Neoplatonism.*'         THEN REPLACE(source_id, 'Neoplatonism.',         'neoplatonism.')
    WHEN source_id GLOB 'Egyptian.*'             THEN REPLACE(source_id, 'Egyptian.',             'egyptian.')
    WHEN source_id GLOB 'Taoism.*'               THEN REPLACE(source_id, 'Taoism.',               'taoism.')
    WHEN source_id GLOB 'Greek Mystery.*'        THEN REPLACE(source_id, 'Greek Mystery.',        'greek_mystery.')
    WHEN source_id GLOB 'Christian Mysticism.*'  THEN REPLACE(source_id, 'Christian Mysticism.',  'christian_mysticism.')
    WHEN source_id GLOB 'Zoroastrianism.*'       THEN REPLACE(source_id, 'Zoroastrianism.',       'zoroastrianism.')
    WHEN source_id GLOB 'Jewish Mysticism.*'     THEN REPLACE(source_id, 'Jewish Mysticism.',     'jewish_mysticism.')
    WHEN source_id GLOB 'Buddhism.*'             THEN REPLACE(source_id, 'Buddhism.',             'buddhism.')
    WHEN source_id GLOB 'Mesopotamian.*'         THEN REPLACE(source_id, 'Mesopotamian.',         'mesopotamian.')
    ELSE source_id
END
WHERE source_id GLOB 'Neoplatonism.*' OR source_id GLOB 'Egyptian.*' OR source_id GLOB 'Taoism.*'
   OR source_id GLOB 'Greek Mystery.*' OR source_id GLOB 'Christian Mysticism.*'
   OR source_id GLOB 'Zoroastrianism.*' OR source_id GLOB 'Jewish Mysticism.*'
   OR source_id GLOB 'Buddhism.*' OR source_id GLOB 'Mesopotamian.*';

-- edges.target_id
UPDATE edges SET target_id = CASE
    WHEN target_id GLOB 'Neoplatonism.*'         THEN REPLACE(target_id, 'Neoplatonism.',         'neoplatonism.')
    WHEN target_id GLOB 'Egyptian.*'             THEN REPLACE(target_id, 'Egyptian.',             'egyptian.')
    WHEN target_id GLOB 'Taoism.*'               THEN REPLACE(target_id, 'Taoism.',               'taoism.')
    WHEN target_id GLOB 'Greek Mystery.*'        THEN REPLACE(target_id, 'Greek Mystery.',        'greek_mystery.')
    WHEN target_id GLOB 'Christian Mysticism.*'  THEN REPLACE(target_id, 'Christian Mysticism.',  'christian_mysticism.')
    WHEN target_id GLOB 'Zoroastrianism.*'       THEN REPLACE(target_id, 'Zoroastrianism.',       'zoroastrianism.')
    WHEN target_id GLOB 'Jewish Mysticism.*'     THEN REPLACE(target_id, 'Jewish Mysticism.',     'jewish_mysticism.')
    WHEN target_id GLOB 'Buddhism.*'             THEN REPLACE(target_id, 'Buddhism.',             'buddhism.')
    WHEN target_id GLOB 'Mesopotamian.*'         THEN REPLACE(target_id, 'Mesopotamian.',         'mesopotamian.')
    ELSE target_id
END
WHERE target_id GLOB 'Neoplatonism.*' OR target_id GLOB 'Egyptian.*' OR target_id GLOB 'Taoism.*'
   OR target_id GLOB 'Greek Mystery.*' OR target_id GLOB 'Christian Mysticism.*'
   OR target_id GLOB 'Zoroastrianism.*' OR target_id GLOB 'Jewish Mysticism.*'
   OR target_id GLOB 'Buddhism.*' OR target_id GLOB 'Mesopotamian.*';

-- chunk_embeddings.chunk_id (PK)
UPDATE chunk_embeddings SET chunk_id = CASE
    WHEN chunk_id GLOB 'Neoplatonism.*'         THEN REPLACE(chunk_id, 'Neoplatonism.',         'neoplatonism.')
    WHEN chunk_id GLOB 'Egyptian.*'             THEN REPLACE(chunk_id, 'Egyptian.',             'egyptian.')
    WHEN chunk_id GLOB 'Taoism.*'               THEN REPLACE(chunk_id, 'Taoism.',               'taoism.')
    WHEN chunk_id GLOB 'Greek Mystery.*'        THEN REPLACE(chunk_id, 'Greek Mystery.',        'greek_mystery.')
    WHEN chunk_id GLOB 'Christian Mysticism.*'  THEN REPLACE(chunk_id, 'Christian Mysticism.',  'christian_mysticism.')
    WHEN chunk_id GLOB 'Zoroastrianism.*'       THEN REPLACE(chunk_id, 'Zoroastrianism.',       'zoroastrianism.')
    WHEN chunk_id GLOB 'Jewish Mysticism.*'     THEN REPLACE(chunk_id, 'Jewish Mysticism.',     'jewish_mysticism.')
    WHEN chunk_id GLOB 'Buddhism.*'             THEN REPLACE(chunk_id, 'Buddhism.',             'buddhism.')
    WHEN chunk_id GLOB 'Mesopotamian.*'         THEN REPLACE(chunk_id, 'Mesopotamian.',         'mesopotamian.')
    ELSE chunk_id
END
WHERE chunk_id GLOB 'Neoplatonism.*' OR chunk_id GLOB 'Egyptian.*' OR chunk_id GLOB 'Taoism.*'
   OR chunk_id GLOB 'Greek Mystery.*' OR chunk_id GLOB 'Christian Mysticism.*'
   OR chunk_id GLOB 'Zoroastrianism.*' OR chunk_id GLOB 'Jewish Mysticism.*'
   OR chunk_id GLOB 'Buddhism.*' OR chunk_id GLOB 'Mesopotamian.*';

-- staged_tags.chunk_id
UPDATE staged_tags SET chunk_id = CASE
    WHEN chunk_id GLOB 'Neoplatonism.*'         THEN REPLACE(chunk_id, 'Neoplatonism.',         'neoplatonism.')
    WHEN chunk_id GLOB 'Egyptian.*'             THEN REPLACE(chunk_id, 'Egyptian.',             'egyptian.')
    WHEN chunk_id GLOB 'Taoism.*'               THEN REPLACE(chunk_id, 'Taoism.',               'taoism.')
    WHEN chunk_id GLOB 'Greek Mystery.*'        THEN REPLACE(chunk_id, 'Greek Mystery.',        'greek_mystery.')
    WHEN chunk_id GLOB 'Christian Mysticism.*'  THEN REPLACE(chunk_id, 'Christian Mysticism.',  'christian_mysticism.')
    WHEN chunk_id GLOB 'Zoroastrianism.*'       THEN REPLACE(chunk_id, 'Zoroastrianism.',       'zoroastrianism.')
    WHEN chunk_id GLOB 'Jewish Mysticism.*'     THEN REPLACE(chunk_id, 'Jewish Mysticism.',     'jewish_mysticism.')
    WHEN chunk_id GLOB 'Buddhism.*'             THEN REPLACE(chunk_id, 'Buddhism.',             'buddhism.')
    WHEN chunk_id GLOB 'Mesopotamian.*'         THEN REPLACE(chunk_id, 'Mesopotamian.',         'mesopotamian.')
    ELSE chunk_id
END
WHERE chunk_id GLOB 'Neoplatonism.*' OR chunk_id GLOB 'Egyptian.*' OR chunk_id GLOB 'Taoism.*'
   OR chunk_id GLOB 'Greek Mystery.*' OR chunk_id GLOB 'Christian Mysticism.*'
   OR chunk_id GLOB 'Zoroastrianism.*' OR chunk_id GLOB 'Jewish Mysticism.*'
   OR chunk_id GLOB 'Buddhism.*' OR chunk_id GLOB 'Mesopotamian.*';

-- staged_edges.source_chunk
UPDATE staged_edges SET source_chunk = CASE
    WHEN source_chunk GLOB 'Neoplatonism.*'         THEN REPLACE(source_chunk, 'Neoplatonism.',         'neoplatonism.')
    WHEN source_chunk GLOB 'Egyptian.*'             THEN REPLACE(source_chunk, 'Egyptian.',             'egyptian.')
    WHEN source_chunk GLOB 'Taoism.*'               THEN REPLACE(source_chunk, 'Taoism.',               'taoism.')
    WHEN source_chunk GLOB 'Greek Mystery.*'        THEN REPLACE(source_chunk, 'Greek Mystery.',        'greek_mystery.')
    WHEN source_chunk GLOB 'Christian Mysticism.*'  THEN REPLACE(source_chunk, 'Christian Mysticism.',  'christian_mysticism.')
    WHEN source_chunk GLOB 'Zoroastrianism.*'       THEN REPLACE(source_chunk, 'Zoroastrianism.',       'zoroastrianism.')
    WHEN source_chunk GLOB 'Jewish Mysticism.*'     THEN REPLACE(source_chunk, 'Jewish Mysticism.',     'jewish_mysticism.')
    WHEN source_chunk GLOB 'Buddhism.*'             THEN REPLACE(source_chunk, 'Buddhism.',             'buddhism.')
    WHEN source_chunk GLOB 'Mesopotamian.*'         THEN REPLACE(source_chunk, 'Mesopotamian.',         'mesopotamian.')
    ELSE source_chunk
END
WHERE source_chunk GLOB 'Neoplatonism.*' OR source_chunk GLOB 'Egyptian.*' OR source_chunk GLOB 'Taoism.*'
   OR source_chunk GLOB 'Greek Mystery.*' OR source_chunk GLOB 'Christian Mysticism.*'
   OR source_chunk GLOB 'Zoroastrianism.*' OR source_chunk GLOB 'Jewish Mysticism.*'
   OR source_chunk GLOB 'Buddhism.*' OR source_chunk GLOB 'Mesopotamian.*';

-- staged_edges.target_chunk
UPDATE staged_edges SET target_chunk = CASE
    WHEN target_chunk GLOB 'Neoplatonism.*'         THEN REPLACE(target_chunk, 'Neoplatonism.',         'neoplatonism.')
    WHEN target_chunk GLOB 'Egyptian.*'             THEN REPLACE(target_chunk, 'Egyptian.',             'egyptian.')
    WHEN target_chunk GLOB 'Taoism.*'               THEN REPLACE(target_chunk, 'Taoism.',               'taoism.')
    WHEN target_chunk GLOB 'Greek Mystery.*'        THEN REPLACE(target_chunk, 'Greek Mystery.',        'greek_mystery.')
    WHEN target_chunk GLOB 'Christian Mysticism.*'  THEN REPLACE(target_chunk, 'Christian Mysticism.',  'christian_mysticism.')
    WHEN target_chunk GLOB 'Zoroastrianism.*'       THEN REPLACE(target_chunk, 'Zoroastrianism.',       'zoroastrianism.')
    WHEN target_chunk GLOB 'Jewish Mysticism.*'     THEN REPLACE(target_chunk, 'Jewish Mysticism.',     'jewish_mysticism.')
    WHEN target_chunk GLOB 'Buddhism.*'             THEN REPLACE(target_chunk, 'Buddhism.',             'buddhism.')
    WHEN target_chunk GLOB 'Mesopotamian.*'         THEN REPLACE(target_chunk, 'Mesopotamian.',         'mesopotamian.')
    ELSE target_chunk
END
WHERE target_chunk GLOB 'Neoplatonism.*' OR target_chunk GLOB 'Egyptian.*' OR target_chunk GLOB 'Taoism.*'
   OR target_chunk GLOB 'Greek Mystery.*' OR target_chunk GLOB 'Christian Mysticism.*'
   OR target_chunk GLOB 'Zoroastrianism.*' OR target_chunk GLOB 'Jewish Mysticism.*'
   OR target_chunk GLOB 'Buddhism.*' OR target_chunk GLOB 'Mesopotamian.*';

-- tagging_progress.chunk_id (PK)
UPDATE tagging_progress SET chunk_id = CASE
    WHEN chunk_id GLOB 'Neoplatonism.*'         THEN REPLACE(chunk_id, 'Neoplatonism.',         'neoplatonism.')
    WHEN chunk_id GLOB 'Egyptian.*'             THEN REPLACE(chunk_id, 'Egyptian.',             'egyptian.')
    WHEN chunk_id GLOB 'Taoism.*'               THEN REPLACE(chunk_id, 'Taoism.',               'taoism.')
    WHEN chunk_id GLOB 'Greek Mystery.*'        THEN REPLACE(chunk_id, 'Greek Mystery.',        'greek_mystery.')
    WHEN chunk_id GLOB 'Christian Mysticism.*'  THEN REPLACE(chunk_id, 'Christian Mysticism.',  'christian_mysticism.')
    WHEN chunk_id GLOB 'Zoroastrianism.*'       THEN REPLACE(chunk_id, 'Zoroastrianism.',       'zoroastrianism.')
    WHEN chunk_id GLOB 'Jewish Mysticism.*'     THEN REPLACE(chunk_id, 'Jewish Mysticism.',     'jewish_mysticism.')
    WHEN chunk_id GLOB 'Buddhism.*'             THEN REPLACE(chunk_id, 'Buddhism.',             'buddhism.')
    WHEN chunk_id GLOB 'Mesopotamian.*'         THEN REPLACE(chunk_id, 'Mesopotamian.',         'mesopotamian.')
    ELSE chunk_id
END
WHERE chunk_id GLOB 'Neoplatonism.*' OR chunk_id GLOB 'Egyptian.*' OR chunk_id GLOB 'Taoism.*'
   OR chunk_id GLOB 'Greek Mystery.*' OR chunk_id GLOB 'Christian Mysticism.*'
   OR chunk_id GLOB 'Zoroastrianism.*' OR chunk_id GLOB 'Jewish Mysticism.*'
   OR chunk_id GLOB 'Buddhism.*' OR chunk_id GLOB 'Mesopotamian.*';

-- staged_concepts.motivating_chunk (currently 0 rows but FK is real)
UPDATE staged_concepts SET motivating_chunk = CASE
    WHEN motivating_chunk GLOB 'Neoplatonism.*'         THEN REPLACE(motivating_chunk, 'Neoplatonism.',         'neoplatonism.')
    WHEN motivating_chunk GLOB 'Egyptian.*'             THEN REPLACE(motivating_chunk, 'Egyptian.',             'egyptian.')
    WHEN motivating_chunk GLOB 'Taoism.*'               THEN REPLACE(motivating_chunk, 'Taoism.',               'taoism.')
    WHEN motivating_chunk GLOB 'Greek Mystery.*'        THEN REPLACE(motivating_chunk, 'Greek Mystery.',        'greek_mystery.')
    WHEN motivating_chunk GLOB 'Christian Mysticism.*'  THEN REPLACE(motivating_chunk, 'Christian Mysticism.',  'christian_mysticism.')
    WHEN motivating_chunk GLOB 'Zoroastrianism.*'       THEN REPLACE(motivating_chunk, 'Zoroastrianism.',       'zoroastrianism.')
    WHEN motivating_chunk GLOB 'Jewish Mysticism.*'     THEN REPLACE(motivating_chunk, 'Jewish Mysticism.',     'jewish_mysticism.')
    WHEN motivating_chunk GLOB 'Buddhism.*'             THEN REPLACE(motivating_chunk, 'Buddhism.',             'buddhism.')
    WHEN motivating_chunk GLOB 'Mesopotamian.*'         THEN REPLACE(motivating_chunk, 'Mesopotamian.',         'mesopotamian.')
    ELSE motivating_chunk
END
WHERE motivating_chunk GLOB 'Neoplatonism.*' OR motivating_chunk GLOB 'Egyptian.*' OR motivating_chunk GLOB 'Taoism.*'
   OR motivating_chunk GLOB 'Greek Mystery.*' OR motivating_chunk GLOB 'Christian Mysticism.*'
   OR motivating_chunk GLOB 'Zoroastrianism.*' OR motivating_chunk GLOB 'Jewish Mysticism.*'
   OR motivating_chunk GLOB 'Buddhism.*' OR motivating_chunk GLOB 'Mesopotamian.*';

-- ── 5. Post-migration verification (must be empty before COMMIT) ────────────

SELECT '== verification: any chunk_id refs still in display-name form? (must be 0) ==' AS audit;

SELECT 'nodes',                     COUNT(*) FROM nodes WHERE type='chunk' AND id GLOB '*[A-Z]*' AND id NOT GLOB 'concept.*'
UNION ALL
SELECT 'edges (source_id)',         COUNT(*) FROM edges WHERE source_id GLOB '* *' OR (source_id GLOB '*[A-Z]*' AND source_id NOT GLOB 'concept.*')
UNION ALL
SELECT 'edges (target_id)',         COUNT(*) FROM edges WHERE target_id GLOB '* *' OR (target_id GLOB '*[A-Z]*' AND target_id NOT GLOB 'concept.*')
UNION ALL
SELECT 'chunk_embeddings',          COUNT(*) FROM chunk_embeddings WHERE chunk_id GLOB '* *' OR chunk_id GLOB '*[A-Z]*'
UNION ALL
SELECT 'staged_tags',               COUNT(*) FROM staged_tags WHERE chunk_id GLOB '* *' OR chunk_id GLOB '*[A-Z]*'
UNION ALL
SELECT 'staged_edges (source)',     COUNT(*) FROM staged_edges WHERE source_chunk GLOB '* *' OR source_chunk GLOB '*[A-Z]*'
UNION ALL
SELECT 'staged_edges (target)',     COUNT(*) FROM staged_edges WHERE target_chunk GLOB '* *' OR target_chunk GLOB '*[A-Z]*'
UNION ALL
SELECT 'tagging_progress',          COUNT(*) FROM tagging_progress WHERE chunk_id GLOB '* *' OR chunk_id GLOB '*[A-Z]*'
UNION ALL
SELECT 'staged_concepts',           COUNT(*) FROM staged_concepts WHERE motivating_chunk GLOB '* *' OR motivating_chunk GLOB '*[A-Z]*';

-- foreign_key_check returns one row per violation. Must be empty.
SELECT '== foreign_key_check (must be empty) ==' AS audit;
PRAGMA foreign_key_check;

COMMIT;

-- ── 6. Re-enable FKs ────────────────────────────────────────────────────────

PRAGMA foreign_keys = ON;
