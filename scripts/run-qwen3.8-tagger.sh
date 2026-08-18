#!/usr/bin/env bash
# Pinned to the 3090 — same reasoning as run-qwen.sh (docs/ingest/gpu-assembly.md's
# assembly puts every 24B-class model on CUDA 0 / the 3090; unpinned, llama.cpp's
# full-offload silently splits across both cards, discovered 2026-08-17 running
# both GPUs hot for one job).
CUDA_DEVICE_ORDER="${CUDA_DEVICE_ORDER:-PCI_BUS_ID}" \
CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}" \
CTX_SIZE=24576 \
TEMP="${TEMP:-0.6}" \
TOP_P="${TOP_P:-0.95}" \
TOP_K="${TOP_K:-20}" \
MIN_P="${MIN_P:-0.0}" \
REPEAT_PENALTY="${REPEAT_PENALTY:-1.0}" \
SEED="${SEED:-20260816}" \
REASONING_BUDGET="${REASONING_BUDGET:-2048}" \
LLAMA_ARG_CHAT_TEMPLATE_KWARGS="${LLAMA_ARG_CHAT_TEMPLATE_KWARGS:-{\"reasoning_effort\":\"low\"}}" \
EXTRA_ARGS="${EXTRA_ARGS:-}" \
MODEL_DIR="$HOME/programs/qwen" \
exec "$(dirname "$0")/serve-llama.sh" "Qwen3.8-27B-UD-Q4_K_XL.gguf"
