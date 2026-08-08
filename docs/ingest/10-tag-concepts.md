# 10 — tag-concepts

**Kind:** command

Propose chunk→concept tags. Everything it writes is `pending`; nothing reaches
the live graph from this node.

## Precondition

Chunk nodes in `guru.db` (node 09), and a taxonomy that covers the text.

## Action

**Check the slot is free before anything else.** `llm status` reporting
`health: ok` tells you a server is up, not that it is idle.

```sh
llm status
pgrep -af 'tag_concepts|propose_edges'      # must be empty
```

Then start a server if there isn't one, and run the tagger:

```sh
scripts/run-qwen.sh            # Qwen3.5-27B-UD-Q4_K_XL.gguf
# or scripts/run-qwen-4b-guru.sh for the qwen-3-4b-guru fine-tune

python3 scripts/tag_concepts.py --text <source-id> \
    --provider llamacpp --model Qwen3.5-27B-UD-Q4_K_XL.gguf
```

Confirm which mode the launcher starts before committing to a long run.

`llm stop` **only a server you started.** One started outside `llm` — which
`llm status` reports as `model: (started outside llm)` — belongs to another
session.

## Output

`staged_tags` rows with `status='pending'`, carrying `score` (0–3),
`justification`, and `is_new_concept`.

## Gate

```sh
python3 -m guru ingest status <source-id>
```

Reports the staged-tag count for the text.

## Failure modes

**Thinking-budget overflow producing silent gaps.** A thinking model can spend
its whole token budget on reasoning prose and never close the JSON. This lost
about 12% of chunks on the 2026-05 run before `parse_json_response` learned to
warn on it. Check the run log for those warnings rather than trusting the row
count.

**Starting a run on a busy server.** Two `tag_concepts` runs against one
llama.cpp slot do not error and do not queue visibly. They serialise, both crawl,
and the newer one logs its opening two lines and then appears to hang — no
progress output, no rows, because the tagger only logs per chunk after a commit.
Both also contend for write locks on `guru.db`. Diagnosis is `pgrep -af
tag_concepts`, not patience: on 2026-08-08 a pilot run sat at zero rows for six
minutes behind an existing job that had itself reached only chunk 2 of 24.

**Assuming the model is a constant.** The 4B fine-tune and the 27B have
different failure modes and different id ranges — 4B batches are 70xxx, 27B are
71xxx. Node 11 needs to know which produced what.

**`--resume` and `--supersede-pending` interacting badly on a re-run.** Read
what they do before re-tagging a text that already has pending rows; the
defaults are not always what a re-run wants.

**Tagging a text whose concepts are absent from the taxonomy.** Produces a pool
dominated by `is_new_concept=1` proposals, which is a much harder review than
adding the concepts at node 09 would have been.

## Provenance

`scripts/tag_concepts.py`; the token-budget incident is documented in the
`call_llm` docstring in `scripts/llm.py`; id ranges from review practice.
