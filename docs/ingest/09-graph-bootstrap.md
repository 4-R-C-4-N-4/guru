# 09 — graph-bootstrap

**Kind:** command

Create tradition and chunk nodes in `guru.db`, with `BELONGS_TO` edges.

## Precondition

Clean chunk TOMLs on disk (nodes 06–08).

## Action

```sh
python3 scripts/graph_bootstrap.py
```

It walks the whole corpus and is idempotent, so there is no per-text flag.

If the text introduced concepts not yet in `concepts/taxonomy.toml`, add them
and sync — otherwise node 10 has nothing to tag against:

```sh
python3 scripts/sync_taxonomy.py --dry-run
python3 scripts/sync_taxonomy.py --apply
```

Note that `--dry-run` is the default on that script. `--apply` is required.

## Output

`nodes` rows of type `chunk`, one per chunk TOML; `tradition` nodes;
`BELONGS_TO` edges.

## Gate

```sh
python3 -m guru ingest status <source-id>
```

Compares chunk-node count in the DB against chunk files on disk. They must
match exactly.

## Failure modes

**Node count exceeding file count.** Stale nodes from a previous chunking of
the same text, whose ids no longer exist on disk.
`scripts/cleanup_stale_chunk_nodes.py` and
`scripts/cleanup_stale_embeddings.py` exist for this, and the mismatch is the
signal that a re-chunk changed ids.

**Counts agreeing while labels disagree.** The probe compares chunk-node count
to file count, so a re-chunk that only rewrote `section` leaves the node green
and `nodes.label` wrong — the string the reader is shown in a citation. This is
what todo:0888eb07 did to 14 texts. The script is an upsert on `id` (`label`
and `metadata_json` from `excluded`, edges `ON CONFLICT DO NOTHING`), so a
re-run repairs it without touching the graph; it is the right reflex after any
label-moving chunker change. It has no `--text` filter — it is whole-corpus,
and `data/guru.db` is git-ignored and shared across branches, so run it on the
branch whose `corpus/` you actually want the graph to match.

**Tagging against a taxonomy that lacks the text's concepts.** The tagger can
propose new concepts with `is_new_concept=1`, but a text whose central ideas
are entirely absent from the taxonomy produces a tag pool that is mostly
proposals, which is a much harder review at node 11 than adding the concepts
first.

## Provenance

`scripts/graph_bootstrap.py`, `scripts/sync_taxonomy.py`, and the cleanup
scripts that exist because of the stale-node case.
