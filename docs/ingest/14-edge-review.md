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

The live table shows what this has already done — 11,000 verified PARALLELS
against 41 proposed. `proposed` is meaningful for `EXPRESSES`, where
`auto_promote` writes it (27,127 verified / 11,057 proposed), and vestigial
everywhere a human is the only writer.

**Rejecting a pair that already has a live edge.** `reject` *and* `reclassify`
both call `deleteEdge` on the old type unconditionally, so either one silently
destroys an edge someone already promoted. Nothing raises.

The `guru-review-edges` skill states this as "always skip `confidence >= 0.90`",
which is a proxy for "already auto-promoted at the 0.9 floor". Prefer the
direct check, because the proxy is wrong in both directions — it spares a live
0.85 edge nothing, and on a text `auto_promote_edges` never ran against it
skips reviewable rows for no reason:

```sh
sqlite3 data/guru.db "
  SELECT se.id FROM staged_edges se
  WHERE se.status='pending' AND NOT EXISTS (
    SELECT 1 FROM edges e WHERE e.source_id=se.source_chunk
      AND e.target_id=se.target_chunk AND e.type=se.edge_type);"
```

`scripts/validate_queue.py` reports the same thing as a WARN after the fact.

**Filtering by `max_confidence` through the API.** That parameter does not
exist. Filter client-side.

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
