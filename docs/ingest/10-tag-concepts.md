# 10 — tag-concepts

**Kind:** command

Propose chunk→concept tags. Everything it writes is `pending`; nothing reaches
the live graph from this node.

## Precondition

Chunk nodes in `guru.db` (node 09), and a taxonomy that covers the text.

## Action

**Which model, first.** Owner standard, 2026-08-13 — decide before starting a
server, not after:

| text size | tradition / concept territory | model |
|---|---|---|
| large | existing — taxonomy already covers it | 4B fine-tune — `scripts/run-qwen-4b-guru.sh` |
| small | existing | 27B teacher — `scripts/run-qwen.sh` |
| any size | net-new — new tradition, new concept territory, a taxonomy expansion | 27B teacher — `scripts/run-qwen.sh`, regardless of size |

Net-new always wins the row: a large net-new text still gets the 27B teacher.

**"Large" is owner-tunable, not yet fixed.** `>= 100 chunks` is the proposed
starting line (todo:667f1aaf); it has not been settled by review. Until it is,
treat anything you're unsure of as small/net-new and reach for the 27B —
the failure mode below is the cost of guessing wrong in the other direction.

**Why the split.** The 4B fine-tune is much faster and, served via
`scripts/run-qwen-4b-guru.sh` (`PARALLEL=4`), multiplexes four concurrent
`tag_concepts.py` instances against one 12 GB card without VRAM pressure —
the throughput case for routing large, in-distribution batches to it. It
reliably hits the tags it was trained on and nothing else, which is exactly
the problem for a net-new text: it has no way to propose a concept its
training snapshot didn't have, and — see Failure modes — has proposed the
*wrong* existing concept instead of admitting the gap, at least once, on this
corpus. The 27B teacher reads the live taxonomy fresh in-prompt on every call,
so it natively proposes concepts that postdate whatever the 4B was last
trained on (worked example: `docs/ingest/decisions/gospel-of-judas.md`,
node 09, six taxonomy additions the live v3 finetune would have silently
missed).

With two GPUs, the tagger belongs on the 4070 and 24B-class models on the
3090 — see [gpu-assembly.md](gpu-assembly.md).

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
scripts/run-qwen.sh            # Qwen3.5-27B-UD-Q4_K_XL.gguf, small/net-new
# or scripts/run-qwen-4b-guru.sh for the qwen-3-4b-guru fine-tune, large/existing

python3 scripts/tag_concepts.py --text <source-id> \
    --provider llamacpp --model Qwen3.5-27B-UD-Q4_K_XL.gguf
# or --model qwen-3-4b-guru-v3-Q4_K_M.gguf, matching whichever server you started
```

Confirm which mode the launcher starts before committing to a long run.

**Model identifier convention.** `--model` is stamped verbatim into
`staged_tags.model`, and node 11's same-model dedupe keys off that exact
string, so server and client must name the same file:

| model | identifier(s) | serving script |
|---|---|---|
| 27B teacher | `Qwen3.5-27B-UD-Q4_K_XL.gguf` | `scripts/run-qwen.sh` |
| 4B fine-tune, v3 (current) | `qwen-3-4b-guru-v3-Q4_K_M.gguf` | `scripts/run-qwen-4b-guru.sh` |
| 4B fine-tune, v1 (retired serving default) | `qwen-3-4b-guru-Q4_K_M.gguf` | — |

Both 4B identifiers match the `qwen-3-4b-guru-*` convention family; the
`-v3-` infix is deliberate (todo:379722ec), not cosmetic — it keeps v3's rows
distinguishable from v1's in the `model` column rather than colliding under
one string. 27B identifiers follow `Qwen3.5-27B-*`.

**Running a parallel bulk pass.** Parallelism is a property of the 4B path
only. The routing table above already sends large, in-distribution batches
to the 4B and everything small or net-new to the 27B, and `--parallel`
follows that same line rather than crossing it: the model guard
(`check_parallel_model_guard`, todo:5955d038) refuses `--parallel` N>1 for
any `--model` that doesn't start with `qwen-3-4b-guru-`, so the 27B can't be
multiplexed by accident. That costs nothing the routing table wasn't already
deciding — the 27B's rows are exactly the ones this node runs serially by
design.

```sh
scripts/run-qwen-4b-guru.sh    # PARALLEL=4 server-side (gpu-assembly.md)

python3 scripts/tag_concepts.py --text <source-id> \
    --provider llamacpp --model qwen-3-4b-guru-v3-Q4_K_M.gguf \
    --parallel 4
