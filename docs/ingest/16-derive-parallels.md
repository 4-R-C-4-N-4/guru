# 16 — derive-parallels

**Kind:** command

Grade every chunk against each concept it (or a cross-tradition peer) has an
accepted tag for, and rank each chunk's cross-tradition partners off those
grades. This is the corpus's PARALLELS supply now — it replaces Pass C
(retired [13-propose-edges](13-propose-edges.md) /
[14-edge-review](14-edge-review.md), decision record todo:c3f479ff).

**This node is not per-text.** Every other node in this workbook runs against
one `<source-id>` and has a `guru ingest status <source-id>` gate. This one has
no `--text` flag — it reads the whole `edges` table's `EXPRESSES` rows and
regrades the corpus in one pass. Run it after a batch of texts clears node 11,
not once per text. It is deliberately **not** wired into `guru/ingest.py`
(`NODES_BY_KEY` has no `16-derive-parallels` entry, and todo:aaaa5258, which
removed nodes 13/14 from the per-text precondition chain, left it that way on
purpose) — the `Ctx`/`evaluate()` machine in that module is built around one
`<source-id>` at a time, and a corpus-wide, no-`--text`, no-per-source-gate
step has no natural slot in it. `15-publish`'s precondition now runs straight
from node 12 to this node's absence: nodes 01–12 satisfied is enough to reach
publish, and node 16 is run separately, by an operator, on the corpus-wide
schedule described below. `guru ingest status <source-id>` no longer names
node 13 either way — it and node 14 are gone from the graph, not merely
skipped.

## Precondition

- **Applied EXPRESSES edges, any tier.** The generator reads the live `edges`
  table (`type='EXPRESSES'`) directly — not `staged_tags` — and does not
  filter on `tier`. A text's tags only count once node 11's queue has been
  applied by the user; a text sitting in review contributes nothing yet, and
  does so silently (no per-text readiness check exists here — see Failure
  modes). "Applied," though, is not the same as "human-verified": as of this
  writing ~29% of the live EXPRESSES supply (11,057 of 38,457 rows) is
  `tier='proposed'` — auto-promoted by `scripts/auto_promote.py` (deleted
  2026-08-14, todo:68028d8f) without
  per-row human review, before that tool was retired 2026-05-26. Whether this
  generator should restrict itself to `tier='verified'` is a live, explicitly
  unresolved question tracked at todo:dd034dc4 (the tier-semantics
  decision — is `tier` a confidence signal or a provenance timestamp?). This
  node reads every tier today; if that ticket lands on "confidence signal,"
  `load_expresses()` in `scripts/derive_parallels.py` needs `AND
  tier='verified'` added and this bullet updated to match.
- **Taxonomy.** `concepts/taxonomy.toml`, synced to `guru.db` (node 09's
  `sync_taxonomy.py --apply`). Concepts absent from the taxonomy cannot anchor
  a panel even if a chunk was somehow tagged with them.
- **Student checkpoint.** The thin (query, chunk) relevance scorer, vendored
  at `~/programs/guru/scorer-v1` and pinned by path (and a `model_sha256` of
  the weights file) in `config/derived_parallels.toml` `[scoring]`. It is a
  22.7M-parameter cross-encoder distill, not the 4B/27B taggers or the 24B
  proposer — see `~/programs/guru/scorer-v1/training-card.json` for lineage.
- **Apparatus flags applied, not merely queued.** `staged_cleanups` rows with
  `status='apparatus'` are excluded from both EXPRESSES indexes before
  scoring (todo:495577b7). `status='pending'` rows are not a fact yet and are
  correctly ignored — the owner's apply gate is what turns a candidate into an
  exclusion.
- No dependency on node 12 (embed). Unlike Pass C, this generator does not
  candidate-select off vector similarity — it scores every (concept, chunk)
  pair the taxonomy and the accepted tags put in scope.

## Action

```sh
OMP_NUM_THREADS=8 .venv/bin/python scripts/derive_parallels.py \
    [--config config/derived_parallels.toml] [--db data/guru.db] \
    [--out data/derived_parallels/<UTC timestamp>] \
    [--limit-concepts N] [--verbose]
```

CPU is the only path here, not a fallback of last resort: `guru/rerank.py`
does no device placement, so this node cannot be routed at either card and a
CUDA pin on it is inert. Budget ~10 minutes for a cold full-corpus run (measured
2026-08-14) and give it `OMP_NUM_THREADS=8`.

