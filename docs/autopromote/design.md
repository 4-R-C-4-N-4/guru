# auto-promote — design

**Status:** Design — pending implementation
**Scope:** Promote high-confidence LLM-tagged staged_tags into the live `edges` table without per-row human review, mapped onto the existing `verified`/`proposed`/`inferred` tier system.
**Why now:** ~14k pending qwen-pass tags would take ~120 hours of manual review at 30s/tag. Score=3 spot-checks have been "almost all solid"; the existing tier hedge in the web UI already communicates confidence to the RAG consumer. Requiring 100% human review is throwing away the model's strongest signal for no UX benefit.

---

## 1. Tier semantics — `verified` stays behind the human gate

Today's `edges.tier` semantics are mixed:

| tier | currently means |
|---|---|
| `verified` | human-reviewed AND model said score≥2 |
| `proposed` | human-reviewed AND model said score=1 |
| `inferred` | auto-derived structural (e.g. `BELONGS_TO` from chunk metadata) |

The tier field is consumed by the RAG layer and rendered to users via `guru/prompt.py:TIER_LABELS` (✓ Verified / ◇ Proposed / ~ Inferred) and `TIER_HEDGE`.

**Auto-promote will not write `verified`.** That tier is the load-bearing trust signal: a human curator staked their name on it. Even at score=3, the model alone hasn't earned that label — spot-checks aren't full review, and the UI's ✓ should mean what it says. Auto-promote stays one rung down regardless of how confident the model is.

The post-auto-promote tier picture:

| tier | meaning |
|---|---|
| `verified` | **human-reviewed only.** A reviewer accepted the row through `review_tags.py` or the web review tool. Score doesn't matter — what matters is that a human signed off. |
| `proposed` | model-asserted at score≥2 (not yet reviewed) **OR** human-accepted at score=1. "Solid signal, but not human-curated." |
| `inferred` | auto-derived structural (`BELONGS_TO`) **OR** model-asserted at score=1 (only if the operator explicitly opts in). "Weakest signal, treat with most hedge." |

This re-uses the existing tier set rather than adding a fourth. Three tiers are already in the schema, the UI, and operator muscle memory; multiplying them solves nothing — and the existing tier names already mean what we want them to mean *if* `verified` retains its human-gate semantics.

A side benefit: if a future audit wants to know "what edges has a human looked at?", the answer is `WHERE tier = 'verified'`. That query stops being meaningful the moment auto-promote starts writing `verified`.

---

## 2. CLI shape

`scripts/auto_promote.py`

```
auto_promote.py [--score N] [--model M] [--dry-run | --apply] [--db PATH]
```

| flag | default | meaning |
|---|---|---|
| `--score` | `3` | floor — promote rows with `score >= --score`. `--score 3` promotes only score=3 rows. `--score 2` promotes score=2 and score=3. `--score 1` includes all. |
| `--model` | `Qwen3.5-27B-UD-Q4_K_XL.gguf` | provenance filter — only promote rows tagged by this model. Excludes Carnice-9b's known-noisier early run by default. |
| `--dry-run` | implied default | print summary of what would be promoted, no DB writes |
| `--apply` | off | actually run the inserts inside a transaction |
| `--db` | `data/guru.db` | DB path |

**Default behaviour (no flags):** dry-run, `--score 3`, qwen-only, summary printed to stdout. Same defaulting discipline as `cleanup_dupes.sh`. To commit you have to type `--apply`.

---

## 3. Score → tier mapping (per-row)

`--score N` is the *floor* — only rows with `score >= N` are eligible for promotion. The tier each promoted row receives depends on **its own score**, not the floor:

| row score | tier assigned on promotion |
|---|---|
| 3 | `proposed` |
| 2 | `proposed` |
| 1 | `inferred` (only reached if `--score 1` is passed) |

`verified` is intentionally absent — auto-promote never writes that tier (see §1). To get a `verified` edge, a human has to accept the row through the normal review path, where `review_tags.promote_to_expresses` already has `ON CONFLICT DO UPDATE SET tier=excluded.tier` — so a human accept upgrades any prior auto-promoted `proposed` or `inferred` edge to `verified` automatically.

