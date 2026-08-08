# D4 — promote

**Kind:** gate

Assemble accepted staged rows into the live tables. Promotion *is* assembly —
the composed dossier does not exist anywhere before this point.

## Precondition

No pending rows for the work (D3), and the required fields accepted.

## Action

```sh
python3 scripts/promote_dossiers.py --work <work-id> --dry-run
python3 scripts/promote_dossiers.py --work <work-id>
```

## Output

- `work_dossiers` — one row per work
- `summary_nodes` — the retrievable L1/L2 tree, with `children_hash` for
  invalidation

## Gate

```sh
python3 -m guru dossier status <work-id>
```

Checks a live row exists and, for a non-degenerate work, that every planned
span has an accepted structure entry.

## Why this node has no apply gate

This node writes live tables directly. Everywhere else in the project that is
the user's action and never a driver's — `staged_tags` and `staged_edges` are
queued through the guru-review web app's HTTP API and drained by the user, and
`auto_promote` is never run on their behalf at any confidence tier.

Pass D sidesteps that on purpose. The standing preference is for DB writes to
sit behind an API with a queue-then-apply split; this stream is a deliberate
exception, justified by the expertise of the agent that drives it end to end.
It is not an inconsistency waiting to be closed.

Two practical consequences:

- **Do not add an apply gate here, and do not report its absence as a defect.**
  That decision has been made.
- **`--dry-run` first, every time.** It is the only checkpoint this node has,
  which makes skipping it a different kind of mistake than skipping a dry run
  somewhere that a human reviews the result afterwards.

If a new component ever needs to write to `guru.db`, the API-plus-queue shape
is the default to reach for — Pass D is the exception, not the template.

## Failure modes

**Expecting a partial dossier.** A work promotes only when `summary`, `context`
and a structure entry for every planned span have accepted rows. Degenerate
works need no structure. There is no partial state: the work is live or it is
absent.

**Overwriting a manual fix.** For each field the promoter takes the newest
accepted row, *preferring* rows whose `prompt_version` ends in `-manual`.
Manual fixes outrank any template version, and bulk regeneration never targets
them. If a hand-corrected field reverts, something wrote a `-manual` row it
should not have.

**Reading `themes_json` as edges.** It is derived at promotion from the work's
live `EXPRESSES` edges, tier-weighted with the runtime convention (verified
1.0 / proposed 0.7 / inferred 0.4), and it is `[]` below the five-tag floor. It
is display only. It is not an edge, it does not feed retrieval, and generating
it is not a tagging decision.

**Assuming promotion re-reads the corpus.** It reads accepted staged rows. If
the chunks changed after generation, the dossier describes the old ones —
`summary_nodes.children_hash` is the detector, and recomputing it is how you
find out.

## Provenance

`scripts/promote_dossiers.py`; design §1.1 "Promotion = assembly" and §6.1 on
the works layer; the tier weights mirror guru-web's `retriever.ts`.
