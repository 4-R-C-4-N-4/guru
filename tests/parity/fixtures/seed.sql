-- Parity harness shadow seed (todo:2cd9f9b5).
-- Schema mirrors the live data/guru.db DDL exactly.
-- Both shadows are seeded with this script so AUTOINCREMENT ids align.

PRAGMA foreign_keys = ON;

CREATE TABLE nodes (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL CHECK(type IN ('tradition','concept','chunk')),
    tradition_id TEXT REFERENCES nodes(id),
    label       TEXT NOT NULL,
    definition  TEXT,
    metadata_json TEXT DEFAULT '{}'
);
CREATE INDEX idx_nodes_type ON nodes(type);
CREATE INDEX idx_nodes_tradition ON nodes(tradition_id);

CREATE TABLE edges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   TEXT NOT NULL REFERENCES nodes(id),
    target_id   TEXT NOT NULL REFERENCES nodes(id),
    type        TEXT NOT NULL CHECK(type IN ('BELONGS_TO','EXPRESSES','PARALLELS','CONTRASTS','DERIVES_FROM')),
    tier        TEXT NOT NULL DEFAULT 'inferred' CHECK(tier IN ('verified','proposed','inferred')),
    justification TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX idx_edges_source ON edges(source_id);
CREATE INDEX idx_edges_target ON edges(target_id);
CREATE INDEX idx_edges_type   ON edges(type);
CREATE UNIQUE INDEX idx_edges_unique ON edges(source_id, target_id, type);

CREATE TABLE staged_tags (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id        TEXT NOT NULL REFERENCES nodes(id),
    concept_id      TEXT NOT NULL,
    score           INTEGER NOT NULL CHECK(score BETWEEN 0 AND 3),
    justification   TEXT,
    is_new_concept  INTEGER NOT NULL DEFAULT 0,
    new_concept_def TEXT,
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending','accepted','rejected','reassigned')),
    reviewed_by     TEXT,
    reviewed_at     TEXT,
    model           TEXT,
    prompt_version  TEXT
);
CREATE INDEX idx_staged_tags_chunk   ON staged_tags(chunk_id);
CREATE INDEX idx_staged_tags_concept ON staged_tags(concept_id);
CREATE INDEX idx_staged_tags_status  ON staged_tags(status);
CREATE UNIQUE INDEX idx_staged_tags_provenance_unique
    ON staged_tags(chunk_id, concept_id, model, prompt_version)
    WHERE status = 'pending';

-- Tradition + chunk nodes (3 chunks for a small but representative slice).
INSERT INTO nodes(id, type, label) VALUES ('gnosticism', 'tradition', 'Gnosticism');
INSERT INTO nodes(id, type, tradition_id, label) VALUES
    ('gnosticism.gospel-of-thomas.001', 'chunk', 'gnosticism', 'Logion 1'),
    ('gnosticism.gospel-of-thomas.002', 'chunk', 'gnosticism', 'Logion 2'),
    ('gnosticism.gospel-of-thomas.003', 'chunk', 'gnosticism', 'Logion 3');

-- Pre-existing concept nodes:
--   gnosis: has a definition → must be preserved by COALESCE on accept
--   divine_emanation: target of a reassign; has a definition that survives
--   kenoma / aeons / archon: pre-populated to back the auto-promoted edges
--     that reject + reassign decisions must retract. Without these nodes,
--     the FK on edges.target_id would block the seeded edges below.
INSERT INTO nodes(id, type, label, definition) VALUES
    ('concept.gnosis',           'concept', 'Gnosis',           'Direct experiential knowledge of the divine.'),
    ('concept.divine_emanation', 'concept', 'Divine Emanation', 'Pre-existing definition.'),
    ('concept.kenoma',           'concept', 'Kenoma',           NULL),
    ('concept.aeons',            'concept', 'Aeons',            NULL),
    ('concept.archon',           'concept', 'Archon',           NULL);

-- Auto-promoted edges that will be retracted by reject (decision-004) and
-- reassign (decisions-006/007). Tier='proposed' mimics what auto_promote.py
-- writes for score>=2 rows. The reject + reassign branches must DELETE these
-- on both CLI and web sides; compare.py asserts both shadows agree.
INSERT INTO edges(source_id, target_id, type, tier, justification) VALUES
    ('gnosticism.gospel-of-thomas.002', 'concept.kenoma', 'EXPRESSES', 'proposed', '[auto] reject must retract'),
    ('gnosticism.gospel-of-thomas.003', 'concept.aeons',  'EXPRESSES', 'proposed', '[auto] reassign must retract'),
    ('gnosticism.gospel-of-thomas.003', 'concept.archon', 'EXPRESSES', 'proposed', '[auto] reassign must retract');

-- 7 staged_tags covering every action branch. Explicit ids for reproducibility.
-- model/prompt_version mimic the production v3 backfill (qwen3.5-27b / v1).
INSERT INTO staged_tags(id, chunk_id, concept_id, score, justification, is_new_concept, new_concept_def, model, prompt_version) VALUES
    (1, 'gnosticism.gospel-of-thomas.001', 'gnosis',     3, 'verified-tier accept',           0, NULL,                     'Qwen3.5-27B-UD-Q4_K_XL.gguf', 'v1'),
    (2, 'gnosticism.gospel-of-thomas.001', 'demiurge',   1, 'proposed-tier accept',           0, NULL,                     'Qwen3.5-27B-UD-Q4_K_XL.gguf', 'v1'),
    (3, 'gnosticism.gospel-of-thomas.001', 'ineffable',  2, 'is_new_concept=1 accept',        1, 'Beyond all utterance.',  'Qwen3.5-27B-UD-Q4_K_XL.gguf', 'v1'),
    (4, 'gnosticism.gospel-of-thomas.002', 'kenoma',     2, 'reject me',                      0, NULL,                     'Qwen3.5-27B-UD-Q4_K_XL.gguf', 'v1'),
    (5, 'gnosticism.gospel-of-thomas.002', 'pleroma',    3, 'skip me — stays pending',         0, NULL,                     'Qwen3.5-27B-UD-Q4_K_XL.gguf', 'v1'),
    (6, 'gnosticism.gospel-of-thomas.003', 'aeons',      2, 'reassign to existing concept',   0, NULL,                     'Qwen3.5-27B-UD-Q4_K_XL.gguf', 'v1'),
    (7, 'gnosticism.gospel-of-thomas.003', 'archon',     1, 'reassign to free-text new',      0, NULL,                     'Qwen3.5-27B-UD-Q4_K_XL.gguf', 'v1');
