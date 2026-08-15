# GPU assembly for the pipeline

Two cards, two roles, one model each. **Never split a model across both.**

Measured 2026-08-08 on the live rig.

## The hardware, and a naming trap

| CUDA idx | card | VRAM | PCI |
|---|---|---|---|
| 0 | RTX 3090 | 24 GB | `01:00.0` |
| 1 | RTX 4070 | 12 GB | `06:00.0` |

CUDA enumeration does **not** follow motherboard slot numbering — the 3090 sits
in physical slot 1 but enumerates as CUDA 0. Worse, CUDA's default
`CUDA_DEVICE_ORDER` is `FASTEST_FIRST`, which reorders by capability rather than
bus, so `CUDA_VISIBLE_DEVICES=0` is not a stable reference.

**Always set `CUDA_DEVICE_ORDER=PCI_BUS_ID`,** which makes indices match
`nvidia-smi`. Or pin by UUID, which cannot be reordered at all:

```
GPU-1e207c4c-9743-52ff-2165-b19430f5c2ae   # 3090
GPU-e82e59ae-aba4-1fff-25a6-211616234334   # 4070
```

## Everything fits. That is what makes splitting pure loss.

| model | file | 3090 (24 GB) | 4070 (12 GB) |
|---|---|---|---|
| Mistral-Small-3.2-24B Q5_K_XL | 15.6 GB | ✓ (21.3 GB resident with 32K ctx) | ✗ |
| Qwen3.5-27B Q4_K_XL | 16.4 GB | ✓ | ✗ |
| qwen-3-4b-guru Q4_K_M | 2.3 GB | ✓ | ✓ (7.8 GB with 32K *total* ctx, parallel 4 — pre-todo:dcb3cce5 config, see "Slots vs workers" below; not the current `run-qwen-4b-guru.sh` default) |

Neither 24B-class model fits on the 4070, and both fit the 3090 with headroom.
So a split is never *required* here — and `nvidia-smi topo -m` reports `PHB`,
meaning the cards talk through the host bridge with no NVLink. A split model
therefore ships activations across PCIe on every token, for nothing.

## Slots vs workers

`--parallel` on the client (`scripts/tag_concepts.py`) and `PARALLEL` on the
server (`scripts/serve-llama.sh` / `scripts/run-qwen-4b-guru.sh`) are two
halves of one setting, not two independent knobs. The server's `PARALLEL`
decides how many requests llama.cpp will actually multiplex; the client's
`--parallel` decides how many it *sends* concurrently, and the client never
trusts the wrapper's default blindly — before a `--parallel N` run starts it
asks the server how many slots it actually has (`GET /props total_slots`,
falling back to `GET /slots`) and refuses to proceed if the server positively
reports fewer than N. It only refuses on that positive too-low count; an
unreachable server, or a build old enough to lack both endpoints, warns and
continues, because "unknown" and "under-provisioned" are different facts and
only one of them is a reason to block a run. See
[10-tag-concepts.md](10-tag-concepts.md) for what the refusal looks like from
the client side and what to do about it.

Slot *count* being sufficient doesn't mean slot *context* is (todo:dcb3cce5
finding 2) — a 4-slot server passing the check above can still serve 4
slots too small to hold one prompt, which is exactly what happened on
2026-08-15. The same pre-flight now also reads `GET /props
default_generation_settings.n_ctx` (the server's already-divided per-slot
context) and refuses when it's below a measured-prompt-derived floor,
degrading the same way: unknown warns and continues, positively-too-small
refuses.

**Slots are bounded by KV cache and context, not by model weight.** The 4B
finetune is ~2.3 GB at Q4_K_M (table above) — small enough that VRAM for the
weights themselves is never the constraint on how many slots fit. What
actually bounds a slot is llama.cpp dividing whatever `--ctx-size` it's
launched with by the slot count: with `kv_unified` false (the default —
`~/programs/llama.cpp/src/llama-context.cpp`, `cparams.n_ctx_seq =
cparams.n_ctx / cparams.n_seq_max`), raising `--parallel` without raising
`--ctx-size` to match doesn't cost more VRAM — it *shrinks* every slot's
share of the same total. That was silently true here until todo:dcb3cce5:
`serve-llama.sh --ctx-size 32768 --parallel 4` was serving 8192-token
slots, and every chunk of the 2026-08-15 elish run truncated at exactly
that boundary (`n_tokens = 8191, truncated = 1` in the slot-release log
lines) against a worst-case tagging prompt (largest corpus chunk + the
116-concept taxonomy) measured at ~7,600 tokens — leaving under 600 tokens
for the JSON response. `parse_json_response`'s truncation repair closes the
array after the last complete object instead of raising, so this produced
a silently partial tag list, not an error, and `--resume` never revisited
the affected chunks.

