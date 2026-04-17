-- Guru Knowledge Graph Schema
-- SQLite — apply with: sqlite3 data/guru.db < scripts/schema.sql
-- Idempotent: uses IF NOT EXISTS everywhere.

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ============================================================
-- LIVE GRAPH
-- ============================================================

CREATE TABLE IF NOT EXISTS nodes (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL CHECK(type IN ('tradition','concept','chunk')),
    tradition_id TEXT REFERENCES nodes(id),
    label       TEXT NOT NULL,
    definition  TEXT,              -- populated for concept nodes
    metadata_json TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_tradition ON nodes(tradition_id);

CREATE TABLE IF NOT EXISTS edges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   TEXT NOT NULL REFERENCES nodes(id),
    target_id   TEXT NOT NULL REFERENCES nodes(id),
    type        TEXT NOT NULL CHECK(type IN ('BELONGS_TO','EXPRESSES','PARALLELS','CONTRASTS','DERIVES_FROM')),
    tier        TEXT NOT NULL DEFAULT 'inferred' CHECK(tier IN ('verified','proposed','inferred')),
    justification TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_edges_source    ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target    ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_type      ON edges(type);
CREATE UNIQUE INDEX IF NOT EXISTS idx_edges_unique ON edges(source_id, target_id, type);

-- ============================================================
-- EMBEDDINGS
-- ============================================================
-- Per-chunk dense vectors. Stored as float32 little-endian BLOBs so a
-- 768-dim vector takes 3 KB instead of ~15 KB as JSON. `dim` and `model`
-- are per-row so a partial re-embed (e.g. model change mid-migration) is
-- self-describing.

CREATE TABLE IF NOT EXISTS chunk_embeddings (
    chunk_id TEXT PRIMARY KEY REFERENCES nodes(id) ON DELETE CASCADE,
    dim      INTEGER NOT NULL,
    model    TEXT NOT NULL,
    vector   BLOB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_model ON chunk_embeddings(model);

-- ============================================================
-- STAGING — Pass B: LLM concept tagging
-- ============================================================

CREATE TABLE IF NOT EXISTS staged_tags (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id        TEXT NOT NULL REFERENCES nodes(id),
    concept_id      TEXT NOT NULL,              -- may not yet exist as node (is_new_concept)
    score           INTEGER NOT NULL CHECK(score BETWEEN 0 AND 3),
    justification   TEXT,
    is_new_concept  INTEGER NOT NULL DEFAULT 0,
    new_concept_def TEXT,
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending','accepted','rejected','reassigned')),
    reviewed_by     TEXT,
    reviewed_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_staged_tags_chunk   ON staged_tags(chunk_id);
CREATE INDEX IF NOT EXISTS idx_staged_tags_concept ON staged_tags(concept_id);
CREATE INDEX IF NOT EXISTS idx_staged_tags_status  ON staged_tags(status);

-- ============================================================
-- STAGING — Pass C: cross-tradition edge proposals
-- ============================================================

CREATE TABLE IF NOT EXISTS staged_edges (
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
    UNIQUE(source_chunk, target_chunk)
);

CREATE INDEX IF NOT EXISTS idx_staged_edges_source ON staged_edges(source_chunk);
CREATE INDEX IF NOT EXISTS idx_staged_edges_target ON staged_edges(target_chunk);
CREATE INDEX IF NOT EXISTS idx_staged_edges_status ON staged_edges(status);
CREATE INDEX IF NOT EXISTS idx_staged_edges_type   ON staged_edges(edge_type);

-- ============================================================
-- STAGING — new concept proposals from tagging
-- ============================================================

CREATE TABLE IF NOT EXISTS staged_concepts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    proposed_id       TEXT NOT NULL UNIQUE,
    definition        TEXT NOT NULL,
    motivating_chunk  TEXT REFERENCES nodes(id),
    status            TEXT NOT NULL DEFAULT 'pending'
                          CHECK(status IN ('pending','accepted','rejected')),
    reviewed_by       TEXT,
    reviewed_at       TEXT
);

-- ============================================================
-- BOOKKEEPING
-- ============================================================

CREATE TABLE IF NOT EXISTS tagging_progress (
    chunk_id        TEXT PRIMARY KEY REFERENCES nodes(id),
    completed_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
