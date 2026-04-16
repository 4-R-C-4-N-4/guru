# Guru Stage 4 Benchmark Results

## Environment
- Machine: Linux (Arch)
- GPU: NVIDIA GeForce RTX 4070 (11873 MiB VRAM)
- llama.cpp build: CUDA, version 8746 (0893f50f2)
- Corpus: 120 chunks (gospel-of-thomas × 114, sefer-yetirah × 6)

## Embedding Throughput

| Provider | Model | Throughput | Notes |
|---|---|---|---|
| ollama | nomic-embed-text (768-dim) | **~50 chunks/sec** | batch_size=32, GPU-accelerated |

Full corpus (120 chunks) embedded in ~2.4 seconds.
Estimated time for 5,000-chunk corpus at same rate: ~100 seconds.

## Retrieval Latency

Backend: ChromaDB PersistentClient, cosine similarity, 10 queries measured.

| Percentile | Latency |
|---|---|
| p50 | **1.1 ms** |
| p95 | **6.1 ms** |

Vector-only retrieval is well under the 10s end-to-end budget.

## LLM Inference (concept tagging / edge proposal)

| Provider | Model | Speed | Notes |
|---|---|---|---|
| ollama | qwen3:8b | ~30s/chunk | CPU-bound, unacceptable for full corpus |
| llama.cpp server | Carnice-27b-Q4_K_M | **~11s/chunk** | GPU, thinking model, correct JSON output |

llama.cpp direct (port 8080) is ~3× faster than Ollama for the same 27B model.
Thinking model adds ~200-400 reasoning tokens but produces higher-quality structured output.
Full 120-chunk tagging estimated at ~22 minutes.

## Stage 5 Budget Assessment

- Embedding a query: ~20ms (nomic-embed-text via Ollama)
- Vector retrieval (top-10): <2ms
- **Total retrieval path: well under 10s target**
- LLM inference (not included in 10s budget per spec): 11s/response on 27B
