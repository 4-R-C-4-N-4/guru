-- corpus-schema.sql
--
-- Canonical Postgres schema for the guru corpus. This file is the
-- integration contract between guru-pipeline (producer) and guru-web
-- (consumer); it MUST be byte-identical in both repositories. CI
-- compares hashes across repos on every push.
--
-- Loaded by: `gunzip -c export/guru-corpus.sql.gz | psql $DATABASE_URL`
--            inside the single-transaction artifact produced by
--            scripts/export.py.
--
-- Indexes (including the pgvector HNSW index on chunks.embedding) are
-- intentionally omitted here — they are created at the end of the export
-- artifact, after all bulk inserts, because HNSW build cost is
-- proportional to insert order and batching.
--
-- Schema version: bump SCHEMA_VERSION in scripts/export.py and the
-- EXPECTED_SCHEMA_VERSION constant in guru-web on every change.
--
-- CHANGELOG:
--   v2 (2026-04-28) Schema-isolated export (corpus_new + atomic swap).
--                     Export uses COPY FROM STDIN instead of INSERT.
--                     DDL stays unprefixed; export.py prefixes at emission.
--   v3 (2026-05-27) Concept hierarchy: concept_families / concept_family_membership
--                     / concept_aliases / family_aliases tables + concepts.family_id.
--                     Indexes remain in export.py:emit_indexes per the rule above.
--   v4 (2026-07-04) Document-knowledge layer: works + texts.work_id +
--                     work_dossiers + summary_nodes (see v4 block at end).

CREATE EXTENSION IF NOT EXISTS vector;

-- ─── traditions ──────────────────────────────────────────────────────
-- A tradition is the top-level grouping (Gnosticism, Neoplatonism, ...).
-- `color` is optional — used by the web UI for per-tradition theming.

CREATE TABLE traditions (
    id          TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    description TEXT,
    color       TEXT
);

-- ─── texts ───────────────────────────────────────────────────────────
-- A text is a specific source work within a tradition. `sections_format`
-- tells the UI how to render citation addresses (e.g. "verse", "logion",
-- "chapter.verse", "book.section").

CREATE TABLE texts (
    id              TEXT PRIMARY KEY,
    tradition       TEXT NOT NULL REFERENCES traditions(id),
    label           TEXT NOT NULL,
    translator      TEXT,
    source_url      TEXT,
    sections_format TEXT
);

-- ─── concepts ────────────────────────────────────────────────────────
-- Hand-curated thematic anchors (e.g. "divine-light", "emanation").
-- `domain` groups concepts into categories (cosmology, soteriology, ...).

CREATE TABLE concepts (
    id         TEXT PRIMARY KEY,
    label      TEXT NOT NULL,
    domain     TEXT,
    definition TEXT
);

-- ─── chunks ──────────────────────────────────────────────────────────
-- The atomic citation-addressable unit of a text. `tradition` and
-- `text_name` are denormalized for zero-join retrieval — the vector
-- search path returns tradition/text_name/section without touching
-- traditions or texts.
--
-- `section_path` is the address broken into components (e.g. ["1","23"]
-- for "1.23"); the bare `section` keeps the printable form.
--
-- `embedding` is pinned at 768 dims to match ollama/nomic-embed-text
-- (the current canonical model recorded in corpus_metadata). Changing
-- the model requires a full re-embed AND a dimension update here.

CREATE TABLE chunks (
    id            TEXT PRIMARY KEY,
    text_id       TEXT NOT NULL REFERENCES texts(id),
    tradition     TEXT NOT NULL REFERENCES traditions(id),
    text_name     TEXT NOT NULL,
    section       TEXT,
    section_path  TEXT[],
    translator    TEXT,
    body          TEXT NOT NULL,
    token_count   INTEGER NOT NULL,
    embedding     VECTOR(768) NOT NULL
);

-- ─── edges ───────────────────────────────────────────────────────────
-- Typed relationships between any two nodes (chunk↔concept,
-- concept↔concept, chunk↔tradition, etc.). `source` and `target` are
-- intentionally untyped TEXT references — edges are polymorphic across
-- chunks/concepts/traditions, so no single FK would hold. The web app
-- resolves endpoints by lookup against the appropriate table.
--
-- `tier` encodes confidence (verified ✓ / proposed ◇ / inferred ~);
-- `weight` is an optional similarity / relevance score attached by the
-- pipeline for downstream ranking.

CREATE TABLE edges (
    source     TEXT NOT NULL,
    target     TEXT NOT NULL,
    edge_type  TEXT NOT NULL,
    tier       TEXT NOT NULL,
    weight     REAL,
    annotation TEXT,
    PRIMARY KEY (source, target, edge_type)
);

-- ─── corpus_metadata ─────────────────────────────────────────────────
-- Key/value manifest written as the *last* statement by export.py, so a
-- mid-load failure leaves this table unset and the web app refuses to
-- serve. Required keys: schema_version, embedding_model, embedding_dim,
-- corpus_version, exported_at, source_commit_sha.

