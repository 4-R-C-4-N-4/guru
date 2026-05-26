-- ============================================================================
-- v3_006_concept_families.sql
--
-- Promote the implicit category structure in concepts/taxonomy.toml into a
-- queryable three-tier hierarchy (domain → family → concept). Adds four new
-- tables; touches nothing existing (nodes, edges, staged_tags, staged_edges,
-- chunk_embeddings, tagging_progress, staged_concepts are all left alone).
--
-- Per docs/concept-hierarchy/design.md §5 (todo:ad1c2299, parent 10512e6a).
--
-- Tables created:
--   concept_families          — domains (parent_id NULL) and families
--                               (parent_id → domain) in one self-referential
--                               table. Composite IDs for families
--                               ('cosmology.cosmic_agents'), bare IDs for
--                               domains ('cosmology'). No tier column: the
--                               tier is implicit (parent_id IS NULL ⟺ domain).
--   concept_family_membership — concept→family affiliations, is_primary flag.
--                               Exactly one primary family per concept,
--                               enforced by a partial UNIQUE index. is_primary
--                               constrained to {0,1} by CHECK.
--   concept_aliases           — user-facing synonyms for concepts.
--   family_aliases            — user-facing synonyms for families (domains
--                               included, keyed by their bare family_id).
--
-- Index rationale:
--   idx_concept_families_parent              — "families under domain X" is a
--                                              hot lookup once query expansion
--                                              (§11) lands.
--   idx_concept_primary_family               — partial UNIQUE; enforces the
--                                              one-primary-family-per-concept
--                                              invariant.
--   idx_concept_family_membership_family     — reverse lookup "which concepts
--                                              are in family X" (primary or
--                                              secondary).
--   idx_concept_aliases_alias / _family_aliases_alias
--                                            — alias → owner lookup on the
--                                              query path.
--
-- FK / cascade rationale (§5):
--   membership.concept_id → nodes(id)            ON DELETE CASCADE
--   concept_aliases.concept_id → nodes(id)       ON DELETE CASCADE
--   family_aliases.family_id → concept_families  ON DELETE CASCADE
--     Deleting a concept node or a family cleans up its dependent rows.
--   membership.family_id → concept_families      default RESTRICT
--     Deleting a family that still has members is a deliberate action and
--     must fail until the membership rows are removed first.
--
-- Case normalisation (§5.1): the load-bearing alias lowercasing is Python-side
-- in sync_taxonomy.py (str.lower(), Unicode-aware). The CHECK(alias=LOWER(alias))
-- here is a secondary defense — in SQLite, LOWER folds the ASCII range only, so
-- it catches 'The One' but not 'Sūnyatā'; the strict Unicode-aware Postgres
-- CHECK catches the rest at export time.
--
-- Idempotent: every CREATE uses IF NOT EXISTS, so re-running is a no-op. No
-- data is inserted — population is the sync script's job (todo:0a25044c).
-- No foreign_keys toggle needed: this is purely additive DDL.
--
-- Usage:
--   sqlite3 data/guru.db < scripts/migrations/v3_006_concept_families.sql
-- ============================================================================

BEGIN TRANSACTION;

-- ── concept_families: domains (parent_id NULL) + families (parent_id → domain)
CREATE TABLE IF NOT EXISTS concept_families (
  id          TEXT PRIMARY KEY,
  parent_id   TEXT REFERENCES concept_families(id),
  label       TEXT NOT NULL,
  definition  TEXT NOT NULL
);

-- "Families under domain X" is a hot lookup once query expansion lands:
CREATE INDEX IF NOT EXISTS idx_concept_families_parent
  ON concept_families(parent_id);

-- ── concept_family_membership: concept→family, one primary per concept ───────
CREATE TABLE IF NOT EXISTS concept_family_membership (
  concept_id  TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  family_id   TEXT NOT NULL REFERENCES concept_families(id),
  is_primary  INTEGER NOT NULL DEFAULT 0
                CHECK(is_primary IN (0, 1)),   -- 1 = canonical home, 0 = secondary
  PRIMARY KEY (concept_id, family_id)
);

-- Enforce exactly one primary family per concept:
CREATE UNIQUE INDEX IF NOT EXISTS idx_concept_primary_family
  ON concept_family_membership(concept_id) WHERE is_primary = 1;

-- Reverse lookup: which concepts are in family X (primary or secondary):
CREATE INDEX IF NOT EXISTS idx_concept_family_membership_family
  ON concept_family_membership(family_id);

-- ── concept_aliases: user-facing concept synonyms ────────────────────────────
CREATE TABLE IF NOT EXISTS concept_aliases (
  concept_id  TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  alias       TEXT NOT NULL CHECK(alias = LOWER(alias)),
  PRIMARY KEY (concept_id, alias)
);

CREATE INDEX IF NOT EXISTS idx_concept_aliases_alias
  ON concept_aliases(alias);

-- ── family_aliases: user-facing family (and domain) synonyms ─────────────────
CREATE TABLE IF NOT EXISTS family_aliases (
  family_id   TEXT NOT NULL REFERENCES concept_families(id) ON DELETE CASCADE,
  alias       TEXT NOT NULL CHECK(alias = LOWER(alias)),
  PRIMARY KEY (family_id, alias)
);

CREATE INDEX IF NOT EXISTS idx_family_aliases_alias
  ON family_aliases(alias);

-- ── verification: the four tables and five indexes must all be present ───────

SELECT '== verification: new tables (must list 4) ==' AS audit;
SELECT name FROM sqlite_master
 WHERE type='table'
   AND name IN ('concept_families','concept_family_membership',
                'concept_aliases','family_aliases')
 ORDER BY name;

SELECT '== verification: new indexes (must list 5) ==' AS audit;
SELECT name FROM sqlite_master
 WHERE type='index'
   AND name IN ('idx_concept_families_parent','idx_concept_primary_family',
                'idx_concept_family_membership_family',
                'idx_concept_aliases_alias','idx_family_aliases_alias')
 ORDER BY name;

COMMIT;
