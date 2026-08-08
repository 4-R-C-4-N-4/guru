# yoga-sutras — ingest decisions

Pilot run of the ingest workbook, driven only from `guru ingest status` and the
node files it names.

---

## 01 — source-vetting · 2026-08-08 · claude (pilot)

**Verdict:** insufficient-evidence — **node 01 gate not passed, ingest halted here**

**URL vetted:** `https://sacred-texts.com/hin/yogasutr.htm`, proposed by
`docs/corpus-expansion/hit-literature-2026-08.md` §1.1 as "Yoga Sutras of
Patanjali — Charles Johnston 1912".

**Heading chain read:**

```
The Yoga Sutras of Patanjali / The Threads of Union / Translation by BonGiovanni
Part Two — on Spiritual Disciplines
Part Three — on Divine Powers
Part Four — on Realizations
```

**Finding 1 — the translator is not the one claimed.** The page carries
**BonGiovanni**'s translation, not Charles Johnston's. The candidate doc
attached Johnston's attribution and date to BonGiovanni's URL. Both the page
`<title>` and its schema.org `author` block name BonGiovanni.

Johnston's 1912 translation is real and on the same host, at
`https://sacred-texts.com/hin/ysp/index.htm` — `<h2>by Charles Johnston</h2>`,
`<h4>[1912]</h4>`. It is a different edition at a different URL.

**Finding 2 — licence is unevidenced for the page as given.** Nothing on
`yogasutr.htm` dates the BonGiovanni translation or dedicates it to the public
domain. Per the contract, absence of a copyright notice is not evidence, and a
translator with no date attached cannot be assumed pre-1929. Johnston 1912 is
unambiguously public domain; BonGiovanni is not established either way.

**Finding 3 — the Johnston edition is multi-page, with apparatus interleaved.**
`ysp/index.htm` links 11 internal pages, alternating:

```
ysp00  Title Page
ysp01  Introduction to Book I      <- apparatus
ysp02  Book I                      <- translation
ysp03  Introduction to Book II     <- apparatus
ysp04  Book II                     <- translation
ysp05 / ysp06                      ... and so on through Book IV
```

This is the failure mode node 01 documents from the 2026-05-31 Upanishad pass,
recurring: introduction essays interleaved with the translation, where taking
the first or the index page ingests apparatus rather than source text. A
correct Johnston ingest wants **only** `ysp02`, `ysp04`, `ysp06`, `ysp08`.

**Pagination:** `yogasutr.htm` is genuinely single-page (all four Parts on one
page, 28.7 KB). `ysp/` is multi-page, 4 translation pages of 9.

**What this blocks.** The gate requires `verified`. Neither route qualifies as
proposed: the recommended URL fails on licence and on the edition mismatch, and
the intended edition is multi-page and needs a different manifest shape than
`format = "html"`.

**Options, for the corpus owner:**

1. **Johnston via 4 explicit entries** (`ysp02`/`04`/`06`/`08`, or one entry per
   Book). Licence clean, apparatus excluded by construction. No longer a
   single-page pilot.
2. **BonGiovanni** — establish the licence first. If it can be evidenced, this
   is the clean single-page ingest originally wanted.
3. **Drop and pick another candidate.** The doc's other single-page entries were
   not vetted by this run.

**Note on the contract.** `prompts/ingest/source-vetting.md` has no verdict
value for "right work, different edition than the candidate claimed" — the enum
is `verified | wrong-page | apparatus | insufficient-evidence`. This case is
`insufficient-evidence` only because the licence independently failed; had
BonGiovanni carried a PD dedication, the edition mismatch alone would have had
nowhere to land and the run would have reported `verified` against a source
whose provenance did not match its own manifest comment. The enum wants a
`wrong-edition` member, or `wrong-page` wants widening.

**Ledger:** not marked done. The node is correctly still `[ ]`.

---

## 01 — source-vetting (re-run, Johnston edition) · 2026-08-08 · claude (pilot)

**Verdict:** verified — gate passed.

**Edition:** *The Yoga Sutras of Patanjali — The Book of the Spiritual Man, An
Interpretation by Charles Johnston*, 1912. `https://sacred-texts.com/hin/ysp/`.

**Heading chain, per page fetched:**

| page | bytes | `<h1>` | reads |
|---|---|---|---|
| ysp00 | 7.6 K | THE YOGA SUTRAS OF PATANJALI | title page — apparatus |
| ysp01 | 11.5 K | INTRODUCTION TO BOOK I | apparatus |
| ysp02 | 38.4 K | BOOK I | **translation** — "1. OM: Here follows Instruction in Union." |
| ysp04 | 51.6 K | BOOK II | **translation** |
| ysp06 | 64.5 K | BOOK III | **translation** |
| ysp08 | 47.8 K | BOOK IV | **translation** |

