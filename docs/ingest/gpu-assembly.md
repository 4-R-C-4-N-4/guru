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

```
CUDA 0 · RTX 3090 · port 8080   the 24B-class model
                                  Mistral-24B      → node 13 propose-edges
                                  or Qwen3.5-27B   → node 10, for 27B provenance

CUDA 1 · RTX 4070 · port 8081   qwen-3-4b-guru     → node 10 tag-concepts
```

```sh
# 3090 — proposer
CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=0 scripts/run-mistral.sh

# 4070 — tagger, on a second port (see the diff below)
CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=1 PORT=8081 scripts/run-qwen-4b-guru.sh
```

Callers select the endpoint with `LLAMACPP_BASE_URL`, which `scripts/llm.py`
already honours — no code change:

```sh
LLAMACPP_BASE_URL=http://127.0.0.1:8081 python3 scripts/tag_concepts.py --text <id> \
    --provider llamacpp --model qwen-3-4b-guru-Q4_K_M.gguf

python3 scripts/propose_edges.py --text <id> --provider llamacpp   # defaults to :8080
```

## Measured

Decode throughput, Mistral-24B, real edge-proposal traffic:

| configuration | median | note |
|---|---|---|
| split across 3090 + 4070 | **37.6 t/s** | 53 samples; 14.4 GB + 7.6 GB, ~22 GB total for a 15.6 GB model |
| pinned to 3090 | **45.9 t/s** | **+22%**, and the 4070 falls idle |
| pinned, while the 4070 tags | **46.0 t/s** | no measurable interference |
| tagger on 4070, same moment | **112.6 t/s** | |

Two results worth separating. The +22% is the PCIe tax you stop paying. The
second card going from *half a model* to *a whole second model* is the larger
win, because it changes what the pipeline can do rather than how fast one step
runs.

## What this unlocks

Nodes 10 and 13 stop being sequential. Today they contend for one server, so a
text is tagged, then its edges are proposed. Pinned, they are independent
services and the corpus can be pipelined:

```
book N     tag on 4070  ─┐
book N-1                 └─→  propose edges on 3090
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
