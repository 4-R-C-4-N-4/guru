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

**A `regex-section-split` silently merges units where the source's delimiter
slips.** The regex matches what it matches; the units it misses do not error,
they get absorbed into the preceding chunk, and the output is well-formed and
plausible all the way through node 14.

On yoga-sutras the pattern was `'(?:^|\s)(\d+)\.\s'` and the sacred-texts
pages omit the period in exactly three places out of 195 — `5 The darkness of
ignorance is:`, `48 The fruit of right poise`, `34 By perfectly concentrated
Meditation`. Result: `book-02.004` is labelled "Sutra 4" and contains sutras 4
and 5; likewise 47+48 and 33+34. A chunk id that names one unit and delivers
two is exactly the promise the corpus exists to keep.

**Count emitted chunks against the source's own numbering before passing this
node.** Not the total — the *sequence*, which is where the gap shows:

```sh
python3 - <<'PY'
import tomllib, pathlib, re
ids = [tomllib.load(open(p,'rb'))['chunk'].get('section','')
       for p in sorted(pathlib.Path('corpus/{tradition}/{id}/chunks').glob('*.toml'))]
n = [int(m.group(1)) for s in ids if (m := re.search(r'(\d+)', s))]
print('emitted', len(n), 'range', min(n), '-', max(n),
      'missing', [i for i in range(min(n), max(n)+1) if i not in n])
PY
```

A gap means the delimiter is inconsistent in the source, not that the text is
absent. Go and read the raw at the gap before concluding anything else.

Once you have counted, write the count down. `tests/test_enumerated_text_counts.py`
holds one row per text whose source numbers its own units — expected count and
label template, taken from the printed edition rather than from the corpus — and
asserts both the total and that label tracks file ordinal. The second assertion
is the one that earns its keep: yoga-sutras book-02 had file 046 labelled
"Sutra 47" and its last file, 053, labelled "Sutra 55", so the count could look
plausible while a citation resolved by file position landed on the wrong sutra.
A one-line addition there is the difference between this check happening once
and it happening on every run.

**Re-chunking to fix this is not cheap, so find it here.** Chunk ids are file
ordinals; splitting a merged chunk renumbers every chunk after it, and every
`staged_tag`, `staged_edge` and `review_action` keyed to those ids goes stale.
Caught at node 05 it is a one-line regex change. Caught after node 14 it costs
the review.

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
