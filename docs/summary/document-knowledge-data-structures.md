# Data Structures: Document-Knowledge Layer

Tight scope: **`text_dossiers` + `summary_nodes` only.** Tradition dossiers, concept
profiles, and summary-driven edge candidate generation are explicitly deferred —
nothing here touches `edges`, `nodes`, or the tag/tier machinery.

> **Verification status (2026-07-04):** checklist §6 run against the live DB
> (`data/guru.db` @ 2197d2a) and the chunk TOMLs. Results are recorded inline
> per item. Corpus figures in §1.3.5 are remeasured — the draft's numbers were
> stale (pre-dating the Plotinus apparatus strip 79e876b and the Zhuangzi
> rescope 12bd639) and counted texts at the wrong granularity (see V10 —
> added by the audit, decided 2026-07-04: the works layer, §6.1).

Two deliberate reductions from the proposal draft:

- **Dossiers carry no embedding.** In study mode the dossier is fetched by PK for the
  pinned `study_scope.text_id` — it is *injected*, never *retrieved*. No vector, no
  ANN index, no pool-pollution question.
- **Only `summary_nodes` are retrievable**, and only in study mode.

---

## 1. Pipeline side — SQLite (`data/guru.db`)

New migration `scripts/migrations/v3_007_document_knowledge.sql`, following the local
migration sequence (`v3_001`…`v3_006`). Conventions mirrored from `scripts/schema.sql`:
staging tables with `status`/`reviewed_by`/`reviewed_at` (the `staged_tags` /
`staged_edges` pattern), model+prompt provenance on staged rows (the `v3_005` pattern),
embeddings in a separate BLOB table with per-row `dim`/`model` (the `chunk_embeddings`
pattern), JSON as TEXT (the `nodes.metadata_json` pattern).

```sql
-- v3_007_document_knowledge.sql
-- Idempotent: IF NOT EXISTS everywhere, matching scripts/schema.sql.

-- ============================================================
-- STAGING — Pass D: dossier + summary generation (build_dossiers.py)
-- ============================================================
-- Per-FIELD staging: each dossier field is its own generation unit with
-- its own prompt template and template version (§1.3). One row per
-- (text, field, model, prompt_version) attempt. payload_json is that
-- field's output only, validated against the field's contract before
-- insert (reject-and-retry on parse failure, like tag_concepts.parse_tags).
-- The composed dossier only exists at promotion time (live table below).

CREATE TABLE IF NOT EXISTS staged_dossier_fields (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    text_id         TEXT NOT NULL,              -- manifest source id; texts live in TOML, not nodes
    field           TEXT NOT NULL
                        CHECK(field IN ('summary','context','structure_entry',
                                        'key_figures','key_terms','reading_notes')),
    -- structure_entry rows are per-section: one row per span, keyed here.
    -- NULL for whole-text fields.
    section_span    TEXT,
    payload_json    TEXT NOT NULL,              -- field-specific shape (§1.3)
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending','accepted','rejected')),
    reviewed_by     TEXT,
    reviewed_at     TEXT,
    model           TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,              -- per-FIELD template version, e.g. 'context-v3'
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- Re-runs against the same field template don't dupe; settled rows coexist
-- with new pending proposals from a revised template (v3_005 partial-unique
-- pattern). COALESCE folds NULL section_span into the key for SQLite.
CREATE UNIQUE INDEX IF NOT EXISTS idx_staged_dossier_fields_provenance_unique
    ON staged_dossier_fields(text_id, field, COALESCE(section_span, ''), model, prompt_version)
    WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_staged_dossier_fields_status
    ON staged_dossier_fields(status);
CREATE INDEX IF NOT EXISTS idx_staged_dossier_fields_text
    ON staged_dossier_fields(text_id, field);

CREATE TABLE IF NOT EXISTS staged_summaries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    summary_id      TEXT NOT NULL,              -- 'sum:enuma-elish:t4' / 'sum:enuma-elish' / 'fold:plotinus…:0-3'
    text_id         TEXT NOT NULL,
    -- level 0 = internal FOLD (summary of L1/fold bodies, §1.3.5): pipeline
    -- scaffolding for oversized texts. Never promoted, never exported.
    level           INTEGER NOT NULL CHECK(level IN (0, 1, 2)),
    section_span    TEXT,                       -- printable, e.g. 'Tablet IV' (NULL for level 2)
    child_chunk_ids TEXT,                       -- JSON array, level 1 only, corpus order
    child_summary_ids TEXT,                     -- JSON array, levels 0 and 2 built from folds/L1s
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
CREATE INDEX IF NOT EXISTS idx_staged_summaries_text   ON staged_summaries(text_id);
CREATE INDEX IF NOT EXISTS idx_staged_summaries_status ON staged_summaries(status);

-- ============================================================
-- LIVE — promoted artifacts (what export.py reads)
-- ============================================================
-- Promotion (accepted staged row → live row) happens in the review tool
-- (review_dossiers.py, in the mold of review_tags.py) or via a
-- promote_dossiers.py batch, mirroring the auto_promote.* pattern.
-- Live rows carry generation provenance forward.

CREATE TABLE IF NOT EXISTS text_dossiers (
    text_id         TEXT PRIMARY KEY,
    summary         TEXT NOT NULL,              -- 150–300 tokens; the study-prompt injection block
    context         TEXT NOT NULL,              -- dating, provenance, transmission
    structure_json  TEXT NOT NULL,              -- [{section_span, title, synopsis, chunk_ids[]}] in reading order
    key_figures_json TEXT NOT NULL,             -- [{name, role, gloss}]
    key_terms_json  TEXT NOT NULL,              -- [{term, transliteration, gloss}]
    themes_json     TEXT NOT NULL,              -- taxonomy concept ids (display only; NOT edges)
    reading_notes   TEXT,
    manifest_notes  TEXT,                       -- verbatim sources/manifest.toml `notes`
    -- Per-field template versions, semicolon-joined in a fixed field order:
    -- 'summary-v3;context-v2;structure-v1;figures-v1;terms-v1;notes-v1'.
    -- Manually-fixed fields record 'field-manual'. Phase-0 rows record
    -- 'manifest' (see note below).
    generated_by    TEXT NOT NULL,
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- Phase-0 note (no-LLM bootstrap): summary/context are NOT NULL, so
-- generated_by='manifest' rows populate them mechanically — summary :=
-- manifest_notes verbatim; context := the translator/source line composed
-- from manifest metadata ("Translation: {translator}. Source: {source_url}.");
-- structure_json/figures/terms := '[]', themes := '[]'. LLM phases then
-- overwrite field-by-field via normal promotion.

CREATE TABLE IF NOT EXISTS summary_nodes (
    id              TEXT PRIMARY KEY,           -- 'sum:{text_id}[:{span_slug}]'
    text_id         TEXT NOT NULL,
    tradition       TEXT NOT NULL,              -- denormalized like chunks, for zero-join scope filtering
    level           INTEGER NOT NULL CHECK(level IN (1, 2)),
    section_span    TEXT,
    child_chunk_ids TEXT NOT NULL,              -- JSON array; provenance + invalidation key
    body            TEXT NOT NULL,
    token_count     INTEGER NOT NULL,
    generated_by    TEXT NOT NULL,
    -- Invalidation: hash over sorted TRANSITIVE child chunk bodies at
    -- generation time (for L2 this reaches through pipeline folds, matching
    -- how exported child_chunk_ids is computed). Rebuild detection =
    -- recompute and compare; any re-chunk/re-clean of a descendant chunk
    -- (e.g. the todo:b80d8d7d clean-body re-embed) flips it.
    children_hash   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_summary_nodes_text ON summary_nodes(text_id);

-- Embeddings: separate table, float32 LE BLOB — the chunk_embeddings pattern
-- exactly, so embed_corpus.py's writer path is reused with a different target.
CREATE TABLE IF NOT EXISTS summary_embeddings (
    summary_id  TEXT PRIMARY KEY REFERENCES summary_nodes(id) ON DELETE CASCADE,
    dim         INTEGER NOT NULL,
    model       TEXT NOT NULL,
    vector      BLOB NOT NULL
);
```

