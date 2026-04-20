#!/usr/bin/env bash
# scripts/run-qwen.sh
MODEL_DIR="$HOME/programs/qwen" exec "$(dirname "$0")/serve-llama.sh" "Qwen3.5-27B-UD-Q4_K_XL.gguf"
