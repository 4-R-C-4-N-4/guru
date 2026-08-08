# The Pass D workbook — dossiers and summaries

The second ingest stream. [`docs/ingest/`](../ingest/README.md) takes a URL to
clean, tagged, embedded chunks. Pass D takes those chunks to the
document-knowledge layer: a **dossier** per work, and a tree of **summaries**
over its spans.

The design is specified in
[`document-knowledge-data-structures.md`](../summary/document-knowledge-data-structures.md).
That document says what the layer is. This one says how to run it.

## The unit is the work, not the text

This is the first thing to get straight, and the reason Pass D cannot be nodes
16–21 of the ingest workbook.

A **work** is the dossier and level-2 summary unit. Grouped works are declared
in `sources/works.toml`; every corpus text not listed there is an implicit
singleton with `work_id == text_id`. Agrippa's *Natural Magic* is sixty-odd
chapter files — sixty ingest runs, one work, one dossier.

```
python3 -m guru dossier status <work-id>    # where this work is
python3 -m guru dossier survey              # where every work is stuck
python3 -m guru dossier drift               # three views of the corpus, reconciled
```

The streams meet in exactly one place: **D1 requires every member text through
ingest node 07.** A summary generated over uncleaned bodies summarises the
site navigation too.

## The nodes

| # | Node | Kind | Produces |
|---|---|---|---|
| D1 | [plan-freeze](D1-plan-freeze.md) | command | `docs/summary/span-plan-{campaign}.json` |
| D2 | [generate](D2-generate.md) | command | `staged_summaries`, `staged_dossier_fields` |
| D3 | [review](D3-review.md) | gate | accepted rows, and a converged template |
| D4 | [promote](D4-promote.md) | gate | `work_dossiers`, `summary_nodes` |
| D5 | [embed](D5-embed.md) | command | `summary_embeddings` |
| D6 | [export](D6-export.md) | user | a shipped corpus |

Same six-section file schema as the ingest workbook, and the same rule about
which section matters: **Failure modes** is the part that cannot be
reconstructed by reading the scripts.

## Three ideas that are not obvious from the code

**The generation backend is a campaign parameter, not architecture.**
`config/dossiers.toml` sets `provider`. Today it is `claude-code` — headless
Claude Code on the subscription, pinned to an explicit model — which is why
this stream is normally driven by an agent end to end rather than by a local
model. `local` is the llama.cpp path, and it is the only one that uses folds
and map–reduce, because those exist purely to work around a small context
window. Under `claude-code`, `input_budget = 0` and level-0 fold rows never
appear at all.

**The span plan is a freeze artifact.** Once generation has begun, a corpus
change that alters totals means a *new campaign* — bump `campaign_id`, re-plan,
and the prior works' span ids stay identical so their staged rows carry
forward. Never a partial re-plan. `c1` through `c5` each exist because one text
was added.

**The converging unit in review is the template, not the row.** You sample K
works stratified by tradition and size, judge them against seven rubric codes,
and on a *cluster* of the same code you revise the prompt template and
regenerate rather than rejecting rows individually. The version history is the
evidence this works: `l1-v1 → l1-v2`, `structure-v1 → v2`, `l2-v1 → v2`. The
reject counts are not waste — 613 rejected structure entries against 773
accepted is what template convergence looks like from the inside.

## Judgement contracts

Two, in [`prompts/dossier/contracts/`](../../prompts/dossier/contracts/):

- **`review-rubric`** — judging one staged row, and deciding whether its
  failure is a one-off or a template defect.
- **`campaign-bump`** — deciding whether a change forces a new campaign.

They are kept in a subdirectory because `prompts/dossier/*.md` itself holds the
Pass D *generation* templates, which are a different format entirely:
single-brace placeholders, no frontmatter, composed with `preamble.md` and
consumed by `generate_dossiers.py`. Do not put a contract in with them.

```sh
python3 scripts/run_contract.py review-rubric --input stage_input=... --input output=...
python3 scripts/run_contract.py campaign-bump ... --print-prompt
```

## Reading the drift report

`guru dossier drift` reconciles three views that can disagree: the frozen span
plan, the live dossier tables, and the works resolvable from `corpus/` on the
current checkout. Two different problems produce the same symptom, and they
want opposite responses:

- **FREEZE VIOLATION** — the work's texts are on disk and it has a live
  dossier, but the frozen plan does not contain it. The plan no longer
  describes the corpus. Bump the campaign and re-plan.
- **ORPHANED** — a live dossier for a work whose texts are not in `corpus/` at
  all. `data/guru.db` is git-ignored and therefore shared across every branch,
  while `corpus/` and `sources/manifest.toml` are tracked. Pass D run on a
  feature branch leaves live rows that every other branch can see and cannot
  explain. Nothing is wrong with them; they belong to a checkout you are not
  on. Find it with `git log --oneline --all -- corpus/<tradition>`, and do not
  delete anything to make the message go away.

That distinction is the single most useful thing in this workbook, because the
symptom is identical and one of the two responses destroys work.
