# book-of-ceremonial-magic — ingest decisions

One file per text. Append as you go; do not rewrite history when a later node
contradicts an earlier one — record the contradiction and what it cost.

---

## 01 — source-vetting · 2026-08-17 · claude

**Verdict:** verified

**URL:** https://sacred-texts.com/grim/bcm/index.htm (index/contents page;
primary text spans bcm00.htm through bcm80.htm)

**What the page is:** sacred-texts.com's hosting of A.E. Waite's *The Book of
Ceremonial Magic* (subtitle: "The Secret Tradition in Goëtia, including the
rites and mysteries of Goëtic theurgy, sorcery and infernal necromancy"),
London, [1913]. Scanned by J.B. Hare, Dec 2001–Nov 2002.

**Edition — the thing this vetting pass exists to settle.** The candidate
had proposed "1911" and flagged genuine ambiguity: Waite's first edition
(1898) was titled *The Book of Black Magic and of Pacts*; a second, wider
edition under the current title followed a few years later, and secondary
sources disagreed on the exact year. The page **states its own edition
history directly**, twice: the index page ("This book is the second edition
of a work which in its first edition was titled, more provocatively, *The
Book of Black Magic and of Pacts*") and the title page, in the redactor's
own bibliographic note ("This is the second edition of this book; the first
edition was titled *The Book of Black Magic*, and published in 1898; the
second edition contains substantially the same material as the first with
some additions.—JBH"). The title page date-stamps this specific scan
**[1913]**, not 1911. This is unambiguously the **second edition** — the one
actually meant by the proposed manifest entry — not the 1898 original.
`actual_edition.matches_claim` is true in substance (right edition, right
work) though the specific year the candidate proposed (1911) was off by two
years against what the page itself states (1913); both are safely pre-1929.

**Heading chain read:** Index — `<H1>The Book of Ceremonial Magic</H1>`,
`<H2>by Arthur Edward Waite</H2>`, `<H4>[1913]</H4>`, followed by a full
section-by-section table of contents (`<H3>` chapter headings, e.g. "Chapter
I: The antiquity of Magical Rituals", down to numbered `<A HREF>` sections).
Title page (bcm00) — `THE BOOK OF CEREMONIAL MAGIC` / `By ARTHUR EDWARD
WAITE` / `London` / `[1913]`. Spot-read bcm05 (Ch. I §1, "The Importance of
Ceremonial Magic") — confirmed real primary analytical prose, not apparatus.

**Is this a translation, or apparatus?** Not a translation — Waite's own
synthesis/commentary work in English, drawing on and quoting several
grimoires. Confirmed primary text (his own scholarly argument), not editorial
apparatus, by direct read.

**Pagination:** **multi** — 81 pages (bcm00 through bcm80): title, contents,
"Explanation of Full-Page Plates," preface, introduction, then Parts I & II
across nine numbered chapters with lettered/numbered sections. `format =
"html_multi"`, same pattern as `tertium-organum` and `kybalion`.

**Licence:** public_domain — positive evidence: pre-1929 publication ([1913],
London), and sacred-texts' redactor note dates the *first* edition to 1898,
confirming both editions predate the 1929 cutoff with room to spare.

**Format:** html (multi-page)

**Concerns for later nodes:**
- **Real, localized image-dependency — the same class of problem flagged for
  Waite's *Pictorial Key to the Tarot*, but contained to one sub-section
  instead of the whole book.** Chapter IV §7, "Talismans of the Sage of the
  Pyramids" (bcm26.htm–bcm35.htm, 10 of the 81 pages), consists of ritual
  instructions punctuated by bare `TALISMAN I. / Click to view` links with no
  textual description of the glyph itself — the image *is* the content there.
  Everything else spot-checked (Ch. I §1 general prose, and the front-matter
  "Explanation of Full-Page Plates," which is itself a real prose description
  of each plate's iconography, e.g. "The Angels of the Seven Planets, their
  Sigils...") reads as fully self-contained scholarly prose with no
  image-dependency. Recommend node 04/05 flag bcm26–35 specifically —
  exclude that sub-section or chunk it with an explicit caveat, rather than
  rejecting the book, which is otherwise the strongest-fit candidate of the
  four besides Kybalion.
- "Explanation of Full-Page Plates" (bcm02) is genuinely descriptive prose,
  not a bare caption list — worth a node-04 judgment call on whether to keep
  it as a chunk (real interpretive content on sigils/angels/planetary
  correspondences) or treat as front-matter apparatus like the title/TOC
  pages.
- Chapter/section headings are clean, real `<H3>` tags with a numbered
  `§`-scheme within chapters — `heading`-based chunking should work well,
  same shape as the other western_esoteric entries.
- Standard sacred-texts nav cruft present (same P1–P3 boilerplate classes
  already established elsewhere in this corpus).

---

## 04 — boilerplate-survey · 2026-08-17 · claude

**Classes found:**
- P2 ×82 — leading `Sacred Texts Grimoires Index Previous Next` header, every page.
- P1 — trailing `Next:`-style nav present on most pages (implicit in the P2-style header/footer wrap sacred-texts uses here; matches the established pattern).
- P6 ×1 — `book-of-ceremonial-magic-82` is the errata page in full: `Errata page 210: 'familars'->'familiars'`. Whole-page match, not a partial strip.
- New: "Click to view" plate captions (e.g. "Click to view THE SERPENT OF THE GARDEN OF THE HESPERIDES. From a Greek Vase Painting.") appear inline at illustration points throughout the main chapters.

**Proposed strips:** standard P1/P2, same rules as `tertium-organum.toml`. P6 (errata page) dropped whole — low risk, single dedicated page, matches the class definition exactly.

**Left alone:** "Click to view" plate captions — these document the book's own illustration program (what the plate depicts and its source), not archive packaging; stripping them would delete real bibliographic content. Confirmed at node 01 as genuinely descriptive, not bare "Click to view" with nothing else — **except** in Chapter IV §7 ("Talismans of the Sage of the Pyramids," bcm26–bcm35), where several instances genuinely are a bare `TALISMAN N. / Click to view` with no textual description — that sub-section's image-dependency (already flagged at node 01) is a chunk-config concern, not resolved by any boilerplate strip.

---

## 05 — chunk-config · 2026-08-17 · claude

**Strategy:** page-as-chunk, filename-based numbering with generic "Page {n}" labels — content-based CHAPTER/§ numbering rejected (see below).

**Rejected:**

| Strategy | Why not |
|---|---|
| `number_source=content`, `CHAPTER\s+([IVXLCDM]+)` | Only the first page of each chapter repeats the "CHAPTER N" heading; continuation pages (most of the book) start directly with "§ N." with no chapter context, so most pages would fall back anyway — worse, a naive pattern would mislabel every continuation page with a stale chapter number rather than falling back honestly. |
| Title extraction via `title_pattern` | Plain-text extraction collapses the HTML heading/body tag boundary — a page's heading and its first sentence run together with no reliable delimiter (headings don't reliably end in a period; body prose doesn't reliably start after one). No regex reliably isolates just the heading text. |

**Expected chunk count:** ~170 (82 raw pages, minus 2 front matter, minus 10 image-dependent Talismans pages, minus 1 errata page = 69 kept pages, at ~640 tokens/chunk average against 800 max_tokens ≈ 2.5 chunks/page) · **Actual:** 175, 111,884 tokens.

**Drops applied and verified:** title page + contents (via `drop_before_marker`, kept-from "EXPLANATION OF FULL-PAGE PLATES"), the 10-page Talismans of the Sage of the Pyramids sub-section (via `drop_chunk_patterns` matching `TALISMAN\s+[IVXLCDM]+\s*\.\s*Click to view`), and the errata page. Verified the Talismans drop doesn't over-match: one other chunk legitimately contains the word "TALISMAN" (a different, fully-described plate reference in Ch. II §1, "TALISMAN OF ARBATEL") and correctly survived, since its body doesn't match the bare `TALISMAN N. Click to view` pattern.

**Bug found and fixed during this node, not specific to this text:** `scripts/chunk.py`'s multi-page path stamped every chunk with the FIRST page's `source_url`, not the page it actually came from — confirmed on the already-live `tertium-organum` corpus too (every one of its 225 chunks cites `to00.htm` regardless of source page). Fixed in `scripts/chunk.py` + `scripts/chunkers/page_chunker.py` (per-page source_url now threaded through metadata). Re-chunked this text after the fix; verified `source_url` now varies correctly across sampled chunks (bcm02, bcm15, bcm48, bcm80). **Did not re-chunk any already-applied text** — that's live corpus data and out of scope for this pass; flagging for the user to decide whether the other ~11 `html_multi` sources need a re-chunk sweep.

---

## 09 (taxonomy pre-seed) · 2026-08-17 · claude

See `docs/ingest/decisions/kybalion.md`'s node 09 section for the full
writeup of the workbook gap (taxonomy pre-seeding has no judgement contract)
and the general method. This text's finding:

**Concept added:** `spirit_conjuration` (`concepts.praxis.ritual_and_symbolic`
— same family as `theurgy`, `word_power_incantation`, `sacred_names`, its
nearest neighbors). 89 of 175 chunks touch grimoire-evocation vocabulary
(goetia, seals, talismans, conjuration) with no adequate existing match:
`theurgy` is Iamblichean and ascent-oriented (the operator engaging the gods
through reverent, prepared receptivity); this text's central practice is the
inverse power relationship — compelling a subordinate spirit's appearance and
obedience through consecrated apparatus. `word_power_incantation` and
`sacred_names` are components this practice deploys (verbal force, name-
power), not the ritual structure itself. Full definition and disambiguation
in `concepts/taxonomy.toml`.

Synced together with the Kybalion additions in one `sync_taxonomy.py --apply`
run (see kybalion.md for the full sync report).
