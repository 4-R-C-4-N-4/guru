---
id = "campaign-bump"
title = "Decide whether a corpus change forces a new campaign"
node = "D1-plan-freeze"
max_tokens = 3072
required_keys = ["verdict", "rationale"]

[inputs]
change = "what changed — texts added or removed, a re-chunk, a provider or model switch, a span_target change"
current_campaign = "the campaign block from config/dossiers.toml"
drift = "output of `python3 -m guru dossier drift`"
---

## System

You decide whether a change to the corpus or the configuration requires a new
dossier campaign.

The span plan is a **freeze artifact**, not a cache. Once generation has begun
against it, the plan is the shared coordinate system that every staged row's
provenance refers to. Regenerating it in place with different totals silently
redefines what existing rows were summarising — that is rule V9, and it is the
one thing this decision exists to prevent.

A new campaign is cheap. Bump `campaign_id`, re-run `--plan`, and prior staged
rows keep satisfying the generate loop's skip and upstream checks **provided
the span identities they refer to are unchanged**. That proviso is the whole
question.

Span identity is provider-independent by design: `span_target` is expressed in
pipeline tokens and does not move when the backend does. So a provider switch
changes provenance but not span ids; a re-chunk changes span ids and therefore
invalidates everything downstream of them.

Answer with a single JSON object and no prose outside it.

## Task

```
change:
{{change}}

current campaign config:
{{current_campaign}}

current drift:
{{drift}}
```

Work through it in this order.

**1. Does the change alter any existing work's spans?** Adding a new text
leaves every prior work's span ids identical — that is why `c1`→`c5` each
carried their predecessors' staged rows forward unchanged. Re-chunking an
existing text does not: its span ids move, and every L1, structure entry, L2
and dossier field derived from them is stale.

**2. Does it alter the generation provenance?** A provider or model change is
a new campaign even when span ids are untouched, because the `model` column is
what disambiguates provenance lines. Prior rows stay valid and simply belong to
the earlier line.

**3. Does `input_budget` cross zero?** Going from `claude-code`
(`input_budget = 0`) to `local` activates folds and the figures/terms
map–reduce for oversized works. Those are internal scaffolding, never promoted
and never exported, but they change what the generate loop does.

**4. What does the drift report say?** `off_plan` entries are a freeze already
broken and must be reconciled by the bump. `orphaned` entries are not a freeze
problem at all — `data/guru.db` is git-ignored and shared across branches while
`corpus/` is tracked, so those rows belong to a checkout you are not on. Do not
let orphans drive a campaign bump, and do not delete them.

Return:

```json
{
  "verdict": "bump | continue | reconcile-first",
  "next_campaign_id": "c6",
  "spans_change": false,
  "provenance_change": false,
  "invalidated": ["work ids whose staged rows do not carry forward"],
  "reconcile": ["off-plan works this bump must fold in"],
  "ignore_orphans": ["orphaned work ids, and the branch they likely belong to"],
  "rationale": "two or three sentences"
}
```

`reconcile-first` is for the case where the drift report shows a freeze already
violated by work you cannot account for. Find out what produced it before
planning on top of it — a bump that folds in rows nobody understands just
launders the problem into the new campaign.
