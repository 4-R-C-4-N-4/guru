# guru-review: Implementation Plan

**Source of truth:** `docs/web-review/design.md`
**Status:** Pending — pre-flight done, P1 not yet started
**Tracking:** Each phase below maps to a `todo` ticket on branch `todo/<id>`. Parent phases aggregate children via `todo plan`. Done contract per ticket follows the project default (commit + test/note for bugs, commit + note for features/chores).

This doc is the bridge between the design spec and the ticket store. Read `design.md` first; this plan won't make sense without it.

---

## Pre-flight

| Item | Status | Reference |
|---|---|---|
| DB backup `~/guru-backups/guru-20260425-142226-pre-web-review.db` | done | manifest at `~/guru-backups/guru-pre-web-review-manifest.txt` |
| Canary counts (15371 / 2548 / 2600) recorded | done | manifest |
| `data/guru.db` integrity check `ok` | done | manifest |
| Branch off main: `todo/web-review-feature` (parent ticket) | pending | P0 below |
| `.gitignore` adds `guru-review/**/node_modules/`, `guru-review/**/dist/`, `data/guru-shadow*` | pending | P1 |

---

## Phase map

```
P0  Parent ticket + branch                [feature, parent]
├── P1  Repo skeleton                     [chore]
├── P2  Schema + db handles               [feature]
├── P3  Startup snapshot                  [feature]
├── P4  Read endpoints                    [feature, parent → P4a–P4h]
├── P5  Write endpoint                    [feature]
├── P6  Queue + undo endpoints            [feature]
├── P7  Apply transaction + parity gate   [feature, parent → P7a–P7b]
├── P8  Web shell                         [feature]
├── P9  Chunk card + deck                 [feature, parent → P9a–P9h]
├── P10 Filter / picker / settings        [feature, parent → P10a–P10e]
├── P11 Apply screen                      [feature]
├── P12 PWA + service worker              [feature]
├── P13 Local retry queue                 [feature]
└── P14 Real run                          [chore]
```

Children of a parent share the parent's branch and are commit boundaries within it. Parent closes only after every child closes.

---

## Phase definitions

Each phase below uses this template:

```
### P<n> — <name>
Type:           feature | chore | bug | refactor | debt
Branch:         todo/<slug>
Depends on:     <prior phase ids>
Files:          <created> / <modified>
Acceptance:     <observable + verifiable deliverable>
Verification:   <command(s) to prove it>
Tags:           web-review,<scope>,<...>
todo new ...:   <literal CLI invocation>
```

### P0 — Parent ticket + feature branch

**Type:** feature (parent)
**Branch:** `todo/web-review` (the umbrella)
**Depends on:** —
**Acceptance:** Parent ticket created with all phases below as children via `todo plan`. Branch checked out off main.
**todo new:**
```bash
todo new "guru-review: phone-first PWA for staged_tags review (Pass B)" \
  --type feature --tags "web-review,umbrella"
todo work <id>   # creates branch todo/<id-prefix>
```
Then for each P1-P14 below: `todo new "..." --parent <P0-id>`.

---

### P1 — Repo skeleton
**Type:** chore
**Branch:** shared with P0 (`todo/web-review`)
**Depends on:** P0
**Files (create):**
- `guru-review/package.json` (workspace root)
- `guru-review/pnpm-workspace.yaml`
- `guru-review/server/{package.json, tsconfig.json}`
- `guru-review/web/{package.json, tsconfig.json, vite.config.ts}`
- `guru-review/.eslintrc.cjs`, `.prettierrc`
**Files (modify):**
- `.gitignore` — add `guru-review/**/node_modules/`, `guru-review/**/dist/`, `data/guru-shadow*`
**Acceptance:**
- `pnpm install` from `guru-review/` exits 0
- `git status --ignored=traditional` shows no `node_modules` or `dist` leaking
- Pre-existing Python toolchain unaffected (`pytest tests/` still 42-green)
**Verification:**
```bash
cd guru-review && pnpm install
git -C /home/ivy/Work/guru status --short
pytest tests/
```
**Tags:** web-review,scaffolding

---

