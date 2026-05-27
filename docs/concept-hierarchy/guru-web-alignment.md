# Concept Hierarchy — guru-web Alignment & Downstream Impacts

_Companion to `design.md` (§10–§12). Reflects the **completed** concept-hierarchy
feature on the `tag-family` branch of the **guru** (pipeline) repo as of
2026-05-27. This is the handoff contract for the guru-web side._

## TL;DR

The pipeline now produces a **fully clustered** three-tier concept hierarchy
(6 domains → 22 families → 95 concepts) and exports it to Postgres at
**SCHEMA_VERSION 3**. guru-web alignment is **not just adding tables** — the payoff
lands when the **query plane** (`extractConcepts`), **ranking**, and **UI** learn
to use families/domains. The schema mirror is necessary but inert on its own:
typing `cosmology` matches nothing until `graph.ts` changes.

Three hard coordination rules:
- **`corpus-schema.sql` is byte-identical across repos.** CI hashes both copies on
  every push (see that file's header). guru-web must take the **exact** v3 additions
  (4 tables + `ALTER concepts ADD family_id` + the two `COMMENT`s) verbatim.
- **`SCHEMA_VERSION` 2 → 3 is lockstep.** guru-web's `EXPECTED_SCHEMA_VERSION` must
  advance in the *same* deploy as the export, or the app rejects the corpus.
- **Families are real now** (clustering done) — no mirror-state guard needed. A
  domain→family→concept tree renders meaningfully; families group ~3–8 concepts.

---

## 1. What shipped in the pipeline repo (all done)

| Piece | State |
|-------|-------|
| `v3_006` SQLite migration (4 tables) | ✅ applied to live `guru.db` |
| `taxonomy.toml` three-tier, hand-clustered into the §4 22-family hierarchy | ✅ 95 concepts incl. 7 ex-orphans |
| `sync_taxonomy.py` | ✅ live: 28 family rows (6 domains + 22), 95 primaries, 0 secondaries/orphans |
| Family context in review surfaces (`review_tags` / `review_edges`) | ✅ |
| `export.py` + `corpus-schema.sql` at SCHEMA_VERSION 3 | ✅ real artifact produced & structurally validated |

**Tagging decision (important):** the grouped "v2" tagging prompt was benched
against v1 and **regressed** agreement-with-review (recall 71.7→50.4, precision
95.1→85.1; `bench-v1-vs-v2.md`). It was **reverted** — tagging stays
**concept-driven on the flat v1 prompt**. The hierarchy is a **retrieval/structure
layer only** and does not touch the tagger LLM call; family assignment is
deterministic via `sync_taxonomy.py`. Consequence for guru-web below (§4).

---

## 2. The data contract guru-web receives

The export mirrors the SQLite shape into Postgres (`design.md §10.2`).

**Four new tables** in `corpus`:
- `concept_families(id, parent_id, label, definition)` — domains have `parent_id
  IS NULL`; families point at their domain. IDs dotted for families
  (`cosmology.cosmic_agents`), bare for domains (`cosmology`).
- `concept_family_membership(concept_id, family_id, is_primary)` — `is_primary` is
  native **`BOOLEAN`** (vs `0/1` in SQLite; `export.py` emits `t`/`f`). Exactly one
  primary per concept (enforced by the partial unique index, built post-load).
- `concept_aliases(concept_id, alias)` and `family_aliases(family_id, alias)` — both
  `CHECK(alias = LOWER(alias))`. **The Postgres CHECK is the strict Unicode-aware
  authority** on lowercasing (SQLite's is ASCII-only); a bad row fails at COPY time.

**One denormalised column** on `concepts`:
- `concepts.family_id` → primary family (export-maintained from `WHERE is_primary`).
  Turns "filter/group chunks by family" from a 3-way into a 2-way join. **Do not
  write at runtime.**
- `concepts.domain` **stays** and keeps working for existing `src/lib/` queries; now
  derived (export-only) from the primary family's `parent_id`. Removal is a later
  follow-on once no query reads it.

**Indexes** (5) are created post-load by the export, not in `corpus-schema.sql`
(that file is index-free by rule). guru-web doesn't need to manage them.

**Empty-in-v1:** both alias tables ship empty (incremental population). Every
membership row is `is_primary = TRUE` until secondary affiliations (§5.3) appear via
review actions.

---

## 3. Downstream impacts — beyond schema

### 3.1 Query plane — `extractConcepts` (`src/lib/graph.ts`) — the main work

Today: a single `%token%` LIKE against `concepts.label`. High-level queries
(`cosmology`, `salvation`) and synonyms (`the One`, `the cosmos`) match nothing and
the retriever silently degrades to pure vector search.

Match tokens **simultaneously across three namespaces** (not priority-ordered):
1. **Concept** — `concepts.label` + `concept_aliases.alias` → `concept.<id>`.
2. **Family** — `concept_families.label` + `family_aliases.alias` → expands to **all**
   concepts with a membership row pointing at that family.
3. **Domain** — domain-row label + its `family_aliases` → all concepts whose family's
   `parent_id` is that domain.

Each match emits `(concept_id, match_tier)`, `match_tier ∈ {concept, family, domain}`.
**Read-side ignores `is_primary`** — primary and secondary are co-equal for expansion.
Substring LIKE on lowercased values everywhere (not equality). `walkGraph` consumes
the concept set unchanged.

### 3.2 Ranking (`src/lib/retriever.ts`)

`match_tier` becomes a scalar weight: concept **1.0**, family **0.5**, domain **0.25**,
multiplied into the existing chunk score. An alias match weighs the same as the
canonical label at its tier (`the One` == `monad`). Multi-overlap requirements are a
later tunable, not pre-emptive.

### 3.3 Presentation / UX

- **Browse by domain → family → concept** — and it's meaningful now (22 real families).
- **Family context on concept/chunk views** — "Monad · Cosmology → Divine Structure."
- **Query-expansion transparency** — show when `cosmology` expanded to N concepts.
- (The earlier "mirror-state guard" caveat is **retired** — families are real.)

### 3.4 API / response shape

Endpoints returning concepts should consider carrying `family_id` / `family_label` /
`domain` so clients don't re-query. Typed DTOs (shared types / zod / OpenAPI) gain the
new **optional** fields (keep optional so older clients don't break).

### 3.5 Curation UI (guru-review)

Review rows gain a `FAMILY: domain → family / gloss` line (already done on the local
`review_tags.py`; `review_edges.py` shows each linked chunk's expressed families). If
guru-review shares the guru-web codebase, port the same display. This is also where
**secondary memberships** (`is_primary = 0`) get populated over time.

### 3.6 New-concept proposal loop (future — `design.md §12`)

The hierarchy is its substrate: **family-scoped dedupe**, a **review UI structured
around the family tier**, **stricter family-inflation caps**. Acceptance writes a
`concept_family_membership` row. Design the review UI family-first. Note: per the
tagging decision, family classification of a *candidate* concept should be a
**separate focused LLM call**, never folded into chunk tagging.

---

## 4. Cross-cutting things guru-web must know

- **Tags are v1.** Tagging stayed on the flat v1 prompt; there are **no v2 tags**.
  Existing tags are intact and gain family context via the concept (families attach to
  concepts, not tags), so no re-tagging and no chunk-level migration.
- **Families attach to concepts** — every existing tagged chunk inherits family context
  for free once the export lands.
- **Aliases inert until populated** — alias query paths return zero rows today; correct
  from day one, improve silently. Don't block the query-plane work on alias data.

---

## 5. Operational / deploy notes

- **Apply path (VPS):** the export `.sql.gz` is self-contained (staging schema → load →
  atomic swap), applied with `sudo -u postgres psql guru < export/guru-corpus.sql` — no
  separate migration step. (The `postgres` user's shell has no `DATABASE_URL`.)
- **Schema lockstep (repeat — it bites):** export emits SCHEMA_VERSION 3 and a runtime
  validation block that **raises** if `corpus_metadata.schema_version != 3`; guru-web's
  `EXPECTED_SCHEMA_VERSION` must be 3 in the same deploy.
- **Reproducibility:** a fresh DB reaches the correct state via `v3_006` migration +
  `sync_taxonomy.py --apply` against the (already-clustered) `taxonomy.toml` — no mirror
  state and no teardown; that was a one-time live-migration artifact.
- **Build caveat:** build guru-web with `next build --webpack` (Next 16 Turbopack
  silently ignores `middleware.ts`; standalone output is incompatible with `proxy.ts`).
  Clerk prod keys are domain-locked.

---

## 6. Suggested sequencing for guru-web (pipeline side is fully unblocked)

1. Take the v3 `corpus-schema.sql` additions **verbatim** (byte-identical) and bump
   `EXPECTED_SCHEMA_VERSION` 2 → 3 on a branch.
2. Generate a real export here, apply to a **staging Postgres**, integration-test.
   (The v3 artifact has already been load-tested against `pgvector/pgvector:pg17` —
   loads clean, the inline `schema_version==3` validation passes, FK/BOOLEAN/indexes
   all correct — so this step is confirmation on the real VPS PG, not a first try.)
3. Implement the three-namespace `extractConcepts` + tier-weighted ranking; verify
   against representative high-level queries (`cosmology`, `the cosmos`, `cosmic agents`,
   `the One`, `salvation`).
4. Family-aware UI (real families exist — no mirror guard).
5. Alias population & proposal-loop UI: ongoing / future.

## 7. Open questions / watch-items

- The v3 export has been **load-tested against pgvector pg17** (clean load, validation
  block passes, FK/BOOLEAN/partial-unique-index all enforced). The remaining check is the
  real VPS Postgres apply on staging — version/extension parity, not artifact correctness.
- Whether `concepts.domain` is removed in a follow-on or kept (needs a guru-web query audit).
- Ranking weights (1.0 / 0.5 / 0.25) are a starting point — revisit on real results.
- Two placements (`emotional_epistemology` → soteriology.knowledge_path,
  `prophetic_rejection` → ethics.moral_teaching) are flagged for reconsideration in a
  future clustering pass (see the `ea1c2372` analysis note). guru-web shouldn't hard-code
  anything per-concept.
- `sync_taxonomy.py` has no `--prune`/`--strict-primary`; a future re-clustering that
  *moves* concepts will leave demoted-to-secondary rows that need cleanup (one-time SQL,
  as done for the mirror teardown). Not a guru-web concern, but noted for the next pass.
