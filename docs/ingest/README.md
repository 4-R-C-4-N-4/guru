# The ingest workbook

How a text gets from a URL to a queryable, citable part of the corpus.

> This is one of two streams. The second,
> [`docs/dossiers/`](../dossiers/README.md), takes clean chunks to the
> document-knowledge layer — dossiers and summaries. It operates on **works**
> rather than texts, which is why it is a separate graph with its own CLI. The
> two meet at one point: Pass D's first node requires every member text through
> node 07 here.

This workbook exists because most of that process used to live in two places
that neither travel nor outlast a session: a person's head, and an agent
conversation. Fifteen nodes, each one a file in this directory, each one
readable by a person, an agent, or a script.

## The driver loop

Nothing here assumes a particular agent runtime. Any driver — a human at a
terminal, Claude Code, another harness, a cron job — runs the same three steps
until the pipeline is satisfied:

```
python3 -m guru ingest status <source-id>   # which node, what blocks it, what runs next
<do exactly the one thing it named>
python3 -m guru ingest status <source-id>   # the gate re-checks; the node advances or it doesn't
```

`status` reads the filesystem and `guru.db` directly, so it tells you the truth
about the corpus rather than the truth about what someone remembers doing.
`--json` gives the same answer machine-readably, which is what a harness adapter
should consume.

The graph itself lives in `guru/ingest.py` as data. The node files here are its
prose half; they are kept one-to-one by key, and the CLI prints the path to the
file for whichever node is next.

## Node kinds

| Kind | Meaning | May a driver do it unattended? |
|---|---|---|
| `command` | A deterministic script with a checkable output artifact | Yes |
| `judgement` | LLM-in-the-flow: a call that needs reading and deciding | Yes, against the node's contract |
| `gate` | Proposals are queued for human review | It may **queue** decisions; it may never apply them |
| `user` | Belongs to the user | No — stop and hand back |

The `gate` and `user` distinctions are the load-bearing ones. Every LLM
proposal in this pipeline lands in a `staged_*` table with `status='pending'`.
Promotion to the live graph, and publication to production, are the user's
decisions. A driver that applies its own proposals has broken the pipeline's
one real invariant.

## Judgement nodes and their contracts

The judgement nodes are the reason this workbook exists. They were the parts
that required on-the-spot thinking, which meant they were re-derived from
scratch every session and their reasoning evaporated afterwards.

Each one now has a **contract** in `prompts/ingest/`: role, inputs, output JSON
schema, decision rubric, and worked examples drawn from decisions already made
on this corpus. A contract is written to be executable two ways, with the same
inputs and the same output shape either way:

```sh
# by a local model, through the existing provider abstraction
python3 scripts/llm.py --prompt prompts/ingest/chunk-config.md --input raw/celtic/mabinogion.txt

# or by whichever agent is driving — read the contract, produce the same JSON
```

That equivalence is the point. If a judgement can only be made by the agent
that happens to be driving today, it is not yet a contract; it is still a
conversation.

**Record the decision.** Judgement nodes are marked done in the ledger:

```sh
python3 -m guru ingest done <source-id> 05-chunk-config --by <who> --note "<one line>"
```

The one-line note goes in the ledger; the reasoning goes in
`docs/ingest/decisions/<source-id>.md`, which is tracked in git. A year from
now the question will not be *what* strategy was chosen for the Mabinogion but
*why* `heading` was rejected — and that answer only exists if someone wrote it
down at the time.

## The ledger, and staleness

`data/ingest/<source-id>.json` records nodes that leave no artifact of their
own — the judgement calls, and the manual gates. Everything else is probed from
real state: manifest entries, raw files, chunk TOMLs, node and embedding counts
in `guru.db`.

Two nodes are marked `stale_on_rechunk`. If they were recorded done and the
chunk files have changed since, `status` reports `[!]` rather than `[x]`. This
is the machine-checked form of a rule that was previously remembered or
forgotten: **`chunk.py` output is pre-clean, so any re-chunk invalidates
`clean_bodies.py` and the readability gate that followed it.**

## The node graph

| # | Node | Kind | Produces |
|---|---|---|---|
| 01 | [source-vetting](01-source-vetting.md) | judgement | a verified URL, format and license |
| 02 | [manifest-entry](02-manifest-entry.md) | command | `sources/manifest.toml` block |
| 03 | [acquire](03-acquire.md) | command | `raw/{tradition}/{id}.txt` |
| 04 | [boilerplate-survey](04-boilerplate-survey.md) | judgement | a strip plan |
| 05 | [chunk-config](05-chunk-config.md) | judgement | `chunking/{tradition}/{id}.toml` |
| 06 | [chunk](06-chunk.md) | command | `corpus/{tradition}/{id}/` |
| 07 | [clean-bodies](07-clean-bodies.md) | command | cleaned chunk bodies |
| 08 | [readability-gate](08-readability-gate.md) | judgement | a pass/fix decision |
| 09 | [graph-bootstrap](09-graph-bootstrap.md) | command | chunk nodes in `guru.db` |
| 10 | [tag-concepts](10-tag-concepts.md) | command | `staged_tags` rows |
| 11 | [tag-review](11-tag-review.md) | gate | queued tag decisions |
| 12 | [embed](12-embed.md) | command | `chunk_embeddings` rows |
| 13 | [propose-edges](13-propose-edges.md) | command | `staged_edges` rows |
| 14 | [edge-review](14-edge-review.md) | gate | queued edge decisions |
| 15 | [publish](15-publish.md) | user | a shipped corpus |

## Node file schema

Every node file has the same six sections, in the same order. Keep it that way;
a driver skimming for one field should always find it in the same place.

- **Precondition** — what must be true, phrased so it can be checked
- **Action** — the command, or the judgement and its contract
- **Output** — the artifact, by path
- **Gate** — what proves the node is done
- **Failure modes** — what has actually gone wrong here before
- **Provenance** — where the knowledge in this file came from

**Failure modes is the section that matters.** Preconditions and commands can be
reconstructed by reading the scripts. The failure modes cannot: they are the
residue of things that already went wrong on this corpus, and they are the
difference between a workbook and a table of contents. Every time this pipeline
surprises you, the surprise belongs in that section of the relevant node file.

## Adding a harness adapter

Adapters should be thin. All of them do the same thing: call
`guru ingest status --json`, read the node file it names, act, and call status
again. If an adapter starts accumulating rules of its own, those rules belong
in a node file instead — that is exactly the silo this workbook was built to
drain.

- **Any harness** — `AGENTS.md` at the repo root carries the driver loop and
  the standing constraints.
- **Claude Code** — `CLAUDE.md` defers to `AGENTS.md`. The
  `guru-review-tags` and `guru-review-edges` skills drive nodes 11 and 14
  through the review web app; their judgement criteria are mirrored in
  `prompts/ingest/tag-review.md` and `prompts/ingest/edge-review.md` so a
  driver without those skills can still do the work.
