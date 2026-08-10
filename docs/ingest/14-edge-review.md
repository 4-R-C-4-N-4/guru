# 14 — edge-review

**Kind:** gate · **Contract:** [`prompts/ingest/edge-review.md`](../../prompts/ingest/edge-review.md)

Curate the staged edges. Queue decisions; never apply them.

## Precondition

`staged_edges` rows exist for the text (node 13).

## Action

```sh
python3 scripts/review_edges.py [--min-confidence 0.7] [--edge-type PARALLELS]
                                [--tradition-a <t>] [--tradition-b <t>]
```

Note there is no `--text`: this CLI scopes by tradition pair, edge type and
confidence, not by text. Per-text scoping is available through the review web
app, which is what the `guru-review-edges` skill drives.

Or the review web app, which the `guru-review-edges` skill drives. Same
criteria either way.

Queue `accept` (as `verified` or `proposed`), `reclassify`, `reject`, `skip`.
Prefer reclassifying to `surface_only` or `unrelated` over a bare reject — it
carries information into the audit trail that a reject does not.

## Output

Queued decisions. The live `edges` table does not change until the user drains
the queue.

## Gate

No `pending` staged edges remain for the text.

## Failure modes

**Accepting shared topic as shared move.** Two mystical texts both using
"light" is not a parallel. The bar is the same conceptual claim, or opposite
stances on the same question. Justifications reading "both passages
discuss/explore" an abstract noun are almost always surface.

**Treating `CONTRASTS` as "these disagree".** Opposite stances on *different*
questions is not a contrast; it is two unrelated passages.

**Filtering by `max_confidence` through the API.** That parameter does not
exist. Filter client-side.

**Over-claiming the tier.** Retrieval hedges on `verified` versus `proposed`,
so an honest `proposed` is more useful downstream than an optimistic
`verified`.

**Known-noisy pairings accepted on their justification.** Diamond Sutra ↔ Yasna
Gathas; Pythagorean *Golden Verses* paired with self-will surrender; anything
paired with `egyptian-book-of-the-dead-index` chunks labelled `Chapter — C`.

## Provenance

Rubric, known-real and known-noisy clusters extracted from the
`guru-review-edges` skill so they live in the repository. The skill remains the
Claude Code adapter.
