# Chunking Config Schema

Every text in the corpus has a corresponding `chunking/{tradition}/{text_id}.toml`
that governs how `scripts/chunk.py` segments it.

## Full schema

```toml
[chunking]
# Required. One of: "regex", "heading", "paragraph"
strategy = "regex"

# Required for strategy = "regex"
# Regex with one capture group that becomes the raw section ID.
# Applied against the full raw text (re.MULTILINE).
pattern = '\\((\\d+)\\)\\s+'

# Required for strategy = "heading"
# Regex matching a heading line. The full matched line becomes section_label
# unless section_label_format overrides it.
heading_pattern = '^\\d+\\.\\s+'

# Optional. Python format string applied to the capture group or heading text.
# For regex: {n} = capture group value (stripped)
# For heading: {heading} = full matched line (stripped)
# For paragraph: {n} = 1-based sequential counter
# Default: "{n}"
section_label_format = "Logion {n}"

# Optional. Max tokens per chunk before sub-splitting.
# Default: 800
max_tokens = 800

# Optional. Number of consecutive sections to bundle into one chunk.
# Default: 1
group_size = 1

[metadata]
# Required.
tradition = "gnosticism"
text_name = "Gospel of Thomas"
translator = "Thomas O. Lambdin"

# Optional. Describes the native division system used in citations.
# e.g. "logion", "chapter.verse", "tractate.section", "paragraph"
sections_format = "logion"
```

## Strategy reference

| Strategy | Use when | Key config fields |
|---|---|---|
| `regex` | Text has explicit section markers like `(N)`, verse numbers | `pattern`, `section_label_format`, `group_size` |
| `heading` | Text has titled or numbered heading lines | `heading_pattern`, `section_label_format` |
| `paragraph` | Prose with no structural markers | `group_size` (how many paragraphs per chunk) |

## Sub-splitting

When a chunk exceeds `max_tokens`, the orchestrator splits it at the nearest
paragraph boundary and appends a letter suffix to the section label:
- `Logion 3` → `Logion 3a`, `Logion 3b`

## Example configs

### Sayings gospel (Gospel of Thomas)
```toml
[chunking]
strategy = "regex"
pattern = '\\((\\d+)\\)\\s+'
section_label_format = "Logion {n}"
max_tokens = 800
group_size = 1

[metadata]
tradition = "gnosticism"
text_name = "Gospel of Thomas"
translator = "Thomas O. Lambdin"
sections_format = "logion"
```

### Mystical prose (Sefer Yetzirah)
```toml
[chunking]
strategy = "paragraph"
section_label_format = "Section {n}"
max_tokens = 800
group_size = 3

[metadata]
tradition = "jewish_mysticism"
text_name = "Sefer Yetzirah"
translator = "Sefaria Community Translation"
sections_format = "paragraph"
```

### Tractate text (Corpus Hermeticum)
```toml
[chunking]
strategy = "heading"
heading_pattern = '^\\[Chapter \\d+\\]'
section_label_format = "{heading}"
max_tokens = 800
group_size = 1

[metadata]
tradition = "hermeticism"
text_name = "Corpus Hermeticum I"
translator = "G.R.S. Mead"
sections_format = "chapter"
```
