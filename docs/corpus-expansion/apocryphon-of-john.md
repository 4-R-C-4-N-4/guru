# apocryphon-of-john — source vetting and ingest decisions

The Secret Writing According to John, translated by Samuel Zinner, edited by
Mark M. Mattison. A **local PDF**, not a URL fetch, which is why several of the
usual steps were done by hand and why `scripts/acquire.py` cannot reach it.

---

## Vetting

**Verdict:** verified.

**Source:** `The_Secret_Writing_According_to_John_A_P.pdf`
(sha256 `82f50e3138b9c4b67fc9ddcdd1b3a2d7926e6e199a80f6046fafda07c1e135ac`),
34 pages, Ghostscript-produced, text layer intact — no OCR needed. Canonical
home <https://othergospels.com/john>; project site <http://nag-hammadi.net>.
First published online 2025-01-23.

**Licence:** public domain, positively stated on page 1 of the PDF: "The
following translation has been committed to the public domain and may be freely
copied and used, changed or unchanged, for any purpose." The underlying Coptic
edition (Waldstein & Wisse, Brill 1995) remains in copyright; the translation
made from it is the translator's to dedicate, and they have.

**Structure:** a three-column synoptic setting of four witnesses to one
treatise — Codex II, 1 (with Codex IV, 1 readings in italics) | BG 8502, 2 |
Codex III, 1.

---

## Which witnesses are ingested

**Only Codex II, 1**, as `apocryphon-of-john`.

The columns are recensions of a single treatise and are often verbatim identical
for a paragraph at a stretch. Ingesting all three would put near-duplicate
chunks into `chunk_embeddings` — three near-identical hits for every query — and
would have `propose_edges` drawing PARALLELS between the text and itself. Codex
II, 1 is the long recension, the only complete witness, and it carries the Codex
IV, 1 readings inline as italics, so one file covers two of the four witnesses.

Codex III, 1 fails on its own merits besides: 8.7 % bracket density, whole pages
lost ("(Pages 19 and 20 are lost.)"), and passages that read "[. . .] John, the
brother [of James] [. . .] the sons of Zebedee] –".

The BG 8502 and Codex III raw files are still produced and left in
`raw/gnosticism/` (git-ignored) — they cost nothing there and make the synoptic
comparison available outside the pipeline.

---

## Acquisition

`scripts/pdf_synoptic_extract.py` replaces `acquire.py` for this source:

```sh
python3 scripts/pdf_synoptic_extract.py <pdf> -o raw/gnosticism/
```

Column separation is **positional, not heuristic**. Column origins sit at
36.6 / 215.2 / 393.6 pt with clean gutters, and parallel paragraph groups share
their y-position across all three columns, so both the per-witness
reconstruction and the synoptic alignment fall out of the geometry.

Indent offset from the column origin encodes structure and is decoded rather
than guessed: ~0 pt = flush prose continuation, ~8 pt = new verse line, ~13 pt =
new prose paragraph, ≥15 pt = hanging continuation of the previous verse line.
Font runs carry the rest: `Garamond-Italic 11` = Codex IV, 1 reading,
`BerlinSans 11` = Coptic codex page number, `Garamond 7` = footnote reference,
`BerlinSans 12` centred = shared section heading.

### Verification

Every word of `pdftotext -layout` output is present in the three witness files,
except the per-page running headers (dropped deliberately) and one token —
`willwill`, a column-collision artifact *introduced* by `pdftotext` where column
1's "will" abuts column 2's. Geometric extraction has no such failure mode.

The stronger check is that every witness's Coptic page markers come out strictly
ascending and within that manuscript's real extent for this treatise:

| witness | markers | range | expected extent |
|---|---|---|---|
| Codex II, 1 | 31 | 2–32 | pages 1–32 |
| Codex IV, 1 | 48 | 2–49 | pages 1–49 |
| BG 8502, 2 | 59 | 19–77 | pages 19–77 |
| Codex III, 1 | 38 | 1–40 | pages 1–40 |

A column mis-assignment anywhere would break monotonicity. None does.

---

## Editorial sigla, and why markers carry their witness

Kept, because they are the text's critical apparatus rather than boilerplate:
`[ ]` lacuna, `[. . .]` longer gap, `( )` editorial insertion, `< >` editorial
correction, `{ }` scribal error, `*italics*` Codex IV, 1 readings.

Page markers are written **`[II, 18]` / `[BG 19]` / `[III, 3]`, never a bare
`[18]`.** The print uses bare numerals, but `clean_bodies.py` carries a
corpus-wide P9 rule, `\s*\[\d{1,3}\]`, that strips bracketed numbers as footnote
references. Left bare, the markers were silently eaten and — where a marker had
been set across a line break — an orphaned `[II,]` was left welded to the next
sentence. Qualifying every marker dodges the collision and is more informative.

That fix has a subtlety worth recording. Qualification cannot be done by
rewriting brackets after the fact, because the *printed* text also contains
bracketed numbers: "nor could the other [3]60 angels" is a restored digit, not a
page marker, and a naive pass rewrote it to "[III, 3]60". Markers are therefore
carried as sentinels from the moment they are recognised by font, and only
become brackets once qualified — a distinction the extractor still has and a
post-hoc regex never could.

---

## Chunking

