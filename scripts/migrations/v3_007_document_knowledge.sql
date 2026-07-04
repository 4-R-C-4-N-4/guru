-- v3_007_document_knowledge.sql — staging + live tables for the
-- document-knowledge layer (docs/summary/document-knowledge-data-structures.md
-- §1, as amended by §6.1: the WORK is the dossier and level-2 summary unit;
-- works are defined in sources/works.toml, singletons implicit).
-- Idempotent: IF NOT EXISTS everywhere, matching scripts/schema.sql.

-- ============================================================
-- STAGING — Pass D: dossier + summary generation (build_dossiers.py)
-- ============================================================
-- Per-FIELD staging: each dossier field is its own generation unit with its
-- own prompt template and version (§1.3). One row per
-- (work, field, span, model, prompt_version) attempt. payload_json is that
-- field's output only, validated against the field's contract before insert
-- (reject-and-retry, the tag_concepts.parse_tags pattern). The composed
-- dossier only exists at promotion time (live table below).

CREATE TABLE IF NOT EXISTS staged_dossier_fields (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    work_id         TEXT NOT NULL,              -- works layer (§6.1); singleton = text_id
    field           TEXT NOT NULL
                        CHECK(field IN ('summary','context','structure_entry',
                                        'key_figures','key_terms','reading_notes')),
    -- structure_entry rows are per-span: one row per span, keyed here.
    -- NULL for whole-work fields. Map-pass key_figures/key_terms rows
    -- (local campaigns only, §1.3.5) also set this.
    section_span    TEXT,
    payload_json    TEXT NOT NULL,              -- field-specific shape (§1.1)
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending','accepted','rejected')),
    reviewed_by     TEXT,
    reviewed_at     TEXT,
    model           TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,              -- per-FIELD template version, e.g. 'context-v1'
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- Re-runs against the same field template don't dupe; settled rows coexist
-- with new pending proposals from a revised template (v3_005 partial-unique
-- pattern). COALESCE folds NULL section_span into the key for SQLite.
CREATE UNIQUE INDEX IF NOT EXISTS idx_staged_dossier_fields_provenance_unique
    ON staged_dossier_fields(work_id, field, COALESCE(section_span, ''), model, prompt_version)
    WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_staged_dossier_fields_status
    ON staged_dossier_fields(status);
CREATE INDEX IF NOT EXISTS idx_staged_dossier_fields_work
    ON staged_dossier_fields(work_id, field);

CREATE TABLE IF NOT EXISTS staged_summaries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    summary_id      TEXT NOT NULL,              -- 'sum:{text_id}:{span_slug}' (L1) /
                                                -- 'sum:{work_id}' (L2) / 'fold:{work_id}:{n}' (L0)
    work_id         TEXT NOT NULL,              -- works layer (§6.1)
    -- L1 rows: the member text the span lives in. NULL on level-2 rows of
    -- multi-member works (an L2 spans texts) and on folds.
    text_id         TEXT,
    -- level 0 = internal FOLD (§1.3.5): pipeline scaffolding for oversized
    -- works under small-context providers ONLY (input_budget > 0). Never
    -- promoted, never exported; zero rows under the claude-code provider.
    level           INTEGER NOT NULL CHECK(level IN (0, 1, 2)),
    section_span    TEXT,                       -- printable span (NULL for level 2)
    child_chunk_ids TEXT,                       -- JSON array, level 1 only, corpus order
    child_summary_ids TEXT,                     -- JSON array, levels 0 and 2
    body            TEXT NOT NULL,
    token_count     INTEGER NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending','accepted','rejected')),
    reviewed_by     TEXT,
    reviewed_at     TEXT,
    model           TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_staged_summaries_provenance_unique
    ON staged_summaries(summary_id, model, prompt_version)
    WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_staged_summaries_work   ON staged_summaries(work_id);
CREATE INDEX IF NOT EXISTS idx_staged_summaries_status ON staged_summaries(status);

-- ============================================================
-- LIVE — promoted artifacts (what export.py reads)
-- ============================================================
-- Promotion (accepted staged rows → live rows) happens in
-- promote_dossiers.py (§ implementation doc G6). Live rows carry generation
-- provenance forward in generated_by (per-field template versions,
-- semicolon-joined; manual fixes record 'field-manual').

CREATE TABLE IF NOT EXISTS work_dossiers (
    work_id         TEXT PRIMARY KEY,
    summary         TEXT NOT NULL,              -- 150-300 tokens; the study-prompt injection block
    context         TEXT NOT NULL,              -- dating, provenance, transmission
    structure_json  TEXT NOT NULL,              -- [{section_span, title, synopsis, chunk_ids[]}] span order
    key_figures_json TEXT NOT NULL,             -- [{name, role, gloss}]
    key_terms_json  TEXT NOT NULL,              -- [{term, transliteration, gloss}]
    themes_json     TEXT NOT NULL,              -- taxonomy concept ids (display only; NOT edges);
                                                -- '[]' when the work has <5 accepted tags (V5 floor)
    reading_notes   TEXT,
    manifest_notes  TEXT,                       -- member manifest `notes`, labeled + concatenated
    generated_by    TEXT NOT NULL,
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS summary_nodes (
    id              TEXT PRIMARY KEY,           -- 'sum:{text_id}:{span_slug}' / 'sum:{work_id}'
    work_id         TEXT NOT NULL,
    text_id         TEXT,                       -- NULL on multi-member work L2s
    tradition       TEXT NOT NULL,              -- denormalized like chunks (zero-join scoping)
    level           INTEGER NOT NULL CHECK(level IN (1, 2)),
    section_span    TEXT,
    child_chunk_ids TEXT NOT NULL,              -- JSON array; provenance + invalidation key;
                                                -- L2 = transitive union over member L1s, corpus order
    body            TEXT NOT NULL,
    token_count     INTEGER NOT NULL,
    generated_by    TEXT NOT NULL,
    -- Invalidation (normative rule, implementation doc G6):
    -- sha256("\n".join(sha256(chunk body) for transitive child chunks,
    -- sorted by chunk id)). Rebuild detection = recompute and compare.
    children_hash   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_summary_nodes_work ON summary_nodes(work_id);
CREATE INDEX IF NOT EXISTS idx_summary_nodes_text ON summary_nodes(text_id);

-- Embeddings: separate table, float32 LE BLOB — the chunk_embeddings pattern
-- exactly, so the embed writer path is reused with a different target.
CREATE TABLE IF NOT EXISTS summary_embeddings (
    summary_id  TEXT PRIMARY KEY REFERENCES summary_nodes(id) ON DELETE CASCADE,
    dim         INTEGER NOT NULL,
    model       TEXT NOT NULL,
    vector      BLOB NOT NULL
);
