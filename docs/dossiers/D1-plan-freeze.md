# D1 — plan-freeze

**Kind:** command · **Contract (when bumping):** [`prompts/dossier/contracts/campaign-bump.md`](../../prompts/dossier/contracts/campaign-bump.md)

Compute every work's span layout deterministically from the chunk TOMLs and
the campaign config, and freeze it.

## Precondition

Every member text of every work through **ingest node 07** — chunked and
cleaned. This is the only coupling between the two streams, and it is not
optional: a summary generated over uncleaned bodies summarises the site
navigation and the digitisation credits along with the text.

## Action

```sh
python3 scripts/build_dossiers.py --plan
```

Writes both halves of the freeze artifact:

- `docs/summary/span-plan-{campaign_id}.json` — machine
- `docs/summary/span-plan-{campaign_id}.md` — human

If the corpus has changed since the current plan froze, this is a **new
campaign**, not a re-plan. Bump `campaign_id` in `config/dossiers.toml` first,
with a comment saying what changed — the existing comments in that file are the
model, and they are the only record of why `c1`…`c7` exist.

## Output

The frozen plan for the current campaign, containing every work's spans with
their chunk ids.

## Gate

```sh
python3 -m guru dossier status <work-id>
python3 -m guru dossier drift
```

`drift` is the real gate. A plan that leaves live dossiers unaccounted for is
not a freeze.

## Failure modes

**Re-planning in place.** Rule V9, and the reason this node exists as its own
step. Once generation has begun, the plan is the coordinate system every staged
row's provenance refers to. Regenerating it with different totals silently
redefines what existing rows were summarising. Bump the campaign instead — it
is cheap, and prior works' span ids stay identical so their staged rows carry
forward unchanged.

**Trusting the carry-forward promise across a labeler change.** "Prior works'
span ids stay identical" holds only while `slugify(label)` is stable — and the
slug comes from the span *label*, so a change to how the planner names spans
(e.g. the suffix-format change in `8d0b00cf`, `VIIIao` → `VIII (ao)`) renames
the span ids of every letter-suffixed span at the next re-plan. The c7 freeze
did exactly this to ~180 spans across a dozen works. Nothing breaks loudly:
the D2/D3 gates count rows rather than match ids, so works still pass — but
`--respin` cannot find old-id rejected rows in the new plan ("not in plan"),
and plan-to-DB reconciliation by span id silently reports every renamed span
as missing. Re-promotion heals the live tables (D4 rebuilds a work's nodes
wholesale from its staged rows), but staged-row provenance keeps the old ids
forever. If a label-format change is unavoidable, expect this and check
whether any not-yet-promoted work has fully-rejected rows under old ids —
those spans have silently left `--respin`'s reach.

**Assuming a provider switch invalidates spans.** It does not. `span_target` is
in pipeline tokens and is provider-independent by design, precisely so span
identity survives a backend change. A provider switch is still a new campaign,
but for provenance reasons — the `model` column disambiguates the lines.

**Confusing an orphan for a freeze violation.** `drift` separates them and the
distinction is load-bearing; see the workbook README. A live dossier for a work
whose texts are not in `corpus/` is almost certainly work done on another
branch, because `data/guru.db` is git-ignored and shared while `corpus/` is
tracked. Reconciling it into a new campaign would be wrong, and deleting it
would be worse.

**Planning on top of drift you cannot account for.** If the report shows a
freeze already violated by work you did not do, find out what produced it
first. A bump that folds in rows nobody understands just launders the problem
into the new campaign.

## Provenance

`scripts/build_dossiers.py` (G4 plan mode); rule V9 and the span rules from
`docs/summary/document-knowledge-data-structures.md` §1.3.5; the campaign
history from the comments in `config/dossiers.toml`.
