# guru-review: edge review extension

**Status:** Design — pending implementation
**Companion to:** [`design.md`](design.md) (Pass B — staged_tags) and [`impl.md`](impl.md). This doc extends the same web tool to handle Pass C (cross-tradition `staged_edges` — PARALLELS / CONTRASTS proposals from `scripts/propose_edges.py`).
**Why now:** `propose_edges.py` is producing rows; the CLI (`scripts/review_edges.py`) is the only review path; bulk review on a phone is the same operational gap that motivated the original web tool. The infrastructure (snapshot, prepared statements, apply transaction, parity harness, PWA shell, retry queue) is already in place — this is a parallel route on top.

---

## 1. Scope

### In
- Replace `scripts/review_edges.py` for everyday review with a phone-first UI.
- Per-device review attribution and offline-resilient queueing — same shape as the tag-review path.
- Editorial-overlay semantics: accept = `verified` regardless of LLM confidence, reject + reclassify retract live edges that auto-promote-edges (future, see §10) might write.

### Out
- Auto-promote for `staged_edges` itself. That belongs to the future `auto_promote_edges.py` work, not this ticket — flagged in `docs/autopromote/design.md` §10. The web tool should be ready for it (tier semantics, retraction paths) but this design only ships the human-review side.
- New filter dimensions beyond what the CLI already supports (`edge_type`, `min_confidence`, `tradition_a/b`).
- Diff/comparison highlighting between the two passages. Worth doing eventually; not v1.

---

## 2. The two surfaces are different enough to warrant their own routes

`staged_tags` review is *one chunk × N candidate concepts*. `staged_edges` review is *one edge × two chunks*. They share zero render code and only ~half the data shape:

| | staged_tags (Pass B) | staged_edges (Pass C) |
|---|---|---|
| primary unit | chunk | edge (chunk-pair) |
| confidence signal | `score INTEGER 0-3` | `confidence REAL 0.0-1.0` |
| LLM-asserted classification | concept_id | edge_type ∈ {PARALLELS, CONTRASTS, surface_only, unrelated} |
| accept upgradeable to | EXPRESSES edge | PARALLELS or CONTRASTS edge |
| reassign / classify | reassign concept_id, spawn new pending row | reclassify edge_type in-place, promote |
| filters | tradition / text / concept / min_score | edge_type / min_confidence / tradition_a / tradition_b |

The right architectural call is **a parallel route stack** (`/edges` deck, `/api/edges*`) rather than overloading the existing tag routes. Same Express server, same DB, same review_actions queue (extended), same apply transaction (extended). Distinct UI screens.

---

## 3. Tier semantics under the editorial overlay (re-stated)

Same rule as `staged_tags` per `design.md` §1 and `docs/autopromote/design.md` §1:

| tier | meaning |
|---|---|
| `verified` | **human-reviewed only.** Reviewer accepted the edge through the web tool or `review_edges.py`. The LLM's confidence float doesn't matter; what matters is that a human signed off. |
| `proposed` | model-asserted (auto-promoted, future work) **OR** any future "low-confidence-human-accept" affordance. Currently never written by this design. |
| `inferred` | structural (`BELONGS_TO`) or future low-confidence auto-promote. Not produced by edge review. |

**Companion change to `scripts/review_edges.py`** (matches the staged_tags companion landed in `todo:f21b6baf` / `todo:7fd43fe4`):

- The CLI today has **two accept keys**: `[a]` writes `verified`, `[p]` writes `proposed`. That predates the editorial-overlay framing. Under the new semantic, any human accept = `verified`. Drop `[p]`. The reviewer's signal is "I accept this," not "I accept it at this confidence level" — the LLM's `confidence` float already carries strength signal and travels through `staged_edges.confidence` for downstream use.
- This is part of the implementation plan (§11 Ticket B-edges) and should land in the same change as the web side, for the same reason the original companion shipped together: keeps CLI and web symmetric, keeps the parity harness honest.

---

## 4. Review actions and their DB effects

Four actions, same shape as `staged_tags` review but operating on `staged_edges`:

