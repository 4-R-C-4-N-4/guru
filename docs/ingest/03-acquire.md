# 03 — acquire

**Kind:** command

Download the raw text.

## Precondition

A resolvable `[[source]]` block (node 02).

## Action

```sh
python3 scripts/acquire.py --only <source-id>
```

The downloader is selected by URL host — see `scripts/downloaders/`. Hosts with
dedicated handling: `sacred_texts.py`, `gnosis_org.py`, `access_to_insight.py`,
`sefaria.py`. Everything else falls through to `generic_html.py`.

## Output

Single-page sources (`format = "html"` / `"text"`):

- `raw/{tradition}/{source-id}.txt`
- `raw/{tradition}/{source-id}.meta.toml`

Multi-page sources (`format = "html_multi"`, 12 entries today) instead land one
file per page:

- `raw/{tradition}/{source-id}-01.txt`, `-02.txt`, …

`_find_multi_raw_files` in `scripts/chunk.py` is what consumes them, and it is
the source of truth for the naming. All git-ignored and reproducible from the
manifest.

## Gate

```sh
python3 -m guru ingest status <source-id>
```

Node 03 flips to `[x]` when a non-empty raw artifact exists — either the
single-page file or at least one `-NN.txt` page.

## Failure modes

**A plausible file size is not proof of a complete fetch.** A multi-page work
fetched as single-page produces a perfectly well-formed file containing one
chapter. Compare against what node 01 recorded about pagination.

**Do not conclude text is missing from a `grep` that used another
translation's wording.** Negative evidence about a body of text is only as
good as the phrase searched for. On yoga-sutras, grepping the raw for
"impermanent" and "pairs of opposites" — Prabhavananda's phrasing — returned
nothing and was briefly taken as proof that two sutras were absent. Johnston
renders the same lines "unenduring, impure, full of pain, not the Soul" and
"the strength to resist the shocks of infatuation or sorrow". The sutras were
present throughout.

Search for the *number* and read the surrounding text, or diff unit counts
(node 05). Never conclude absence from a phrase you have not confirmed the
translator uses.

**Words split across page breaks.** Some sources hyphenate or break words at
page boundaries, and the break survives extraction: `Pytha [Pg 2] goreans`.
Removing the marker later leaves `Pytha goreans`. This is ingest damage, and
the only place it can be fixed properly is here — noticing it at node 08 means
re-acquiring.

**Gzip and encoding surprises.** The Kalevala fetch had a gzip caveat recorded
during vetting. Trust the vetting notes over the default path.

**A sacred-texts index page can leak an adjacent title's pages into this
one's raw files.** `fetch_index` in `scripts/downloaders/sacred_texts.py`
scraped every `.htm`/`.html` link on the index page and excluded only ones
with `"index"` literally in the href — which misses two real shapes of
site-wide navigation: a header breadcrumb shortcut (e.g. a "Tarot Reading"
link to a *different* work's title page) and a footer Previous/Next-title
block whose target isn't named `index.htm` (e.g. `pageidx.htm`). Both slipped
through on the 2026-08-17 western_esoteric batch — `kybalion` picked up one
page of Rudolf Steiner's *Knowledge of the Higher Worlds* via the footer nav,
`tarot-of-the-bohemians` picked up Waite's *Pictorial Key to the Tarot* title
page via the header breadcrumb — one stray page each, both from a completely
different work, both silently present in the raw output with no error. Fixed
by scoping `fetch_index` to links whose resolved path shares the index page's
own directory, which every genuine chapter/section link does and neither
false positive did. **The check this buys you:** after any multi-page
sacred-texts acquisition, diff the `source_url` host+path prefix across all
`-NN.meta.toml` files against the index URL's own prefix — a mismatch is
contamination, not a legitimate extra page. `tertium-organum-31.txt`
(`eso/to/pageidx.htm`) looks similar at a glance but is *not* an instance of
this — it is that work's own back-index page, same directory as its `index.htm`,
correctly retained.

## Provenance

Downloader registry from `scripts/downloaders/`; the page-break and gzip cases
from `docs/summary/boilerplate-audit.md` (P4) and
`docs/corpus-expansion/url-vetting.md`.
