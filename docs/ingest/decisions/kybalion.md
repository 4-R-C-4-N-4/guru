# kybalion — ingest decisions

One file per text. Append as you go; do not rewrite history when a later node
contradicts an earlier one — record the contradiction and what it cost.

---

## 01 — source-vetting · 2026-08-17 · claude

**Verdict:** verified

**URL:** https://sacred-texts.com/eso/kyb/index.htm (index/contents page; primary
text spans https://sacred-texts.com/eso/kyb/kyb00.htm through kyb17.htm)

**What the page is:** sacred-texts.com's hosting of *The Kybalion: A Study of
The Hermetic Philosophy of Ancient Egypt and Greece*, by "Three Initiates"
(pseudonymous; commonly attributed to William Walker Atkinson), published by
the Yogi Publication Society, Chicago.

**Heading chain read:** Index page — `<title>The Kybalion Index | Internet
Sacred Text Archive</title>`, `<H1>The Kybalion</H1>`, `<H2>by Three
Initiates</H2>`, `<H4>[1912]</H4>`. Title page (kyb00.htm) —
`<h1>THE KYBALION</h1>`, `<h5>A Study of The Hermetic Philosophy of Ancient
Egypt and Greece</h5>`, `<h2>BY THREE INITIATES</h2>`, publisher block "THE
YOGI PUBLICATION SOCIETY MASONIC TEMPLE, CHICAGO, ILLINOIS", `[1912]`.
Chapter I (kyb03.htm) — `<h1>CHAPTER I</h1>`, `<h3>THE HERMETIC
PHILOSOPHY</h3>`, followed by real body prose (spot-read in full — this is
primary text, not an introduction essay or apparatus).

**Is this a translation, or apparatus?** Neither exactly — this is an
originally English-language work (not a translation of a foreign text), and
the fetched chapter is confirmed primary text, not editorial apparatus. The
contract's `is_translation` field doesn't cleanly fit an originally-English
source; recorded as `false` with this note rather than force a `true`. The
real question the field is a proxy for — primary text vs. apparatus — is
answered: primary text, confirmed by direct read of Chapter I's body.

