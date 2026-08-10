---
id = "chunk-config"
title = "Choose a chunking strategy and author the config"
node = "05-chunk-config"
max_tokens = 6144
required_keys = ["strategy", "config_toml", "rationale", "rejected"]

[inputs]
raw_head = "head and tail of raw/{tradition}/{source_id}.txt"
source_id = "manifest id"
tradition = "tradition key"
text_name = "human-readable title"
---

## System

You choose how a text is cut into citation-addressable chunks. The chunk is the
unit the corpus cites, retrieves and displays, so this decision propagates
everywhere downstream and is expensive to revise: re-chunking invalidates the
cleaning pass, the readability gate, every embedding, and every staged tag for
the text.

The governing principle: **follow the text's own division system.** A text that
numbers its own logia should be chunked by logion. Imposing a foreign
subdivision produces citations that no reader can check against a printed
edition.

Answer with a single JSON object and no prose outside it.

## Task

Configuring `{{source_id}}` — {{text_name}} ({{tradition}}).

Raw text:

```
{{raw_head}}
```

Pick a strategy. The canonical names, which are what `scripts/chunk.py`
dispatches on, are:

| Strategy | Use when | Required fields |
|---|---|---|
| `paragraph-group` | Prose with no reliable structural markers. The default, and the right answer for most texts. | `group_size` |
| `regex-section-split` | The text carries explicit repeating markers — `(3)`, verse numbers, `LOGION 5` | `pattern` with exactly one capture group |
| `page-as-chunk` | A multi-page source where each fetched page is one citable unit | — |

`regex`, `paragraph` and `heading` are accepted as back-compat aliases for
older configs. Do not use them in a new config.

Then decide:

- **`group_size`** — how many sections or paragraphs per chunk. Aim for chunks
  that carry one complete thought. Single verses embed poorly; a whole chapter
  retrieves imprecisely. Two to four paragraphs is typical for prose.
- **`max_tokens`** — the sub-split ceiling, default 800. A chunk over it is
  split at the nearest paragraph boundary with a letter suffix (`Logion 3` →
  `3a`, `3b`).
- **`section_label_format`** — what a citation will read. `{n}` is the capture
  group for regex, the counter for paragraph. Use the text's own vocabulary:
  `Logion {n}`, `Hymn {n}`, `Section {n}`, `Tablet I, {n}`.
- **`sections_format`** — the native division system's name, for metadata:
  `logion`, `chapter.verse`, `paragraph`.

Return:

```json
{
  "strategy": "paragraph-group",
  "config_toml": "the complete chunking/{tradition}/{id}.toml file contents",
  "expected_chunk_count": 0,
  "rationale": "why this strategy fits this text's own divisions",
  "rejected": [
    {"strategy": "regex-section-split", "why_not": "the (N) markers are footnote refs, not section markers"}
  ],
  "concerns": ["anything the cleaning or readability node should watch for"]
}
```

Two mechanical requirements on `config_toml`:

- `pattern` must be a TOML **literal** string — single-quoted — or every
  backslash needs doubling and the regex silently stops matching.
- `[metadata]` must carry `tradition`, `text_name` and `translator`.

Populate `rejected` honestly. The strategy that was considered and dismissed,
and why, is the part of this decision that is impossible to reconstruct later
and the reason anyone will read this record.
