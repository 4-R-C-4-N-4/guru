# tarot-of-the-bohemians — ingest decisions

One file per text. Append as you go; do not rewrite history when a later node
contradicts an earlier one — record the contradiction and what it cost.

---

## 01 — source-vetting · 2026-08-17 · claude

**Verdict:** verified

**URL:** https://sacred-texts.com/tarot/tob/index.htm (index/contents page;
primary text spans tob00.htm through tob60.htm)

**What the page is:** sacred-texts.com's hosting of Papus's *The Tarot of the
Bohemians* (running title on this scan: *Absolute Key to Occult Science* /
*The Tarot of the Bohemians: The Most Ancient Book in the World, For the
Exclusive Use of Initiates*), translated from the French *Clef absolue de la
science occulte* by A.P. Morton, London: Chapman and Hall, Ltd., [1892].
Scanned by J.B. Hare, Sept. 2003.

**Heading chain read:** Index — `The Tarot of the Bohemians` / `By Papus
[Gérard Encausse, (b. 1865 d. 1916)]` / `Translated by A. P Morton` /
`[1892]`, followed by a full chapter/section TOC (22 Major Arcana entries,
Parts I–III, a 7-lesson divination section, author bibliography). Title page
(tob00) — `Absolute Key to Occult Science` / `The Tarot of the Bohemians` /
`By PAPUS` / `Original Title: Clef absolue de la science occulte` /
`Translated from the French By A. P. Morton` / `London, Chapman and Hall,
Ltd.` / `[1892]`. Spot-read tob14 ("1. The Juggler," the first Major Arcana
entry) — confirmed real primary text: Hebrew-letter/numerological argument,
not apparatus.

**Translator/edition match:** Candidate proposed A.P. Morton, English
translation "1896." The page itself stamps **[1892]** and names the
publisher (Chapman and Hall). Both years are external-secondary-source vs.
this-scan discrepancies of the same shape already seen on `kybalion`
(1908 vs. [1912]) — likely first-printing year vs. this-specific-printing
year — and both are safely pre-1929. Translator name matches exactly
(A.P. Morton). Treat as verified, not `wrong-edition`: translator, work, and
publisher all match; only the year differs, and only by a few years within
the same safely-PD window.

**Pagination:** **multi** — 61 pages (tob00 through tob60): title, preface,
contents, introduction, then Parts I–III (numerology/Kabbalah theory, the
22-card symbolic walkthrough, and applications/divination). `format =
"html_multi"`, same pattern as the tradition's other entries.

**Licence:** public_domain — **explicit** positive evidence, stated directly
on the title page: "This text is in the public domain. These files may be
used for any non-commercial purpose, provided this notice of attribution is
left intact." Also independently supported by pre-1929 publication.

**Format:** html (multi-page)

