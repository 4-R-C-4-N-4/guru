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