### P2 — Schema + db handles
**Type:** feature
**Depends on:** P1
**Files (create):**
- `guru-review/server/src/schema.ts`
- `guru-review/server/src/db.ts` (ro/rw handles, prepared statement allowlist scaffold)
- `guru-review/server/src/config.ts`
- `guru-review/server/src/index.ts` (boot harness — boot, schema, exit clean)
**Schema deltas (live DB):** all `IF NOT EXISTS`; idempotent.
```sql
CREATE TABLE IF NOT EXISTS review_actions (...full DDL from design.md §3...);
CREATE INDEX IF NOT EXISTS idx_review_actions_unapplied
  ON review_actions(staged_tag_id) WHERE applied_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_review_actions_client_id
  ON review_actions(client_action_id);
CREATE INDEX IF NOT EXISTS idx_staged_tags_status_chunk
  ON staged_tags(status, chunk_id);
```
**Acceptance:**
- Boot, write schema, exit. No row counts change.
- `.indexes staged_tags` shows `idx_staged_tags_status_chunk`
- `.schema review_actions` matches design §3 byte-for-byte
- Canary counts (15371/2548/2600) unchanged after boot
**Verification:**
```bash
sqlite3 data/guru.db ".indexes staged_tags" | grep status_chunk
sqlite3 data/guru.db ".schema review_actions"
sqlite3 data/guru.db "SELECT COUNT(*) FROM staged_tags"   # → 15371
```
**Tags:** web-review,server,schema

---

### P3 — Startup snapshot
**Type:** feature
**Depends on:** P2
**Files (create):**
- `guru-review/server/src/snapshot.ts` — `db.backup()` + `PRAGMA integrity_check` + manifest.json + prune to `KEEP_BACKUPS`
- `guru-review/server/config.example.json` (with `~/guru-backups/`, `keep_backups: 20`)
**Files (modify):**
- `guru-review/server/src/index.ts` — call snapshot before opening rw handle
**Schema fingerprint check.** Add to snapshot.ts: validate `SELECT name FROM sqlite_master WHERE type='table'` against a known list (`['traditions','texts','nodes','edges','staged_tags','staged_concepts','staged_edges','review_actions','chunk_embeddings','tagging_progress']`). Mismatch → refuse to start with hint to update tool. (Design §8 risks.)
**Acceptance:**
- Boot writes `~/guru-backups/guru-<ts>-pre-session.db` + `.manifest.json` pair
- Boot **fails** if backup target dir is unwritable (tested by chmod 000 a tmpdir)
- Boot **fails** if integrity_check returns anything other than `'ok'`
- 21st snapshot prunes oldest (verified by mocking 20 stub files in BACKUP_DIR)
**Verification:**
```bash
node guru-review/server/dist/index.js  # ctrl-c after boot logs success
ls -lt ~/guru-backups/ | head
cat ~/guru-backups/*pre-session.db.manifest.json
```
**Tags:** web-review,server,backup,safety

---

### P4 — Read endpoints (parent)
**Type:** feature (parent)
**Depends on:** P2

#### P4a — `/api/health` — trivial, 5min
Returns `{ ok: true }`. No DB. Used as tailscale liveness.

#### P4b — `/api/stats`
Counts pending tags, queued actions, applied today (per reviewer + total). `WHERE applied_at >= date('now')` per design §4.5. ISO timestamps sort lexicographically.

#### P4c — `/api/traditions`
`SELECT DISTINCT tradition_id FROM nodes WHERE type='chunk' AND tradition_id IS NOT NULL ORDER BY 1`.

#### P4d — `/api/texts?tradition=X`
`SELECT DISTINCT json_extract(metadata_json, '$.text_id') ...`. Returns `null` filtered.

#### P4e — `/api/concepts`
Returns `[{node_id, concept_id, label, definition}]`. `node_id` = `concept.<concept_id>`; `concept_id` is bare. Picker sends `concept_id` back.

#### P4f — `/api/chunks` (the big one)
Keyset-paginated chunk-grouped read per design §4.6. Two queries (outer chunks + inner tags). Cursor: `base64(JSON.stringify([tradition_id, chunk_id]))`. Returns full `ChunksResponse` shape.
**Acceptance:** page 1 → cursor → page 2 contiguous, no overlap, no gap; concept filter shifts to "chunks containing X" per §4.6 caveat.

