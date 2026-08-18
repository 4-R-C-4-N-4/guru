# 15 — publish

**Kind:** user

Ship the corpus. **This node belongs to the user.**

## Precondition

Nodes 01–12 satisfied, and the review queues applied — which is itself the
user's action, not a driver's. Nodes 13/14 (Pass C) are retired
(todo:c3f479ff / todo:aaaa5258) and no longer part of this precondition —
`guru/ingest.py`'s `NODES` list does not include them, so `guru ingest
status` walks straight from 12-embed to this node. Node 16
([derive-parallels](16-derive-parallels.md)) is not a *per-text*
precondition — it has no `--text` flag and no `guru ingest status` gate, so
it never blocks any one source from reaching this node. But publish itself
is not independent of it: node 15's action is `scripts/export.py`, which
refuses to run — loudly, via `SystemExit` — unless a derived-parallels run
exists under `config[export].derived_dir` and is younger than
`max_age_days` (default 30). Re-run node 16 before publishing if the last
run has aged out; see that node's file for the trigger and the command.

## Action

Nothing, if you are a driver, beyond the artifact. Stop before the VPS and
hand back.

A driver's work ends at the artifact: the corpus TOMLs, the migrated local DB,
the queued review decisions, an open PR. Publication is the user's.

**Building and loading the local artifact is a driver's normal work, not part
of the gate.** Running `scripts/export.py` and loading the resulting
`export/guru-corpus.sql.gz` into a local Postgres — most commonly `guru-web`'s
`docker compose exec postgres psql`, to run that repo's golden-query gates
against the new corpus — is exactly the same "local artifact, validates the
corpus end to end" carve-out that
[D6-export](../dossiers/D6-export.md) already states for the dossier stream:
*"Building it locally is fine... Shipping it is not yours."* The same holds
here. What stays the user's exclusively is anything that reaches the VPS or
production: `scripts/sync_corpus.sh`, ssh to the box, or a push to a
protected `main`. Reloading a local dev database from a local export crosses
none of those lines.

**A corpus update that adds or re-chunks a text needs a companion
`guru-web` PR.** That repo's `docs/golden-queries.md` states the rule from
its own side: *"A corpus update that adds or re-chunks a work ships that
work's query file (new or re-audited) in the same PR."* A `guru` PR that
lands a new or re-chunked text without also drafting/re-auditing that work's
`src/__tests__/fixtures/golden-queries/<work>.json` in a paired `guru-web`
PR is incomplete — the golden set otherwise drifts from the corpus it's
meant to be evaluating. Draft the file from the work's own chunks (never
from memory), verify it locally with
`npx tsx scripts/verify-golden-queries.ts <work>` against the freshly loaded
corpus, then run that repo's own gates before opening the PR there. See that
file for the full authoring rules (paraphrase-against-circularity,
`frozenEval`, provenance-only chunk ids).

Specifically, and regardless of how broad the instruction that got you here
was — including "run the whole thing" and "do the full fix":

- Do not run `scripts/sync_corpus.sh`.
- Do not ssh to the production VPS.
- Do not push to `main` in `guru` or `guru-web`. Both protect it. Branch,
  `gh pr create`, and reset local `main` to `origin/main`.

## Output

The user's decision.

## Gate

The user's.

## Failure modes

**Reading a broad instruction as authorisation for the last step.** "Run the
whole fix" means run it up to this node. The gate is deliberate, and a driver
that infers its way past it has removed the one checkpoint the pipeline was
designed around.

**Pushing to a protected main.** Branch and open a PR.

**Assuming a merged PR is a deployed corpus.** Corpus sync to production rides
the user's own push. A merged PR and a live corpus are different states —
`mabinogion`'s re-chunk sat in exactly that gap.

**There is no such thing as a throwaway export.** `next_corpus_version()`
increments and commits the counter in `_export_state` before a single COPY
block is written, so an export run "just to see if it works" permanently
advances the corpus version — and the dump it overwrote is gone, because
`gzip.open(OUTPUT, "wt")` truncates. Two runs during the Pass C cutover moved
the counter this way. The version numbers are cheap and gaps are harmless, so
this is a bookkeeping surprise rather than damage; it is only worth knowing
before you go looking for who burned v51. Note the ordering guarantee this
node *does* give you: every guard that can refuse an export — the missing,
stale, or orphan-endpoint checks on the derived-parallels artifact and the
frozen CONTRASTS snapshot — runs in `main()` before the bump and before the
truncation, so a *refused* export costs neither a version number nor the last
good dump.

## Provenance

Standing constraints, recorded here so that they survive independently of any
one harness's configuration.
