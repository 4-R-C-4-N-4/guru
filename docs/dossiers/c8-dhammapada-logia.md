# c8 — the logia extension (Dhammapada)

> **Naming note (2026-08-18).** `campaign_id = "c8"` below is this
> benchmark's own local identifier, frozen when it ran, and unrelated to the
> production campaign of the same name created independently on `main`
> afterward (four western_esoteric texts, `provider = "claude-code"`). This
> branch never modified the shared `config/dossiers.toml`, and the plan
> artifact is filed as `span-plan-c8-bench.*` to avoid colliding on disk with
> whatever the real c8 plan writes. The `"c8"` string inside that frozen JSON
> is left as generated — editing it would falsify the freeze record.

The paired set (todo:8c67ee44) was three works of long continuous prose at
~5,200 tok/span and contained no sayings collection, the genre where `l1-v3`'s
order rule is most binding. This closes that gap (todo:b67bf6d9), and is the
first run made under the **pinned sampler** — `scripts/run-qwen-judge.sh`,
seed 20260816, reasoning budget 2048, MTP off — so it is reproducible where the
earlier arms were not.

8 Dhammapada chapters, ~1,540 tok/span of discrete verses. 7 pair (local
log-skipped chapter V).

## Generation: local is materially worse here

| | frontier (opus-4-8) | local (Qwen3.8-27B) |
|---|---|---|
| spans produced | **8 / 8** | **7 / 8** |
| calls spent | **8** | **~18** |
| spans needing ≥1 retry | **0** | **all of them** |
| length vs frontier | — | **+40.6%** |

Per-span ratios 1.04–1.57. Across the wider run (chapters 1–18) **three spans
exhausted all 3 attempts and produced nothing**; frontier had zero failures.

The cause is the budget formula, not the genre. L1 budget is
`min(300, max(80, span_tokens // 12))`, so a 1,052-token chapter gets **87
tokens** where an Iamblichus span got the full 300. The band tightens with span
length and the model does not adapt — it writes its natural 250–550 tokens
regardless. One first attempt returned **4,889 tokens against a ceiling of
380**, a 13x overrun.

Compare long prose: +17.7% length drift, 42% of spans needing a retry, zero
skips. Short spans make the same bias qualitatively worse.

## Review: the two judges do not agree

Both arms, both judges, same 14 rows.

| judge | local accept | frontier accept | rejects |
|---|---|---|---|
| claude-opus-4-8 | **7 / 7** | **7 / 7** | none |
| Qwen3.8 (pinned) | 3 / 7 | 2 / 7 | GROUND 6, REGISTER 2, COVERAGE 1 |

**Judge agreement: 5/14 = 36%.**

Against 87.9% on long prose. That earlier figure was measured with an unpinned
seed and MTP on, so it was never trustworthy — but the gap is far too large to
be confound alone. On this genre the local judge and the frontier judge are
not interchangeable.

Which is right is **not established**. Neither reading is comfortable:

- Opus accepted 14/14 including a summary running +40% over budget, on a text
  it certainly knows well. The rubric's own caveat is that a frontier judge
  shares the generator's knowledge and so cannot see what the input failed to
  support. 14/14 with no code fired on any row is the shape that caveat predicts.
- Qwen rejected 9/14, on a genre where the reference finds nothing at all. It
  was also harsher on frontier (5 rejects) than on its own arm (4), which is
  the opposite direction from self-preference, so strictness rather than bias
  looks like the better explanation.

Without ground truth for these 14 rows, the honest statement is that the
instrument disagrees with itself depending on which model holds it.

## The COVERAGE reject

One fired — `s1685`, local, from the Qwen judge. It is the only COVERAGE reject
in the entire study, across 72 long-prose judgements plus a deliberately
truncated control that every grader accepted.

