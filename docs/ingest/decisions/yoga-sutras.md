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

---

## 09–12 · 2026-08-08 · claude (pilot)

**09 graph-bootstrap** — 192 chunk nodes. (Written to `guru.db`, which is
git-ignored and shared across branches: until this branch merges, other
checkouts see chunk nodes for a text their `corpus/` does not contain. That is
the condition `guru dossier drift` reports as ORPHANED.)

**10 tag-concepts — the model had to change, and the measurement is the reason.**

| model | per chunk | 192 chunks |
|---|---|---|
| `Qwen3.5-27B-UD-Q4_K_XL` (`REASONING=auto`) | **219 s** (~3,200 tokens of reasoning preamble at 32 t/s) | ~11.7 h |
| `qwen-3-4b-guru-Q4_K_M` (`PARALLEL=4`) | **~6 s** | **~19 min** |

The 27B was left to finish one chunk to get a real number rather than a guess.
No-think on the 27B was the other candidate, but guru's `scripts/serve-llama.sh`
has no `EXTRA_ARGS` hook — only the model-runners copy does — so it would have
meant editing the launcher. The 4B needed no changes and is the fine-tune built
for this task.

Result: **2,579 tags across all 192 chunks**, score 1/2/3 = 737/1481/354 (before
the chunk-001 redo).

**Provenance had to be repaired.** The aborted 27B run left 15 tags on
`book-01.001`, so that one chunk carried different provenance from the other
191 — different id range at review (70xxx vs 71xxx), different failure modes.
Deleting those rows was not enough to re-tag it: `--resume` consults the
separate `tagging_progress` table, which still recorded the chunk complete, so
the re-run reported "0 chunks tagged". `--chunk-ids-from-file` ignores resume
and did it.

**12 embed** — 192 embedded, 0 errors.

**Retrieval verified end to end** (the actual proof the ingest worked):

```
Q: What is the aim of concentration of the mind?
  0.735  hinduism.yoga-sutras-book-03.001  [Sutra 1]      <- top hit
  0.675  neoplatonism.plotinus-select-works-index.282
  0.730  hinduism.yoga-sutras-book-03.019  [Sutra 19]
```

Book III Sutra 1 is *dharana* — "the binding of the perceiving consciousness to
a certain region is attention" — so the top hit is the correct sutra, and
Plotinus arriving alongside it is the cross-tradition behaviour working.

**11 tag-review — a 5-tag sample, not a review.** Read against the bodies:
`self_knowledge` (score 3) and `mystical_union` (2) look grounded;
`divine_light` (1) rests on "implying an illumination" with no light in the
body, and `ritual_purity` (1) on service-to-the-Master, both of which read as
rejects under rubric rule 2. `hidden_sayings` (1) is on the historically-noisy
list but does quote real text. Two clear rejects in five, both score 1 —
consistent with the corpus's known score-1 accept rate. 2,579 pending tags is a
curation job, not something to queue in one sitting.

---

## 13 · 2026-08-08 · claude (pilot)

**696 proposals** — 693 PARALLELS, 3 CONTRASTS — from
`Mistral-Small-3.2-24B-Instruct-2506-UD-Q5_K_XL`, prompt v2, across all four
books. Pending, unreviewed. Node 14 is the user's, via `/guru-review-edges`.

Two model mistakes preceded this, both mine. Node 13 documented the 27B because
I wrote it from the README's Stage-3 example rather than from
`propose_edges.py`, whose own default is Mistral with help text naming
`scripts/run-mistral.sh`. Following my own wrong instruction, I then reached for
the 4B tagging fine-tune when the 27B proved too slow, and discarded its 208
proposals on the reasoning that an all-PARALLELS batch showed rubber-stamping.

**That reasoning was also wrong.** `surface_only`, `unrelated` and most
`CONTRASTS` are review outcomes, not proposals — every one of the corpus's 8,338
`surface_only` rows carries `status='rejected'` and a reviewer. The proposer
emits PARALLELS by design; reclassify at node 14 is where discrimination
happens. So this Mistral run's 693-of-696 PARALLELS is the expected shape, and
the earlier 4B batch was worth discarding only because Mistral is the documented
proposer — not because of its type spread.

