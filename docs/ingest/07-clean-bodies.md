# 07 — clean-bodies

**Kind:** command · **Goes stale on re-chunk**

Execute the strip plan from node 04 against the generated chunk bodies.

## Precondition

Chunk TOMLs exist (node 06), and a strip plan exists (node 04).

## Action

Dry run first, always, and read the diff:

```sh
python3 scripts/clean_bodies.py --dry-run --text <source-id>
python3 scripts/clean_bodies.py --apply --text <source-id>
```

`--apply` writes the TOMLs and updates token counts in `guru.db`.

Then record it, because this node leaves no artifact of its own that a probe
can distinguish from an unclean one:

```sh
python3 -m guru ingest done <source-id> 07-clean-bodies --by <who> --note "P1 x3, P5"
```

## Output

Cleaned chunk bodies in place; token counts updated.

## Gate

The dry-run diff, read by a person or by whoever is driving. `--max-shrink`
defaults to 0.25 and will refuse a chunk that wants to lose more than a quarter
of itself.

## Failure modes

**Skipping it after a re-chunk.** This is the single most repeated mistake in
the pipeline. `chunk.py` output is pre-clean *every time*, so every re-chunk
re-dirties every body. `guru ingest status` marks this node `[!]` when the
chunk files are newer than the ledger entry, which is the machine-checked form
of that rule.

**Hitting `--max-shrink` and raising it.** A chunk that wants to lose a quarter
of itself is a bug in the strip plan, not a dirty chunk. Go back to node 04.
`--allow-id` exists for the genuine exceptions and takes them one at a time,
deliberately.

**Cleaning after embedding.** Node 12 must come after this one. Embedding dirty
bodies bakes nav lines into the vectors, and node 13 then proposes edges off
boilerplate similarity — two texts that share a sacred-texts header are not
making the same conceptual move.

## Provenance

`scripts/clean_bodies.py`; the ordering constraint from the embedding and
edge-proposal stages; the re-chunk invariant from repeated incidents.
