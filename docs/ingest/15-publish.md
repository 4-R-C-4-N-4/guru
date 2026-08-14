# 15 — publish

**Kind:** user

Ship the corpus. **This node belongs to the user.**

## Precondition

Nodes 01–12 satisfied, and the review queues applied — which is itself the
user's action, not a driver's. Nodes 13/14 (Pass C) are retired
(todo:c3f479ff / todo:aaaa5258) and no longer part of this precondition —
`guru/ingest.py`'s `NODES` list does not include them, so `guru ingest
status` walks straight from 12-embed to this node. Node 16
([derive-parallels](16-derive-parallels.md)) is not a per-text precondition
either: it is corpus-wide and runs independently of any one text's publish
gate — see that node's file for when to re-run it.

## Action

Nothing, if you are a driver. Stop here and hand back.

A driver's work ends at the artifact: the corpus TOMLs, the migrated local DB,
the queued review decisions, an open PR. Publication is the user's.

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

## Provenance

Standing constraints, recorded here so that they survive independently of any
one harness's configuration.
