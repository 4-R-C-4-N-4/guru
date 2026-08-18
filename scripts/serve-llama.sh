#!/usr/bin/env bash
# scripts/serve-llama.sh
# Shared llama.cpp server launcher. Called by run-<model>.sh wrappers.
#
# Usage: serve-llama.sh <model-filename>
#   model-filename is resolved relative to $MODEL_DIR (default: ~/models)

set -euo pipefail

MODEL_FILE="${1:?Usage: $0 <model-filename>}"

# --- Paths (override via env if needed) ---
LLAMA_BIN="${LLAMA_BIN:-$HOME/programs/llama.cpp/build/bin/llama-server}"
MODEL_DIR="${MODEL_DIR:-$HOME/programs/}"
MODEL_PATH="$MODEL_DIR/$MODEL_FILE"

# --- Server config ---
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8080}"

# --- Model loading ---
# CTX_SIZE is PER SLOT, not the total passed to llama-server (todo:dcb3cce5
# finding 1). llama.cpp itself divides whatever --ctx-size it's given by
# n_seq_max (== --parallel) when kv_unified is false, the default
# (~/programs/llama.cpp/src/llama-context.cpp:289:
# cparams.n_ctx_seq = cparams.n_ctx / cparams.n_seq_max) — so a launch of
# `--ctx-size 32768 --parallel 4` was already serving 8192-token slots, not
# 32768-token ones, and every chunk of the 2026-08-15 elish run truncated
# at n_ctx_slot=8192 (n_tokens=8191, truncated=1) with the ~7,600-token
# worst-case tagging prompt (largest corpus chunk + the 116-concept
# taxonomy). parse_json_response's truncation repair closes the array after
# the last complete object instead of raising, so this failed silently —
# --resume never revisited the affected chunks.
#
# This script now scales the total it asks llama-server for by PARALLEL
# below, matching llama.cpp's own preset convention (common/arg.cpp sets
# params.n_ctx = X * params.n_parallel for its context-size presets) — so
# CTX_SIZE means "what one slot gets" here too, and llama.cpp's own division
# hands it straight back. With the default PARALLEL=1 (the 27B teacher path,
# run-qwen.sh), CTX_SIZE * PARALLEL == CTX_SIZE, so nothing changes for that
# caller. run-qwen-4b-guru.sh sets both CTX_SIZE and PARALLEL explicitly —
# see its header for the chosen per-slot default and why. Total VRAM now
# scales with PARALLEL: raising it buys more per-slot context at the cost of
# a proportionally larger total KV cache, on top of the same 2.3GB of
# weights — that trade is unmeasured in absolute GB here (no GPU was used to
# produce this comment); watch `nvidia-smi` when you raise it.
#
# --kv-unified (llama.cpp: cparams.kv_unified, common/common.h) is the other
# lever this could use — it stops dividing --ctx-size by slot count at all,
# so a single request could use the full budget instead of a fixed
# `total/PARALLEL` share. Not used here: it trades a static per-slot
# reservation for a *shared* pool that concurrent sequences draw from
# dynamically, which pays off when requests are heterogeneous (some short,
# some long) so the total can be smaller than the sum of worst cases. This
# workload is the opposite — every tag_concepts.py request is close to the
# same worst-case prompt size — so a shared pool would still need to hold
# PARALLEL requests near their worst case at once, buying nothing over
# static division while adding the unified cache's own complexity
# (allocation/defrag across sequences). Static division (the default,
# kv_unified=false) stays the simpler, equally-sized choice for this
# specific access pattern.
CTX_SIZE="${CTX_SIZE:-32768}"
N_GPU_LAYERS="999"
THREADS="6"
BATCH_SIZE="512"
# --parallel controls how many concurrent requests llama-server will
# multiplex. Default 1 (serialized) suits the 27B thinking model where
# each request can consume most of available VRAM. Smaller models can
# safely run higher — set PARALLEL via the wrapper (see
# run-qwen-4b-guru.sh).
#
# This PARALLEL is the SERVER-side half of one setting; the CLIENT-side
# half is tag_concepts.py's --parallel N (todo:5955d038). The client
# pre-flights this value (GET /props total_slots, when reachable) before
# starting a run and refuses to exceed it — so raising --parallel N on the
# client without raising PARALLEL here just makes the client refuse to
# start, not silently queue behind too few slots.
PARALLEL="${PARALLEL:-1}"

# --- Sampling defaults (overridable per-request from clients, or by a
#     model-specific wrapper exporting TEMP/TOP_P/TOP_K/MIN_P/REPEAT_PENALTY
#     before calling this script — scripts/run-mistral.sh did this for
#     Mistral's near-greedy recommendation before Pass C's retirement
#     removed it; see docs/ingest/13-propose-edges.md) ---
TEMP="${TEMP:-0.2}"
TOP_P="${TOP_P:-0.9}"
TOP_K="${TOP_K:-40}"
MIN_P="${MIN_P:-0.05}"
REPEAT_PENALTY="${REPEAT_PENALTY:-1.05}"