Concretely with the live qwen-pass pool:
- `--score 3` (default) → 2,082 rows → 2,082 new `proposed` edges
- `--score 2` → 9,704 rows → 9,704 new `proposed` edges
- `--score 1` → 14,296 rows → 9,704 `proposed` + 4,592 `inferred` edges

The operator picks the floor based on appetite. The tier rule stays fixed: model-only signal is at most `proposed`.

---

## 4. What does NOT auto-promote

Three categories stay manual:

1. **`is_new_concept = 1` rows.** These propose a new `concept_id` that's not in the live taxonomy. Auto-promoting silently creates a `concept.<id>` node — taxonomy is editorial state and shouldn't grow under autopilot. Filter: `AND is_new_concept = 0`.

2. **Score=1 by default.** Score=1 = "peripherally present" — empirically noisy enough that the operator should opt in deliberately. Reachable via `--score 1` but never the default.

3. **Edges with an existing live row.** If `edges` already has a row at `(chunk_id, concept_node_id, EXPRESSES)`, auto-promote does NOT touch it. Human-reviewed `verified` rows can't be silently downgraded. SQL guard:
   ```sql
   AND NOT EXISTS (
       SELECT 1 FROM edges e
       WHERE e.source_id = st.chunk_id
         AND e.target_id = 'concept.' || st.concept_id
         AND e.type = 'EXPRESSES'
   )
   ```

The third guard also makes `auto_promote.py` re-runnable. A second run sees the edges from the first run and no-ops on them.

---

## 5. SQL shape

```sql
-- Inside BEGIN/COMMIT, behind --apply
INSERT INTO edges (source_id, target_id, type, tier, justification)
SELECT
    st.chunk_id,
    'concept.' || st.concept_id,
    'EXPRESSES',
    CASE st.score
        WHEN 3 THEN 'proposed'
        WHEN 2 THEN 'proposed'
        WHEN 1 THEN 'inferred'
    END AS tier,
    '[auto] ' || COALESCE(st.justification, '')
FROM staged_tags st
WHERE st.status = 'pending'
  AND st.score >= :score_floor
  AND st.is_new_concept = 0
  AND st.model = :model
  AND NOT EXISTS (
      SELECT 1 FROM edges e
      WHERE e.source_id = st.chunk_id
        AND e.target_id = 'concept.' || st.concept_id
        AND e.type = 'EXPRESSES'
  )
ON CONFLICT (source_id, target_id, type) DO NOTHING;
```

Two design choices to call out:

- **`'[auto] ' || justification` prefix.** A small marker in the edge's justification text makes the auto-promoted edges identifiable in retrieval debugging without adding a new column. The text is what the RAG sends to the LLM at query time, so the prefix doubles as a disclosure to the answering LLM that this association is model-asserted not human-curated.
- **`ON CONFLICT DO NOTHING`** (vs the `DO UPDATE SET tier=...` used in `review_tags.promote_to_expresses`). Auto-promote is conservative: never overwrites. The human-review path retains its current upgrade behaviour because it uses a different INSERT statement with `DO UPDATE`.

Concept node creation: auto-promote also needs to ensure target concept nodes exist. Mirror `review_tags.promote_to_expresses`:

```sql
INSERT INTO nodes(id, type, label, definition)
VALUES('concept.' || :concept_id, 'concept', :label, NULL)
ON CONFLICT(id) DO UPDATE SET
  definition = COALESCE(nodes.definition, excluded.definition);
```

`label` follows the same rule as `review_tags`: `concept_id.replace('_',' ').title()`. With `is_new_concept=0` filtered out, every promoted concept_id should already correspond to a taxonomy concept whose node already exists from earlier review activity or from the seeded taxonomy — but the upsert is defensive insurance.

---

## 6. Human review under auto-promote — the editorial overlay

Auto-promote shifts the role of the human review tools (`scripts/review_tags.py` and the web review UI) from **gatekeeper** ("nothing ships until I approve") to **curator** ("auto-promote ships RAG signal; I confirm, retract, or correct it").

