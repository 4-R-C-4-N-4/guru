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
HOST="127.0.0.1"
PORT="8080"

# --- Model loading ---
CTX_SIZE="32768"
N_GPU_LAYERS="999"
THREADS="6"
BATCH_SIZE="512"

# --- Sampling defaults (overridable per-request from clients) ---
TEMP="0.2"
TOP_P="0.9"
TOP_K="40"
MIN_P="0.05"
REPEAT_PENALTY="1.05"

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

# --- Banner so you know what's running ---
cat <<EOF
╭─────────────────────────────────────────────────────╮
│ llama-server starting                               │
├─────────────────────────────────────────────────────┤
│ model:   $MODEL_FILE
│ bind:    http://$HOST:$PORT
│ ctx:     $CTX_SIZE tokens
│ layers:  $N_GPU_LAYERS (full GPU offload)
│ stop:    Ctrl-C
╰─────────────────────────────────────────────────────╯
EOF

exec "$LLAMA_BIN" \
    --model "$MODEL_PATH" \
    --host "$HOST" \
    --port "$PORT" \
    --ctx-size "$CTX_SIZE" \
    --n-gpu-layers "$N_GPU_LAYERS" \
    --threads "$THREADS" \
    --batch-size "$BATCH_SIZE" \
    --ubatch-size "$BATCH_SIZE" \
    --parallel 1 \
    --temp "$TEMP" \
    --top-p "$TOP_P" \
    --top-k "$TOP_K" \
    --min-p "$MIN_P" \
    --repeat-penalty "$REPEAT_PENALTY" \
    --jinja \
    --no-webui \
    --metrics
