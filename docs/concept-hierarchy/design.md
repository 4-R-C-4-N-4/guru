# Concept Hierarchy — Design Doc

## Codename: tag-family
## Scope: Promote the implicit category structure in `concepts/taxonomy.toml` into a queryable three-tier hierarchy (domain → family → concept), surface families in the tagger prompt and in guru-web, and create the substrate the new-concept proposal loop needs for scoped dedupe.

---

## 1. Summary

The flat-with-categories TOML is doing two jobs badly. The scholarly domains (`cosmology`, `soteriology`, etc.) appear only as TOML headers the LLM never sees, and individual concepts inside a domain have no expressed relationship to each other beyond co-membership. At 88 concepts across 6 domains today — with cosmology alone holding 26 — the cost of leaving the hierarchy implicit has already compounded: the tagger sees a flat list, dedupe across the proposal loop has no natural scope, and reviewers re-derive structural intuition by hand every pass.

Just as importantly, guru-web users routinely query at a higher level than a discrete concept — they type `cosmology` or `salvation`, not `monad` or `theosis`. Today those queries match no concept label at all and fall through to vector search alone. The same hierarchy that helps the tagger also unlocks domain- and family-scoped retrieval on the read side.

This doc specifies a small, additive schema delta (three new tables plus one denormalised column), a TOML restructure, a sync script, prompt and review-surface changes, the export path into guru-web, the query-side expansion that makes high-level queries work, and a concrete starting family proposal to iterate on. Two refinements layered into the schema from the start give it room to grow: user-facing **alias** mechanisms on families/domains (inline column) and on concepts themselves (join table) so natural-language queries map to canonical IDs, and an `is_primary` flag on `concept_family_membership` so cross-cutting secondary affiliations (unpopulated in v1) live in the same table as the primary home, with the single-primary-per-concept invariant enforced by a partial unique index. Every existing concept ID, every tagged chunk, every edge, and every staged tag is preserved unchanged.

---

## 2. Goals and Non-Goals

### Goals

- Promote `domain` and a new `family` tier into queryable tables in both the SQLite source-of-truth and guru-web's Postgres mirror.
- Surface family groupings to the LLM in `build_prompt()` so it picks within a family rather than across the flat 88-concept space.
- Show family context in the review surfaces (CLI and web).
- Propagate the hierarchy through `export.py` and `corpus-schema.sql` so guru-web can filter and expand on it.
- Extend guru-web's concept extractor so user queries at the family or domain level expand into the underlying concept set, with `aliases` (inline column on families/domains, join table for concepts) bridging natural-language queries and canonical IDs.
- Lay the substrate the new-concept proposal loop will use for family-scoped dedupe.
- Create the secondary-membership seam (`is_primary = FALSE` rows in `concept_family_membership`, unpopulated in v1) so cross-cutting family affiliations have a first-class home when the time comes, without re-opening the schema.

### Non-Goals

- Renaming, renumbering, or moving any existing concept ID. The snake_case IDs in `edges.target_id` and `staged_tags.concept_id` are unchanged.
- Introducing a relational concept graph (`IS_A`, `PART_OF`, `OPPOSED_TO`, …). Explicitly deferred — see §3.
- Changing how `EXPRESSES` edges from chunks to concepts work, or what auto-promote does.
- Per-tradition concept variants (e.g. `mystical_union/sufi`). Cross-tradition variants stay as one concept.
- Automated family assignment for the existing 88 concepts. The first clustering pass is manual.
- Cross-family concept relationships (e.g. `gnosis_direct_knowledge` upstream of `self_knowledge`). That's the relational-graph layer's job — separate from secondary memberships (`is_primary = FALSE` in `concept_family_membership`), which handle family-level affiliations only.
- Populating secondary memberships, `concept_aliases`, or family/domain `aliases` in v1. All three are additive seams; population is ongoing work driven by reviewer judgment and surfaced query patterns.
- A "browse by domain" UI. The minimum bar is that free-text queries at the hierarchy level do something useful.

---

## 3. The three tiers

| tier | name | example | count (target) |
|---|---|---|---|
| 1 | **domain** | `cosmology`, `soteriology`, `theology`, `praxis`, `anthropology`, `ethics` | 6 today, ~6–10 long-term |
| 2 | **family** | `cosmic_agents`, `divine_structure`, `cosmic_order`, `origin_events` | ~22 proposed (see §4), 3–6 per domain (realised range 2–8) |
| 3 | **concept** | `demiurge`, `archons`, `monad`, `pleroma` | the existing snake_case IDs, 88 today |

Domains are the scholarly categorisation the TOML already encodes. Families are the new tier — clusters of conceptually adjacent concepts within a domain. Concepts are unchanged.

### Why three tiers, not two

Two tiers (domain → concept) is what's there today. It doesn't give the tagger prompt anything actionable — "here are all 26 concepts under cosmology, pick the right one" is barely better than the flat list. The family tier means the prompt can group `monad`/`pleroma`/`kenoma`/`sephirot` together under `divine_structure` with a one-line family gloss, and the LLM gets a hint about *what kind* of distinction it's being asked to make.

It also gives the new-concept proposal loop (§12) a natural dedupe scope. Comparing a candidate concept to all 88 existing concepts is wasteful and noisy. Comparing it to the small set of siblings in its likely family (proposal: 2–8) is the comparison that actually matters — `divine_marriage` and `mystical_union` are both about union; that's where the dedupe pressure lives.

Four tiers (domain → super-family → family → concept) is premature. If a domain ends up with 15 families and clearly subdivides, that's the moment to discuss a fourth tier.

### Why not a relational concept graph instead

The relational graph (`IS_A`, `PART_OF`, `OPPOSED_TO`, …) is strictly more powerful but needs hand-curation or another LLM-review pipeline; defer until the proposal loop has run. The classification hierarchy lays the groundwork — every `merge into existing` action in the new-concept reviewer is an implicit `IS_A` edge worth eventually capturing.

