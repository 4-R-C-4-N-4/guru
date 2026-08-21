-- v3_012: materialize derived parallels into guru.db (todo:675a76f8).
--
-- Replaces the data/derived_parallels/<timestamp>/ JSONL run-directory
-- artifact as node 16's output and export's PARALLELS source. Two tables:
--
--   derived_runs      — one row per generator run, full history. The summary
--                       dict ships verbatim in summary_json; generated_at,
--                       limit_concepts and edge_rows are promoted to columns
--                       because export's guards read them (freshness, the
--                       partial-run refusal, the zero-rows refusal).
--   derived_parallels — edge rows of the LATEST run only. Each run replaces
--                       the table wholesale inside one transaction; history
--                       of *summaries* is cheap and kept, history of 45k-row
--                       edge sets is not. edge_type/tier are not stored —
--                       every row is PARALLELS/inferred by construction and
--                       export reconstructs them.
--
-- These are derived-cache tables in the same category as chunk_embeddings:
-- written directly by the generator script, regenerable from tags + taxonomy
-- + scorer, and NOT part of the staged_*/review/apply flow.

CREATE TABLE IF NOT EXISTS derived_runs (
    run_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at   TEXT NOT NULL,
    limit_concepts INTEGER,            -- NULL = full run; export refuses partial runs
    edge_rows      INTEGER NOT NULL,
    summary_json   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS derived_parallels (
    run_id     INTEGER NOT NULL REFERENCES derived_runs(run_id),
    source     TEXT NOT NULL,
    target     TEXT NOT NULL,
    weight     REAL NOT NULL,
    annotation TEXT NOT NULL,
    PRIMARY KEY (source, target)
);

CREATE INDEX IF NOT EXISTS idx_derived_parallels_target ON derived_parallels(target);
