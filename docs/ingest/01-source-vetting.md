# 01 — source-vetting

**Kind:** judgement · **Contract:** [`prompts/ingest/source-vetting.md`](../../prompts/ingest/source-vetting.md)

Confirm the URL holds the translation it claims to hold, under a licence that
permits use, in a shape the acquisition layer can actually fetch whole.

## Precondition

A candidate URL. Nothing else — this is the entry node.

## Action

Fetch the page. A bare `curl` gets **403 from sacred-texts.com** — it filters on
User-Agent — so send one. The repo's own downloaders do the same
(`scripts/downloaders/sacred_texts.py` sets a Chrome UA); a 403 here is almost
never a dead source.

```sh
curl -sSL --max-time 30 -A "Mozilla/5.0 (X11; Linux x86_64)" <url> -o /tmp/page.html
```

Read the heading chain before anything else — `<title>`, then `<h1>`–`<h4>`, then
the internal links. On sacred-texts the schema.org `author` block is often the
fastest way to see who actually translated it.

Then run the contract:

```sh
python3 scripts/run_contract.py source-vetting \
    --input page_head=/tmp/page.html \
    --var source_id=<id> --var tradition=<t> --var url=<url>
```

Or read the contract and answer it directly. Same inputs, same JSON.

Write the reasoning to `docs/ingest/decisions/<source-id>.md`, then:

```sh
python3 -m guru ingest done <source-id> 01-source-vetting --by <who> --note "<one line>"
```

## Output

A verdict, and the four facts node 02 needs: verified URL, format, licence,
and single- versus multi-page.

## Gate

`verdict == "verified"`. Anything else stops here — an unverified source that
proceeds becomes a citation the corpus cannot support.

## Failure modes

**The URL returns 200 and contains the wrong text.** This is the normal case,
not the exotic one. In the 2026-05-31 Upanishad batch, 9 of 11 URLs were wrong:
most pointed at a different Upanishad or at Müller's introduction essay rather
than the translation. Every one of them fetched successfully.

**Scholarly introductions look like source text.** Multi-volume series bunch
per-work introduction essays at the front of the file numbering, so the
lowest-numbered file for a work is frequently apparatus. Read the heading
chain, not the filename.

**Multi-page works enter as single-page entries.** 8 of the 11 Upanishads span
multiple files. A `format = "html"` entry against the first one ingests chapter
one and reports success. There is no error to catch downstream — the corpus
just quietly contains a fragment.

**The text may not exist in the expected source at all.** Mandukya-Upanishad is
in neither SBE volume; Müller never translated it. Absence is a valid finding.

## Provenance

Rubric and failure modes from `docs/corpus-expansion/url-vetting.md`
(2026-05-31, index-driven cross-check of 18 candidate URLs).
