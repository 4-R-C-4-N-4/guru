# Cleanup review queue (staged_cleanups)

todo:b44966d0 · shipped 2026-07-23 · third queue alongside tags/edges.

## What it reviews

Model-proposed rewrites of malformed chunk bodies — the damage class the
readability audit (docs/summary/readability-audit.md) left after the regex
passes: hard-wrapped prose (audit `hard_wrap` signal, currently the 40
mandaean gnostic-john-baptizer chunks). The task given to the model is
whitespace repair ONLY: join mid-sentence line breaks, rejoin end-of-line
hyphen splits, keep real paragraph boundaries. Every proposal carries a
mechanically computed `words_preserved` flag: the character stream minus
whitespace/hyphens must be identical to the original.

## Flow

1. `scripts/propose_cleanups.py` — audit-driven targeting (`--min-hard-wrap`,
   default 0.15), local model via scripts/llm.py (default ollama/qwen3:8b),
   stages into `staged_cleanups(status='pending')` with provenance
   (model, prompt_version=v1) and the partial-unique pending index.
2. **guru-review `/cleanups` deck** — BEFORE/AFTER card with the
   words-preserved badge and the mechanical diff note. Actions:
   - **Accept** — queue the rewrite (button disabled when the model
     drifted; apply refuses those regardless).
   - **Reject / Skip** — as in the other decks.
   - **Apparatus…** — reclassify → `apparatus_drop`: "this whole chunk is
     editorial apparatus (footnote block, errata, front-matter)". On apply
     the row becomes `status='apparatus'` — an accumulating,
     reviewer-confirmed drop-candidate list for todo:50438e23. Nothing is
     deleted by the queue.
3. **Apply gate** (`/queue` → POST /api/apply) — flips staged_cleanups
   status only (`accepted`/`rejected`/`apparatus`). The server NEVER
   writes the corpus.
4. `scripts/apply_cleanups.py --apply` — the corpus half, mirroring
   clean_bodies.py --apply: staleness check (TOML body must still equal
   original_body), words_preserved recheck, length-ratio guard, then TOML
   write + token_count recompute + nodes.metadata_json mirror +
   `applied_at` stamp. Prints the embed_corpus/export follow-up commands.

## Schema

`staged_cleanups` in scripts/schema.sql; live DBs migrate via
`scripts/migrations/v3_008_cleanup_review.sql` (also recreates
review_actions with the third CHECK branch: actions accept/reject/skip/
reclassify, reclassify_to constrained to 'apparatus_drop').

## Querying the apparatus hand-off list

```sql
SELECT chunk_id, reviewed_by, reviewed_at
FROM staged_cleanups WHERE status = 'apparatus' ORDER BY chunk_id;
```
