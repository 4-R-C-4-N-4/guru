# Parity harness — guru-review web vs CLI

**Purpose:** asserts that the web tool's apply transaction
(`guru-review/server/src/apply.ts`) and the CLI's `promote_to_expresses`
(`scripts/review_tags.py`) produce **content-equivalent** rows in
`staged_tags` and `edges` for the same fixture decision sequence.

Per `docs/web-review/design.md` §10 #1 and `docs/web-review/impl.md` P7b.

## Layout

```
tests/parity/
├── fixtures/
│   ├── seed.sql               # 30-row representative slice (chunks + staged_tags + nodes)
│   └── decision_sequence.json # ~20 mixed actions covering every branch
├── runners/
│   ├── run_cli.py             # apply via review_tags.py against shadow A
│   └── run_web.ts             # apply via apply.ts against shadow B
├── compare.py                 # row-content diff per design §10
└── orchestrator.sh            # end-to-end: seed both shadows, run, compare, exit code
```

## What "content-equivalent" means

Comparison is **column-restricted**:

- `staged_tags`: compare `(chunk_id, concept_id, status, score, justification, is_new_concept)`.
  Excludes `id` (AUTOINCREMENT differs between runs), `reviewed_at` and `reviewed_by` (timestamp/attribution).
- `edges`: compare `(source_id, target_id, type, tier, justification)`.
  Excludes `id` and `created_at`.
- `nodes` (concept rows added by accepts): compare `(id, type, label, definition)`.
  Strict equivalence — including `definition`, since `todo:bdbdccd5` made the CLI populate it.

## Decision fixture coverage

Per impl.md P7b. Required cases:

- `accept` with score=3 → tier='verified'
- `accept` with score=1 → tier='proposed'
- `accept` with `is_new_concept=1` → concept node created with definition populated
- `reject`
- `skip`
- `reassign` to existing concept (mutate + spawn — verify spawned row content)
- `reassign` to free-text new concept_id
- Re-accept on the spawned-from-reassign row (multi-step interaction)

## Running locally

```bash
cd tests/parity
bash orchestrator.sh
```

Exit 0 = parity holds. Exit nonzero = mismatch (diff printed to stderr).

## When to re-run

Any PR touching:

- `scripts/review_tags.py` (especially `promote_to_expresses`)
- `guru-review/server/src/apply.ts`
- `guru-review/server/src/db.ts` (the prepared statement set)
- `guru-review/server/src/schema.ts`

must run this harness as a CI check. Failing harness blocks merge.
