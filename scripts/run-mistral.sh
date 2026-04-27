#!/usr/bin/env bash
# scripts/run-mistral.sh
#
# Mistral-Small-3.2-24B-Instruct-2506 (UD-Q5_K_XL).
# Sampling params follow Mistral's published recommendation for 3.2:
#   temp 0.15, top-p 1.0, top-k disabled, min-p disabled, no repeat penalty.
# These are server-side defaults; clients can still override per-request.
MODEL_DIR="$HOME/programs/mistral" \
TEMP="0.15" \
TOP_P="1.0" \
TOP_K="0" \
MIN_P="0.0" \
REPEAT_PENALTY="1.0" \
exec "$(dirname "$0")/serve-llama.sh" "Mistral-Small-3.2-24B-Instruct-2506-UD-Q5_K_XL.gguf"
