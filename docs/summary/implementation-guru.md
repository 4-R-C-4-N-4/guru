# Implementation Plan — Document-Knowledge Layer, guru repo

Scope: everything the guru repo needs to take the design
(`document-knowledge-data-structures.md`, as amended by §6.1 works layer and
§1.3.6 configurable backend) from spec to a loaded v4 export artifact.
**guru-web work is explicitly out of scope** — it gets its own document after
this one is vetted. Runtime consumption (study mode) is greenfield guru-web
work and nothing here depends on it.

Status of inputs: checklist V1–V10 all resolved/decided; corpus cleaned and
re-embedded (todo:fccaf47d). One external gate: **G0 below (c59758f3) must
land before the corpus-hermeticum work's span plan freezes** — it does not
block any other step.

Conventions used throughout: "work" per `work-grouping.md` (52 works);
campaign config per §1.3.6; span identity frozen per campaign (V9).

---

## G0 — Corpus gate: resolve c59758f3 (CH-15/16 duplicate)

*Blocks: G4 span freeze for `corpus-hermeticum` only. Parallelizable with G1–G3.*

- Resolve the duplicate libellus XVI acquisition (manifest labels vs
  chunking-config labels disagree). Whatever the fix (drop one member,
  re-acquire, relabel), it is id-changing for that text's chunks → follow the
  remap precedent (tags/edges/embeddings updated in the same change).
- Update `work-grouping.md`'s `corpus-hermeticum` row (member list, counts).
- Done when: `todo close c59758f3`, work-grouping row corrected, and
  `python3 -c "import ..."` bijection check (chunk ids ↔ TOMLs) passes.

## G1 — Works layer: `sources/works.toml` + loader

*Depends on: nothing. Files: `sources/works.toml`, `scripts/works.py` (new).*

- `works.toml`: `[[work]]` blocks for exactly the **9 grouped works** in
  `work-grouping.md` — `id`, `label`, `tradition`, `members` (text_ids in
  reading order). Singleton works are implicit (`work_id = text_id`).
- `scripts/works.py`: `load_works() -> dict[work_id, Work]` materializing all
  52; validates every member text exists in the corpus, every text belongs to
  exactly one work, all members share one tradition. Used by build, promote,
  and export.
- Test: `tests/test_works.py` — 52 works, 211 texts covered exactly once,
  single-tradition invariant, member reading order matches corpus order.

## G2 — Migration `scripts/migrations/v3_007_document_knowledge.sql`

*Depends on: nothing. Apply order after v3_006.*

Design §1 SQL with the §6.1 deltas applied:

- `staged_dossier_fields` — as specced, with **`work_id`** (not text_id);
  `field` CHECK unchanged; partial-unique on
  `(work_id, field, COALESCE(section_span,''), model, prompt_version) WHERE status='pending'`.
- `staged_summaries` — as specced **plus `work_id TEXT NOT NULL`**; `text_id`
  stays (NULL only on level-2 rows of multi-member works); level CHECK (0,1,2)
  retained (level 0 = folds, `local` campaigns only).
- `work_dossiers` (renamed from text_dossiers) — `work_id TEXT PRIMARY KEY`,
  other columns as specced; `manifest_notes` = concatenated member notes,
  labeled, for grouped works.
- `summary_nodes` — as specced plus `work_id TEXT NOT NULL`; `text_id`
  nullable; `children_hash` per G6 rule below.
- `summary_embeddings` — as specced.
- Idempotent (IF NOT EXISTS), matching schema.sql conventions.
- Done when: applies cleanly to a copy of `data/guru.db`, then to the real DB;
  re-applying is a no-op.

## G3 — Campaign config + claude-code provider

*Depends on: nothing. Files: `config/dossiers.toml`, `scripts/llm.py` (extend).*

- `config/dossiers.toml` exactly per §1.3.6 (`provider`, `model`,
  `span_target=6000`, `input_budget=0`, `review_k=15`), plus
  `campaign_id = "c1"` (namespaces the span-plan freeze artifact).
