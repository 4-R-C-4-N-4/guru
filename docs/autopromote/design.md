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

## 6. staged_tags status — left untouched

Auto-promote does **not** mark rows as `accepted`. `staged_tags.status` stays `pending`. Rationale:

- A future human review pass can still upgrade an auto-promoted `proposed` (or `inferred`) edge by accepting the staged_tag through the normal path. `review_tags.promote_to_expresses` uses `ON CONFLICT DO UPDATE`, so a human accept overwrites the auto-promoted tier with whatever tier the human-review path computes.

  ⚠ **Companion change worth considering:** today `review_tags.promote_to_expresses` writes `tier = 'verified' if score >= 2 else 'proposed'`. Under the new "`verified` = human-reviewed, full stop" semantic, that score check should drop — *any* human accept should write `verified`, because the load-bearing distinction is "did a human sign off?" not "did a human sign off AND was the model also confident?"
  This is a small change (`review_tags.py` line 78 + the equivalent line in the web tool's `apply.ts`) but it's a separate behaviour change from auto-promote and should be its own ticket. Without it, the human-review path can write `proposed` for accepted score=1 rows, which then can't be distinguished from auto-promoted score≥2 rows by tier alone — defeating the audit query "what's been human-reviewed?".
- The staged_tags pool remains the canonical "what's been generated" record. Reviewers can query `WHERE status='pending'` to see what's untouched by humans, regardless of what auto-promote did to `edges`.

The downside: the web review tool will keep surfacing rows whose `(chunk, concept)` pair already has an auto-promoted edge. Two ways to handle this when it becomes annoying:

- **Filter the review query** to exclude rows whose `(chunk, concept)` already has an EXPRESSES edge of any tier. Cheap, no schema change. This is the recommended follow-up if auto-promote ships and reviewer fatigue grows.
- **Introduce `status='auto_promoted'`** as a fourth `staged_tags.status` value. Cleaner audit trail but requires a CHECK constraint update and migration. Defer unless the cleaner audit becomes worth the schema churn.

Neither is required for v1 of auto-promote; both are downstream cleanup.

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

## 10. Future: cross-tradition (PARALLELS / CONTRASTS) auto-promote

Out of scope for this design, but worth flagging the symmetric idea: `propose_edges.py` already attaches an LLM `confidence` float to `staged_edges`. A future `auto_promote_edges.py` could promote rows with `confidence >= 0.85` into `edges` at tier=`proposed` (never `verified` — cross-tradition equivalence is editorially loaded enough that human review should retain the top tier). Defer until the per-tag auto-promote has settled and the operator sees the staging-vs-shipped balance they want.

---

## 11. Implementation checklist

When this lands as a ticket:

- [ ] `scripts/auto_promote.py` — Python with argparse (`--score`, `--model`, `--apply`, `--db`)
- [ ] `scripts/auto_promote.sh` — bash wrapper for snapshot + apply (mirrors `cleanup_dupes.sh`)
- [ ] `tests/test_auto_promote.py` — unit tests against in-memory DB:
  - default `--score 3` promotes only score=3
  - `--score 2` promotes score=2+3 with correct tier mapping per row
  - `is_new_concept=1` rows are skipped
  - non-default model rows are skipped
  - existing live edge is NOT downgraded (re-run safety)
  - `[auto]` prefix lands on the justification
  - dry-run produces summary, no writes
- [ ] One real-DB sanity run via `--dry-run` to confirm count matches the design's prediction (~2,082 score=3 rows post-cleanup)
- [ ] No changes to `schema/corpus-schema.sql` — auto-promote is purely additive content into `edges`. Schema-drift CI stays green; export.py picks up the new edges automatically; `corpus_metadata.corpus_version` increments naturally on next export.
- [ ] **Optional companion ticket** (separate, but should land before/with auto-promote to keep tier semantics clean): update `review_tags.promote_to_expresses` and the web tool's apply.ts so any human accept writes `tier='verified'` (drop the `score >= 2` predicate). Re-aligns `verified` with "human-reviewed, full stop." Parity harness fixture and `test_promote_definition.py` will need their tier-assertion updates in the same change.

Acceptance: `--apply` writes ~2k EXPRESSES rows at tier='proposed' to `data/guru.db::edges`, no row downgrades a pre-existing edge, `--dry-run` is the default with a numeric summary, `pytest` + parity harness stay green.
