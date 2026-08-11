# 14 — edge-review

**Kind:** gate · **Contract:** [`prompts/ingest/edge-review.md`](../../prompts/ingest/edge-review.md)

Curate the staged edges. Queue decisions; never apply them.

## Precondition

`staged_edges` rows exist for the text (node 13).

Survey the pool before starting — the shape of it decides how to batch:

```sh
sqlite3 data/guru.db "
  SELECT printf('%.2f', confidence) AS conf, edge_type, COUNT(*)
  FROM staged_edges WHERE status='pending'
  GROUP BY confidence, edge_type ORDER BY confidence DESC;"
```

Mistral quantizes confidence to {0.95, 0.90, 0.85, 0.80, 0.75}; 0.85 is
normally the bulk. Confidence predicts nothing well enough to skip a reading —
it decides order, not verdict.

## Action

```sh
python3 scripts/review_edges.py [--min-confidence 0.7] [--edge-type PARALLELS]
                                [--tradition-a <t>] [--tradition-b <t>]
```

Note there is no `--text`: this CLI scopes by tradition pair, edge type and
confidence, not by text. Per-text scoping is available through the review web
app, which is what the `guru-review-edges` skill drives. Same criteria either
way.

Through the web app, one batch is a `GET` and a `POST` per verdict:

```sh
curl -s "http://localhost:7314/api/edges?edge_type=PARALLELS&min_confidence=0.85&limit=20"

curl -s -X POST "http://localhost:7314/api/edges/<ID>/action" \
  -H "Content-Type: application/json" \
  -d '{"action":"reclassify","reclassify_to":"surface_only",
       "client_action_id":"agent-claude-edge-<ID>-<TS>","reviewer":"agent-claude"}'
```

`GET /api/edges` returns both chunk bodies inline, so a batch needs no extra
reads. Params: `edge_type`, `min_confidence`, `tradition_a` / `tradition_b`
(symmetric — either side matches), `limit` (max 20), `cursor`. The response
carries `pending_edges_in_filter` and `next_cursor`.

Four verdicts:

| verdict | when |
|---|---|
| `accept` | Both chunks make the same conceptual claim (PARALLELS), or take opposite stances on the *same* question (CONTRASTS). |
| `reclassify` → `PARALLELS`/`CONTRASTS` | Right relationship, wrong type. |
| `reclassify` → `surface_only` | Genre or vocabulary similarity, no shared move. |
| `reclassify` → `unrelated` | Not about the same thing; includes corpus-quality cases (mis-shelved chunks, footnotes, contents pages). |
| `reject` | Reserve for what you cannot classify. Prefer `surface_only` / `unrelated` — they carry information into the audit trail that a bare reject does not. |

`reviewer` is always `agent-claude` for agent passes, so the whole queue stays
filterable and wipeable with one predicate.

## Output

Queued decisions. The live `edges` table does not change until the user drains
the queue.

## Gate

No `pending` staged edges remain for the text. Validate before handing over:

```sh
python3 scripts/validate_queue.py
```

`POST /api/apply` drains every queued action in a single transaction, and
`/api/apply/preview` only counts them, so one bad row discards the pass.

## Failure modes

**Accepting shared topic as shared move.** Two mystical texts both using
"light" is not a parallel. The bar is the same conceptual claim, or opposite
stances on the same question. Justifications reading "both passages
discuss/explore" an abstract noun are almost always surface.

**Treating `CONTRASTS` as "these disagree".** Opposite stances on *different*
questions is not a contrast; it is two unrelated passages.

**Believing there is a tier hedge.** There is not. Both the API and
`review_edges.py` write `tier='verified'` on accept unconditionally — no
interface takes a tier from the reviewer. `guru-web`'s Atlas then shows only
`edge_type='PARALLELS' AND tier='verified'`, so accept means publish. An
interpretive reading has no soft landing: it is `surface_only` or `skip`.

The two-tier design is inert in practice, because `auto_promote` is not part
of this pipeline — every edge and every tag goes through review. The
`proposed` rows that exist are residue from two abandoned episodes, not a
policy:

| type | last `proposed` written | rows |
|---|---|---|
| `EXPRESSES` | 2026-05-26 | 11,057 |
| `PARALLELS` / `CONTRASTS` | 2026-07-03, all in one run | 45 |

Everything written since is `verified` — 11,000 verified PARALLELS against 41
proposed, and every EXPRESSES edge from June onward. A reviewer has never had
a tier to choose, so the column records which *tool* wrote a row and in what
month, not how good anyone judged it.

That has a live cost: `guru-web`'s `retriever.ts` weights `verified` 1.0 and
`proposed` 0.7, so those 11,057 April–May tags are permanently down-ranked
against identical work reviewed later, and the 45 July edges are absent from
the Atlas. Tracked separately; it is not a node 14 decision.