### 1.1 Per-field `payload_json` contracts (staged_dossier_fields)

Each field is generated by its own prompt (§1.3) and validated against its own shape:

| `field` | `payload_json` shape |
|---|---|
| `summary` | `{"body": "…"}` — 150–300 tokens |
| `context` | `{"body": "…"}` — hedging rules enforced by template + rubric |
| `structure_entry` | `{"section_span": "Tablet I", "title": "…", "synopsis": "…"}` — one row per span; `chunk_ids` are attached at promotion from the span→chunks map, never model-emitted |
| `key_figures` | `{"figures": [{"name": "…", "role": "…", "gloss": "…"}]}` |
| `key_terms` | `{"terms": [{"term": "…", "transliteration": "…", "gloss": "…"}]}` |
| `reading_notes` | `{"body": "…"}` — optional field; a text may legitimately have none |

**`themes` is not generated at all** — it is *derived* at promotion time from the
text's chunks' accepted concept tags (top-N `EXPRESSES` targets by count, tier-weighted
via the existing verified/proposed/inferred weights). Zero LLM calls, automatically
taxonomy-consistent, automatically current when tags change. One less prompt to
converge and the one field where hallucination risk was pure downside.
(Verified: live EXPRESSES edges carry only `verified` (24,180) and `proposed`
(11,085) tiers — no `inferred` rows exist yet; the weighting must not assume
all three tiers are present. Coverage is thin at the tail: 79/211 texts have
<10 accepted tags, 56 have <5, 4 have zero — the min-N floor in V5 is a real
decision, not an edge case.)

**Promotion = assembly.** `promote_dossiers.py` composes the live `text_dossiers` row
from the latest **accepted** row per (field, span): whole-text fields map to their
columns; `structure_entry` rows sort into `structure_json` by corpus span order with
`chunk_ids` joined in; `themes_json` is derived as above. A text promotes only when
its required fields (`summary`, `context`, all `structure_entry` spans) have accepted
rows — partial dossiers never go live. `generated_by` records the per-field template
versions (e.g. `summary-v3;context-v2;structure-v1`) so a live dossier is exactly
reproducible.

### 1.2 Two grounded caveats

- **Section grouping cannot use `section_path`** — it is unpopulated end-to-end
  (`export.py` line ~484 asserts `section_path is None`). Level-1 groups therefore
  come from the per-text chunking config in `chunking/` + corpus TOML chunk order,
  with the printable `section` parsed per `texts.sections_format`. `child_chunk_ids`
  order is corpus order, which is reading order.
- **Summaries are generated over cleaned bodies**: port `NAV_PREFIX` / `PAGE_MARKER`
  / `APPARATUS_DROP` from `guru-web/src/lib/retriever.ts` into the build script so
  the ~32% sacred-texts nav pollution documented there never reaches a summary.
  **A straight port is not sufficient (V8, verified):** Enuma Elish chunk 001
  opens with `"Sacred-Texts Ancient Near East ENUMA ELISH … King Translator …
  A more complete etext … is also available here."` and none of the three
  regexes touch it — `NAV_PREFIX` requires `Sacred Texts` (space, not hyphen)
  *and* a `Previous Next` marker, both absent. The build script needs a
  hardened variant (hyphenated prefix, header-without-nav-links form) plus the
  V8 per-domain sample before L1 generation.

