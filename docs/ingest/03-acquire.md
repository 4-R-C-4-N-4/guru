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

**Words split across page breaks.** Some sources hyphenate or break words at
page boundaries, and the break survives extraction: `Pytha [Pg 2] goreans`.
Removing the marker later leaves `Pytha goreans`. This is ingest damage, and
the only place it can be fixed properly is here — noticing it at node 08 means
re-acquiring.

**Gzip and encoding surprises.** The Kalevala fetch had a gzip caveat recorded
during vetting. Trust the vetting notes over the default path.

## Provenance

Downloader registry from `scripts/downloaders/`; the page-break and gzip cases
from `docs/summary/boilerplate-audit.md` (P4) and
`docs/corpus-expansion/url-vetting.md`.
