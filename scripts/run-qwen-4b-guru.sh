#!/usr/bin/env bash
# scripts/run-qwen-4b-guru.sh
#
# Serves the guru tagger model from the rellm finetune repo at
# /home/ivy/Work/rellm/out/qwen3-4b-guru/. Pair with:
#   python3 scripts/tag_concepts.py --model qwen-3-4b-guru ...
# so the model identifier recorded in staged_tags.model matches across
# server and client.
#
# This finetune is much leaner than the 27B teacher — small enough that
# the server can multiplex 4 concurrent requests without VRAM pressure.
# That lets multiple tag_concepts.py instances run in parallel against
# disjoint --tradition / --text scopes for a much faster bulk pass.
PARALLEL=4 \
MODEL_DIR="$HOME/Work/rellm/out/qwen3-4b-guru/gguf" \
exec "$(dirname "$0")/serve-llama.sh" "qwen-3-4b-guru-Q4_K_M.gguf"
