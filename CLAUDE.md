@AGENTS.md

## Claude Code adapter notes

Everything that governs work in this repository is in `AGENTS.md`. This file
carries only what is specific to this harness.

- **`/guru-review-tags`** drives ingest node 11 through the review web app's
  HTTP API. Its judgement criteria are mirrored in
  `prompts/ingest/tag-review.md` so the same review is possible without it. If
  the criteria diverge, the repository copy is authoritative — a rubric that
  only exists in a skill is the silo the workbook was built to drain.
- Node 14 (edge review) is retired with Pass C — cross-tradition PARALLELS are
  now derived at node 16 (`docs/ingest/16-derive-parallels.md`), off applied
  tags (any tier), with no review queue. `/guru-review-edges` now only matters
  for the historical `staged_edges` queue, not new proposals.
- The review app must already be running (default `http://localhost:7314`). Ask
  the user to start it; do not start it unprompted.
- Adapters stay thin. A rule worth writing down belongs in a node file under
  `docs/ingest/`, where every harness and every human can reach it.