### 1.3 Generation prompt contracts + review loop

#### 1.3.1 The generation DAG

Each field is a **separate prompt with a separate, versioned template** — no one-shot
dossier generation. Later stages consume *earlier generated artifacts*, not raw chunks,
which keeps every context window small on the local rig and makes each stage
independently reviewable and regenerable:

```
cleaned chunk bodies (per span; spans PACKED to input budget, §1.3.5)
   └─► L1  level-1 summary            (input: span's chunk bodies)
          ├─► [F  fold summaries]     (only when ΣL1 bodies > budget; recursive)
          │      └─► L2  level-2 summary   (input: L1 bodies, or top folds)
          │             ├─► D1  dossier.summary     (input: L2 + manifest notes)
          │             └─► D2  dossier.context     (input: manifest notes + L2)
          ├─► D3  structure_entry (per span)         (input: that span's L1 body)
          └─► D4/D5  key_figures / key_terms         (map per-L1 → reduce; §1.3.5)
D6  dossier.reading_notes                            (input: accepted D2 + D3 set)
—   themes: derived from accepted concept tags — no generation stage
```

Consequences of the DAG shape:

- A template revision regenerates **only its stage and downstream** — revising
  `structure-v1 → v2` never touches summaries; revising `l1-v1 → v2` invalidates
  everything (which is correct: L1 is the grounding layer).
- Stage inputs are staged rows, so `build_dossiers.py` resumes per (text, field, span),
  the same granularity `tagging_progress` gives Pass B.
- Only **L1 reads primary text**. Every hallucination-control question therefore
  concentrates on one template; everything above it is summarization-of-summaries
  with a closed input.

#### 1.3.2 Shared preamble (all templates)

```
You are generating reference apparatus for a study edition of {text_label}
({tradition_label}). Your output is editorial apparatus, not commentary:
describe, do not interpret or evaluate.

Rules for all outputs:
- Write in third person, present tense, neutral scholarly register.
- No cross-tradition comparison. No superlatives ("greatest", "most important").
- No direct address ("you", "the reader will").
- Use figures' and terms' names as this text/translation uses them.
- Do not quote or reference any work outside the provided input.
- Output EXACTLY the format requested. No preamble, no markdown fences.
```

#### 1.3.3 Field templates, v1

**`l1-v1` — level-1 summary** (input: cleaned chunk bodies of one span, in order)

```
INPUT: the complete text of {section_span} of {text_label}, in reading order.

Write a summary of {budget} tokens (±20%) stating what happens or what is
said in this span, in the order it occurs.

- Every statement must be supported by the input text. If the input is
  fragmentary or obscure, say "the text is fragmentary/unclear here" rather
  than filling gaps.
- Name every figure who acts or speaks, as the text names them.
- Describe; do not interpret, moralize, or explain significance.

OUTPUT: the summary as plain prose. Nothing else.
```

`{budget}` scales with span size: `clamp(child_token_count / 12, 80, 300)`.

**`l2-v1` — level-2 summary** (input: all accepted L1 bodies, in order)

```
INPUT: section-by-section summaries of {text_label}, in reading order.

Write a 200–350 token summary of the whole text: its overall movement from
beginning to end, its principal figures, and how its parts relate.

- Draw only on the input summaries.
- Preserve the text's own proportions — do not let one famous episode
  dominate if it is one section among many.

OUTPUT: the summary as plain prose. Nothing else.
```

**`summary-v1` — dossier summary** (input: L2 body + `manifest_notes`)

```
INPUT: (1) a summary of {text_label}; (2) curator's notes.

Write the 150–300 token introduction a reader sees before studying this text.
Make exactly three moves, in order:
1. CLASSIFICATION — what kind of text this is (genre, form, tradition,
   language of composition if stated in the input).
2. CONTENTS — what the text contains, compressed from the input summary.
3. SIGNIFICANCE — why it is read, ONLY as supported by the curator's notes;
   if the notes are silent on significance, omit the third move entirely.

OUTPUT: {"body": "..."} as a single JSON object. Nothing else.
```

**`context-v1` — historical context** (input: `manifest_notes` + L2 body)

```
INPUT: (1) curator's notes on {text_label}; (2) a summary of its contents.

Write 100–250 tokens answering, in order, only those that can be answered:
language and composition; dating; attestation and transmission; this
translation ({translator}, from the source named in the curator's notes).

Dating and attribution rules (strict):
- Every date is a RANGE or is marked "traditionally dated", never a bare year.
- Every dating claim names its basis ("tablets dated to...", "linguistic
  evidence suggests...", "per the curator's notes...").
- Where scholarship is unsettled, say so plainly ("dating is contested").
- If the input does not support an answer, omit that question — do not
  supply dates or transmission history from general knowledge.

OUTPUT: {"body": "..."} as a single JSON object. Nothing else.
```

