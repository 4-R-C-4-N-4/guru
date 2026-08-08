# 06 — chunk

**Kind:** command

Generate the corpus TOMLs.

## Precondition

A valid `chunking/{tradition}/{source-id}.toml` that passes `--dry-run`.

## Action

```sh
python3 scripts/chunk.py --only <source-id>
```

## Output

- `corpus/{tradition}/{source-id}/metadata.toml`
- `corpus/{tradition}/{source-id}/chunks/NNN.toml`

Git-tracked, and marked `linguist-generated` so GitHub collapses them. Review
the chunker config, not the generated output.

## Gate

```sh
python3 -m guru ingest status <source-id>
```

Checks `metadata.toml` exists, chunk files exist, and `chunk_count` matches the
number of files on disk. A mismatch means a partial run.

## Failure modes

**Believing the output is ready to use. It is not.** `chunk.py` output is
pre-clean by construction. Node 07 is not an optional tidy-up; it is part of
producing a correct chunk. This has been forgotten before, which is why node 07
and node 08 are marked `stale_on_rechunk` and `guru ingest status` reports `[!]`
rather than `[x]` when chunk files change underneath them.

**Re-chunking silently invalidating downstream state.** A re-chunk after
tagging or embedding leaves `guru.db` holding rows keyed to chunk ids that may
no longer mean the same thing. If node 09 reports a node-count mismatch against
the files on disk, that is what happened.

## Provenance

`scripts/chunk.py`; the pre-clean invariant is why
`scripts/cleanup_chunk_ids.sh` and the `clean_bodies` re-run exist as separate
steps.
