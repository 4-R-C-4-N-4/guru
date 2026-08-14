# Derived-parallels cutover — ratification evidence, 2026-08-14

Ratification record for `todo:9097deed`, the owner gate on the Pass C
retirement (`todo:c3f479ff`, shipped in PR #64). Everything below was measured
against corpus **v54**, exported from merged `main` and loaded into guru-web's
local docker postgres.

**Summary: the golden gates are not the problem. Two reader-facing surfaces
are.** One of them is a one-line fix; the other needs the generator re-run.

---

## 1. Golden gates: 271 / 272

| gate | result | note |
|---|---|---|
| legacy (`golden-retrieval.json`) | **14 / 14 pass** | better than the recorded 13/14 — the known v50 drift on "gnosis and the demiurge and the archons" (guru-web `e7b40dd5`) now passes |
| per-work (`golden-queries`) | **257 / 258 pass** | one failure, `enoch-charles-1917` |

### Running them correctly

Both suites are `describe.skipIf(!INTEGRATION_TEST)` **and** vitest does not
load `.env`. Getting this wrong produces two different false readings, both of
which I hit before getting a real number: a plain `npm test` run reports the
per-work gate as "258 skipped" and looks green, while `INTEGRATION_TEST=1`
without the env fails all 14 legacy tests with a SASL password error that reads
like catastrophic corpus drift.

```bash
set -a; . ./.env; set +a
INTEGRATION_TEST=1 npx vitest run \
  src/__tests__/golden-queries.test.ts src/__tests__/golden-retrieval.test.ts
```

Runtime is ~8 minutes; every query embeds through host Ollama.

---

## 2. The one failure is not ours

`enoch-charles-1917`'s recall probe no longer returns `jewish_mysticism` at
all. It is tempting to blame the cutover. That is wrong: **the edge rework
cannot affect retrieval**, proven three independent ways.

1. **PARALLELS can never enter the retrieval path.** guru-web's `walkGraph`
   expands concepts using `CONCEPT_EDGE_TYPES = ['PARALLELS','DERIVES_FROM']`
   via `WHERE source = ANY($concept_ids) OR target = ANY($concept_ids)`, then
   surfaces chunks through `EXPRESSES` only. PARALLELS endpoints are chunk ids
   and cannot match a concept id. Measured on v54: of 17,244 PARALLELS rows,
   **0 touch a concept node** (all 38,457 EXPRESSES rows do), and
   `DERIVES_FROM` does not exist in the corpus. The hop is a no-op, before and
   after the cutover.
2. **The failing query's own trace shows the graph leg contributing nothing.**
   Under `RETRIEVAL_TRACE=1`, all 201 candidates score `graphS=0.00`; every hit
   is sourced `vector` or `lexical`.
3. **The retrieval code is unchanged since the goldens passed.**
   `git log a8fdd36..HEAD -- src/lib/retriever.ts src/lib/matcher.ts` is empty,
   and `LEXICAL_WEIGHT = 1.0` is the committed tuned default (`todo:3fc23534`),
   not an environment override — so the gate run is comparable to the reference
   run.

**What it actually is:** a real v50 → v54 regression on the vector/lexical
side, unrelated to this project. `todo:a3bb24b5` records 258/258 passing on v50
and the fixture is pinned `corpus_version: 50`. Across that window the corpus
gained 227 chunks (5,340 → 5,567) and lost 1,256 EXPRESSES (39,713 → 38,457);
the EXPRESSES delta is irrelevant here because the graph leg contributes zero.
Enoch itself was not re-chunked — all 111 of its v50-era chunk ids survive, as
do all 3,525 v50 ids referenced by the preserved Pass C backup.

The probe loses to `western_esoteric.secret-teachings-of-all-ages`, an
encyclopedic work that covers Enoch's own material, on lexical score (up to
0.949). That is the failure mode already filed as guru-web `todo:31a7fe76`
(small/commentary-heavy works miss top-15) and `todo:418a98c9` (recall gaps
from the backfill). Pinning it to an exact commit needs the v50 corpus, which
the load overwrote locally.

---

## 3. What the cutover did change: two reader surfaces

PARALLELS have exactly two consumers — the `/read` "Related passages" strip and
the `/atlas` route. Both are affected, for **different and independent
reasons**.