All four review actions stay, but two of them gain a new responsibility: cleaning up auto-promoted edges that the curator decides shouldn't have shipped. This is the **companion ticket** for auto-promote (§11); both should land together so the editorial gate is honest from day one.

| action | new behaviour | why this changes |
|---|---|---|
| **Accept** | upsert edge at tier=`verified` regardless of score. ON CONFLICT DO UPDATE upgrades any prior auto-promoted `proposed` / `inferred` row. Status → `accepted`. | Today's `tier = 'verified' if score >= 2 else 'proposed'` rule conflates "human-reviewed" with "model-was-confident." Under auto-promote, those need to be separate axes. Any human accept = `verified`. |
| **Reject** | DELETE the corresponding row from `edges` (if any), then set status='rejected'. | Without the DELETE, a row the curator explicitly rejected stays live in production via auto-promote's prior write. The whole point of `Reject` is retraction. |
| **Reassign** | DELETE the auto-promoted edge for the original (chunk, old_concept) pair, mutate `staged_tags.concept_id`, spawn new pending row for new concept. The new concept's edge will materialize on the next auto-promote run if it qualifies. | Reassign is "wrong concept, here's the right one." Without retracting the wrong edge, the curator's correction leaves a stale association in the live graph. |
| **Skip** | unchanged — no DB write, staged_tag stays pending, any auto-promoted edge stays live. | Skip means "punt for now." Leaving the edge in place is consistent with that. |

Without the DELETE on Reject and Reassign, the human review tool can never remove an edge that auto-promote shouldn't have written, and the curator role degenerates back to "rubber-stamp the auto-promotions you agree with." The whole point of keeping `verified` behind the human gate is so the curator stays load-bearing — that means giving them retraction power, not just upgrade power.

### staged_tags status interactions

Auto-promote does **not** mark rows as `accepted`. `staged_tags.status` stays `pending`. Two reasons:

- The human review path uses `WHERE status='pending'` to find untouched rows. Auto-promote shouldn't move rows out of that queue — the curator might still want to review them (to upgrade `proposed` → `verified`, or to retract via Reject).
- The staged_tags pool remains the canonical "what was generated" record. `WHERE status` queries answer questions about the curator's actions, not auto-promote's. Auto-promote's footprint lives in `edges` (visible via `tier='proposed'` and the `[auto]` justification prefix).

The downside: the web review tool will keep surfacing rows whose `(chunk, concept)` pair already has an auto-promoted edge. The reviewer needs UI signal to know what's already live so they're not flying blind. Two ways to handle this — both downstream of the v1 auto-promote ticket:

- **Filter or annotate the review query** to surface "this row is currently live at tier=X, accept upgrades it / reject retracts it." Cheap, no schema change. Recommended.
- **Introduce `status='auto_promoted'`** as a fourth `staged_tags.status` value. Cleaner audit trail but requires a CHECK constraint update and migration. Defer unless the operator finds the audit worth the schema churn.

Neither is required for v1; both are downstream UX work.

---

## 7. Snapshot + safety discipline

Match the `cleanup_dupes.sh` pattern:

1. `--apply` first takes a labeled snapshot at `~/guru-backups/guru-<ts>-pre-autopromote.db` with `PRAGMA integrity_check`. Refuses to proceed if integrity isn't `ok`.
2. Wraps the migration in `BEGIN TRANSACTION; ... COMMIT;`. SQLite-level transaction means partial failures roll back cleanly.
3. Runs `auto_promote.py` from a thin bash wrapper `scripts/auto_promote.sh` that handles the snapshot, integrity check, and the `--apply` plumbing — same shape as `scripts/cleanup_dupes.sh`. Keeps the SQL/Python side dry-run-pure.

Re-runs after a corpus expansion are safe: the `NOT EXISTS` clause skips edges that already exist, so a second run just adds the new chunks' qualifying staged_tags.

---

## 8. Dry-run summary format

What `--dry-run` prints (the default invocation):