**Concerns for later nodes — image-dependency, the specific thing this
candidate was checked for:** This is a real but different case from Waite's
*Pictorial Key to the Tarot* (which was dropped from the candidate list for
exactly this problem). sacred-texts' own editorial note on the index page
warns of "abundant and profoundly esoteric tables, charts and diagrams," and
the sampled Major Arcana entry (tob14, "The Juggler") does open with
picture-referencing language ("If you take the first card of the Tarot and
examine it attentively, you will see that the form of the juggler depicted
upon it corresponds…"). **But** what follows is Papus's own argued
correspondence-schema (Hebrew letter Aleph → Top/Bottom/Right/Left →
divine/earthly/active/passive principles, mapped onward to Kabbalah and
Freemasonry symbolism) — independently meaningful text, not a bare
description of what's in the picture. This matches an earlier spot-check
this session of the same work under its alternate archive.org title
(*Absolute Key to Occult Science*), which read the book as ~85–90%
freestanding philosophical/numerological argument. Net assessment: **keep
this text**, but flag the ~22-page Major Arcana walkthrough (Part II, the
individual card chapters, tob14 onward) for extra attention at node 08
(readability-gate) — a chunk that opens mid-argument with "as you can see
from the figure" reads slightly worse standalone than the rest of the book,
even though the substance holds without the image. This is a matter of
degree, not a disqualifying defect.

- Chapter/section headings are clean (card names as page-level headers,
  e.g. "THE JUGGLER"), consistent with heading-based chunking already used
  elsewhere in this tradition.
- Standard sacred-texts nav cruft present (same P1–P3 boilerplate classes).
- Interior page-number markers (`p. 105`, `p. 108`, …) appear inline, same
  pattern already handled for other sacred-texts entries in this corpus —
  should survive as content per existing convention, not be stripped as
  boilerplate.

---

## 03 — acquire · 2026-08-17 · claude

Initial acquire resolved 63 pages, not the 61 confirmed at node 01 —
`tarot-of-the-bohemians-01` fetched `tarot/pkt/tarot0.htm`, the title page of
Waite's *Pictorial Key to the Tarot*, via a "Tarot Reading" header-breadcrumb
link on the index page. Same downloader defect as `kybalion` (see
docs/ingest/03-acquire.md's Failure modes) — fixed in
`scripts/downloaders/sacred_texts.py`. Stale raw files deleted and
re-acquired clean: 62 pages, all under `tarot/tob/` (one more than node 01's
61-page count from the visible TOC links — the extra page is legitimate,
sacred-texts' own errata/back matter, not re-flagged as contamination since
its `source_url` is under `tarot/tob/`).

---

## 04 — boilerplate-survey · 2026-08-17 · claude

**Classes found:**
- P2 ×62 — leading `Sacred Texts Tarot Tarot Reading Index Previous Next` header, every page.
- P1 — trailing `Next:`-style nav, standard pattern.
- Inline page markers (`p. 105`, `p. 108`, …) confirmed present as flagged at node 01 — left alone per corpus convention (indistinguishable from citation at regex level).

**Proposed strips:** standard P1/P2, same rules as `tertium-organum.toml`.

**Left alone:** the dense correspondence "tables" inside the Major Arcana chapters (e.g. astrology/Hebrew-letter/Kabbalah crosswalks rendered as run-on text: "Astronomy: The Moon ... Hebrew letter: Beth ... Reflex of God the Father or Osiris GOD the Son ISIS yod of he he he") — this is real content (Papus's own correspondence schema, the "tables, charts and diagrams" sacred-texts' own editorial note warned about), just poorly reflowed from an original tabular layout into linear text by the HTML extraction. Not boilerplate, so nothing to strip — but flagging again for node 08 (readability-gate) alongside the image-dependency concern already on record: these passages will read as dense/telegraphic even though nothing is missing.

---

## 05 — chunk-config · 2026-08-17 · claude

**Strategy:** page-as-chunk, `CHAPTER\s+([IVXLCDM]+)` content numbering (works cleanly for Parts I-III, one page per chapter — verified, unlike book-of-ceremonial-magic, no chapter spans multiple pages here), falling back to generic "Page {n}" for the 22 Major Arcana card pages (headed by card name, not "CHAPTER").

**Rejected:** a card-name title pattern for the Major Arcana section — considered, but the same heading/body plain-text collapse problem as book-of-ceremonial-magic applies (card name runs directly into body prose with no clean delimiter); generic fallback is honest rather than fragile.

**Expected chunk count:** 62 raw pages minus 3 dropped (contents, title, errata) = 59 kept pages · **Actual:** 134 chunks, 81,938 tokens.

**Drops verified:** contents page, title page (crawled out-of-sequence, landed last), errata page. The bibliography page ("Alphabetic Table of the Authors and Principal Works Quoted") was deliberately kept, not dropped — Papus's own compiled source list, not archive packaging.

**Same source_url bug as book-of-ceremonial-magic** (see that file's node 05 entry) — fixed in `scripts/chunk.py`/`page_chunker.py`, this text re-chunked after the fix and spot-verified (tob01, tob23, tob46, tob60 all show their own distinct URLs, not a shared fallback).

---

## 08 — readability-gate · 2026-08-17 · claude

**Verdict:** pass

**Signals, and whether each read as apparatus or breakage:** mean 2.2, worst 10.3 (chunk 110), dominant signals `caps_runs`, `dot_leaders`. Read the worst 5 chunks directly rather than trusting the score alone (per this node's own guidance — Gilgamesh precedent). Chunk 110 is the "List of the Authors Who Have Interested Themselves in the Tarot" bio-bibliography — genuine book structure, each author gets an ALL-CAPS name subheading (RAYMOND LULLE, CARDAN, POSTEL, …), which is exactly what triggers `caps_runs`. Chunk 021 and its neighbors are the Kabbalah/Tarot numerological correspondence tables flagged at nodes 01 and 04 — dense but genuine content, not damage; the original tabular layout collapses to choppy linear text once HTML table structure is lost, which is an extraction-fidelity ceiling, not a strip-plan defect fixable at node 05/07. One real but minor cosmetic artifact noted in passing: the sentence-boundary fallback splitter breaks on abbreviation periods (e.g. "J.\n\nA.\n\nVAILLANT" instead of "J. A. Vaillant"), fragmenting some paragraphs oddly — no words lost, just choppy breaks. Not specific to this text; a systemic quirk of `subsplit()`'s sentence-fallback path, out of scope for a single-text node 08 pass.

---

## 09 (taxonomy pre-seed) · 2026-08-17 · claude

See `kybalion.md`'s node 09 section for the workbook-gap writeup and method.
**Deliberate non-addition, no concepts added for this text.** Checked the
Hebrew-letter/Major-Arcana correspondence scheme (66 of 134 chunks) against
the taxonomy directly, spot-reading chunk content rather than inferring from
keyword hits alone: the fixed letter-card-meaning mapping is adequately
covered by existing `correspondence` (the structural mirroring claim),
`letter_meditation` (Hebrew letters as cosmic symbols, already in
`jewish_mysticism`'s family but tradition-agnostic per the taxonomy's own
design), and `numerical_mysticism`. No gap the size of Kybalion's or
Ceremonial Magic's turned up here.
