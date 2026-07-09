# V8 Boilerplate Audit (todo:9ff92786)

Corpus-wide scan, 2026-07-04, all 4,176 chunk bodies across all 4 source
domains in `sources/manifest.toml`. Method: regex probe battery + leading-prefix
frequency over `corpus/*/*/chunks/*.toml` (scan script preserved in the ticket
trail; rerunnable in ~2s).

**Headline: the "~32% nav pollution" era is over.** Prior cleanup passes
(Plotinus apparatus strip 79e876b, CH re-chunk d18a44c, Zhuangzi rescope
12bd639, `apparatus_remap.py` lineage) removed most of it. Current state:
**~290 chunks (~7%) carry residual boilerplate**, in six pattern classes, all
in-place-strippable. `{p. N}` braced page markers — the `PAGE_MARKER` regex in
guru-web — now match **zero** chunks; that regex is vestigial.

## Per-domain summary

| domain | texts | chunks | residual pollution |
|---|---|---|---|
| sacred-texts.com | 183 | 2,862 | ~180 chunks: trailing `Next:` nav lines, title-page credit sentences, 5 site headers, 2 etext notices, 2 errata blocks |
| gutenberg.org | 6 | 957 | 110 chunks: inline `[Pg N]` markers; 2 trailing license blocks |
| gnosis.org | 7 | 200 | 6 chunks: `Next:` lines, 2 `Index Previous Next` headers (CH-16/17) |
| ccel.org | 15 | 157 | **clean** — no pattern hits |

## Pattern classes → strip strategy

Strips operate at **paragraph** or **sentence/inline** granularity — never
substring surgery mid-paragraph, never chunk drops (id-preserving per parent
ticket fccaf47d).

| # | class | count | example | strip | risk |
|---|---|---|---|---|---|
| P1 | Trailing `Next: <chapter title>` nav paragraph | 167 (163 s-t + 4 gnosis) | `…is world.  Next: Chapter VII.  The Venerable (Arhat).` (dhammapada-chapter-06.003) | drop paragraph matching `^Next:\s.{0,120}$` | low — a body paragraph never opens `Next:`; length cap protects against a legit paragraph. The mandaean John-Book case (`Next:` followed by separate footnote paragraphs) is safe at paragraph granularity — only the nav paragraph drops. |
| P2 | Leading site-header paragraph (`Sacred-Texts <breadcrumb> <title> [year]`, `Index Previous Next …`) | 7 | `Sacred-Texts Ancient Egypt Book of the Dead Index …` (BotD.240); `Index Previous Next Thrice-Greatest Hermes - Volume 2 by G.R.S. Mead p. 266` (CH-16.001) | drop **leading** paragraph matching `^(Sacred-[Tt]exts?\b\|Index\s+Previous\s+Next\b)` — including the hyphenated form the guru-web `NAV_PREFIX` provably misses (the V8 reproducer, enuma-elish 001) | low — anchored to chunk start |
| P3 | Digitization-credit sentences (`scanned at sacred-texts.com…`, `J.B. Hare, redactor`, `Proofed and formatted by…`, `This text is in the public domain…`, `This is a Unicode version of…`) | ~10 | `[1895] scanned at www.sacred-texts.com, Oct-Dec 2000.` (BotD.001) | sentence-level regexes, each `…[^.]{0,120}\.` bounded | low-med — bounded length; dry-run review per hit (small count) |
| P4 | Inline `[Pg N]` page markers | 110 (heroic-enthusiasts pt1/pt2) | `the Pytha [Pg 2] goreans` | replace `\s*\[Pg \d+\]\s*` → single space | low for the strip itself. **Known residual:** ingest split words across page breaks (`Pytha / goreans`), so removal leaves `Pytha goreans`. That damage is pre-existing ingest breakage, out of V8 scope — flagged to 50438e23. |
| P5 | Trailing Gutenberg license block | 2 (kalevala.275, heroic-enthusiasts-pt2.049) | `End of the Project Gutenberg EBook of Kalevala…` | strip from `End of the Project Gutenberg` to EOF | none |
| P6 | Errata paragraph | 2 (enoch-charles-1917.140, tertium-organum.222) | `Errata page 88: 'astonied'->'astonished'` | drop paragraph matching `^Errata\b` | none |

## Explicitly NOT stripped (noted, out of scope)

- **Bare `p. NN` page references** (gnosis.org John-Book, CH): indistinguishable
  from citations at regex level; low embedding harm. Leave.
- **Footnote paragraphs** (John-Book `1 Because Yōhānā is mentioned…`):
  translator's scholarly notes — arguably content. Leave; revisit only if the
  dossier review loop shows `LEAK` failures sourced from them.
- **Split-word artifacts** around removed `[Pg N]` markers: ingest damage, not
  boilerplate — handed to 50438e23.

## Whole-chunk apparatus candidates → handed to 50438e23

Three chunks are ≥30% boilerplate by character count — title pages whose credit
sentences P2/P3 will strip in place, but which remain candidates for the
id-changing treatment under 50438e23 if judged pure apparatus:

- `egyptian.egyptian-book-of-the-dead-index.357` — title page of a *different
  Budge work* ("Egyptian Ideas of the Future Life", London 1900) appended to
  the BotD text — likely a mis-acquired page, worth 50438e23's attention.
- `greek_mystery.pythagorean-golden-verses.001` — anthology title page.
- `jewish_mysticism.enoch-charles-1917.001` — title page + full credit block.

Also for 50438e23: `pythagorean-golden-verses.034` opens with a **Hesiod
Theogony** sacred-texts header — the anthology text includes non-Pythagorean
material; membership worth a look.

## Consequences for the existing regex sets

- guru-web `NAV_PREFIX` (`Sacred Texts … Previous Next`): misses the hyphenated
  and no-nav-link forms — superseded by P2. `PAGE_MARKER` (`{p. N}`): zero
  corpus matches — vestigial, replace with P4's `[Pg N]` form. `APPARATUS_DROP`
  (`^Next:/Previous:/Errata`): only catches whole chunks that *start* with nav —
  P1/P6 handle the embedded cases.
- `scripts/clean_bodies.py` (todo:88a28e67) implements P1–P6 with `--dry-run`
  diffs and a per-chunk overreach guard (refuse if a strip removes >25% of a
  body — the three title-page chunks above are the only expected near-misses
  and are listed for manual confirmation).
