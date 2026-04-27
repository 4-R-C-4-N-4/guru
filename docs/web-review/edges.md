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

**Decision:** extend the existing `review_actions` table — same drain, same apply transaction, same offline-retry queue, unified audit trail. The schema cost is two new columns + a CHECK. **Plus a column rename** (covered as a prerequisite ticket — see §11) so the column that used to be `staged_tag_id` becomes `target_id`, since under polymorphism it points at either `staged_tags.id` *or* `staged_edges.id`.

> `review_actions` is the web tool's local queue table — the staging buffer between phone tap and live `edges` write. It is **not** part of the corpus pipeline (chunk → embed → tag → propose_edges → export). Renaming its columns has zero impact on `scripts/propose_edges.py`, `scripts/embed_corpus.py`, `scripts/tag_concepts.py`, or `scripts/export.py`. Those scripts have zero references to `review_actions`. Verified via grep before this design.

### Why the rename is its own ticket

In SQLite, dropping a FK constraint requires the full table-recreate dance (SQLite has no `ALTER TABLE DROP CONSTRAINT`). The polymorphism we want for edges (`target_id` pointing at either staged_tags or staged_edges) means dropping the existing FK to `staged_tags(id)`. That's the table-recreate.

But there are two separable changes in flight: **(a) cosmetic column rename**, **(b) drop FK + add target_table + add reclassify_to**. Doing them as one migration is harder to validate than doing them sequentially. The standalone rename is just `ALTER TABLE … RENAME COLUMN`, and SQLite 3.25+ updates the dependent partial index automatically — trivial to verify. The polymorphism migration then lands as a focused second step that adds columns + recreates the table without the FK + sets up the new CHECK.

### Migration #1: column rename (prerequisite, see Ticket 0 in §11)

```sql
BEGIN TRANSACTION;
ALTER TABLE review_actions RENAME COLUMN staged_tag_id TO target_id;
-- SQLite 3.25+ rewrites the partial index `idx_review_actions_unapplied`
-- to reference the new column name automatically. The FK to
-- staged_tags(id) is preserved (still a non-polymorphic FK at this
-- point — polymorphism comes in Migration #2).
COMMIT;
```

### Migration #2: polymorphism (lands with edge-review)

```sql
BEGIN TRANSACTION;

-- SQLite has no DROP CONSTRAINT, so to drop the FK we recreate the table.
CREATE TABLE review_actions_v2 (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id         INTEGER NOT NULL,                 -- polymorphic, no FK
    target_table      TEXT NOT NULL DEFAULT 'staged_tags'
                          CHECK(target_table IN ('staged_tags','staged_edges')),
    action            TEXT NOT NULL CHECK(action IN ('accept','reject','skip','reassign','reclassify')),
    reassign_to       TEXT,                             -- iff staged_tags + reassign
    reclassify_to     TEXT,                             -- iff staged_edges + reclassify
    reviewer          TEXT NOT NULL,
    client_action_id  TEXT NOT NULL UNIQUE,
    applied_at        TEXT,
    error             TEXT,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    CHECK (
      (target_table = 'staged_tags'  AND action IN ('accept','reject','skip','reassign')
                                     AND reclassify_to IS NULL
                                     AND ((action='reassign') = (reassign_to IS NOT NULL)))
      OR
      (target_table = 'staged_edges' AND action IN ('accept','reject','skip','reclassify')
                                     AND reassign_to IS NULL
                                     AND ((action='reclassify') = (reclassify_to IS NOT NULL)))
    )
);
INSERT INTO review_actions_v2(id, target_id, target_table, action, reassign_to,
                              reviewer, client_action_id, applied_at, error, created_at)
SELECT id, target_id, 'staged_tags', action, reassign_to,
       reviewer, client_action_id, applied_at, error, created_at
FROM review_actions;
DROP TABLE review_actions;
ALTER TABLE review_actions_v2 RENAME TO review_actions;
CREATE INDEX idx_review_actions_unapplied
    ON review_actions(target_id) WHERE applied_at IS NULL;
CREATE INDEX idx_review_actions_client_id
    ON review_actions(client_action_id);
COMMIT;
```

The two-migration split lets each step be validated independently against a backup before moving on. Migration #1 is reversible by a second RENAME; Migration #2 takes a labeled snapshot first (matches the existing `~/guru-backups` discipline) and is recoverable from that.

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

## 11. Implementation plan (three tickets — Ticket 0 is the rename prerequisite)

### Ticket 0 — rename `review_actions.staged_tag_id` → `target_id` (prerequisite)

Cosmetic column rename, lands before any edge-review code. Audit-trail-preserving (104 existing rows are renamed in place, no data movement). The FK to `staged_tags(id)` is unchanged at this stage; polymorphism comes in Ticket A-edges via the table-recreate dance described in §5 Migration #2.

**Real edit sites (mapped from grep, not estimated):**

- **DB migration:** `scripts/migrations/v3_002_rename_target_id.sql` (new) — `ALTER TABLE review_actions RENAME COLUMN staged_tag_id TO target_id` inside BEGIN/COMMIT. Take a labeled snapshot at `~/guru-backups/guru-<ts>-pre-target-id-rename.db` before running.

- **Server-side TS column references** (must rename — true SQL column reads):
  - `guru-review/server/src/schema.ts` lines 6, 19 (CREATE TABLE column + partial index column)
  - `guru-review/server/src/db.ts` lines 52, 66, 137 (INSERT, SELECT, JOIN ON `ra.staged_tag_id = st.id`)
  - `guru-review/server/src/routes/apply.ts` line 21 (`COUNT(DISTINCT staged_tag_id)`)
  - `guru-review/server/src/routes/chunks.ts` lines 81, 130, 233 (NOT EXISTS subqueries on `ra.staged_tag_id`)
  - `guru-review/server/src/parity/web_runner.ts` lines 45, 52 (mirror of the above prepared statements)
  - `guru-review/server/src/schema.test.ts` lines 77, 85, 91 (INSERT statement strings)
  - `scripts/cleanup_dupes.sql` line 64 (`AND staged_tag_id IN (…)`)

