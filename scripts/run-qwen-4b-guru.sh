#!/usr/bin/env bash
# scripts/run-qwen-4b-guru.sh
#
# Serves the guru tagger model, vendored at
# /home/ivy/programs/guru/4b-v3/ (v3-r32 — see training-card.md and
# taxonomy.toml alongside the weights there for provenance; model home
# convention: ~/programs/guru/<name>-v<N>, docs/ingest/gpu-assembly.md).
# Pair with:
#   python3 scripts/tag_concepts.py --model qwen-3-4b-guru-v3-Q4_K_M.gguf ...
# so the model identifier recorded in staged_tags.model matches across
# server and client. The -v3- infix is deliberate, not cosmetic: v1/v2
# served "qwen-3-4b-guru-Q4_K_M.gguf" (no infix), and tag_concepts.py's
# same-model dedupe keys off this exact string — reusing the v1 identifier
# for v3 weights would make a genuinely different model's tags
# indistinguishable from v1's in the model column.
#
# This finetune is much leaner than the 27B teacher — small enough that
# the server can multiplex 4 concurrent requests without VRAM pressure.
# That lets multiple tag_concepts.py instances run in parallel against
# disjoint --tradition / --text scopes for a much faster bulk pass, or (as
# of todo:6950de58/0c34642e) a single tag_concepts.py --parallel 4 run.
#
# PARALLEL=4 here is the SERVER-side half of that --parallel; the two must
# be read together (todo:5955d038). tag_concepts.py's model guard also
# keys off this script's model id: it only allows --parallel N>1 for model
# ids starting with "qwen-3-4b-guru-", exactly what's served below —
# --parallel against the 27B teacher is refused unless overridden, because
# the teacher runs think-on and was never sized for concurrent requests.
PARALLEL=4 \
MODEL_DIR="/home/ivy/programs/guru/4b-v3" \
exec "$(dirname "$0")/serve-llama.sh" "qwen-3-4b-guru-v3-Q4_K_M.gguf"
