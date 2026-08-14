# 13 — propose-edges

> **RETIRED 2026-08-13.** Pass C (LLM pair classification) is replaced by a
> derived table — see [16-derive-parallels](16-derive-parallels.md). Decision
> record: todo:c3f479ff. This file is kept for history; do not run this node
> on new texts. `guru/ingest.py`'s `NODES` list no longer includes this node
> (todo:aaaa5258, landed) — `guru ingest status` walks straight from
> 12-embed to 15-publish. `propose_edges.py` carries a deprecation header;
> `scripts/run-mistral.sh`, which served the model behind every proposal
> below, has been removed (git history has it, if it's ever needed again).

**Kind:** command

Propose cross-tradition relationships between this text's chunks and the rest
of the corpus. Everything it writes is `pending`.

## Precondition

Embeddings exist for the text (node 12) — candidate pairs come from vector
similarity.

## Action

Retired — do not run. The commands below are kept verbatim as a historical
record of what this node used to do; `scripts/run-mistral.sh`, which the
first line depended on, no longer exists in this repo.

```sh
pgrep -af '[t]ag_concepts|[p]ropose_edges'      # must be empty — see node 10
scripts/run-mistral.sh                       # REMOVED — see banner above

python3 scripts/propose_edges.py --text <source-id> \
    --provider llamacpp --top-n 5 --min-similarity 0.75
```

`llm stop` when finished — but only if you started it (node 10).

## Output

`staged_edges` rows with `status='pending'`, typed `PARALLELS`, `CONTRASTS`,
`surface_only` or `unrelated`, with a confidence and a justification.

## Gate

```sh
python3 -m guru ingest status <source-id>
```

Counts staged edges touching this text on either side.

Pin it to the 3090 — [gpu-assembly.md](gpu-assembly.md).

**Serve Mistral, not a tagging model.** (Historical.) `Mistral-Small-3.2-24B-Instruct`
was `propose_edges.py`'s own default — the `--model` flag exists to *label*
provenance, and its help text still points at the now-removed
`scripts/run-mistral.sh`. That model produced every edge proposal in the
corpus. The launcher set near-greedy sampling (temp 0.15, top_p 1.0, top_k 0,
min_p 0, repeat_penalty 1.0), which is what made it classify rather than
agree. The model dir itself, `~/programs/mistral`, is unaffected by this
script's removal — see [gpu-assembly.md](gpu-assembly.md)'s "Model home"
section and todo:aaaa5258's close note for whether anything else in this rig
still depends on it.

## Failure modes

**Do not judge a fresh batch by its edge-type spread.** The proposer emits
`PARALLELS` almost exclusively, and that is correct behaviour, not a defect.
`surface_only`, `unrelated` and most `CONTRASTS` are **review outcomes** — they
arrive through the reclassify action at node 14, not from this node.

The corpus makes this unambiguous (`staged_edges`, 21,673 rows, 2026-08-09):

| edge_type | status | rows |
|---|---|---|
| PARALLELS | accepted / pending | 10,998 / 2,048 |
| surface_only | **rejected** | 8,338 — every one `reviewed_by` a reviewer |
| unrelated | **rejected** | 175 — likewise |
| CONTRASTS | reclassified / accepted / pending | 78 / 24 / 10 |

Counts drift with every ingest; the shape does not. Re-derive rather than
trust the figures, and date any you write down:

```sh
sqlite3 data/guru.db "
  SELECT edge_type, status, COUNT(*) FROM staged_edges
  GROUP BY 1,2 ORDER BY edge_type, 3 DESC;"
```

So comparing a new run's spread against the corpus-wide table compares
unreviewed output to reviewed output and will always look alarming. If you want
a health signal, compare against `status='pending'` rows only, which are also
overwhelmingly PARALLELS.

This entry exists because that mistake was made here on 2026-08-08: a 4B run's
207-of-208 PARALLELS was read as rubber-stamping and the batch was discarded on
that reasoning. The batch was worth discarding — `propose_edges.py` defaults to
Mistral for a reason — but the type spread was not the evidence.


**Proposals off dirty vectors.** If node 07 was skipped or went stale, the
candidate pairs are partly boilerplate similarity and the whole proposal set is
suspect. This is the failure that makes node 07's staleness check worth having.

**The 0.85 confidence tier.** `auto_promote_edges` promotes above its
threshold and leaves a large, noisy band behind. That residue is the bulk of
what node 14 reviews, and it is noisy by construction rather than by accident —
do not read a high confidence as a shortcut.

**`--min-similarity` too low.** More candidates is not better here. Every extra
pair is human review time at node 14, and low-similarity pairs are
overwhelmingly surface.

## Provenance

`scripts/propose_edges.py`, `scripts/auto_promote_edges.py`; the confidence-tier
characterisation from the `guru-review-edges` skill.