**`structure-v1` — structure entry** (input: one span's L1 body)

```
INPUT: a summary of {section_span} of {text_label}.

OUTPUT a single JSON object: {"title": "...", "synopsis": "..."}
- title: 2–6 words naming what this span contains, in the register of a
  table of contents ("The Creation of Humanity", not "Amazing Origins!").
- synopsis: at most 2 sentences compressing the input summary. Descriptive
  present tense. No interpretation.
Nothing else.
```

**`figures-v1` — key figures** (input: all L1 bodies)

```
INPUT: section-by-section summaries of {text_label}.

OUTPUT a JSON object {"figures": [{"name": "...", "role": "...", "gloss": "..."}]}
listing the 4–10 figures most central to this text.
- name: as used in the input. role: 2–5 words ("storm god, slayer of Tiamat").
- gloss: ≤25 words, definitional register, stating only what the input
  supports about this figure IN THIS TEXT.
- Order by centrality. Include a figure only if it acts or is acted upon
  in the input — not merely mentioned once.
Nothing else.
```

**`terms-v1` — key terms**: identical frame to `figures-v1` over technical/
transliterated vocabulary; `transliteration` null when not applicable; ≤10 terms;
a term qualifies only if understanding it is required to follow the text.

**`notes-v1` — reading notes** (input: accepted context body + assembled structure)

```
INPUT: (1) the historical context note for {text_label}; (2) its section outline.

If useful, write ≤120 tokens of practical reading guidance: a sensible
reading order if non-linear, sections commonly read first, translation
caveats stated in the context note, difficulty notes.
- Only guidance derivable from the input. No study-plan padding.

OUTPUT: {"body": "..."} — or {"body": null} if the outline speaks for itself.
```

#### 1.3.4 Review loop — the template is the unit of refinement

Accept/reject per row exists (the staging columns), but the *converging* loop is:

```
generate batch under {field}-vN
  → sample-review K rows per field against the rubric (K≈15 texts, stratified
    by tradition and text length; structure entries sampled per-span)
  → classify failures by rubric code
  → failures cluster on a rule?  → revise the TEMPLATE → vN+1 → regenerate
     (cheap: local 3090, resumable, only the stage + its DAG descendants)
  → failures idiosyncratic to a text? → fix that row manually as a new staged
     row with model='manual', prompt_version='{field}-manual' — the promoter
     prefers manual rows over any template version, and bulk regeneration
     never targets them, so they're never clobbered
  → rubric passes on a fresh sample → bulk-accept the field's batch
```

Folds participate in the same flow: L2 for a folded text reads only **accepted**
fold rows, and fold review is folded into L2's sample (a bad fold shows up as an
L2 `COVERAGE`/`GROUND` failure and is traced down via `child_summary_ids`).

Rubric codes (what a reviewer marks, and what template revisions answer to):

| code | failure | typical template fix |
|---|---|---|
| `GROUND` | claim unsupported by the stage's input | tighten "draw only on the input" / add fragmentary-text escape |
| `HEDGE` | bare date, unattributed dating claim (context only) | strengthen dating rules block |
| `REGISTER` | evaluative, second-person, or devotional drift | extend preamble ban list with the observed phrase pattern |
| `COVERAGE` | L1/L2 skips or disproportionately weights spans | add proportion rule; adjust `{budget}` formula |
| `LEAK` | references a work outside the input | tighten outside-work ban; check nav-cleaning caught the source |
| `FORMAT` | output shape violation surviving the parser | tighten OUTPUT clause; add reject-retry pattern |
| `COMPARE` | cross-tradition comparison in apparatus | reinforce preamble rule |

Two properties make this converge rather than churn: **comparability is the
template** — every text answers the same interrogation in the same order under the
same budgets, so cross-text review is diffing like against like; and **provenance is
already load-bearing** — `prompt_version` per field means superseded generations stay
queryable for before/after diffs, and the partial-unique index permits re-proposal by
design. Mechanically this is `tag_concepts.py:build_prompt` discipline applied to
prose: templates live as versioned files under `prompts/dossier/{field}-vN.md`,
loaded by `build_dossiers.py`, with the filename as the `prompt_version` value.

#### 1.3.5 Input budgets and the fold strategy

The one-prompt-per-stage picture holds for most of the corpus but not its tail —
or its *head*: most texts are small enough that the hierarchy degenerates (below).
Remeasured 2026-07-04 from the chunk TOMLs (`corpus/*/*/chunks/*.toml`,
`chunk.token_count`), cross-checked against live `nodes` (counts agree exactly):

| | |
|---|---|
| texts | **211 text dirs** · 4,176 chunks · 2.56M tokens — but ~115 dirs are chapter/tablet **shards** of ~102 base works (V10) |
| median text | **~1.5k tokens** (190/211 ≤ 24k; 169/211 fit a single 6–8k span; 110 have ≤ 2 chunks) |
| tail | 12 texts > 50k — Plotinus *Select Works* **373.6k** (752 chunks, post-apparatus-strip 79e876b), Book of the Dead 261k, Kalevala 186k, Tertium Organum 165k, Mabinogion 141k, Pistis Sophia 121k, Boehme *Life and Doctrines* 118k, Iamblichus *On the Mysteries* 114k … Zhuangzi was rescoped to the Inner Chapters (12bd639) and is now 42k — **out of the tail and out of V3** |
| chunk cap | uniformly ≤ 800 tokens (max observed = 800, corpus-wide — confirmed) |

Working figure for the local rig: **`INPUT_BUDGET` ≈ 6–8k tokens** per call
(template + input + output headroom), set per provider in the build config alongside
`llm.py`'s provider selection — a 27B-class model at Q4 on the 3090 is comfortable
there; the budget is config, not architecture.

The uniform 800-token chunk cap makes the whole thing **plannable before generation**:
`build_dossiers.py` computes each text's full DAG — spans, folds, call count —
deterministically from chunk counts, then executes it resumably per node.

**Single-span degenerate case.** 169/211 texts fit one span — but the
degenerate unit is the **work** (§6.1): after V10 grouping, 14 of 52 works are
single-span. Rule: a work whose plan yields exactly one span gets **one
summary staged directly at level 2** (`sum:{work_id}`, `child_chunk_ids` = all
chunks) under the `l1-v1` template's grounding rules; no separate L1 row, no
structure entry beyond the single natural section. The plan step decides this
per work before generation, so call counts and review samples reflect it.