#### P4g — `chunkBody.ts`
Port `guru/corpus.py:resolve_chunk_path` to TS with two-candidate fallback. LRU ~5k entries. Use `smol-toml`.
**Acceptance:** TS port test mirrors `tests/test_chunk_paths.py` against fixture corpus tree (Buddhism / Christian Mysticism / gnosticism cases).

#### P4h — Count cache
30s TTL, keyed on canonical hash of filter params (`{tradition, text, concept, min_score}` JSON-stringified in sorted-key order). Server-global, not reviewer-scoped.

**Acceptance (parent):** `curl /api/chunks?limit=2` returns a real chunk with all its pending tags + bodies untruncated; cursor pagination round-trips.
**Tags:** web-review,server,api,reads

---

### P5 — Write endpoint
**Type:** feature
**Depends on:** P2, P4 (existence check needs ro handle and aligned shape)
**Files (create):**
- `guru-review/server/src/routes/tags.ts`
- `guru-review/server/src/lib/zodSchemas.ts`
**Files (modify):**
- `db.ts` — add `insertReviewAction`, `selectStagedTagExists` to allowlist
**Logic per design §4.7:**
1. zod validate body
2. existence check via ro (404 if `staged_tag_id` missing)
3. insert via prepared stmt
4. catch UNIQUE on `client_action_id` → return success (idempotent)
5. **never touch `staged_tags` or `edges`**
**Acceptance:**
- POST writes a row to `review_actions`
- Replay same `client_action_id` → 200, no second row
- Bogus `staged_tag_id` → 404
- Live `staged_tags` / `edges` row counts unchanged across all the above
**Verification:**
```bash
curl -X POST localhost:7314/api/tags/123/action -d '{...}' -H 'content-type: application/json'
sqlite3 data/guru.db "SELECT COUNT(*) FROM review_actions"
sqlite3 data/guru.db "SELECT COUNT(*) FROM staged_tags WHERE status != 'pending'"  # canary: 18, unchanged
```
**Tags:** web-review,server,api,writes

---

### P6 — Queue + undo endpoints
**Type:** feature
**Depends on:** P5
**Files (create):** `guru-review/server/src/routes/queue.ts`
**Files (modify):** `db.ts` — add `selectQueuedActions`, `deleteUnappliedAction`
**Acceptance:**
- `GET /api/queue` returns enriched queued actions (chunk + concept context)
- `DELETE /api/queue/:client_action_id` removes only when `applied_at IS NULL`
- Cannot delete applied actions (audit-trail preservation)
**Tags:** web-review,server,api,queue

---

### P7 — Apply transaction + parity harness (parent)
**Type:** feature (parent)
**Depends on:** P5, P6
**This is the most load-bearing phase. Do not skip P7b.**

#### P7a — Apply transaction (`apply.ts`)
Per design §4.8 verbatim. Wrapped in `rw.transaction()`. Re-checks `staged_tags.status` per row (no-op if CLI got there first).
**Files:** `guru-review/server/src/apply.ts`, `routes/apply.ts`
**Prepared stmts added:** `selectQueuedActions`, `selectStagedTag`, `ensureConceptNode`, `insertOrUpdateEdge`, `updateStagedTagStatus`, `updateStagedTagConcept`, `insertReassignedTag`, `markActionApplied`.
**Routes:** `POST /api/apply` (drains queue), `GET /api/apply/preview` (counts).
**Idempotency:** duplicate POST after success returns `{ applied: 0, status: 'already_applied' }` per design §10 #5.

#### P7b — Parity harness (`tests/parity/`)
Per design §7 step 7. Automated CI test, not manual diff.

**Layout:**
```
tests/parity/
├── README.md
├── fixtures/
│   ├── decision_sequence.json     # ~20 mixed actions
│   └── seed_subset.sql            # 30-row representative slice
├── run_cli.py                     # apply via review_tags.py against shadow A
├── run_web.ts                     # apply via web's apply.ts against shadow B
├── compare.py                     # row-content diff per design §10
└── orchestrator.sh                # spin up both, run, diff, exit nonzero on mismatch
```