- `llm.py`: add `claude_code_complete(prompt, model, timeout) -> str` —
  subprocess `claude -p --model {model} --output-format json`, prompt on
  stdin, parse the JSON envelope's result text. Errors: nonzero exit or
  usage-limit message → raise `ProviderBusy` with retry-after; caller sleeps
  and resumes (staging rows make every node idempotent). Never fall back to a
  different model silently — the configured model string is provenance.
- Smoke test (manual, cheap): one call, assert non-empty text and that the
  configured model served it.

## G4 — Plan step: span packing + freeze artifact

*Depends on: G1, G3 (span_target), G0 for CH only.
Files: `scripts/build_dossiers.py` (plan mode).*

- `build_dossiers.py --plan`: for every work, compute spans — natural
  sections first (parse `section` per `sections_format`; **trust parsed
  strings, never the declared format** — V1), merge adjacent tiny sections up
  to `span_target`, split oversized at chunk boundaries into `(part n)`;
  budget-pack fallback for the two bare-format texts. Single-span works get
  the degenerate flag (one summary staged at level 2, no L1/structure).
  Fold/map-reduce nodes are emitted **only** when `input_budget > 0` and
  ΣL1-estimate exceeds it (zero under claude-code).
- Span/summary ids: L2 `sum:{work_id}`; L1 `sum:{text_id}:{span_slug}`;
  `span_slug` = section string lowercased, non-alphanumerics → `-`, collapsed;
  `(part n)` → `-part-n`. Slugs must be unique per text (assert).
- Output (the **freeze artifact**, committed): `docs/summary/span-plan-c1.json` (machine) + `docs/summary/span-plan-c1.md` (human: per-work spans, call
  counts, degenerate/fold flags, totals). V9: regenerating this file with
  different totals after generation has begun = new campaign, full stop.
- Test: `tests/test_span_plan.py` — every chunk in exactly one span; span
  order = corpus order; known cases (dhammapada merges to <span_target
  spans; enuma-elish falls back to `(part n)`; 14 degenerate works).

## G5 — Templates + generation loop

*Depends on: G2, G3, G4. Files: `prompts/dossier/*.md`,
`scripts/build_dossiers.py` (generate mode).*

- `prompts/dossier/`: `preamble.md`, `l1-v1.md`, `l2-v1.md`, `fold-v1.md`,
  `summary-v1.md`, `context-v1.md`, `structure-v1.md`, `figures-v1.md`,
  `terms-v1.md`, `notes-v1.md` — verbatim from design §1.3.2–§1.3.3, with
  work-level wording ("text" → "work" for L2/D1–D6). Filename =
  `prompt_version` value.
- `build_dossiers.py --generate [--stage l1|l2|structure|...] [--work id]`:
  walks the frozen plan in DAG order; for each node, skip if a pending or
  accepted row exists for (work, field/summary, span, model, prompt_version);
  render template; call provider; validate against the field contract (§1.1 —
  JSON shapes; L1/L2/fold are plain prose with token-band check ±20%);
  reject-and-retry up to 3 (the `parse_tags` pattern); insert staged row with
  model + prompt_version.
- Inputs per stage come from **accepted** upstream rows only (L2 reads
  accepted L1s, etc.), except campaign bootstrap where `--stage l1` runs
  against chunks directly.
