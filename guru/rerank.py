"""CPU cross-encoder relevance scoring for edge partner selection (EDGE_RERANK).

bge-reranker-v2-m3, zero-shot, mirrored exactly from rellm
tools/edge_scorer_rungs.py rung 2 — fp32, max_length 1024, batch 8, body
truncated to 2400 chars — so the threshold calibrated on the re-powered
judgment run (rellm runs/edges/relevance-judge/2026-08-12T18-14-23Z)
transfers: raw logit >= -3.8 is the top-11-of-108 operating point where kept
slots judged 63.6% strict-relevant vs the 65.2% baseline ceiling.

Lazy import: the pilot retriever stays torch-free unless the term is on.
CPU-only by construction, matching the measurement discipline (and the
GPU is not this pipeline's to take).
"""
from __future__ import annotations

import os
import time

# Latency of the most recent score_pairs call, for harnesses to read.
LAST: dict[str, float] = {}

_TOK = None
_MODEL = None


def _load():
    global _TOK, _MODEL
    if _MODEL is None:
        os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
        t0 = time.monotonic()
        import torch  # noqa: F401
        from transformers import (AutoModelForSequenceClassification,
                                  AutoTokenizer)
        # EDGE_RERANK_MODEL selects the scorer: default is the zero-shot
        # teacher; point it at a distilled student checkpoint dir for the
        # thin-scorer deployment (rellm thin-scorer-spec.md). The calibrated
        # EDGE_RERANK_THRESHOLD is model-specific — recalibrate when swapping.
        name = os.environ.get("EDGE_RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
        _TOK = AutoTokenizer.from_pretrained(name)
        _MODEL = AutoModelForSequenceClassification.from_pretrained(
            name, dtype="float32")
        _MODEL.eval()
        LAST["load_seconds"] = time.monotonic() - t0
    return _TOK, _MODEL


def score_pairs(query: str, bodies: dict[str, str]) -> dict[str, float]:
    """Raw reranker logits for (query, body) pairs, keyed like `bodies`."""
    if not bodies:
        return {}
    tok, model = _load()
    import torch
    # bge takes 1024; BERT-class students cap at their position table (512).
    max_len = min(1024, int(getattr(model.config,
                                    "max_position_embeddings", 1024)))
    ids = list(bodies)
    out: dict[str, float] = {}
    t0 = time.monotonic()
    with torch.no_grad():
        for i in range(0, len(ids), 8):
            batch = ids[i:i + 8]
            enc = tok([[query, bodies[j][:2400]] for j in batch],
                      padding=True, truncation=True, max_length=max_len,
                      return_tensors="pt")
            logits = model(**enc).logits.view(-1)
            for j, s in zip(batch, logits.tolist()):
                out[j] = s
    LAST.update(pairs=len(ids), seconds=time.monotonic() - t0)
    return out
