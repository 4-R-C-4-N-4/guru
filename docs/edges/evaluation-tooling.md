# Edge evaluation tooling — what exists, and where it actually lives

Written 2026-08-14 (todo:7427712c) after an agent proposed building a
"selection-rule harness" from scratch for the derived-parallels threshold work.
Most of it already existed. None of it is discoverable from this repository,
which is the reason for this file.

**The short version:** guru owns the *retriever*; rellm owns the *evaluation*.
Nothing in guru points at rellm, so anyone working an edge question from inside
guru will conclude there is no tooling and start writing some.

---

## 1. What guru has

| thing | where | note |
|---|---|---|
| parity retriever | `guru/retriever.py` | the pipeline; `guru query` / `guru interactive` drive it |
| the legs | `guru/retrieval_legs.py` | explicitly "brought to guru-web parity"; read its header before assuming anything about drift |
| cross-encoder scoring | `guru/rerank.py` | CPU-only, no device placement (see `docs/ingest/gpu-assembly.md`) |
| eval scripts | **none** | `scripts/` has no `eval*`, `bench*`, or harness of any kind |

`retrieval_legs.py`'s header is the authoritative statement on how faithful the
sqlite path is: *"Not bit-exact with Postgres by intent — exact reproduction is
what `scripts/export.py` plus a docker staging DB is for. The goal is a
baseline that does not systematically flatter or starve any one leg."* Treat it
as a baseline, not as production.

### The toggles are the A/B surface

These exist so edge mechanisms can be measured rather than argued about. All
default off/neutral:

| env | effect |
|---|---|
| `EDGE_LEG=on` | chunk↔chunk PARALLELS/CONTRASTS partner hop. **guru-web has never had this leg** — its graph walk is concept↔concept. This toggle exists precisely because the pilot traversing it was the largest behavioural difference between the two systems |
| `EDGE_INHERIT=<weight>` | anchored score inheritance through PARALLELS (0/unset = off) |
| `EDGE_ANCHOR_MIN_MATCH` | anchor-quality gate for the inheritance term |
| `EDGE_RERANK` / `EDGE_RERANK_MODEL` / `EDGE_RERANK_THRESHOLD` | cross-encoder reranking of partners; threshold is **model-specific** |
| `GRAPH_LEG=off` | disable the concept graph leg |
| `RETRIEVAL_GRAPH_WEIGHT`, `RETRIEVAL_LEXICAL_WEIGHT` | leg weights, for sweeps |
| `RETRIEVAL_QUALITY_FILTER` | quality filter |

**A trap worth naming:** the concept↔concept reachability query includes
`type IN ('PARALLELS','DERIVES_FROM')`, which reads as though PARALLELS feed
concept expansion. They cannot — PARALLELS endpoints are chunk ids and can
never match a concept node id, and `DERIVES_FROM` does not exist in the corpus.
Seeing PARALLELS in that query and concluding "edges affect retrieval" is a
mistake that has now been made twice. With the toggles at their defaults,
edges do not enter retrieval in either system.

---

## 2. What rellm has (`~/Work/rellm/tools/`)

The whole edge evaluation apparatus. It drives **guru's** retriever — several
of these `os.chdir` into a guru checkout, selected by `EDGE_GURU_ROOT` so a
worktree can be targeted instead of the main checkout the owner works in.

| tool | what it answers |
|---|---|
| `edge_inherit_ab.py` | A/B arms (baseline / rarity-off / EDGE_INHERIT at several weights) per golden query, **through guru's parity retriever**. Writes `surfaced.jsonl` — the judgment set for grading |
| `edge_relevance_judge.py` | blind, shuffled three-strata grading (surfaced / baseline / random). This is the judgment that decides whether a mechanism ships |
| `edge_scorer_rungs.py` | can an off-the-shelf scorer separate relevant from not, before training anything |
| `edge_band_eval_set.py` + `edge_band_eval_collect.py` | build and grade a frozen **rank 6–50** eval set. See §3 — this is the most important one to understand |
| `edge_symmetry.py` | AB vs BA judge consistency; PARALLELS is symmetric so `f(A,B)` must equal `f(B,A)` |
| `edge_matrix.py` | cross-tradition outcome matrix with Wilson lower bounds, so small-n cells cannot read as 100% |
| `edge_curation_probe.py` | via-concept coverage of live edges; produced the 2,825-edge suspect queue |
| `edge_candidate_probe.py`, `edge_retrieval_novelty.py`, `edge_retrieval_sim.py`, `edge_label_repro.py` | candidate generation, novelty, similarity, label reproducibility |
| `derived_parallels.py` | the prototype `scripts/derive_parallels.py` was ported from |

