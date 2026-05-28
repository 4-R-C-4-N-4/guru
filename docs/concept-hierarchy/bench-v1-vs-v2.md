# Tagger prompt bench — v1 vs v2 (concept-hierarchy)

_Generated 2026-05-27 · todo:25f4b30b · design.md §13 step 5_

## Setup

- **Model (held fixed):** `Qwen3.5-27B-UD-Q4_K_XL.gguf` — isolates the *prompt* change (v1 flat JSON array → v2 domain→family grouped outline). Same model produced the v1 tags being compared against, so this is not a model swap.
- **Sample:** 90 held-out chunks with human-reviewed v1 tags, stratified across traditions (≤6/tradition, seed=42).
- **Ground truth:** 857 reviewed (chunk, concept) verdicts (565 accepted, 292 rejected).
- **Metric:** agreement-with-review at **score ≥ 2**. A prompt "predicts present" when it scores a (chunk, concept) ≥ 2; compared against the human accept(=present)/reject(=absent) verdict on the same pair. v2 tags absent for a reviewed pair count as score 0.
- **v2 coverage:** tagged 89/90 sampled chunks; 1114 v2 (chunk,concept) tags; 432 v2 score≥2 tags fell on pairs with no prior human verdict (not scorable here — candidate new signal).

## Results (on the 857 reviewed pairs)

| prompt | precision@≥2 | recall@≥2 | agreement@≥2 |
|--------|-------------|-----------|--------------|
| v1 (old, flat)     | 95.1% | 71.7% | 78.9% |
| v2 (new, grouped)  | 85.1% | 50.4% | 61.5% |
| **Δ (v2 − v1)**    | -10.0 pp | -21.2 pp | -17.4 pp |

- v1: precision 95.1%  recall 71.7%  agreement 78.9%  (TP=405 FP=21 TN=271 FN=160)
- v2: precision 85.1%  recall 50.4%  agreement 61.5%  (TP=285 FP=50 TN=242 FN=280)

## Decision gate (threshold: a drop > 5 pp on any axis = material)

**⚠ MATERIALLY WORSE — investigate before clustering**

## Diff detail (reviewed set)

- **Regressions** — human-accepted concepts v1 caught (≥2) but v2 missed (<2): 159
- **Improvements** — human-accepted concepts v2 caught that v1 missed: 39
- **New false positives** — human-rejected concepts v2 now flags ≥2 (v1 did not): 41

### Sample regressions (up to 15)
- infinite_cosmos  ·  ('buddhism.diamond-sutra.009', 'infinite_cosmos')
- love_of_neighbour  ·  ('buddhism.diamond-sutra.010', 'love_of_neighbour')
- active_contemplation  ·  ('buddhism.diamond-sutra.020', 'active_contemplation')
- inner_silence  ·  ('christian_mysticism.eckhart-sermons-field.016', 'inner_silence')
- body_as_obstacle  ·  ('christian_mysticism.eckhart-sermons-field.016', 'body_as_obstacle')
- body_as_obstacle  ·  ('christian_mysticism.eckhart-sermons-field.020', 'body_as_obstacle')
- living_god  ·  ('christian_mysticism.eckhart-sermons-field.020', 'living_god')
- cosmic_dualism  ·  ('christian_mysticism.eckhart-sermons-field.020', 'cosmic_dualism')
- gnosis_direct_knowledge  ·  ('christian_mysticism.life-and-doctrines-boehme.025', 'gnosis_direct_knowledge')
- self_knowledge  ·  ('christian_mysticism.life-and-doctrines-boehme.025', 'self_knowledge')
- theosis_deification  ·  ('christian_mysticism.life-and-doctrines-boehme.025', 'theosis_deification')
- evil_as_privation  ·  ('christian_mysticism.life-and-doctrines-boehme.025', 'evil_as_privation')
- kingdom_within  ·  ('christian_mysticism.life-and-doctrines-boehme.025', 'kingdom_within')
- body_as_obstacle  ·  ('christian_mysticism.life-and-doctrines-boehme.025', 'body_as_obstacle')
- divine_sparks  ·  ('christian_mysticism.life-and-doctrines-boehme.025', 'divine_sparks')