| action | DB effects |
|---|---|
| **Accept** | Upsert `(source, target, edge_type)` into `edges` at tier=`verified` with `staged_edges.justification`. Set `staged_edges.status='accepted'`, `tier='verified'`, `reviewed_by`, `reviewed_at`. ON CONFLICT DO UPDATE — upgrades any prior auto-promoted `proposed`/`inferred` edge once that pipeline exists. |
| **Reject** | DELETE the live edge if any (`source_id, target_id, type`); set `staged_edges.status='rejected'`, `reviewed_by`, `reviewed_at`. Same retraction discipline as reject in the tag tool — without DELETE, an auto-promoted edge for a row the curator rejected would stay live. |
| **Reclassify** | Mutate `staged_edges.edge_type` to the chosen replacement. **If new type is PARALLELS or CONTRASTS:** DELETE the old-type live edge if any, upsert the new-type edge at tier=`verified`, set `status='reclassified'`. **If new type is `surface_only` or `unrelated`:** DELETE the old-type live edge if any, set `status='rejected'` (treat as a typed reject — no live edge can have those types per the `edges.type` CHECK). This is the editorial-overlay fix for a CLI bug where reclassify-to-surface_only would promote a row that fails the CHECK constraint at insert time. |
| **Skip** | No DB write, no status change, the row stays pending. Same as tag review skip. |

Note the asymmetry with `staged_tags` review:
- Tag review's "Reassign" mutates `concept_id` and **spawns a new pending row** for the corrected concept (the user might want to review it later).
- Edge review's "Reclassify" mutates `edge_type` **in place** and (if appropriate) promotes — the row is now resolved. There's no analogous "spawn a new pending row" semantic because edges aren't tag-like; the LLM picked a relationship and the human is fixing the type, not recommending re-evaluation.

---

## 5. Queue + apply: extend, don't fork

Two questions: where do queued edge actions live, and where does the apply transaction live?

**Decision:** extend the existing `review_actions` table with a target column, rather than create a new `review_edge_actions` table. Rationale:
- Keeps the apply transaction single — one drain, one snapshot scope, one parity-harness fixture pattern, one offline-retry queue.
- Keeps the audit trail unified: `WHERE reviewer='ivy-phone' AND created_at >= date('now')` answers "what did I review today?" across both surfaces.
- The schema cost is minor (one nullable column + a CHECK).

### Schema change (additive, idempotent)

```sql
ALTER TABLE review_actions ADD COLUMN target_table TEXT NOT NULL DEFAULT 'staged_tags';
-- NULL semantics: existing rows are all staged_tags actions; default
-- backfills them. New rows must declare 'staged_tags' or 'staged_edges'.

-- The existing CHECK already covers actions for the staged_tags case
-- (accept/reject/skip/reassign + reassign_to). Edge actions need a
-- different value set:
ALTER TABLE review_actions ADD COLUMN reclassify_to TEXT;
-- Used iff target_table='staged_edges' AND action='reclassify'.

-- A combined CHECK keeps the table coherent without a forking schema.
-- (Conceptual; the actual DDL goes in scripts/migrations/v3_002_edge_review.sql:)
--
--   CHECK (
--     (target_table = 'staged_tags'  AND action IN ('accept','reject','skip','reassign')
--                                    AND reclassify_to IS NULL
--                                    AND ((action='reassign') = (reassign_to IS NOT NULL)))
--     OR
--     (target_table = 'staged_edges' AND action IN ('accept','reject','skip','reclassify')
--                                    AND reassign_to IS NULL
--                                    AND ((action='reclassify') = (reclassify_to IS NOT NULL)))
--   )
```

`staged_tag_id` becomes a polymorphic FK (the column name stays for backwards compatibility with existing rows; in the staged_edges case the value points at `staged_edges.id`). Cleaner alternatives are nameable but cost more migration churn. The pragmatic call is to keep the column name and document the polymorphism in `db.ts` and the schema fingerprint comment.

### Apply transaction

Extend `apply.ts` to dispatch on `target_table`:

```ts
for (const q of queued) {
  if (q.target_table === 'staged_tags') {
    // existing tag dispatch (Accept/Reject/Skip/Reassign), unchanged
  } else if (q.target_table === 'staged_edges') {
    applyEdgeAction(rw, stmts, q);   // new branch — see §6
  }
}
```