`scripts/serve-llama.sh` now scales for you: `CTX_SIZE` means **per slot**,
and the script passes llama-server `CTX_SIZE * PARALLEL` as `--ctx-size` —
matching llama.cpp's own preset convention (`common/arg.cpp` sets `params.n_ctx
= X * params.n_parallel` for its named context-size presets) so llama.cpp's
internal division hands the per-slot figure straight back out. This makes
the arithmetic in this section's earlier wording *true* rather than
backwards: raising `PARALLEL` now genuinely is a `CTX_SIZE × PARALLEL`
check against the card's free VRAM, because the script computes that
product and asks the server for it — before this fix, the same raise cost
nothing (the flag divided the fixed total further instead). `PARALLEL=4` /
`CTX_SIZE=16384` in `run-qwen-4b-guru.sh` (65536 total, chosen for headroom
over the measured ~7,600-token worst case, see that script's header for the
full justification) is a starting point, not a measured VRAM ceiling for
either card — no GB figure for this specific total is measured in this
file; watch `nvidia-smi` when you change it.

**How to spot truncation if it happens again.** The server's startup banner
(both this section's and `serve-llama.sh`'s own) logs `n_ctx_slot` —
compare it against whatever prompt you expect to send, not against the
`--ctx-size` total. At the HTTP layer, a request that hit the wall shows up
in the server's slot-release log line as `truncated = 1`; if you see that
paired with `n_tokens` equal to (or one less than) the slot's `n_ctx_slot`,
the response was cut off mid-generation, not legitimately short.

**A second endpoint, on the other card.** `tag_concepts.py --endpoint`
(repeatable, todo:d267201a) fans work out to more than one llama.cpp server.
This is a different pairing than "The assembly" below (27B on the 3090, 4B
on the 4070): here both cards run the 4B, for two lanes of the same bulk pass
instead of one, which only makes sense when a large tagging batch is all
that's queued and the 27B server doesn't need to be up at the same time.

```sh
# 3090, port 8080
CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=0 scripts/run-qwen-4b-guru.sh

# 4070, port 8081
CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=1 PORT=8081 scripts/run-qwen-4b-guru.sh

python3 scripts/tag_concepts.py --text <source-id> \
    --provider llamacpp --model qwen-3-4b-guru-v3-Q4_K_M.gguf \
    --parallel 4 \
    --endpoint http://127.0.0.1:8080 --endpoint http://127.0.0.1:8081