---

## 4. Starting family hierarchy

Recommended seed for the hand-clustering pass — 22 families across the 6 domains, averaging ~4 concepts per family. **This is a proposal, not a settled mapping.** Concept assignments will move during the clustering pass and as the family glosses get sharpened. The numbers in parentheses are concept counts per family.

### cosmology (26 concepts → 5 families)

- **divine_structure** (8) — the architecture of the highest realms.
  `emanation_hierarchy`, `pleroma`, `kenoma`, `monad`, `aeons`, `logos`, `sephirot`, `sefirot_tree`
- **cosmic_agents** (5) — beings or powers acting on or within the cosmos.
  `demiurge`, `archons`, `ahura_mazda_principle`, `angra_mainyu_principle`, `watchers_descent`
- **cosmic_order** (6) — the lawful structure of reality.
  `asha_cosmic_order`, `maat_cosmic_order`, `correspondence`, `microcosm_macrocosm`, `cosmic_sympathy`, `infinite_cosmos`
- **origin_events** (4) — originating events and re-creations.
  `letters_of_creation`, `tzimtzum`, `fall_of_sophia`, `frashokereti`
- **soul_cosmology** (3) — the cosmic geography of soul.
  `divine_sparks`, `soul_migration`, `psychopomp_journey`

### soteriology (17 concepts → 5 families)

- **knowledge_path** (5) — salvation through knowing.
  `gnosis_direct_knowledge`, `self_knowledge`, `anamnesis`, `hidden_sayings`, `forbidden_knowledge`
- **union_and_return** (5) — merging with the divine source.
  `return_to_source`, `divine_marriage`, `mystical_union`, `theosis_deification`, `fana_annihilation`
- **ecstatic_ascent** (2) — eros-driven rapture.
  `divine_madness`, `ladder_of_love`
- **purgation_and_emptiness** (3) — the felt costs and negations of the path.
  `dark_night`, `separation_from_source`, `sunyata_emptiness`
- **soteric_categories** (2) — typological frames for who is saved and when.
  `pneumatic_elect`, `eschatological_judgment`

### theology (14 concepts → 3 families)

- **divine_nature** (5) — what God is, including via negation.
  `apophatic_theology`, `divine_hiddenness`, `divine_simplicity`, `ein_sof`, `anthropomorphism`
- **divine_attributes_and_acts** (5) — what God reveals or does.
  `divine_light`, `living_god`, `sacred_names`, `divine_providence`, `covenant`
- **ontological_structure** (4) — how being itself is structured.
  `unity_of_being`, `evil_as_privation`, `cosmic_dualism`, `numerical_mysticism`

### praxis (18 concepts → 5 families)

- **contemplative_practice** (5) — inward attention as method, including non-coercive aligned action.
  `meditation`, `active_contemplation`, `inner_silence`, `detachment_gelassenheit`, `wu_wei`
- **ritual_and_symbolic** (6) — outward acts and symbol-bearing media.
  `letter_meditation`, `permutation_of_letters`, `ritual_fire`, `funerary_navigation`, `theurgy`, `prayer`
- **ascetic_discipline** (3) — bodily and moral self-purification.
  `fasting_and_prayer`, `ritual_purity`, `self_examination`
- **ecstatic_modes** (2) — non-rational receptivity as practice.
  `heroic_furor`, `divine_intoxication`
- **transformative_path** (2) — transformation through intensified work.
  `alchemical_work`, `spiritual_ascent`

### anthropology (9 concepts → 3 families)

- **divine_indwelling** (3) — the divine present within the human.
  `inner_light`, `kingdom_within`, `birth_of_word_in_soul`
- **human_constitution** (3) — what humans are, by default.
  `tripartite_soul`, `body_as_obstacle`, `mechanical_humanity`
- **spiritual_completion** (3) — the realised state.
  `opposites_transcended`, `childlike_innocence`, `poverty_of_spirit`

### ethics (4 concepts → 1 family)

- **moral_teaching** (4) — right conduct and the pedagogy of insight.
  `renunciation_of_wealth`, `love_of_neighbour`, `rejection_of_hypocrisy`, `paradox_as_teaching`

Ethics is small enough today that a single family is the honest call; subdividing 4 concepts is empty ceremony. If ethics grows past ~8 it should split.

### Known judgment calls to revisit during clustering