**Span packing (fixes L1).** Spans are built by packing chunks in corpus order:
natural section boundaries first (parsed from `section` per `sections_format`, since
`section_path` is unpopulated — §1.2); a natural section over budget splits into
`{section} (part n)` sub-spans at chunk boundaries; adjacent tiny sections merge up to
budget. Worst case a span is `⌊budget / 800⌋ ≈ 8–10` chunks — every L1 call fits by
construction.

**Folds (fixes L2).** When a text's accepted L1 bodies exceed the budget (Plotinus:
~65 L1s ≈ 13k tokens), they are grouped in reading order into budget-sized batches
and each batch is summarized by `fold-v1` into a **level-0 fold row**
(`child_summary_ids` = the batch). Recursive until one batch remains; L2 then reads
the top folds instead of raw L1s. Depth is logarithmic — even Plotinus needs one fold
layer (~3 folds); nothing in the corpus needs more than two. Folds are scaffolding:
staged only, never promoted, never exported. At promotion, an L2's exported
`child_chunk_ids` is computed **transitively** (union of descendant L1s' chunk ids,
corpus order), preserving the invariant that every exported summary expands to
primary chunks regardless of fold depth.

**`fold-v1`** (input: a reading-order batch of L1/fold bodies):

```
INPUT: consecutive section summaries of {text_label}, in reading order,
covering {span_first} through {span_last}.

Condense into a single {budget}-token summary of this stretch of the text,
in order, preserving proportions across the input summaries.
- Draw only on the input. Name figures as the input names them.

OUTPUT: the summary as plain prose. Nothing else.
```

**Map–reduce (fixes figures/terms).** For texts whose L1 set exceeds budget, D4/D5
run in two passes. *Map*: per-L1 extraction with the `figures-v1`/`terms-v1` frame
scoped to that summary (tiny calls), staged as `field='key_figures'` rows **with
`section_span` set** (the CHECK permits this; span-null vs span-set distinguishes
reduce output from map output). *Reduce*: candidates are merged mechanically —
dedupe by normalized name, rank by (spans-appeared-in, order of first appearance) —
then one final call selects/edits glosses for the top 4–10 from the merged list
(compact input: names + candidate glosses only, always fits), staged as the
whole-text row (`section_span` NULL), which is what promotion reads. The mechanical
rank also answers §1.3.1's coverage concern: a figure central to many spans can't
be lost to one L1's compression.

Call-count reality check: L1 calls and structure entries are **1:1 per span**;
2.56M tokens / ~6k budget bounds packed spans at ~430, and natural-section
granularity on small texts pushes the real number somewhat higher — call it
**~450–600 spans** (× 2 calls each: L1 + structure), ~15 folds, one summary +
D1/D2 per dossier unit (**52 works** — V10 decided, §6.1 and
`work-grouping.md`), and map–reduce passes for the ~12
large texts. An overnight-scale local
batch, re-runnable per stage as templates revise. The exact span count falls out of
the plan step (§ above) before any generation runs — the agent should print the plan
totals per text as its first deliverable.

---

## 2. Export contract — Postgres (`schema/corpus-schema.sql`, v3 → v4)

Appended to the byte-identical schema file **in both repos** (CI hash-compares on push).
`SCHEMA_VERSION = 4` in `scripts/export.py`; `EXPECTED_SCHEMA_VERSION = '4'` in
`guru-web/src/lib/boot.ts:48` — same deploy, per the protocol in the schema header.

```sql
-- v4 (2026-07-xx) Document-knowledge layer: text_dossiers + summary_nodes.
--                 Dossiers are PK-fetched (no embedding); summary_nodes are
--                 retrievable and share the 768-dim space with chunks.
--                 Indexes remain in export.py:emit_indexes per the rule above.

-- ─── text_dossiers ───────────────────────────────────────────────────
-- One precomputed knowledge object per text. Injected into study-mode
-- prompts by PK lookup; never retrieved, so no embedding column.
CREATE TABLE text_dossiers (
    text_id        TEXT PRIMARY KEY REFERENCES texts(id),
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
-- Hierarchical summaries (level 1 = section group, level 2 = whole text).
-- `tradition`/`text_id` are denormalized like chunks so buildScopeFilter()
-- (guru-web src/lib/graph.ts) applies verbatim. child_chunk_ids keeps every
-- summary expandable to primary chunks — the citation contract's escape
-- hatch; for level 2 it is computed transitively through pipeline folds
-- (§1.3.5), which never export. NOT graph nodes: nothing in edges may
-- reference a summary id.
CREATE TABLE summary_nodes (
    id              TEXT PRIMARY KEY,
    text_id         TEXT NOT NULL REFERENCES texts(id),
    tradition       TEXT NOT NULL REFERENCES traditions(id),
    level           SMALLINT NOT NULL CHECK (level IN (1, 2)),
    section_span    TEXT,
    child_chunk_ids TEXT[] NOT NULL,
    body            TEXT NOT NULL,
    token_count     INTEGER NOT NULL,
    embedding       VECTOR(768) NOT NULL
);
```

Notes on shape decisions:

- **Embedding inline** on `summary_nodes` (not a side table) — matching `chunks`, the
  consumer-side convention, rather than the SQLite producer-side convention. The
  producer/consumer shapes already diverge this way for chunks.
- **`child_chunk_ids` is `TEXT[]`, no FK** — Postgres can't FK array elements;
  integrity is the pipeline's job (validated at promotion: every id must exist in
  live chunk nodes).