```
auto-promote dry run
  filter:           score >= 3, model = Qwen3.5-27B-UD-Q4_K_XL.gguf, is_new_concept = 0
  candidate rows:   2,082
  already in edges: 0
  would-promote:    2,082
  by tier:          proposed=2,082  inferred=0
  by tradition:     gnosticism=N  Christian Mysticism=N  ...
  sample row:       gnosticism.gospel-of-thomas.001 → concept.gnosis (score=3 → proposed)
                    "[auto] The passage explicitly equates finding interpretation with..."

(no DB writes — re-run with --apply to commit)
(verified tier is reserved for human-reviewed edges; this run will not write any.)
```

The "by tradition" breakdown helps catch obvious skew (e.g. one tradition contributes 80% of promotions — might be over-tagged).

---

## 9. Re-runnability + corpus growth

Operationally, auto_promote.sh becomes a step in the steady-state pipeline:

```
chunk.py → embed_corpus.py → graph_bootstrap.py → tag_concepts.py
   ↓
   ├── (optional) review_tags.py / web review tool — high-stakes review
   └── auto_promote.sh --apply                      — bulk RAG signal
   ↓
   propose_edges.py → review_edges.py → edges
   ↓
   export.py
```

After every fresh tagging run, `auto_promote.sh --apply` brings the new score=3 rows online. Human review continues for the long tail. Both feed the same `edges` table; tier signals which path each came from. Operator decides per-run whether to bump `--score 2` for broader auto-promotion or keep the conservative score=3 default.

---

## 10. Cross-tradition (PARALLELS / CONTRASTS) auto-promote — shipped

Symmetric to per-tag auto-promote, against `staged_edges` (populated by
`propose_edges.py`). Lives in `scripts/auto_promote_edges.py` +
`scripts/auto_promote_edges.sh`.

### Promotion rule

Per row in `staged_edges`:

```
status = 'pending'
AND confidence >= floor                       -- default 0.85
AND edge_type IN ('PARALLELS','CONTRASTS')    -- skip surface_only/unrelated
AND NOT EXISTS (live edges row for same (source, target, type))
                                              ↓
INSERT INTO edges(source_id, target_id, type, tier='proposed',
                  justification='[auto] ' || staged_edges.justification)
ON CONFLICT(source_id, target_id, type) DO NOTHING
```

`tier='verified'` is never written by this script — the verified tier
stays behind the human gate (`scripts/review_edges.py` and the web edge
review path in `guru-review/server/src/apply.ts`).

### What does NOT auto-promote

- `confidence < floor`
- `edge_type IN ('surface_only','unrelated')` — both are valid in
  `staged_edges` but the live `edges.type` CHECK rejects them. The
  filter is defence-in-depth; the constraint would catch them anyway.
- Rows whose corresponding live edge already exists (re-run safety).
- Non-`pending` rows (already accepted/rejected/reclassified by a human).

### No model filter

Unlike the per-tag auto-promote, there is no `--model` filter.
`staged_edges` has no `model` column — `propose_edges.py` writes
`(source_chunk, target_chunk, edge_type, confidence, justification)`
only. If model attribution becomes useful, it's a schema-add ticket
against `staged_edges` first.

### Editorial overlay — retract on Reject / Reclassify

The human edge-review path (CLI `review_edges.py` + the web tool's
`apply.ts` edge branch) treats Accept / Reject / Reclassify symmetrically
to the per-tag overlay (§6):

- Accept → write `tier='verified'` (regardless of LLM confidence)
- Reject → DELETE the live edge row if it exists
- Reclassify → DELETE the live edge for the original `edge_type`; the
  new edge_type's row will materialise on the next auto-promote run if
  it qualifies

This means an auto-promoted edge at `tier='proposed'` can be retracted
by a human reviewer the same way a per-tag auto-promoted EXPRESSES edge
can. See `tests/parity/fixtures/decision_sequence.json` for the
reject-after-auto-promote case.

### Tests

`tests/test_auto_promote_edges.py` — 15 tests covering confidence
boundary, type filter, status filter, conflict-skip, apply tier=proposed,
never-verified guarantee, idempotency, no-downgrade-on-existing, summary
shape, dry-run discipline.

---

## 11. Implementation plan

Two tickets, intentionally split. Both should land close together — auto-promote without the companion leaves the human gate unable to retract anything, which is the wrong shipping order.

### Ticket A — auto-promote tool

