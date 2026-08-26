# 05 — chunk-config: H.P. Blavatsky — The Secret Doctrine

**Source:** `blavatsky-sd` · **Strategy:** page-as-chunk · **Done:** 2026-08-22

## Rationale

Each of the 99 raw files is one page of the original 1888 edition, with its own
`[[Vol. N, Page X]]` page marker — the natural chunk unit. `page-as-chunk`
produces one chunk per page (subsplit on oversize), so a chunk id maps to a
specific page of the book, and the inline `[[Vol. N, Page X]]` markers in the
bodies double as citation anchors.

## Config

```toml
[chunking]
strategy = "page-as-chunk"
section_label_format = "Page {n}"
max_tokens = 1500
number_source = "filename"

# Pre-strips (node 04 survey). Two patterns, both paragraph-anchored, both low
# risk, neither drops a chunk:
#   1. Leading nav line on the two TOC pages (sd-01, sd-99).
#   2. Trailing "Next Section Contents" nav line on content pages.
pre_strip_patterns = [
    "^Back to Esoteric Sacred Texts\\\\s+Back to Sacred Texts Main Index",
    "^\\\\s*Next Section Contents\\\\s*$",
]

# No drop_before_marker / drop_chunk_patterns: no separable whole-chunk
# apparatus block to drop. sd-01 (Vol-2 TOC) and sd-99 (Vol-1 Contents) are
# genuine TOC listings (not apparatus) — kept.
[metadata]
tradition = "western_esoteric"
text_name = "The Secret Doctrine"
sections_format = "page"
```

## Notes

- **Commentary retained.** Blavatsky's commentary is the primary text — nothing
  is stripped as apparatus. See `docs/ingest/decisions/blavatsky-sd.md`.
- **Page markers retained.** Inline `[[Vol. N, Page X]]` markers are kept (per
  the decision doc); the contract forbids stripping bare p. NN-style references,
  and these double as citation anchors.
- **`max_tokens = 1500`.** 99 pages range from ~2,816 tokens (sd-01) to ~17,277
  (sd-02), mean ~9,200. Small pages stay whole; large pages subsplit into
  8–12 chunks. Estimated ~250–350 chunks total. Re-runnable if retrieval
  testing shows a different sweet spot.
- **File inventory: 99 pages.** Confirm ordering (sd-01 = Vol-2 TOC first,
  sd-99 = Vol-1 Contents last) before node 06; the crawler may have captured an
  out-of-order or duplicate file.