CREATE TABLE corpus_metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ─── concept hierarchy (domain → family → concept) ───────────────────
-- Mirrors the SQLite shape (scripts/migrations/v3_006_concept_families.sql).
-- See docs/concept-hierarchy/design.md §5, §10. Indexes are emitted post-load
-- by export.py:emit_indexes (this file stays index-free, per the header rule).
-- `is_primary` is native BOOLEAN here vs 0/1 INTEGER in SQLite — export.py
-- converts at emit time.

CREATE TABLE concept_families (
    id          TEXT PRIMARY KEY,
    parent_id   TEXT REFERENCES concept_families(id),
    label       TEXT NOT NULL,
    definition  TEXT NOT NULL
);

CREATE TABLE concept_family_membership (
    concept_id  TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    family_id   TEXT NOT NULL REFERENCES concept_families(id),
    is_primary  BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (concept_id, family_id)
);

CREATE TABLE concept_aliases (
    concept_id  TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    alias       TEXT NOT NULL CHECK(alias = LOWER(alias)),
    PRIMARY KEY (concept_id, alias)
);

CREATE TABLE family_aliases (
    family_id   TEXT NOT NULL REFERENCES concept_families(id) ON DELETE CASCADE,
    alias       TEXT NOT NULL CHECK(alias = LOWER(alias)),
    PRIMARY KEY (family_id, alias)
);

-- Denormalised primary family on concepts for two-way-join filters.
ALTER TABLE concepts ADD COLUMN family_id TEXT REFERENCES concept_families(id);

COMMENT ON COLUMN concepts.family_id IS 'Denormalised primary family for two-way-join filters. Maintained by export.py from concept_family_membership WHERE is_primary; do not edit at runtime.';
COMMENT ON COLUMN concepts.domain IS 'Derived from concept_families.parent_id of the row pointed at by family_id. Set by export.py only; do not edit at runtime. May be removed in a follow-on migration once src/lib/ queries no longer reference it.';

-- ─── v4: document-knowledge layer ────────────────────────────────────
-- v4 (2026-07-04) Works layer + document-knowledge: works, texts.work_id,
--                 work_dossiers, summary_nodes. Dossiers are PK-fetched (no
--                 embedding); summary_nodes are retrievable and share the
--                 768-dim space with chunks. Indexes remain in
--                 export.py:emit_indexes per the rule above.

-- ─── works ───────────────────────────────────────────────────────────
-- The dossier and level-2 summary unit (V10, guru docs/summary/
-- work-grouping.md): 9 grouped works absorb 168 serialization-shard texts;
-- every other text is a singleton work. member_text_ids is reading order.
CREATE TABLE works (
    id              TEXT PRIMARY KEY,
    tradition       TEXT NOT NULL REFERENCES traditions(id),
    label           TEXT NOT NULL,
    member_text_ids TEXT[] NOT NULL
);

-- Every text belongs to exactly one work (singleton work_id = text id).
-- Table is empty at DDL time (fresh corpus_new), so NOT NULL is safe.
ALTER TABLE texts ADD COLUMN work_id TEXT NOT NULL REFERENCES works(id);

-- ─── work_dossiers ───────────────────────────────────────────────────
-- One precomputed knowledge object per work. Injected into study-mode
-- prompts by PK lookup (text → texts.work_id → work_dossiers); never
-- retrieved, so no embedding column. Coverage is optional per work: a
-- missing dossier means "study mode without the dossier block", not an
-- error.
CREATE TABLE work_dossiers (
    work_id        TEXT PRIMARY KEY REFERENCES works(id),
    summary        TEXT NOT NULL,
    context        TEXT NOT NULL,
    structure      JSONB NOT NULL,
    key_figures    JSONB NOT NULL,
    key_terms      JSONB NOT NULL,
    themes         JSONB NOT NULL,
    reading_notes  TEXT,
    manifest_notes TEXT,
    generated_by   TEXT NOT NULL
);

-- ─── summary_nodes ───────────────────────────────────────────────────
-- Hierarchical summaries (level 1 = section span, level 2 = whole work).
-- `tradition` is denormalized like chunks so buildScopeFilter() applies
-- verbatim. text_id is NULL on level-2 rows of multi-member works.
-- child_chunk_ids keeps every summary expandable to primary chunks — the
-- citation contract's escape hatch (no FK: Postgres can't FK array
-- elements; integrity is validated at export). NOT graph nodes: nothing
-- in edges may reference a summary id.
CREATE TABLE summary_nodes (
    id              TEXT PRIMARY KEY,
    work_id         TEXT NOT NULL REFERENCES works(id),
    text_id         TEXT REFERENCES texts(id),
    tradition       TEXT NOT NULL REFERENCES traditions(id),
    level           SMALLINT NOT NULL CHECK (level IN (1, 2)),
    section_span    TEXT,
    child_chunk_ids TEXT[] NOT NULL,
    body            TEXT NOT NULL,
    token_count     INTEGER NOT NULL,
    embedding       VECTOR(768) NOT NULL
);
