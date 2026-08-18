#!/usr/bin/env bash
# scripts/run-qwen.sh
#
# Pinned to the 3090 (docs/ingest/gpu-assembly.md's assembly: a 24B-class
# model belongs on CUDA 0 / the 3090, port 8080). Without this, llama.cpp's
# default full-offload (--n-gpu-layers 999, no device limit) silently splits
# the model's layers across BOTH visible cards — costs ~22% throughput (the
# PCIe tax gpu-assembly.md measures) and runs both cards hot for one job's
# worth of work, discovered 2026-08-17 when a run left both GPUs at 84-87°C
# instead of one card carrying the load. CUDA_DEVICE_ORDER=PCI_BUS_ID is
# required alongside CUDA_VISIBLE_DEVICES — this rig's default FASTEST_FIRST
# ordering resolves CUDA 0 to the 4070, not the 3090 (see gpu-assembly.md's
# naming-trap section).
CUDA_DEVICE_ORDER="${CUDA_DEVICE_ORDER:-PCI_BUS_ID}" \
CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}" \
MODEL_DIR="$HOME/programs/qwen" \
exec "$(dirname "$0")/serve-llama.sh" "Qwen3.5-27B-UD-Q4_K_XL.gguf"
