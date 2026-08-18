# c8 local L1 generation run

> **Naming note (2026-08-18).** `campaign_id = "c8"` below is this
> benchmark's own local identifier, frozen when it ran, and unrelated to the
> production campaign of the same name created independently on `main`
> afterward (four western_esoteric texts, `provider = "claude-code"`). This
> branch never modified the shared `config/dossiers.toml`, and the plan
> artifact is filed as `span-plan-c8-bench.*` to avoid colliding on disk with
> whatever the real c8 plan writes. The `"c8"` string inside that frozen JSON
> is left as generated — editing it would falsify the freeze record.

Phase 1 of the local-generator benchmark (todo:8c67ee44). Generates the LOCAL
arm for the 36 spans that already carry an accepted frontier `l1-v3` row, so
the two arms are paired on identical spans under an identical template.

## Configuration

| | |
|---|---|
| campaign | `c8`, plan hash `958afdef342af639` |
| provider / model | `llamacpp` / `Qwen3.8-27B-UD-Q4_K_XL.gguf` |
| server | llama.cpp, 3090 pinned (`LLM_GPUS=0`), ctx 24576, f16 KV |
| speculative | MTP `draft-mtp`, n-max 2, q8_0 draft cache |
| reasoning | `reasoning_effort=medium`, `--reasoning-budget 4096` |
| DB | snapshot `guru-20260816T192724Z-pre-c8-local-bench.db` (never the live DB) |

`--reasoning-budget` was set to 4096 deliberately: `generate_dossiers.py:264`
hardcodes `max_tokens=8192`, so a thinking budget at or near 8192 would consume
the entire allowance and emit an empty summary. 4096 leaves ~4k for the answer
against a ~300-token target.

Provenance was verified before generating — `/props` `model_path` basename was
checked equal to the configured `model` string, because llama-server ignores
the request-body `model` field and the column would otherwise record a label
for a model that never ran.

## Results

36 of 36 spans generated. **Zero log-skips** — no span exhausted `MAX_ATTEMPTS`.

| work | spans | calls | retries | wall |
|---|---|---|---|---|
| apocryphon-of-john | 3 | 4 | 1 | 4m16s |
| egyptian-heaven-and-hell | 11 | 20 | 9 | 24m10s |
| iamblichus-on-the-mysteries | 22 | 28 | 6 | 32m30s |
| **total** | **36** | **52** | **16** | **~61m** |

15 of 36 spans (42%) needed at least one retry; one needed two.

### The retries are almost entirely one failure

15 of 16 retries were `prose length N outside sanity band [120, 720]`, with N
from 727 to 1538. The remaining one was `prose starts mid-sentence
(lowercase)`. No echo-guard trips, no fence/format violations, no content
blocks.

The model overruns the length budget on first attempt and corrects when the
rejection is fed back (`_attempt` appends the reason to the prompt). So the
reject-retry loop is doing real work here — without it this run would have
produced malformed output at scale rather than a 42% retry rate.

### Length drift survives the retry

After correction, the local arm still runs consistently long:

| work | n | local avg | frontier avg | ratio |
|---|---|---|---|---|
| apocryphon-of-john | 3 | 440 | 331 | 1.21 |
| egyptian-heaven-and-hell | 11 | 526 | 457 | 1.16 |
| iamblichus-on-the-mysteries | 22 | 468 | 398 | 1.18 |
| **all** | **36** | **483.6** | **410.2** | **+17.7%** |

The consistency across three unrelated works (1.16–1.21) suggests a systematic
verbosity bias rather than per-work noise.

Note the validator enforces only the **sanity** band (`lo*0.5` to `hi*2`), not
the ±20% band the prompt asks for — `_v_prose` raises on `not (lo*0.5 <= n <=
hi*2)`. So a summary at +17.7% passes the contract silently. If this matters it
is a REVIEW finding (COVERAGE: disproportionate weighting), not a contract one.

## Throughput

~70 tok/s decode, ~85s per span. Pinning to the 3090 alone rather than letting
llama.cpp split across both cards measured 70.1–71.2 tok/s versus 48.3 tok/s
split — the PCIe hop per token is worth avoiding for a batch of this shape.

## What this run does NOT establish

Nothing about quality. Every local row is `pending`; none has been judged. The
rubric review (todo:fd16e2f9) is what decides whether the length drift and the
first-attempt overruns matter, and whether GROUND/LEAK moved in the predicted
direction. The fold path was not exercised (L1 only). No structured field was
generated.
