# biblical-asv (Genesis / John / Revelation) — Pass D decisions

Campaign **c11** (2026-09-22). The first `biblical`-tradition works through the
dossier stream, and the first Pass D run driven on **local llamacpp** (Qwen3.8
on the 3090) for brand-new works rather than claude-code. Owner's call:
`config/dossiers.toml` set `provider="llamacpp"`, `model="Qwen3.8-27B-UD-Q4_K_XL.gguf"`,
`input_budget=8000`. The c11 re-plan also reconciled the pre-existing
`blavatsky-sd` freeze violation (its span ids carried forward; no regeneration).

## The load-bearing finding: local Qwen overruns on dense scripture spans

Generation was clean on most spans but **failed on the densest ~5,400-token,
7-chunk spans** — one per book:
- `genesis-asv` 24:20–27:31, 31:33–36:12, 44:20–49:9
- `gospel-of-john-asv` 1:1–5:13, 5:14–8:23
- `revelation-asv` 1:1–8:2

Failure shape (same at L1, L2, and the L2-derived `reading_notes`): the model
produces ~770–860 tokens against the L1 sanity band `[budget*0.4, budget*2.4]`
= `[120, 720]` for a 300-token budget (`generate_dossiers._v_prose`), the
`compress-v1` retry **cannot** bring it down — its "keep EVERY distinct claim"
rule contradicts the ~214-word target on dense content (open bug
`b1c8be4c`) — and the fold fallback then trips the verbatim-echo guard (the
model copies scripture instead of transforming it), so the span **stages
nothing**. Not a serving mistake: the tagger and generate `run-*.sh` scripts are
byte-identical in sampling (temp 0.6, top_p 0.95, top_k 20, reasoning 2048).

**Owner hypothesis to bench later: a different generation temperature.** The
c8 grid-search (temp 0.6 wins) was on other content; dense verse-spans may want
a different point. Tracked as a ticket. Widening the shared `_v_prose` band was
rejected as the fix here — it has test coverage (`test_promote.py`) and is
corpus-wide, disproportionate to a localized failure on one net-new tradition.

## What was hand-authored (owner-authorized manual rows)

Because the failures were few and precisely localized, the proportionate fix
(D3 rung 3) was manual rows, not a template bump that would mass-regenerate the
corpus. All carry a `-manual` `prompt_version` and `model='manual'`:
- **3 L1 summaries** for the overrun spans above (written from the ASV source,
  in-band, independently reviewed and accepted by a separate agent).
- **3 corrected L1s** for D3 rejects (an order flip on Deborah's death; an
  over-asserted "Israel dies at 147" where the span only gives his age; a
  "dwelt among the speakers" garble of John 1:14 "dwelt among us").
- **8 structure titles** rebuilt from the accepted L1s. The generator clustered
  on a COVERAGE defect — token-grouped spans cross multiple episodes, and
  `structure-v5` picks one punchy title over one that samples the span's spread.
- **2 key_figures** augmented — the generator omitted **Lazarus** (John) and
  **Babylon/the great harlot** (Revelation), both major.
- **3 reading_notes** — brief structural guidance grounded in each outline.

The auto-generated `summary`/`context` fields passed review (context correctly
hedged: "no dating provided in the input").

## Cleanup note

Re-running `--generate` after inserting accepted `-manual` rows **regenerated
duplicates** (a rejected original does not block regeneration, and a `-manual`
accepted row is a different `(model, prompt_version)` than the `l1-v3`/`structure-v5`
skip check looks for). 13 duplicate pending rows were deleted (each had an
accepted authoritative sibling for the same unit) before D3 could show `done`.
Watch for this on any future manual-remediation + re-generate sequence.

## State at hand-off

D1–D5 complete for all three works; **D6 export is the owner's gate** (not run).
Live: `work_dossiers` ×3, `summary_nodes` 12/7/4, `summary_embeddings` for all 23.
