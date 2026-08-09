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

**A `reassign` cannot close this gate in one cycle.** `insertReassignedTag`
marks the donor `reassigned` and inserts the new tag at `status='pending'`, so
applying a queue that contains reassigns leaves exactly as many new pending
rows as there were reassigns. The node then reports itself unfinished, and
node 14 stays blocked behind it, until the reviewer queues a verdict on each
new row and the user applies a *second* time.

Measured on yoga-sutras: the node 11 queue carried six reassigns. After the
apply, books 01, 02 and 04 each still showed pending rows and failed the gate;
book 03 — the only book with no reassigns — passed. The six accepts that would
close it are queued and unapplied.

Plan for two applies whenever the pass uses `reassign`, and say so when handing
the queue over. A driver that reports "node 11 complete" after queueing has
told the user something the status machine will contradict.

Before handing the queue to the user, validate it:

```sh
python3 scripts/validate_queue.py        # --json for machines, -v to list all
```

`POST /api/apply` drains every unapplied action in a single transaction, and
`GET /api/apply/preview` only counts them. One collision therefore discards a
whole review pass. The validator replays the queue read-only in the server's
own order and exits non-zero on anything that would raise.

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

**Treating review as subtraction only.** Accept and reject work on what the
tagger proposed, so it is easy to conclude that a concept the tagger *missed*
is out of reach at this node and belongs to node 10's recall problem.
`reassign` is the way in: per `apply.ts` it marks the donor tag `reassigned`,
deletes its live edge exactly as `reject` would, and then inserts a **new**
`staged_tag` for the target concept. The donor's fate is identical either way,
so any queued reject on the same chunk is free capacity — and at an observed
13.4 tags per chunk there is always one to spare.

Two things this does not do. The new row lands `pending` with no `upsertEdge`,
so a reassign does not produce a live edge — it puts the missing concept back
in the queue for a second pass. And `updateStagedTagConcept` overwrites the
donor's `concept_id` with the target, so the record of what was originally
proposed there is lost. Pick a donor whose original tag you do not want in the
over-generation statistics.

The self-collision that looks fatal is not: the reassign path updates the donor
to `reassigned` *before* inserting, and `idx_staged_tags_provenance_unique` is
partial (`WHERE status = 'pending'`), so the donor leaves the index first. The
collision in the failure mode above is with a *different* pending row.

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