Opus accepted that same row. So this is not the blind spot closing; it is one
judge seeing something the reference does not, once, on a discrete-verse
source. Worth noting as a lead — omission may be easier to see when the source
is a list of separable items than when it is continuous argument — and nowhere
near enough to claim.

## What this changes

The generator question and the judge question separate cleanly, and they answer
differently:

- **Local generation on short-span logia: no.** One in eight spans produced
  nothing, every span needed a retry, and output ran +40% over budget. On long
  prose it was defensible; here it is not.
- **Local judging as a drop-in for opus: not established.** 36% agreement on
  this genre. Both the earlier 87.9% and this 36% are single-genre numbers, and
  they bracket a range too wide to orchestrate on.

Neither result forbids local orchestration. Both say the case is not yet made,
and that the budget formula — not the model — is the first thing to fix if the
answer is meant to be yes.

## Addendum — judge temperature (2026-08-17)

The judge above ran at TEMP=1.0. That was wrong, and the reasoning that put it
there was confounded.

An earlier TEMP=0.2 test produced 4,469 tokens of thinking and no verdict, 6 of
6 judgements returning nothing, and was written up as "low temperature breaks
thinking models". That run had **no reasoning budget set**. Unbounded thinking
exhausts the caller's max_tokens by itself; temperature was never the cause. The
conclusion should never have been drawn from it, and it closed off the range a
gate actually wants.

Re-tested with REASONING_BUDGET held at 2048, varying only temperature and
reasoning effort. Six rows across both genres (3 long-prose, 3 logia), two
passes each, all six carrying `opus=accept` as reference:

| config | deterministic | agrees with opus | parse failures |
|---|---|---|---|
| temp 1.0 / effort medium | 6/6 | 4/6 | 0 |
| **temp 0.6 / effort low** | **6/6** | **5/6** | **0** |

Same reproducibility, closer to the reference, no parse cost. `s1641` — the
apocryphon "his seed" row — is the one that moves, from reject to accept.

`scripts/run-qwen-judge.sh` now defaults to temp 0.6 with
`reasoning_effort=low`. Raw verdicts in `c8-judge-temp-tuning.txt`.

Two caveats. n=6 with every reference verdict being `accept`, so this measures
false-positive rate and says nothing about whether either config catches a real
failure — the negative controls would need re-running at 0.6 to establish that.
And the 36% judge-agreement figure above was measured at temp 1.0; it would
need re-running at 0.6 before being quoted as the local judge's agreement rate.

## Addendum 2 — generation temperature (2026-08-17)

The generation numbers above were produced at temp 1.0 / effort medium, because
the run used the judge server's settings. Re-run with only TEMP and
reasoning_effort changed — same spans, same seed, same reasoning budget — via
the new `scripts/run-qwen-generate.sh`:

| chapter | frontier | temp 1.0 / medium | temp 0.6 / low |
|---|---|---|---|
| I | 380 | 554 | 585 |
| II | 142 | 148 | 158 |
| III | 191 | 300 | 251 |
| IV | 175 | 267 | 230 |
| V | 153 | **LOG-SKIP** | **210** |
| VI | 236 | 371 | 358 |
| VII | 240 | 308 | 262 |
| VIII | 178 | 248 | 212 |
| **produced** | 8/8 | 7/8 | **8/8** |
| **vs frontier** | — | +40.6% | **+30.7%** |

temp 0.6 is tighter on 6 of 7 comparable spans and **recovers chapter V**, which
at 1.0 exhausted all three attempts (387/320/309 against a [42,256] band) and
produced nothing.

This corrects a claim made earlier in this investigation. The argument was that
configuration could deliver reproducibility but not compliance, because "no
sampler setting changes what the prompt is asking for", and that the budget
formula was therefore the only lever. The second half stands — the residual
+30.7% and the retry rate do trace to `min(300, max(80, tok // 12))` asking ~87
tokens of a 1,052-token chapter, and frontier clearing all 8 bands first try
proves the formula is met-able. But the first half was wrong: temperature
changes how closely the model tracks a length instruction, and at 0.6 it tracks
it well enough to clear a band it could not clear at 1.0. A span was recovered
by a config change alone.