`is_translation: true` for ysp02/04/06/08. The odd-numbered pages are Johnston's
introductions and are excluded by construction, not by a strip rule.

**Licence:** public domain. Positive evidence — `<h4>[1912]</h4>` on the index,
publication 1912, well clear of the 1929 line. This is what the BonGiovanni page
could not supply.

**Pagination: multi, 4 translation pages of 9 — and NOT `format = "html_multi"`.**

`html_multi` resolves to `sacred_texts.py`, which follows sequential next-links.
From ysp02 that walks ysp02 → **ysp03 (Introduction to Book II)** → ysp04 → …,
pulling every introduction into the corpus as if it were source text. The
apparatus is interleaved with the translation, so sequential paging cannot
exclude it.

**Shape chosen: four single-page `format = "html"` entries, grouped as one
work.** This is the corpus's established pattern for a serialized text — the
Bhagavad Gita is 18 chapter entries grouped into one work, the Dhammapada 26,
Agrippa 74. Ids `yoga-sutras-book-01` … `-04`, matching the Gita's zero-padded
convention, grouped in `sources/works.toml` as work `yoga-sutras`.

**Structural note for node 05.** Sutras are numbered `<h?>` headings —
`"1. OM: Here follows Instruction in Union."` — with Johnston's commentary as
the following prose. The heading *is* the sutra, so a chunk is sutra +
commentary, and the section label should carry the sutra number. That makes this
a `heading` or `regex-section-split` decision rather than the corpus-default
`paragraph-group`.

### Two workbook frictions this step exposed

1. **Node 01 is per-source-id, but vetting is per-edition.** One vetting act
   covers all four pages; the ledger wants four entries. Recorded once here and
   marked four times.
2. **`decisions/<source-id>.md` has no name for a grouped work.** This file is
   `yoga-sutras.md` — the work id, not any source id. For serialized texts the
   convention should be work-level, which the workbook does not say.

---

## 02–08 · 2026-08-08 · claude (pilot)

**02 manifest** — four `format = "html"` entries, `yoga-sutras-book-01…04` →
`ysp02/04/06/08`. The block comment records why not `html_multi` and warns off
re-pointing at the BonGiovanni URL. Gate: `acquire --dry-run` resolved each.

**03 acquire** — 28.8K / 41.5K / 54.2K / 38.4K chars.

**04 boilerplate** — P2 site header (`Sacred Texts Hinduism Yoga Index Previous
Next`) + `Buy this Book at Amazon.com`, P3 byline (`…by Charles Johnston,
[1912], at sacred-texts.com`), P1 trailing `Next: Introduction to Book N`. All
known classes; the first two are already in `BASELINE_PRE_STRIP`, the third is
`clean_bodies`. No new classes proposed.

**05 chunk-config — the real decision.** The raw is a **single line with zero
paragraph breaks**, so `paragraph-group` (the corpus default, 379 of 408
configs) would have produced exactly one chunk per book. `regex-section-split`
on `'(?:^|\s)(\d+)\.\s'`, `section_label_format = "Sutra {n}"`, `group_size = 1`.

Three things checked before committing to it:

- **Not `^`-anchored**, because with one line there is nothing to anchor to.
- **No capital-letter requirement after the number.** Tested three variants —
  requiring `[A-Z]`, requiring nothing, and a capital-or-quote lookahead — all
  produce identical output here. The looser one is kept because the stricter one
  would silently drop a sutra that opens on a quotation mark, and nothing about
  this text guarantees that never happens in a book we have not read closely.
- **The apparent numbering gaps are Johnston's, not the parser's.** Book II has
  no sutra 5 or 48 and Book III no 34. Johnston merges those pairs and says so
  in the commentary — *"Here we have really two Sutras in one."* Labels follow
  the edition as printed, so a citation can be checked against it.

**06 chunk** — 51 / 53 / 54 / 34 = **192 chunks**, avg 117–240 tokens, none over
the 800 budget.

**07 clean-bodies** — 1 chunk changed in each of Books I–III (the trailing
`Next:` on the last chunk); Book IV already clean.

**08 readability** — mean **0.0** for all four, worst 1.3 (Book III). Nothing to
judge: the single-line source has no `hard_wrap`, and the sacred-texts page
marks were pre-stripped at chunk time. Pass.
