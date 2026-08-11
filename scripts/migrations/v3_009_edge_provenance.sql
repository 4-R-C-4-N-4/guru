-- ============================================================================
-- v3_009_edge_provenance.sql
--
-- Phase 0.2 of the edge pipeline roadmap (rellm docs/edges/edge-roadmap.md):
-- stop the unrecoverable provenance loss in the edge pipeline.
--
--   1. staged_edges.similarity — the retrieval score that triggered the
--      proposal. propose_edges.py never persisted it, which is why
--      --min-similarity was never tunable against outcomes. Backfillable for
--      existing rows from chunk_embeddings (nomic-embed-text, L2-normalised,
--      cosine == dot); run scripts/backfill_edge_similarity.py after this
--      migration.
--
--   2. staged_edges.presentation_order — 'ab' | 'ba', which passage the model
--      saw as Passage A. pair_key() canonicalises before insert
--      (propose_edges.py:164), destroying presentation order; the judge flips
--      its verdict on 21% of pairs under order reversal, so without this
--      column AB/BA symmetry is permanently unauditable from the store.
--      NULL on all existing rows — historically unrecoverable by design.
--
--   3. edge_progress — mirrors tagging_progress, plus (model, prompt_version)
--      since sweep completion is relative to the model and prompt that swept.
--      836 chunks (15%) have never been evaluated and nothing records what
--      has been swept. Seeded EMPTY, deliberately: nothing recorded which
--      chunks a historical sweep actually completed, and inferred "done"
--      markers under the top-5-with-floor regime would suppress exactly the
--      re-coverage a Phase 2 wide sweep is for. Populate going forward only.
--
-- Additive only: no table recreation, no index changes, no rows touched.
-- CHECK on presentation_order passes NULL (SQLite three-valued logic), so
-- existing rows are unaffected.
--
-- Idempotent: no. ADD COLUMN aborts on the duplicate column if re-run after a
-- committed pass — same convention as v3_005.
--
-- Usage:
--   sqlite3 data/guru.db < scripts/migrations/v3_009_edge_provenance.sql
-- ============================================================================

PRAGMA foreign_keys = OFF;
.bail on
.headers on
.mode column

BEGIN TRANSACTION;

ALTER TABLE staged_edges ADD COLUMN similarity REAL;
ALTER TABLE staged_edges ADD COLUMN presentation_order TEXT
    CHECK(presentation_order IN ('ab', 'ba'));

CREATE TABLE IF NOT EXISTS edge_progress (
    chunk_id        TEXT PRIMARY KEY REFERENCES nodes(id),
    model           TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    completed_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- ----- verification --------------------------------------------------------

SELECT 'verify: staged_edges columns (similarity + presentation_order present)' AS check_name;
SELECT name FROM pragma_table_info('staged_edges')
 WHERE name IN ('similarity', 'presentation_order');

SELECT 'verify: new columns all NULL (no rows touched)' AS check_name,
       COUNT(*) AS non_null_rows
  FROM staged_edges
 WHERE similarity IS NOT NULL OR presentation_order IS NOT NULL;

SELECT 'verify: edge_progress exists and is empty' AS check_name,
       COUNT(*) AS rows
  FROM edge_progress;

SELECT 'verify: staged_edges row count unchanged (compare against manifest)' AS check_name,
       COUNT(*) AS total_rows
  FROM staged_edges;

COMMIT;

PRAGMA foreign_keys = ON;
