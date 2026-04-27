# guru-review: Mobile Tag Review Tool

**Status:** Design — pending implementation
**Scope:** Pass B (concept tag) review only. Edge review (Pass C) is out of scope for v1. Predates the v3 benchmarking/fine-tuning track described in `docs/v3.md` and `docs/v3-impl.md`; v3 schema additions (model and prompt_version columns on `staged_tags`, plus `bench_runs`/`bench_results`/`sample_sets` tables) do not affect this tool's operation. If those columns exist when this tool runs, they're transparently included in the SELECT but not rendered in the UI for v1.
**Target:** Phone-first PWA backed by a thin TypeScript server reading `data/guru.db` directly.

---

## 1. Goals & Non-Goals

### Goals

- Review the **~15k pending `staged_tags` rows** from a phone over the local network. Sessions will be many; the tool needs to feel sustainable, not heroic.
- **Match the unit of review to the unit of generation.** The LLM tagged each chunk holistically — reading the passage, then proposing N concepts with scores. The reviewer should audit the same way: read the chunk once, then evaluate the model's full take on it. The CLI's per-tag fragmentation (one card per `(chunk, concept)` pair) makes you re-read the same passage 3-7 times for the same chunk and prevents you from noticing patterns *across* a chunk's tags. The web tool flips this: the unit of review is the chunk-with-its-pending-tags, not the individual tag.
- Preserve **exactly** the semantics of `scripts/review_tags.py` so the live graph state after a session is indistinguishable from what the CLI would have produced for the same decisions. (Aggregation is a UI concern only — the underlying writes are still per-`target_id`.)
- Protect the database. Three days of 3090 tagging time is the asset being insured. No path through the new tool can corrupt `staged_tags` rows or insert junk into `edges` without an operator-initiated apply step.
- Make per-device review attribution possible (`reviewer = "ivy-phone"` vs. `"ivy-laptop"` vs. `"human"` from the CLI), so future audits can tell sources apart.

### Non-Goals (v1)

- Edge review (`staged_edges`). Different data shape, different UI, and the staging table is empty until `propose_edges.py` runs after embedding. Defer.
- Concept proposal review (`staged_concepts`). Out of scope.
- New chunk tagging or LLM invocation. The tool only reviews what's already been generated.
- Authentication. Network boundary is tailscale.
- Multi-user merge / conflict resolution. Single human reviewer assumed.

### Explicit non-divergence from the CLI

The following CLI behaviors must be replicated exactly. They are listed here so any reviewer of this doc can verify them in `scripts/review_tags.py` before signing off:

1. Accept promotes via `INSERT INTO edges ... ON CONFLICT(source_id, target_id, type) DO UPDATE SET tier=excluded.tier, justification=excluded.justification`. This **silently overwrites** any pre-existing edge's tier and justification. Preserve.
2. Tier on accept is `verified` if `score >= 2` else `proposed`. Preserve.
3. Reject sets `staged_tags.status = 'rejected'`. No edge written. Preserve.
4. Reassign is a **mutate + spawn**, not a single state change:
   - Sets the original row to `status = 'reassigned'` *and* updates its `concept_id` to the new value.
   - Inserts a *new* pending `staged_tags` row for the new concept with the same chunk and score, justification = `"Reassigned from <old_concept_id>"`, `is_new_concept = 0`.
   The new row is itself reviewable in a future pass. Preserve. Note: this means one queued `reassign` action expands into two row writes at apply time, and the spawned row will appear in the *next* deck load (not the current one — the apply step is what creates it).
