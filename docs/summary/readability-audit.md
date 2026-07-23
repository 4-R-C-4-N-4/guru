# Readability audit — corpus chunk bodies (todo:82e3a09d)

**Date:** 2026-07-23 · **Scanner:** `scripts/audit_readability.py` · **Corpus:** 4,923 chunks / 214 texts

The public reader (guru-ai.org/read, guru-web#106) serves chunk bodies verbatim,
so formatting damage is now user-facing. This audit ranks every text by
heuristic damage score (0–100, higher = worse; see the scanner docstring for
signal definitions). Regenerate with:

```
python3 scripts/audit_readability.py --format markdown --min-score 5
```

## Ranked findings (mean score ≥ 5)

| text | chunks | mean | worst (chunk) | dominant signals |
|---|---|---|---|---|
| shinto/kojiki-beginning-heaven-earth | 1 | 16.9 | 16.9 (shinto.kojiki-beginning-heaven-earth.001) | page_marks, footnotes, brackets |
| mandaean/gnostic-john-baptizer-3 | 24 | 16.0 | 40.7 (mandaean.gnostic-john-baptizer-3.021) | page_marks, hard_wrap, brackets |
| mandaean/gnostic-john-baptizer-2 | 10 | 15.4 | 33.6 (mandaean.gnostic-john-baptizer-2.007) | page_marks, hard_wrap, brackets |
| mandaean/gnostic-john-baptizer-1 | 32 | 14.5 | 36.0 (mandaean.gnostic-john-baptizer-1.023) | page_marks, hard_wrap, caps_runs |
| mesopotamian/gilgamesh-tablet-08 | 1 | 13.9 | 13.9 (mesopotamian.gilgamesh-tablet-08.001) | brackets, dot_leaders |
| mesopotamian/gilgamesh-tablet-06 | 4 | 12.6 | 14.7 (mesopotamian.gilgamesh-tablet-06.001) | brackets, dot_leaders, caps_runs |
| mesopotamian/gilgamesh-tablet-05 | 2 | 11.3 | 12.6 (mesopotamian.gilgamesh-tablet-05.001) | brackets, dot_leaders, caps_runs |
| mesopotamian/gilgamesh-tablet-04 | 2 | 10.9 | 11.7 (mesopotamian.gilgamesh-tablet-04.001) | brackets, dot_leaders |
| mesopotamian/gilgamesh-tablet-10 | 4 | 10.9 | 12.1 (mesopotamian.gilgamesh-tablet-10.001) | brackets, dot_leaders |
| mesopotamian/gilgamesh-tablet-12 | 3 | 10.6 | 11.0 (mesopotamian.gilgamesh-tablet-12.003) | brackets, caps_runs |
| mesopotamian/gilgamesh-tablet-03 | 5 | 9.9 | 11.2 (mesopotamian.gilgamesh-tablet-03.001) | brackets |
| zoroastrianism/yasna-47 | 1 | 9.0 | 9.0 (zoroastrianism.yasna-47.001) | page_marks |
| mesopotamian/gilgamesh-tablet-07 | 2 | 8.8 | 12.7 (mesopotamian.gilgamesh-tablet-07.001) | brackets, dot_leaders |
| mesopotamian/gilgamesh-tablet-01 | 6 | 8.6 | 10.6 (mesopotamian.gilgamesh-tablet-01.001) | brackets |
| mesopotamian/gilgamesh-tablet-02 | 2 | 8.3 | 10.4 (mesopotamian.gilgamesh-tablet-02.001) | brackets, caps_runs |
| mesopotamian/gilgamesh-tablet-11 | 7 | 7.9 | 12.0 (mesopotamian.gilgamesh-tablet-11.001) | brackets, dot_leaders |
| egyptian/egyptian-book-of-the-dead-index | 357 | 5.8 | 20.0 (egyptian.egyptian-book-of-the-dead-index.112) | footnotes, brackets |
| hermeticism/corpus-hermeticum-16 | 1 | 5.7 | 5.7 (hermeticism.corpus-hermeticum-16.001) | brackets |
| hermeticism/corpus-hermeticum-17 | 4 | 5.7 | 9.3 (hermeticism.corpus-hermeticum-17.002) | brackets, caps_runs |
| buddhism/dhammapada-chapter-16 | 1 | 5.4 | 5.4 (buddhism.dhammapada-chapter-16.001) | page_marks, brackets |

194 of 214 texts score below 5 — the damage is concentrated, not corpus-wide.

## Damage families (verified by inspection)

**1. Mandaean footnote-block leak — worst, route to todo:50438e23.**
`gnostic-john-baptizer-1/2/3` (66 chunks, means 14.5–16.0). Inspected
`…-3.021`: the entire body is a translator footnote block ("p. 81 / 1 The
salt, bitter, water of the sea…"), hard-wrapped, with `p. NN` page markers
between entries. These are apparatus chunks masquerading as primary text —
exactly the apparatus-leak class already tracked in **todo:50438e23**
(whole-chunk work: drop/merge, not regex cleanup). The `p. NN` markers and
hard-wrapping in the *legitimate* prose chunks of these texts are a
clean_bodies-style strip.

**2. Gilgamesh brackets — FALSE POSITIVE, no action.**
All 12 `gilgamesh-tablet-*` texts flag on `brackets`/`dot_leaders`. Inspected
`tablet-08.001`: `[shall ye listen]`, `[comrade]`, `(Slung at)` are the
translator's reconstruction markers for broken tablet text — scholarly
apparatus a reader *should* see. The dot leaders are lacuna ellipses. Keep
verbatim; optionally suppress the ALL-CAPS tablet-title lines only. The same
reading applies to bracket-flagged hermeticism (Mead's insertions) and most
lower-scoring bracket hits.

**3. Egyptian Book of the Dead — regex-strippable, biggest surface.**
`egyptian-book-of-the-dead-index` is 357 chunks (7% of the corpus) at mean
5.8. Inspected `.112`: real damage is `{p.\n\nxcli}` page markers broken
across paragraph boundaries, `[1]`/`[2]` footnote refs, and stray unbalanced
`]` — but the numbered ritual-instruction structure is content. Fix: extend
`clean_bodies.py` with a `{p. …}` pattern class (split-across-newlines aware)
+ footnote-ref strip. High value: this one text is most of egyptian's
user-facing surface.

**4. Single-chunk page-mark stragglers.**
`kojiki-beginning-heaven-earth.001`, `yasna-47.001`,
`dhammapada-chapter-16.001` — isolated `p. NN`/footnote remnants the existing
clean_bodies pattern classes nearly cover; verify and extend rather than
hand-edit.

## Recommended order

1. Extend `clean_bodies.py`: `{p. roman}` split-marker class, `p. NN`
   standalone-paragraph class, footnote-ref `[N]` strip (egyptian + stragglers
   + mandaean prose chunks). Re-run this audit to confirm score drops.
2. Resolve the mandaean apparatus chunks under todo:50438e23 (drop/merge).
3. Model-assisted rewrites (staged_cleanups queue, separate ticket) only for
   what survives 1–2 — on this evidence that's the hard-wrap unwrapping in
   mandaean prose, which regex can't safely do.
4. Gilgamesh et al.: no action; brackets are content.