**`decision_sequence.json` MUST cover:**
- `accept` with score=3 (verified tier path)
- `accept` with score=1 (proposed tier path)
- `accept` with `is_new_concept=1` (concept-node creation path — both shadows must populate `nodes.definition` from `staged_tags.new_concept_def` per the CLI fix in `todo:bdbdccd5` / commit 35d448a)
- `reject`
- `skip`
- `reassign` to **existing** concept (mutate + spawn — verify spawned row content)
- `reassign` to **free-text new** concept_id
- Re-accept on a spawned-from-reassign row (multi-step interaction)

**Comparison rules** (per design §10 #1):
- Compare `staged_tags` on `(chunk_id, concept_id, status, score, justification, is_new_concept)`
- Compare `edges` on `(source_id, target_id, type, tier, justification)`
- **Exclude** `id` (AUTOINCREMENT), `reviewed_at`, `reviewed_by`, `created_at`

**CI hook:** `.github/workflows/parity.yml` runs harness on every push to `todo/web-review-*` branches. Failing → block merge.

**Acceptance:**
- `bash tests/parity/orchestrator.sh` exits 0 on a clean shadow seed
- Mismatch → harness prints unified diff and exits nonzero
- CI workflow green on the parent's branch before P14

**Tags:** web-review,server,apply,parity,tests,critical

---

### P8 — Web shell
**Type:** feature
**Depends on:** P4 (HeaderBar reads `/api/stats`)
**Files (create):**
- `guru-review/web/index.html`, `vite.config.ts`
- `guru-review/web/src/{main.tsx, App.tsx}` — router
- `guru-review/web/src/components/HeaderBar.tsx`
- `guru-review/web/src/styles/globals.css` — Howm aesthetic (black bg, blue accent, mono for chunk bodies, sans for chrome)
- `guru-review/web/src/api/client.ts` — fetch wrapper + idempotency key minting (retry queue scaffold for P13)
- `guru-review/web/src/state/reviewer.ts` — idb-keyval device id; first-launch prompt
**Acceptance:** load `http://<tailscale-ip>:7314/` on phone, see counts in header.
**Tags:** web-review,web,scaffolding

---

### P9 — Chunk card + deck (parent)
**Type:** feature (parent)
**Depends on:** P4, P5, P8
Build leaf-up — small, isolated components first; compose last.

#### P9a — `ScoreBadge.tsx`
Score 0-3 → color (3=green, 2=blue, 1=amber, 0=red). Pill shape. Used by P9c.

#### P9b — `ConceptDef.tsx`
Collapsible block. ▸/▾ toggle, per-tag-instance state. `definition` for live concepts; `new_concept_def` (with "PROPOSED CONCEPT" note) for `is_new_concept=1`.

#### P9c — `TagRow.tsx`
One pending tag sub-card. Composes ScoreBadge + ConceptDef + per-row Accept/Reject/Skip/Reassign.

#### P9d — `ConceptPicker.tsx`
Bottom sheet for reassign. Searchable list from `/api/concepts`. Free-text fallback (matches CLI). **Cancel = no API call** (deviation from CLI per design §1 deviations).

#### P9e — `ChunkActions.tsx`
"Accept Remaining (N) / Reject Remaining (N) / Defer Remaining (N)" row. Dynamic count. Disabled when N=0.

#### P9f — `ChunkCard.tsx`
Composes header (CHUNK / SECTION / BODY in CLI 9-char-column format) + stacked TagRows + ChunkActions. Body collapses >1.5k chars with "show more" toggle.

#### P9g — `Deck.tsx` screen
Fetches paginated chunks via `/api/chunks`. Local "queued action" state per tag. Shows "Next Chunk" when all tags actioned.

#### P9h — Gestures + per-tag undo
Long-press tag → undo. Swipe left/right → reject/accept. 30% threshold + rubber-band.

**Acceptance:** review one full chunk's tags on phone end-to-end; queued actions appear in `/api/queue` server-side; undo works before apply.
**Tags:** web-review,web,deck,ui

---

### P10 — Filter / picker / settings (parent)
**Type:** feature (parent)
**Depends on:** P9

#### P10a — Filter sheet
Tradition / text / concept / min_score. URL-synced for bookmark resumption.

#### P10b — Settings screen
Reviewer device ID (editable), server URL, dry-run indicator banner.

#### P10c — Per-device cursor (`state/cursor.ts`)
IndexedDB key `cursor:<filter_hash>` (filter_hash = same canonical hash as server count cache). Resume banner with "Start from top" override.

#### P10d — Session stats drawer
Tap header counter → drawer with today / all-time / rate (last 10min) / ETA at current rate. State server-side, scoped by reviewer.

**Acceptance:** filter persists across reload; resume from saved cursor; switching filter loads correct cursor.
**Tags:** web-review,web,filter

---

### P11 — Apply screen
**Type:** feature
**Depends on:** P7, P10
**Files (create):**
- `guru-review/web/src/screens/Queue.tsx` — virtualized (`react-window`) list, group-by-tradition collapsible sections
- `guru-review/web/src/screens/ApplyResult.tsx`
**Acceptance:** queued batch promotes successfully on shadow DB; result screen shows `{ applied, edges_created, skipped_already_resolved, errors }`.
**Tags:** web-review,web,apply

---

### P12 — PWA + service worker
**Type:** feature
**Depends on:** P11
**Files (create):** `guru-review/web/public/manifest.webmanifest`, `guru-review/web/public/sw.js`
**Acceptance:** install-to-home-screen works on iOS Safari + Android Chrome; UI loads on flaky network (app shell only — no API caching).
**Tags:** web-review,web,pwa

---

### P13 — Local retry queue
**Type:** feature
**Depends on:** P12
**Files (create/modify):** `guru-review/web/src/state/queue.ts`, extend `api/client.ts` with retry + IndexedDB persistence
**Acceptance:**
- Force airplane mode mid-session; reconnect; queue drains with original `client_action_id`s
- Force-close app with unsynced actions → relaunch → replay from IndexedDB
- Indicator shows "queued locally — N waiting" while offline
**Tags:** web-review,web,offline

---

### P14 — Real run
**Type:** chore
**Depends on:** P13 + parity harness CI green for **≥2 prior dry-run sessions**
**Files (modify):** `guru-review/server/config.json` — `"dry_run": false`
**Pre-flight checklist (run as a script in `guru-review/scripts/preflight.sh`):**
- [ ] Take fresh snapshot labeled `pre-first-web-apply` (separate from boot snapshot — name it explicitly)
- [ ] `bash tests/parity/orchestrator.sh` green
- [ ] Verify canary: `staged_tags=15371, edges=2548, nodes=2600` against current live DB (or whatever the latest manifest says — drift here means CLI was used in the meantime, fine, just record the new baseline)
- [ ] At least 2 dry-run web sessions complete with parity harness regression-checked after each
**Acceptance:**
- Small batch (~20 tags) reviewed and applied on phone
- Post-apply audit: `SELECT * FROM staged_tags WHERE reviewed_by='ivy-phone' ORDER BY reviewed_at DESC LIMIT 5` shows expected status + reviewer
- Spot-check 5 promoted edges in `data/guru.db` — tier and justification match queued action
- New snapshot taken post-apply, labeled `post-first-web-apply`
**Tags:** web-review,go-live,critical

---

## Cross-cutting concerns

### Conventions

- TS: ESM, strict mode, no implicit any.
- Commits: `todo:<id> — <terse summary>` per project convention.
- Branches: parent on `todo/web-review`; phase commits stack on it. **Do not** split each phase into its own branch off main — the parity harness is the gate, and it lives at the parent level.
- Each leaf phase ends with `todo close <id>` + ticket-state commit. Parent closes only after every child closes.
- Merge parent to main with `--no-ff` once §10 acceptance criteria all hold.

### Parity harness as merge gate

Any PR that touches:
- `scripts/review_tags.py`
- `guru-review/server/src/apply.ts`
- `guru-review/server/src/db.ts` (the prepared statement set)
- `guru-review/server/src/schema.ts`

**must** include a parity-harness run as a CI check. Failing harness → can't merge. This is non-negotiable; the parity invariant is the project's load-bearing assumption for data safety.

### Open design questions to resolve before implementation

These come from `design.md` §9. They block specific phases:

| # | Question | Blocks | Status |
|---|---|---|---|
| §9.1 | Concept picker scope (live nodes only vs include staged_concepts) | P9d | live + free-text fallback (matches CLI) |
| §9.2 | Per-device 24h skip-hide | P10 | defer to v1.1 (note in P10 docs) |
| §9.3 | Edit justification on accept | P9c | defer to v1.1, match CLI |
| §9.4 | "Propose missing tag" affordance | P9 | defer to v1.1 — adds write path |
| §9.5 | Accept Remaining confirmation modal | P9e | 3-second toast (already specced) |
| §9.6 | Score=0 chunks | — | **resolved** — 0 exist, no action |
| §9.7 | Populate `nodes.definition` on `is_new_concept` accept | — | **resolved by `todo:bdbdccd5`** (commit 35d448a) — CLI's `promote_to_expresses` now upserts with `COALESCE(nodes.definition, excluded.definition)`. Web's `apply.ts` mirrors this; harness asserts strict equivalence on `nodes.definition`, no carve-out needed |

All open questions are resolved or deferred to v1.1 with explicit defaults. None block P7.

### What this plan deliberately omits

- Edge review (Pass C) UI
- Concept proposal review
- Authentication (tailscale boundary)
- Multi-user merge
- Bulk Accept by tradition
- Production deployment beyond local Node + tailscale

All non-goals per `design.md` §1.

---

## Risk register (impl-time)

| Risk | Phase | Mitigation |
|---|---|---|
| pnpm/node deps pollute Python repo | P1 | gitignore additions verified before first install; CI also runs `git status --ignored` after install to catch leaks |
| Long-lived feature branch drifts from main | All | weekly rebase; any `scripts/review_tags.py` change on main triggers immediate parity-harness re-run |
| Parity harness has a bug → false confidence | P7b | for first 2 dry runs, manually compare 5 random row triplets (CLI shadow / web shadow / live) before trusting CI |
| First `/api/apply` on real DB has latent bug | P14 | `dry_run: true` for ≥2 sessions; `pre-first-web-apply` snapshot taken separately from boot snapshot |
| Schema migration on live DB fails mid-run | P2 | indexes are `CREATE INDEX IF NOT EXISTS`; if fails, server fails-fast at boot before any writes |
| Concurrent CLI + web run | All | `apply.ts` re-checks `staged_tags.status` per row → no-op for already-resolved; `review_actions.applied_at` audit-trails skipped rows |
| Operator commits `guru-shadow.db` or backup file | All | `.gitignore` covers `data/guru-shadow*` and `~/guru-backups/` is outside repo entirely |
| Backup dir fills up | P3 | `KEEP_BACKUPS=20` cap; prune at boot; ~1.6GB ceiling at 80MB/snapshot |
| Future change to `promote_to_expresses` definition-handling drifts CLI from web | P7 | parity harness will catch it; any PR touching review_tags.py:67-86 must re-run harness |

---

## Done = `design.md` §10

Restated as a phase-mapped checklist:

- [ ] §10 #1 (parity content equivalence) — P7b automation green
- [ ] §10 #2 (snapshot fail-fast) — P3 acceptance
- [ ] §10 #3 (no write outside allowlist) — P2 + code-review rule "no `rw.prepare` outside `db.ts`"
- [ ] §10 #4 (POST action idempotent) — P5 acceptance
- [ ] §10 #5 (POST apply idempotent no-op) — P7a acceptance
- [ ] §10 #6 (PWA installs to home screen) — P12 acceptance
- [ ] §10 #7 (queued actions = taps modulo undo) — manual P9+P13 verification
- [ ] §10 #8 (`reviewed_by` = device id) — P14 audit query

---

## How to consume this plan as todo tickets

1. Run `todo new` for P0 (the umbrella feature ticket). Capture its id.
2. For each P1-P14, run:
   ```bash
   todo new "<phase summary>" --type <type> --tags "web-review,..." --parent <P0-id>
   ```
3. For parent phases (P4, P7, P9, P10), repeat step 2 for each child sub-phase, parented to the parent phase ticket.
4. Run `todo work <P0-id>` to create branch `todo/web-review` and start.
5. Work phases in order; don't skip to a later phase even if it looks easier — the dependency graph reflects real coupling, especially for the parity harness gate at P7b.
6. Each leaf closes via `todo close <id> --note "..."` (or `--test ...::test_x` if a parity-harness or unit test is the proof).
7. Each parent closes only after all its children are done.