- **`themes` as JSONB** (not TEXT[]) — keeps it symmetric with the other payload
  fields and uncommitted to array semantics runtime-side.

---

## 3. `export.py` changes

### 3.1 New emitters in `emit_copies()`

Ordered after `texts` (FK) and after `chunks` (logical child integrity). Reads
**live** SQLite tables only — staging never exports.

```python
# text_dossiers — after texts (FK). JSON TEXT columns pass through copy_esc
# unchanged: valid JSON text is valid JSONB input under COPY.
emit_copy_start(f, schema, "text_dossiers",
                ["text_id", "summary", "context", "structure", "key_figures",
                 "key_terms", "themes", "reading_notes", "manifest_notes", "generated_by"])
for r in load_text_dossiers(conn):
    f.write(
        f"{copy_esc(r['text_id'])}\t{copy_esc(r['summary'])}\t{copy_esc(r['context'])}\t"
        f"{copy_esc(r['structure_json'])}\t{copy_esc(r['key_figures_json'])}\t"
        f"{copy_esc(r['key_terms_json'])}\t{copy_esc(r['themes_json'])}\t"
        f"{copy_esc(r['reading_notes'])}\t{copy_esc(r['manifest_notes'])}\t"
        f"{copy_esc(r['generated_by'])}\n"
    )
emit_copy_end(f)

# summary_nodes — after chunks. child_chunk_ids needs the COPY array form
# ({"a","b"}), i.e. the copy_esc_array() the chunks emitter's section_path
# comment already calls for — this lands it, unblocking section_path too.
emit_copy_start(f, schema, "summary_nodes",
                ["id", "text_id", "tradition", "level", "section_span",
                 "child_chunk_ids", "body", "token_count", "embedding"])
for r in load_summary_nodes(conn):        # joins summary_embeddings
    vector = vec_to_pg(r["vector"], EMBEDDING_DIM)   # same 768-dim guard as chunks
    f.write(
        f"{copy_esc(r['id'])}\t{copy_esc(r['text_id'])}\t{copy_esc(r['tradition'])}\t"
        f"{r['level']}\t{copy_esc(r['section_span'])}\t"
        f"{copy_esc_array(json.loads(r['child_chunk_ids']))}\t"
        f"{copy_esc(r['body'])}\t{r['token_count']}\t{vector}\n"
    )
emit_copy_end(f)
```

### 3.2 `emit_indexes()` additions (post-bulk-load, per the schema-header rule)

```python
f.write(f"CREATE INDEX summary_nodes_embedding_hnsw ON {schema}.summary_nodes "
        f"USING hnsw (embedding vector_cosine_ops);\n")
f.write(f"CREATE INDEX summary_nodes_text_id ON {schema}.summary_nodes (text_id);\n")
```

### 3.3 Validation + metadata

- The inline validation block gains: emitted `text_dossiers` rows == SQLite live
  rows and every `text_id` exists in `texts`; every `summary_nodes.child_chunk_ids`
  element resolves against emitted chunk ids; every text with a dossier has exactly
  one level-2 summary node. **Coverage policy: dossiers are optional per text** —
  the export reports coverage (n texts with dossiers / total texts) but does not
  fail on gaps; the runtime must
  treat a missing dossier as "study mode without the dossier block", not an error.
- `corpus_metadata` gains key `dossier_model`. It remains the **last** statement
  emitted, so a mid-load failure still leaves the app refusing to serve.

---

## 4. Push to prod — sequence

The existing machinery already handles this end-to-end; v4 rides it unchanged.

```
[local rig]
 1. sqlite3 data/guru.db < scripts/migrations/v3_007_document_knowledge.sql
 2. python scripts/build_dossiers.py          # per-field staged rows (DAG order §1.3.1),
                                              #   resumable, local 3090
 3. python scripts/review_dossiers.py         # rubric sample-review loop (§1.3.4):
    (iterate 2↔3 until rubric passes)         #   template revisions → regenerate → bulk-accept
 3b. python scripts/promote_dossiers.py       # assemble accepted fields → live tables;
                                              #   derive themes from concept tags
 4. python scripts/export.py                  # SCHEMA_VERSION=4 → export/guru-corpus.sql.gz
                                              #   emits into corpus_new, indexes last,
                                              #   corpus_metadata last, atomic swap to corpus

[guru-web repo]
 5. Same commit/deploy: schema/corpus-schema.sql (v4 appended — CI hash check passes
    only if both repos updated), boot.ts EXPECTED_SCHEMA_VERSION = '4',
    migrations/*.sql for app-side tables (sessions.mode etc. — separate concern,
    IF NOT EXISTS, runs via the normal migrate path)

[hetzner]
 6. Load dump:   gunzip -c guru-corpus.sql.gz | psql $DATABASE_URL
    — builds corpus_new fully (COPYs → indexes → metadata), then swaps.
    The OLD app build (expects '3') keeps serving right up to the swap.
 7. Deploy new app build (deploy/ scripts / systemd restart).
    boot.ts reads corpus.corpus_metadata.schema_version → '4' → serves.
```

Failure containment, all pre-existing properties:

- Dump load fails mid-way → `corpus_new` is discarded at next load, `corpus` (v3)
  untouched, old build serves on.
- Swap lands before the app deploy → old build's boot check fails loudly
  (`Corpus schema version mismatch: expected 3, got 4`, boot.ts:118-121) on restart —
  so the operational rule is **swap and app restart in the same deploy step**, which
  is what the deploy script already does. Window of exposure ≈ the systemd restart.
