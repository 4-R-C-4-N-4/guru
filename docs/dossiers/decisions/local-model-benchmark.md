# Can a local model run Pass D? — 2026-08-16 to 2026-08-18

**Verdict: not yet.** Provider stays `claude-code`. The blocker is a template
budget formula, not model quality, and is fixable independent of this
decision. Two runner scripts and a reproducibility fix landed from this work;
everything else — the investigation's raw data, intermediate docs, and
throwaway analysis scripts — was deliberately not kept in-tree. This file is
the durable record.

> **Qualified 2026-08-20.** "Not yet" holds for the *sample this was measured
> on*, not as a blanket rule. Local generation subsequently ran the full
> **Kybalion** Pass D end-to-end and shipped as campaign `c9` — the first
> local-model dossier live in the corpus. See
> [Update: the Kybalion counter-case](#update-2026-08-20--the-kybalion-counter-case).

## Question

Local capacity (Qwen3.8-27B on the 3090, tuned via `run-qwen-generate.sh` /
`run-qwen-judge.sh`) sat idle while Pass D ran entirely on `claude-code`. Could
generation, review, or both move local — for cost, for throughput, or simply
to stop leaving a GPU idle?

## Method, briefly

A paired A/B: generate the same spans under both providers, judge both blind
against the D3 rubric, compare. Started on 36 spans of long continuous prose
(three works already carrying accepted frontier `l1-v3` rows, so the pairing
was free). Extended to 8 chapters of the Dhammapada — short, discrete-verse
spans — because the first sample had no sayings/logia genre and `l1-v3`'s
strictest rule (source order) binds hardest there. Judge quality was checked
separately with negative controls (rows with a deliberately injected GROUND /
LEAK / REGISTER / COVERAGE failure), since a review that already accepts
~97% of everything can't distinguish a discriminating judge from a rubber
stamp. Finally, a grid search over temperature and reasoning-budget for both
roles, to confirm the tuned defaults were a real optimum and not a lucky
first guess.

## Findings

**Generation doesn't clear the bar, and the cause is identified.** Even at
the best sampler configuration found (temp 0.6), local generation ran
+26–31% over the L1 length budget and needed a retry on most spans; at worse
configurations it skipped spans outright after exhausting all retries.
Frontier cleared every band on the first attempt, zero retries, across both
genres. The root cause is `generate_dossiers.py`'s L1 budget formula —
`min(300, max(80, span_tokens // 12))` — which gives a short chapter as
little as ~87 tokens of budget. That number is calibrated to how terse
`claude-code` happens to be; Qwen3.8 writes longer regardless of temperature,
so the tighter the span, the more certainly it misses. No sampler setting
closes this gap; the formula would need to change (e.g. a wider band, or a
model-specific multiplier) before local generation is worth re-testing.

**Judge agreement is unresolved, and swings hard by genre.** On long prose,
an early measurement showed 87.9% agreement with the frontier judge — but
that run had two uncontrolled variables (an unpinned sampler seed, and
speculative decoding on) later shown to move verdicts on their own. Re-run
properly on the Dhammapada set, agreement was 36%. Neither number can be
trusted in isolation, and which judge is closer to "right" was never
established — the local judge was *stricter* on both arms, not just its own,
which argues against simple self-preference but doesn't resolve the question.

**COVERAGE is a blind spot for every judge tested, frontier included.** A
control response — truncated to its first third, whole later episodes
dropped — was accepted by every grader in every configuration, opus among
them. Proportion and ordering are exactly what `l1-v3` was written to
enforce after prior review rounds; this review cannot currently verify
either, independent of which model runs it.

**A real, general infrastructure bug was found and fixed.** `serve-llama.sh`
never set `--seed`, and llama.cpp defaults it to -1 — a fresh random seed
per request. The same row judged twice, identical inputs, returned different
verdicts: 3 of 3 flipped in one test. A review gate whose accept/reject
depends on which run happened to occur isn't a gate. Fixed by adding
`SEED` (plus `REASONING_BUDGET`, to stop unbounded thinking from consuming a
caller's entire token budget and returning prose instead of JSON) as
additive, opt-in knobs to `serve-llama.sh` — default behavior for every other
caller is unchanged.

**The tuned defaults are a genuine optimum, not a guess that got lucky.** A
grid search (temp × reasoning-budget for the judge; temp alone for
generation, since its caller has no per-request override path) confirmed
temp 0.6 wins on every axis tested in the 0.5–0.7 range: fastest among the
judge configs that hit ceiling accuracy, and the only generation config with
zero skipped spans *and* the best length ratio. 0.5 and 0.7 both fail on the
identical two chapters that 0.6 alone resolves.

## What shipped

- `scripts/run-qwen-generate.sh`, `scripts/run-qwen-judge.sh` — tuned,
  reproducible launchers for the two roles, kept for future local-model
  work (ad hoc spot-checks, a future re-attempt once the budget formula is
  revisited). Neither is wired into `config/dossiers.toml`; the live
  campaign provider is untouched.
- `SEED` / `REASONING_BUDGET` / `EXTRA_ARGS` in `scripts/serve-llama.sh` —
  general reproducibility fixes, not specific to this investigation.

## What did not ship

The raw grid data, the paired-arm generation logs, the judge verdict dumps,
and three one-off analysis scripts lived in `docs/dossiers/` and `scripts/`
for the duration of the investigation and were removed before merge — they
were lab notebook, not workbook reference, and cluttered the six-node
operational docs they sat alongside. The full history, including every raw
data file, is preserved in this branch's git history up to commit
`40418f2d` if ever needed again.

## Before revisiting

1. Recalibrate (or make model-aware) the L1 budget formula in
   `generate_dossiers.py`. This is the one blocker generation actually has.
2. Resolve the judge-agreement question with a third genre or a
   differently-sourced ground truth — two data points bracketing 36%–88% is
   not enough to trust either.
3. Test past L1. Structured fields (`context`, `key_figures`, `key_terms`,
   `reading_notes`), L2 synthesis, and the fold/map-reduce path
   (`input_budget > 0`) were never touched — Phase 1 of this investigation
   was L1-only throughout, and a good L1 result doesn't imply the rest of
   the pipeline is ready.

## Update 2026-08-20 — the Kybalion counter-case

After this benchmark, **Qwen3.8-27B (`llamacpp`) drove the entire Pass D for
the Kybalion** — generate, review-as-judge, promote, embed — as campaign `c9`,
and it went live: the first local-model dossier in the corpus
(`config/dossiers.toml`, c9 note). It did well. So the blanket "not yet" now has
a real counter-data-point: local Pass D is *demonstrated end-to-end on at least
one work*, past the L1-only boundary Phase 1 stopped at.

**It does not overturn the benchmark, and the two are consistent.** The one hard
blocker here was the L1 budget formula overshooting on *terse, discrete-verse
spans* — the Dhammapada arm, where the finding above says the formula "binds
hardest." The Kybalion is modern, continuous prose with looser spans: exactly
the shape the formula does **not** pinch. Kybalion clearing what the Dhammapada
arm failed is what this benchmark would predict from span geometry alone — a
genre effect, not a reversal of the length-budget finding.

**Owner's read (unproven):** the more modern prose may simply be easier for the
local model to handle. Plausible, but **not measured** — nothing here isolates
prose-era from span geometry, sampler settings, or the budget-formula
interaction, and the two candidate explanations (modern prose vs. loose
continuous spans) are confounded in this single case. Treat it as a hypothesis
to test — the third-genre control called for in "Before revisiting" #2 is
exactly the instrument that would separate them — not as an established finding.

**Standing guidance is unchanged.** The campaign default is still `claude-code`;
local is proven on one modern-prose work, not as a general option; and
recalibrating the L1 budget formula (#1 above) is still the prerequisite before
local generation is worth defaulting anywhere near terse-verse material.
