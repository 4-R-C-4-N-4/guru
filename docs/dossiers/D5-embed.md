# D5 — embed

**Kind:** command

Embed the promoted summary nodes.

## Precondition

`summary_nodes` rows exist for the work (D4).

## Action

```sh
python3 scripts/embed_summaries.py --resume
```

Whole-corpus with `--resume`; `--reindex` rebuilds. Same embedding config as
the chunk path.

## Output

`summary_embeddings` — the `chunk_embeddings` pattern exactly: float32 LE BLOB
with per-row `dim` and `model`, which is why the writer path is reused.

## Gate

```sh
python3 -m guru dossier status <work-id>
```

Every `summary_node` for the work has an embedding.

## Failure modes

**Embedding dossiers.** There is nothing to embed. Dossiers deliberately carry
no vector: in study mode a dossier is fetched by primary key for the pinned
`study_scope` and *injected*, never retrieved. No ANN index, no pool-pollution
question. Only `summary_nodes` are retrievable, and only in study mode.

**Leaving a gap and discovering it at export.** `export.py` hard-fails on a
`summary_node` with no embedding — it raises rather than emitting a partial
artifact. A gap here blocks the entire corpus export, not just this work.

**Stale embeddings after a regeneration.** A re-promoted summary keeps its id
and gets a new body. `--resume` skips by id, so it will not notice.
`--reindex` is the honest option after a template revision.

## Provenance

`scripts/embed_summaries.py`; the no-embedding-for-dossiers decision from
`docs/summary/document-knowledge-data-structures.md`, stated there as one of
two deliberate reductions from the proposal draft; the export hard-fail from
`load_summary_nodes` in `scripts/export.py`.