5. Skip is non-destructive — no DB write, the row stays `pending`. Preserve. (Same observable effect as the CLI's session-local skip counter.)
6. The CLI ensures the target concept node exists via upsert with COALESCE on the definition column:

   ```sql
   INSERT INTO nodes(id, type, label, definition)
     VALUES(?, 'concept', ?, ?)
     ON CONFLICT(id) DO UPDATE SET
       definition = COALESCE(nodes.definition, excluded.definition)
   ```

   `label = concept_id.replace("_"," ").title()`. Definition argument is `staged_tags.new_concept_def` (`None` for `is_new_concept=0` accepts). COALESCE preserves any pre-existing definition. Preserve. (Updated by `todo:bdbdccd5`; see §9.7 for history.)
7. CLI default `--min-score` is 1; README example uses 2. Server defaults to 1.

### Explicit *deviations* from the CLI

These are intentional improvements where strict parity would propagate a footgun:

1. **Reassign-with-empty-input is a Cancel, not a silent skip.** The CLI's `c` followed by Enter on the "New concept ID:" prompt silently breaks out of the action loop with no DB write *and* no skip-counter increment — the row vanishes from the session with no audit trail (`review_tags.py:177`). The web tool surfaces reassign through a concept picker sheet; dismissing the sheet is a Cancel that returns the user to the same card with no API call made. A `reassign` action is only POSTed when a concept is actually selected. This deviation is strictly safer (no ambiguous "did I review that?" rows) and observable only as the absence of a bug.
2. **Per-device reviewer attribution.** CLI hardcodes `reviewed_by = 'human'`; web tool uses the device-supplied reviewer ID (`'ivy-phone'`, etc.). Already covered in §1 goals.

### Scale considerations (15k pending tags)

The pending pool is large enough that several CLI assumptions break and the UX has to be designed for it directly:

**Stamina, not throughput.** At even a generous 10 seconds per tag, 15k tags is ~42 hours of human attention. This is many sessions. Design implications:

- The deck must support **session resumption** without re-showing already-reviewed cards. The CLI's `WHERE status='pending'` ordering by `tradition_id, score DESC` already gives a stable order; the web tool must respect it and remember position across sessions per device.
- **Progress visibility matters more than at smaller scales.** Header should show `pending / total reviewed today / total accepted` so the reviewer can see the bar moving. Without this, 15k feels infinite.
- **Filter-driven sessions are the primary mode**, not "review the whole deck." Reviewer picks a tradition, a text, or a min-score and works that slice. The filter sheet (§5.5) becomes the main entry point, not the all-pending deck.

**The CLI's `fetchall()` will blow up at 15k.** `review_tags.py:120` does `rows = conn.execute(sql, params).fetchall()` — fine at 2k, painful at 15k, and the result set joins to `nodes` and reads chunk bodies from disk on demand. The web tool's `GET /api/tags` must paginate. See §4.6.

**Apply queue size.** A long phone session might queue 200–500 actions. Apply transaction at that size is still fast (single transaction, ~100ms), but the apply *preview* screen should not render all 500 in one DOM tree — virtualize the list. See §5.6.

**Backup growth.** 20 snapshots at ~80MB each (DB grows with `review_actions` rows over time) is ~1.6GB. Still fine. Prune aggressively if disk pressure ever materializes.

**Concept picker scale.** The current taxonomy has 44 concepts (per README), well within a single scrollable picker. If reassign creates many `is_new_concept` proposals over the 15k pass, the picker may grow — but `staged_concepts` rows aren't picker candidates until accepted into `nodes`, so the live picker stays at ~44. No change needed.

---

## 2. Architecture

```
                    ┌──────────────────────────────┐
                    │  React PWA (web/)            │
                    │   - swipe deck               │
                    │   - filter sheet             │
                    │   - apply screen             │
                    │   - per-device reviewer id   │
                    └──────────────┬───────────────┘
                                   │ HTTPS over tailscale
                                   │
                    ┌──────────────▼───────────────┐
                    │  Express + TS (server/)      │
                    │   - readonly db handle       │  ← all GETs
                    │   - rw db handle (gated)     │  ← only inside POST handlers
                    │   - prepared statement set   │  ← no ad-hoc SQL on rw
                    │   - review_actions log       │  ← append-only buffer
                    │   - apply transaction        │  ← drains log → live tables
                    │   - online backup at startup │
                    └──────────────┬───────────────┘
                                   │
                            data/guru.db
                                   │
                    backups/guru-<timestamp>.db
```

One process. The Express server also serves the built web bundle from `web/dist`, so deployment is `node server/dist/index.js` and you're done.

### Why a separate review_actions table

Phone taps go to `review_actions` only. Nothing in `staged_tags` or `edges` changes until the operator hits **Apply** in the UI. Benefits:

- **Auditability.** Every decision recorded with timestamp, device, action, optional reassign target.
- **Idempotency.** A `client_action_id` UUID minted on the phone makes retries safe — phone connection drops, replays, server dedupes.
- **Replayability.** If a bug in promote logic is discovered later, fix the bug, then re-run apply over un-applied actions.
- **Undo.** Mistakes during a session can be undone before apply with no DB impact.
- **Concurrent safety.** If you accidentally start `review_tags.py` while the server is running, the worst that happens is the CLI processes a row the server has queued. The queued action becomes a no-op at apply time (the row is no longer `pending`). No corruption.

---

## 3. Data Model Changes

One additive table. No modifications to existing schema.

```sql
CREATE TABLE IF NOT EXISTS review_actions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id     INTEGER NOT NULL REFERENCES staged_tags(id),
    action            TEXT NOT NULL CHECK(action IN ('accept','reject','skip','reassign')),
    reassign_to       TEXT,                       -- concept_id, required iff action='reassign'
    reviewer          TEXT NOT NULL,              -- e.g. 'ivy-phone', 'ivy-laptop', 'human'
    client_action_id  TEXT NOT NULL UNIQUE,       -- UUID from client; idempotency key
    applied_at        TEXT,                       -- NULL = queued; set on apply
    error             TEXT,                       -- set if apply failed for this row
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_review_actions_unapplied
    ON review_actions(target_id) WHERE applied_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_review_actions_client_id
    ON review_actions(client_action_id);
```

The partial index on `applied_at IS NULL` keeps the "is this tag already queued?" lookup cheap even after thousands of applied actions accumulate.

A `CHECK` constraint enforcing `(action = 'reassign') = (reassign_to IS NOT NULL)` would be ideal but SQLite's CHECK is per-row and that's exactly per-row, so:

```sql
CHECK ((action = 'reassign' AND reassign_to IS NOT NULL)
    OR (action != 'reassign' AND reassign_to IS NULL))
```

Apply at table creation time.

---

## 4. Server

### 4.1 Stack

- Node 20+, TypeScript, ESM.
- `express` for routing.
- `better-sqlite3` for DB. Synchronous, fast, exposes prepared statements cleanly. The whole tool fits comfortably in single-threaded sync — there's one user.
- `zod` for request body validation.
- `pino` for structured logs.

No ORM. Direct SQL is shorter than any wrapper for this size.

### 4.2 Database handles

Two connections opened at boot:

```ts
const ro = new Database(DB_PATH, { readonly: true, fileMustExist: true });
const rw = new Database(DB_PATH);
rw.pragma('journal_mode = WAL');
rw.pragma('foreign_keys = ON');
rw.pragma('busy_timeout = 5000');
```

Every GET handler closes over `ro`. Every write closes over `rw`. The `rw` handle is only ever passed to handlers that mutate. Routing helpers don't see it.

### 4.3 Prepared statement allowlist

All writes go through this set, prepared once at boot:

```ts
const stmts = {
  insertReviewAction: rw.prepare(`
    INSERT INTO review_actions
      (target_id, action, reassign_to, reviewer, client_action_id)
    VALUES (?, ?, ?, ?, ?)
  `),
  deleteUnappliedAction: rw.prepare(`
    DELETE FROM review_actions
    WHERE client_action_id = ? AND applied_at IS NULL
  `),
  // apply-time statements — see §4.7
  selectQueuedActions: ro.prepare(`...`),
  ensureConceptNode: rw.prepare(`...`),
  insertOrUpdateEdge: rw.prepare(`...`),
  updateStagedTagStatus: rw.prepare(`...`),
  insertReassignedTag: rw.prepare(`...`),
  markActionApplied: rw.prepare(`...`),
};
```

Any code path that wants to write must use one of these. Code review rule: no `rw.prepare` outside `db.ts`.

### 4.4 Startup snapshot

Before opening the rw handle, on every server start. Uses SQLite's online backup API (via `better-sqlite3`'s `db.backup()`) rather than `VACUUM INTO`, matching the Phase 0 backup discipline at `docs/v3-impl.md` §11. The online backup API is WAL-safe and is what the upstream project standardized on. **This is the only async point in an otherwise synchronous server**; the rest of `index.ts` stays sync after `await tmp.backup(target)` completes:

```ts
const ts = new Date().toISOString().replace(/[:.]/g, '-');
const target = path.join(BACKUP_DIR, `guru-${ts}-pre-session.db`);
fs.mkdirSync(BACKUP_DIR, { recursive: true });

const tmp = new Database(DB_PATH, { readonly: true });
await tmp.backup(target);   // SQLite online backup API
tmp.close();

// Manifest: integrity check + canary counts
const verify = new Database(target, { readonly: true });
const integrity = verify.pragma('integrity_check', { simple: true });
const stagedCount = verify.prepare('SELECT COUNT(*) AS n FROM staged_tags').get() as {n: number};
const acceptedCount = verify.prepare(
  "SELECT COUNT(*) AS n FROM staged_tags WHERE status='accepted'"
).get() as {n: number};
verify.close();

if (integrity !== 'ok') {
  throw new Error(`snapshot integrity check failed: ${integrity}`);
}
fs.writeFileSync(target + '.manifest.json', JSON.stringify({
  created_at: ts, integrity, staged_tags: stagedCount.n, accepted: acceptedCount.n,
}, null, 2));

pruneOldBackups(BACKUP_DIR, KEEP_BACKUPS);
```

If `backup()` throws or the integrity check fails, server **refuses to start**. No backup, no run.