`regex-section-split` on the 19 shared editorial section headings, which the
extractor emits as `== Heading ==`. They are the edition's own articulation of
the treatise and the units a reader would cite. `paragraph-group` was rejected:
the text alternates verse colometry with long prose, so a fixed
paragraphs-per-chunk grouping cuts at unstable granularity — one "paragraph" is
sometimes a single half-line ("I am the Mother,"). 19 sections → 24 chunks after
`max_tokens = 800` sub-splitting, 11,803 tokens, avg 491.

**Known cosmetic wart:** `subsplit()` appends a bare letter to the section
label, so an over-long section yields "The Monada", "The Monadb". With numeric
labels ("Logion 5a") this reads fine; with heading labels it reads like a typo.
The corpus already does this — `Tale BRANWEN THE DAUGHTER OF LLYRa` in the
Mabinogion — so this text follows precedent rather than inventing a second
convention. Fixing it properly means changing how `_letter_suffix` is joined in
`scripts/chunkers/regex_splitter.py`, which would relabel existing texts and
belongs in its own change.

---

## Cleanup and readability

`clean_bodies.py` reports **0 changes** — the extractor emits no nav, credit or
page-marker cruft for it to strip, and the marker-qualification above removed
the one class of damage it was inflicting.

Readability audit: 24 chunks, mean **10.5**, worst **40.0**
(`gnosticism.apocryphon-of-john.001`), dominant signals `hard_wrap` and
`brackets`.

**Verdict: pass.** The bracket density is in line with the corpus's other
bracket-heavy texts (Gilgamesh tablets run 11.5–13.9 mean) and is the
translator's apparatus, not damage. `hard_wrap` is a **false positive here**: it
counts short lines continued by a lowercase line, which is exactly what verse
colometry looks like, and this translation is set one clause per line —

> I am the Father,
> I am the Mother,
> I am the Son.

That structure is authorial and load-bearing for a revelation dialogue built on
parallelism, so it is preserved rather than reflowed to satisfy the signal.
The consequence, recorded here so it does not surprise anyone reading a future
audit table: **this text is the corpus's worst readability score, ~2.6× the next
highest, and that is expected rather than a defect.** Reflowing to flowed prose
would drop it to roughly Gilgamesh's range at the cost of the colometry.

---

## Graph, tags and edges

| step | result |
|---|---|
| graph bootstrap | 24 chunk nodes (corpus total 5340 → 5364) |
| concept tagging | 350 staged tags over 24/24 chunks, 0 errors — score 3: 73, score 2: 191, score 1: 86 |
| embeddings | 24 rows, `nomic-embed-text` via Ollama, 0 errors |
| edge proposal | 61 staged edges, 0 errors — 59 PARALLELS (19 @ 0.95, 40 @ 0.85), 2 CONTRASTS |

No taxonomy additions were needed: `pleroma`, `monad`, `aeons`, `demiurge`
(aliased to `yaldabaoth`, which this text spells Yaltabaoth), `archons`,
`kenoma` and `fall_of_sophia` were already in `concepts/taxonomy.toml`. The
tagger's most frequent picks — `divine_light`, `archons`, `cosmogony`, `aeons`,
`divine_hiddenness`, `demiurge`, `gnosis_direct_knowledge`, `divine_sparks`,
`emanation_hierarchy`, `pleroma` — are what this treatise is actually about.

Edge proposals land where a Sethian cosmogony should: western_esoteric (17),
jewish_mysticism (6), hermeticism (5), renaissance_hermeticism (4),
neoplatonism (4), sufism (3), mandaean (3).

**Everything above is `status='pending'`.** Tag review is the gate; nothing
here has been promoted, and the 40 proposals at 0.85 are the usual noisy tier.
(Edge review — Pass C — has since been retired in favour of derived parallels;
see `docs/ingest/16-derive-parallels.md`. This expansion predates that cutover.)
`/guru-review-tags` is the flow for the tags.

### Tagging was run in no-think mode

`scripts/serve-llama.sh` in this repo hardcodes `--reasoning auto` and has no
`EXTRA_ARGS` hook, so it cannot be asked for no-think; the copy in
`~/programs/model-runners/` can. On this text the difference was ~300 s/chunk
versus ~37 s/chunk — 24 chunks in ten minutes rather than two hours. Worth
knowing before anyone runs a long tagging pass from the repo script.

---

## Pre-existing test failures (not caused by this change)

`tests/test_works.py` fails on `main` before this branch: it asserts hardcoded
totals of 54 works over 214 texts, and `main` already has **56 works over 233
texts**. This change makes it 57 / 234. The invariants the file actually
guards — total coverage, no strays, member disjointness — all still hold
(`work_of` auto-creates a singleton work for this text, so no `sources/works.toml`
entry is needed). Only the frozen counts are stale, and refreshing them is a
separate change from this one. The rest of the suite is green: 349 passed.

---

## Note on the ingest workbook

This work was done on `feat/secret-john`, branched from `main`. The `guru
ingest` CLI and `docs/ingest/` workbook live on an unmerged branch, so the
ledger at `data/ingest/apocryphon-of-john.json` has **not** been written and the
judgement nodes above are recorded here instead. When the workbook lands, the
vetting, boilerplate, chunk-config and readability verdicts on this page are
what nodes 01, 04, 05 and 08 need.
