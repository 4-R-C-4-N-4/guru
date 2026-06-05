# SBE Downloader Patch — Necessity Assessment

*Companion to `extra.md` (the Upanishads manifest draft).*
*Conclusion up front:* **The patch is a quality improvement, not a prerequisite.**
The current `sacred_texts.py` extractor already ingests SBE-volume pages successfully
— the committed Zoroastrian Yasna corpus is the existence proof. The artifacts the
patch would prevent (bare-digit footnote refs glued to words; uncaptured trailing
Footnotes block) are present in those committed raw files today. The pipeline
tolerates them: BASELINE pre-strip + per-config pre-strip + the tag-review
apparatus-rejection layer absorb the dirt downstream. Ship the Upanishads on the
unpatched extractor; open the patch as a separate quality ticket scoped against
all SBE traditions (Zoroastrian, Buddhist, Vedanta).

---

## 1. Claim under test

From `docs/corpus-expansion/extra.md:31-46`:

> These SBE pages need two fixes in `extract_text_page()` that the current
> extractor lacks. Verified against sbe15009.htm raw markup:
> 1. FOOTNOTE/PAGE-MARKER STRIP — inline refs `<a href="...#fn_NN"><font size="1">N</font></a>`
>    are flattened by `get_text()` to bare digits glued to words ("Svetâsva 1").
> 2. FOOTNOTE BLOCK DROP — apparatus after `<h3 align="CENTER">Footnotes</h3>` is
>    not removed.

Two questions to answer:

- **A.** Is the markup analysis correct? Does the unpatched extractor actually
  produce these artifacts on SBE pages?
- **B.** If yes, does it matter — i.e., is the patch a blocker for ingesting
  the Upanishads, or a backlog quality improvement?

---

## 2. Methodology

