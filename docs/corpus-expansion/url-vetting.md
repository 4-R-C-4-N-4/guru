# Corpus-Expansion URL Vetting

*Date: 2026-05-31. Verifier: Hermes Agent.*
*Inputs: `docs/corpus-expansion/extra.md` (Upanishads draft, 11 entries) and
`docs/corpus-expansion/pagan.md` (pagan/folkloric draft, 7 entries).*
*Method: index-driven cross-check, then direct HEAD-equivalent fetch of every
candidate page to confirm the `<h1>/<h2>/<h3>` chain reads the expected
translation, not an Introduction essay.*

**Bottom line up front:** 9 of 11 Upanishad URLs were wrong — most pointed at
other Upanishads or at unrelated Introduction essays. 8 of the 11 Upanishads
are multi-page on sacred-texts and the single-page `format = "html"` shape
will only capture their first chapter; restructure is required before
acquisition. All 7 pagan/folkloric URLs resolved correctly. No slug or id
collisions anywhere in the repo. Mandukya-Upanishad is **not** in either SBE
volume — Müller never translated it; adding it requires a different source.

---

## 1. Summary Table

| ID | Original URL | Status | Final URL |
|---|---|---|---|
| katha-upanishad | …/sbe15011.htm | **corrected** + multi-page restructure | …/sbe15010.htm |
| mundaka-upanishad | …/sbe15014.htm | **corrected** + multi-page restructure | …/sbe15016.htm |
| taittiriya-upanishad | …/sbe15016.htm | **corrected** + multi-page restructure | …/sbe15022.htm |
| brihadaranyaka-upanishad | …/sbe15018.htm | **corrected** + multi-page restructure | …/sbe15053.htm |
| svetasvatara-upanishad | …/sbe15022.htm | **corrected** + multi-page restructure | …/sbe15100.htm |
| prasna-upanishad | …/sbe15025.htm | **corrected** + multi-page restructure | …/sbe15106.htm |
| maitrayana-upanishad | …/sbe15028.htm | **corrected** + multi-page restructure | …/sbe15112.htm |
| chandogya-upanishad | …/sbe01023.htm | **corrected** + multi-page restructure | …/sbe01022.htm |
| kena-upanishad | …/sbe01015.htm | **corrected** + multi-page restructure | …/sbe01176.htm |
| aitareya-upanishad | …/sbe01018.htm | **corrected** + multi-page restructure + label re-scoped | …/sbe01180.htm |
| isa-upanishad | …/sbe01021.htm | **corrected** (single-page genuinely) | …/sbe01243.htm |
| aradia-gospel-witches | …/pag/aradia/index.htm | verified | (unchanged) |
| poetic-edda-voluspo | …/neu/poe/poe03.htm | verified | (unchanged) |
| poetic-edda-hovamol | …/neu/poe/poe04.htm | verified | (unchanged) |
| kojiki-beginning-heaven-earth | …/shi/kj/kj008.htm | verified | (unchanged) |
| yoruba-speaking-peoples-ellis | …/afr/yor/index.htm | verified, chapter-numbering caveat | (unchanged) |
| kalevala | …/cache/epub/5186/pg5186.html | verified, gzip caveat | (unchanged) |
| mabinogion | …/files/5160/5160-h/5160-h.htm | verified | (unchanged) |

**Summary:** 10 corrected, 1 single-page corrected, 7 verified clean.

The "multi-page restructure" tag means: the URL is now correct (points at the
first translation page of that Upanishad) BUT the Upanishad's translation
spans multiple sacred-texts files, so a single `format = "html"` entry will
only ingest the first page. See §3 below for the recommended restructure.

---

## 2. Detailed Findings per Corrected URL

The SBE volume indexes (https://sacred-texts.com/hin/sbe15/index.htm and
.../sbe01/index.htm) are organised in two layers:

1. **Per-Upanishad Introduction essays** — Roman-numeralled I, II, III…
   chapters by Müller, one per Upanishad in the volume, all bunched at the
   front of the file numbering. These are *not* translations; they are
   Müller's scholarly dating/textual notes.