- Nav-clean residual layer (§1.2): apply the P1–P6 pattern set from
  `clean_bodies.py` to bodies at read time (import, don't duplicate) — cheap
  insurance, bodies are already clean at source.
- Done when: a full `--generate` run over 2–3 pilot works (one degenerate,
  one grouped, one large) produces contract-valid staged rows, resumably.

## G6 — Review loop + promotion

*Depends on: G5. Files: `scripts/review_dossiers.py`,
`scripts/promote_dossiers.py` (new, in the mold of review_tags/auto_promote).*

- `review_dossiers.py`: stratified sample (review_k works by tradition ×
  size; structure entries sampled per-span); presents row + its stage INPUT
  (so GROUND/LEAK are checkable — the frontier-model caveat in §1.3.4 means
  the reviewer must see what the model was allowed to know); records
  accept/reject with rubric code in `reviewed_by`/notes; `--bulk-accept
  --field X --prompt-version Y` after a passing sample.
- `promote_dossiers.py`: per work — require accepted `summary`, `context`,
  and all structure spans (unless degenerate); compose `work_dossiers` row
  (structure_json in span order with chunk_ids attached from the plan;
  manual rows preferred over any template version); derive `themes_json`
  from live EXPRESSES tags (tier-weighted; **works with <5 accepted tags →
  `[]`** — V5 floor); insert `summary_nodes` (L1s + L2; never level 0) with
  `children_hash`.
- **children_hash rule (normative):** `sha256("\n".join(sha256(body) for
  chunk in transitive child chunks, sorted by chunk id))`, bodies as stored
  post-clean. Recompute-and-compare is the rebuild detector.
- Summary embeddings: `scripts/embed_summaries.py` (or `embed_corpus.py
  --summaries`) — same provider/config/writer pattern, target
  `summary_embeddings`, 768-dim guard.
- Tests: `tests/test_promote.py` — assembly ordering, manual-row preference,
  themes floor, children_hash stability + flip-on-body-change.

## G7 — Export v4

*Depends on: G6 (needs live rows to validate against; code can start earlier).
Files: `scripts/export.py`, `schema/corpus-schema.sql` (guru side).*

- `schema/corpus-schema.sql`: append v4 block per design §2 **with §6.1
  deltas**: `works(id PK, tradition FK, label, member_text_ids TEXT[])`;
  `texts.work_id TEXT NOT NULL`; `work_dossiers(work_id PK REFERENCES
  works)`; `summary_nodes` with `work_id NOT NULL REFERENCES works`,
  `text_id` nullable, inline `VECTOR(768)`. (The byte-identical guru-web copy
  is Phase W — do not push the guru side until the paired guru-web change is
  ready, or CI hash-compare fails.)
- `export.py`: `SCHEMA_VERSION = 4`; `copy_esc_array()` (unblocks
  section_path later, per the emitter comment); emitters after texts/chunks:
  `works`, `work_dossiers`, `summary_nodes` (join summary_embeddings,
  `vec_to_pg` 768 guard); `emit_indexes()` adds summary hnsw + text_id
  index; validation block per §3.3 (row counts, child_chunk_ids resolve,
  exactly one L2 per dossiered work, **coverage reported not enforced**);
  `corpus_metadata` gains `dossier_model`, stays last.
- Test: full export against the local DB; load the dump into a scratch
  Postgres (or at minimum assert the SQL orders: COPYs → indexes → metadata →
  swap) and run the emitted validation.

## G8 — Campaign 1 runbook (execution, not code)

Sequenced order once G0–G7 are merged:

```
1. todo work c59758f3 → resolve → CH member list final          (G0)
2. python3 scripts/build_dossiers.py --plan                     → commit freeze artifact
3. python3 scripts/build_dossiers.py --generate --stage l1      (overnight ok; resumable)
4. review loop: review_dossiers.py sample → template vN bumps → regenerate → bulk-accept
5. --generate remaining stages in DAG order; review each
6. promote_dossiers.py; embed_summaries.py
7. export.py dry-run → inspect validation output → guru-corpus.sql.gz
8. STOP — deploy rides the paired guru-web change (Phase W doc)
```

Estimated volume (from the plan step, to be confirmed by G4's printed
totals): ~450–600 L1+structure span pairs, 52 × (L2 + D1 + D2 + D4 + D5 +
D6), ~3M input / ~300k output tokens on the subscription.

---

## Suggested ticket structure

One parent per phase G1–G7 is overkill; suggested: parent
"implement document-knowledge layer (guru)" with children ≈ G1, G2, G3,
G4, G5, G6, G7 (G0 is the existing c59758f3; G8 is ops, tracked in the
runbook). Each child's done contract is the "Done when"/test line of its
section.

## Explicitly deferred to the guru-web document (Phase W)

- Byte-identical `schema/corpus-schema.sql` v4 append + CI hash check
- `boot.ts` `EXPECTED_SCHEMA_VERSION = '4'`
- Study-mode spec (greenfield: sessions.mode, study_scope, dossier
  injection, summary UNION leg with `COALESCE(section_span, ...)` and
  `JOIN texts` for text_name)
- Deploy sequencing (§4 steps 5–7)