# RNG seed. llama.cpp's default is -1, meaning a fresh random seed PER REQUEST,
# so two identical calls to the same model with the same prompt can return
# different answers. That is fine for generation and fatal for a gate: measured
# on the D3 rubric, three of three verdicts flipped between two consecutive
# runs of the same rows. Pin SEED in a wrapper that needs reproducibility
# (scripts/run-qwen-judge.sh). -1 keeps the existing behaviour everywhere else.
SEED="${SEED:--1}"

# --- Reasoning routing ---
# REASONING=auto + REASONING_FORMAT=deepseek route a thinking model's
# preamble into message.reasoning_content instead of mixing it into
# message.content. scripts/llm.py:call_llamacpp already handles that
# split: it returns content when present, falls back to reasoning_content
# only when content is empty. With these flags, the production tagging
# path will read clean JSON from content even when the model thinks for
# thousands of tokens first. Non-thinking models (Mistral) are unaffected.
REASONING="${REASONING:-auto}"
REASONING_FORMAT="${REASONING_FORMAT:-deepseek}"

# Hard cap on thinking tokens. -1 (llama.cpp's default) is unbounded, and for
# a thinking model that is a live failure: the reasoning pass can consume the
# caller's entire max_tokens, leaving `content` empty. llm.py:call_llamacpp
# then falls back to reasoning_content and hands the caller a paragraph of
# deliberation where it expected JSON — every contract call fails, and fails
# looking like a parse bug rather than a budget one. At N>0 llama.cpp injects
# a message and closes the think block with the proper end tag, so an answer
# is emitted. Set this in any wrapper whose caller parses structured output.
REASONING_BUDGET="${REASONING_BUDGET:--1}"

# Raw llama-server flags, word-split on purpose so a wrapper can pass several.
# Same hook the model-runners copy of this script already has; added here so a
# wrapper can reach flags this script does not model, e.g. speculative decoding:
#   EXTRA_ARGS='--spec-type draft-mtp --spec-draft-n-max 2'
# Unquoted expansion means values containing spaces must not be quoted as one
# argument — pass JSON without spaces, or use the LLAMA_ARG_* env var instead.
EXTRA_ARGS="${EXTRA_ARGS:-}"

# --- Sanity checks ---
if [[ ! -f "$MODEL_PATH" ]]; then
    echo "Model not found: $MODEL_PATH" >&2
    echo "Available in $MODEL_DIR:" >&2
    ls "$MODEL_DIR"/*.gguf 2>/dev/null | sed 's|.*/|  |' >&2 || echo "  (none)" >&2
    exit 1
fi

if [[ ! -x "$LLAMA_BIN" ]]; then
    echo "llama-server not found or not executable: $LLAMA_BIN" >&2
    exit 1
fi

# Total context handed to llama-server. CTX_SIZE is per-slot (see the
# comment above the variable); llama.cpp divides this total back down by
# PARALLEL internally, so multiplying here is what makes CTX_SIZE actually
# mean "per slot" instead of "per slot only when PARALLEL happens to be 1".
TOTAL_CTX_SIZE=$((CTX_SIZE * PARALLEL))

# --- Banner so you know what's running ---
cat <<EOF
╭─────────────────────────────────────────────────────╮
│ llama-server starting                               │
├─────────────────────────────────────────────────────┤
│ model:   $MODEL_FILE
│ bind:    http://$HOST:$PORT
│ ctx:     $CTX_SIZE tokens/slot  x  $PARALLEL slot(s)  =  $TOTAL_CTX_SIZE total
│ layers:  $N_GPU_LAYERS (full GPU offload)
│ stop:    Ctrl-C
╰─────────────────────────────────────────────────────╯
EOF

exec "$LLAMA_BIN" \
    --model "$MODEL_PATH" \
    --host "$HOST" \
    --port "$PORT" \
    --ctx-size "$TOTAL_CTX_SIZE" \
    --n-gpu-layers "$N_GPU_LAYERS" \
    --threads "$THREADS" \
    --batch-size "$BATCH_SIZE" \
    --ubatch-size "$BATCH_SIZE" \
    --parallel "$PARALLEL" \
    --temp "$TEMP" \
    --top-p "$TOP_P" \
    --top-k "$TOP_K" \
    --min-p "$MIN_P" \
    --repeat-penalty "$REPEAT_PENALTY" \
    --seed "$SEED" \
    --reasoning "$REASONING" \
    --reasoning-format "$REASONING_FORMAT" \
    --reasoning-budget "$REASONING_BUDGET" \
    --jinja \
    --no-webui \
    --metrics \
    $EXTRA_ARGS