The retraction discipline (`deleteExpressesEdge` for tags) gets a sibling helper — we'll need a parallel `deleteRelationEdge(source, target, type)` that DELETEs by `(source_id, target_id, type)` for PARALLELS/CONTRASTS retractions. Generalizing the existing one is fine: rename to `deleteEdge(source, target, type)` and pass the type explicitly at call sites. Small refactor.

---

## 6. New API endpoints

Mirror the `/api/tags*` shape:

| method | path | purpose |
|---|---|---|
| `GET` | `/api/edges` | Paginated pending `staged_edges`. Filters: `edge_type`, `min_confidence`, `tradition_a`, `tradition_b`, `cursor`, `limit`. **Excludes any edge with an unapplied review_action.** Each row enriched with both chunks' bodies + citations. |
| `GET` | `/api/edges/:id` | Single edge with full context (used by deep-link / share). |
| `POST` | `/api/edges/:staged_edge_id/action` | Body: `{ action, reclassify_to?, client_action_id, reviewer }`. Idempotent on `client_action_id`. Validation enforces reclassify_to ∈ {PARALLELS, CONTRASTS, surface_only, unrelated} when action='reclassify', null otherwise. |

The `/api/queue`, `/api/queue/:cid` (DELETE), and `/api/apply` endpoints stay single — they operate on the unified `review_actions` queue regardless of `target_table`. The queue context view will need a small extension to render edge rows differently (two chunks instead of one) — covered in §7.

`/api/apply/preview` likewise stays single but its summary breakdown grows a `by_target_table` field so the operator sees `{ staged_tags: 47, staged_edges: 12 }` before applying.

---

## 7. UI: two-passage card

The center-of-gravity UI element is the **edge card** — analogous to the chunk card in the tag review, but composed of two chunk excerpts and an edge classification banner.

```
┌────────────────────────────────────────────────────┐
│  47 queued · 312 pending edges      [Apply 47]     │
├────────────────────────────────────────────────────┤
│  ════════════════════════════════════════════════  │
│  EDGE:    PARALLELS                  conf 0.87 ◇   │
│  LLM:     Both passages assert that direct          │
│           knowledge of divine reality bypasses      │
│           ritual mediation.                         │
│  ════════════════════════════════════════════════  │
│                                                    │
│  ┌─ A ─────────────────────────────────────────┐  │
│  │ Gnosticism · Gospel of Thomas · Logion 77   │  │
│  │ ─────────────────────────────────────────── │  │
│  │ It is I who am the light which is above     │  │
│  │ them all. It is I who am the all. From me   │  │
│  │ did the all come forth, and unto me did     │  │
│  │ the all extend. Split a piece of wood…      │  │
│  │ ▸ show full body                             │  │
│  └──────────────────────────────────────────────┘  │
│                                                    │
│  ┌─ B ─────────────────────────────────────────┐  │
│  │ Neoplatonism · Enneads · Treatise V.1.7     │  │
│  │ ─────────────────────────────────────────── │  │
│  │ The One is not "all" in the sense of all    │  │
│  │ things, but as the source from which all    │  │
│  │ derives — the all-yet-prior-to-all…         │  │
│  │ ▸ show full body                             │  │
│  └──────────────────────────────────────────────┘  │
│                                                    │
├────────────────────────────────────────────────────┤
│  [ Reject ]   [ Skip ]   [ Accept ]                │
│              [ Reclassify… ]                       │
└────────────────────────────────────────────────────┘
```

Format rules:

- **Two stacked passages on portrait phone**, side-by-side on tablet/desktop (Tailwind `md:grid-cols-2`). Stacking is the right call on phones — small horizontal scroll on each side defeats the read.
- **Edge classification banner at the top** — edge_type as a colored pill (PARALLELS = blue, CONTRASTS = amber, surface_only = zinc, unrelated = zinc), confidence as a small `0.87` decimal. The LLM justification is the prose underneath, never truncated.
- Each passage shows its full citation (tradition · text_name · section). Body collapsed to first ~600 chars with `▸ show full body` toggle — same affordance as `ChunkCard.tsx` but split per passage.
- **No chunk-level "Accept Remaining" / batch ops.** Edge review is per-edge; there's no natural batch unit (no "edges-grouped-by-something" axis the way tags are grouped by chunk).