**Backup location.** `BACKUP_DIR` defaults to `~/guru-backups/` (outside the repo working tree, matching Phase 0 advice). Configurable via `config.json`.

`KEEP_BACKUPS` defaults to 20 — at 15k tags across many sessions, more snapshots is cheap insurance. ~50MB × 20 = 1GB ceiling, still trivial.

**Belt and suspenders: also dump pending+accepted to JSON on startup**, mirroring Phase 0 step 4. If SQLite ever becomes the problem, the JSON is a format-independent escape hatch:

```ts
const dumpPath = path.join(BACKUP_DIR, `staged-tags-${ts}.json`);
const all = ro.prepare('SELECT * FROM staged_tags').all();
fs.writeFileSync(dumpPath, JSON.stringify(all));
```

Add to startup. ~5MB at 15k rows. Pruned alongside snapshots.

### 4.5 API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | `{ ok: true }`. Used for tailscale liveness. |
| `GET` | `/api/stats` | Counts: pending tags total, queued actions, applied today (per reviewer), session rate. The "today" count uses `WHERE applied_at >= date('now')` — works because the ISO timestamp format sorts lexicographically. |
| `GET` | `/api/concepts` | Live concept nodes for reassign picker. Returns `[{node_id, concept_id, label, definition}]` where `node_id` is the prefixed form (`concept.gnosis_direct_knowledge`) and `concept_id` is the bare form (`gnosis_direct_knowledge`). The picker displays `label` + `definition` and sends `concept_id` (the bare form) back in the reassign POST body — the apply step reconstructs the `concept.` prefix when ensuring the node exists, matching CLI behavior. |
| `GET` | `/api/traditions` | Distinct `tradition_id` values from chunk nodes, for filter sheet. |
| `GET` | `/api/texts?tradition=X` | Distinct `text_id`s within a tradition (from `metadata_json`). |
| `GET` | `/api/chunks` | **Keyset-paginated** chunks with their pending tags. Query: `tradition`, `text`, `concept`, `min_score`, `cursor`, `limit`. Excludes any tag with an unapplied action. Returns `{ chunks, next_cursor, pending_chunks_in_filter, pending_tags_in_filter }`. See §4.6. |
| `GET` | `/api/queue` | Currently queued (un-applied) actions, with their tag context, for the apply preview screen. |
| `POST` | `/api/tags/:target_id/action` | Body: `{ action, reassign_to?, client_action_id, reviewer }`. Idempotent on `client_action_id`. |
| `DELETE` | `/api/queue/:client_action_id` | Remove a queued action before apply. |
| `POST` | `/api/apply` | Body: `{ client_action_id }`. Drains queue in single transaction. Idempotent. |
| `GET` | `/api/apply/preview` | What would happen if apply ran now. Counts and a sample. |

### 4.6 Read query: GET /api/chunks

The unit of pagination is the **chunk**, not the individual tag. One response page contains N chunks, each with all its pending tags. With 15k tags and an average of, say, 4 tags per chunk, that's ~3.7k chunks — keyset pagination is still mandatory but on chunk identity, not tag identity.

Approach: outer query selects the next page of chunk_ids ordered by `(tradition_id, chunk_id)`, inner query fetches all pending tags for those chunks. Two queries, one round-trip — bounded fan-out (5-10 chunks per page × ~5 tags each = 25-50 tag rows max).

```sql
-- Outer: page of chunks that still have at least one un-actioned pending tag
SELECT DISTINCT n.id AS chunk_id, n.tradition_id, n.label AS section_label,
       json_extract(n.metadata_json, '$.text_id') AS text_id
FROM nodes n
JOIN staged_tags st ON st.chunk_id = n.id
WHERE st.status = 'pending'
  AND st.score >= :min_score
  AND NOT EXISTS (
      SELECT 1 FROM review_actions ra
      WHERE ra.target_id = st.id AND ra.applied_at IS NULL
  )
  -- + optional tradition / text_id filters
  -- + cursor: (n.tradition_id, n.id) > (:cursor_trad, :cursor_id)
ORDER BY n.tradition_id ASC, n.id ASC
LIMIT :limit;

-- Inner: all pending tags for the chunks in this page
SELECT st.id, st.chunk_id, st.concept_id, st.score, st.justification,
       st.is_new_concept, st.new_concept_def
FROM staged_tags st
WHERE st.chunk_id IN (:chunk_ids)
  AND st.status = 'pending'
  AND st.score >= :min_score
  AND NOT EXISTS (
      SELECT 1 FROM review_actions ra
      WHERE ra.target_id = st.id AND ra.applied_at IS NULL
  )
ORDER BY st.chunk_id, st.score DESC, st.id ASC;
```

The inner query's `score DESC` ordering is what gives the audit-the-LLM-gradient effect: within a chunk, the model's strongest claims appear first.

Cursor encoding: `base64(JSON.stringify([tradition_id, chunk_id]))`. Limit defaults to 8 chunks, max 20.

**Concept filter caveat.** A concept filter shifts semantics from "show me tags of concept X" to "show me chunks containing at least one pending tag for concept X (and all their other pending tags too)." This is intentional — auditing one concept in isolation re-introduces the fragmentation the chunk-grouped view exists to fix. Documented in §5.5.

**Required schema migration.** The outer query needs a compound index on `staged_tags(status, chunk_id)`. The current schema (verified against `data/guru.db`) has `idx_staged_tags_status`, `idx_staged_tags_chunk`, and `idx_staged_tags_concept` as separate single-column indexes — without the compound, SQLite picks one and scans. `schema.ts` adds:

```sql
CREATE INDEX IF NOT EXISTS idx_staged_tags_status_chunk
    ON staged_tags(status, chunk_id);
```

Idempotent and additive — safe to run on the live DB on first server boot.

Server enriches by joining concept definitions for every concept_id appearing in the page and loading chunk bodies via §4.9.

Returned shape:

```ts
type PendingTag = {
  target_id: number;
  concept_id: string;
  concept_label: string;       // from nodes.label, used in concept picker too
  concept_def: string;         // full definition prose (see §5.3 for display)
  score: 0 | 1 | 2 | 3;
  justification: string;
  is_new_concept: boolean;
  new_concept_def: string | null;
};

type Chunk = {
  chunk_id: string;            // e.g. "Buddhism.diamond-sutra.003"
  tradition_id: string;
  section_label: string;       // e.g. "Vajrakkhedika (Diamond Cutter) — Section 1c"
  text_id: string | null;
  body: string;                // full chunk body, untruncated
  pending_tags: PendingTag[];  // ordered score DESC, then id ASC
};

type ChunksResponse = {
  chunks: Chunk[];
  next_cursor: string | null;
  pending_chunks_in_filter: number;   // chunks with ≥1 pending tag in filter
  pending_tags_in_filter: number;     // total tags in filter (for stats drawer)
};
```

