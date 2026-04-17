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
