#!/usr/bin/env bash
# scripts/run-qwen-generate.sh
#
# Serves Qwen3.8-27B for Pass D GENERATION (D2). Pair with:
#   python3 scripts/build_dossiers.py --generate --stage l1 [--work <id>]
# with config/dossiers.toml set to provider = "llamacpp" and
# model = "Qwen3.8-27B-UD-Q4_K_XL.gguf".
#
# SAME MODEL AS run-qwen-judge.sh, DIFFERENT CONFIGURATION. That is the point
# of having two files. Generation and review are different tasks with different
# failure modes, and a config tuned for one is not tuned for the other:
#
#   generation  fails by overrunning the length band -> retries, then log-skips
#   review      fails by not reaching the verdict     -> no parseable JSON
#
# Both are reproducible only if the sampler is pinned, so both pin SEED. Beyond
# that they diverge, and the divergence is measured, not assumed.
#
# WHAT THE DEFAULTS BUY, MEASURED
# 8 Dhammapada chapters (~1,540 tok/span of discrete verses), same spans, same
# seed, same reasoning budget — only TEMP and reasoning_effort differ. Frontier
# (claude-opus-4-8) shown as the target:
#
#   chapter   frontier   temp 1.0/medium   temp 0.6/low
#   I              380               554            585
#   II             142               148            158
#   III            191               300            251
#   IV             175               267            230
#   V              153          LOG-SKIP            210
#   VI             236               371            358
#   VII            240               308            262
#   VIII           178               248            212
#   ------------------------------------------------------
#   produced       8/8               7/8            8/8
#   vs frontier      —            +40.6%         +30.7%
#
# temp 0.6 is tighter on 6 of 7 comparable spans and RECOVERS chapter V, which
# at 1.0 exhausted all three attempts (387/320/309 against a [42,256] band) and
# produced nothing. Lower temperature tracks the prompt's length instruction
# more closely; that is the whole of the gain, and it is worth having.
#
# GRID-SEARCHED. temp {0.5,0.6,0.7} vs the shipped 1.0, budget fixed at 2048,
# same 8 chapters each. Comparing produced-count alone favors configs that skip
# the hard chapters, so ratio is computed on the 6 chapters every config
# actually produced (I,II,III,IV,VII,VIII):
#
#   temp 1.0   7/8 produced   +37.9%
#   temp 0.7   6/8 produced   +29.0%
#   temp 0.6   8/8 produced   +26.1%   <- wins BOTH axes, not a tradeoff
#   temp 0.5   6/8 produced   +34.6%
#
# 0.5 and 0.7 skip the identical two chapters (V, VI) that 0.6 alone resolves.
# temp=0.6 is a genuine local optimum in the tested range, not an arbitrary
# midpoint. Full table: docs/dossiers/c8-dhammapada-logia.md Addendum 3,
# c8-generate-temp-grid.txt.
#
# IT DOES NOT CLOSE THE GAP. Still +30.7% long, still retrying on most spans,
# against a frontier arm that cleared all 8 bands first try in 8 calls. The
# residual is the budget formula in generate_dossiers.py:
#   min(300, max(80, span_token_count // 12))
# which asks ~87 tokens of a 1,052-token chapter while l1-v3 simultaneously
# requires every figure named and every episode covered. The formula is not
# impossible — frontier meets it — it is calibrated to a terser generator. No
# sampler setting fixes a demand the instruction itself makes hard, so if the
# retry rate matters, change the formula, not this file.
#
# CTX_SIZE=24576 — a span up to ~6k tokens, the composed prompt, and
# generate_dossiers.py's hardcoded max_tokens=8192 of output.
#
# REASONING_BUDGET=2048 leaves ~6k of that 8192 for the summary itself. Unset,
# thinking can consume the whole allowance and llm.py returns reasoning_content
# instead of prose — see the note above REASONING_BUDGET in serve-llama.sh.
#
# MTP IS OFF, deliberately. It is a real speedup (70 tok/s against 38) and it
# is not output-neutral: at a FIXED seed, toggling it changed 2 of 3 verdicts in
# the review harness. Anything generated with it is not comparable to anything
# generated without it, which makes it the wrong default for a corpus whose rows
# carry a provenance column. Opt in for a throwaway bulk pass, never for a
# campaign you intend to compare:
#   EXTRA_ARGS='--spec-type draft-mtp --spec-draft-n-max 2' scripts/run-qwen-generate.sh
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