- New build up, old corpus still loaded → same mismatch refusal, inverted. Either
  ordering error fails closed, never wrong-schema-serving.

---

## 5. What runtime reads (for orientation, not in scope here)

⚠ **Hard dependency, not an aside: study mode does not exist.** guru-web's
`src/` today has no `study` or `compare` mode anywhere — no `sessions.mode`
column, no `study_scope`, no mode switch in the prompt or retriever paths
(the only "mode" is `scopeMode: 'all'|'whitelist'|'blacklist'` scope
filtering). Everything in this table, and the premise that dossiers are
injected and summaries retrieved *in study mode*, presumes a mode system that
is entirely greenfield guru-web work with its own spec. The v4 corpus tables
can ship ahead of it (nothing reads them until then), but sign-off on this doc
is not sign-off on a consumer.

| Access | Query shape | Mode |
|---|---|---|
| Dossier injection | `SELECT … FROM text_dossiers WHERE text_id = $1` (PK) | study |
| Summary retrieval | `chunks` vector leg `UNION ALL` `summary_nodes` under `buildScopeFilter` | study only |
| Compare mode | untouched — no summary table in any leg; tuned config stays as swept | compare |

⚠ **Column-shape caveat for the UNION**: `RetrievedChunk` (and `formatChunk`) expect
`text_name`, `translator`, `section` — columns `summary_nodes` deliberately lacks.
The runtime UNION leg must `JOIN texts` for `label` → `text_name` and NULL-fill
`translator`, with `section := COALESCE(section_span, '(whole text)')` —
`RetrievedChunk.section` is a non-nullable `string` (types.ts:11) and level-2
rows have NULL `section_span`, so a bare passthrough breaks the type contract.
This is guru-web work, noted here so the schema isn't "fixed" by denormalizing
summary rows into fake chunks — the missing columns are the point.

---

## 6. Pre-signoff verification checklist (needs the real corpus / local DB)

Items the agent must verify locally **before** implementation, in dependency order.
Each is cheap; several will change the span plan or a template.
**Status legend:** ✅ verified/decided 2026-07-04 against `data/guru.db` +
chunk TOMLs; ⬜ still open. V3 and V10 are decided (works layer — §6.1,
`work-grouping.md`); remaining open: V7 (rig-bound) and the V8 regex
hardening + per-domain sample.

**V1 — Section-string audit (blocks span packing).** ✅ **Run; mostly good, one
trap.** `sections_format` is populated for 211/211 texts (11 formats, zero NULL).
Section strings are overwhelmingly rich and parseable (4,155 printable like
`Rune Ia` / `Chapter VI, Section 1b`; only 21 bare `1a`-style values, confined
to `enuma-elish` and `book-of-concealed-mystery`). The trap: **`sections_format`
does not describe what the strings contain** — Enuma Elish declares
`sections_format="tablet"` but its sections run `1a`…`1l` with no tablet
structure recoverable at all. The planner must trust the parsed strings, never
the declared format; the two bare-format texts fall back to budget-packing with
synthetic `(part n)` spans. The per-text grouping strategy table (output of the
plan step) still needs to be checked into `docs/` before the first campaign.

**V2 — Chunk-order guarantee (blocks everything).** ✅ **Confirmed.** Kalevala
runs `Rune Ia` → `Rune Lk` monotonically across all 275 chunks; Enuma Elish
`1a`→`1l` across 001–012. `chunks/NNN.toml` numbering is reading order;
`child_chunk_ids` order can be trusted corpus-wide.

**V3 — `-index` aggregates decision (blocks the plan for the top texts).**
✅ **DECIDED 2026-07-04: keep whole.** (Scope had already shrunk: Zhuangzi was
rescoped to the Inner Chapters in 12bd639 — 42k, no longer a collection problem;
Plotinus is 373.6k/752 chunks post-79e876b.) `plotinus-select-works-index` and
`egyptian-book-of-the-dead-index` each stay one text = one singleton work with
one dossier; folds absorb the size and `structure_json` provides per-treatise
navigation. Splitting would ripple through 4,176 chunk ids, 35k edges, and all
accepted tags for a benefit the dossier already delivers. Rationale + revisit
condition in `docs/summary/work-grouping.md`.

**V4 — `manifest_notes` coverage (shapes context-v1).** ✅ **Resolved: coverage
is total.** All 399/399 `[[source]]` entries in `sources/manifest.toml` carry
non-empty `notes`. `context-v1`'s grounding assumption holds corpus-wide; no
backfill needed. (Note 399 sources vs 211 ingested text dirs — the corpus is
still growing; batch sizing is a moving target and the resumable-per-text
design is what absorbs that.)

**V5 — EXPRESSES orientation + tag coverage (blocks themes derivation).**
✅ **Orientation confirmed; coverage floor is a real decision.** All 35,265
live EXPRESSES edges run source=chunk → target=concept, zero exceptions.
Tiers present: `verified` 24,180, `proposed` 11,085, `inferred` **0** — the
weighting must tolerate missing tiers. Per-text coverage: median 15 edges,
but 79/211 texts have <10, 56 have <5, and 4 have zero (three
`agrippa-natural-magic-ch-*` shards + `zoroastrianism.bundahishn`). Thin
`themes_json` affects over a third of texts as sharded — but V10's work
grouping pools member tags, collapsing the tail to 3 works (`bundahishn` 0,
`gathas-introduction` 2, `kojiki-beginning-heaven-earth` 5). **Floor decided:**
works with <5 accepted tags export `themes = []`.