- [ ] `scripts/auto_promote.py` — Python with argparse (`--score`, `--model`, `--apply`, `--db`)
- [ ] `scripts/auto_promote.sh` — bash wrapper for snapshot + apply (mirrors `cleanup_dupes.sh`)
- [ ] `tests/test_auto_promote.py` — unit tests against in-memory DB:
  - default `--score 3` promotes only score=3
  - `--score 2` promotes score=2+3 with correct tier mapping per row (both land at `proposed`)
  - `--score 1` includes score=1 rows at tier=`inferred`
  - `is_new_concept=1` rows are skipped
  - non-default model rows are skipped
  - existing live edge is NOT downgraded (re-run safety via `ON CONFLICT DO NOTHING`)
  - `[auto]` prefix lands on the justification
  - dry-run produces summary, no writes
- [ ] One real-DB sanity run via `--dry-run` to confirm count matches the design's prediction (~2,082 score=3 rows post-cleanup)
- [ ] No changes to `schema/corpus-schema.sql` — auto-promote is purely additive content into `edges`. Schema-drift CI stays green; export.py picks up the new edges automatically; `corpus_metadata.corpus_version` increments naturally on next export.

**Acceptance:** `--apply` writes ~2k EXPRESSES rows at tier=`proposed` to `data/guru.db::edges`, no row downgrades a pre-existing edge, `--dry-run` is the default with a numeric summary, `pytest` + parity harness stay green.

### Ticket B — human review path becomes the editorial overlay (companion to A)

This is **Option B** scope: rework the review tools so Accept/Reject/Reassign honestly act on the live graph. Without this, the human gate degenerates to rubber-stamp.

- [ ] **Accept path — drop the score predicate.** `scripts/review_tags.py:promote_to_expresses` currently writes `tier = 'verified' if score >= 2 else 'proposed'`. Change to unconditional `tier = 'verified'`. The whole point of the human gate is that *the human signed off*; the model's score is upstream signal that's already encoded elsewhere. Same change in the web tool's `guru-review/server/src/apply.ts` accept branch.
- [ ] **Reject path — DELETE the auto-promoted edge.** `scripts/review_tags.py` reject branch currently only updates `staged_tags.status='rejected'`. Add: `DELETE FROM edges WHERE source_id=? AND target_id='concept.'||? AND type='EXPRESSES'` for the rejected row's (chunk_id, concept_id). Same change in `apply.ts` reject branch.
- [ ] **Reassign path — DELETE the original-concept edge.** Before the existing `UPDATE staged_tags SET concept_id=...` and the spawn of the new pending row, run the same DELETE for the (chunk_id, *original* concept_id). The new concept's edge will materialize on the next auto-promote run if the spawned row qualifies. Same change in `apply.ts` reassign branch.
- [ ] **db.ts prepared statements** — add `deleteExpressesEdge` to the rw allowlist in `guru-review/server/src/db.ts`. Wire into reject and reassign branches in `apply.ts`. Mirror in `web_runner.ts` so the parity harness covers it.
- [ ] **Tests:**
  - `tests/test_promote_definition.py`: update tier assertions for the score=1-accept case (was `proposed`, now `verified`).
  - `tests/test_promote_definition.py` (or new file): add cases for "Reject removes a pre-existing edge", "Reassign removes the original-concept edge but not other edges on the same chunk".
  - Web side: `guru-review/server/src/schema.test.ts` and `apply` integration coverage for the same scenarios.
- [ ] **Parity harness:** extend `tests/parity/fixtures/decision_sequence.json` with two new cases: (1) reject-after-auto-promote (verifies CLI and web both DELETE the same edge), (2) reassign-after-auto-promote (verifies both DELETE the original-concept edge symmetrically). The seed.sql may need a pre-existing auto-promoted edge in the fixture to be retracted.
- [ ] No `schema/corpus-schema.sql` change — this ticket is behaviour-only on existing tables.

**Acceptance:** any human Accept writes `tier='verified'`. Reject + Reassign DELETE the corresponding edges in both CLI and web paths. Parity harness asserts equivalence on the new retraction cases. Existing tests continue to pass with updated tier assertions.