So the two runners earn their separation on measurement, not on principle:

| | `run-qwen-generate.sh` | `run-qwen-judge.sh` |
|---|---|---|
| CTX_SIZE | 24576 | 32768 |
| TEMP | 0.6 | 0.6 |
| REASONING_BUDGET | 2048 of 8192 | 2048 of 6000 |
| tuned against | length-band overrun → skips | not reaching the verdict |
| gain from tuning | 7/8 → 8/8 spans, +40.6% → +30.7% | 4/6 → 5/6 agreement, 3/3 flips → 6/6 stable |

Raw output in `c8-generate-temp-tuning.txt`.

## Addendum 3 — stratified grid search, judge and generation (2026-08-17)

Prior tuning was three isolated points (temp 1.0, 0.6, and a confounded 0.2).
This is a real grid: judge over temp x reasoning_budget (9 cells), generation
over temp alone (4 points), against test sets designed to expose false
positives AND false negatives, not just accepts.

### Judge: 3x3 grid, temp {0.5,0.6,0.7} x budget {1024,2048,3072}

Test set: 3 known-accept rows (opus reference) + 4 known-should-reject (1 real
GROUND failure — `s1597` — plus 3 synthetic controls: GROUND, LEAK, REGISTER).
One pass per cell, `reasoning_effort=low` held fixed throughout.

**Reject-detection was 4/4 in every one of the 9 cells.** GROUND, LEAK,
REGISTER and the real s1597 failure are caught regardless of temp or budget in
this range — that axis has no failure mode here. All variance is one row,
`s1640`, over-rejected in the weaker cells.

| temp\budget | 1024 | 2048 | 3072 |
|---|---|---|---|
| 0.5 | 6/7 | **7/7** | 7/7 |
| 0.6 | 6/7 | **7/7** | 7/7 |
| 0.7 | 6/7 | 6/7 | 7/7 |

Five cells tie at 7/7. Fastest among them: **temp 0.6 / budget 2048 at 49.2s/call**
— the config already shipped in `run-qwen-judge.sh`. Its determinism was
verified earlier through the real code path (`run_contract.py`, 2 passes,
6/6 stable). Budget 3072 is the more conservative choice (7/7 at every temp
tested) at a 15-30% speed cost and no accuracy gain on this sample.

Raw data: `c8-judge-grid.jsonl`.

### Generation: temp sweep, 4 points, budget=2048 fixed

Same 8 Dhammapada chapters, everything but TEMP held constant.

| config | produced | ratio, common-6 chapters (fair) |
|---|---|---|
| temp 1.0 | 7/8 | +37.9% |
| temp 0.7 | 6/8 | +29.0% |
| **temp 0.6** | **8/8** | **+26.1%** |
| temp 0.5 | 6/8 | +34.6% |

"Common-6" = the 6 chapters (I,II,III,IV,VII,VIII) every config actually
produced — comparing raw means across configs with different skip sets is
unfair, since a config that skips the hardest chapters (V, VI) gets an
artificially better average. On that fair basis, **temp 0.6 wins outright**:
zero skips AND the best length efficiency, not a tradeoff between them.

Both 0.5 and 0.7 skip the same two chapters (V and VI) that 0.6 alone
resolves. 0.6 is not an arbitrary midpoint — it is a genuine local optimum on
both metrics in the tested range.

Raw data: `c8-generate-temp-grid.txt`.

### Net result

Both files' shipped defaults (temp=0.6, budget=2048, effort=low, seed pinned)
are validated by a real grid rather than by the point-tests that set them.
No change made — the search confirmed the existing choice rather than beating
it, which is itself the useful result: the earlier single comparisons weren't
lucky, they landed on the actual optimum.