- **Server-side TS field-name references** (rename for consistency under Option B — these are aliases in SELECT, fields in TS interfaces, and one URL route param):
  - `guru-review/server/src/db.ts` line 129 (`st.id AS staged_tag_id` — alias for queue-with-context view)
  - `guru-review/server/src/apply.ts` lines 10, 60 (`StagedTag` interface field + `q.staged_tag_id` after SELECT)
  - `guru-review/server/src/routes/chunks.ts` lines 45, 122, 194, 213 (TS type field + alias + response field)
  - `guru-review/server/src/routes/tags.ts` lines 35, 36, 38 (`POST /api/tags/:staged_tag_id/action` URL param + `req.params` access + error string)
  - `guru-review/server/src/parity/web_runner.ts` lines 15, 82 (TS interface + fixture access)

- **Web client TS references:**
  - `guru-review/web/src/api/types.ts` lines 2, 42 (`PendingTag` and `QueueRow` interface fields)
  - `guru-review/web/src/state/queue.ts` lines 15, 55, 80 (`PendingPost` interface, enqueue arg, retry-loop URL fetch path)

- **Python references:**
  - `tests/parity/runners/run_cli.py` line 32 (`action["staged_tag_id"]` fixture access — fixture JSON keys flip to `target_id` too)
  - `tests/parity/fixtures/decision_sequence.json` (already has `staged_tag_id` keys per existing fixture; rename in lockstep)
  - `scripts/auto_promote.py` line 50 — **NOT a rename target.** This is `st.id AS staged_tag_id` against the `staged_tags` table for the candidate dict shape. The table being aliased is `staged_tags` itself, not `review_actions`. Keep the alias name as-is (or rename for cosmetic consistency — call your taste). This site is *adjacent* to the rename, not part of it.

- **Test expectations to update:**
  - `tests/test_auto_promote.py` — does not reference `review_actions`, no change.
  - `tests/test_promote_definition.py` — does not reference `review_actions`, no change.
  - `guru-review/server/src/schema.test.ts` — INSERT statement strings change with the column rename.

- **Doc updates:**
  - `docs/web-review/design.md` lines 126, 137, 190, 268, plus the `staged_tag_id` mentions in §3.1 / §4 / §10 (≈5 sites).
  - `docs/web-review/impl.md` lines 117, 207, 214 (≈3 sites).
  - `docs/web-review/edges.md` — flip §12 question 1 from "keep, document" to "renamed in Ticket 0."

**Acceptance criteria:**
- `pytest tests/` green (53 → 53; no test count change since no review_actions tests existed at column granularity).
- Vitest in `guru-review/server/` green (9 → 9).
- Parity harness (`bash tests/parity/orchestrator.sh`) green; the fixture's `staged_tag_id` keys rename to `target_id` and both shadows still produce identical row content.
- Live DB integrity check `ok` after the migration; `SELECT COUNT(*) FROM review_actions` returns the same count as before (104 today).
- `~/guru-backups/guru-<ts>-pre-target-id-rename.db` snapshot exists with manifest before the live migration runs.

### Ticket A-edges — web edge review (this design)

- [ ] **Schema migration** `scripts/migrations/v3_003_edge_review.sql`: implements §5 Migration #2 — table-recreate to drop the FK on `target_id` (now polymorphic), add `target_table` and `reclassify_to` columns, install the polymorphic CHECK constraint, recreate the two indexes. Wrapped in BEGIN/COMMIT; preceded by a labeled snapshot at `~/guru-backups/guru-<ts>-pre-edge-review.db`. Depends on Ticket 0 having renamed the column.
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

1. ~~**Schema column naming.**~~ **Resolved — renamed in Ticket 0 (§11) before this design lands.** SQLite's `ALTER TABLE … RENAME COLUMN` is in-place since 3.25 (2018) and preserves all 104 existing audit-trail rows; the dependent partial index updates automatically. The earlier framing of "invalidates existing rows" was wrong — it's a name change, not a data migration. Full rename (column, JSON field, URL param, TS interfaces) lands as the standalone prerequisite ticket; this design assumes `target_id` everywhere.
2. **`/api/apply/preview` shape.** Does the operator want a unified count (`{queued: 59}`) or a breakdown (`{tags: 47, edges: 12}`)? Recommendation: breakdown, since the apply screen already displays the queue list.
3. **`surface_only` / `unrelated` reclassify path.** §4 routes them through reject (set status='rejected' + DELETE old edge, no new edge). Alternative: add a `discarded` status value that distinguishes "human classified as not-a-real-relation" from "human said no." More signal, more schema churn. Recommendation: route through reject for v1, lift to a discarded status only if downstream wants the distinction.
4. **Auto-promote-edges interaction.** When that ticket ships, where does the seam between auto-promote-edges and the editorial overlay live? Same as for staged_tags: auto-promote writes `proposed`, human review writes `verified` and DELETE-retracts on reject. Editorial overlay is already designed for this; no change needed in this ticket.
5. **Reading load.** Two passages × ~2,500 chars × N edges in a session = a lot of text. The `▸ show full body` collapse is the hedge. Worth tracking how often reviewers expand vs. accept on the preview alone — if it's mostly preview, the truncation is doing real work; if reviewers always expand, default to full body. Defer.