Action row: `Reject` / `Skip` / `Accept` (single Accept — see §3 on dropping the two-tier `[a]`/`[p]` split). `Reclassify…` opens a sheet that lists the four edge types with each one's definition, lets the human pick a different `edge_type` than what the LLM proposed.

The reclassify sheet should warn when the user picks `surface_only` or `unrelated`: "this will mark the edge rejected — there's no `surface_only` relation in the live graph." So the curator's intent is explicit.

---

## 8. Filter sheet

| filter | type | URL param |
|---|---|---|
| edge type | chip selector: any / PARALLELS / CONTRASTS | `edge_type` |
| min confidence | range slider 0.00–1.00, default 0.0 | `min_confidence` |
| tradition A | chip selector populated from `/api/traditions` | `tradition_a` |
| tradition B | chip selector populated from `/api/traditions` | `tradition_b` |

Tradition filters are symmetric in the SQL: an edge matches when `tradition_a` is the source's tradition OR target's, same for `tradition_b`. Mirror the CLI's filter semantic.

The min-confidence slider has the most operational value at scale — when a propose_edges run produces a few thousand staged edges with confidences spread between 0.50 and 0.95, dialing in `min_confidence=0.80` lets the reviewer triage the obvious wins first.

---

## 9. Parity harness extensions

The harness in `tests/parity/` needs to assert that CLI's `review_edges.py` and the web's edge-action apply branch produce identical row content for the same fixture decisions. The mechanics mirror the existing tag-review harness (per `tests/parity/README.md` and the v3 Phase 1 / autopromote work):

- `tests/parity/fixtures/seed.sql` already has 3 chunks and a few staged_tags. Add 3 `staged_edges` rows covering each action branch:
  - one PARALLELS edge to be accepted at verified
  - one CONTRASTS edge to be rejected (with a pre-seeded live edge that must be DELETEd)
  - one PARALLELS edge to be reclassified to CONTRASTS (verifies the old PARALLELS edge is deleted, new CONTRASTS edge is upserted, status='reclassified')
- `tests/parity/fixtures/decision_sequence.json` gains entries with `target_table: 'staged_edges'` and the new action set.
- `tests/parity/runners/run_cli.py` gets a sibling `apply_edge_action()` that imports from `review_edges.py` (after the helpers are extracted into testable functions parallel to `reject_tag` / `reassign_tag`).
- `compare.py` already covers `edges` row-content; just needs the new fixture decisions to exercise that comparison on the edge-review path.

---

## 10. Future: auto-promote-edges

`docs/autopromote/design.md` §10 already flags the symmetric idea: a future `scripts/auto_promote_edges.py` that promotes high-confidence `staged_edges` to live edges at tier=`proposed` (never `verified` — the editorial overlay rule applies).

This design is forward-compatible with that:
- The Reject DELETE branch already retracts whatever's live — including a future auto-promoted `proposed` edge.
- The Reclassify branch DELETEs the original-type edge before promoting the new one — the same retract-then-promote dance.
- The tier='verified' upsert on Accept upgrades any prior auto-promoted `proposed` edge correctly via ON CONFLICT DO UPDATE.

So the editorial overlay is in place from day one even though auto-promote-edges is a separate ticket. When that ticket lands, the human gate is already honest.

---

## 11. Implementation plan (two tickets, B-edges before A-edges if A-edges ever ships)

### Ticket A-edges — web edge review (this design)

