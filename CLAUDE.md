@AGENTS.md

## Claude Code adapter notes

Everything that governs work in this repository is in `AGENTS.md`. This file
carries only what is specific to this harness.

- **`/guru-review-tags`** and **`/guru-review-edges`** drive ingest nodes 11 and
  14 through the review web app's HTTP API. Their judgement criteria are
  mirrored in `prompts/ingest/tag-review.md` and `prompts/ingest/edge-review.md`
  so the same review is possible without them. If the criteria diverge, the
  repository copy is authoritative — a rubric that only exists in a skill is the
  silo the workbook was built to drain.
- The review app must already be running (default `http://localhost:7314`). Ask
  the user to start it; do not start it unprompted.
- Adapters stay thin. A rule worth writing down belongs in a node file under
  `docs/ingest/`, where every harness and every human can reach it.
