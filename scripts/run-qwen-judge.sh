#!/usr/bin/env bash
# scripts/run-qwen-judge.sh
#
# Serves Qwen3.8-27B for the D3 review gate — the local half of
# prompts/dossier/contracts/review-rubric.md. Pair with the node's own
# commands; this script starts a server, it is not an entrypoint:
#
#   scripts/run-qwen-judge.sh &
#   python3 scripts/run_contract.py prompts/dossier/contracts/review-rubric.md \
#       --provider llamacpp --model Qwen3.8-27B-UD-Q4_K_XL.gguf \
#       --budget 200000 \
#       --input stage_input=<file> --input output=<file> \
#       --var field=l1 --var work_label='...' --var prompt_version=l1-v3
#
# Then act on the verdict through D3's documented commands
# (review_dossiers.py accept/reject). Nothing here writes to guru.db.
#
# WHY A DEDICATED RUNNER, AND WHAT IT PINS
# A gate must be reproducible. llama.cpp's --seed defaults to -1, a fresh
# random seed PER REQUEST, so the same row judged twice can come back
# differently. MEASURED on this box, same model, same rows, two consecutive
# runs at the model-runners defaults:
#
#   s1639  reject -> accept
#   s1640  reject -> accept
#   s1641  reject -> accept
#
# Three of three flipped. SEED below is what fixes that.
#
# TEMP stays at the model card's 1.0 rather than serve-llama.sh's 0.2 default,
# and this is the non-obvious part. Lowering temperature looks like the
# reproducibility fix and is not: MEASURED at 0.2, the thinking pass rambles —
# 4,469 generated tokens and still going on a span that takes ~1,200 at 1.0 —
# exhausting the token budget before the verdict JSON is emitted. Six of six
# judgements returned no parseable verdict at 0.2. Qwen specifies temp 1.0 for
# thinking mode for exactly this reason. Reproducibility comes from pinning the
# SEED, not from flattening the distribution.
#
# REASONING_BUDGET=2048 is load-bearing, not tuning. Unbounded, the thinking
# pass consumes the caller's whole max_tokens and `content` comes back empty;
# llm.py then returns reasoning_content, so run_contract.py receives a
# paragraph of deliberation and reports "no parseable JSON". MEASURED: every
# call failed that way before this was set. 2048 leaves ~4k of a --max-tokens
# 6000 budget for the verdict object, which runs a few hundred tokens.
#
# MTP IS DELIBERATELY OFF, and this one is counter-intuitive enough to be
# worth the paragraph. Qwen3.8 ships a draft head in the GGUF and
# --spec-type draft-mtp is a free 62 tok/s against 38 — for generation. For a
# gate it is not free. Speculative decoding is distribution-preserving in
# theory, but it consumes the RNG differently, so at a FIXED seed it draws a
# different sample. MEASURED, same seed, same rows, MTP off then on:
#
#   s1639  reject GROUND  ->  PARSE-FAIL (reproducibly, both passes)
#   s1640  accept GROUND  ->  reject GROUND
#   s1641  reject GROUND  ->  accept
#
# Two of three verdicts changed and one stopped parsing at all. Both configs
# are internally reproducible; they simply do not agree with each other. A
# review gate answers to correctness before throughput, so the fast path is
# opt-in:
#   EXTRA_ARGS='--spec-type draft-mtp --spec-draft-n-max 2' scripts/run-qwen-judge.sh
# and if you take it, re-baseline — verdicts from an MTP server are not
# comparable to verdicts from this default.
#
# CTX_SIZE=32768. The rubric prompt is the stage input plus the output plus
# the ~3.5k-char rubric body; the largest c8 L1 stage input measured ~38k
# chars (~12k tokens), and run_contract.py's default --budget of 12000 CHARS
# elides the MIDDLE of anything longer. That elision is silent and it breaks
# the gate's whole premise: the rubric says "Never judge an output alone. If
# stage_input is missing, return insufficient-input" — a judge shown head and
# tail with a hole between them will mis-score COVERAGE in both directions.
# Pass --budget 200000 on the client side; 32768 tokens of context is what
# holds the result.
#
# MAX TOKENS is a CLIENT concern, not set here: the contract declares
# max_tokens=2048, which is too small for a thinking model — the reasoning
# pass alone can consume it and emit no verdict. Pass --max-tokens 6000.
#
# NOT A JUDGE OF ITS OWN WORK. Qwen3.8 accepted its own generated summaries at
# 91.4% against 80.6% for frontier-generated ones
# (docs/dossiers/c8-local-grader-bakeoff.md). That gap is consistent with
# self-preference and also with the frontier arm genuinely carrying more
# GROUND violations; the two are not separated by that data. Until they are,
# do not use this server to judge a campaign it also generated.
#
# KNOWN BLIND SPOT, shared with the frontier judge: COVERAGE. Every grader
# tested — opus-4-8, this model, and GLM-4.7-Flash — accepted a summary
# deliberately truncated to its first third. Proportion and ordering are what
# l1-v3 exists to enforce; this gate does not currently verify them, whoever
# runs it.
CTX_SIZE=32768 \
TEMP="${TEMP:-1.0}" \
TOP_P="${TOP_P:-0.95}" \
TOP_K="${TOP_K:-20}" \
MIN_P="${MIN_P:-0.0}" \
REPEAT_PENALTY="${REPEAT_PENALTY:-1.0}" \
SEED="${SEED:-20260816}" \
REASONING_BUDGET="${REASONING_BUDGET:-2048}" \
EXTRA_ARGS="${EXTRA_ARGS:-}" \
MODEL_DIR="$HOME/programs/qwen" \
exec "$(dirname "$0")/serve-llama.sh" "Qwen3.8-27B-UD-Q4_K_XL.gguf"
