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
    model           TEXT,
    prompt_version  TEXT
);

CREATE INDEX IF NOT EXISTS idx_staged_edges_source ON staged_edges(source_chunk);
CREATE INDEX IF NOT EXISTS idx_staged_edges_target ON staged_edges(target_chunk);
CREATE INDEX IF NOT EXISTS idx_staged_edges_status ON staged_edges(status);
CREATE INDEX IF NOT EXISTS idx_staged_edges_type   ON staged_edges(edge_type);

-- Partial UNIQUE: only enforce on pending rows so a re-propose against the
-- same model doesn't dupe-violate, while frozen settled rows
-- (accepted/rejected/reclassified) can coexist with new pending proposals
-- from a different model run. Mirrors v3_001 staged_tags pattern.
CREATE UNIQUE INDEX IF NOT EXISTS idx_staged_edges_provenance_unique
    ON staged_edges(source_chunk, target_chunk, model, prompt_version)
    WHERE status = 'pending';

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

-- ============================================================
-- CONCEPT HIERARCHY (domain → family → concept)
-- See docs/concept-hierarchy/design.md §5. Applied to existing DBs by
-- scripts/migrations/v3_006_concept_families.sql.
-- ============================================================

-- Domains (parent_id NULL) and families (parent_id → domain) in one
-- self-referential table. Family IDs are composite ('cosmology.cosmic_agents'),
-- domain IDs are bare ('cosmology'). Tier is implicit: parent_id IS NULL ⟺ domain.
CREATE TABLE IF NOT EXISTS concept_families (
    id          TEXT PRIMARY KEY,
    parent_id   TEXT REFERENCES concept_families(id),
    label       TEXT NOT NULL,
    definition  TEXT NOT NULL
);

-- "Families under domain X" — hot lookup for query expansion.
CREATE INDEX IF NOT EXISTS idx_concept_families_parent
    ON concept_families(parent_id);

-- Concept→family affiliations. is_primary=1 is the canonical home (exactly one
-- per concept); is_primary=0 rows are secondary cross-cutting affiliations.
CREATE TABLE IF NOT EXISTS concept_family_membership (
    concept_id  TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    family_id   TEXT NOT NULL REFERENCES concept_families(id),
    is_primary  INTEGER NOT NULL DEFAULT 0
                    CHECK(is_primary IN (0, 1)),
    PRIMARY KEY (concept_id, family_id)
);

-- Enforce exactly one primary family per concept.
CREATE UNIQUE INDEX IF NOT EXISTS idx_concept_primary_family
    ON concept_family_membership(concept_id) WHERE is_primary = 1;

-- Reverse lookup: which concepts are in family X (primary or secondary).
CREATE INDEX IF NOT EXISTS idx_concept_family_membership_family
    ON concept_family_membership(family_id);

-- User-facing concept synonyms. alias stored lowercase (Python-side in
-- sync_taxonomy.py; CHECK is an ASCII-range secondary defense in SQLite).
CREATE TABLE IF NOT EXISTS concept_aliases (
    concept_id  TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    alias       TEXT NOT NULL CHECK(alias = LOWER(alias)),
    PRIMARY KEY (concept_id, alias)
);

CREATE INDEX IF NOT EXISTS idx_concept_aliases_alias
    ON concept_aliases(alias);

-- User-facing family (and domain) synonyms; same shape as concept_aliases.
CREATE TABLE IF NOT EXISTS family_aliases (
    family_id   TEXT NOT NULL REFERENCES concept_families(id) ON DELETE CASCADE,
    alias       TEXT NOT NULL CHECK(alias = LOWER(alias)),
    PRIMARY KEY (family_id, alias)
);

CREATE INDEX IF NOT EXISTS idx_family_aliases_alias
    ON family_aliases(alias);
