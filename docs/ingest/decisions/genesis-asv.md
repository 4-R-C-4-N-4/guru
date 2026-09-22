# genesis-asv — ingest decisions

The first canonical biblical text in the corpus, and the first `biblical`
tradition. Genesis, John and Revelation were ingested together (branch
`feat/biblical-tradition`); the chunk-strategy reasoning here is shared by all
three, so the John and Revelation decision files point back to this one and only
record what differs.

---

## 01 — source-vetting · 2026-09-21 · claude

**Verdict:** verified

**Source:** `openbibleinfo/American-Standard-Version-Bible`, the
`usx-english-only/` tree, file `01-GEN.usx`.

**Licence:** public domain. The ASV (1901) text is public domain, and — this is
the load-bearing detail — the `usx-english-only/` files carry that text *without*
alignment markup. The repository's `-aligned/` trees additionally embed CC-BY
components (SBL Greek NT, MACULA Hebrew/Greek datasets) with attribution terms.
Using the english-only tree keeps the ingest cleanly public-domain with no
downstream attribution obligation. **Do not switch to an aligned file for
"richer" markup** — it changes the licence.

**Why ASV and not KJV/NIV.** NIV is copyright-encumbered (a stored, chunked
corpus is exactly what its licence forbids) — a non-starter. Between the
public-domain options the tension is faithfulness (ASV 1901 is the most literal
reputable PD English translation, on a critical text) versus esoteric resonance
(KJV is what Blavatsky/Golden Dawn/Boehme's translators actually quote). The
owner chose faithfulness. Recorded because a future reader will reasonably ask
why the corpus's biblical spine is not the KJV that its secondary sources cite.

---

## 03 — acquire · 2026-09-21 · claude

`format = "usx"`, dispatched to a new downloader `scripts/downloaders/usx.py`
(registered in `acquire.py`'s `FORMAT_DISPATCH`). Unlike the apocryphon PDF, the
USX source *is* fetchable over HTTPS, so a real downloader — reproducible from
the manifest like every other source — is the right pattern, not a no-downloader
local-file exception.

The extractor walks USX 3.0 in document order and emits one `[C:V] <verse>` block
per verse:

- `<note>` subtrees (translator/textual apparatus) are dropped entirely, but the
  verse text that *follows* a note is kept — apparatus is stripped before
  chunking, per the workbook.
- `<char style="add">` spans (ASV translator additions, italic in print) are
  unwrapped: the text is ASV rendering and stays in the body.
- Editorial section headings (`<para style="s*"/"d"/"r">`) carry no verse
  milestone, so their text falls outside any verse span and is dropped.
- The `[C:V]` marker is taken verbatim from the verse `sid` (`GEN 1:1` → `1:1`),
  so chapter tracking is inherent.

Verse counts verified against the printed canon at acquire time: **Genesis 1533,
50 chapters — contiguous, zero gaps.**

---

## 04–05 — chunk-config · 2026-09-21 · claude

**Strategy:** `regex-section-split` with `group_by = "tokens"`, `max_tokens = 800`,
`pattern = '(?=^\[(\d+:\d+)\])'`.

The owner's instruction: *split on verses, but chunk by the traditional ceiling
size as a max length.* That is neither pure pericope grouping nor one-chunk-per-
verse. It means: verse is the atomic boundary, but pack consecutive verses up to
the corpus-standard 800-token ceiling (420/421 configs use 800) and label each
chunk by the verse **range** it spans.

Neither existing splitter did both:

- `paragraph-group` packs to a token ceiling but only emits sequential
  `Section {n}` labels — no verse ranges.
- `regex-section-split` emits first–last range labels (when `group_size > 1`) but
  packs a *fixed verse count*, not to a token budget.

So `group_by = "tokens"` was added to `regex_splitter` — an additive,
backward-compatible mode (default stays fixed-count; all 26 existing
regex-section-split configs are untouched, 145 chunker tests still green). It
greedily packs sections to `max_tokens`, breaks only on a verse boundary, and
labels by first–last range. Covered by
`tests/test_regex_splitter_token_group.py` and, end-to-end, by the biblical
verse-tiling test.

**The `[C:V]` marker is kept in the body** via a zero-width lookahead pattern:
`group(1)` still captures the verse for the label, but nothing is consumed, so
verse numbers remain readable *inside* a multi-verse chunk. For a RAG that cites
scripture this preserves verse-level precision even though the retrieval/citation
unit is a range. (Alternative considered and rejected: a consuming pattern that
strips the markers — cleaner prose, but a retrieved 10-verse chunk could no
longer tell a reader which verse a phrase came from.)

**Result:** 73 chunks, token min/median/max = 256/780/800, no chunk over 800
(so no sub-split a/b suffixes), labels like `1:1-1:25`, `1:26-2:14` (chapter-
crossing), tiling the whole book. Verified: every chunk body starts at its
label's first verse; ranges are contiguous and non-overlapping.

**Why not put Genesis in `tests/test_enumerated_text_counts.py`:** that test is
for texts chunked 1:1 against their own numbering (one chunk per numbered unit).
Token-budget grouping is explicitly out of its scope per its own docstring. The
equivalent citation-integrity guard for range-grouped scripture is verse tiling
(every verse present exactly once, contiguous), asserted separately.

---

## 10–11 — tagging density · 2026-09-21 · owner + claude

Genesis is ingested **complete** (all 50 chapters). Chapters 12–50 are the
patriarchal-narrative lineage (Abraham, Jacob, Joseph) — low cross-tradition
parallel yield, high chunk count. The esoteric weight is front-loaded in 1–11
(creation, Eden, the Fall, the flood, Babel).

**Decision: do not hand-prune 12–50 at node 10.** Tag all chapters at normal
density, then cull the low-value lineage/genealogy tags at the node-11 review
gate, keeping anything worthwhile that surfaces from those chapters. Rationale
(owner): manual under-tagging pre-judges what is worthless; the review gate is
the correct place to hold down graph noise without discarding real signal.

**Primary cosmogony edge targets already in the corpus** (why 1–11 earns full
tagging): `enuma-elish` (Genesis 1), `apocryphon-of-john` (Genesis 1–11 gnostic
rewrite), `enoch-charles-1917` (Genesis 6, the Watchers).