### 3a. The Atlas renders nothing (cause: tier filter)

`src/lib/atlas.ts` filters `edge_type='PARALLELS' AND tier='verified'` in four
places. Every derived row is `tier='inferred'`:

```
atlas_sees_verified | actually_present | tiers
                  0 |           17,244 | inferred
```

So the Atlas shows **zero** cross-tradition parallels corpus-wide — not
degraded, empty. This hits all 17,244 rows including the good ones, and is
independent of the coverage loss described below. It is the guru `todo:dd034dc4` tier
question (is `tier` confidence or provenance?) arriving in production.

**Fix:** one predicate. Either stop filtering on tier in `atlas.ts`, or settle
`dd034dc4` and re-tier. No regeneration required.

### 3b. Panel coverage concentrates (cause: `min_grade` floor)

| | Pass C | derived |
|---|---|---|
| chunks with a panel | 3,525 | 2,427 |
| texts with any panel | 201 / 241 | 169 / 241 |
| total PARALLELS rows | 11,412 | 17,244 |

More edges over fewer chunks: 1,560 chunks lose their panel, 462 gain one, and
**52 texts go completely dark**. The reader page renders the section as
`{related.length > 0 && …}`, so a dark text shows no strip and no empty state —
indistinguishable from a broken feature.

Worst-hit works with ≥100 Pass C edges:

| work | Pass C | derived | kept |
|---|---|---|---|
| enuma-elish | 249 | **0** | 0% |
| diamond-sutra | 134 | 2 | 1% |
| enoch-charles-1917 | 737 | 68 | 9% |
| tao-te-ching-legge | 201 | 46 | 23% |
| dionysius-divine-names-7 | 249 | 81 | 33% |
| pistis-sophia | 571 | 247 | 43% |

**Mechanism**, confirmed against `data/derived_parallels_score_cache.json`
against the `config[scoring].min_grade` floor of −4.415:

| work | pairs | best | median | above floor |
|---|---|---|---|---|
| enuma-elish | 76 | −4.84 | −6.29 | **0 (0%)** |
| diamond-sutra | 143 | −3.88 | −6.62 | 1 (0%) |
| enoch-charles-1917 | 757 | −1.01 | −6.94 | 29 (3%) |
| dionysius-divine-names-5 | 130 | +1.97 | −4.11 | 76 (58%) |

enuma-elish's *best* pair scores −4.84: the entire work sits under the floor
and cannot emit a single edge regardless of how its chunks rank against each
other.

**Why this is a threshold artifact, not a corpus verdict.** −4.415 is
scorer-v1's calibration from the rellm thin-scorer work, fitted on the
**(query, chunk)** relevance frame — the kappa +0.827 ship gate. Here it gates
**(concept-definition, chunk)** grading, a different input distribution, with no
reason the calibrated point transfers. The per-work spread is what a
non-transferring threshold looks like: not that a Babylonian creation epic
expresses no concepts, but that its register scores lower against
concept-definition prose than Christian mystical and Neoplatonic text does, and
one global floor turns that gradient into a cliff.

**Fix:** make selection rank-based rather than absolute. The generator already
ranks candidates per chunk, so taking each chunk's top-k regardless of an
absolute floor (optionally with a much lower sanity floor) restores whole-work
coverage without disturbing the ranking that the 21/24 partner-recovery
evidence rests on. Alternatives: recalibrate `min_grade` on the
concept-definition frame, or per-work floors. Cost is ~10 CPU-minutes to
re-derive plus a re-export.

---

## 4. What is unaffected

Retrieval, chat grounding, `/read/search`, and both golden gates. Proven in §2:
PARALLELS never touch a concept node and the graph leg scores zero on them.

---

## 5. Recommendation

Neither issue blocks merging code, and neither requires re-doing anything else
from PR #64. Before a corpus push I would want:

1. **3a settled** — a one-line predicate change; without it the Atlas ships blank.
2. **3b decided** — a product call on whether 52 dark texts (including Enuma
   Elish, the Diamond Sutra and Enoch) are acceptable for this release, and if
   not, a re-derive with rank-based selection.

The single golden failure (§2) is pre-existing, unrelated, and should be
tracked on its own against guru-web `31a7fe76` / `418a98c9` rather than held
against this cutover.