Read the in-tree extraction and chunking code paths, then compare against the
committed raw output of an existing SBE source (Mills' Gathas, SBE31) to see
whether the predicted artifacts actually appear in production data.

Files examined:
- `scripts/downloaders/sacred_texts.py:138-204` — `extract_text_page()`.
- `scripts/chunk.py:60-101` — `BASELINE_PRE_STRIP` + `is_apparatus_chunk()`.
- `chunking/zoroastrianism/yasna-30.toml` — per-config chunking for an SBE source.
- `raw/zoroastrianism/yasna-30.txt` — committed raw text from an SBE page.
- `sources/manifest.toml:375-440` — existing Yasna manifest entries, used as the
  precedent for "one entry per text" of an SBE volume.

---

## 3. Findings

### 3.1 Is the markup analysis correct? — **Yes.**

`extract_text_page()` (`scripts/downloaders/sacred_texts.py:138-204`) does:

1. Find content container (`div.content`, `#content`, `<main>`, or `<body>`
   after stripping `nav/aside/footer/header`).
2. Decompose elements with class in `["footnotes", "notes", "fn"]`,
   `["ad", "advertisement", "adsense"]`, `["nav", "navigation", "menu"]`,
   `["caption", "credit", "source"]`.
3. `main.get_text(separator="\n")` — this is the failure surface for inline
   `<font size="1">N</font>` superscript refs: they get pulled in as bare digits.
4. `normalize_whitespace()` collapses the result.

There is **no** handler for:
- `<font size="1">` (the superscript footnote-ref carrier on SBE pages).
- `<sup>`.
- `<h3 align="CENTER">Footnotes</h3>` apparatus-block headers (the SBE pages do
  not use a class-based footnote container, so the class-list decompose above
  doesn't catch them).
- `<a name="page_xliv">` style page anchors with `<font size="1" color="green">`
  content.

So the patch's markup analysis is accurate against the actual extractor code.

### 3.2 Do the artifacts actually appear in committed raw output? — **Yes.**

Sampled `raw/zoroastrianism/yasna-30.txt`, ingested from
`https://sacred-texts.com/zor/sbe31/sbe31008.htm` (one of Mills' SBE31 Yasna
pages — same SBE markup template as Müller's SBE15 Upanishads). Concrete
artifacts in the committed raw text:

| Artifact | Example from yasna-30.txt | Predicted by patch? |
|---|---|---|
| Bare-digit footnote ref glued mid-sentence | `"a worse 5 , as to thought, as to word, and as to deed"` | Yes — item 1 |
| Bare-digit footnote ref before a period | `"(The qualifying words are all in the neuter 1 .)"` | Yes — item 1 |
| Inline `p. N` page marker mid-paragraph | `"the more bounteous spirit 5 chose the p. 31 [paragraph continues]"` | Yes — item 1 (page-anchor variant) |
| Footnotes apparatus block captured into raw | Full `Footnotes` section with `25:1`, `26:1`, … `35:6` notes appended after Translation | Yes — item 2 |
| `[paragraph continues]` artifact | `"chose the p. 31 [paragraph continues] (Divine) Righteousness"` | Adjacent — not patch-targeted; existing sacred-texts artifact |

So claim A is confirmed empirically, not just from markup inspection.

### 3.3 Does it matter? — **Mostly no, with one caveat.**

The reason it doesn't block: the pipeline has three downstream layers that
absorb SBE dirt today:

1. **`BASELINE_PRE_STRIP`** (`scripts/chunk.py:72-81`) — strips the
   sacred-texts nav/byline header, `{p. N}` brace page markers, the
   "Buy this Book at Amazon" preamble, "click to enlarge", and the per-page
   byline. Comment at `:63-65` explicitly notes that **bare `p. N` is left
   alone** because it's a legitimate citation form; that's a deliberate
   policy choice, not an oversight.
2. **Per-config `pre_strip_patterns`** (loaded at `scripts/chunk.py:192`) —
   each `chunking/{trad}/{id}.toml` can add a `pre_strip_patterns = […]`
   list. This is where a per-source regex cut of the `Footnotes…(EOF)` tail
   would live. The existing Yasna configs do **not** use this — they just
   let the apparatus through into the chunked text.
3. **`is_apparatus_chunk()`** (`scripts/chunk.py:84-101`) — a whole-chunk
   drop test that runs after chunking. Catches `Errata` blocks and short
   `Next:`/`Previous:` footer chunks. Combined with the `feedback_tag_reject_preface_chunks`
   review policy (recalled from MEMORY.md), apparatus chunks that survive
   into the chunked output get rejected at curation rather than tagged into
   the graph.

The bare-digit footnote refs (artifact 1) are **not** removed by any layer.
They're embedded into the final chunks and the embeddings learn around them.
This is the one signal-quality cost of leaving the patch unwritten — and it
already affects the committed Yasna chunks. The Upanishads would inherit
the same minor degradation, no worse.

The trailing Footnotes block (artifact 2) **can be** stripped per-config — the
draft manifest's "belt-and-suspenders" note (`extra.md:43`) is right that a
`pre_strip_patterns` regex for `^Footnotes\b[\s\S]*$` is the obvious fix. That
keeps the apparatus out of the chunked text without touching the downloader.

### 3.4 Manifest precedent: one-entry-per-text on an SBE volume — already done.

The Yasna entries in `sources/manifest.toml:386-440` show:
- Each Yasna chapter is its own `[[source]]` with `format = "html"`.
- Filenames don't match reading order: `sbe31006 = Yasna XXIX`,
  `sbe31007 = Yasna XXVIII`, `sbe31008 = Yasna XXX` (note in entry 386
  flags this explicitly).
- Per-Yasna `chunking/zoroastrianism/yasna-NN.toml` uses `paragraph-group`,
  no `pre_strip_patterns`.

This is the working template for the Upanishads. Same volume layout (SBE
single-text-per-page pattern), same filename-misorder quirk, same chunking
strategy. No downloader changes were made for the Yasnas; they shipped on
the current extractor.

---

## 4. Decision matrix

| Option | When it's right | Cost |
|---|---|---|
| **A. Ship Upanishads on current extractor; do no patch.** | If we accept the same minor signal degradation already present in the Yasna corpus. | 11+ texts ingested with bare-digit footnote refs and apparatus tails that need per-config `pre_strip_patterns` (or tag-review rejection) to keep out of chunks. |
| **B. Ship Upanishads now with a per-config `pre_strip_patterns` for the Footnotes tail; defer the downloader patch as a quality ticket.** | **Recommended.** Solves the apparatus-block problem at the chunking layer (where it's a 1-line regex per id) without coupling the Upanishads PR to an extractor change. Leaves the bare-digit-ref artifact, matching Yasna parity. | One ~5-token regex per Upanishad chunking config: `pre_strip_patterns = ['(?m)^Footnotes\\b[\\s\\S]*$']` (verified against the yasna-30.txt apparatus shape). |
| **C. Patch `extract_text_page()` first, then ingest Upanishads.** | If we want clean ingest *and* are willing to re-acquire the existing Yasnas (and Buddhist SBE49, SBE10, SBE11 if added per the expansion doc) for parity. | Couples the Upanishads PR to a cross-SBE quality ticket; raw files for existing SBE sources should be re-acquired so the corpus is uniform; rerun chunk + embed for affected sources. |

---

## 5. Recommendation

**Take option B.** Concretely:

1. Land the Upanishads with per-config `pre_strip_patterns = ['(?m)^Footnotes\\b[\\s\\S]*$']`
   in each `chunking/{slug}/{id}.toml`. (Trim to fit the actual apparatus
   header — verify against the first acquired raw file before committing the
   regex to all 11.)
2. Open a separate quality ticket: **"Strip inline `<font size="1">` superscript
   refs in `sacred_texts.extract_text_page()`"**. Scope it across all SBE-volume
   sources (Zoroastrian + future Buddhist SBE49/10/11 + new Vedanta) with a
   re-acquire + re-chunk + re-embed plan. This is the right shape for the
   change — not a side-effect of the Upanishads PR.
3. Optional follow-up: the bare `p. N` policy decision (`chunk.py:63-65`) is
   worth revisiting once the inline-ref strip lands, because the `p. N`
   markers were ambiguous *because* the footnote-ref digits looked similar;
   once the refs are gone, `p. N` could be cleanly stripped corpus-wide.

---

## 6. What this assessment does *not* cover

- The **URL-verification** problem (9/11 Upanishad URLs are `# GUESS`) is
  independent of the patch question and remains a prerequisite for ingest.
  See the URL-vetting pass that runs against `sources/manifest.toml` patterns.
- The **`vedanta` vs `upanishads` vs `hinduism`** tradition-slug decision is
  an upstream choice; doesn't affect the extractor question.
- The **diacritic-fold-at-embed-time** suggestion (`extra.md:47-50`) is a
  separate corpus-wide normalizer change. Treat as its own ticket.
