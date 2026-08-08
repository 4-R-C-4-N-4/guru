# 05 — chunk-config

**Kind:** judgement · **Contract:** [`prompts/ingest/chunk-config.md`](../../prompts/ingest/chunk-config.md)

Choose how the text is cut into citation-addressable units, and write the
config. This is the highest-leverage judgement in the pipeline.

## Precondition

`raw/{tradition}/{source-id}.txt` exists, and node 04 has flagged anything that
would confuse a splitter.

## Action

```sh
python3 scripts/run_contract.py chunk-config \
    --input raw_head=raw/<tradition>/<source-id>.txt \
    --var source_id=<id> --var tradition=<t> --var text_name="<Title>"
```

Write the returned `config_toml` to `chunking/{tradition}/{source-id}.toml`.

`scripts/chunk_init.py` generates a scaffold if you would rather start from one
and hand-tune, which is how most existing configs were made.

## Output

`chunking/{tradition}/{source-id}.toml`

## Gate

```sh
python3 scripts/chunk.py --dry-run --only <source-id>
```

Read the section labels it prints. They are what citations will say. If they
do not match how a reader would cite this text from a printed edition, the
config is wrong regardless of whether it runs.

## Failure modes

**Using the aliases instead of the canonical strategy names.**
`docs/chunking-schema.md` documents `regex`, `heading` and `paragraph`. Those
are back-compat aliases. The corpus actually uses `paragraph-group` (379
configs), `regex-section-split` (17) and `page-as-chunk` (12).
`STRATEGY_TYPES` in `scripts/chunk.py` is the source of truth, and the schema
doc has drifted from it.

**`pattern` written as a basic TOML string.** It must be single-quoted — a TOML
literal string — or every backslash needs doubling and the regex silently stops
matching. Failure looks like one enormous chunk, not an error.

**A regex that matches footnote references rather than section markers.** `(1)`
is ambiguous in most texts. The dry run shows this immediately in the section
count.

**Imposing a foreign subdivision.** Follow the text's own division system. A
citation a reader cannot check against a printed edition is worse than a
coarser one they can.

**Forgetting how expensive revision is.** Re-chunking invalidates node 07, node
08, every embedding, and every staged tag for the text. Spend the time here.

## Provenance

Schema from `docs/chunking-schema.md`; canonical strategy names from
`scripts/chunk.py`; strategy distribution counted across `chunking/*/*.toml`
on 2026-08-07.