```

`--parallel` is interpreted *per endpoint* (`_run_parallel_pool`'s docstring
in `tag_concepts.py`), so the run above is 8-wide total, not 4. Each endpoint
is pre-flighted independently against that same `--parallel` value, so a
slow or under-provisioned second server refuses on its own without dragging
the first one's check down with it.

**Pin explicitly, every time.** The naming trap above applies here exactly as
it does to a single server: this rig's un-pinned CUDA enumeration is
inverted relative to physical device order, not merely unstable — under the
default `FASTEST_FIRST`, CUDA 0 resolves to the 4070, not the 3090 (the
opposite of the pinned table above), because `FASTEST_FIRST` ranks by
compute capability and the newer, smaller card wins that ranking. Always set
`CUDA_DEVICE_ORDER=PCI_BUS_ID` and pick `CUDA_VISIBLE_DEVICES` explicitly per
server, as in the commands above — never rely on the default to land the
right model on the right card, in either direction.

**The 27B teacher is excluded, and not just by convention.** It runs
think-on by default (`serve-llama.sh`'s `REASONING=auto`) and is 16.4 GB
against the 3090's 24 GB — far less headroom per additional slot than the
4B's 2.3 GB leaves on either card, for a model whose single-request VRAM
footprint from a full reasoning pass is already why `serve-llama.sh` defaults
`PARALLEL=1`. `tag_concepts.py`'s model guard (`check_parallel_model_guard`,
todo:5955d038) refuses `--parallel` N>1 against it structurally, not just by
the routing convention in [10-tag-concepts.md](10-tag-concepts.md) —
multiplexing it needs `--allow-parallel-any-model` as a deliberate,
individually-justified override, not a default anyone reaches for on this
hardware.

**No throughput number exists for any of this yet.** Slot count, endpoint
count, and `--parallel` are all unmeasured past "it runs without erroring" —
there is no chunks/sec or wall-clock figure in this file for the parallel
tagging path, on one endpoint or two, and none should be assumed from the
numbers in Measured below (those are Mistral-24B decode throughput on the
retired node 13 path — a different model doing a different kind of work).
Measure it the way everything else in this file is measured: time a real run
at `--parallel 1` and again at the value you intend to ship, against the
same `--tradition`/`--text` scope, and record what you get rather than
reusing a number that belongs to a different tool — see "Earlier drafts of
this file quoted a '~7 min GPU' row..." further down for exactly what that
mistake cost the last time it happened in this workbook.

## The assembly

Node 13 (propose-edges, the Mistral-24B consumer below) is retired —
todo:c3f479ff / todo:aaaa5258 — so node 10 is the only ingest node left that
needs a GPU-served local model. The two-server assembly this section
originally described is kept as history: it explains the PCIe-tax measurement
below and still applies verbatim if Qwen3.5-27B (node 10's 27B-provenance
path) is ever run alongside something else that wants the second card.

```
CUDA 0 · RTX 3090 · port 8080   the 24B-class model
                                  Mistral-24B      → node 13 propose-edges  (RETIRED)
                                  or Qwen3.5-27B   → node 10, for 27B provenance

CUDA 1 · RTX 4070 · port 8081   qwen-3-4b-guru     → node 10 tag-concepts
```

```sh
# 3090 — a 24B-class model (Qwen3.5-27B via scripts/run-qwen.sh today;
# scripts/run-mistral.sh served this slot for node 13 before its retirement
# and has been removed)
CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=0 scripts/run-qwen.sh

# 4070 — tagger, on a second port (see the diff below)
CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=1 PORT=8081 scripts/run-qwen-4b-guru.sh
```

Callers select the endpoint with `LLAMACPP_BASE_URL`, which `scripts/llm.py`
already honours — no code change:

```sh
LLAMACPP_BASE_URL=http://127.0.0.1:8081 python3 scripts/tag_concepts.py --text <id> \
    --provider llamacpp --model qwen-3-4b-guru-Q4_K_M.gguf