`concept_def` ships with every tag row even though many tags will share concepts. This is intentional — the alternative (separate `/api/concepts` lookup) means the UI has to manage a concept cache and handle race conditions on stale data. The duplication is small (44 concepts × ~200 chars) and the rendering path is dead simple. For the rare 20-concept page, that's still <100KB.

Both counts are cached for ~30s server-side, keyed on a stable hash of the filter params (`{tradition, text, concept, min_score}` serialized in canonical order). Cache is server-global — counts are filter-scoped, not reviewer-scoped, so all devices share the same warmed value. The body is **not truncated**; CLI's 400-char truncation was a terminal constraint.

### 4.7 Write path: POST /api/tags/:id/action

```ts
// validate body with zod
// EXISTENCE check (read via ro): staged_tag with this id must exist
//   - this is NOT a staleness check; the apply transaction re-checks status per row
//   - purpose: give the phone a fast 404 for bogus ids (chunk deleted, stale page),
//     so bad actions don't sit in the queue surfacing as per-row errors at apply time
// if action='reassign', reassign_to must be a non-empty string
// insert into review_actions via prepared stmt
// if UNIQUE constraint on client_action_id fires, treat as success (idempotent)
// return { ok: true, queued_count }
```

That's the whole write. **Nothing in `staged_tags` or `edges` is touched.**

### 4.8 Apply transaction

The heart of the tool. Must replicate `review_tags.py` exactly.

```ts
const apply = rw.transaction((reviewerActionId: string) => {
  const queued = stmts.selectQueuedActions.all() as QueuedAction[];
  // queued is ordered by review_actions.id ASC — same order user reviewed in

  const results = { applied: 0, edges_created: 0, edges_updated: 0,
                    skipped_already_resolved: 0, errors: [] as ApplyError[] };

  for (const q of queued) {
    try {
      // Re-check current staged_tag status — may have been resolved by CLI in parallel
      const tag = stmts.selectStagedTag.get(q.target_id) as StagedTag | undefined;
      if (!tag || tag.status !== 'pending') {
        // No-op. Mark action applied with a note. Preserves audit trail.
        stmts.markActionApplied.run({
          id: q.id, error: `tag was ${tag?.status ?? 'missing'} at apply time`,
        });
        results.skipped_already_resolved++;
        continue;
      }

      switch (q.action) {
        case 'accept': {
          // 1. Ensure concept node — exact CLI label rule
          const conceptNodeId = `concept.${tag.concept_id}`;
          // Mirror Python str.title() exactly: lowercase rest of word, capitalize first letter.
          // Without the leading toLowerCase(), an uppercase concept_id like "AHURA_MAZDA"
          // would render as "AHURA MAZDA" (web) vs "Ahura Mazda" (CLI), breaking parity.
          // Today's concept_ids are all snake_case lowercase so this is insurance, not a fix.
          const label = tag.concept_id
              .toLowerCase()
              .replace(/_/g, ' ')
              .replace(/\b\w/g, c => c.toUpperCase());
          // Pass new_concept_def through — COALESCE in the prepared stmt
          // (see §1.3 #6) preserves pre-existing definitions. For
          // is_new_concept=0 accepts tag.new_concept_def is null.
          stmts.ensureConceptNode.run(conceptNodeId, label, tag.new_concept_def);

          // 2. Insert/update edge with CLI's tier rule
          const tier = tag.score >= 2 ? 'verified' : 'proposed';
          stmts.insertOrUpdateEdge.run(
            tag.chunk_id, conceptNodeId, 'EXPRESSES', tier, tag.justification ?? '',
          );

          // 3. Mark staged_tag accepted with reviewer attribution
          stmts.updateStagedTagStatus.run('accepted', q.reviewer, nowIso(), tag.id);
          results.edges_created++;
          break;
        }
        case 'reject': {
          stmts.updateStagedTagStatus.run('rejected', q.reviewer, nowIso(), tag.id);
          break;
        }
        case 'reassign': {
          stmts.updateStagedTagStatus.run('reassigned', q.reviewer, nowIso(), tag.id);
          // Also update the concept_id on the reassigned row to match CLI behavior
          stmts.updateStagedTagConcept.run(q.reassign_to, tag.id);
          // Spawn a new pending row for the new concept
          stmts.insertReassignedTag.run(
            tag.chunk_id, q.reassign_to, tag.score,
            `Reassigned from ${tag.concept_id}`,
          );
          break;
        }
        case 'skip': {
          // No staged_tags write, just close the action
          break;
        }
      }

      stmts.markActionApplied.run({ id: q.id, error: null });
      results.applied++;
    } catch (e) {
      // Per-row failure inside a transaction will throw out — better-sqlite3
      // transactions are atomic. So we re-throw to roll the whole thing back.
      throw new ApplyFailure(q.id, e);
    }
  }
  return results;
});
```

Key invariants:
- **All-or-nothing.** `better-sqlite3`'s `db.transaction()` wrapper rolls back on any throw.
- **Re-checks `staged_tags.status` per row.** If the CLI processed a row in parallel, the queued action becomes a no-op rather than a conflict.
- **Same-shape SQL as the CLI's `promote_to_expresses`.** Use the literal queries from `scripts/review_tags.py:promote_to_expresses` (the upsert + COALESCE node ensure, then the edge upsert).
- **Reviewer attribution flows through.** `staged_tags.reviewed_by` is set to `'ivy-phone'` (or whatever the device reports) instead of the CLI's hard-coded `'human'`.

After successful apply, the response has the full result object, which the UI shows on a confirmation screen.

### 4.9 load_chunk_body — TypeScript port

Port from `guru/corpus.py:resolve_chunk_path` (added in commit 21c5541). The tradition segment of a chunk_id is a **display name** like `"Christian Mysticism"` — corpus directories are snake_case `christian_mysticism`. The resolver tries the raw segment first, then a normalized form, returning the first path that exists:

```ts
import * as toml from 'smol-toml';

function resolveChunkPath(chunkId: string, corpusDir: string): string | null {
  const parts = chunkId.split('.');
  if (parts.length < 3) return null;
  const [rawTrad, textId, seq] = [parts[0], parts[1], parts[2]];
  const candidates = [
    rawTrad,
    rawTrad.toLowerCase().replace(/ /g, '_'),
  ];
  for (const trad of candidates) {
    const p = path.join(corpusDir, trad, textId, 'chunks', `${seq}.toml`);
    if (fs.existsSync(p)) return p;
  }
  return null;
}

function loadChunkBody(chunkId: string): string {
  const file = resolveChunkPath(chunkId, CORPUS_DIR);
  if (file === null) return '';
  const parsed = toml.parse(fs.readFileSync(file, 'utf8')) as any;
  return parsed?.content?.body ?? '';
}
```

