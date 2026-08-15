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
#
# CTX_SIZE=16384 is PER SLOT (serve-llama.sh's comment above its own
# CTX_SIZE has the mechanics — llama.cpp divides --ctx-size by --parallel
# internally, so serve-llama.sh multiplies it back by PARALLEL before
# passing it on). This is the todo:dcb3cce5 fix: the previous effective
# per-slot figure was 8192 (32768 total / 4 slots, from serve-llama.sh's
# CTX_SIZE default meaning "total" pre-fix), and every chunk of the
# 2026-08-15 elish run truncated at exactly that boundary
# (n_tokens=8191, truncated=1) against a worst-case tagging prompt (largest
# corpus chunk + the 116-concept taxonomy) measured at ~7,600 tokens —
# leaving under 600 tokens for the JSON response, nowhere near enough.
# 16384 leaves ~8,800 tokens of generation headroom over that measured
# worst-case prompt: comfortably more than a tagging response realistically
# needs (a full-taxonomy JSON array is at most a few thousand tokens), while
# staying well short of LLM_MAX_TOKENS (24000 in tag_concepts.py — a
# defensive ceiling sized for a thinking model's reasoning preamble, not
# the typical response this model produces; requiring headroom for the full
# ceiling would roughly double this again for no measured benefit).
#
# This total (16384 * 4 = 65536) is double the previous 32768 total, so
# expect roughly double the previous KV-cache VRAM footprint on top of the
# ~2.3GB of weights (docs/ingest/gpu-assembly.md's table) — that GB figure
# is NOT measured for this new total (no GPU was used to write this
# comment); check `nvidia-smi --query-gpu=index,name,memory.used
# --format=csv,noheader` after starting the server and before assuming it
# fits alongside anything else on the same card.
CTX_SIZE=16384 \
PARALLEL=4 \
MODEL_DIR="/home/ivy/programs/guru/4b-v3" \
exec "$(dirname "$0")/serve-llama.sh" "qwen-3-4b-guru-v3-Q4_K_M.gguf"