The interpreter above is not incidental. torch and transformers are an optional
group this repo installs into `.venv/` (see the README) — a bare `python3` has
neither, and because `guru/rerank.py` lazy-imports them, the run dies *after*
loading the database and taxonomy rather than at startup. Timings and what adding GPU support would take
are in [gpu-assembly.md](gpu-assembly.md) ("derive_parallels: the one CPU-only
exception") — not duplicated here.

Ranking, in brief (full logic in the script's docstring): a chunk's partners
are the cross-tradition chunks that best express its own accepted concepts,
ranked by the *partner's* score on the shared concept (not the weaker of the
two legs — min-leg clamping made panels monochrome in the prototype trial),
round-robinned across the chunk's via-concepts so one concept doesn't
monoculture a panel, and capped per source work (`config[panels].per_work_cap`,
default 2) so one prolific text doesn't fill every partner slot.

## Output

`data/derived_parallels/<UTC timestamp>/edges_derived.jsonl` (one JSON object
per derived edge — `source`, `target`, `edge_type='PARALLELS'`,
`tier='inferred'`, `weight` = the partner's grade, `annotation` naming the via
concept) plus a `summary.json` (concept/pair counts, scoring time, the
`top_k`/`min_grade`/`per_work_cap` knobs the run used).

**Does not write `guru.db`.** No `derived_parallels` table exists yet —
materializing one is a documented future step, not this node's job. The
run-directory artifact is the interface to export, below.

## Gate

No `guru ingest status` entry exists for this node, by design (see above —
it does not fit the per-text state machine). Treat a run as done when:

```sh
ls -t data/derived_parallels/ | head -1                    # latest run dir
cat "data/derived_parallels/$(ls -t data/derived_parallels/ | head -1)/summary.json"
```

reports `chunks_with_partners` and `unique_edge_rows` in the range you expect
for the corpus's current tag coverage, and the run is fresh enough for
`scripts/export.py` to accept it — see the hand-off below, which enforces this
for real at hand-off time rather than leaving it a suggestion.

**The re-derive trigger.** Re-run after **any `EXPRESSES` change** (a node 11
apply — new accepted tags, a reassignment, or a rejection that removes one) or
**any taxonomy change** (a new concept, or an edited definition — the score
cache is keyed on a hash of the concept definition text, so an edit forces a
rescore of every chunk against that concept). There is no automatic trigger;
a driver or the owner runs it by hand after a batch lands. Because scoring is
cached per `(concept, chunk)`, a re-run only pays for what actually changed —
it is cheap to run more often than the corpus actually changes.

**The export hand-off.** `scripts/export.py` does not take a run directory on
the command line: it reads `config[export].derived_dir` (`data/derived_parallels`),
picks the lexicographically latest subdirectory (the timestamp format sorts
correctly), and uses that run's `edges_derived.jsonl` as the *sole* source of
PARALLELS rows in the corpus dump — CONTRASTS comes separately from a frozen,
curated snapshot (`config/frozen_contrasts.toml`, todo:6da4f965), not from this
node. Export refuses — loudly, not silently — if the run directory is missing,
`summary.json` is incomplete, or `generated_at` is older than
`config[export].max_age_days` (default 30). There is no override flag by
design: a stale artifact gets regenerated, not waved through. Run this node
again, not export with a stale run, if that guard trips.

## Failure modes

**Empty-via = untagged chunk, not an error.** A chunk with no accepted
`EXPRESSES` tags — or whose only tagged concepts don't clear
`config[scoring].min_grade` on the chunk's own leg — never enters the anchor
set and gets `panels[chunk] = []`. It shows up in `summary.json`'s
`chunks_total` but not `chunks_with_partners`. This mirrors node 10's
legitimately-tagless-chunk case (`plotinus-select-works-index`, 107 of 752):
a low `chunks_with_partners` ratio is a tag-coverage signal, not a generator
defect, and should send you back to node 11's queue depth, not to this
script's logic.

**Concept namespace mismatch: `concept.<id>` vs bare taxonomy keys.**
`concepts/taxonomy.toml` keys are bare (`emanation_hierarchy`); every graph
identity — `EXPRESSES` edge targets, `nodes.id` — is namespaced
(`concept.emanation_hierarchy`). `load_taxonomy()` applies the `concept.`
prefix on read specifically so the rest of the script never has to think about
the split again. Anything that queries around this script by hand — an ad hoc
`sqlite3` check, a config edit, a future caller — using the bare key against
`edges`/`nodes` will silently match nothing rather than error, because SQLite
does not complain about a `WHERE` clause that matches zero rows.

**Stale score cache after re-chunk — self-healing, but not free.** The cache
(`config[scoring].score_cache`) is keyed on `(concept, chunk)` and a content
hash of the concept definition plus the first 2400 characters of the chunk
body (`content_hash()` in the script). `clean_bodies.py` or a re-chunk that
changes a chunk's body text changes that hash, so a stale cache entry is
detected and the pair is rescored automatically on the next run — it does
*not* silently serve an old score against new content. The real cost is
running this node against **pre-clean** bodies: `chunk.py` output (node 06) is
dirty by construction (the same rule node 07's own failure-modes section and
the README's staleness note state), so scoring before node 07 runs spends a
scoring pass on content that is about to change and will be invalidated and
re-paid for once cleaning lands. Not wrong, just wasted work — run node 07
first.

**A partial run written to the default location silently replaces the real
one.** `export.py` selects the lexicographically-latest *complete* run
directory under `config[export].derived_dir` — it has no notion of how much of
the corpus a run covered. So a quick `--limit-concepts 3` sanity run, left in
the default `data/derived_parallels/`, becomes "latest" and ships its few
hundred PARALLELS rows in place of the full run's seventeen thousand. Nothing
errors: the artifact is well-formed, fresh, and non-empty, so every guard in
`load_derived_parallels()` passes. This came within one command of happening
twice during the port. **Always send a partial run somewhere else** —
`--out /tmp/.../smoke` — and keep the default path for runs you intend to
ship. `summary.json`'s `concepts` and `chunks_with_partners` are the fastest
way to tell afterwards which kind of run produced an artifact.

**A successful re-run proves nothing about the environment.** Once the score
cache is warm, every pair resolves from disk, `rerank._load()` is never
reached, and torch/transformers are never imported — so a run that completes
happily is not evidence that the optional dependency group is installed or
working. Anyone verifying an environment (new venv, new machine, a dependency
bump) has to force real scoring: point `config[scoring].score_cache` at a
throwaway path, or skip the script and score a pair directly —
`EDGE_RERANK_MODEL=~/programs/guru/scorer-v1 .venv/bin/python -c "from guru
import rerank; print(rerank.score_pairs('q', {'a': 'body'}))"`. A relevant
pair should land well above `min_grade` and an unrelated one far below it.

**Pinning this node at a GPU appears to work and does nothing.**
`guru/rerank.py` performs no device placement anywhere — no `.to()`, no
`.cuda()` — so the model and its tensors stay on CPU regardless of the
environment. The `os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")` in
`_load()` only *hides* the cards; overriding it with the rig's usual
`CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=0` un-hides them and
changes nothing else. The run then proceeds at exactly CPU speed while the
command line claims otherwise, and `nvidia-smi` shows an idle card. Historical
"~7 min GPU" timings for this step belong to the rellm prototype, which had
its own GPU scoring path; the guru port inherited none of it. See
[gpu-assembly.md](gpu-assembly.md).

**The wrong interpreter fails minutes in, not at startup.** torch and
transformers are an optional group living in `.venv/` (README), and
`guru/rerank.py` imports them lazily inside `_load()`. A bare `python3` run
therefore opens the database, loads the taxonomy, resolves the cache, prints
its pair counts, and only *then* dies on `ModuleNotFoundError` — far enough in
to look like a data problem rather than a missing dependency. Invoke this node
as `.venv/bin/python`.

**Local retrieval divergence.** `scripts/export.py` sources PARALLELS
exclusively from this node's output now (see the export hand-off above), but
`guru/retrieval_legs.py` still queries the live `edges` table's ~11,300
PARALLELS rows (the old Pass C output) at query time, in three places. A
local `guru query` run or a retrieval benchmark against `data/guru.db` is
therefore reading a different, older PARALLELS set than production serves —
silently, since both are well-formed rows. Tracked at todo:69682961 (PR #64
review finding 9); not yet fixed.

## Provenance

`scripts/derive_parallels.py`, `config/derived_parallels.toml`. Ported from
rellm `tools/derived_parallels.py` (todo:5620391a / parent todo:c3f479ff,
"retire Pass C: parallels become a derived table" — cost table and the
21/24 judged-good partner-recovery evidence live in rellm
`docs/edges/derived-parallels-proposal.md`). Apparatus gating: todo:495577b7.
Export hand-off and the frozen-CONTRASTS split: todo:6da4f965. Model
vendoring and the `~/programs/guru/scorer-v1` pin: todo:379722ec.
