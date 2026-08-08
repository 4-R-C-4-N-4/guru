# 11 — tag-review

**Kind:** gate · **Contract:** [`prompts/ingest/tag-review.md`](../../prompts/ingest/tag-review.md)

Curate the staged tags. A driver may **queue** decisions. Only the user applies
them.

## Precondition

`staged_tags` rows exist for the text (node 10).

## Action

Terminal UI:

```sh
python3 scripts/review_tags.py --text <source-id> [--min-score 2]
```

Or the review web app's HTTP API, which is what the `guru-review-tags` skill
drives. Either way the judgement criteria are the contract's, and they are the
same criteria in both.

Queue `accept` / `reject` / `reassign` / `skip`. Never call `/api/apply`.

## Output

Queued decisions in `review_actions`. The live `EXPRESSES` edges do not change
until the user drains the queue.

## Gate

No `pending` rows remain for the text. `guru ingest status` reports the
remaining count.

## Failure modes

**Queueing blind.** Every accept and reject must come from having read the
chunk body. Not "the model is well calibrated here", not "I read thirty of
fifty-five and the rest looked similar", not grepping ids out of a batch dump.
A verdict without a reading is indistinguishable from one in the audit trail,
which is what makes it worse than no verdict.

**Rejecting on tradition mismatch.** Cross-tradition tags are the entire point
of the corpus. A 2026-05-31 session over-rejected roughly 43 valid mappings on
the Plato dialogues by reasoning "concept is Zoroastrian, text is Greek,
therefore reject", and they had to be flipped back. The only question is
whether the chunk substantively expresses the concept's structural pattern.

**Reassigning onto a concept the chunk already carries.** The apply fails on
`UNIQUE constraint failed: staged_tags.chunk_id, staged_tags.concept_id,
staged_tags.model, staged_tags.prompt_version` and rolls back the entire batch.
`insertReassignedTag` in `apply.ts` does not guard against it. Check first, and
prefer plain `reject` when the better concept is already in play.

**Mistyped ids in a batch queue.** They are silently rejected. Check the
accepted count matches what was intended — 4B ids are 70xxx, 27B are 71xxx.

**Chasing an accept rate.** Observed rates run from about 15% on diffuse
score-1 pools to 90% on densely on-concept curated runs, and 0% on apparatus
chunks. The rate is an outcome.

## Provenance

Rubric extracted from the `guru-review-tags` skill (calibrated against a
50-chunk score-1 run, 2026-05-11) so that it lives in the repository rather
than in one harness's configuration. The skill remains the Claude Code adapter
for the web app.