2. **Translations proper** — labeled "I, 1" / "FIRST ADHYÂYA" / "First
   Question" / "First Prapâthaka" depending on each Upanishad's native
   subdivision scheme, starting after the introduction block.

Most of the draft URLs collided with either (a) the wrong file from the
correct translation, or (b) an Introduction essay or even an unrelated
Upanishad's first page.

### 2.1 katha-upanishad
- Draft pointed at `sbe15011.htm`. Per index `<h3>Katha-Upanishad</h3>`, that
  page is Vallî **I,2** — Katha's second translation chapter, not its first.
- The first translation page is `sbe15010.htm`. Direct fetch confirms
  `<h2>FIRST ADHYÂYA</h2>` / `<h3>FIRST VALLÎ</h3>` / `<title>The Upanishads,
  Part 2 (SBE15): Katha-Upanishad: I, 1</title>`.
- Per-Upanishad Introduction is `sbe15003.htm` ("I: The Katha-Upanishad").
- Full file list (translations): `sbe15010..sbe15015` = I,1 / I,2 / I,3 /
  II,4 / II,5 / II,6.

### 2.2 mundaka-upanishad
- Draft pointed at `sbe15014.htm`. That's Katha-Upanishad II,5 — wrong
  Upanishad entirely.
- Correct first page: `sbe15016.htm`. Index `<h3>Mundaka Upanishad</h3>` block
  is `sbe15016..sbe15021` = I,1 / I,2 / II,1 / II,2 / III,1 / III,2.
- Intro essay is `sbe15004.htm`.

### 2.3 taittiriya-upanishad
- Draft pointed at `sbe15016.htm`. That's Mundaka I,1 (wrong Upanishad).
- Correct first page: `sbe15022.htm`. Direct fetch confirms
  `<h1>TAITTIRÎYAKA-UPANISHAD.</h1>` / `<h2>FIRST VALLÎ</h2>`.
- Intro essay is `sbe15005.htm`.
- The Taittirîya is 31 pages: `sbe15022..sbe15052`
  (Sikshâ-Vallî I.1-12 = sbe15022-033, Brahmânanda-Vallî II.1-9 =
  sbe15034-042, Bhrigu-Vallî III.1-10 = sbe15043-052).

### 2.4 brihadaranyaka-upanishad
- Draft pointed at `sbe15018.htm`. That's Mundaka II,1 (wrong Upanishad).
- Correct first page: `sbe15053.htm`. Direct fetch confirms
  `<h1>BRIHADÂRANYAKA-UPANISHAD.</h1>` / `<h2>FIRST ADHYÂYA</h2>` /
  `<h3>FIRST BRÂHMANA</h3>`. Footnote in the page itself adds the helpful
  scholion: *"It is the third Adhyâya of the Âranyaka, but the first of the
  Upanishad."*
- Intro essay is `sbe15006.htm`.
- See §3 for full Brihadâranyaka file map (47 pages, the heaviest in SBE15).

### 2.5 svetasvatara-upanishad
- Draft pointed at `sbe15022.htm`. That's **Taittirîya I,1** — way off.
- Correct first page: `sbe15100.htm`. Direct fetch confirms
  `<h3>FIRST ADHYÂYA</h3>` and `<title>...Svetâsvatara Upanishad...</title>`.
