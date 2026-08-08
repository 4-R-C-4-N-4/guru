# 08 — readability-gate

**Kind:** judgement · **Contract:** [`prompts/ingest/readability-gate.md`](../../prompts/ingest/readability-gate.md) · **Goes stale on re-chunk**

Score the cleaned bodies and decide whether what the scanner flagged is
scholarly apparatus or ingest breakage.

## Precondition

Node 07 done and not stale.

## Action

```sh
python3 scripts/audit_readability.py --text <source-id> --format markdown
python3 scripts/audit_readability.py --text <source-id> --worst 3
```

Then judge the output against the contract, and record the verdict.

## Output

A `pass` / `fix` / `escalate` verdict with per-signal readings.

## Gate

A recorded verdict. `pass` advances; `fix` sends you back to node 05 or 07;
`escalate` sends you back to node 03.

## Failure modes

**Treating the score as the verdict.** It is a prompt to look. Bodies are
served verbatim to the public reader at guru-ai.org/read, so formatting damage
is user-facing — but so is deleting a fragmentary original's lacunae.

**Confusing apparatus with damage.** From the 2026-07-23 audit: the Gilgamesh
tablets score 8–14 on `brackets` and `dot_leaders` and are clean — that is what
a fragmentary cuneiform transcription looks like. The Mandaean
John-the-Baptizer texts score 14–16 on `page_marks` and `hard_wrap` and are
genuinely damaged. The scores barely separate. The bodies do.

**Fixing here what belongs upstream.** Words split across page breaks are
acquisition damage (node 03). Wrong section boundaries are a config problem
(node 05). Neither is repairable at this node, and attempting it produces
corpus state that no config reproduces.

## Provenance

`scripts/audit_readability.py`; calibration figures from
`docs/summary/readability-audit.md` (2026-07-23, 4,923 chunks across 214
texts).
