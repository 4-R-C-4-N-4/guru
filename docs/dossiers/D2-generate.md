# D2 — generate

**Kind:** command

Walk the frozen plan in DAG order and fill the staging tables.

## Precondition

A frozen plan containing this work (D1).

## Action

```sh
python3 scripts/build_dossiers.py --generate [--work <work-id>] [--limit N] [--stage l1]
```

Stages, in dependency order: `l1` → `structure` → `l2` → `summary`, `context`,
`figures`, `terms`, `notes`. `--stage` runs one; omitting it runs the DAG.

Every node is idempotent — a pending or accepted row for
`(unit, model, prompt_version)` is skipped — so an interrupted run resumes by
being re-run. `--limit` bounds the number of generation calls.

## Output

- `staged_summaries` — level 1 per span, level 2 per work, level 0 folds only
  under a small-context provider
- `staged_dossier_fields` — `structure_entry` per span, plus `summary`,
  `context`, `key_figures`, `key_terms`, `reading_notes` per work

All `pending`. Nothing is live.

## Gate

```sh
python3 -m guru dossier status <work-id>
```

Checks that every planned span has an L1 summary — or, for a degenerate work,
that an L2 exists.

## Failure modes

**Generating L2 before reviewing L1.** Upstream inputs are **accepted rows
only**. An L2 whose L1s are all still `pending` has nothing to read and
produces nothing. The DAG is a real dependency, and D3 sits inside it rather
than after it — in practice you review L1, then generate structure and L2, then
review those.

**Expecting L1 rows for a degenerate work.** A work of a single span skips the
L1 tier entirely: no structure entries, no per-span summaries, straight to one
L2. Eleven of the 56 works are like this. Anything that requires an L1 per span
reports every small text as permanently unstarted.

**Assuming the session's model.** Provider and model come from the campaign
config and are recorded verbatim in each row. `claude-code` is headless Claude
Code; `local` is llama.cpp on the 3090. Never rely on a session default — the
`model` column is the provenance line, and a run under an unpinned model
corrupts it silently.

**Expecting folds under `claude-code`.** Level-0 fold rows and the
figures/terms map–reduce exist only to work around a small context window. They
activate when `input_budget > 0`. Under the current campaign there are zero
fold rows, and there should be.

**Forgetting that idempotency is version-keyed.** The skip check is
`(unit, model, prompt_version)`, so bumping a template version makes every
unpromoted span of every work look ungenerated — a `--generate --stage l1` run
after a bump regenerates *whole works*, not just the rows the bump was meant to
fix (the `l1-v2 → l1-v3` bump turned a 1-row fix for
`egyptian-heaven-and-hell` into 11 calls). For targeted remediation use
`--respin`, which regenerates only spans whose every row is rejected and feeds
the rejection note back as a corrective addendum. After a bump, never run the
bumped stage without deciding which behaviour you want.

**Reading a parse failure as a hard stop.** Contract validation follows the
`tag_concepts.parse_tags` pattern: reject-and-retry up to a limit, then
log-skip. The node stays ungenerated and a later run retries it. A skipped node
is not an error, but it also will not fix itself unless you re-run.

## Provenance

`scripts/generate_dossiers.py` (G5); design §1.3.1 on accepted-only upstream
inputs; §1.3.5 on folds; degenerate-work behaviour verified against the c5 plan
and the live DB.