**Rejecting a pair that already has a live edge.** `reject` *and* `reclassify`
both call `deleteEdge` on the old type unconditionally, so either one silently
destroys an edge someone already promoted. Nothing raises.

The `guru-review-edges` skill states this as "always skip `confidence >= 0.90`"
— a proxy for "already auto-promoted at the 0.9 floor", written when that floor
was in use. It no longer is, so the rule now skips reviewable rows to guard
against a tool nobody runs. On yoga-sutras it would have withheld 77 of 696
edges, none of which is live.

Use the direct check instead. It is the thing the proxy was approximating, it
stays correct whatever auto-promote does later, and it also catches a live 0.85
edge, which the confidence rule never did:

```sh
sqlite3 data/guru.db "
  SELECT se.id FROM staged_edges se
  WHERE se.status='pending' AND NOT EXISTS (
    SELECT 1 FROM edges e WHERE e.source_id=se.source_chunk
      AND e.target_id=se.target_chunk AND e.type=se.edge_type);"
```

`scripts/validate_queue.py` reports the same thing as a WARN after the fact.

**Accepting a view the text is about to refute.** The commonest non-obvious
error, and the only one that can publish a *false* claim rather than a weak
one. A chunk that expounds a position at length may be setting it up for
demolition: Ouspensky lays out mechanistic positivism for two pages and closes
"Such is the teaching of positivism"; Plotinus opens "It remains to notice the
theory … *alleged* to interweave everything". Four cases in 696 edges on
yoga-sutras, and the proposer's single `CONTRASTS` in that pass was one of
them — which is the dangerous direction, since a wrong `PARALLELS` overstates
agreement but a wrong `CONTRASTS` invents a disagreement the author disowns.

Read to the end of the chunk before accepting. Tells: "it is said that", "the
theory that", "alleged", "some hold" — and any final sentence that names the
position as a school's.

**Judging a chunk whose content is not the named author's.** Two kinds, both
corpus-quality problems that surface here because node 14 is the first node
that reads bodies adversarially.

*Apparatus* — translator's notes, editorial introductions, contents lists,
plate captions. Verdict is `unrelated`. Twelve chunks in the yoga-sutras pass;
the Rolt Dionysius, Hartmann's Boehme and the *Heroic Enthusiasts*
introduction were the repeat offenders, and one Corpus Hermeticum chunk was
matched on a modern editor's bracketed headnote.

*Quotation chunks* — the chunk is largely another tradition's words quoted
under this tradition's label. `tertium-organum.156` is Ouspensky quoting
Plotinus; `tertium-organum.188` is Ouspensky quoting *The Voice of the
Silence*. These attract proposals at several times the normal rate, because a
chunk containing tradition X's words matches everything X matches. An edge
from one credits the quoting author with the quoted author's claim. Verdict is
`surface_only`, or `unrelated` if the chunk is nothing but quotation.

If a partner chunk appears unusually often in a pass, check whether it is one
of these before checking anything else. Partner saturation is a symptom.

**Treating a shared word as a shared concept.** Two translators, working from
different languages a century apart, can land on the same English word for
unrelated ideas. MacKenna's Plotinus says "The phases present are those which
the nature of body demands" (aspects of soul); Johnston's Patanjali says
perception occurs when vibrations are "in the same phase" (frequency). The
collision exists only in English and nothing in either body supports the pair.
Likewise a shared *count* is not a shared structure: three Gnostic syzygies
(an emanation sequence) against three gunas (a compositional analysis) share
the number and nothing else.

**Losing a good pairing aimed at the wrong chunk.** `reclassify` changes the
edge *type*; it cannot move an endpoint. There is no `reassign` at this node,
so a correct insight proposed against the neighbouring sutra can only be
discarded. Node 11's comparable pass produced six reassigns, so the loss here
is real but unmeasured. Log these in the decision record when you spot them —
that log is the only evidence the gap exists.

**Filtering by `max_confidence` through the API.** That parameter does not
exist. Filter client-side.

**Reading confidence as quality.** It orders a batch and decides nothing. On
yoga-sutras the single 0.95 was right, several 0.85s were right, and the one
proposed `CONTRASTS` — at 0.85, like almost everything else — was wrong.

**Known-noisy pairings accepted on their justification.** Diamond Sutra ↔ Yasna
Gathas; Pythagorean *Golden Verses* paired with self-will surrender; anything
paired with `egyptian-book-of-the-dead-index` chunks labelled `Chapter — C`.

## Provenance

Rubric, known-real and known-noisy clusters extracted from the
`guru-review-edges` skill so they live in the repository. The skill remains the
Claude Code adapter.

Tier finding and the live-edge rule: 2026-08-09, from
`guru-review/server/src/apply.ts`, `scripts/review_edges.py:136`,
`guru-web/src/lib/atlas.ts` and `retriever.ts`.
