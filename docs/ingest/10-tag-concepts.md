# 10 — tag-concepts

**Kind:** command

Propose chunk→concept tags. Everything it writes is `pending`; nothing reaches
the live graph from this node.

## Precondition

Chunk nodes in `guru.db` (node 09), and a taxonomy that covers the text.

## Action

With two GPUs, the tagger belongs on the 4070 and the 24B-class models on the
3090 — see [gpu-assembly.md](gpu-assembly.md), which also covers running this
node and node 13 concurrently instead of one after the other.

**Check the slot is free before anything else.** `llm status` reporting
`health: ok` tells you a server is up, not that it is idle.

```sh
llm status
pgrep -af '[t]ag_concepts|[p]ropose_edges'      # must be empty
```

The brackets are load-bearing. Written as `'tag_concepts|propose_edges'` the
pattern matches the shell running it — the command line contains the string —
so the check reports a competing process forever and the precondition can never
pass. `[t]ag_concepts` matches the same processes but not the literal text of
the command itself.

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

**The gate now counts coverage, not existence — it used to count neither.**
Until todo:1f6d2c11 the probe asked whether *any* `staged_tags` row existed for
the text, so one surviving chunk satisfied it. After a partial re-chunk,
`yoga-sutras-book-02` reported `[x]` with 3 of 55 chunks tagged, and because
node 11's gate is "no pending rows remain", 52 chunks carrying no tags made
that trivially true as well: 10 green, 11 green, text walks to node 12
silently under-tagged. It now reads `N of M chunks untagged — run with
--resume`.

The signal is `tagging_progress`, one row per chunk the tagger processed, not
`staged_tags`. A chunk the model read and found nothing in is legitimately
tagless — `plotinus-select-works-index` has 107 of 752 such chunks with all 752
processed — so keying the gate on `staged_tags` would call that text incomplete
forever. Corollary: a tagging run that dies mid-chunk leaves no progress row,
which is what makes `--resume` correct rather than merely convenient.

**What the coverage gate still cannot see: the failure mode directly below
it.** `mark_complete` runs after the insert loop whether or not the loop had
anything to insert, and `parse_tags` returns `[]` rather than raising when a
thinking model burns its budget without closing the JSON. So an overflowed
chunk is recorded as processed and the gate reports `all N chunks tagged`. A
repeat of the 2026-05 run, which lost about 12% of chunks this way, would pass
cleanly. `tagging_progress` cannot distinguish it, because "processed, no tags"
is also what a legitimately tagless chunk looks like — and that ambiguity is
exactly what makes the gate work for plotinus. The discriminator would have to
come from the parse: skip `mark_complete` when the response failed to parse, as
opposed to parsing to an empty list. Until then the run log's
`parse_json_response` warnings are the only signal, and the gate going green
does not stand in for reading them.

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

**Expecting deleted `staged_tags` to make a chunk re-taggable.** They are
different tables. `--resume` is on by default and filters on
`tagging_progress` (`AND n.id NOT IN (SELECT chunk_id FROM tagging_progress)`),
which is written per chunk as it completes and is never touched by clearing
`staged_tags`. Wipe the staged rows and the re-run tags nothing at all,
reporting success. Either `--no-resume`, or delete the matching
`tagging_progress` rows, or pass `--chunk-ids-from-file`, which takes an
explicit id list and ignores the resume filter entirely.

`--supersede-pending` is the other half: it defaults on in the batch path and
deletes a prior pending row of the same provenance rather than colliding with
it. On a re-run against a text that still has an unreviewed queue, that
silently discards rows a reviewer may already have queued verdicts against.

**Tagging a text whose concepts are absent from the taxonomy.** Produces a pool
dominated by `is_new_concept=1` proposals, which is a much harder review than
adding the concepts at node 09 would have been.

## Provenance

`scripts/tag_concepts.py`; the token-budget incident is documented in the
`call_llm` docstring in `scripts/llm.py`; id ranges from review practice.