### Sample new false positives (up to 15)
- neoplatonism.plotinus-on-intelligible-beauty.001  ·  mystical_union
- neoplatonism.plotinus-on-intelligible-beauty.001  ·  active_contemplation
- christian_mysticism.eckhart-sermons-field.020  ·  unity_of_being
- christian_mysticism.life-and-doctrines-boehme.143  ·  divine_hiddenness
- christian_mysticism.life-and-doctrines-boehme.143  ·  cosmic_dualism
- christian_mysticism.life-and-doctrines-boehme.150  ·  tripartite_soul
- christian_mysticism.life-and-doctrines-boehme.150  ·  return_to_source
- egyptian.egyptian-book-of-the-dead-index.079  ·  anthropomorphism
- egyptian.egyptian-book-of-the-dead-index.126  ·  funerary_navigation
- egyptian.egyptian-book-of-the-dead-index.126  ·  sacred_names
- egyptian.egyptian-book-of-the-dead-index.149  ·  living_god
- egyptian.egyptian-book-of-the-dead-index.149  ·  anthropomorphism
- egyptian.egyptian-book-of-the-dead-index.266  ·  eschatological_judgment
- egyptian.egyptian-heaven-and-hell.071  ·  numerical_mysticism
- gnosticism.gospel-of-thomas.056  ·  pneumatic_elect

## Debug — why v2 regressed (§13.5 "debug before proceeding")

**v2 is systematically more conservative.** Tag counts on the 90-chunk sample:

| score | v1 | v2 |
|-------|----|----|
| 1 | 467 | 347 |
| 2 | 613 | 594 |
| 3 | 168 | 173 |
| total | 1248 | 1114 |

The grouped prompt makes Qwen surface fewer concepts, with the drop concentrated in the
score-1 tier.

**The recall loss is real, not just threshold noise.** Of the 280 human-accepted pairs v2
scored <2: **112** it scored exactly 1 (calibration shift — saw the concept, rated it
peripheral) and **168** it omitted entirely. Cross-referencing v1's score on those pairs:
**158 had v1 score = 2** — concepts v1 confidently tagged that v2 dropped below threshold.
That is the core regression. New false positives are borderline: 40 of 41 are v2 score = 2,
not 3.

### Major confound — benched in the mirror state

This ran against the **mirror-state** taxonomy, where every family is degenerate (one per
domain, label identical to the domain). The v2 grouped prompt therefore showed the model
redundant nesting — `# Cosmology … / ## Cosmology … / [27 concepts]` — paying the *cost* of the
grouped format (extra structure, repeated low-information headers) without the *benefit* it is
designed for (meaningful semantic family clusters that aid reasoning). The grouped prompt's
core premise is untested until real families exist (`ea1c2372`). The design's step ordering
(prompt → bench → cluster) deliberately benches here, but the result suggests the format needs
real families — or rework — to pay off.

### Decoupling note

The hierarchy's retrieval value (query expansion, families in guru-web) does **not** depend on
this prompt change. Tagging can stay on the v1 flat prompt while the hierarchy ships for
retrieval. The prompt change is separable from the schema/retrieval rollout.

## Recommendation / options (operator decision)

Gate **fails** as run. Paths:

1. **Keep tagging on v1; ship the hierarchy for retrieval anyway.** Lowest risk — families help
   guru-web regardless of the tagging prompt. Revisit the grouped prompt later.
2. **Re-bench v2 after hand-clustering (`ea1c2372`).** Controls for the mirror-state confound by
   testing the grouped prompt with real families. Cost: do the manual clustering before knowing
   the prompt pays off.
3. **Iterate the v2 prompt and re-bench.** E.g. keep the exhaustive flat list but annotate each
   concept with its family inline (structure as metadata, not reorganization), and/or add an
   explicit "score every concept, do not skip" instruction to counter the conservative shift.

## Notes

- This is an ad-hoc one-time comparison (the formal harness in docs/benchmark-stage4.md is not built yet).
- v2 tags were written to a scratch DB copy only; the live guru.db was not modified by this bench.
- Recall here is measured against v1-proposed-and-reviewed pairs, which slightly under-credits v2:
  432 v2 score≥2 tags fell on pairs with no human verdict and are not scorable. This biases the
  comparison toward v1, but does not explain the drop on the *common* accepted set (the 158
  score-2 concepts v2 genuinely dropped).