Design records sit beside them in `~/Work/rellm/docs/edges/`:
`derived-parallels-proposal.md`, `thin-scorer-spec.md`, `query-scorer-rungs.md`,
`edge-roadmap.md`, `edge-process-audit.md`, `edge-review-pass.md`,
`edge-reranker-build-spec.md`. Run outputs are under
`~/Work/rellm/runs/edges/` — `relevance-judge/<ts>/` carries `judge.jsonl` and
`key.json`, `scorer/<ts>/` the ship-gate `FINDINGS.md`.

**rellm is the owner's sandbox.** Read it, mine it, cite it — but guru must not
acquire a runtime dependency on it. The model artifacts guru needs are vendored
to `~/programs/guru/` and the Python runtime is guru's own `.venv`
(`requirements-derive.txt`); see todo:5104d8c8 for why that separation exists.

---

## 3. The sampling bias this apparatus was built to dodge

`edge_band_eval_set.py` exists for a reason that will bite anyone evaluating a
new selection rule: **labels exist almost exclusively where the incumbent
looked** — rank ≤5, similarity ≥0.75, because that is the region the old
proposer sampled. Grading a new rule against the existing judged partners
therefore measures *agreement with the incumbent*, not quality, and a rule that
surfaces genuinely better material outside that region is scored down for it.

The correction already implemented is to sample the gated band (rank 6–50)
fresh and grade it blind. Any new work on selection rules should reuse that
pattern rather than re-deriving the mistake. Concretely: "how many of the 24
judged strict-relevant partners does my new rule still reach?" is a **necessary
but not sufficient** metric — it can only detect regressions against what the
old approach already found, and is blind to what it never looked at.

---

## 4. If you are about to build a harness

Check, in order:

1. `~/Work/rellm/tools/edge_*.py` — does one of them already answer this?
2. `~/Work/rellm/docs/edges/*.md` — has the question already been settled, and
   on what frame? Operating points are frame-specific: the thin scorer's
   −4.415 was calibrated on **(query, chunk)** relevance and does not transfer
   to **(concept-definition, chunk)** grading (todo:7427712c).
3. `~/Work/rellm/runs/edges/` — is there already a graded set you can reuse
   instead of spending human labelling time?
4. guru's toggles above — can the question be posed as an A/B on the existing
   retriever rather than as new code?

---

## 5. What the threshold work actually concluded (2026-08-15/16)

This file was written mid-investigation. The investigation finished; recording
the outcome here so the next person starts from it rather than re-opening the
question. Full record and the reproduction recipe:
[`../ingest/16-derive-parallels.md`](../ingest/16-derive-parallels.md).

**The −4.415 floor was removed entirely (todo:ac63de1a), not re-derived.** Only
18.9% of 27,395 human-*verified* (concept, chunk) pairs cleared it, against
22.6% for never-reviewed auto-promoted pairs — slightly *more* permissive
toward tags nobody checked. What it tracked was passage length (12% clearance
under 500 chars vs 58% at 2,000–2,400), not correctness. The score ranks; it
does not gate. Note what this leaves: **there is no quality filter on derived
PARALLELS at all today.** 83% of shipped edges carry a negative weight and
~1,300 sit below the old floor. That is the deliberate consequence of the
removal, not an oversight, and it is the open question — not the threshold.

**The replacement bound is on degree, not score (todo:38a01171).** Removing the
floor exposed unbounded incoming fan-in: one chunk reached 1,178 partners.
`config[panels].max_fan_in` (400) bounds how many *other* panels may list a
chunk as a partner. Three findings worth not rediscovering:

- **Charge only the receiving leg.** A degree budget charged to both endpoints
  lets a chunk's own accumulated degree veto its neighbours' edges — it deleted
  58% of the edge set and darkened 367 chunks, 4,531 of the losers never having
  been over cap.
- **The threshold mattered more than the mechanism.** 83% of edges touch the
  129 chunks above degree 100, so a cap near 100 must delete most of the graph
  regardless of how correctly it is implemented. Darkening starts below 400.
- **Rank by the anchor's leg, never the row weight (todo:6310a495).** The row
  weight is the *partner's* score, so for a chunk receiving edges it is that
  chunk's own score — constant across all of them. The top hub had 1,178
  incoming edges and 9 distinct weights. Ranking by it silently degenerated to
  alphabetical order for 47% of deletions. **This was invisible in every count
  metric**; what exposed it was comparing the median anchor leg of kept vs
  dropped edges (−5.97 vs −5.91 — noise; now −5.70 vs −6.94). If you change how
  partners are ranked, run that check.

The section 3 warning above applies to all of it: these are coverage and
discrimination measurements over the incumbent's own output. None of them
establishes that a derived parallel is *correct*. That still needs blind
grading on the (concept-definition, chunk) frame.
