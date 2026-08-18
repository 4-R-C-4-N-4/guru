# c8 paired review — findings

> **Naming note (2026-08-18).** `campaign_id = "c8"` below is this
> benchmark's own local identifier, frozen when it ran, and unrelated to the
> production campaign of the same name created independently on `main`
> afterward (four western_esoteric texts, `provider = "claude-code"`). This
> branch never modified the shared `config/dossiers.toml`, and the plan
> artifact is filed as `span-plan-c8-bench.*` to avoid colliding on disk with
> whatever the real c8 plan writes. The `"c8"` string inside that frozen JSON
> is left as generated — editing it would falsify the freeze record.

Blind rubric review of both arms of the local-generator benchmark
(todo:8c67ee44 / todo:fd16e2f9). 72 judgements, 36 paired spans, ~27 min.

## Method

Judge: `claude-opus-4-8` via `run_contract.py` against
`prompts/dossier/contracts/review-rubric.md`.

Blinding: the judge received only `stage_input`, `output`, `field`,
`work_label`, `prompt_version`. Never the generating model, never the arm.
Rows were shuffled with a fixed seed (20260816) so judge drift over the run
cannot correlate with arm.

`--budget 200000` — the default 12000 elides the MIDDLE of an over-long input,
and stage inputs reach ~38k chars. A judge shown head+tail with a hole in it
would mis-score COVERAGE in both directions.

**Both arms were judged fresh.** The pre-existing frontier statuses could not
serve as a baseline: 696 rows carry `reviewed_by='bulk'` against only 175
individual `agent` verdicts, so "accepted" there mostly means a sampled review
passed and the rest were bulk-accepted, not that each row was judged.

## Results

| arm | accept | reject | insufficient | accept rate |
|---|---|---|---|---|
| local (Qwen3.8-27B) | 36 | 0 | 0 | 100.0% |
| frontier (opus-4-8) | 35 | 1 | 0 | 97.2% |

`template_defect=true`: local 0/36, frontier 1/36. Zero parse failures.

**Do not read this as "local wins."** Read it as: at this configuration the
review has almost no discriminative power. 71 of 72 accepted.

## The one reject, and why it invalidates the headline

The single reject is `s1597`, the FRONTIER row for
`sum:apocryphon-of-john:the-savior-enters-the-realm-of-darkness-conclusion`.
Judge's evidence:

> The output renders Providence with feminine pronouns throughout — 'transforming
> into her own seed', 'she enters the realm of darkness' [...] The input never
> genders Providence: it speaks entirely in the first person ('I, the perfect
> Providence', 'my (own) seed'), with no gender marker anywhere

That is a textbook GROUND failure and a direct confirmation of the rubric's own
thesis: the frontier model knows Pronoia is feminine in Gnostic literature and
wrote it confidently. Correct is not the standard; supported by the input is.

**But the local row for the SAME span — `s1641` — wrote "transforms into _his_
seed" and was ACCEPTED**, with the rationale "imports no outside knowledge; no
rubric code fires."

Both arms imposed a gender the source does not supply. The judge caught one and
not the other, on the same span, under the same template, in the same run. So
the 100% local accept rate is not trustworthy, and the 1-row gap between the
arms is inside the judge's own noise.

## Length drift passed entirely unremarked

The local arm runs +17.7% longer than frontier (483.6 vs 410.2 tokens, ratio
1.16-1.21 across all three works — see `c8-local-l1-run.md`). Not one COVERAGE
reject fired. Either that drift is genuinely harmless, or neither the validator
(which enforces only the sanity band) nor the rubric as written catches
proportion drift at this magnitude.

## Judge behaviour worth knowing

`code` is populated even on accepts — 40 accepts named GROUND as the axis
examined, 31 named nothing, 1 reject named GROUND. So `code` is "the axis I
checked", not "the failure I found". Count codes only where
`verdict == 'reject'`. `template_defect` is the load-bearing field, as the
rubric itself says.

## What this does and does not license

Established: the local arm produces output that a blind frontier judge accepts
at the same rate as frontier output, on 36 paired spans of long continuous
prose, at L1 only.

NOT established: that the two are equivalent in quality. A test where 71 of 72
rows pass cannot separate "equally good" from "the instrument is too blunt."
Before this decides anything, the review needs **negative controls** — rows
with deliberately injected GROUND / LEAK / REGISTER / COVERAGE failures — to
establish that the judge detects the failures it is supposed to detect. The
s1597/s1641 pair is a ready-made natural control showing it does not, reliably.

Also untested: the logia/sayings genre (todo:b67bf6d9, still open), the fold
path, and every structured field.
