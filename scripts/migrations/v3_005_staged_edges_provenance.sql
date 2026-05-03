-- ============================================================================
-- v3_005_staged_edges_provenance.sql
--
-- Add (model, prompt_version) provenance columns to staged_edges, mirroring
-- the v3_001 pattern for staged_tags. Replaces the table-level
-- UNIQUE(source_chunk, target_chunk) with a partial UNIQUE index on
-- (source_chunk, target_chunk, model, prompt_version) WHERE status = 'pending',
-- so multi-model A/B rows can coexist for the same chunk pair while still
-- preventing same-model re-proposal duplicates.
--
-- Backfill rationale: per operator confirmation the existing staged_edges rows
-- were all produced by Mistral-Small-3.2-24B-Instruct-2506-UD-Q5_K_XL.gguf
-- with the v1 prompt template (the SYSTEM_PROMPT + build_pair_prompt body
-- in scripts/propose_edges.py at the time of this migration). Future prompt
-- changes bump to v2.
--
-- Partial UNIQUE rationale (mirror of v3_001): only enforce on
-- status='pending'. Once a row transitions to accepted/rejected/reclassified
-- it is frozen audit history; a future re-propose against the same model
-- must not UNIQUE-violate against settled past.
--
-- Table recreation rationale: SQLite cannot drop a table-level UNIQUE
-- constraint in place, so we copy → drop → rename. Wrapped in a single
-- transaction with .bail on; safe to rerun only if the prior run committed.
--
-- Idempotent: ADD COLUMN errors abort early; the migration assumes a clean
-- pre-state. After successful run, re-running aborts on the duplicate column.
--
-- Usage:
--   sqlite3 data/guru.db < scripts/migrations/v3_005_staged_edges_provenance.sql
-- ============================================================================

PRAGMA foreign_keys = OFF;
.bail on
.headers on
.mode column

BEGIN TRANSACTION;

-- ----- columns + backfill on the existing table ----------------------------

ALTER TABLE staged_edges ADD COLUMN model TEXT;
ALTER TABLE staged_edges ADD COLUMN prompt_version TEXT;

UPDATE staged_edges
   SET model = 'Mistral-Small-3.2-24B-Instruct-2506-UD-Q5_K_XL.gguf',
       prompt_version = 'v1'
 WHERE model IS NULL;

-- ----- recreate table without the (source_chunk, target_chunk) UNIQUE -------
-- The partial UNIQUE index below replaces it with a model-aware variant.

CREATE TABLE staged_edges_new (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_chunk    TEXT NOT NULL REFERENCES nodes(id),
    target_chunk    TEXT NOT NULL REFERENCES nodes(id),
    edge_type       TEXT NOT NULL CHECK(edge_type IN ('PARALLELS','CONTRASTS','surface_only','unrelated')),
    confidence      REAL NOT NULL DEFAULT 0.0,
    justification   TEXT,
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending','accepted','rejected','reclassified')),
    tier            TEXT NOT NULL DEFAULT 'proposed'
                        CHECK(tier IN ('verified','proposed')),
    reviewed_by     TEXT,
    reviewed_at     TEXT,
    model           TEXT,
    prompt_version  TEXT
);

INSERT INTO staged_edges_new
    (id, source_chunk, target_chunk, edge_type, confidence, justification,
     status, tier, reviewed_by, reviewed_at, model, prompt_version)
SELECT
    id, source_chunk, target_chunk, edge_type, confidence, justification,
    status, tier, reviewed_by, reviewed_at, model, prompt_version
FROM staged_edges;

DROP TABLE staged_edges;
ALTER TABLE staged_edges_new RENAME TO staged_edges;

-- ----- recreate the supporting indexes the original table had --------------

CREATE INDEX IF NOT EXISTS idx_staged_edges_source ON staged_edges(source_chunk);
CREATE INDEX IF NOT EXISTS idx_staged_edges_target ON staged_edges(target_chunk);
CREATE INDEX IF NOT EXISTS idx_staged_edges_status ON staged_edges(status);
CREATE INDEX IF NOT EXISTS idx_staged_edges_type   ON staged_edges(edge_type);

-- ----- the new partial UNIQUE index ----------------------------------------

CREATE UNIQUE INDEX IF NOT EXISTS idx_staged_edges_provenance_unique
    ON staged_edges(source_chunk, target_chunk, model, prompt_version)
    WHERE status = 'pending';

-- ----- verification: must come back with zero null rows --------------------

SELECT 'verify: rows missing provenance after backfill (must be 0)' AS check_name,
       COUNT(*) AS null_rows
  FROM staged_edges
 WHERE model IS NULL OR prompt_version IS NULL;

SELECT 'verify: provenance distribution by status' AS check_name;
SELECT model, prompt_version, status, COUNT(*) AS rows
  FROM staged_edges
 GROUP BY model, prompt_version, status
 ORDER BY model, status;

SELECT 'verify: indexes' AS check_name;
SELECT name FROM sqlite_master
 WHERE type='index'
   AND tbl_name='staged_edges'
 ORDER BY name;

COMMIT;

PRAGMA foreign_keys = ON;
