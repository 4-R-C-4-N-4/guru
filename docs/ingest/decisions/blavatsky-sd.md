# 04 — boilerplate-survey: H.P. Blavatsky — The Secret Doctrine

**Source:** `blavatsky-sd` · **Host:** sacred-texts.com · **Done:** 2026-08-22

## Surveyed pages

Sampled first/last files plus several mid-range content pages: sd-01, sd-02,
sd-03, sd-04, sd-05, sd-10, sd-25, sd-30, sd-50, sd-53, sd-70, sd-99.

## Boilerplate found

### B1 — Leading site-navigation line (P2 variant)

**Shape:** a single leading line on some pages:

```
Back to Esoteric Sacred Texts Back to Sacred Texts Main Index
```

**Occurrences:** sd-01 (TOC Vol 2), sd-99 (TOC Vol 1) — the two TOC pages.
Content pages (sd-02, sd-03, sd-04, sd-05, sd-50, sd-53, …) do NOT carry it;
they begin directly with the work title + page marker.

**Strip:** drop the leading paragraph matching `^Back to Esoteric Sacred Texts\s+Back to Sacred Texts Main Index`. Anchored at paragraph start — the phrase never appears mid-content. Risk low.

### B2 — Trailing "Next Section Contents" nav line (P1 variant)

**Shape:** a trailing line on content pages:

```
…the Occultist may remain satisfied, and care for no more. Next Section Contents
```

**Occurrences:** sd-02, sd-10, sd-25, sd-30, sd-53, sd-70, and (by the pattern)
every content page except the TOC pages. Verified on 6 sampled content pages;
safe to assume present on all 97 content pages.

**Strip:** drop the trailing paragraph matching `^\s*Next Section Contents\s*$`. Anchored at paragraph end. Risk low.

### B3 — "This page continued in next section" markers

**Shape:** mid-text or trailing marker:

```
…light. ------- [[This page continued in next section]] Next Section Contents
```

**Occurrences:** sd-10, sd-25, sd-30 — pages where the original book pagination
carries over to the next sacred-texts file. These are structural markers from
the original edition, not site nav.

**Decision:** leave alone. They are content-adjacent structural markers (the
original book's page-break continuation notes), not archive packaging. Removing
them would be content modification. Low embedding harm, and they are a genuine
feature of the source text.

## NOT stripped (per contract)

- **Inline `[[Vol. N, Page X]]` page markers:** present on every content page
  (e.g. `[[Vol. 1, Page xvii]]`, `[[Vol. 1, Page]] 35`, `[[Vol. 2, Page xv]]`).
  The decision doc explicitly says to retain them as citation anchors; they are
  the analogue of P4's `[Pg N]` markers but in a different format. The contract
  forbids stripping bare p. NN-style references, and these double as chunk
  headers for citation. Leave.
- **TOC pages (sd-01, sd-99):** genuine table-of-contents listings, not
  apparatus. Keep (with B1 stripped).
- **Title-page caption block on sd-01/sd-99** ("THE SECRET DOCTRINE: THE
  SYNTHESIS OF SCIENCE, RELIGION, AND PHILOSOPHY. by H. P. BLAVATSKY … London:
  THE THEOSOPHICAL PUBLISHING COMPANY, LIMITED. 1888."): publication metadata
  on the TOC pages, not boilerplate. Keep.

## Strip plan

Two paragraph-anchored pre_strip patterns, both low risk, neither drops a chunk:

1. `^Back to Esoteric Sacred Texts\s+Back to Sacred Texts Main Index` — leading
   nav line, TOC pages only.
2. `^\s*Next Section Contents\s*$` — trailing nav line, content pages.

## Chunk strategy (node 05)

`page-as-chunk` with `number_source = "filename"` and `max_tokens = 1500`.
Rationale:

- Each of the 99 raw files is a self-contained page of the original edition,
  with its own `[[Vol. N, Page X]]` marker — the natural chunk unit.
- Pages range from 2,816 tokens (sd-01) to 17,277 (sd-02); mean ~9,200 tokens.
  `max_tokens = 1500` keeps chunks in the embedding-friendly 1,000–1,500 token
  range: small pages (sd-01, sd-04) stay whole or split once; large pages
  (sd-02, sd-03, sd-53) subsplit into 8–12 chunks. Estimated ~250–350 chunks
  total across the 99 pages.
- `number_source = "filename"` gives every chunk a stable page number
  (`Page 01` … `Page 99`) regardless of content; the inline `[[Vol. N, Page X]]`
  markers in the bodies provide the original-edition citation anchors.
- Preserve the commentary. Blavatsky's commentary IS the primary text — nothing
  is stripped as apparatus.

## Risks

- `max_tokens = 1500` is a judgement call; re-runnable if retrieval testing
  shows chunks too coarse or too fine.
- The 99 raw files include sd-01 (Vol-2 TOC) and sd-99 (Vol-1 TOC) plus one
  file that may be a duplicate/misordered crawl capture — TODO confirm file
  inventory is exactly 99 pages and in order before node 06.
