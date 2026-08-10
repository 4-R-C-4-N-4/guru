# 12 — embed

**Kind:** command

Embed the chunk bodies into `chunk_embeddings`.

## Precondition

Chunk nodes exist (node 09) **and bodies are clean** (node 07, not stale).

## Action

```sh
python3 scripts/embed_corpus.py --resume --text <source-id>
```

Default model is `nomic-embed-text` via Ollama, per `config/embedding.toml`.
Vectors live in `guru.db`; there is no separate vector store.

## Output

`chunk_embeddings` rows, one per chunk.

## Gate

```sh
python3 -m guru ingest status <source-id>
```

Compares embedding count against chunk-node count. A shortfall means an
interrupted run — re-run with `--resume`.

## Failure modes

**Embedding before cleaning.** The ordering constraint that matters most in the
back half of the pipeline. Nav lines and digitisation credits in a body become
part of its vector, and node 13 then proposes cross-tradition edges off
boilerplate similarity. Two texts sharing a sacred-texts header are not making
the same conceptual move, but their vectors say they are.

**Stale embeddings after a re-chunk.** Rows keyed to chunk ids that changed
meaning. `scripts/cleanup_stale_embeddings.py` exists for this. `--reindex`
rebuilds rather than resuming.

**Ollama not running.** The failure is a connection error, not a silent
degradation, so it is at least loud.

## Provenance

`scripts/embed_corpus.py`, `config/embedding.toml`; the ordering constraint
from the edge-proposal stage's dependence on vector quality.
