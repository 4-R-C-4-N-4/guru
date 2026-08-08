# AGENTS.md

Guidance for any agent runtime working in this repository. Harness-neutral by
intent: nothing here assumes a particular tool, and anything that would only
make sense to one harness belongs in that harness's adapter, not in this file.

## What this repository is

Guru ingests public-domain primary texts from ~21 religious and esoteric
traditions, chunks them into citation-addressable units, builds a concept graph
over them, and answers questions with per-tradition citations via hybrid
retrieval — vector similarity plus graph traversal.

The corpus is the product. Citations are load-bearing: a chunk id is a promise
that a specific passage says a specific thing, and a reader can check it against
a printed edition.

## Ingesting a text

This is the main flow, and it is documented as a state machine rather than as
prose you are expected to have memorised.

```sh
python3 -m guru ingest status <source-id>    # which node, what blocks it, what runs next
<do exactly the one thing it names>
python3 -m guru ingest status <source-id>    # the gate re-checks; the node advances or it doesn't
```

`status` probes the filesystem and `guru.db` directly, so it reports the state
of the corpus rather than the state of anyone's memory. `--json` for machine
consumption.

Fifteen nodes, one workbook file each, in [`docs/ingest/`](docs/ingest/). Read
the node file the CLI names before acting — the **Failure modes** section of
each is the part that is not reconstructible from the scripts.

Six of the nodes are judgement calls rather than commands. Each has a contract
in [`prompts/ingest/`](prompts/ingest/) specifying its inputs, output JSON
schema, and decision rubric, executable either way:

```sh
python3 scripts/run_contract.py <contract-id> --input <name>=<path> --var <name>=<value>
python3 scripts/run_contract.py <contract-id> ... --print-prompt   # to answer it yourself
```

If you find yourself making an ingest judgement that has no contract, that is a
gap in the workbook. Write the reasoning into
`docs/ingest/decisions/<source-id>.md` and say so.

## Building dossiers and summaries

The second stream, documented in [`docs/dossiers/`](docs/dossiers/). It runs on
**works** — the dossier unit, declared in `sources/works.toml`, with unlisted
texts as implicit singletons — so it has its own graph and its own CLI:

```sh
python3 -m guru dossier status <work-id>    # where this work is
python3 -m guru dossier survey              # where every work is stuck
python3 -m guru dossier drift               # plan vs live tables vs corpus on disk
```

Six nodes: plan-freeze, generate, review, promote, embed, export. The streams
meet at one point — D1 requires every member text through ingest node 07.

Three things to know before touching it:

- **The span plan is a freeze artifact.** A corpus change that alters totals
  means a new campaign — bump `campaign_id` in `config/dossiers.toml` and
  re-plan. Never a partial re-plan.
- **The generation backend is a campaign parameter.** `provider` in that same
  file. Today it is `claude-code`, which is why this stream is normally driven
  by an agent end to end. Never rely on a session default for the model; the
  `model` column is the provenance line.
- **Review converges the template, not the row.** A cluster of one rubric code
  is a template defect: revise the prompt, bump its version, regenerate.

Run `guru dossier drift` before planning anything. It separates a genuine
freeze violation from an orphan — a live dossier whose texts are not in
`corpus/` because `data/guru.db` is git-ignored and shared across branches
while `corpus/` is tracked. Those rows belong to a checkout you are not on.
Never delete them to clear the report.

## Standing constraints

**Never apply your own proposals.** Every LLM proposal in this pipeline lands in
a `staged_*` table with `status='pending'`. You may queue accept / reject /
reassign / reclassify decisions. Promotion to the live graph is the user's.
Never call the review app's `/api/apply`.

**Never queue a verdict you did not earn.** Every accept and reject at nodes 11
and 14 must come from having read the chunk body. Sampling and extrapolating
across a batch is not review; it produces an audit trail that cannot be
distinguished from one that was.

**Never publish.** No `scripts/sync_corpus.sh`, no ssh to the production VPS —
including under an instruction as broad as "run the whole thing". Stop at the
artifact.

**Never push `main`.** Protected in both `guru` and `guru-web`. Branch,
`gh pr create`, reset local `main` to `origin/main`.

**Release the GPU.** Local model work ends with `llm stop`. An idle GPU is the
resting state; do not restart a model that was not asked for.

## Conventions

- Python 3.11+; `tomllib` for reads, `tomli-w` for writes. No YAML dependency.
- `guru/paths.py` is the single source of truth for filesystem paths.
- `scripts/llm.py` is the provider abstraction — `llamacpp`, `ollama`,
  `anthropic`, `openai`, `claude-code`. Pipeline scripts and the query CLI all
  go through it. `max_tokens` is deliberately required, not defaulted.
- `corpus/*.toml` is generated. Review the chunker config, not its output.
- Tests: `python3 -m pytest tests/`. Chunking tests need
  `PYTHONPATH=scripts/chunkers`.

## Where knowledge goes

The point of the workbook is that ingest knowledge lives in this repository
rather than in a conversation or in one harness's configuration.

- A rule about how a node behaves → that node's file in `docs/ingest/`.
- A judgement rubric → the node's contract in `prompts/ingest/`.
- Why a specific text was handled a specific way →
  `docs/ingest/decisions/<source-id>.md`.
- Anything that surprised you → the **Failure modes** section of the relevant
  node file. That section is the workbook's actual value.