**V6 — id formats (blocks the summary_id scheme).** ✅ **Confirmed.** All 4,176
chunk ids are uniformly `{tradition}.{text}.{NNN}`; Postgres `texts.id` is the
middle component (`export.py:322` — e.g. `enuma-elish`), and there are no
text-slug collisions across traditions. `sum:{text_id}[:{span_slug}]` is safe
as designed; still need the slug rule for `(part n)` spans.

**V7 — INPUT_BUDGET empirical check (tunes §1.3.5).** ⬜ **Open — needs the rig.**
On the 3090 with the chosen generation model: confirm comfortable context at 6–8k
with headroom (KV cache, quality at depth), and note that `chunk.token_count` was
computed by the *pipeline's* tokenizer — apply a ~15% slack factor against the
generation model's tokenizer rather than assuming counts transfer.

**V8 — Boilerplate audit beyond sacred-texts (feeds the LEAK rubric).**
⬜ **Open, and upgraded from "audit" to "known gap":** the ported regexes
already fail on sacred-texts itself — Enuma Elish chunk 001's header
(`"Sacred-Texts Ancient Near East …"`, hyphenated, no `Previous Next` marker)
survives all three patterns untouched (§1.2). Harden the sacred-texts patterns
*and* sample chunks from every other source domain in the manifest before L1
generation — un-stripped apparatus is the likeliest source of `LEAK`/`GROUND`
failures.

**V9 — Span-plan stability rule (process, not code).** Span identity is the string
join key between `staged_summaries` and `staged_dossier_fields.structure_entry`,
and changes whenever the budget or grouping strategy changes. Rule for the agent:
the span plan is **frozen per template-generation campaign** — a budget/strategy
change is treated like an `l1` template bump (full regenerate), never a partial one.

**V10 — Shard-grouping decision (blocks the dossier unit; NEW, from the corpus
audit).** ✅ **DECIDED 2026-07-04: option (a), the works layer.** The draft
assumed text dir ≈ work (120 texts, median ~4.4k tokens). Reality: **211 text
dirs, and 168 of them are serialization shards of just 9 works** (the full
audit found more families than the first estimate: `dhammapada-chapter-*` ×26,
`agrippa-natural-magic-ch-*` ×74, `corpus-hermeticum-*` ×17, `yasna-*` ×17,
`dionysius-divine-names-*` ×13, `gilgamesh-tablet-*` ×12, `plato-republic-*`
×4, `gnostic-john-baptizer-*` ×3, `heroic-enthusiasts-pt*` ×2). One dossier
per text_id would have meant one dossier per chapter, with each L2
summarizing a ~1–2k-token sliver (110 texts have ≤2 chunks).

Resolution: shards group into works via a pure mapping layer
(`sources/works.toml`), no re-manifest, no id churn — **52 works total** (9
grouped + 43 singleton). The dossier unit and L2 unit become the work; shard
members become natural sections. Rejected: (b) re-manifest (same blast radius
V3 rejects), (c) per-shard dossiers (wrong reader-facing unit). Side effect:
per-work tag pooling collapses V5's thin-tags tail from 79 texts to 3 works.
Full table, judgment calls (Corpus Hermeticum grouped; Poetic Edda poems,
Paracelsus treatises, Zoharic texts NOT grouped; translator intros standalone
+ dossier-optional): `docs/summary/work-grouping.md`. Schema consequences:
§6.1 below.

### 6.1 Works-layer amendments (V3+V10 resolution — deltas to §1 and §2)

The SQL in §1/§2 predates this decision; apply these deltas when writing
`v3_007` and the v4 schema append. The **work** is the dossier + L2 unit;
text_ids, chunk ids, tags, and edges are untouched.

- **`sources/works.toml`** (new, pipeline input): `[[work]]` with `id`,
  `label`, `members` (text_ids in reading order). Any text not listed is
  implicitly a singleton work with `work_id = text_id`. `build_dossiers.py`
  materializes the full 52-work map at plan time.
- **§1 staging/live (SQLite):** `staged_dossier_fields.text_id` →
  `work_id`; `text_dossiers` → **`work_dossiers`** keyed on `work_id`
  (`manifest_notes` for a grouped work = concatenated member notes, labeled).
  `staged_summaries` / `summary_nodes` gain `work_id TEXT NOT NULL`;
  `text_id` stays for L1 rows (the span lives in one shard text) and is
  **NULL on level-2 rows of multi-member works** — an L2 spans texts.
  Summary id scheme: L2 = `sum:{work_id}`, L1 = `sum:{text_id}:{span_slug}`
  as before.
- **§2 export (Postgres v4):** new `works(id PK, tradition FK, label,
  member_text_ids TEXT[])`; `texts` gains `work_id TEXT NOT NULL` (v4 is a
  fresh schema — no migration concern); `text_dossiers` becomes
  `work_dossiers(work_id PK REFERENCES works)`; `summary_nodes` gains
  `work_id NOT NULL REFERENCES works` and `text_id` becomes nullable.
  `tradition` denormalization is unchanged (every work is single-tradition —
  holds for all 52), so `buildScopeFilter` still applies verbatim.
- **§1.3 DAG:** unchanged in shape; "text" reads as "work" for L2/D1–D6.
  Each grouped-work member is a natural section (structure entry + L1
  span(s), tiny members merge per span packing). Single-span *works* take the
  degenerate rule (one summary staged at level 2 directly): 14 of 52.
- **§5 runtime:** study scope still pins a `text_id`; the dossier fetch
  becomes `SELECT … FROM work_dossiers WHERE work_id = (SELECT work_id FROM
  texts WHERE id = $1)` — still a PK-shaped lookup.
- **Call-count effect:** L2/D1/D2/notes and figures/terms reduce runs are
  per-work (~52 each, not ~211); L1 + structure stay per-span (~450–600).
