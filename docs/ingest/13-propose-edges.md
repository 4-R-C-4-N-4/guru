# 13 — propose-edges

**Kind:** command

Propose cross-tradition relationships between this text's chunks and the rest
of the corpus. Everything it writes is `pending`.

## Precondition

Embeddings exist for the text (node 12) — candidate pairs come from vector
similarity.

## Action

```sh
pgrep -af '[t]ag_concepts|[p]ropose_edges'      # must be empty — see node 10
scripts/run-qwen.sh                          # only if nothing is serving

python3 scripts/propose_edges.py --text <source-id> \
    --provider llamacpp --model Qwen3.5-27B-UD-Q4_K_XL.gguf \
    --top-n 5 --min-similarity 0.75
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

## Failure modes

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