The two-candidate logic must match the Python exactly — same order, same normalization. There is a regression test for the Python at `tests/test_chunk_paths.py`; the TS port should pass an equivalent test on `["Buddhism.diamond-sutra.003", "Christian Mysticism.life-and-doctrines-boehme.012", "gnosticism.gospel-of-thomas.077"]` against a fixture corpus tree.

Result is cached in-memory by `chunk_id` (LRU, ~5k entries).

### 4.10 Configuration

`server/config.json` (or env vars, both work):

```json
{
  "guru_root": "/home/ivy/Work/guru",
  "db_path": "/home/ivy/Work/guru/data/guru.db",
  "backup_dir": "/home/ivy/guru-backups",
  "keep_backups": 20,
  "port": 7314,
  "host": "0.0.0.0",
  "default_reviewer": "human",
  "dry_run": false
}
```

`backup_dir` lives outside the repo working tree to match the Phase 0 discipline in `docs/v3-impl.md` §11; `keep_backups` matches §4.4. `dry_run: true` opens a copy of the DB at `data/guru-shadow.db` instead. First session should run dry to validate apply behavior.

---

## 5. Web App

### 5.1 Stack

- Vite + React 18 + TypeScript.
- TailwindCSS for layout. Match the Howm aesthetic: pure black background, dark surfaces, blue accent, terminal/protocol typography. The CLI output style this tool replicates *is* the protocol aesthetic — lean into it.
- Mono font for chunk bodies (matches the CLI), sans for chrome.
- PWA manifest + service worker so it installs to home screen on iOS/Android. Service worker only caches the app shell, not API responses — the data is what the server has, period.
- `idb-keyval` for one piece of localState: the device reviewer ID (set once on first launch).

### 5.2 Routes

- `/` — Review deck.
- `/queue` — Apply preview / queued actions list.
- `/filter` — Filter sheet (modal on top of `/`).
- `/settings` — Reviewer device ID, server URL, dry-run indicator.

### 5.3 Chunk card layout

The unit shown is a chunk plus all its pending tags. The reviewer reads the body once, then audits each of the model's calls against that one mental model of the passage. This is the central UX shift from the CLI.

```
┌──────────────────────────────────────────┐
│ 12 queued · 487 chunks left · 12,403 ▾   │  ← header
│            [Apply 12]                    │
├──────────────────────────────────────────┤
│  ════════════════════════════════════════│
│  CHUNK:   Buddhism.diamond-sutra.003     │
│  SECTION: Vajrakkhedika (Diamond Cutter) │
│           — Section 1c                   │
│  ────────────────────────────────────────│
│  BODY:                                   │
│    The Tathagata cannot be perceived by  │
│    the possession of signs. And why?     │
│    Because the Tathagata has taught that │
│    the possession of signs is in truth   │
│    no-possession of no-signs.            │
│  ════════════════════════════════════════│
│                                          │
│  ┌─ TAG 1 of 3 ──────────────────────┐   │
│  │ CONCEPT: apophatic_theology   [3] │   │  ← score badge inline
│  │ LLM:     The passage explicitly   │   │
│  │          states the Tathagata     │   │
│  │          cannot be known by       │   │
│  │          possession of signs…     │   │
│  │ ▸ definition                      │   │  ← tap to expand
│  │ [ Reject ]   [ Skip ]   [ Accept ]│   │
│  │              [ Reassign … ]       │   │
│  └───────────────────────────────────┘   │
│                                          │
│  ┌─ TAG 2 of 3 ──────────────────────┐   │
│  │ CONCEPT: emptiness_sunyata    [3] │   │
│  │ LLM:     "No-possession of no-    │   │
│  │          signs" is a direct       │   │
│  │          articulation of sunyata  │   │
│  │ ▾ definition                      │   │  ← expanded
│  │   The Buddhist doctrine that all  │   │
│  │   phenomena are empty of inherent │   │
│  │   self-existence; reality is      │   │
│  │   relational and contingent.      │   │
│  │ [ Reject ]   [ Skip ]   [ Accept ]│   │
│  │              [ Reassign … ]       │   │
│  └───────────────────────────────────┘   │
│                                          │
│  ┌─ TAG 3 of 3 ──────────────────────┐   │
│  │ CONCEPT: divine_immanence     [1] │   │
│  │ LLM:     The Tathagata's nature   │   │
│  │          pervades all signs…      │   │
│  │ ▸ definition                      │   │
│  │ [ Reject ]   [ Skip ]   [ Accept ]│   │
│  │              [ Reassign … ]       │   │
│  └───────────────────────────────────┘   │
│                                          │
├──────────────────────────────────────────┤
│  Chunk-level (3 remaining):              │  ← see §5.4
│   [ Accept Remaining (3) ]               │
│   [ Reject Remaining (3) ] [ Defer (3) ] │
└──────────────────────────────────────────┘
```

Format rules:

- The chunk header (CHUNK / SECTION / BODY) renders once at the top of the card with the `=` and `-` rules from the CLI. Same 9-char field column.
- Each pending tag is a sub-card stacked vertically inside. They scroll within the chunk card on long chunks.
- **Score badge** sits on the right of the CONCEPT line as a colored pill: 3=green, 2=blue, 1=amber, 0=red. The colors are the primary visual signal — at a glance the reviewer can see "this chunk got two 3s and a 1" before reading any text.
- Tag ordering within a chunk: `score DESC, id ASC` (the model's most confident call first). Audits the model's confidence gradient top-down.
- Each tag's concept definition is **collapsed by default** behind a `▸ definition` toggle. Tapping expands inline (`▾ definition` + the prose). This is the drill-in for adjudication — when you need to decide between `apophatic_theology` and `divine_transcendence` you tap to read the full definition without leaving the chunk view. The collapsed default keeps the card scannable; the expansion is one tap and never leaves the card.
- For `is_new_concept` rows: the `CONCEPT:` line renders as `concept_id (proposed)` in italic, and the `▸ definition` toggle shows `new_concept_def` instead of the (nonexistent) live definition. A small "PROPOSED CONCEPT — review carefully" note above the action buttons signals the higher-stakes decision.
- Long chunk bodies (>1.5k chars) collapse to first ~400 chars with a `▾ show more` toggle. Most chunks are well under this; the toggle is the escape hatch.

**Reading patterns this enables that the CLI couldn't:**

- *Cross-tag inference.* Looking at all three tags above, the reviewer can see the model's interpretive arc: it called the apophatic move (3), correctly extended that to sunyata (3), then over-reached into divine_immanence (1, dubious — Buddhism doesn't have a divine in that sense). The score-1 reject is informed by the first two accepts in a way it couldn't be in isolation.
- *Spot the absence.* Reading the body, you might think "this chunk is also doing `non-duality` and the model didn't tag it." That observation is impossible in the CLI's per-tag view. (For now, this is a manual note in the user's head; v1 doesn't surface a "propose missing tag" affordance — see §9.)
- *Concept-vs-concept arbitration.* When two tags compete for the same passage element (e.g. `apophatic_theology` vs `divine_transcendence`), expanding both definitions side-by-side resolves it.

