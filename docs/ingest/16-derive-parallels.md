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
default 2) so one prolific text doesn't fill every partner slot. How many
*other* panels may then list a chunk as a partner — its incoming fan-in, which
none of the above bounds — is separately capped at `config[panels].max_fan_in`
(default 500), keeping the suitors that express the shared concept most
strongly; see the
fan-in note in Failure modes.

## Output

`data/derived_parallels/<UTC timestamp>/edges_derived.jsonl` (one JSON object
per derived edge — `source`, `target`, `edge_type='PARALLELS'`,
`tier='inferred'`, `weight` = the partner's grade, `annotation` naming the via
concept) plus a `summary.json` (concept/pair counts, scoring time, the
`top_k`/`per_work_cap`/`max_fan_in` knobs the run used, and
`fan_in_cap_edges_dropped` / `fan_in_cap_chunks_reduced` /
`fan_in_cap_chunks_darkened` — always written, 0 when the cap dropped
nothing).

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
for the corpus's current tag coverage, `fan_in_cap_chunks_darkened` is 0, and
the run is fresh enough for
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

**Empty-via = untagged or unscored chunk, not an error.** A chunk with no
accepted `EXPRESSES` tags — or whose only tagged (concept, chunk) pairs were
never actually scored (scoring didn't run for them, not that it ran and
scored low) — never enters the anchor set and gets `panels[chunk] = []`. It
shows up in `summary.json`'s `chunks_total` but not `chunks_with_partners`.
This mirrors node 10's legitimately-tagless-chunk case
(`plotinus-select-works-index`, 107 of 752): a low `chunks_with_partners`
ratio is a tag-coverage signal, not a generator defect, and should send you
back to node 11's queue depth, not to this script's logic. A low *score* on
a tagged concept is never the cause any more — see the removed-floor note
below.

`chunks_with_partners` is a **selection** statistic, counted from `panels`
before the fan-in cap runs, and it stays that way precisely so it keeps
answering the tag-coverage question above. What actually shipped is
`chunks_in_export`, counted from the final rows. The two are equal until the
cap darkens something — at `max_fan_in = 100` the first reads 5,054 while 353
of those chunks have no edge in `edges_derived.jsonl` at all. When they differ
the run line says so explicitly, and `fan_in_cap_chunks_darkened` is the
number to act on.

**There is no absolute score floor (removed 2026-08, todo:ac63de1a).**
`build_panels()` used to require a (concept, chunk) pair to clear
`config[scoring].min_grade` (-4.415) to anchor a panel or be picked as a
partner. That number was the thin scorer's calibrated operating point for a
different frame — (query, chunk) `EDGE_RERANK` relevance — carried over
unexamined when this script substituted a concept definition for the query,
and it was never re-derived for that substitution (parent todo:7427712c).
Measurement showed it was actively wrong on this frame, not merely
uncalibrated:
- Of 27,395 (concept, chunk) pairs a human VERIFIED at node 11, only 18.9%
  cleared -4.415 — the generator was discarding four-fifths of completed
  review work.
- Human-verified pairs cleared at 18.9%; unreviewed auto-promoted
  (`tier='proposed'`) pairs cleared at 22.6% — the score was very slightly
  *more* permissive toward tags nobody had reviewed, so it carried no signal
  about whether a chunk actually expresses a concept.
- Score clearance tracked passage length, not relevance: 12% for chunks
  under 500 chars vs 58% for 2,000–2,400 chars.
- Simulated effect of removal, over the existing score cache: chunks
  carrying a panel 2,364 -> 5,054; texts with any panel 166 -> 235.

The score remains the ranker — spot-checks confirm it still picks each
work's defining concept (`sunyata_emptiness` for the Diamond Sutra, `wu_wei`
for the Tao Te Ching, `sephirot` for the Lesser Holy Assembly) — it was only
the absolute cut that was wrong. Expect the consequence: panels are now
bigger and include weaker partners than before. `config[panels].per_work_cap`
manages one shape of that (a source chunk's own outgoing panel); the other
shape — a chunk's incoming fan-in — is covered next.

**Fan-in: nothing bounded how many OTHER chunks could pick a given chunk as a
partner (todo:38a01171, `config[panels].max_fan_in`).** `top_k`/`per_work_cap`
bound only a chunk's own *outgoing* panel. They say nothing about how many
*other* panels list that same chunk as a partner, and a chunk expressing a
common concept can be everyone's best partner on that concept at once —
removing the score floor removed the only thing accidentally suppressing it.
The v55 run surfaced a 1,178-partner panel
(`christian_mysticism.life-and-doctrines-boehme.016`) and a second at 1,159
(`plato-phaedrus.018`). guru-web's `LIMIT 100` read-time query (guru-web
todo:bc084b37) hid this from the UI but did not fix it: the exported
`edges_derived.jsonl` still carried the unbounded tail, so any other consumer
reading the export directly got it.

