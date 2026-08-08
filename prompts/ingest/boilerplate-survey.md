---
id = "boilerplate-survey"
title = "Identify non-source cruft in a raw text and plan the strip"
node = "04-boilerplate-survey"
max_tokens = 4096
required_keys = ["classes", "rationale"]

[inputs]
raw_head = "head and tail of raw/{tradition}/{source_id}.txt"
source_id = "manifest id"
host = "source host, e.g. sacred-texts.com"
---

## System

You separate source text from the archive's packaging: site navigation,
digitisation credits, page markers, licence blocks, errata.

Two hard constraints on anything you propose.

**Granularity is paragraph or sentence, never substring.** Mid-paragraph
surgery on a regex match has no way to know it has hit a quotation rather than
a header.

**Nothing may drop a chunk.** Chunk ids are citations that have already been
issued; the corpus keeps apparatus chunks deliberately and leaves them
untagged rather than deleting them.

When a passage could plausibly be either the archive's or the author's, leave
it. A retained page marker costs a little embedding noise. A stripped line of
scripture is a corpus error that surfaces as a fabricated citation.

Answer with a single JSON object and no prose outside it.

## Task

Surveying `{{source_id}}` from {{host}}.

```
{{raw_head}}
```

The classes below are the ones this corpus has actually encountered, with the
strip that was settled on for each. Match against them first, and only propose
a new class for something genuinely unlike them.

| Class | Shape | Strip |
|---|---|---|
| P1 | Trailing `Next: <chapter title>` nav paragraph | drop paragraph matching `^Next:\s.{0,120}$` |
| P2 | Leading site header — `Sacred-Texts <breadcrumb> <title>`, `Index Previous Next …` | drop **leading** paragraph matching `^(Sacred-[Tt]exts?\b\|Index\s+Previous\s+Next\b)` |
| P3 | Digitisation credits — `scanned at sacred-texts.com`, `J.B. Hare, redactor`, `Proofed and formatted by` | sentence-level, each bounded `…[^.]{0,120}\.` |
| P4 | Inline `[Pg N]` page markers | replace `\s*\[Pg \d+\]\s*` with a single space |
| P5 | Trailing Gutenberg licence block | strip from `End of the Project Gutenberg` to EOF |
| P6 | Errata paragraph | drop paragraph matching `^Errata\b` |

Deliberately **not** stripped, and not to be re-proposed: bare `p. NN`
references, which are indistinguishable from citations at regex level; and
translator's footnote paragraphs, which are arguably content.

Return:

```json
{
  "classes": [
    {
      "class": "P1",
      "occurrences": 3,
      "example": "the exact matched text",
      "strip": "the rule from the table, or a proposed new one",
      "granularity": "paragraph | sentence | inline",
      "risk": "low | medium | high",
      "risk_note": "what a false positive would destroy"
    }
  ],
  "new_classes": [],
  "leave_alone": ["things that look like boilerplate but are content"],
  "rationale": "two or three sentences"
}
```

Anything at `high` risk should be left for a human rather than proposed as an
automatic strip. Note P4's known residual: this source's ingest split words
across page breaks, so removing the marker leaves `Pytha goreans`. That is
pre-existing ingest damage, not something the strip introduces — flag it, do
not try to repair it here.