**Edition match:** Candidate proposed "1908, Three Initiates." sacred-texts'
own metadata stamps this specific scan `[1912]` in three separate places
(index H4, title-page H4, and every chapter's running byline). 1908 is the
externally well-attested first-publication year (Wikipedia, Project
Gutenberg #14209, Internet Archive editions); 1912 is most likely a later
Yogi Publication Society printing/copyright-registration year that this
particular scan reproduces. **Both years are safely pre-1929** — the
discrepancy has no PD consequence — but the *label* and any citation-facing
date should say what this specific scanned printing states (1912), not the
externally-cited first-edition year (1908), to avoid a provenance mismatch
between the manifest entry and what a reader would find on the page.

**Pagination:** **multi** — the index links to 18 separate pages: title
(kyb00), table of contents (kyb01), introduction (kyb02), and Chapters I–XV
(kyb03–kyb17), each a distinct HTML page with its own Prev/Next nav. This
should enter as `format = "html_multi"`, following the same pattern already
used for `tertium-organum` in this tradition (index page + sequential
numbered chapter pages), not a single `html` entry.

**Licence:** public_domain — positive evidence: pre-1929 publication (1908
per external sources / 1912 per this scan, either way outside the 1929
copyright-term boundary), sacred-texts' own page metadata stamps `<meta
name="copyright" content="Public Domain and Creative Commons">`, and this is
independently corroborated by Project Gutenberg (#14209) and Internet
Archive carrying the same text as PD.

**Format:** html (multi-page)

**Concerns for later nodes:**
- Node 02: use `format = "html_multi"`, `translator` field left blank
  (originally English; author is the "Three Initiates" pseudonym — note the
  Atkinson attribution in `notes` as historically probable but unconfirmed by
  the source itself), and record the `[1912]` printing date the scan
  actually shows.
- Node 04/05: kyb00 (title page) carries a dedication block ("TO HERMES
  TRISMEGISTUS ... THIS LITTLE VOLUME ... DEDICATED") that is front-matter
  apparatus, not body text — plan to exclude kyb00/kyb01 (title + TOC) from
  chunking, same treatment as other sacred-texts front matter in this corpus.
  kyb02 (Introduction) should be read at node 04 to decide whether it's
  primary-text framing (keep) or apparatus (strip) — not fetched as part of
  this vetting pass.
- Chapter headings are clean, real `<h1>`/`<h3>` tags (`CHAPTER I` /
  `THE HERMETIC PHILOSOPHY`) — a `heading`-based chunk strategy should work
  cleanly, one chunk (or chunk group) per chapter page, same shape as
  Tertium Organum.
- Standard sacred-texts nav cruft present (Sacred Texts/Esoteric/Index/
  Prev/Next links, "Buy this Book at Amazon.com", Amazon iframe ad) — same
  P1–P3 boilerplate classes already established elsewhere in this corpus.

---

## 03 — acquire · 2026-08-17 · claude

Initial acquire (dry-run and real) resolved 19 pages, not the 18 confirmed at
node 01 — `kybalion-18` fetched `eso/khw/pageidx.htm`, the back-index of
Rudolf Steiner's *Knowledge of the Higher Worlds*, via a footer catalog-nav
link on the Kybalion index page that the downloader's link filter didn't
catch. Fixed in `scripts/downloaders/sacred_texts.py` (`fetch_index` now
scopes links to the index page's own directory); see
docs/ingest/03-acquire.md's Failure modes for the general writeup. Stale raw
files deleted and re-acquired clean: 18 pages, all under `eso/kyb/`.

---

## 09 (taxonomy pre-seed) · 2026-08-17 · claude

**Gap in the workbook, flagged rather than silently used:** node 09
(`docs/ingest/09-graph-bootstrap.md`) gestures at taxonomy pre-seeding in one
line — "if the text introduced concepts not yet in `concepts/taxonomy.toml`,
add them and sync" — but this is not its own judgement node. No contract in
`prompts/ingest/`, unlike the five other judgement calls (source-vetting,
boilerplate-survey, chunk-config, readability-gate, tag-review). The only
precedent is a single worked example in `gospel-of-judas`'s decision log
(node 09 section). Followed that precedent here in its absence; the user was
told directly this is a gap, not something the workbook actually specifies.

**Concrete motivation, not a hypothetical.** A live sample run of the 4B
fine-tune (`qwen-3-4b-guru-v3-Q4_K_M.gguf`, `--parallel 4`) against 6 chunks
covering the text's Seven Hermetic Principles produced 63 tags, zero of them
`is_new_concept=1`. Mentalism ("THE ALL IS MIND") was mapped onto
`unity_of_being` (a different doctrine — general monism, not a claim about
mind-as-substrate); Vibration was mapped onto `theurgy` and
`active_contemplation`; a dense passage naming both Correspondence and
Vibration explicitly got zero tags. This is the same "reach for the nearest
concept it does know" pattern as the documented v2 finnic-theurgy
contamination (node 10's Failure modes) — confirmed by diffing the 4B's own
vendored `~/programs/guru/4b-v3/taxonomy.toml` against the live one: identical
except for six unrelated gnosticism concepts, so the gap isn't a fluke of one
run, it's the training snapshot. Sample tags deleted from `staged_tags` /
`tagging_progress` after diagnosis so a real run starts clean.

**Concepts added** (`concepts.theology.ontological_structure` and
`concepts.cosmology.cosmic_order`; full definitions in
`concepts/taxonomy.toml`): `mentalism`, `vibration`, `polarity`, `rhythm`,
`gender`. Each checked against the *whole* taxonomy (not just its landing
family) for redundancy and given an explicit "distinct from" clause against
its closest existing neighbor — `mentalism` vs. `unity_of_being` and `logos`;
`vibration` vs. `cosmic_sympathy` and `magical_equilibrium`; `polarity` vs.
`opposites_transcended` and `magical_equilibrium`; `rhythm` vs.
`apocatastasis`; `gender` vs. `divine_marriage` and `aeons`.

**Deliberate non-addition:** `causation` (the Cause-and-Effect principle).
Splits cleanly across two existing concepts rather than needing its own —
`divine_providence` already covers "nothing happens by blind chance,"
`magical_will` already covers "rise from effect to cause through disciplined
volition." Adding a third node here would have been redundant, not additive.

Synced: `python3 scripts/sync_taxonomy.py --apply` — 6 concept nodes upserted,
6 primary memberships created, 0 moved/demoted. (A pre-existing, unrelated
worklist item — 5 live concept nodes with no primary family, from some
earlier `is_new_concept` application that was never folded into the TOML's
family sections — was left alone; out of scope for this pre-seed.)

---

## 04 — boilerplate-survey · 2026-08-17 · claude

**Classes found:**
- P2 ×18 — leading `Sacred Texts Esoteric Index Previous Next Buy this Book at Amazon.com The Kybalion , by Three Initiates, [1912], at sacred-texts.com` header, every page.
- P1 ×~16 — trailing `Next: <title>` nav line, every page but the last (kyb17/FINIS) and the title page's own contents-page pointer.
- P3 — none distinct from P2 here; no separate digitization-credit sentence found on this scan (no "scanned at sacred-texts.com" line surfaced on the sampled pages).

**Proposed strips:** standard P1/P2, same rules and granularity as `tertium-organum.toml` (`^Sacred Texts.*?at sacred-texts\.com`, `Next:[^\n]*$`). Both low risk — same pattern already in production use.

**Left alone:** the title page's dedication block ("TO HERMES TRISMEGISTUS … REVERENTLY DEDICATED") — this is the work's own front matter, not archive packaging; excluded from chunking at node 05 by scope (title/TOC pages), not by strip pattern.

---

## 05 — chunk-config · 2026-08-17 · claude

**Strategy:** page-as-chunk, same shape as tertium-organum — verified 1:1 chapter:page mapping means a single `CHAPTER\s+([IVXLCDM]+)` content pattern labels every primary-text page correctly.

**Rejected:** heading-based splitting — raw text is plain-text extracted (HTML tags already stripped by the downloader), so there's no heading tag left to split on; page-as-chunk is the natural granularity here since sacred-texts already paginated the book at the chapter boundary.

**Correction after first dry-run:** initial config didn't drop kyb00 (title/dedication) or kyb01 (TOC) — both got chunked as real citable chunks (caught by inspecting chunk 001's body, which was the literal table of contents). Added `drop_chunk_patterns` for both. Final: 63 chunks, 41,966 tokens (was 65 before the drop).

---

## 11 — tag-review · 2026-08-17 · claude

All 516 pending tags across 52 chunks reviewed and queued (377 accept / 139
reject, 73.1%) via `guru-review-tags` in 5 batches, one chunk-body read per
tag — no batch-dumps. Validator clean, no reassigns used, single apply pass
suffices. Full concept-level pattern notes and the accept/reject breakdown
are in the conversation record, not duplicated here.

**Three `is_new_concept=1` proposals accepted and placed in the hierarchy**
(three more proposed on this same review were rejected as redundant — see
the `01 (taxonomy pre-seed)` note above for the same discipline applied to
`cause_and_effect`/`mental_transmutation`/`law`):

| concept | family | why here |
|---|---|---|
| `esoteric_lineage` | `soteriology.knowledge_path` | sits beside `oral_tradition` and `hidden_sayings` — distinct in naming the master-to-disciple *chain* rather than the transmission's modality or its concealment |
| `relative_truth` | `theology.ontological_structure` | sits beside `mentalism` and `unity_of_being` — a two-register (Absolute/Relative) truth-claim, distinct from either |
| `divine_immanence` | `theology.ontological_structure` | sits beside `unity_of_being` — the pervading-presence claim generalized to all creation, distinct from `kingdom_within`'s human-specific indwelling |

These three existed as orphan `nodes` (created at tagging time, no family
membership) until this pass — same pre-existing gap noted in the node 09
section above, now closed for these three specifically. The other ~5 orphans
from earlier ingests are still untouched; out of scope here.

Synced: `python3 scripts/sync_taxonomy.py --apply` — 3 primary memberships
created, 0 moved/demoted.