- **`wu_wei` in `contemplative_practice`** — moved here from an earlier draft's `transformative_path` placement. The family gloss stretches from `meditation` → `inner_silence` → `detachment_gelassenheit` → `wu_wei` along a coherent axis of disengaging the active will. The previous `transformative_path` placement was the weakest assignment in the draft; this resolves it but newly thins `transformative_path` to 2 concepts — see below.
- **`transformative_path` at 2** is now newly thin after wu_wei's move. Candidate refinements to consider during clustering: fold `spiritual_ascent` into `contemplative_practice` (which would become 6) and pull `theurgy` out of `ritual_and_symbolic` to form a `transformative_arts` family with `alchemical_work` — alchemy and theurgy share the operative/technical/results-oriented character. Deferred to clustering pass; not pre-committed.
- **`ecstatic_modes` at size 2** is below the family-cohesion threshold the proposal loop will want. Either accept it as a small permanent family or fold `heroic_furor` / `divine_intoxication` into adjacent families (soteriology's `ecstatic_ascent`?). The current split keeps the praxis/soteriology boundary clean.
- **`numerical_mysticism` in `theology.ontological_structure`** could equally live in `cosmology.cosmic_order` — numbers as cosmic structure vs numbers as divine reality. Keep theology for now; reconsider if cosmology's cosmic_order grows. Likely candidate for a secondary-membership row (§5.3) once that mechanism gets populated.
- **`forbidden_knowledge`** sits in `soteriology.knowledge_path` as an explicit foil (the concept's own definition contrasts it with `gnosis_direct_knowledge`). If the family gloss reads as "the saving forms of knowing," forbidden_knowledge becomes an outlier and probably wants its own home.

---

## 5. SQLite schema delta

Three new tables in `scripts/schema.sql`. None touch `nodes`, `edges`, `staged_tags`, or any existing concept reference.

```sql
CREATE TABLE IF NOT EXISTS concept_families (
  id          TEXT PRIMARY KEY,
  parent_id   TEXT REFERENCES concept_families(id),
  label       TEXT NOT NULL,
  definition  TEXT NOT NULL,
  aliases     TEXT             -- JSON array of strings; see §5.1
);

CREATE TABLE IF NOT EXISTS concept_family_membership (
  concept_id  TEXT NOT NULL REFERENCES nodes(id),
  family_id   TEXT NOT NULL REFERENCES concept_families(id),
  is_primary  INTEGER NOT NULL DEFAULT 0,   -- 1 = canonical home, 0 = secondary affiliation
  PRIMARY KEY (concept_id, family_id)
);

-- Enforce exactly one primary family per concept:
CREATE UNIQUE INDEX IF NOT EXISTS idx_concept_primary_family
  ON concept_family_membership(concept_id) WHERE is_primary = 1;

-- Reverse lookup: which concepts are in family X (primary or secondary):
CREATE INDEX IF NOT EXISTS idx_concept_family_membership_family
  ON concept_family_membership(family_id);

CREATE TABLE IF NOT EXISTS concept_aliases (
  concept_id  TEXT NOT NULL REFERENCES nodes(id),
  alias       TEXT NOT NULL,
  PRIMARY KEY (concept_id, alias)
);

CREATE INDEX IF NOT EXISTS idx_concept_aliases_alias
  ON concept_aliases(alias);
```

**Self-referential `parent_id`** carries both upper tiers in one table. A domain row has `parent_id = NULL`; a family row has `parent_id` pointing at its domain.

**Composite IDs** for family rows: `cosmology.cosmic_agents`, not bare `cosmic_agents`. Family names will collide across domains (`cosmic_order` in cosmology vs a possible `moral_order` in ethics) and the dotted form encodes the hierarchy in a human-readable way. Domains use bare IDs (`cosmology`), so the dotted form is unambiguously `domain.family`.

**One unified membership table, `is_primary` flag.** A concept's set of family affiliations lives in a single table; the `is_primary = 1` row is its canonical home and drives prompt rendering, scoped dedupe, and the "domain → family → concept" path. `is_primary = 0` rows are secondary affiliations (§5.3). Forward lookup ("all family affiliations for concept Y") is `WHERE concept_id = Y`; reverse lookup ("all concepts in family X, primary or secondary") is `WHERE family_id = X`; tagger lookup ("the primary family for concept Y") is `WHERE concept_id = Y AND is_primary = 1`. The single-primary invariant is enforced by the partial unique index on `(concept_id) WHERE is_primary = 1`.

**FKs everywhere.** `concept_family_membership` references both `nodes(id)` and `concept_families(id)`; `concept_aliases` references `nodes(id)`. Every membership references a real family, every alias references a real concept, and orphans are impossible by construction.

**No tier column.** The tier is implicit: `parent_id IS NULL` ⟺ domain. A separate `tier` enum is redundant with `parent_id` and creates the possibility of the two disagreeing.

### 5.1 Aliases (families, domains, and concepts)

Two parallel mechanisms, deliberately shaped differently to fit their volume and update patterns.

**Family and domain aliases — inline column on `concept_families`.** `label` is the canonical, prompt-facing string ("Cosmic Agents"). `aliases` is a JSON-encoded array of user-facing synonyms — for `cosmology.cosmic_agents` this might be `["demiurges and powers", "cosmic powers", "world-rulers"]`. Family labels that read well as prompt headers don't necessarily read well as queries users type. Domains carry aliases the same way: `cosmology` matches the bare term but `["the cosmos", "origin of the universe"]` would also dispatch to the domain.

**Concept aliases — separate `concept_aliases` table.** Concepts outnumber families ~4×, alias counts per concept are uneven, and indexing alias→concept needs a join-table for clean LIKE behaviour. Each row is one alias for one concept: `('monad', 'the One')`, `('monad', 'the First Principle')`, `('gnosis_direct_knowledge', 'gnosis')`. The asymmetry with family aliases (inline) is intentional — small static set vs larger growing set.

**Storage asymmetry between databases.** `concept_families.aliases` is JSON-encoded text in SQLite, native `TEXT[]` in Postgres. The conversion happens in exactly one place: `export.py`'s `load_families`. Nothing reads JSON-encoded aliases at runtime in guru-web; nothing reads native arrays at runtime in the pipeline.

**Alias hygiene.** Aliases must unambiguously target one family or concept. If a phrase plausibly belongs to two — `"god"` could route to any number of families in theology and cosmology; `"light"` to `divine_light` (theology) but also `inner_light` (anthropology) — leave it off both rather than create cross-family false matches. The quality gate during alias population is: would a user typing this phrase be satisfied with the chunks they get back? If the answer is "depends on which sense they meant," it's not a good alias. Prefer longer, more specific phrases (`"the highest divine realm"`) over single tokens (`"realm"`).

**Population is incremental.** All three alias surfaces (family inline, domain inline, concept table) ship empty in v1 and accumulate as natural-language queries surface that the canonical labels fail to match. The sync script's report (§7) flags families with no aliases and concepts with no aliases as worklists. Population is not the migration's blocker.

### 5.2 What `concept_aliases` does and does not include

- `alias` is the user-facing surface string. Both single phrases ("the One") and multi-token phrases ("the absolutely simple principle") are valid.
- Aliases are *not* stored in the TOML alongside concept definitions inline — they live in a dedicated `[concept_aliases]` section (§6) so the per-family concept lists stay clean.
- Aliases are *not* shown to the LLM in the tagger prompt. The prompt sees `id`, `label`, `definition`, family context. Aliases are read-side metadata only.
- Aliases do *not* affect concept identity, definition, or tagging. A concept with 12 aliases and a concept with 0 aliases are functionally identical from the tagging path's perspective.

### 5.3 Secondary family affiliations (`is_primary = 0`)

Cross-cutting memberships live in the same `concept_family_membership` table as primaries, distinguished only by `is_primary = 0`. The primary row (one per concept) is the canonical home and drives prompt rendering, scoped dedupe, and the "domain → family → concept" path. Secondary rows are additional family-level affiliations a concept carries when the primary-family choice cuts against a genuinely cross-cutting concept.

The motivating cases are concepts like `numerical_mysticism` (primary `theology.ontological_structure`, naturally also expresses `cosmology.cosmic_order` content) and `forbidden_knowledge` (primary `soteriology.knowledge_path`, explicitly defined as the foil of the family it sits in). Today's draft handles these by encoding the cross-cutting relationship in prose inside the concept's definition. That works for a handful of cases but doesn't scale and isn't machine-readable — a shadow relational graph in unstructured text.

Secondary rows make the cross-reference first-class without forcing it through the relational-graph layer's full edge-typing system. A row says "this concept *also* belongs to family X" and that's it — no edge type, no justification, no tier. The retrieval-side query expansion (§11) doesn't distinguish primary from secondary: a query that matches family X returns all concepts with a `concept_family_membership` row pointing at X, regardless of `is_primary`.

The tagger prompt deliberately *does* distinguish. Prompt rendering uses primary rows only (`WHERE is_primary = 1`) to keep the grouping unambiguous; the LLM sees each concept in exactly one place. Secondary rows are read-side metadata only.

**Population is deferred.** Not populated in v1. The schema is open from day one but the prose-in-definition workaround is the v1 answer. The migration to populating happens organically as reviewer judgment surfaces specific cases — most often during the new-concept proposal loop's review step, when a candidate concept obviously straddles two families and the reviewer can record both rather than picking one. Same discipline as the relational-graph deferral in §3: build the simpler thing, leave the schema seam open, populate when the cost of the workaround exceeds the cost of using the seam.

**What secondary memberships are not.** Not a primary home — a concept's prompt-rendering home is always its `is_primary = 1` row, of which there is exactly one (enforced by the partial unique index). Not a relational graph between concepts — secondary rows affiliate a concept with a *family*, not with another concept. Concept-to-concept relationships remain deferred to the relational-graph layer per §3.

---

## 6. TOML restructure

`concepts/taxonomy.toml` becomes (using the §4 starting hierarchy as the worked example):

```toml
# Guru Concept Taxonomy v2 — three-tier hierarchy

# ── DOMAINS ──────────────────────────────────────────────────
[families.cosmology]
definition = "Origin and structure of the universe."
aliases    = ["the cosmos", "origin of the universe"]

[families.soteriology]
definition = "Salvation, liberation, and the soul's return."
aliases    = ["salvation", "liberation", "the soul's return"]

# ── FAMILIES (under domains) ─────────────────────────────────
[families.cosmology.divine_structure]
definition = "The architecture of the highest realms."
aliases    = ["the highest realms", "divine architecture"]

[families.cosmology.cosmic_agents]
definition = "Beings or powers acting on or within the cosmos."
aliases    = ["demiurges and powers", "cosmic powers", "world-rulers"]

# ── CONCEPTS (grouped by family) ─────────────────────────────
[concepts.cosmology.divine_structure]
emanation_hierarchy = "A chain of divine beings or principles flowing downward from a single transcendent source ..."
pleroma             = "The divine fullness or totality of the highest realm ..."
kenoma              = "The void or emptiness outside the pleroma ..."
monad               = "The absolutely simple, undivided first principle ..."
# ... aeons, logos, sephirot, sefirot_tree

[concepts.cosmology.cosmic_agents]
demiurge = "A secondary creator deity ..."
archons  = "Malevolent planetary rulers ..."
# ... ahura_mazda_principle, angra_mainyu_principle, watchers_descent

# ── CONCEPT ALIASES (dedicated section, kept separate from definitions) ──
[concept_aliases]
monad                   = ["the One", "the First Principle"]
gnosis_direct_knowledge = ["gnosis", "direct knowing"]
demiurge                = ["the craftsman", "the second power"]
# ... etc, populated incrementally
```

All alias fields (family `aliases`, domain `aliases`, `[concept_aliases]` entries) are **optional**. Domains, families, and concepts without aliases match by their canonical label only. Population is incremental — fill in aliases as natural-language queries surface that the canonical label fails to match.

The loader distinguishes domain-level (one segment after `families.`) from family-level (two segments) by counting dots in the TOML path. One-segment entries are domain rows with `parent_id = NULL`; two-segment entries are family rows pointing at the matching one-segment domain. (Alternative: explicit `[domains.X]` sectioning — rejected as more verbose for no gain, with the dot-count rule documented in a header comment at the top of the file.)

**Per-family definition is required, not optional.** The whole point of the family tier is that the LLM sees it in the prompt; an unlabelled family is dead weight. A reasonable family gloss is one sentence describing what makes the concepts in this family belong together.

**Migration of the existing TOML is mechanical.** The current `[concepts.cosmology]` flat block becomes either (a) a single domain-wide family during the first sync if hand-clustering isn't done yet, or (b) split per §4 once the clustering pass is complete. The schema and sync script work in both states. Ship the migration before finishing the hand-clustering.

---

## 7. The sync script

`scripts/sync_taxonomy.py`. Reads `concepts/taxonomy.toml`, populates `concept_families`, `concept_family_membership`, and `concept_aliases`. Idempotent — safe to run on every TOML edit.

```
sync_taxonomy.py [--db PATH] [--dry-run | --apply]
```

Default behaviour is `--dry-run`, summarising what would change. Same defaulting discipline as `auto_promote.py` and `cleanup_dupes.sh`.

Logic per run:

1. Parse TOML, build the expected state: `{family_id: (parent_id, label, definition, aliases)}`, `{concept_id: family_id}`, and `{concept_id: [aliases]}`.
2. Upsert each family row (`INSERT … ON CONFLICT(id) DO UPDATE SET parent_id=excluded.parent_id, label=excluded.label, definition=excluded.definition, aliases=excluded.aliases`). Aliases are stored as JSON-encoded text in SQLite.
3. Upsert each concept node — same pattern `promote_to_expresses` (`scripts/review_tags.py:67`) already uses for `nodes`, covering the case where a concept is in TOML but no chunk has tagged it yet.
4. Set primary memberships from the TOML. For each concept Y assigned to family X:
   - Demote any other current primary: `UPDATE concept_family_membership SET is_primary = 0 WHERE concept_id = Y AND is_primary = 1 AND family_id != X` — the demoted row stays as a secondary affiliation rather than being deleted, on the conservative assumption that the previous home may still be a legitimate cross-cutting affiliation. A `--strict-primary` flag (off by default) would instead delete the demoted row for a clean cut.
   - Upsert the target as primary: `INSERT INTO concept_family_membership (concept_id, family_id, is_primary) VALUES (Y, X, 1) ON CONFLICT(concept_id, family_id) DO UPDATE SET is_primary = 1`.
5. Replace `concept_aliases` rows for each concept that appears in the TOML's `[concept_aliases]` section: `DELETE FROM concept_aliases WHERE concept_id = ?` then `INSERT` the new alias set. Concepts not mentioned in `[concept_aliases]` are not touched (so manually-added aliases via review surfaces survive).
6. **Does not touch** existing `is_primary = 0` rows in `concept_family_membership`. Secondary memberships are populated only via review actions (§5.3), not from the TOML. The sync reads existing secondary rows and reports their count but does not write or delete them.
7. Report: `N families upserted, M primary memberships unchanged, K primary memberships moved (from→to), L primaries demoted to secondary, J concepts in DB with no primary family, F families with no concepts, A families with no aliases, C concepts with no aliases, S secondary memberships present`.

The report worklists: concepts in `nodes` with no primary family are the candidates the new-concept proposal loop should be deciding on; families with no concepts want a `--prune` review; families/concepts with no aliases are candidates for alias population as user-query patterns emerge.

### What the sync does not do

- Does not delete families, primary memberships, or alias rows that disappear from the TOML (except for the explicit alias-replace logic in step 5, which is scoped to concepts mentioned in `[concept_aliases]`). Bulk removal requires a deliberate `--prune` flag.
- Does not rewrite `edges` or `staged_tags`. Family changes are pure metadata; the concept ID a chunk was tagged against is unchanged.
- Does not write `is_primary = 0` rows. Secondary memberships are populated through review surfaces only.
- Does not LLM-classify new concepts into families. That's the proposal loop's job (§12).

---

## 8. Tagger prompt changes

`load_taxonomy()` in `tag_concepts.py` currently returns concept dicts as `{id, definition, node_id}`. Expand it to also carry `family_id`, `family_label`, `family_definition`, `domain_id`, `domain_label`, and order results by `(domain, family, concept)` so `build_prompt()` can render groups in a stable order. Aliases are **not** included — the prompt deliberately sees canonical labels and definitions only.

`build_prompt()` renders concepts grouped by family with a family header. Today's prompt block is a flat JSON array. It becomes:

```
Concepts (grouped by domain → family):

# Cosmology — origin and structure of the universe

  ## Divine Structure — the architecture of the highest realms
    - monad:               The absolutely simple, undivided first principle ...
    - pleroma:             The divine fullness or totality of the highest realm ...
    - kenoma:              The void or emptiness outside the pleroma ...
    - emanation_hierarchy: A chain of divine beings or principles flowing downward ...
    - aeons:               Divine archetypal beings ...
    - logos:               The divine reason, word, or ordering principle ...
    - sephirot:            The ten attributes or emanations of the Ein Sof ...
    - sefirot_tree:        The diagrammatic arrangement of the ten Sephirot ...

  ## Cosmic Agents — beings or powers acting on or within the cosmos
    - demiurge:            A secondary creator deity ...
    - archons:             Malevolent planetary rulers ...
    - ahura_mazda_principle: The divine ordering principle of truth and light.
    - angra_mainyu_principle: The principle of cosmic disorder and falsity.
    - watchers_descent:    The 1 Enoch narrative ...
```

The JSON output format is unchanged. The model still returns `{concept_id, score, justification, is_new_concept, new_concept_def}` per concept. The grouping is presentation-only on the prompt side.

### Token-cost discipline

The new format swaps a compact JSON array for a structured outline with ~22 family headers and per-family definitions. At 88 concepts the budget is roughly:

- Old prompt: ~88 × ~25 tokens of JSON wrapper + definition ≈ ~2.2K tokens of concept block.
- New prompt: ~88 × ~20 tokens of bulleted line + 22 × ~25 tokens of family header ≈ ~2.3K tokens of concept block.

Net cost is roughly flat — well inside budget. The real concern is *signal quality*, not token count, and the planned bench harness (per `docs/benchmark-stage4.md`) is what will make this comparable to the old prompt: agreement-with-review on the same sample set is the decision metric. Until that harness exists, run a small ad-hoc comparison on a held-out chunk sample before declaring the new prompt the default.

### Prompt version bump

`PROMPT_VERSION` in `guru/prompt.py` bumps from `v1` because the prompt structure has materially changed. The partial UNIQUE index on `staged_tags(chunk_id, concept_id, model, prompt_version)` (added in `scripts/migrations/v3_001_provenance.sql`) is what makes this safe: tags from the new prompt are distinguishable from tags from the old prompt, and the eventual training-data export filters cleanly. Old `staged_tags` stay valid; new tag runs produce new rows at the new prompt version.

---

## 9. Review surface changes

`review_tags.py` (`print_tag_row` at line 42) shows family context alongside concept:

```
======================================================================
CHUNK:   chunk.gnosticism.gospel-of-thomas.0042
SECTION: Logion 22
----------------------------------------------------------------------
BODY:    When you make the two one ...
----------------------------------------------------------------------
CONCEPT: opposites_transcended
FAMILY:  anthropology → spiritual_completion
         — The realised state of the human being.
DEF:     The dissolution of binary oppositions (male/female, inner/outer,
         above/below) as a mark of spiritual completion.
SCORE:   3/3
LLM:     ...
```

The two extra lines are trivial to render and meaningfully help the reviewer — "is this concept in the right family for this passage?" is a useful sanity check the current flat presentation doesn't surface. `review_edges.py` and the guru-review web tool get the same family display.

The existing `[a]ccept / [r]eject / [c]reassign / [s]kip / [q]uit` action set is sufficient; reassign-across-families is just reassign with a different concept ID.

---

## 10. guru-web propagation

The hierarchy has to land on the VPS Postgres mirror for guru-web to query against. The data plane is half-mirrored already.

### 10.1 Current state in guru-web

guru-web's Postgres already has (at `schema/corpus-schema.sql:56-61`):

```sql
CREATE TABLE concepts (
    id         TEXT PRIMARY KEY,
    label      TEXT NOT NULL,
    domain     TEXT,
    definition TEXT
);
```

`export.py:217-238` (`load_concepts`) reads the current TOML, looks up domain via `tax["concepts"][domain]`, and emits the four columns above. So `domain` is already crossing the boundary as a flat string — it just isn't normalised into its own table, and the family tier doesn't exist on either side.

### 10.2 Schema additions

Three new tables in `schema/corpus-schema.sql`, mirroring the SQLite shape:

```sql
CREATE TABLE concept_families (
    id          TEXT PRIMARY KEY,
    parent_id   TEXT REFERENCES concept_families(id),
    label       TEXT NOT NULL,
    definition  TEXT NOT NULL,
    aliases     TEXT[] NOT NULL DEFAULT '{}'   -- native Postgres array; see §5.1
);

CREATE TABLE concept_family_membership (
    concept_id  TEXT NOT NULL REFERENCES concepts(id),
    family_id   TEXT NOT NULL REFERENCES concept_families(id),
    is_primary  BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (concept_id, family_id)
);

CREATE UNIQUE INDEX idx_concept_primary_family
    ON concept_family_membership(concept_id) WHERE is_primary;

CREATE INDEX idx_concept_family_membership_family
    ON concept_family_membership(family_id);

CREATE TABLE concept_aliases (
    concept_id  TEXT NOT NULL REFERENCES concepts(id),
    alias       TEXT NOT NULL,
    PRIMARY KEY (concept_id, alias)
);

CREATE INDEX idx_concept_aliases_alias
    ON concept_aliases(alias);
```

The Postgres `is_primary` is a native `BOOLEAN`; SQLite uses `INTEGER` with `0`/`1` values. The export step (§10.3) converts at emit time.

The Postgres `concept_families.aliases` column uses the native `TEXT[]` array type rather than SQLite's JSON-encoded text. The export step (§10.3) handles the conversion in exactly one place: read JSON-encoded aliases from SQLite, emit as Postgres array literals.

Plus one denormalised column on the existing `concepts` table:

```sql
ALTER TABLE concepts ADD COLUMN family_id TEXT REFERENCES concept_families(id);
```

The `family_id` column on `concepts` is intentionally redundant with `concept_family_membership`. The common read pattern is "filter or group chunks by family," which without denormalisation needs a three-way join (`chunks` → `edges` (EXPRESSES) → `concepts` → `concept_family_membership`). With `concepts.family_id` it's a two-way join. The membership table stays as the audit table; `concepts.family_id` is the convenience column.

The existing `concepts.domain` column also stays. It's derivable (`concept_families.parent_id` of the row pointed at by `family_id`), but every existing query in `src/lib/` that filters by domain keeps working unchanged. Removing it is a separate cleanup.

### 10.3 Export changes

`export.py` adds three new emitter blocks and an enrichment to the existing one:

1. `load_families()` — read `concept_families` from SQLite (including the JSON-encoded `aliases` column), emit `concept_families` rows with aliases converted to Postgres array literal syntax.
2. `load_concept_family_membership()` — read the membership table including `is_primary`, emit each row to Postgres converting `0`/`1` to `FALSE`/`TRUE`. In v1 every row has `is_primary = 1` (only primaries populated); the column carries through cleanly when secondary rows start appearing.
3. `load_concept_aliases()` — read the aliases table, emit it. Empty until aliases get populated.
4. `load_concepts()` already merges TOML and `nodes`; extend it to also pull each concept's primary `family_id` (from `WHERE is_primary = 1`) into the new `concepts.family_id` column.

Schema isolation via `corpus_new.*` (the existing staging-then-swap pattern at `export.py:52-53`) extends to the new tables for free — they're created in the staging schema and atomic-renamed into `corpus` at load time, same as everything else. `SCHEMA_VERSION` in `export.py:46` bumps from 2 to 3.

### 10.4 Apply path on the VPS

Matches the existing pattern: `sudo -u postgres psql guru < export/guru-corpus.sql`. The exported `.sql.gz` is self-contained — it creates the staging schema, loads, swaps. No separate migration step needed on the VPS for the new tables; they appear in the staging schema and are promoted by the existing swap.

---

## 11. guru-web query plane

This is the section where the user-visible benefit shows up. The schema mirror is necessary but not sufficient — without query-side changes, typing `cosmology` still matches no concept and falls through to pure vector search.

### 11.1 Current concept extraction

`src/lib/graph.ts:16` (`extractConcepts`) does a `LIKE` match of query tokens against `concepts.label`. The pattern is `%token%` substring match (lowercased). Concept labels are things like `Demiurge`, `Monad`, `Theosis` — none match a high-level query like `cosmology` or `salvation`, and the synonyms a user actually types (`the One` for monad, `the cosmos` for cosmology) miss entirely. Today such queries return zero concepts and the retriever silently degrades to pure vector search (`src/lib/retriever.ts`, the `Promise.all` over vectorSearch + graphSearch).

### 11.2 Hierarchy-aware extraction

Extend `extractConcepts` to match query tokens simultaneously across three label namespaces, not in priority order — a query "cosmology demiurge" should hit both the domain expansion AND the direct concept:

1. **Concept labels and aliases** — `monad` matches `concepts.label`; `the One` matches a row in `concept_aliases`. Both dispatch to `concept.monad`.
2. **Family labels and aliases** — `cosmic agents` matches `concept_families.label`; `demiurges and powers` matches an entry in `concept_families.aliases`. Both dispatch to family `cosmology.cosmic_agents`, which expands to all concepts with a `concept_family_membership` row pointing at that family — `is_primary` is ignored for the retrieval-side expansion (primary and secondary are co-equal at read time).
3. **Domain labels and aliases** — `cosmology` matches the domain label; `the cosmos` matches its aliases. Both dispatch to domain `cosmology`, expanding to all concepts whose family's `parent_id` is `cosmology`, again regardless of `is_primary`.

Each match emits `(concept_id, match_tier)` where `match_tier ∈ {concept, family, domain}`. Secondary memberships carry the same match tier as primaries — at read time, a secondary affiliation is a co-equal family affiliation. The downstream `walkGraph` (`src/lib/graph.ts:41`) consumes the concept set the same way it does today.

**Matching semantics — substring LIKE everywhere.** All three paths use `%token%` substring match against lowercased values, the same as today's concept-label match. For aliases that means:

- Concept aliases: `WHERE EXISTS (SELECT 1 FROM concept_aliases ca WHERE ca.concept_id = concepts.id AND LOWER(ca.alias) LIKE $1)`.
- Family/domain aliases (Postgres TEXT[]): `WHERE LOWER(label) LIKE $1 OR EXISTS (SELECT 1 FROM unnest(aliases) a WHERE LOWER(a) LIKE $1)`.

Equality matching would mean "cosmic powers" hits but "the cosmic powers" misses — wrong semantics for free-text queries. The substring pattern matches the existing label-LIKE behaviour so the three namespaces are uniform.

**v1 with empty alias tables.** All alias matches return zero rows in v1. Queries match canonical labels only, which is exactly today's behaviour for the concept path plus the new family/domain paths. Aliases earn their keep as they get populated; the query code is correct from day one and just lights up more results over time.

### 11.3 Ranking

Match tier matters for ranking, not graph traversal. A query that directly named `monad` should not be treated as equivalent to a query that named `cosmology` and got `monad` as one of 26 expanded concepts. Default: scalar weight by match tier — concept = 1.0, family = 0.5, domain = 0.25 — multiplied into the chunk-level score `retriever.ts` already computes. A multi-concept-overlap requirement on expanded matches is a tunable to reach for if scalar weights produce noisy results in practice; not pre-emptive.

An alias match (at any tier) carries the same weight as the canonical-label match at that tier. A user typing `"the One"` and a user typing `"monad"` should get the same chunk ranking; the alias is just a different surface form of the same intent.

---

## 12. New-concept proposal loop integration

The proposal loop (not yet built; lives in this design's slipstream) is the planned pipeline where periodic LLM passes over un-tagged or low-confidence chunks surface candidate new concepts for human review. What the hierarchy unlocks for that loop:

**Scoped dedupe.** When the proposal pass produces a candidate concept, the dedupe step (cosine similarity of candidate definition vs existing concept definitions) runs *family-scoped*: predict the candidate's family first via a cheap LLM classification call against family definitions, then compute similarity only against concepts in that family. Cross-family similarity is also computed but at a higher threshold — a candidate that looks like an existing concept across family lines is more likely a genuine new concept than a duplicate, so the bar for "merge instead of accept" is higher.

**Bootstrap caveat.** Family-scoped dedupe is bounded above by family-definition quality. Early in the taxonomy's life — particularly during the first two or three proposal cycles after hand-clustering — family definitions will be rough and the classifier's family predictions will be noisy. Plan for more cross-family false-negatives during this period and re-evaluate the family glosses after each cycle. The fix is iteration on family definitions, not abandoning the scoping.

**Review framing.** The candidate-concept reviewer shows: predicted family, the existing concepts in that family with their definitions, the candidate's definition, and the nearest-sibling-by-similarity. The reviewer's decision space — accept new concept, merge into existing sibling, reject, reassign to a different family — is structured around the family tier rather than the flat 88-concept space.

**Acceptance writes family membership.** When a candidate concept is accepted, the reviewer confirms or edits the predicted family, and the sync script (or the review action directly) writes the `concept_family_membership` row. The new concept appears in the tagger prompt under its family on the next tag run.

**Family inflation control.** Concept inflation has its own caps (minimum supporting chunks, minimum tradition diversity, maximum similarity to existing concepts). Family inflation needs a separate, stricter cap. A candidate concept that doesn't fit any existing family is far more often a genuine new concept that *does* fit a family the reviewer hasn't considered than the seed of a brand-new family. Default: the reviewer can propose a new family, but it requires explicit confirmation and at least 3 supporting concepts (current + 2 future candidates).

---

## 13. Migration plan

Strict ordering. Each step is independently shippable and a no-op for already-tagged data.

1. **SQLite migration** — `scripts/migrations/v3_006_concept_families.sql` creates `concept_families` (with `aliases`), `concept_family_membership` (with `is_primary` and the partial unique index), and `concept_aliases`. Idempotent.
2. **Restructure `taxonomy.toml`** with the new sectioning. Even at this step every family can be a single-tier mirror of the old categories (one family per domain, containing all that domain's concepts). The file parses, the sync script works, the tagger prompt renders — the family tier just isn't doing much work yet.
3. **`scripts/sync_taxonomy.py`** populates the three new SQLite tables (families, primary memberships at `is_primary = 1`, concept aliases). Run with `--dry-run` first, eyeball the report, then `--apply`. Secondary memberships (`is_primary = 0`) are left empty by the sync; populated only via review actions.
4. **Update `load_taxonomy()` and `build_prompt()`** to render grouped. Bump `PROMPT_VERSION` from `v1`. **This is the moment the LLM starts seeing structure.** New tag runs from this point use the new prompt; old `staged_tags` remain valid at `v1`.
5. **Ad-hoc bench** — run the new prompt against the old on a held-out sample (50–100 chunks). Decision metric: agreement-with-review at score ≥ 2. Once the planned bench harness ships (`docs/benchmark-stage4.md`), the comparison becomes formalised.
6. **Hand-cluster per §4** into proper two-tier families. Edit TOML, re-run sync. The membership table updates via the `ON CONFLICT(concept_id) DO UPDATE` clause; no other table is touched. Iterate as the right family structure becomes clearer.
7. **Update review surfaces** — `print_tag_row` in `review_tags.py`, equivalents in `review_edges.py` and the guru-review web UI. Cosmetic, low-risk.
8. **Update `export.py`** to emit the new tables (`concept_families` with aliases, `concept_family_membership` with `is_primary`, `concept_aliases`) and the `concepts.family_id` column; bump `SCHEMA_VERSION` to 3. Update `guru-web/schema/corpus-schema.sql` to match.
9. **Run a full export + VPS apply** to land the schema on the Postgres mirror.
10. **Update `extractConcepts` in `src/lib/graph.ts`** for family/domain matching with scalar weight by match tier, substring LIKE against label + aliases across all three namespaces. Verify against representative high-level queries (`cosmology`, `the cosmos`, `cosmic agents`, `the One`, `salvation`).
11. **Family-aware new-concept proposal loop** is built on this foundation as separate work.

Steps 1–10 are the migration. Step 11 is future work.

### Time estimates

- Steps 1–4 (schema, TOML restructure, sync script, prompt change): half a day.
- Step 5 (ad-hoc bench): half a day including reviewing the diff.
- Step 6 (hand-clustering 88 concepts per §4): three to five hours. Clustering for an LLM prompt is more intellectual work than clustering for a database — every family gloss has to read well as a prompt header, and §4 is a starting point that will move during the pass.
- Steps 7–10 (review surfaces, export, VPS apply, guru-web query): one day.

---

## 14. Rollback

If the migration needs to be unwound:

```sql
-- SQLite
DROP TABLE concept_aliases;
DROP TABLE concept_family_membership;
DROP TABLE concept_families;

-- guru-web Postgres
DROP TABLE concept_aliases;
DROP TABLE concept_family_membership;
DROP TABLE concept_families;
ALTER TABLE concepts DROP COLUMN family_id;
```

`tag_concepts.py` and `extractConcepts` revert by checking out the prior commit. `PROMPT_VERSION` and `SCHEMA_VERSION` revert. No `staged_tags`, `edges`, `nodes`, or chunk data is touched.

---

## 15. What this does not solve

- **Concept identity drift.** If a concept's definition needs to materially change after it's been tagged against, that's still a manual operation (rewrite TOML, decide whether existing tags carry forward, possibly bump prompt version and re-tag a sample). The hierarchy doesn't make this harder, but it doesn't make it easier either.

---

## 16. Open questions

- **Family granularity per §4.** Some families are small by design (`ecstatic_modes` at 2, `soteric_categories` at 2, `transformative_path` at 2) and ethics is a single family. The clustering pass will pressure-test whether these hold up or want to collapse / split. Pre-committing to a target distribution is the wrong move; let the clustering pass surface the answer.
- **Family definition style.** One sentence describing what makes the family coherent ("Beings or powers that act on or within the cosmos") versus one sentence describing what concepts in the family share ("Concepts naming individual cosmic agents"). The first reads better as a prompt header; the second is more precise. Recommend the first with a note in the prompt that the family is a grouping, not a definition.
- **Per-tier match weight tuning.** The 1.0 / 0.5 / 0.25 scalar in §11.3 is a guess. The right values are an empirical question once there's real query traffic to look at.
- **Concepts that genuinely span families** (e.g. `numerical_mysticism`, `forbidden_knowledge`). Two-level policy in the unified `concept_family_membership` table: the `is_primary = 1` row records the dominant family (drives prompt rendering, scoped dedupe, the canonical home); `is_primary = 0` rows record secondary affiliations for retrieval. v1 has only primary rows — the prose-in-definition workaround handles current cases and the seam is open. The open question is the *population trigger*: a reviewer-driven workflow (every `[c]reassign` action in the candidate-concept reviewer offers a "keep the old family as secondary?" option) is probably right, but the UX hasn't been designed. The exit ramp to the relational graph layer is still real — secondary memberships handle family-level cross-cutting but not concept-to-concept relationships.
- **Whether to surface families through the corpus metadata endpoint.** `src/app/api/corpus/route.ts` could return the family tree alongside traditions/texts so the UI can build a navigator. Straightforward but independent from the query-extraction work in §11.
- **Vector-path enrichment from aliases (future).** Today `vectorSearch` embeds the raw user query and is completely isolated from the hierarchy. A future enhancement could use alias matches as a signal to enrich the vector path: when a query matches a family alias, do a second embedding pass on the family definition and blend the vector results, or at index time factor family definitions into chunk embeddings so the embedded chunks know their family. Both would move the retrieval needle further than the keyword path can on its own, but neither is in scope for this migration — they want their own spec once the keyword path is in production and we have query-traffic data to inform the design.
