# 04 — boilerplate-survey

**Kind:** judgement · **Contract:** [`prompts/ingest/boilerplate-survey.md`](../../prompts/ingest/boilerplate-survey.md) · **Ledger:** `docs/ingest/decisions/blavatsky-sd.md` (2026-08-22)

Decide what in the raw file is the archive's packaging and what is the text.
Produces a strip plan; node 07 executes it.

**Apparatus policy — translator's and editor's apparatus is filtered out
BEFORE chunking, not kept.** Translation notes, endnotes, editor's
introductions and prefaces, and indices are scholarly apparatus, not primary
text. They stay in the raw file (reproducibility) but are removed at chunk
time via `pre_strip_patterns` (or `drop_*_marker` for whole-chunk regions) —
see apocryphon-of-john.toml ("Translator's notes … kept in the raw file,
stripped before chunking"), pistis-sophia.toml (PREFACE/CONTENTS/INTRODUCTION
and INDEX blocks), gilgamesh-tablet-*.toml. The corpus norm is that a clean
apparatus tail never becomes chunks. If a text's strip plan leaves a
translator's-notes block chunked, the plan is wrong.

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

**Dropping chunks.** Chunk ids are citations already issued. Do not delete
chunks that carry primary text. The apparatus distinction is the load-bearing
one: a cleanly-separable apparatus block (translator's notes, editor's
preface, index) is STRIPPED before chunking, not kept as chunks — keeping it
produces chunks that only exist to be rejected at node 11. The corpus does
deliberately keep SOME apparatus chunks — the residue that could not be
cleanly separated (interleaved introductions, surviving `*-index` chunks) —
and node 11 rejects tags on those rather than the pipeline deleting them. The
rule of thumb is separability: a clean tail strips; interleaved residue stays
tag-empty. Check the raw's tail for a notes/apparatus block before finalising
a strip plan — gospel-of-judas (2026-08-12) was initially chunked with its
"Notes on Translation" tail kept and had to be re-chunked to strip it.

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