`cap_fan_in()`, applied by `run()` after `build_edges()`, bounds this in the
generated graph itself. It charges each edge only to the chunk *receiving* it —
the endpoint that did not anchor the panel — and, when a receiver is over
budget, keeps the suitors whose *own* leg on the shared concept is strongest.

**Rank by the anchor's leg, never by the row weight (todo:6310a495).** This is
the subtle part and the first implementation got it wrong. An edge's weight is
the *partner's* score on the via concept — so for a chunk receiving edges, it
is that chunk's **own** score, identical across every edge pointing at it. The
top v55 hub carried 1,178 incoming edges with **9 distinct weights, 1,170 of
them tied at −0.994**. Ranking by weight therefore fell straight through to the
`(source, target)` tiebreak and kept an alphabetical slice; 47% of all
deletions were of edges tied with a survivor. The measurable signature was that
kept and dropped edges had indistinguishable parallel strength (median anchor
leg −5.97 vs −5.91 — the selection was noise). Ranking by the anchor's leg
separates them properly: **−5.77 kept vs −7.07 dropped**, swapping 3,421 of
44,330 edges. This is *not* the min-leg clamping the port rejected — that was
about ranking a chunk's *outgoing* panel, where the partner's score is
correctly the signal. Choosing among a saturated chunk's *incoming* edges is a
different question, and the anchor's leg is the only leg that varies.

**The asymmetry is load-bearing, and the first cut got it wrong.** That
version charged *both* endpoints and skipped an edge when either was full,
which sounds equivalent and is not: it lets a chunk's own accumulated degree
veto its neighbours' edges. Replayed over v55 at 100, it cut 50,148 edges to
21,008 — only 129 chunks were ever over the cap, but 4,531 under-cap chunks
lost edges and 367 ended with none, handing back a large share of the coverage
the floor removal had just won.

**But the value matters more than the mechanism.** Correct fan-in at 100 gives
21,476 edges and 353 darkened chunks — a 468-edge improvement on the broken
version. The near-identical numbers are not evidence the rewrite was pointless;
both were swamped by a threshold that cannot fit the distribution. Median chunk
degree is 10, but **41,807 of 50,148 edges (83%) touch one of the 129 chunks
above 100**, so a cap of 100 offers those hubs 12,900 slots for 41,807
hub-bound edges and *must* delete most of the graph. Swept over the v55 cache
(edges kept / chunks left with no partners):

| `max_fan_in` | 1000 | 750 | 500 | 400 | 300 | 200 | 150 | 100 |
|---|---|---|---|---|---|---|---|---|
| edges | 49,830 | 48,168 | 44,330 | 41,613 | 37,713 | 31,120 | 26,769 | 21,476 |
| darkened | 0 | 0 | 0 | 0 | 3 | 48 | 134 | 353 |

Darkening — a chunk dropping out of the graph entirely — is the hard failure
and starts below 400. Uncapped p99 degree is 315, so the default of 500 bites
only the genuine outliers (max degree 1,178 -> 516) while keeping 88% of the
edges. If you retighten it, read `fan_in_cap_chunks_darkened`; any nonzero
value means chunks fell out of the graph. Two standing properties: a **mutual**
pair (both endpoints picked each other) is outgoing for both, so it is kept and
charged to neither — the real per-chunk bound is `|own panel| + max_fan_in`,
not `max_fan_in` — and the cap cannot promise a chunk keeps every partner it
picked, since every edge is incoming for *somebody*.

**Panel work-concentration is upstream of the cap, and mostly real
(todo:bd00679b).** A chunk's partners can cluster heavily in one source work:
`christian_mysticism.dionysius-divine-names-2.001` draws 189 of its 205
partners (92%) from `plotinus-select-works-index`. This is tempting to blame
on the fan-in cap and it is not the cap's doing — those figures are identical
in the uncapped run, and at degree 205 that chunk never reaches the 500 cap at
all. Across the 378 chunks with degree ≥ 20, mean top-work share moves only
0.315 → 0.333 under capping. `per_work_cap` bounds a chunk's *outgoing* panel
per work; incoming fan-in has never had a per-work bound, independently of any
degree cap.

Do not "fix" this by making the cap work-aware. Swept as a per-work fan-in
bound (edges kept / chunks darkened / mean top-work share, from 50,148 / 0 /
0.315): 50 → 42,320 / 57 / 0.296; 25 → 34,672 / 238 / 0.272; 10 → 23,957 /
730 / 0.192. Meaningful flattening costs coverage at the rate the score floor
did, and much of the concentration is genuine structure rather than noise —
Dionysius really is Neoplatonic. The cap therefore ranks on weight alone, and
`test_cap_fan_in_leaves_a_chunk_under_budget_completely_untouched` pins that.
If a per-work fan-in bound is ever wanted it belongs in selection
(`build_panels()`), not in the degree cap.

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
pair should score noticeably higher than an unrelated one — there is no
`min_grade` cut to compare against any more (see the removed-floor note
above); this is a sanity check on the model's *ranking*, not a threshold
check.

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