```

`--parallel` on the client and `PARALLEL` in `run-qwen-4b-guru.sh` are two
halves of one setting (see "Slots vs workers" in
[gpu-assembly.md](gpu-assembly.md)). Before submitting anything,
`tag_concepts.py` pre-flights the server's actual slot count (`GET /props
total_slots`, falling back to `GET /slots`) and refuses to start if the
server positively reports fewer than `--parallel`. **When it refuses:**
either restart the server with a higher `PARALLEL`, or lower `--parallel` to
match what it reported — never proceed past the refusal on the assumption
the server will "catch up". An unreachable server, or one running a build
old enough to lack both endpoints, only warns and continues rather than
refusing — see Failure modes below for why that case is the one to worry
about, not the refusal.

Multiplexing the 27B anyway is `--allow-parallel-any-model` — a deliberate,
individually-justified override of the guard above, not a workaround for it.
The teacher runs think-on and was never sized for concurrent requests; see
gpu-assembly.md for why it's excluded on hardware grounds too.

A second 4B server on the other card is `--endpoint URL`, repeatable;
`--parallel` is interpreted *per endpoint*, so `--parallel 4 --endpoint
http://127.0.0.1:8080 --endpoint http://127.0.0.1:8081` submits 8 concurrent
requests total, not 4. See gpu-assembly.md for bringing the second server up.

No throughput figure exists for this path — it has not been measured, on one
endpoint or two. The number to trust is whatever you measure on your own
run: wrap the command above in `time`, once at `--parallel 1` and once at
the `--parallel N` you intend to ship, against the same `--tradition`/`--text`
scope, and compare wall-clock. Do not carry over a number from a different
tool or a different node — see gpu-assembly.md's "~7 min GPU" correction for
what that mistake cost elsewhere in this workbook.

**The no-think caveat.** Running the 27B in no-think mode measured roughly
6x faster on this corpus — one pass
(`docs/corpus-expansion/apocryphon-of-john.md`) measured ~300 s/chunk
thinking versus ~37 s/chunk no-think, and
that ratio should be read as an order-of-magnitude figure from one text, not
a precise constant. It is also the mode the *applied* corpus was tagged in.
**Quality versus think mode remains UNMEASURED** — no gold-eval or accuracy
comparison exists, only the speed figure and the fact that it's what shipped.
Do not silently default to no-think on the strength of the speed number alone;
say which mode a run used. Practically: `scripts/serve-llama.sh` in this repo
hardcodes `--reasoning auto` and has no `EXTRA_ARGS` hook, so no-think is not
reachable from the in-repo script — only the `~/programs/model-runners/` copy
supports it.

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

**A `--parallel` run against a 1-slot server *looks* parallel and isn't.** N
worker threads, N in-flight requests, log lines interleaving exactly as
`--parallel N` promises — and llama.cpp still serialises every one of them
internally if the server was started with `PARALLEL=1` (or never restarted
after `PARALLEL` was raised in the wrapper). Wall-clock barely improves over
`--parallel 1`; the only visible symptom is that a run that should be faster
isn't, which reads as "the model is just slow" unless you go looking. This is
exactly what `preflight_server_slots` (todo:5955d038) exists to catch — but
it can only refuse on a *positive* too-low slot count. Against an unreachable
server, an older build without `/props`/`/slots`, or a response shape it
doesn't recognize, it logs a warning and continues rather than blocking the
run. At that point you are flying blind exactly as this failure mode
describes, and that warning line in the run log — not the absence of an
error — is the only signal the check didn't actually run.

**Assuming the model is a constant.** The 4B fine-tune and the 27B have
different failure modes and different id ranges — 4B batches are 70xxx, 27B are
71xxx. Node 11 needs to know which produced what.

**The v2 finnic-theurgy contamination — the reason the net-new rule exists.**
The 4B fine-tune's v2 run tagged `kalevala` (tradition `finnic`, new to that
model's training snapshot) and proposed `theurgy` — an Iamblichean,
Neoplatonic-tradition concept — against it. That is not a random miss: v2 had
no way to propose a concept its training distribution didn't cover, so it
reached for the nearest concept it *did* know and stamped a wrong tag with the
same confidence as a right one, rather than surfacing the gap the way an
`is_new_concept` proposal would. The regression was traced to this
contamination, not to a training defect (todo:379722ec) — the fix was not
retraining v2, it was routing: net-new traditions and net-new concept
territory always go to the 27B teacher, at any size, because it reads the
live taxonomy fresh in-prompt and can propose what it doesn't already know
instead of substituting something it does.
`docs/ingest/decisions/gospel-of-judas.md`'s node 09 section is the same rule
applied on purpose, ahead of a failure: v3 was passed over for a
net-new-concept text before it had the chance to repeat v2's mistake.

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