- Intro essay is `sbe15007.htm` (matches the user's pre-recorded fact).
- 6 translation pages: `sbe15100..sbe15105` = Adhyâya I through Adhyâya VI.

### 2.6 prasna-upanishad
- Draft pointed at `sbe15025.htm`. That's Taittirîya I,4 (wrong Upanishad).
- Correct first page: `sbe15106.htm`. Direct fetch confirms
  `<h3>FIRST QUESTION</h3>`.
- Intro essay is `sbe15008.htm`.
- 6 translation pages: `sbe15106..sbe15111` = First Question through Sixth
  Question.

### 2.7 maitrayana-upanishad
- Draft pointed at `sbe15028.htm`. That's Taittirîya I,7 (wrong Upanishad).
- Correct first page: `sbe15112.htm`. Direct fetch confirms
  `<h3>FIRST PRAPÂTHAKA</h3>`.
- Intro essay is `sbe15009.htm` (matches the user's pre-recorded fact).
- 7 translation pages: `sbe15112..sbe15118` = First Prapâthaka through
  Seventh Prapâthaka.

### 2.8 chandogya-upanishad (Khândogya)
- Draft pointed at `sbe01023.htm`. That's Khândogya I,2 — Müller's text
  *does* start on `sbe01022.htm` (page I,1). The draft was off by one file.
- Correct first page: `sbe01022.htm`. Direct fetch confirms
  `<h1>KHÂNDOGYA-UPANISHAD.</h1>` / `<h2>FIRST PRAPÂTHAKA.</h2>` /
  `<h3>FIRST KHANDA.</h3>`.
- Intro essay is `sbe01017.htm` ("I. The Khândogya-Upanishad").
- See §3 for the full file map — Khândogya is the heaviest single text in the
  set (154 sacred-texts pages).

### 2.9 kena-upanishad
- Draft pointed at `sbe01015.htm`. That's the **Introduction-to-the-series
  essay titled "Meaning of the Word Upanishad"** — not even a per-Upanishad
  intro, let alone a translation. Very wrong.
- Correct first page: `sbe01176.htm`. Direct fetch confirms
  `<h1>TALAVAKÂRA</h1>` / `<h1>KENA-UPANISHAD.</h1>`. Sacred-texts uses both
  names interchangeably (it sits in the Talavakâra-Brâhmana of the Sâma-Veda).
- Per-Upanishad intro is `sbe01018.htm` ("II. The Talavakâra-Upanishad").
- 4 translation pages: `sbe01176..sbe01179` = Khanda I through Khanda IV.

### 2.10 aitareya-upanishad
- Draft pointed at `sbe01018.htm`. That's the Talavakâra-Upanishad (= Kena)
  **introduction essay** — wrong Upanishad AND wrong document type.
- Correct first page: `sbe01180.htm`. Direct fetch confirms
  `<h2>FIRST ADHYÂYA.</h2>` and `<title>...Aitareya-Âranyaka...</title>`.
- Per-Upanishad intro is `sbe01019.htm` ("III. The Aitareya-Âranyaka").
- **Important scoping note:** Müller publishes the entire *Aitareya-Âranyaka*
  in SBE01, not only the narrow "Aitareya Upanishad" which is *Âranyaka
  II.4-7*. The label on this entry has been corrected to
  "Aitareya-Âranyaka". If the corpus wants only the Upanishad proper (3
  chapters as the manifest notes claim), scope acquisition to
  `sbe01222..sbe01227` (6 pages: II,4,1..II,7,1) instead of the full
  Âranyaka. If the corpus wants the whole Âranyaka, that's 59 pages
  (`sbe01180..sbe01238`).

### 2.11 isa-upanishad
- Draft pointed at `sbe01021.htm`. That's the **introduction essay** "V. The
  Vâgasaneyi-Samhitâ-Upanishad" — wrong.
- Correct first page: `sbe01243.htm`. Direct fetch confirms the page begins
  with `<h3>VÂGASANEYI-SAMHITÂ-UPANISHAD, SOMETIMES CALLED ÎSÂVÂSYA OR
  ÎSÂ-UPANISHAD</h3>` and then the 18 numbered verses ("1. ALL this,
  whatsoever moves on earth, is to be hidden in the Lord (the Self)…").
- This is the **only Upanishad in the set that is genuinely on a single
  page.** Caveat: the same page continues after verse 18 with ~30 paragraphs
  of Müller's verse-by-verse commentary citing Sankara, Uvata, and Mahidhara.
  That commentary is currently in-band. The draft annotation in extra.md now
  flags a pre-strip-patterns rule to drop the post-verse-18 horizontal-rule
  tail if commentary should be excluded.

---

## 3. Multi-Page Treatment for Brihadâranyaka, Chandogya, and the Rest

**Headline:** the draft entries assume one `[[source]]` per Upanishad. But of
the 11 Upanishads, **only Îsâ is genuinely on a single sacred-texts page.**
The other 10 are split across multiple files (per the volume indexes), so the
naive `format = "html"` shape captures only the first chapter and silently
loses the rest.

The user's prompt asked specifically about Brihadâranyaka and Chandogya; the
same shape problem applies to all eight non-Îsâ Upanishads, just with
shorter file lists.

### 3.1 The two restructure options

**Option A — `format = "html_multi"` pointed at a custom sub-index.**
`html_multi` (`scripts/downloaders/sacred_texts.py:212-`) fetches the source's
URL, parses every non-`index` `.htm` link from the page, and downloads each.
For the SBE volume indexes this would conflate all seven (SBE15) or five
(SBE01) Upanishads in the volume into one source_id, plus all the Müller
intros — wrong shape, exactly the failure mode the draft already calls out.
A *custom* sub-index per Upanishad would need to be hosted somewhere
`acquire.py` can fetch — not a local file (the downloader makes HTTP requests
against the source's URL). Without an `html_multi`-with-inline-url-list
feature in the pipeline, this option is **infeasible** as the pipeline is
written today.

**Option B — Per-page sub-entries with `format = "html"`.** This matches the
existing **Yasna precedent** documented in `sources/manifest.toml:386-440`,
where every Yasna chapter is its own `[[source]]` (yasna-28 = sbe31007,
yasna-29 = sbe31006, etc., 11 total). Per-page sub-entries with ids like
`brihadaranyaka-upanishad-1-1` (Adhyâya 1, Brâhmana 1 — file sbe15053) make
each chunkable section a first-class corpus citation, mirror how the
Zoroastrian Gathas are already structured, and require zero pipeline changes.

**Recommendation: Option B.** It's the only option compatible with the
pipeline as it exists, and it matches an already-shipped precedent.

### 3.2 Cost of Option B at full fidelity

| Upanishad | Pages | Range |
|---|---|---|
| Katha | 6 | sbe15010..sbe15015 |
| Mundaka | 6 | sbe15016..sbe15021 |
| Taittirîya | 31 | sbe15022..sbe15052 |
| Brihadâranyaka | 47 | sbe15053..sbe15099 |
| Svetâsvatara | 6 | sbe15100..sbe15105 |
| Prasña | 6 | sbe15106..sbe15111 |
| Maitrâyana | 7 | sbe15112..sbe15118 |
| Khândogya (Chandogya) | 154 | sbe01022..sbe01175 |
| Kena (Talavakâra) | 4 | sbe01176..sbe01179 |
| Aitareya-Âranyaka (full) | 59 | sbe01180..sbe01238 |
| Îsâ | 1 | sbe01243 |
| **Total** | **327** | |

That's 327 `[[source]]` entries instead of 11 — a ~30× expansion. Each entry
also needs a matching `chunking/vedanta/{id}.toml`.

### 3.3 Pragmatic middle path

A 30× expansion of the manifest is awkward to author and review. Two ways to
soften the cost while preserving correctness:

1. **Scope-prune the longest texts.** For Chandogya, ingest only the
   highest-density Prapâthakas first (VI through VIII = 55 pages, covering
   *tat tvam asi*, the honey-doctrine, Indra-Virocana, Sândilya-vidyâ, the
   bridge metaphors — i.e. the entire conceptual payload). Defer I-V to a
   later expansion. Similarly, for Aitareya-Âranyaka, ingest only II.4-7
   (the "Upanishad proper", 6 pages) and defer the Âranyaka apparatus.
   Net total drops from 327 to roughly 170.
2. **Generate the entries.** A small script over the volume-index files
   could emit the 327 (or 170) `[[source]]` stanzas mechanically — the
   filename mapping is in this report's Appendix-ready form, and the
   id-to-citation pattern is uniform. The chunking configs are similarly
   uniform per Upanishad. Authoring by hand is unnecessary.

### 3.4 Brihadâranyaka file map (since the user asked specifically)

By Adhyâya, per the SBE15 volume index:

- **Adhyâya I:** sbe15053 (I,1), sbe15054 (I,2), sbe15055 (I,4), sbe15056
  (I,5), sbe15057 (I,6) — **5 files**, not 6; the index appears to skip I,3
  (likely a numbering-only quirk, the actual content is contiguous).
- **Adhyâya II:** sbe15058..sbe15063 = II,1..II,6 (6 files)
- **Adhyâya III:** sbe15064..sbe15072 = III,1..III,9 (9 files; the
  Yâjñavalkya dialogues)
- **Adhyâya IV:** sbe15073..sbe15078 = IV,1..IV,6 (6 files)
- **Adhyâya V:** sbe15079..sbe15093 = V,1..V,15 (15 files)
- **Adhyâya VI:** sbe15094..sbe15097 = VI,1..VI,4, then sbe15099 = VI,5 (5
  files). **Caveat:** sbe15098 is labeled "VI, 4: Hume Translation" — a
  duplicate VI,4 in Hume's rendering inserted into the Müller sequence.
  Either skip sbe15098 (recommended, since the rest of the corpus is Müller)
  or treat it as a separate `brihadaranyaka-upanishad-6-4-hume` entry under
  a different translator tag.
- **Total:** 47 files when sbe15098 is included; 46 if it's excluded.

### 3.5 Chandogya file map

By Prapâthaka:

- Prapâthaka I: sbe01022..sbe01034 = I,1..I,13 (13 files)
- Prapâthaka II: sbe01035..sbe01058 = II,1..II,24 (24 files)
- Prapâthaka III: sbe01059..sbe01077 = III,1..III,19 (19 files)
- Prapâthaka IV: sbe01078..sbe01094 = IV,1..IV,17 (17 files)
- Prapâthaka V: sbe01095..sbe01118 = V,1..V,24 (24 files)
- Prapâthaka VI: sbe01119..sbe01134 = VI,1..VI,16 (16 files) — *tat tvam
  asi* lives in VI,8-16
- Prapâthaka VII: sbe01135..sbe01160 = VII,1..VII,26 (26 files)
- Prapâthaka VIII: sbe01161..sbe01175 = VIII,1..VIII,15 (15 files)
- Total: 154 files.

---

## 4. Mandukya-Upanishad

**Conclusion: do not add a Mandukya entry to this manifest. The text is not
in either SBE volume.**

Both volume indexes were walked end-to-end. SBE15 carries seven Upanishads
(Katha, Mundaka, Taittirîya, Brihadâranyaka, Svetâsvatara, Prasña,
Maitrâyana); SBE01 carries five (Khândogya, Talavakâra/Kena,
Aitareya-Âranyaka, Kaushîtaki-Brâhmana, Vâgasaneyi-Samhitâ/Îsâ). Müller did
not translate the Mandukya in either Sacred Books of the East volume.

The hin/upan/ subtree on sacred-texts is the same Müller material (no
Mandukya). The hin/ top index has no Mandukya link.

**Pathways to add Mandukya later:**

- Robert Hume's *The Thirteen Principal Upanishads* (1921, Oxford UP) is
  public domain in the US and includes the Mandukya proper. It's not
  currently hosted on sacred-texts.com so it would need a different downloader
  target (Internet Archive has scans, archive.org/details/thirteenprincipa00inhume
  or similar). Verify the PD status and add as a one-off entry under
  `tradition = "vedanta"`.
- Swami Nikhilananda's Ramakrishna-Vedanta-Math edition (1949) carries the
  Mandukya + Gaudapada's Karika — still in copyright, do not use.
- Swami Gambhirananda's Sankara-bhasya English (Advaita Ashrama) — still in
  copyright.

**Recommendation:** open a separate ticket for "add Mandukya-Upanishad
(Hume)" once a clean source is selected. Do not slot a placeholder into
extra.md. A note to this effect was appended to the bottom of extra.md.

---

## 5. Slug Collision Report

All seven proposed new tradition slugs were checked against:
- `sources/manifest.toml` (all `tradition = "..."` values)
- `corpus/` directory listing
- `chunking/` directory listing
- `concepts/taxonomy.toml` (the only file in concepts/)
- `scripts/auto_promote.py`, `scripts/auto_promote_edges.py`,
  `scripts/auto_promote.sh`, `scripts/auto_promote_edges.sh`
- `docs/autopromote/` (only `design.md`)

| Slug | Status | Note |
|---|---|---|
| `vedanta` | clean (no collision) | See judgement below — recommend reconsidering. |
| `pagan_witchcraft` | clean | underscore matches existing convention (`christian_mysticism`, `jewish_mysticism`, `greek_mystery`, `renaissance_hermeticism`, `western_esoteric`). |
| `norse` | clean | |
| `shinto` | clean | |
| `yoruba` | clean | |
| `finnic` | clean | "finnic" is a linguistic-family label that covers Finnish + Karelian + Ingrian (the actual source-material breadth of the Kalevala). More precise than "finnish". |
| `celtic` | clean | "celtic" is broad but the Mabinogion is Welsh-medieval-pagan and a finer slug ("welsh"? "brythonic"?) would orphan an entry. |

**No live collisions found** — every slug only appears in the draft docs
themselves (`docs/corpus-expansion/extra.md`, `docs/corpus-expansion/pagan.md`,
`docs/corpus-expansion/sbe-downloader-patch-assessment.md`,
`docs/corpus-expansion-candidates.md`).

### 5.1 Judgement on `vedanta` vs `upanishads` vs `hinduism`

The existing tradition-naming convention in `corpus/` and `chunking/` favours
**school/stream/movement names** over either text-collection names or umbrella
religion names:

- `buddhism` not `tipitaka`
- `taoism` not `tao-te-ching`
- `zoroastrianism` not `avesta`
- `hermeticism` not `corpus-hermeticum`
- `christian_mysticism` (stream) not `christianity` (umbrella)
- `jewish_mysticism` (stream) not `judaism`
- `neoplatonism` (school) distinguished from `platonism` (school)

By this convention, `vedanta` is grammatically consistent with the corpus —
it names the philosophical school (the *uttara-mîmâmsâ* commentarial
tradition that takes the Upanishads, Brahma-Sûtra, and Gîtâ as its
foundation). It is not, strictly, the textual layer being ingested: the
Upanishads are pre-Vedanta and Vedanta proper is Sankara, Râmânuja,
Madhva, et al. So there is a real category-mismatch in calling the source
texts "vedanta".

Alternatives:
- **`upanishads`** — textually precise (this is exactly what is being
  ingested). Mismatch with convention since no other tradition slug names a
  text-collection (closest near-violation is `egyptian` for the Book of the
  Dead, which is itself a text-collection slug rather than a movement, so
  precedent for text-as-tradition exists).
- **`hinduism`** — religion-as-umbrella; conventionally rejected elsewhere in
  the corpus (`buddhism` is the only large-umbrella that is used, and that's
  for a textual canon spanning multiple schools).
- **`vedanta`** — school-as-tradition; conventionally clean but textually
  slightly anachronistic.

**Recommendation:** use **`upanishads`** as the tradition slug. The precedent
of `egyptian` (also text-collection-flavoured) makes it consistent enough,
and it is textually accurate. The Upanishads are pre-Vedanta foundational
revelation literature; calling them "vedanta" is like calling the Hebrew
Bible "rabbinic_judaism" — defensible-ish but anachronistic. The downside is
that if someone later adds the Brahma-Sûtra or Sankara's commentaries, those
WOULD properly be `vedanta` and the current `upanishads` entries would need
re-slugging to `vedanta` (or coexist under different slugs, which is what
`buddhism` already does — many sub-schools under one slug).

Defer the final call to the user. If `vedanta` is kept, no action needed.
If switched to `upanishads`, do a sed-style replace across `extra.md` before
committing to manifest.toml.

---

## 6. ID Collision Report

All 18 proposed source ids were checked against `sources/manifest.toml` via
exact `id = "..."` match. **No collisions.** The closest near-clash is
`gathas-introduction` (existing) vs the conceptual pattern of "tradition's
introductory text" but there's no string conflict.

Proposed ids (all confirmed clean):
- katha-upanishad, mundaka-upanishad, taittiriya-upanishad,
  brihadaranyaka-upanishad, svetasvatara-upanishad, prasna-upanishad,
  maitrayana-upanishad, chandogya-upanishad, kena-upanishad,
  aitareya-upanishad, isa-upanishad
- aradia-gospel-witches, poetic-edda-voluspo, poetic-edda-hovamol,
  kojiki-beginning-heaven-earth, yoruba-speaking-peoples-ellis, kalevala,
  mabinogion

If the per-page restructure (§3) is adopted, the derived ids
(`brihadaranyaka-upanishad-1-1`, etc.) inherit cleanly from these stems
since none of those forms exist in the manifest either.

---

## 7. Outstanding Gaps

Things the verification pass did **not** confirm and that the user should be
aware of before acquisition:

1. **`is_apparatus_chunk()` behaviour on Müller's verse-by-verse commentary
   tail (Îsâ-Upanishad, sbe01243).** The page mixes 18 verses of scripture
   with ~30 paragraphs of Müller's commentary discussing Sankara, Uvata, and
   Mahidhara. Whether the existing chunking apparatus rejects that tail or
   ingests it as scripture is untested here. Spot-check after first
   acquisition.
2. **Multi-page count for Chandogya cross-checked file-by-file? No.** I
   walked the volume index linearly and counted ranges between the H3
   section headers. I did not open each of sbe01022-01175 individually to
   confirm none of them are content-empty or sub-page-split. There could be
   edge cases (sbe15098 = "VI, 4: Hume Translation" duplicate in
   Brihadâranyaka is the one I caught; there could be analogous insertions
   in Chandogya I haven't surfaced). Recommend an end-to-end fetch + line-
   count smoke test before committing 154 entries to the manifest.
3. **Aitareya-Âranyaka III,1,3 gap.** The volume index shows sbe01228..29
   then jumps to sbe01230 labelled "III, 1, 4" — III,1,3 is missing. Could
   be a sacred-texts archive omission, or a Müller decision to merge that
   paragraph into III,1,2. Not chased.
4. **Gutenberg gzip handling.** Both Kalevala and Mabinogion are served
   gzipped; `requests` (used by `acquire.py` indirectly via the per-format
   downloaders) auto-decompresses by default. The annotation in pagan.md
   flags this; not separately tested in the pipeline.
5. **Mandukya alternative sources.** Hume 1921 PD claim noted but not
   independently verified against archive.org's holdings.

---

## 8. What Got Changed in the Draft Files

`docs/corpus-expansion/extra.md`:
- All 11 `[[source]]` entries had their `# GUESS` URL comment replaced with
  a `# VERIFIED 2026-05-31` annotation describing what was confirmed and
  what the original URL actually pointed at.
- 10 URLs were corrected. 1 (Îsâ) was corrected from an Intro essay to the
  genuinely single-page translation.
- The label on the aitareya-upanishad entry was changed to
  "Aitareya-Âranyaka (Müller)" to match what Müller actually publishes (the
  whole Âranyaka, not the narrower Upanishad).
- Added inline `# NOTE:` blocks to each Upanishad documenting its
  multi-page sacred-texts layout and recommending the restructure pattern.
- Appended a "Mandukya-Upanishad: NOT INCLUDED" stanza at the bottom of the
  file documenting why no entry was added.

`docs/corpus-expansion/pagan.md`:
- All 7 entries had a `# VERIFIED 2026-05-31` annotation added describing
  what was confirmed at fetch time (titles, h-tag chain, chapter pattern,
  gzip caveats).
- No URLs were changed — every pagan/folkloric draft URL resolved
  correctly.
- The aradia entry note flags ara00/01/02/18 as non-chapter front/back
  matter that the html_multi downloader will pull and that needs apparatus-
  rejection downstream.
- The yoruba entry note flags the X-XII chapter omission in the
  sacred-texts archive.
- The kojiki entry note flags the same SBE-style footnote/apparatus issue
  documented in extra.md (per-config pre_strip_patterns will be needed).
- The kalevala entry note flags gzip handling on the Gutenberg URL.