Both corrections are in `docs/ingest/13-propose-edges.md`.

---

## 11 · 2026-08-09 · claude (pilot)

**2,579 tags on 192 chunks, all reviewed against the chunk body.** Queued
444 accept / 6 reassign / 2,129 reject — **17.4%**. By book: I 19.4%,
II 17.6%, III 16.4%, IV 15.1%. Unreviewed remaining: 0. Pending the user's
apply; nothing here has touched the live graph.

Six tagger failure modes, in rough order of cost:

- **Over-generation.** 13.4 tags per chunk against a ~2.6 accept. Worst case
  III.24 — 31 tags, 1 accepted. This is the whole of the 82.6% reject rate;
  the individual judgements are mostly not *wrong* so much as ungrounded.
- **Stance inversion** (6 cases). The chunk argues against a position and the
  tag reads it as holding it.
- **Silent omission** (10 candidates, see below).
- **Referent mismatch.** The concept fits something the chunk mentions rather
  than something it claims.
- **Taxonomy gap.** No concept covers Sankhya metaphysics, the siddhis, or
  Patanjali's epistemology of the pramanas — the three things Books II–IV
  spend the most words on. This is the finding most worth acting on, and it is
  a taxonomy job, not a tagger job.
- **Empty justification at score 3** (2 cases).

### Silent omission is reviewable, and mostly did not survive review

Recall failures look like node 10's problem, but `reassign` reaches them: it
disposes of the donor tag exactly as `reject` would and inserts a new
`staged_tag` for the concept the tagger missed. Mechanics and caveats are in
node 11's failure modes.

Ten omissions logged during the pass, re-read against the concept definitions
before queueing. **Five held, one was not an omission at all, four failed:**

| chunk | concept | verdict |
|---|---|---|
| I.28 | `sacred_names` | queued — "soundless repetition of OM", "the potency of the word itself" |
| I.45 | `unity_of_being` | queued — "the partition wall … is broken down and we are all made perfect in the One" |
| II.10 | `inner_silence` | queued — "stilled by meditation … the strong, silent life above … the stillness" |
| II.43 | `sacred_names` | queued — "recital of sacred texts, which, in their very sounds, had mystical potencies" |
| IV.31 | `unity_of_being` | queued — "the soul that is in them is one with the soul that is in thee" |
| II.9 | `love_of_neighbour` | **not an omission** — the tagger proposed `unity_of_being` here at score 3 and it was already queued accept |
| II.3 | `love_of_neighbour` | dropped — def requires active care for others; the chunk gives non-separateness |
| III.2 | `renunciation_of_wealth` | dropped — one borrowed clause ("the deceitfulness of riches") in a chunk about dhyana |
| III.6 | `dharma` | dropped — duties of one's day, with none of the def's binding of duty to cosmic station |
| III.29 | `ritual_purity` | dropped — purity as an outcome of redirected force, not a state maintained for encounter |
| III.48 | `inner_silence` | dropped — "heard the voice of the silence" is an attainment named, not a practice expressed |

The 6-of-10 attrition is the useful number. Omissions logged mid-review are
recorded on the strength of a phrase; four of them dissolved the moment they
were tested against the concept definition rather than against the phrase that
suggested them. **An addition needs a higher burden than a removal** — a reject
discards one model guess, an accepted reassign asserts a claim in the graph
under the reviewer's name. The queue carries 6 reassigns, not the 10 the
mid-review notes implied.

Donors were the queued reject on the same chunk whose original concept was
least worth keeping — `paradox_as_teaching` in four of five, a persistent
over-application here. I.28 had only score-2 rejects available, so its new tag
carries score 2 rather than 1; noted because score drives the auto-promote
tier, and the score was left as the donor's rather than adjusted to steer what
happens downstream.