#### 5.3.1 Concept definition drill-in

The concept definition is the authoritative reference for adjudicating edge cases. Headlines and `concept_id` strings aren't enough — when you're deciding between `gnosis_direct_knowledge` and `mystical_union`, the actual prose definition is what tips the call. The CLI inlines it (`DEF: ...` field) which is fine for terminal width but crowds the chunk-grouped card where 3-7 tags share screen real estate.

**Behavior:**

- Each tag sub-card has a `▸ definition` toggle directly below the `LLM:` justification.
- Tap to expand inline (`▾ definition` plus the prose). Other tags' definitions are unaffected — each can be expanded or collapsed independently.
- Multiple definitions can be open simultaneously. This is the explicit purpose: side-by-side comparison of two competing concept defs is exactly what unsticks ambiguous cases.
- State is **per-tag, per-card-instance** — when the chunk advances, the next chunk's tags load with all definitions collapsed. The reviewer's expansion choices don't persist across chunks. (Persisting them would create UI debt — a stale "this concept's def is open" flag that becomes confusing fast.)
- For `is_new_concept` rows, the same toggle shows `new_concept_def` — the LLM's proposed definition for the new concept. The toggle label changes to `▸ proposed definition` to signal the difference.
- Optional: a small `↗` icon next to the concept name opens the concept's full node detail in a sheet (other chunks expressing this concept, total live edge count, sibling concepts). Defer to v1.1; the inline expansion handles 95% of the need.

**Why inline-expand instead of a modal or sheet:** Modals interrupt reading flow. Sheets cover the chunk body. The reviewer needs the body, the LLM justification, *and* the concept def all on screen at the same time to resolve ambiguity. Inline expansion is the only layout that achieves this on a phone screen.

### 5.4 Action mechanics

**Per-tag actions** (the per-row buttons inside each tag sub-card):

- **Accept** → POST action immediately, the tag sub-card collapses with a small "✓ accepted" indicator. Queue counter `+1`. The chunk card stays on screen until the user advances.
- **Reject** → same, with "✗ rejected" indicator.
- **Skip** → no API call, the tag sub-card greys out with "skipped this session." Stays on screen so the user remembers they punted on it.
- **Reassign** → opens a bottom sheet with searchable concept list. Sources: `GET /api/concepts`. Picker shows `concept_id` + `label` + first line of `definition`. Selecting a concept POSTs the action; dismissing the sheet without selection is a Cancel — no API call, sub-card unchanged. (Diverges from CLI; see §1 deviations.)

When all of a chunk's tags have an action queued (accepted, rejected, skipped, or reassigned), the **Next Chunk** button appears at the bottom of the card. The chunk does not auto-advance — explicit advance lets the reviewer re-check decisions before moving on.

**Chunk-level actions** (the row at the bottom of the card). Button copy is **dynamic** — it always shows the count of tags the action would actually affect, so the reviewer never wonders whether a chunk-level tap will overwrite earlier per-tag decisions:

- **Accept Remaining (N)** → posts `accept` for every still-pending tag in the chunk. Confirmation is a 3-second undo toast at the bottom of the screen ("Accepted 3 tags · Undo"). Designed for the case where the reviewer reads the chunk, agrees with the model's full take, and wants to commit everything in one tap. Cheapest natural batch operation at the right granularity (one chunk = one shared context).
- **Reject Remaining (N)** → same, with `reject`. For chunks where the model's whole take is off — usually because the chunk is meta-content (table of contents, citation, fragmentary) that shouldn't have been tagged at all.
- **Defer Remaining (N)** → marks every still-pending tag in this chunk as session-skipped and advances. Replaces the awkward CLI workflow of skipping each tag individually. No DB write — same semantics as per-tag skip, just batch.

Chunk-level actions only operate on tags that don't already have a queued action. If the reviewer has already accepted 2 of 3 tags individually, the chunk-level row reads `[ Accept Remaining (1) ] [ Reject Remaining (1) ] [ Defer Remaining (1) ]` — the count makes the targeting transparent. When N=0 the buttons are disabled and greyed. Rationale: surprise-overwriting an already-queued decision is exactly the sort of mistake that erodes trust in the tool.

**Gestures.** Swipe left on a tag sub-card → reject. Swipe right → accept. Threshold ~30% width with rubber-band resistance. Chunk-level actions are tap-only; no gesture for accept-all because the consequences are larger.

**Per-tag undo.** Long-press a tag sub-card to undo its queued action (only available before apply). Toast confirms.

### 5.5 Filter sheet

Mirrors CLI flags. Persists to URL params so `/filter` is bookmarkable per session.

