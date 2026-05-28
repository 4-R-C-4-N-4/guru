Here's the evidence-based list, mined from the live v27 corpus and sorted by impact. The big realization: most of
  it is a boilerplate prefix on otherwise-good chunks (strip, keep the chunk) — not whole junk chunks. I confirmed
  stripping leaves real content.
  
  Tier 1 — strip the boilerplate, keep the chunk (highest impact)
  
  Pattern: Site nav prefix — ^Sacred Texts\b.*?\bPrevious\s+Next\b\s*
  Hits: 984 (~32%) 
  Notes: The single biggest win. Collection word varies (Classics / Zoroastrianism / Egypt EHH / Esoteric /
  Buddhism).
    Confirmed: stripping "Sacred Texts Buddhism Index Previous Next {p. 111} THE…" → "{p. 111} THE VAGRAKKHEDIKÂ OR 
    DIAMOND-CUTTER…" — real content survives.
  ────────────────────────────────────────
  Pattern: Page-break markers — \{\s*p\.\s*\d+\s*\}
  Hits: part of 1381  
  Notes: The brace form {p. 111} is a scan artifact — safe to strip. (Bare p. 111 without braces — see caveats.)
  ────────────────────────────────────────
  Pattern: Plate/figure/scan apparatus — click to enlarge, \bPlate\s+[IVXLC\d], \bFig\.
  Hits: ~110
  Notes: Image captions from the scans.

  Tier 2 — drop the whole chunk (pure apparatus, no content)

  ┌──────────────────────────────────┬───────┬───────────────────────────────────────────────────────────────────┐
  │             Pattern              │ Hits  │                             Examples                              │
  ├──────────────────────────────────┼───────┼───────────────────────────────────────────────────────────────────┤
  │ Nav/TOC pointers —               │ ~170+ │ "Next: Section 3", "Next: Chapter IV. The Book Am-Tuat…", "Next:  │
  │ ^(Next|Previous):\s              │       │ Book XI: Zâi Yû…"                                                 │
  ├──────────────────────────────────┼───────┼───────────────────────────────────────────────────────────────────┤
  │ Errata notes — ^Errata\b         │ few   │ "Errata page 88: 'astonied'->'astonished'"                        │
  └──────────────────────────────────┴───────┴───────────────────────────────────────────────────────────────────┘
  
  Tier 3 — structural, handle in the chunker (needs care, lower volume)
  
  - Leading document title / byline repeated at chunk start: "The Life and Doctrines of Jacob Boehme, by Franz 
  Hartmann, [translator]…". Strip the leading title line.
  - Editorial / philological footnotes interleaved in the body: (sic) (20), MS. / in his MS (22),
  manuscript-collation notes ("the word 'âidûm' stood… in his MS."). These are interleaved with real text — best
  fixed by separating the footnote stream at parse time, not a blanket string strip.

  Caveats — please don't over-trim

  1. Don't drop by length alone. "Jesus said, 'Become passers-by.'" is 9 tokens and is a real Gospel of Thomas 
  logion. Short ≠ junk. Combine length with a pattern.
  2. Bare p. N (no braces) can be a legitimate citation — only the {p. N} brace form is unambiguously a scan marker.
  3. Stripping changes the text → you must re-embed the affected chunks (their embeddings were computed on the 
  polluted text, which is part of why retrieval is off) and re-export. Strip-without-re-embed won't fix retrieval.
  4. Ideally strip at the source-HTML level in the chunker (sacred-texts.com has identifiable nav/header/footer
  elements) rather than regex on concatenated text — cleaner and avoids the false-positive risk above.
  
  The ^Sacred Texts … Previous Next prefix alone is ~⅓ of the corpus and safe — that's the 80/20.
  

