# 04 — boilerplate-survey

**Kind:** judgement · **Contract:** [`prompts/ingest/boilerplate-survey.md`](../../prompts/ingest/boilerplate-survey.md)

Decide what in the raw file is the archive's packaging and what is the text.
Produces a strip plan; node 07 executes it.

## Precondition

`raw/{tradition}/{source-id}.txt` exists (node 03).

## Action

```sh
python3 scripts/run_contract.py boilerplate-survey \
    --input raw_head=raw/<tradition>/<source-id>.txt \
    --var source_id=<id> --var host=<host>
```

For a multi-page source the raw file is `{source-id}-01.txt` and its siblings,
not `{source-id}.txt` — survey the first and last page rather than one file,
since each page carries its own header and nav.

The runner keeps the head and tail within a character budget and elides the
middle, which is correct here: site headers lead, nav lines and licence blocks
trail. Boilerplate lives at the edges.

Record the plan in `docs/ingest/decisions/<source-id>.md`, then mark done.

## Output

A classified strip plan — which of P1–P6 apply, at what granularity, with what
risk.

## Gate

Every proposed strip is paragraph- or sentence-granular, and none of them drops
a chunk. A `high` risk classification is not a gate failure; it is a handoff to
a human.

## Failure modes

**Substring surgery.** A regex that matches mid-paragraph cannot tell a header
from a quotation of one. Paragraph or sentence granularity, always.

**Dropping chunks.** Chunk ids are citations already issued. The corpus keeps
apparatus chunks deliberately and leaves them untagged — node 11 rejects tags
on them rather than the pipeline deleting them.

**Over-stripping what is actually content.** Bare `p. NN` references are
indistinguishable from citations at regex level and are left alone. Translator
footnote paragraphs are arguably content and are left alone. Both decisions
were made deliberately; re-proposing them is a regression.

**Assuming the old numbers still hold.** The "~32% nav pollution" era ended
with earlier cleanup passes. As of the 2026-07-04 audit, residual boilerplate
is about 7% of chunks, and `ccel.org` texts are clean. The `{p. N}` braced page
marker regex in guru-web now matches zero chunks and is vestigial.

## Provenance

Pattern classes P1–P6, counts, and strip strategies from
`docs/summary/boilerplate-audit.md` (2026-07-04, corpus-wide scan of 4,176
chunk bodies).
