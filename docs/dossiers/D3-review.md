# D3 — review

**Kind:** gate · **Contract:** [`prompts/dossier/contracts/review-rubric.md`](../../prompts/dossier/contracts/review-rubric.md)

Judge sampled rows against the rubric, revise the template on clustered
failures, bulk-accept the passing batch.

## Precondition

Staged rows for the work (D2).

## Action

```sh
python3 scripts/review_dossiers.py sample --field <field> --k 15
python3 scripts/review_dossiers.py sample --level <n> --k 15
python3 scripts/review_dossiers.py show <id>
python3 scripts/review_dossiers.py accept <id>
python3 scripts/review_dossiers.py reject <id> --code GROUND --note "..."
python3 scripts/review_dossiers.py bulk-accept --field <f> --prompt-version <v> [--work <w>]
python3 scripts/review_dossiers.py status
```

`sample` takes **exactly one** of `--field` or `--level` and exits with
`pass exactly one of --field / --level` if you give it both or neither.

Row ids are prefixed: `f…` for `staged_dossier_fields`, `s…` for
`staged_summaries`.

## Output

Accepted and rejected staged rows — and, when a code clusters, a revised prompt
template at a new version.

## Gate

No `pending` rows remain for the work.

## Failure modes

**Reviewing rows instead of the template.** The unit that converges here is the
template. A single bad row is a data point; a cluster of the same code is a
defect, and the fix is to revise `prompts/dossier/<field>-vN.md`, bump the
version, and regenerate. The version history — `l1-v1 → l1-v2`,
`structure-v1 → v2`, `l2-v1 → v2` — is what that looks like when it works, and
the 613 rejected structure entries against 773 accepted are its cost, not its
failure.

**Judging output without its input.** `show` prints the reconstructed stage
input alongside the output for a reason. With a frontier-model generator the
characteristic failure is fluent, well-formed, *correct* prose that the input
never supported — the model knows these texts and will tell you what it knows.
Correct is not the standard; grounded in the input is. You cannot check
`GROUND` or `LEAK` without seeing what the model was allowed to know.

**Expecting the old failure distribution.** Under `claude-code`, `FORMAT`
should be nearly extinct and `REGISTER`/`HEDGE` should mostly hold. That makes
`GROUND` and `LEAK` *harder* to catch, not easier — the failures that remain
are the ones that read well.

**Blaming an L2 template for an L1 defect.** An L2 `COVERAGE` or `GROUND`
failure frequently traces down through `child_summary_ids` to a bad L1. Check
before revising.

**Judging cluster membership from one work's sample.** `template_defect` is a
claim about the template, and the evidence for it is cross-work. In the c7 tail
review, three GROUND failures with the identical mode — naming the work's
author/translator ("Hall", "Ouspensky", "Taylor") when the input never does —
sat in three different works, and each looked like a one-off from inside its
own work. Reviewed per-work, the cluster is invisible; aggregate the codes
across the whole sample before deciding one-off versus defect. That cluster is
what bumped `l1-v2 → l1-v3`.

**Blaming the template for a span-boundary artifact.** Two review observations
that look like template failures and are not: spans consisting entirely of
translator footnotes (the chunker splits an edition's endnote block into its
own span — `gnostic-john-baptizer`), and numbered endnotes split mid-note so
the next span opens with an unnumbered fragment the summary then mis-numbers
(`iamblichus-on-the-mysteries`, s1557). The first the template handles well —
it names the span as editorial apparatus; the second produces a real GROUND
reject, but the fix is upstream in span planning, not in the prompt.

**Leaving the queue half-drained.** For most of c7 this is where the corpus
actually sat: 17 of 56 works with pending rows — `iamblichus-on-the-mysteries`
(13), `pistis-sophia` (11), `zhuangzi-inner-chapters-index` (9) worst. Works
with pending rows cannot promote, so their dossiers are simply absent from
study mode. The backlog was drained 2026-08-13; what it cost to drain (three
template bumps, two respins, and a manual-remediation round) is recorded in
the version-history comments in `generate_dossiers.py`.

## Provenance

`scripts/review_dossiers.py`; rubric codes and their template responses from
`docs/summary/document-knowledge-data-structures.md` §1.3.4 and its
frontier-model caveat; backlog figures measured 2026-08-08.
