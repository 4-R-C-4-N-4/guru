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
| qwen-3-4b-guru Q4_K_M | 2.3 GB | ✓ | ✓ (7.8 GB with 32K ctx, parallel 4) |

Neither 24B-class model fits on the 4070, and both fit the 3090 with headroom.
So a split is never *required* here — and `nvidia-smi topo -m` reports `PHB`,
meaning the cards talk through the host bridge with no NVLink. A split model
therefore ships activations across PCIe on every token, for nothing.

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

| path | full corpus |
|---|---|
| GPU | ~7 min |
| CPU, 8 threads, int8 | ~6 min |

The CPU run is not slower here — quantized int8 on 8 threads keeps pace with
an unquantized GPU pass for a model this small, so there is no reason to
reserve either card for it. If you do route it at a GPU, pin the same way as
every other model on this rig: **`CUDA_DEVICE_ORDER=PCI_BUS_ID
CUDA_VISIBLE_DEVICES=0`** selects the 24 GB 3090 (see the naming trap above —
without `PCI_BUS_ID`, CUDA's default `FASTEST_FIRST` ordering makes `0` an
unstable reference, and on this host CUDA's un-pinned enumeration order is
inverted relative to what device 0 means physically).

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
