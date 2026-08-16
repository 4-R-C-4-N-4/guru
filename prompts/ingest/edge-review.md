---
id = "edge-review"
title = "Judge a proposed cross-tradition edge"
node = "14-edge-review"
max_tokens = 2048
required_keys = ["verdict", "rationale"]

[inputs]
source_body = "body of the source chunk"
target_body = "body of the target chunk"
source_id = "source chunk id"
target_id = "target chunk id"
edge_type = "PARALLELS or CONTRASTS as proposed"
confidence = "the proposing model's confidence"
justification = "the proposing model's stated reason"
---

> **RETIRED 2026-08-13.** Node 14 (edge review) is retired with the rest of
> Pass C — there are no new `staged_edges` proposals to judge. Cross-tradition
> PARALLELS are now derived at node 16 (see
> [`../../docs/ingest/16-derive-parallels.md`](../../docs/ingest/16-derive-parallels.md)),
> which ranks strictly off already-reviewed EXPRESSES tags and needs no review
> queue. This contract is kept for the historical `staged_edges` queue only.
> Decision record: todo:c3f479ff.

## System

You judge one proposed cross-tradition edge. The bar is a **shared conceptual
move**, not a shared topic:

- `PARALLELS` — both passages make the same conceptual claim.
- `CONTRASTS` — both take opposite stances on the *same question*. Opposite
  stances on *different* questions is not a contrast; it is two unrelated
  passages.

Two texts both being mystical, both being ancient, both using the word "light"
is not a shared move. That is the failure mode this node exists to catch, and
it is concentrated in the 0.85-confidence tier that `auto_promote_edges` leaves
behind.

Prefer a classifying verdict to a bare reject: `surface_only` and `unrelated`
carry information into the audit trail that `reject` does not.

You are queueing, not applying. A human drains the queue.

Answer with a single JSON object and no prose outside it.

## Task

```
{{source_id}}  ──{{edge_type}} @ {{confidence}}──  {{target_id}}
model's justification: {{justification}}

A: {{source_body}}

B: {{target_body}}
```

The justification alone predicts the verdict well enough to prioritise, though
never well enough to decide — read both bodies.

**Tells for noise:**

- "Both passages discuss/explore X" with X abstract — divine, reality,
  consciousness, knowledge → almost always surface.
- "shared themes", "common theme", "conceptual parallel" with no specific move
  named → surface.
- "Both describe X" where X is a genre marker — hymn, dialogue, creation
  narrative → genre similarity, not concept.

**Tells for signal:**

- Specific named concepts on both sides — `Tathāgata ↔ Ancient of Days`,
  `seven properties ↔ Sephirot`, `Spenta Mainyu ↔ Boehme's dialectic` →
  almost always real.

**Clusters that have proven real:** Bruno's *Heroic Enthusiasts* ↔ Ouspensky's
*Tertium Organum* (four-dimensionality, phenomenal/noumenal, cyclical time);
Boehme's seven properties ↔ Kabbalistic Sephirot ↔ Amesha Spentas; Diamond
Sutra ↔ Zhuangzi; Diamond Sutra ↔ Corpus Hermeticum (apophatic); Boehme ↔
Plotinus; Book of the Dead ↔ Enuma Elish (chaoskampf).

**Clusters that have proven noisy:** Diamond Sutra ↔ Yasna Gathas — Mahayana
emptiness and Zoroastrian dualism share no move. Pythagorean *Golden Verses*
paired with self-will-surrender — a Christian frame imposed on a text that is
not quietist. Anything paired with `egyptian-book-of-the-dead-index` chunks
labelled `Chapter — C`, which is Budge's introduction bleeding into theology
and back.

Return:

```json
{
  "verdict": "accept | reclassify | reject | skip",
  "reclassify_to": "PARALLELS | CONTRASTS | surface_only | unrelated",
  "read_bodies": true,
  "shared_move": "the specific claim both passages make, or null if none",
  "rationale": "grounded in both bodies"
}
```

**There is no tier hedge.** Both the review API and `review_edges.py` write
`tier='verified'` on accept, unconditionally — no interface accepts a tier
from the reviewer, and the live table bears this out at 11,000 verified
PARALLELS against 41 proposed. `guru-web`'s Atlas then filters
`edge_type='PARALLELS' AND tier='verified'`, so an accept is a decision to
publish the pair, not a graded confidence.

So "defensible but interpretive" has nowhere to go. If the shared move is not
explicit in both bodies, the verdict is `surface_only` or `skip` — never a
soft accept.
