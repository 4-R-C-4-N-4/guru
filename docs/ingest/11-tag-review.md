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

**Reading "nothing staged to review" as "nobody has looked".** It used to mean
both. The gate tests live and staged state only, so queued-but-unapplied
`review_actions` were invisible to it, and the most common intermediate state
in the pipeline — every judgement made, sitting in the queue waiting for the
user — rendered exactly like an untouched text. After the yoga-sutras pass,
2,579 queued verdicts were reported as an absence.

Since todo:4264c23f the gate says `N tag verdicts queued, awaiting your apply
— POST /api/apply`. The node still reports not-done, because a queued verdict
is not an applied one; only the message changed, from an absence to a call to
action. It also makes an agent's hand-off checkable: "node 11 complete" can
now be verified against the status machine instead of taken on trust, which is
the reason review and apply are separate in the first place.

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

A reject on the occupying tag *does* clear the way, but only if it is queued
**before** the reassign. `buildApply` drains `selectQueuedActions`, which is
`ORDER BY id ASC`, so the queue applies in insertion order: clear the concept
first, then reassign onto it. Queue them the other way round and the reassign
applies while the occupant is still `pending`, which is the batch-destroying
case above. Asserted both directions in
`guru-review/server/src/apply.test.ts`, 'queue drain order'.

Note that `scripts/validate_queue.py` currently replays the queue in the
opposite order and will disagree with all of this — it mirrored the queue
*display* query rather than the apply drain (todo:7a815c05). Until that lands,
trust the ordering here over the validator's collision findings.

**Treating review as subtraction only.** Accept and reject work on what the
tagger proposed, so it is easy to conclude that a concept the tagger *missed*
is out of reach at this node and belongs to node 10's recall problem.
`reassign` is the way in: per `apply.ts` it marks the donor tag `reassigned`,
deletes its live edge exactly as `reject` would, and then inserts a **new**
`staged_tag` for the target concept. The donor's fate is identical either way,
so any tag on that chunk you were going to reject is a free *donor* — and at an
observed 13.4 tags per chunk there is always one to spare. (Free as a donor
only. A reject that has to clear the *target* concept is the ordered case in
the failure mode above, not free capacity.)

One thing this does not do: the new row lands `pending` with no `upsertEdge`,
so a reassign does not produce a live edge — it puts the missing concept back
in the queue for a second pass.

The donor keeps its original `concept_id`. It used to be overwritten with the
target (`updateStagedTagConcept`), which stored the target twice and the
proposal nowhere, so donor choice had to avoid tags you wanted kept in the
over-generation statistics. Since todo:a8bb7213 that constraint is gone: a
`reassigned` row still records what the model proposed, and picking the donor
is purely a question of which tag you were going to reject anyway.

**`concept_id` therefore means two different things across the `reassigned`
rows already in `guru.db`.** The 31 rows applied before todo:a8bb7213 store the
*target*; every row after it stores the *original*, and nothing on the row
distinguishes them. An over-generation query run today mixes both. The original
is recoverable — each reassign's spawned row carries
`justification = 'Reassigned from <original>'`, keyed to the same `chunk_id` —
so a backfill is possible, but none has been run, and `reviewed_at` is the only
thing that separates the two populations.

The self-collision that looks fatal is not: the reassign path updates the donor
to `reassigned` *before* inserting, and `idx_staged_tags_provenance_unique` is
partial (`WHERE status = 'pending'`), so the donor leaves the index first. The
collision in the failure mode above is with a *different* pending row.

**Mistyped ids in a batch queue.** They are silently rejected. Check the
accepted count matches what was intended — 4B ids are 70xxx, 27B are 71xxx.

**A new concept's id/label can collide with an ordinary word in
`guru-web`'s query-time concept matcher.** `is_new_concept=1` acceptance adds a
row to `concepts/taxonomy.toml`; the query side (`extractConcepts` in
`guru-web/src/lib/graph.ts`) matches concept labels against query text
whole-word, case-insensitively. A concept id like `group_mind` derives the
label "Group Mind" — and "mind" alone, as a whole word, is common enough that
it fired on an unrelated golden-query probe about a completely different
tradition, pulling the graph leg into this concept's tradition on a query that
had nothing to do with it. Confirmed directly: renaming the concept
(`group_mind` → `collective_psychic_field`, same definition, id/label only)
stopped the spurious match and cleared the resulting retrieval regression.
Before accepting a new concept, sanity-check its id against common English
words the same way you would a variable name shadowing a builtin — a
one- or two-word id built from ordinary nouns/verbs ("mind", "path", "power",
"light" alone) is the risk case; a more specific compound
(`collective_psychic_field`, `psychopomp_journey`) is not. This is a
node-11 judgement call, not something `sync_taxonomy.py` catches — it has no
knowledge of `guru-web`'s matcher.

**Renaming an already-applied concept touches four tables, not three.**
`nodes` (the concept row itself), `edges` (any live `EXPRESSES` rows), and
`staged_tags` (any queued rows) are the obvious ones — but
`concept_family_membership` also references the concept id directly, and
`sync_taxonomy.py` explicitly does not clean up rows for ids that vanish from
the TOML ("Does not delete families / memberships / aliases that vanish from
the TOML"). A rename that misses this table leaves an orphaned membership row
that only surfaces later, as a foreign-key failure in `scripts/export.py`'s
output when `concept_family_membership` is COPY'd but the concept it
references is not. Check all four tables (`nodes`, `edges`, `staged_tags`,
`concept_family_membership`) plus `concept_aliases` before considering a
concept rename complete, then run `sync_taxonomy.py --apply` to pick up the
new id.

**Mistrust `sync_taxonomy.py --dry-run`'s "concepts with no primary family"
count during a rename.** It is computed inside the same transaction the dry
run rolls back, so it reflects a hypothetical post-write state, not the
current one — and in one case here it reported entries as "no primary family"
that, once queried directly against the applied state, already had correct
memberships. Don't debug against the dry-run summary; query
`concept_family_membership` directly.

**Chasing an accept rate.** Observed rates run from about 15% on diffuse
score-1 pools to 90% on densely on-concept curated runs, and 0% on apparatus
chunks. The rate is an outcome.

## Provenance

Rubric extracted from the `guru-review-tags` skill (calibrated against a
50-chunk score-1 run, 2026-05-11) so that it lives in the repository rather
than in one harness's configuration. The skill remains the Claude Code adapter
for the web app.