- [ ] **Schema migration** `scripts/migrations/v3_002_edge_review.sql`: add `target_table` (default 'staged_tags') and `reclassify_to` columns to `review_actions`, plus the polymorphic CHECK constraint. Idempotent.
- [ ] **`scripts/review_edges.py`** — extract reusable helpers: `accept_edge(conn, row)`, `reject_edge(conn, row)`, `reclassify_edge(conn, row, new_type)` matching the shape of `reject_tag`/`reassign_tag` introduced in `todo:f21b6baf`. The interactive loop calls them. Drop the `[p]` accept-at-proposed key per §3 — Accept always writes verified. The DELETE-on-reject and DELETE-on-reclassify discipline lands here and mirrors the staged_tags companion ticket.
- [ ] **`guru-review/server/src/db.ts`** — add prepared statements for the edge dispatch (`insertReviewActionEdge`, `selectStagedEdge`, `deleteEdge` (generic, replaces `deleteExpressesEdge`), `upsertEdge` (generic for any type, replaces `insertOrUpdateEdge`), `updateStagedEdgeStatus`, `updateStagedEdgeType`). Update `web_runner.ts` mirror.
- [ ] **`guru-review/server/src/apply.ts`** — dispatch on `target_table`. The existing tag branch stays untouched; new edge branch implements Accept / Reject / Reclassify / Skip per §4.
- [ ] **`guru-review/server/src/routes/edges.ts`** — three routes: `GET /api/edges` (keyset paginated, filtered, enriched with both chunks' bodies + citations), `GET /api/edges/:id`, `POST /api/edges/:id/action`. Reuse the existing `/api/queue` and `/api/apply` flow.
- [ ] **`guru-review/server/src/routes/queue.ts`** — extend the queue render so rows with `target_table='staged_edges'` ship enough context to render the queue card (both chunks' citations, edge_type, reclassify_to). Same `DELETE /api/queue/:cid` semantics.
- [ ] **Web UI**: `EdgeCard.tsx`, `EdgeActions.tsx`, `EdgeReclassifySheet.tsx`, `screens/EdgeDeck.tsx`, `screens/EdgeFilter.tsx`. Shared with tag review: header bar, stats drawer, retry queue, apply screen (group `by_target_table` in the apply preview).
- [ ] **Parity harness extension** per §9: 3 new fixture rows, decision sequences, `apply_edge_action` in `run_cli.py`, mirrored in `web_runner.ts`.

**Acceptance:** CLI and web edge-review produce identical row content (`staged_edges` status + `edges` upserts/deletes) for the parity fixture. PWA loads the edge deck on phone, shows two-passage layout correctly stacked. Apply screen surfaces both queue types in one batch.

### Ticket B-edges — `review_edges.py` companion (drops `[p]`)

- [ ] Drop the `[p]` accept-at-proposed branch from `review_edges.py`. Update help text. Any human accept = `verified`.
- [ ] Update fixtures and any test that exercised the dropped key.

This is small enough to fold into Ticket A-edges as a sub-step rather than its own ticket — mention it for clarity, decide at planning time. Same shape as the staged_tags companion change in `todo:f21b6baf`.

---

## 12. Open questions (decide before implementation, not at planning)

1. **Schema column naming.** Keep `staged_tag_id` as a polymorphic FK column (with comment) for migration cheapness, vs. rename to `target_id` (cleaner but invalidates 18+ months of existing review_actions rows). Recommendation: keep, document.
2. **`/api/apply/preview` shape.** Does the operator want a unified count (`{queued: 59}`) or a breakdown (`{tags: 47, edges: 12}`)? Recommendation: breakdown, since the apply screen already displays the queue list.
3. **`surface_only` / `unrelated` reclassify path.** §4 routes them through reject (set status='rejected' + DELETE old edge, no new edge). Alternative: add a `discarded` status value that distinguishes "human classified as not-a-real-relation" from "human said no." More signal, more schema churn. Recommendation: route through reject for v1, lift to a discarded status only if downstream wants the distinction.
4. **Auto-promote-edges interaction.** When that ticket ships, where does the seam between auto-promote-edges and the editorial overlay live? Same as for staged_tags: auto-promote writes `proposed`, human review writes `verified` and DELETE-retracts on reject. Editorial overlay is already designed for this; no change needed in this ticket.
5. **Reading load.** Two passages × ~2,500 chars × N edges in a session = a lot of text. The `▸ show full body` collapse is the hedge. Worth tracking how often reviewers expand vs. accept on the preview alone — if it's mostly preview, the truncation is doing real work; if reviewers always expand, default to full body. Defer.
