# The per-text ticket

How each text's journey is recorded — and signed — as it crosses the pipeline,
when more than one driver is working the corpus at once.

A per-text ticket is **documentation first**: a durable, git-tracked record of
what was decided and done to a text, with each driver signing its own work. It
is not a task board, and it is not the coordination channel — the drivers
coordinate the actual handoff by messaging each other directly. What the ticket
gives you is the part that outlives the conversation: months later, the ticket
and the decision doc it links are why anyone can reconstruct how this text came
to be in the corpus.

It is deliberately separate from **`guru ingest status <id>`**, which is
*physical* truth — which node is done, probed from disk and `guru.db`. `status`
says where the text physically is; the ticket says who did what, and why. A solo
driver at a terminal can ignore this file; it earns its place once two agents
share the corpus.

## Branch mode is `managed` — and must stay that way

`.todo/config.json` sets `behavior.branch_mode: "managed"`. In this mode `todo`
performs **no git operations**: `todo work` only marks a ticket active, and
`close` records state without a branch guard. Branching is left entirely to the
PR flow this repo already requires (`main` is protected; branch, `gh pr create`,
reset local `main` to `origin/main`).

This is the load-bearing choice for a multi-agent team. The default
`per-ticket` mode would have `todo work <id>` cut a `todo/<id>` branch per
ticket — on top of the PR feature-branches — and two agents turn that into
branch soup fast. Managed mode makes the ticket count and the branch count
independent: the ticket is a record that travels with the work, and branches
stay whatever the PR flow makes them — the two never have to line up.

## The shape: one text, a parent and two children

Each source-id gets one ticket tree, so nothing is lost between the two
territories:

```
Parent   feature        "Ingest <source-id>"            spans both territories
  ├─ A   investigation  "Vet + acquire <source-id>"     the Explorer's, nodes 01–03
  └─ B   feature        "Process <source-id> → PR"       the Driver's, nodes 04–16 + Pass D
```

- **Child A belongs to the Explorer.** `investigation` is the right type: its
  done-contract closes on a **note**, and that note is the vetting verdict. Its
  `todo analyze` entries (blame → hypothesis → evidence → conclusion) carry the
  vetting rationale — the same reasoning written to
  [`decisions/<source-id>.md`](decisions/), linked from the ticket rather than
  duplicated. A closes when the raw is down (node 03 `[x]`).
- **Child B belongs to the Driver.** Its done-contract is a commit and a
  test-or-note — satisfied by the merged PR. Create it `blocked` if you want the
  dependency on A recorded on the ticket: the drivers don't need that state to
  coordinate — they message each other — but it documents that processing
  follows acquisition. It closes when the text ships.

## Sign your work; coordinate over chat

The ticket's first job is authorship. Each driver signs its transitions with
`TODO_ACTOR` — `explorer` on Child A, `driver` on Child B — so the parent's
history reads plainly as "the Explorer vetted and acquired this, the Driver
processed and shipped it," and stays legible long after both sessions are gone.
Sign every write; if the environment doesn't carry `TODO_ACTOR`, prefix it
inline: `TODO_ACTOR=explorer todo close ...`.

The **handoff itself is a message between the two bots**, not a ticket poll —
the Explorer tells the Driver a text is acquired and names the ticket. The
ticket records that it happened; it is the receipt, not the messenger. The
territory split still holds and is what keeps the record clean: the Explorer's
work ends at raw + manifest — it never opens Child B or writes `corpus/` /
`guru.db`; the Driver reads Child A's note but does not edit it.

## Keeping the store honest

Because state lives in git and is edited by agents, run **`todo doctor`** in CI.
It reconciles `.todo/` against git reality and catches exactly the multi-agent
drift this convention is exposed to: a Driver whose PR branch was deleted
mid-flight, a parent closed while its Explorer child is still open, a resolution
commit orphaned by a squash-merge. It exits non-zero, so it gates.

## Provenance

`todo` (github: 4-R-C-4-N-4/todo) `README.md` / `BIBLE.md` — branch modes, the
done contract, the parent/child model, and the rationale trail (`analyze`) that
makes a ticket a lightweight ADR. Framing the per-text ticket as a signed record
rather than a task board — with coordination left to direct messaging between
drivers — is this repo's application of them, chosen so the Explorer/Driver split
leaves an audit trail a physical `guru ingest status` probe cannot.