- Tradition: chip selector populated from `/api/traditions`.
- Text: chip selector populated from `/api/texts?tradition=...`. Disabled until tradition is chosen.
- Concept: free-text + autocomplete from `/api/concepts`. **Semantics differ from the CLI** — instead of "show me only this concept's tags," the chunk-grouped view shows "chunks that have at least one pending tag for this concept (and all their other pending tags too)." This is intentional; auditing one concept in isolation re-introduces the per-tag fragmentation the chunk view exists to fix. Documented inline in the filter sheet UI ("Shows chunks where this concept appears, with all the chunk's pending tags").
- Min score: slider 0–3, default 1 (matches CLI default). Filters which tags are visible *within* a chunk and which chunks appear at all (a chunk with no tag at or above min_score doesn't appear).

### 5.6 Apply screen

- Header: "X queued actions · Y reviewer · Z chunks affected"
- **Virtualized** scrollable list of queued actions, newest first. At 15k scale a session might queue several hundred actions; never render them all in one DOM tree. Use `react-window` or equivalent. Each row: section label, concept, action (color-coded), undo button.
- Group-by-tradition collapsible sections so a 300-action queue is browsable.
- Footer: big primary button **Promote N to live graph**. Disabled if N=0.
- On tap: confirmation modal showing exact counts ("This will create up to N new EXPRESSES edges in `data/guru.db`. Continue?"). Yes → POST `/api/apply` with a fresh `client_action_id`.
- Result screen: "Applied 47 actions. 2 were already resolved by another tool. 0 errors." Plus a link to start a new review batch.
- **No "select all reject" or batch shortcuts.** Each queued row was an individual decision; bulk-modifying after the fact undermines the per-row review intent. Undo is per-row only.

### 5.7 Reviewer device ID

On first launch the app prompts: "Name this device for review attribution." Stored in IndexedDB. Sent on every action POST as `reviewer`. Suggested defaults based on user-agent: `ivy-phone`, `ivy-tablet`, `ivy-laptop`. Editable in `/settings`.

### 5.7.1 Session resumption (15k scale)

Sessions will span days and devices. Two pieces of state matter:

**1. Filter state.** Persisted in URL params (already covered in §5.5). Reload restores filter. Bookmark-friendly.

**2. Deck position.** Stored per-device in IndexedDB as the last `next_cursor` returned by `GET /api/chunks` (the chunk-keyed cursor from §4.6). The IndexedDB key is `cursor:<filter_hash>` where `filter_hash` is the same canonical hash used by the server-side count cache (§4.6) — switching filters loads a different cursor, no cross-contamination. Reviewer scoping is implicit (each device has its own IndexedDB). On launch, if a saved cursor exists for the current filter, the deck loads from that cursor instead of the top of the pool. UI shows a small banner "Resuming from your last position" with a one-tap "Start from top" override.

Position is **not** synced across devices — phone and laptop have independent positions. This is intentional: cross-device sync requires conflict resolution and the cost outweighs the benefit. The reviewer mentally maintains "phone is on Buddhism, laptop is on Gnosticism" easily enough.

Skipped tags never persist — same as CLI. Skip is purely a session-local "advance without writing."

**Resumption interaction with the queue.** Queued actions (in `review_actions` with `applied_at IS NULL`) live server-side and are visible across all devices. When the laptop opens the app, it sees actions queued from the phone session and can apply them. Position is per-device, queue is shared. This is the right asymmetry: position is "where am I reading" (personal), queue is "what have I decided" (shared).

### 5.7.2 Session stats drawer

Tapping the total-pending counter in the header opens a drawer with:

- Today: N accepted, M rejected, R reassigned, S skipped
- All-time on this device: same breakdown
- Current rate: tags/minute over last 10 minutes
- ETA at current rate: hours remaining for the active filter

Useful at 15k where stamina matters; trivial UI cost. State derived from `review_actions` server-side, scoped by reviewer.

### 5.8 Offline & connection drops

- App shell (HTML/JS/CSS) is cached by SW so the UI loads even on flaky cell.
- API calls are not cached. If a POST action fails (offline / 5xx), the action is held in an in-memory queue and retried with backoff. The user sees a small "queued locally — 3 actions waiting" indicator. As soon as the server is reachable, queue drains.
- Idempotency keys (`client_action_id` minted before retry loop starts) make retries safe.
- If the app is force-closed with unsynced local actions, they're persisted to IndexedDB and replayed on next launch.

---

## 6. Project Layout

```
guru-review/
├── README.md
├── package.json                  # workspaces: server, web
│
├── server/
│   ├── package.json
│   ├── tsconfig.json
│   ├── config.example.json
│   └── src/
│       ├── index.ts              # bootstrap, snapshot, mount routes, serve web/dist
│       ├── config.ts             # load + validate config
│       ├── db.ts                 # ro/rw handles, prepared statement set
│       ├── schema.ts             # CREATE TABLE review_actions IF NOT EXISTS
│       ├── snapshot.ts           # online backup + integrity check + manifest + prune
│       ├── chunkBody.ts          # load_chunk_body port + LRU
│       ├── apply.ts              # the apply transaction
│       ├── routes/
│       │   ├── tags.ts
│       │   ├── queue.ts
│       │   ├── apply.ts
│       │   ├── concepts.ts
│       │   ├── traditions.ts
│       │   └── stats.ts
│       └── lib/
│           ├── time.ts           # nowIso()
│           └── errors.ts
│
└── web/
    ├── package.json
    ├── vite.config.ts
    ├── tsconfig.json
    ├── index.html
    ├── public/
    │   ├── manifest.webmanifest
    │   └── sw.js
    └── src/
        ├── main.tsx
        ├── App.tsx               # router
        ├── api/
        │   ├── client.ts         # fetch wrapper, idempotency, retry queue
        │   └── types.ts
        ├── state/
        │   ├── reviewer.ts       # device id from IndexedDB
        │   ├── filters.ts        # URL-synced filter state
        │   ├── cursor.ts         # per-device chunk cursor in IndexedDB
        │   └── queue.ts          # local retry queue
        ├── screens/
        │   ├── Deck.tsx          # chunk-grouped review deck
        │   ├── Queue.tsx
        │   ├── Filter.tsx
        │   ├── Settings.tsx
        │   └── ApplyResult.tsx
        ├── components/
        │   ├── ChunkCard.tsx     # chunk header + body + stacked TagRows
        │   ├── TagRow.tsx        # one pending tag with concept-def expand
        │   ├── ConceptDef.tsx    # collapsible def block
        │   ├── ScoreBadge.tsx
        │   ├── ConceptPicker.tsx # bottom sheet for reassign
        │   ├── ChunkActions.tsx  # accept-all / reject-all / defer row
        │   ├── HeaderBar.tsx
        │   └── ThumbRow.tsx      # per-tag accept/skip/reject + reassign
        └── styles/
            └── globals.css        # Howm-aesthetic tailwind base
```

---

## 7. Implementation Order

Each step is a coherent commit boundary.

1. **Repo skeleton.** `pnpm init`, workspace layout, tsconfigs, lint config.
2. **`db.ts` + `schema.ts`.** Open both handles against a real `guru.db`, run `CREATE TABLE review_actions IF NOT EXISTS`. Verify on Ivy's actual DB. **Deliverable:** server boots, schema applied, no rows touched.
3. **`snapshot.ts`.** Online backup via `db.backup()` + integrity check + manifest write + prune. Fail-on-error: server refuses to start if either the copy or the integrity check fails. **Deliverable:** restart server, see new `guru-<ts>-pre-session.db` and `.manifest.json` pair in `~/guru-backups/`.
4. **GET endpoints.** `/api/health`, `/api/stats`, `/api/traditions`, `/api/texts`, `/api/concepts`, `/api/chunks`. Hit them with curl. **Deliverable:** can fetch a real chunk with its full set of pending tags and concept definitions, body included.
5. **POST action.** `/api/tags/:id/action` with zod validation, idempotency, dedupe. **Deliverable:** curl posts a queued action; row visible in `review_actions`; second curl with same `client_action_id` is a no-op.
6. **DELETE action + GET queue.** **Deliverable:** can list and undo queued actions.
7. **Apply transaction + parity harness.** `/api/apply` and `/api/apply/preview`. Build the apply transaction itself, then build an automated parity harness alongside it: a Python+TS test runner that takes a fixed decision sequence (~20 mixed accept/reject/skip/reassign actions covering each branch including `is_new_concept=1`), runs it through `review_tags.py` against shadow DB A and through the web tool's apply against shadow DB B (both seeded identically), then asserts row-content equivalence per the §10 acceptance criterion (excluding AUTOINCREMENT ids, timestamps, reviewer). The harness lives at `tests/parity/` and runs in CI for both repos; whichever side changes its SQL must update the harness fixture in the same PR. **Deliverable:** harness green, end-to-end CLI parity asserted automatically rather than manually.
8. **Web shell.** Vite + React + Tailwind, `App.tsx` routing, header bar with stats. **Deliverable:** load `/` on phone, see counts.
9. **ChunkCard + Deck.** Renders one chunk with stacked tag sub-cards in CLI format, per-tag and chunk-level action buttons hooked up to API client, concept-def inline expansion. **Deliverable:** review a chunk's worth of tags on phone, see them appear in `/queue`.
10. **Filter sheet, concept picker, settings.** **Deliverable:** filtered review session works end-to-end.
11. **Apply screen.** Preview, confirm modal, result screen. **Deliverable:** queued batch promotes successfully on shadow DB.
12. **Service worker + manifest.** Install-to-home-screen works, app shell cached.
13. **Local retry queue.** Force airplane mode mid-session; reconnect; queue drains.
14. **Real run.** Switch off `dry_run`, snapshot, do a small batch (~20 tags), audit. If clean, proceed.

---

## 8. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Apply transaction has a logic bug that mislabels tier | Step 7 validation against CLI byte-diff; first session is dry-run on shadow DB |
| Snapshot disk fills up | `KEEP_BACKUPS` cap (default 20); prune on every startup; ~1.6GB ceiling at 80MB/snapshot |
| Concurrent CLI run during web session | Apply transaction re-checks `staged_tags.status` per row, treats already-resolved as no-op |
| `client_action_id` collision (UUID v4 collision is astronomically improbable but worth thinking about) | UNIQUE constraint catches it; error surfaces clearly |
| `corpus/` files moved or chunk_id resolution fails | UI shows `(body unavailable)` placeholder; user can still review by chunk_id + concept; resolver mirrors `guru/corpus.py:resolve_chunk_path` exactly |
| Phone battery dies mid-session | Queued actions persist server-side in `review_actions`; resume next session from saved cursor (§5.7.1) |
| Server crashes mid-apply | `db.transaction()` rolls back; queue intact; rerun apply |
| Reviewer accidentally taps Apply with wrong filters in queue | Confirm modal shows exact counts and a sample of affected chunks |
| At 15k scale, `OFFSET` pagination on the read query becomes O(N²) | Keyset pagination on `(tradition_id, chunk_id)` for the chunk-grouped outer query (§4.6); supporting compound index `idx_staged_tags_status_chunk` added by `schema.ts` |
| Reviewer fatigue at 15k scale leads to rubber-stamping | Session stats drawer surfaces accept rate; if all-3s for 50 in a row, soft prompt to take a break (consider for v1.1) |
| Corpus or DB schema changes upstream (e.g. v3 provenance migration) break server | Server validates schema fingerprint on startup against a known-good list; fails loudly on mismatch with hint to update tool |

---

## 9. Open Questions

These can be resolved during implementation; flagging now:

1. **Concept picker scope.** Live nodes only (~44), or include staged-but-unaccepted concepts from `staged_concepts`? CLI accepts arbitrary free text. Default: live nodes + free-text fallback for compatibility, free-text creates `is_new_concept = 0` reassign rows (matches CLI).
2. **Session-local skip hide (deferred to v1.1, not punted).** CLI's skip is session-only and the web tool matches that for v1. But across 2.5k pending tags with thousands of skips possible, repeatedly seeing the same low-confidence tags every deck reload will get annoying. v1.1 should add a per-device IndexedDB-backed "skipped this session, hide for 24h" filter — purely client-side, no server schema change, no DB write. Defer to v1.1 to keep v1's parity story tight.
3. **Justification editing on accept.** Sometimes the LLM's justification is fine but slightly off. Allow editing before accept? Default: no for v1, match CLI exactly. Add later if useful.
4. **"Propose missing tag" affordance.** The chunk-grouped view makes it obvious when the LLM missed a concept the reviewer thinks belongs (§5.3 reading patterns). Should v1 have a "+ propose tag" button on the chunk card that creates a new pending `staged_tags` row with `score=null` and a reviewer-supplied justification? Default: no for v1 — adds a write path, requires its own review semantics. Note for v1.1.
5. **Chunk-level Accept Remaining confirmation.** Currently spec'd as a 3-second undo toast. Should it require an explicit confirmation modal instead (matching the apply screen's modal)? Tradeoff: modal slows the common case, toast risks accidental accepts. Default: 3-second toast, no modal. Revisit if accidents happen.
6. ~~**What about chunks where every pending tag is min_score=0?**~~ **Resolved.** `SELECT COUNT(*) FROM staged_tags WHERE score=0 AND status='pending'` returns 0 against the live DB. No score-0 pending tags exist; default `min_score=1` hides nothing. The slider is exposed for forward-compat with future tagging passes that might emit score-0 rows.
7. ~~**Populate `nodes.definition` on accept of `is_new_concept` rows?**~~ **Resolved** by `todo:bdbdccd5` (commit 35d448a). The CLI's `promote_to_expresses` was updated to upsert with `COALESCE(nodes.definition, excluded.definition)` — the LLM-proposed `staged_tags.new_concept_def` now lands on the new concept node, while pre-existing definitions (taxonomy-seeded concepts) are preserved. The web tool's `apply.ts` mirrors this exactly. Strict parity holds; no harness carve-out needed. Regression coverage at `tests/test_promote_definition.py` (5 tests).