```

## Measured

Decode throughput, Mistral-24B, real edge-proposal traffic (node 13, before
its retirement) — kept as the PCIe-tax evidence; the pinning lesson
transfers to any 24B-class model run on this rig, Qwen3.5-27B included:

| configuration | median | note |
|---|---|---|
| split across 3090 + 4070 | **37.6 t/s** | 53 samples; 14.4 GB + 7.6 GB, ~22 GB total for a 15.6 GB model |
| pinned to 3090 | **45.9 t/s** | **+22%**, and the 4070 falls idle |
| pinned, while the 4070 tags | **46.0 t/s** | no measurable interference |
| tagger on 4070, same moment | **112.6 t/s** | |

Two results worth separating. The +22% is the PCIe tax you stop paying. The
second card going from *half a model* to *a whole second model* is the larger
win — historically that meant nodes 10 and 13 stopped contending for one
server (see below); today, with 13 retired, it means node 10's two model
variants (27B and the 4B fine-tune) can run pinned and simultaneously instead
of trading one server back and forth.

## What this unlocked (historical — node 13 is retired)

This section described why nodes 10 and 13 no longer needed to be
sequential: pinned to separate cards, a text could be tagged on the 4070
while the previous text's edges were proposed on the 3090. With node 13
gone, there is no second GPU-bound ingest node to pipeline against — node 16
([derive-parallels](16-derive-parallels.md)), Pass C's replacement, is
CPU-only (see below) and never touches either card. The second card is not
idle by necessity, though: node 10 alone can still use it, e.g. running the
27B teacher and the 4B fine-tune on separate pinned servers when a batch
needs both (see `docs/ingest/decisions/gospel-of-judas.md` for a case that
called for the 27B specifically).

```
book N     tag on 4070  ─┐
book N-1                 └─→  (formerly) propose edges on 3090
```

Node 12's embedder (`nomic-embed-text` via Ollama) is small and can share the
4070, or stay on CPU. The Pass D dossier stream uses the `claude-code` provider
and touches neither card.

## The one blocker

`scripts/serve-llama.sh` hardcodes the listen address, so two servers cannot
coexist:

```diff
-HOST="127.0.0.1"
-PORT="8080"
+HOST="${HOST:-127.0.0.1}"
+PORT="${PORT:-8080}"
@@
-CTX_SIZE="32768"
-N_GPU_LAYERS="999"
+CTX_SIZE="${CTX_SIZE:-32768}"
+N_GPU_LAYERS="${N_GPU_LAYERS:-999}"
```

Four lines, same `${VAR:-default}` idiom the file already uses for `PARALLEL`,
`TEMP` and the rest — nothing changes for existing callers. `CTX_SIZE` and
`N_GPU_LAYERS` are included so the 4070 can take a smaller context without a
second copy of the script.

Device pinning itself needs no change: `CUDA_VISIBLE_DEVICES` is inherited
through the `exec`.

## Checking it worked

```sh
nvidia-smi --query-gpu=index,name,memory.used --format=csv,noheader
```

One card holding the model and the other near zero is correct. Both cards
holding part of one model is the failure this document exists to prevent — and
it is silent, since a split model serves requests perfectly well, just slower
and while occupying hardware another stage wants.

## derive_parallels: the one CPU-only exception

`scripts/derive_parallels.py` does not touch either card. It scores
(concept, chunk) pairs with the vendored `~/programs/guru/scorer-v1`
cross-encoder via `guru.rerank.score_pairs` (torch + transformers, an
optional dependency group — see the README), and that scorer is small enough
(22.7M params) that CPU is the intended path, not a fallback of last resort:

**There is no GPU path to choose.** `guru/rerank.py` never places the model
or its tensors on a device — no `.to()`, no `.cuda()` — so scoring runs on
CPU no matter what the environment says. Its `os.environ.setdefault(
"CUDA_VISIBLE_DEVICES", "")` only *hides* the cards from torch; overriding it
with `CUDA_VISIBLE_DEVICES=0` un-hides them and changes nothing else. Setting
the usual `CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=0` pin here is
inert — it will not move the work to the 3090, it will only look as though it
did.

| path | full corpus |
|---|---|
| CPU, 8 threads | ~10 min (measured 2026-08-14: 614 s scoring, 38,452 pairs over 116 concepts, fp32 as `rerank.py` loads it) |

Earlier drafts of this file quoted a "~7 min GPU" row beside the CPU one. That
number was real, but it belonged to the rellm prototype, which did its own GPU
scoring; the guru port reuses `rerank.py` and inherited none of it. Treat any
GPU timing for this node as prototype history, not something this script can
reproduce. Adding GPU support would mean a device argument threaded through
`_load()`/`score_pairs()` plus an opt-in env var — worth doing only if the
corpus grows enough that ~15 CPU-minutes per re-derive starts to hurt, since
the model is small enough that the win is minutes, not hours.

## Model home

Every guru fine-tune (this includes `derive_parallels`'s vendored scorer)
lives under `~/programs/guru/<purpose>-v<N>/` — siblings of `~/programs/mistral`
and `~/programs/gemma4`, never inside a repo checkout. The repo pins the path
(and, where computed, a sha256 of the weights file) plus a training-card copy:
`~/programs/guru/scorer-v1` (pinned in `config/derived_parallels.toml`) and
`~/programs/guru/4b-v3` (pinned as `MODEL_DIR` in
`scripts/run-qwen-4b-guru.sh`, the current `qwen-3-4b-guru` build — v3-r32,
see `docs/ingest/decisions/gospel-of-judas.md` for why a text can still call
for the 27B teacher instead: the finetune is pinned to the taxonomy snapshot
it trained on).
