# Can a local model replace the frontier judge?

> **Naming note (2026-08-18).** `campaign_id = "c8"` below is this
> benchmark's own local identifier, frozen when it ran, and unrelated to the
> production campaign of the same name created independently on `main`
> afterward (four western_esoteric texts, `provider = "claude-code"`). This
> branch never modified the shared `config/dossiers.toml`, and the plan
> artifact is filed as `span-plan-c8-bench.*` to avoid colliding on disk with
> whatever the real c8 plan writes. The `"c8"` string inside that frozen JSON
> is left as generated — editing it would falsify the freeze record.

> **[2026-08-16] READ THIS BEFORE QUOTING ANY NUMBER BELOW.** Every measurement
> here was taken through `llm qwen3.8`, which at the time meant TWO uncontrolled
> variables, both discovered afterwards while building `scripts/run-qwen-judge.sh`:
>
> 1. **No pinned seed.** llama.cpp's `--seed` defaults to -1 — a fresh random
>    seed per request. Re-judging the same three rows flipped 3/3 verdicts.
> 2. **MTP speculative decoding on.** At a fixed seed, MTP on vs off changed
>    2 of 3 verdicts and made a third fail to parse, reproducibly. It is
>    distribution-preserving in theory and draws a different sample in practice.
>
> So the agreement rate, the control scores and the self-preference gap all
> have an unknown noise floor. Treat them as directional, not as measurements.
> Re-run through `scripts/run-qwen-judge.sh` (pinned seed, bounded reasoning,
> MTP off — verified reproducible) before any of this decides anything.
>
> Two findings survive the confound. The control DESIGN is sound: opus caught
> 5/6, so the injections are detectable. And the COVERAGE blind spot is real —
> all three graders accepting a summary truncated to its first third is not
> something a seed or a draft head explains.

Three graders over the same 78 items: the 72 paired L1 rows plus 6 negative
controls. Question: can the review loop run offline?

## Why negative controls were necessary

The natural review is 71/72 accept. At that base rate, agreement with the
reference judge cannot separate a discriminating grader from a rubber stamp —
a judge that always says "accept" scores ~99%. So six accepted rows were
mutated with exactly one unambiguous rubric violation each (2 GROUND, 2 LEAK,
1 REGISTER, 1 COVERAGE) and mixed into the run, shuffled with the rest.

Each grader was given only `stage_input`, `output`, `field`, `work_label` and
`prompt_version` — never the generating model, never whether a row was a
control.

## Results

| grader | judged | schema fails | controls caught | agreement w/ opus | mean |
|---|---|---|---|---|---|
| claude-opus-4-8 (reference) | 78 | 0 | **5/6** | — | 22.4s |
| Qwen3.8-27B UD-Q4_K_XL | 78 | 6 | **5/6** | **87.9%** | 46.6s |
| GLM-4.7-Flash UD-Q6_K_XL | 78 | 8 | 2/6 | 26.6% | 32.4s |

"Controls caught" means rejected **with the correct rubric code**. Bare
rejection is not enough — GLM rejected 5 of 6 but coded two GROUND injections
as LEAK and one LEAK as COMPARE, and it rejects most things anyway.

### Qwen3.8 — viable

Matched the reference exactly on the controls, including the same miss. 87.9%
agreement on the natural rows, and **all 8 disagreements run one way**: opus
accepted, Qwen rejected. It is uniformly stricter, never more permissive —
the right failure direction for a gate.

Its 6 schema failures are all JSON truncated mid-sentence: the model wrote
sprawling `evidence`/`rationale` and exhausted the allowance. That is the same
verbosity bias that made its summaries +17.7% long, reappearing in the grader
role. `run_contract.py` does not retry, so those rows yield nothing.

### GLM-4.7-Flash — not viable as configured

Rejected **47 of 72 rows opus accepted**, coding them LEAK 22x, GROUND 12x,
FORMAT 7x. Accept rates of 30.3% local / 19.4% frontier against opus's 100% /
97.2%. Its control "detections" are therefore uninformative — a grader that
rejects three quarters of everything catches injected faults by default.

Not a throughput problem: it ran at 87.4 tok/s, faster per token than Qwen.
It discriminates rubric codes poorly.

GLM-4.5-Air was not tested. Flash was chosen over it as the stronger candidate
(Q6 and VRAM-resident versus Air's Q2 with ~20 GiB of experts on CPU, which at
Air's measured 131 tok/s prompt throughput would have cost ~2.6h for this run).
Given how far Flash landed from the reference, Air at Q2 is unlikely to do
better, but that is inference, not measurement.

## Two findings that hold across all three graders

**COVERAGE is a blind spot.** Every grader accepted `ctl6` — a summary
truncated to its first third, dropping whole later episodes. Opus, Qwen and
GLM all missed it. This converges with the local arm's +17.7% length drift
drawing zero COVERAGE rejects across 72 judgements. Proportion and ordering
are exactly what `l1-v3` was written to enforce after the c1 and c7 failures,
and this review cannot currently verify either. That is a rubric/tooling gap,
not a model gap, and it is the most actionable result here.

**The gendering pair was not judge noise.** Earlier this was reported as the
judge catching one instance of a defect and missing an identical one. All
three graders independently rejected `s1597` (frontier) and accepted `s1641`
(local). Counting referents, frontier imposed a gender on Providence ~10 times
where local did so ~2 times (local's other masculine pronouns correctly track
John and the sleeper). A difference of degree, judged consistently by three
models — not an inconsistency. The earlier "judge caught one and not the
other" framing overstated it.

## What this licenses

Qwen3.8 can plausibly stand in for the frontier judge on L1 review: it matches
control sensitivity exactly and errs strict. Before relying on it, fix the
schema-failure rate — either raise the contract's `max_tokens` for local
graders or add a reject-retry to `run_contract.py`, which currently has none.

It does NOT license running generation and review both on Qwen. Qwen accepted
its own output at 91.4% versus 80.6% for frontier output. That gap is
consistent with self-preference, but also with the frontier arm genuinely
carrying more GROUND violations — which is what the rubric predicts and what
the one confirmed real defect was. The two explanations are not separated by
this data. If the pipeline ever runs local-generate + local-review, that
question needs answering first.
