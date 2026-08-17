# c8 — the logia extension (Dhammapada)

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
