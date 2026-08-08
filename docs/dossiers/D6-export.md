# D6 — export

**Kind:** user

Ship. **This node belongs to the user**, exactly as ingest node 15 does.

## Precondition

Every work through D5.

## Action

Building `export/guru-corpus.sql.gz` locally is fine — it is a local artifact
and it validates the corpus end to end. Shipping it is not yours.

Regardless of how broadly the instruction was phrased:

- Do not run `scripts/sync_corpus.sh`.
- Do not ssh to the production VPS.
- Do not push `main` in `guru` or `guru-web`. Branch, `gh pr create`, reset
  local `main` to `origin/main`.

## Output

The user's decision.

## Gate

The user's.

## Failure modes

**Exporting with a summary gap.** `export.py` raises on any `summary_node`
without an embedding rather than emitting a partial artifact. Fix D5; do not
work around it.

**Exporting mid-review.** A work with pending rows has no live dossier, so it
exports as a text with no document-knowledge layer at all — silently, because
absence is a valid state. Check `guru dossier survey` before building the
artifact; 17 of 56 works are currently in that condition.

**Assuming a merged PR is a deployed corpus.** Corpus sync to production rides
the user's own push. Merged and live are different states.

## Provenance

`scripts/export.py`; the standing publication constraints, recorded here so
they survive independently of any one harness's configuration.