---

## 10. Acceptance Criteria

The tool is done when all of the following hold:

- [ ] **Content equivalence with CLI.** On a fresh shadow DB seeded with the real `staged_tags`, applying a sequence of accept/reject/skip/reassign decisions through the web tool produces `staged_tags` and `edges` rows whose **content** matches what `scripts/review_tags.py` would have produced for the same sequence — comparing on `(chunk_id, concept_id, status, score, justification, is_new_concept)` for `staged_tags` and `(source_id, target_id, type, tier, justification)` for `edges`. AUTOINCREMENT `id`s, `reviewed_at`/`reviewed_by` and other timestamp/attribution columns are excluded from the comparison. Asserted by the parity harness in §7 step 7.
- [ ] Server refuses to start if the startup snapshot fails — either the `db.backup()` copy throws, or the post-copy `PRAGMA integrity_check` returns anything other than `'ok'`.
- [ ] No write path exists outside the prepared statement set in `db.ts`.
- [ ] Replaying the same `client_action_id` on POST action is a no-op, not an error.
- [ ] **Apply duplicate-POST safety.** A duplicate POST `/api/apply` with the same `client_action_id` after a successful apply is a safe no-op — it finds the queue empty, returns `{ applied: 0, status: 'already_applied' }`, and does not re-run the transaction or corrupt state. (The phone is responsible for knowing what it queued; we do not cache and replay the prior result.)
- [ ] PWA installs to home screen on iOS Safari and Android Chrome.
- [ ] One hour of review on phone over tailscale produces the same number of queued actions as taps, modulo any explicit undos.
- [ ] Reviewer attribution: `staged_tags.reviewed_by` reads `ivy-phone` after a phone session, not `human`.
