# 02 — manifest-entry

**Kind:** command

Register the vetted source in `sources/manifest.toml`.

## Precondition

Node 01 done with a `verified` verdict.

## Action

Add a `[[source]]` block:

```toml
[[source]]
id = "<source-id>"
tradition = "<tradition>"
label = "<Title (Translator translation)>"
url = "<verified url>"
format = "html"          # or "text"
license = "public_domain"
translator = "<name>"
notes = "<what the acquisition layer needs — which div, what to strip>"
```

Carry the vetting evidence into a comment above the block: what was checked,
when, what the heading chain said, what was rejected. The `pistis-sophia` entry
is the model — it records the verification date, the byte count, the confirmed
title tag, the structure of the primary text, and why the alternative source
was passed over.

## Classify the work kind — primary vs synthesis (todo:9445cd73)

Every work is `primary` (a root text) or `synthesis` (a modern cross-tradition
survey, compilation, or secondary exposition). Default is `primary`; a **synthesis**
work MUST be added to the `synthesis` list in `sources/works.toml` (by work_id — for
a singleton that is the source id, for a grouped work its work id). This drives
guru-web's retrieval **primary floor** (`docs/retrieval-golden-gap-investigation.md`
§8.1a): a synthesis work is never allowed to crowd a *relevant primary* out of the
top-15 — its redundant slot is yielded instead, with no score change.

Decide from the source itself: a scripture, dialogue, poem, or a treatise by the
tradition's own figure is **primary**; an author's synthesis across traditions, an
encyclopedic survey, or a secondary exposition of another figure is **synthesis**
(e.g. blavatsky-sd, secret-teachings-of-all-ages, kybalion, life-and-doctrines-boehme).
Early-modern root texts (Agrippa, Paracelsus, Bruno) are **primary**, not synthesis.
The generated dossier is the later cross-check — its `summary`/`context` names the
form ("synthesis", "encyclopedic survey" vs "revelation discourse", "treatise").

## Output

`sources/manifest.toml`, one new `[[source]]` block; and, **for a synthesis work
only**, its work_id appended to `synthesis` in `sources/works.toml`.

## Gate

```sh
python3 scripts/acquire.py --dry-run --only <source-id> && python3 scripts/works.py
```

This is exactly the gate `python3 -m guru ingest status <id>` runs for this node.
The first command resolves the manifest entry and picks a downloader without
fetching; `python3 scripts/works.py` materializes the works layer and **fails if
the kind classification is malformed** — a mistyped or unknown `synthesis` id
raises rather than silently defaulting the work to `primary`. (It is CWD-robust —
paths resolve from the script, so it runs from any directory.)

## Failure modes

**`id` collisions across traditions.** Ids are the citation namespace and must
be globally unique, not unique per tradition.

**A multi-page work entered as one block.** If node 01 found multi-page
pagination, this is where it gets handled — either one entry per page, as the
Mandaean John-Book does, or multi-page support added to the host's downloader.
Choosing neither means ingesting a fragment.

**No downloader for the host.** Acquisition falls back to
`scripts/downloaders/generic_html.py`, which is often fine and occasionally
produces unusable output. If the host is new, check the dry run names a
downloader you expect.

**A synthesis work left unclassified.** A new modern survey/compilation not added
to `works.toml` `synthesis` defaults to `primary`, so the primary floor treats it as
a root text and it silently crowds real primaries out of top-15 again — the exact
regression the floor exists to prevent. The whole corpus was classified 2026-09-02;
new works are the only gap, which is why this gate lives here.

## Provenance

Comment conventions from the existing manifest, in particular the
`pistis-sophia` and Upanishad entries.
