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
# TEMP=0.6 and reasoning_effort=low, both measured, and the history here is
# worth keeping because the obvious reading was wrong twice.
#
# An earlier test at TEMP=0.2 produced 4,469 tokens of thinking and no verdict,
# 6 of 6 judgements returning nothing, and that was written up as "low
# temperature breaks thinking models". It was CONFOUNDED: that run had no
# reasoning budget set. Unbounded thinking consumes the caller's max_tokens on
# its own — see REASONING_BUDGET above — and temperature was never the cause.
#
# With the budget fixed at 2048, temperature is free to move. MEASURED over 6
# rows spanning both genres (3 long-prose, 3 logia), two passes each, all six
# carrying opus=accept as reference:
#
#   temp 1.0 / effort medium   6/6 deterministic   4/6 agree with opus   0 fails
#   temp 0.6 / effort low      6/6 deterministic   5/6 agree with opus   0 fails
#
# Same reproducibility, closer to the reference, no parse cost. 1.0 is the
# model card's CREATIVE setting and was never the right default for a gate;
# it survived here only because a confounded measurement had closed off the
# rest of the range.
#
# reasoning_effort is a prompt string with no enforcement — `low` injects "Keep
# your thinking brief and focused, moving directly to the conclusion without
# unnecessary elaboration". Against a 2048-token budget that nudges the model
# toward reaching the verdict before the cap, which is the failure mode that
# matters. It is set via LLAMA_ARG_CHAT_TEMPLATE_KWARGS because serve-llama.sh
# does not model chat-template kwargs and the env var needs no hook.
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
