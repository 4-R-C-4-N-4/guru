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

## Output

`sources/manifest.toml`, one new `[[source]]` block.

## Gate

```sh
python3 scripts/acquire.py --dry-run --only <source-id>
```

Resolves the entry and picks a downloader without fetching.

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

## Provenance

Comment conventions from the existing manifest, in particular the
`pistis-sophia` and Upanishad entries.
