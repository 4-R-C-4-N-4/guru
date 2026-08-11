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

**A label-only re-chunk passes every gate and still leaves the graph stale.**
The todo:0888eb07 sub-chunk-separator pass changed `section` in 1,752 files
across 14 texts without adding, removing or renumbering a single chunk. Ids
were stable, so nothing downstream was invalidated — but `nodes.label` and
`metadata_json.section` still held the old strings, and node 09's probe
compares *counts*, so it reported `[x]` throughout. Node 09 is an upsert on
`id`; re-running it is the resync, and it is cheap. After any re-chunk that
moves labels, run it whether or not the gate asks you to.

**Confirming a re-chunk is safe before you commit it.** Snapshot, re-run the
pipeline, diff — the sequence that proves a chunker change did only what you
meant:

```sh
python3 scripts/chunk.py --only <source-id>
python3 scripts/clean_bodies.py --text <source-id> --apply    # node 07, always
git diff -U0 corpus/ | grep -E '^[+-]' | grep -vE '^(\+\+\+|---)'
```

Run it once *before* touching the chunker: the diff should be empty. It is the
only way to tell a change you made from drift that was already there — the
first attempt at this pass showed 328 modified files on a plain re-chunk with
no code change at all, which was node 07 not having been re-run, not a bug in
the chunker.

**A text whose raw cannot be regenerated.** `raw/` is git-ignored, so a source
whose raw is not a plain fetch cannot be re-chunked from a fresh checkout.
`apocryphon-of-john` is the current case — its raw comes from
`scripts/pdf_synoptic_extract.py` over a local PDF — and it was left out of the
0888eb07 pass for exactly this reason. A corpus-wide chunker fix will have a
tail like this; carry the exception in the guarding test with its reason
attached, rather than dropping the text quietly.

## Provenance

`scripts/chunk.py`; the pre-clean invariant is why
`scripts/cleanup_chunk_ids.sh` and the `clean_bodies` re-run exist as separate
steps.
