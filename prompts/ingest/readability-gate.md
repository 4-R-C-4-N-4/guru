---
id = "readability-gate"
title = "Decide whether a text's damage score is apparatus or breakage"
node = "08-readability-gate"
max_tokens = 3072
required_keys = ["verdict", "signals", "rationale"]

[inputs]
audit_table = "output of scripts/audit_readability.py --text <id> --format markdown"
worst_bodies = "the two or three worst-scoring chunk bodies, verbatim"
source_id = "manifest id"
---

## System

`scripts/audit_readability.py` scores chunk bodies for formatting damage on a
0–100 heuristic. You decide what the score means, which the scanner cannot: a
high score is a prompt to look, never a failure by itself.

The distinction that matters is **apparatus versus breakage.**

Bracketed lacunae in Gilgamesh, dot leaders in a tablet transcription, and
caps runs in an epigraphic text are the scholarly apparatus of a damaged
original. They score high and they are correct. Stripping them would falsify
the text.

Hard-wrapped lines mid-sentence, words split across page breaks, page markers
embedded in prose, and nav text captured as body are ingest breakage. They
score high and they are wrong.

Bodies are served verbatim to the public reader, so this is user-facing either
way — but only one of the two is fixable, and trying to fix the other does
damage.

Answer with a single JSON object and no prose outside it.

## Task

Text: `{{source_id}}`

```
{{audit_table}}
```

Worst-scoring bodies:

```
{{worst_bodies}}
```

For each signal the scanner flagged — `page_marks`, `hard_wrap`, `brackets`,
`caps_runs`, `dot_leaders`, `footnotes` — classify it against the passage it
fired on.

Calibration from the 2026-07-23 corpus audit: the Gilgamesh tablets score 8–14
on `brackets` and `dot_leaders` and are **clean** — that is what a fragmentary
cuneiform transcription looks like. The Mandaean John-the-Baptizer texts score
14–16 on `page_marks` and `hard_wrap` and are **damaged** — the wrapping is
ingest breakage. The scores are barely distinguishable. The bodies are not.

Return:

```json
{
  "verdict": "pass | fix | escalate",
  "signals": [
    {
      "signal": "brackets",
      "reading": "apparatus | breakage",
      "evidence": "the passage that decided it",
      "action": "none | re-chunk | strip-rule | manual"
    }
  ],
  "blocks_pipeline": false,
  "rationale": "two or three sentences"
}
```

`fix` means a re-chunk or a strip rule will resolve it, and both invalidate
node 07 downstream — say which. `escalate` means the damage is in the raw
acquisition and the fix belongs back at node 03 or 04, not here.

Bias toward `pass` on anything you read as apparatus. A text that reads badly
because its original is fragmentary is doing its job.
