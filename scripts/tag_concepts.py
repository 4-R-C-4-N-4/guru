"""
tag_concepts.py — Pass B of Stage 3: LLM-assisted concept tagging.

For each chunk in guru.db, asks an LLM to score it against every concept in
the taxonomy and writes results to staged_tags. --resume (skip chunks already
in tagging_progress) is ON by default, so re-runs only tag never-seen chunks
and won't redo or clobber prior work; pass --no-resume to re-tag everything.

Usage:
    python3 scripts/tag_concepts.py \\
        --provider ollama --model llama3 \\
        [--batch-size 10] [--no-resume] \\
        [--tradition gnosticism] [--text gospel-of-thomas]
"""

import argparse
import json
import logging
import sqlite3
import sys
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path

import tomllib

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from guru.corpus import resolve_chunk_path  # noqa: E402
from guru.prompt import PROMPT_VERSION  # noqa: E402

DEFAULT_DB = PROJECT_ROOT / "data" / "guru.db"
TAXONOMY_TOML = PROJECT_ROOT / "concepts" / "taxonomy.toml"

sys.path.insert(0, str(Path(__file__).parent))
from llm import (
    call_llm, parse_json_response, query_llamacpp_slots,
    query_llamacpp_slot_ctx, PROVIDERS,
)

# Sized for thinking models that write a reasoning preamble before the JSON
# answer. The Qwen3.5-27B teacher used 4-6k tokens just for the preamble on
# dense chunks; an earlier 6000 budget cut ~12% of chunks off mid-reasoning,
# which the pipeline could not distinguish from a legitimate empty result.
LLM_MAX_TOKENS = 24000

SYSTEM_PROMPT = """\
You are a comparative religion scholar helping to build a concept index of mystical texts.
For each passage given, score it against every concept definition provided.
Respond ONLY with a valid JSON array (no markdown, no commentary).
"""

# ── --parallel safety guards (todo:5955d038) ────────────────────────────────
#
# --parallel N>1 is scoped to the 4B finetune served by
# scripts/run-qwen-4b-guru.sh, which is small enough for the server to
# multiplex several requests without VRAM pressure (see that script's
# header). The 27B teacher (Qwen3.5-27B-UD-Q4_K_XL.gguf) runs think-on and
# is served with --parallel 1 by default; silently multiplexing it would
# contend multiple full-context reasoning passes for the same VRAM the
# single-request budget assumed. Three independent checks guard --parallel:
#
#   1. check_parallel_model_guard — refuses N>1 for any model id that
#      doesn't look like the finetune, unless explicitly overridden.
#   2. preflight_server_slots — refuses N>1 when the llama.cpp server
#      itself reports fewer slots than N, so a run doesn't silently queue
#      behind a 1-slot server while believing it's running N-wide. This
#      check alone validates a number that is sufficient by construction
#      once the server was launched with a matching PARALLEL — it exists to
#      catch a *mismatched* launch, not to size the run.
#   3. preflight_server_slots (same function) also refuses when the
#      server's PER-SLOT context is too small for a real tagging prompt —
#      the number that actually shrinks as slots rise (llama.cpp divides
#      total --ctx-size by slot count when kv_unified is false, the
#      default), and the one that silently truncated every chunk of the
#      2026-08-15 elish run at n_ctx_slot=8192 (todo:dcb3cce5). Slot count
#      being sufficient says nothing about this — a 4-slot server can still
#      serve 4 slots too small to hold one prompt.

FINETUNE_MODEL_PREFIX = "qwen-3-4b-guru-"

# The 2026-08-15 elish run's worst-case tagging prompt (largest corpus
# chunk + the full 116-concept taxonomy) was measured at ~7,600 tokens
# (todo:dcb3cce5). n_ctx_slot=8192 that day left under 600 tokens for the
# JSON response — nowhere near enough, which is exactly why every chunk
# truncated (`n_tokens = 8191, truncated = 1`) and parse_json_response's
# truncation repair silently produced partial tag lists instead of errors.
# 10,000 is that measured prompt figure plus ~2,400 tokens of generation
# headroom — not generous, just enough that a per-slot context below it is
# close to guaranteed to repeat the same failure on a dense chunk. This is
# deliberately far short of LLM_MAX_TOKENS (24000, the hard ceiling passed
# to the LLM call for pathological chunks) — requiring headroom for the
# full ceiling would flag every real-world server as "too small" by this
# check's own logic, which is not what happened in practice.
MIN_SAFE_SLOT_CTX_TOKENS = 10000


class ParallelModelNotAllowedError(RuntimeError):
    """--parallel N>1 was requested against a model outside the finetune
    convention this feature is scoped to, and no override was given."""


class InsufficientServerSlotsError(RuntimeError):
    """The llama.cpp server positively reports fewer slots than --parallel
    would submit concurrently against it."""


class InsufficientSlotContextError(RuntimeError):
    """The llama.cpp server positively reports a per-slot context smaller
    than MIN_SAFE_SLOT_CTX_TOKENS — the exact silent-truncation failure
    mode of todo:dcb3cce5, caught before any chunk is sent rather than
    discovered later as a partial, "successfully parsed" JSON array."""


class InvalidTaggingArgsError(RuntimeError):
    """A CLI argument combination that run_tagging can reject upfront,
    before touching the DB or the network, rather than surfacing as a
    confusing per-chunk failure or a raw traceback mid-run."""


def check_parallel_model_guard(
    model: str, parallel: int, allow_parallel_any_model: bool = False,
    n_endpoints: int = 1,
) -> None:
    """Refuse --parallel N>1 unless `model` matches the finetune naming
    convention (qwen-3-4b-guru-*, e.g. qwen-3-4b-guru-v3-Q4_K_M.gguf — the
    -vN- infix varies by training run, see run-qwen-4b-guru.sh's header).

    n_endpoints (default 1) is the number of --endpoint flags in play — the
    guard is judged against total concurrency (parallel * n_endpoints), not
    the raw --parallel value alone, since two endpoints at --parallel 1
    each is still 2-wide multiplexing. n_endpoints only affects the
    threshold and the error message's wording; the raw `parallel` value
    passed in is always what's reported back to the operator so the
    message matches the flag they actually typed.

    Total concurrency <=1 is always allowed — there's nothing to
    multiplex. Passing allow_parallel_any_model=True bypasses the check
    entirely; that's a deliberate owner override
    (--allow-parallel-any-model on the CLI), not something a default
    invocation should reach for by accident.
    """
    total_concurrency = parallel * n_endpoints
    if total_concurrency <= 1 or allow_parallel_any_model:
        return
    if model.startswith(FINETUNE_MODEL_PREFIX):
        return
    if n_endpoints > 1:
        scope = (
            f"--parallel {parallel} across {n_endpoints} --endpoint flag(s) "
            f"({total_concurrency} total concurrency)"
        )
    else:
        scope = f"--parallel {parallel}"
    raise ParallelModelNotAllowedError(
        f"{scope} is scoped to the 4B finetune "
        f"(model id starting with {FINETUNE_MODEL_PREFIX!r}), but --model is "
        f"{model!r}. The 27B teacher runs think-on and must not be silently "
        f"multiplexed — it is served with --parallel 1 for a reason. If you "
        f"really mean to fan this model out concurrently, pass "
        f"--allow-parallel-any-model to override deliberately."
    )


def preflight_server_slots(
    provider_name: str,
    parallel: int,
    base_url: str | None = None,
) -> None:
    """Before running a parallel pool against a llama.cpp server, check two
    independent numbers and refuse rather than let a broken config run
    unnoticed:

      1. Slot COUNT (query_llamacpp_slots, llm.py — GET /props
         total_slots/n_parallel, falling back to GET /slots) — refuses
         --parallel N against a server reporting fewer than N slots, so a
         run doesn't silently queue behind too few slots while believing
         it's N-wide.
      2. Per-slot CONTEXT (query_llamacpp_slot_ctx, llm.py — GET /props
         default_generation_settings.n_ctx) — refuses when that number is
         too small for a real tagging prompt (MIN_SAFE_SLOT_CTX_TOKENS).
         This is the check slot count *cannot* substitute for: total_slots
         >= parallel is satisfied by construction once the server was
         launched with a matching PARALLEL, but per-slot context SHRINKS
         as slots rise (llama.cpp divides --ctx-size by slot count), and a
         4-slot server passing check 1 can still serve 4 slots too small
         to hold one prompt — exactly what silently truncated every chunk
         of the 2026-08-15 elish run (todo:dcb3cce5).

    Both degrade gracefully by design: each only refuses when the server
    *positively* reports a too-low number. An unreachable server, an older
    build without /props or /slots, or an unparseable response all come
    back as None from the respective query function — those cases log a
    warning and continue rather than hard-failing, because they mean "we
    don't know", not "the server is under-provisioned". Skipped entirely
    for providers other than llamacpp, which have no slot concept, and for
    --parallel <= 1, where n_ctx_seq == n_ctx (nothing is divided) so
    neither number can be the problem.
    """
    if parallel <= 1 or provider_name != "llamacpp":
        return

    resolved = base_url or "LLAMACPP_BASE_URL (env default)"

    slots = query_llamacpp_slots(base_url=base_url)

    if slots is None:
        logger.warning(
            f"--parallel slot pre-flight: could not determine the slot count "
            f"of the llama.cpp server at {resolved} (older build, --slots "
            f"disabled, or an unrecognized response shape). Continuing "
            f"without the check — verify manually that the server was "
            f"started with --parallel >= {parallel}."
        )
    elif slots < parallel:
        raise InsufficientServerSlotsError(
            f"--parallel {parallel} exceeds the {slots} slot(s) the server "
            f"at {resolved} actually reports. Requests beyond {slots} would "
            f"queue behind it serially while the run believes it's {parallel}-"
            f"wide. Lower --parallel to <= {slots}, or restart the server "
            f"with a higher PARALLEL (scripts/serve-llama.sh / "
            f"run-qwen-4b-guru.sh — the client --parallel and server "
            f"PARALLEL are two halves of one setting)."
        )
    else:
        logger.info(
            f"--parallel slot pre-flight: server at {resolved} reports "
            f"{slots} slot(s) — OK for --parallel {parallel}."
        )

    slot_ctx = query_llamacpp_slot_ctx(base_url=base_url)

    if slot_ctx is None:
        logger.warning(
            f"--parallel slot pre-flight: could not determine the per-slot "
            f"context of the llama.cpp server at {resolved} "
            f"(default_generation_settings.n_ctx missing from /props — "
            f"older build or unrecognized response shape). Continuing "
            f"without the check — this is the number that silently "
            f"truncated every chunk of the 2026-08-15 elish run "
            f"(todo:dcb3cce5), so verify manually: the server's startup "
            f"banner logs n_ctx_slot, and slot-release log lines show "
            f"truncated = 1 when a request actually hit the wall."
        )
    elif slot_ctx < MIN_SAFE_SLOT_CTX_TOKENS:
        raise InsufficientSlotContextError(
            f"--parallel {parallel} against the server at {resolved} "
            f"leaves each slot only {slot_ctx} tokens of context — below "
            f"the {MIN_SAFE_SLOT_CTX_TOKENS}-token floor "
            f"(todo:dcb3cce5's worst-case tagging prompt measured ~7,600 "
            f"tokens; {slot_ctx} tokens is not enough headroom for prompt "
            f"+ a real generation budget and will likely truncate mid-JSON "
            f"exactly as the 2026-08-15 elish run did, silently, since the "
            f"truncation repair in parse_json_response doesn't raise. Raise "
            f"the server's per-slot CTX_SIZE (scripts/serve-llama.sh — "
            f"CTX_SIZE is now PER SLOT; total context served is "
            f"CTX_SIZE * PARALLEL) or lower --parallel to fit within the "
            f"context you're currently serving."
        )
    else:
        logger.info(
            f"--parallel slot pre-flight: server at {resolved} reports "
            f"{slot_ctx} tokens of per-slot context — OK "
            f"(>= {MIN_SAFE_SLOT_CTX_TOKENS})."
        )


def build_prompt(chunk_body: str, chunk_citation: str, concepts: list[dict],
                 max_body_chars: int | None = None) -> str:
    """Build the per-chunk concept-scoring prompt.

    chunk_body is passed through unmodified by default — the chunker
    enforces the token budget at chunk creation time and downstream
    prompts trust that contract. max_body_chars is an optional cap for
    operators running against a smaller-context model; 0/None = unlimited.

    Concepts are rendered as a flat list (prompt version v1). The grouped
    domain→family variant (design.md §8) was benched and regressed agreement-
    with-review (docs/concept-hierarchy/bench-v1-vs-v2.md), so tagging stays
    concept-driven; the concept hierarchy is a separate retrieval/structure
    layer that does not touch this prompt.
    """
    body = chunk_body if not max_body_chars else chunk_body[:max_body_chars]
    concepts_block = "\n".join(
        f'  {{"id": "{c["id"]}", "definition": "{c["definition"]}"}}'
        for c in concepts
    )
    return f"""\
Passage ({chunk_citation}):
\"\"\"
{body}
\"\"\"

Rate each concept 0-3 for how strongly this passage expresses it:
  0 = not present
  1 = peripherally present
  2 = clearly present
  3 = central theme

Concepts:
[
{concepts_block}
]

Return a JSON array of objects for every concept with score >= 1:
[
  {{
    "concept_id": "<id from list above OR a new snake_case id>",
    "score": <0-3>,
    "justification": "<one sentence>",
    "is_new_concept": <true if not in list>,
    "new_concept_def": "<definition if is_new_concept else null>"
  }}
]

Return [] if nothing scores >= 1. Output only the JSON array. No preamble, no explanation, no markdown fences. Start your response with [ and end with ]. Return [] if nothing scores >= 1.
"""


# ── parsing ───────────────────────────────────────────────────────────────────

def parse_tags(raw: str) -> list[dict]:
    """Parse LLM JSON response into list of tag dicts."""
    parsed = parse_json_response(raw)

    if isinstance(parsed, dict):
        for key in ("tags", "results", "concepts", "items"):
            if key in parsed:
                parsed = parsed[key]
                break
        else:
            parsed = list(parsed.values())[0] if parsed else []

    if not isinstance(parsed, list):
        return []

    tags = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        score = int(item.get("score", 0))
        if score < 1:
            continue
        tags.append({
            "concept_id": str(item.get("concept_id", "")),
            "score": score,
            "justification": str(item.get("justification", "")),
            "is_new_concept": bool(item.get("is_new_concept", False)),
            "new_concept_def": item.get("new_concept_def"),
        })
    return tags


# ── main logic ───────────────────────────────────────────────────────────────

def load_taxonomy() -> list[dict]:
    """Return [{id, definition, node_id}] for every concept in the taxonomy.

    Walks the three-tier ``[concepts.DOMAIN.FAMILY]`` tree (design.md §6) to any
    depth and collects leaf-string definitions. Family/domain context is
    deliberately NOT included: tagging is concept-driven on the flat v1 prompt;
    the concept hierarchy is a separate retrieval/structure layer (see
    docs/concept-hierarchy/bench-v1-vs-v2.md for why the grouped v2 prompt was
    not adopted).
    """
    with open(TAXONOMY_TOML, "rb") as f:
        data = tomllib.load(f)
    concepts: list[dict] = []

    def _collect(node: dict) -> None:
        for key, val in node.items():
            if isinstance(val, dict):
                _collect(val)
            elif isinstance(val, str):
                concepts.append({
                    "id": key,
                    "definition": val,
                    "node_id": f"concept.{key}",
                })

    _collect(data.get("concepts", {}))
    return concepts


def read_chunk_ids_file(path: Path) -> list[str]:
    """Parse a newline-delimited chunk-ids file.

    Strips whitespace, drops blank lines and '#' comments, preserves order,
    de-dupes while preserving first occurrence. Used by --chunk-ids-from-file
    to drive recovery runs against a hand-curated list.
    """
    seen: set[str] = set()
    out: list[str] = []
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line in seen:
            continue
        seen.add(line)
        out.append(line)
    return out


def apparatus_chunk_ids(conn: sqlite3.Connection) -> set[str]:
    """chunk ids flagged as whole-chunk apparatus (todo:495577b7).

    Gated on status='apparatus' only, the owner-applied terminal state —
    never 'pending', which is queue-only and not a fact yet. Mirrors
    scripts/derive_parallels.py::load_apparatus_chunks so both consulters
    of the flag apply the identical rule.
    """
    return {r[0] for r in conn.execute(
        "SELECT chunk_id FROM staged_cleanups WHERE status = 'apparatus'"
    )}


def get_chunks(conn: sqlite3.Connection,
               tradition: str | None,
               text_id: str | None,
               resume: bool,
               chunk_ids: list[str] | None = None) -> list[dict]:
    """Load chunk rows for tagging.

    If chunk_ids is provided, fetches exactly those chunks (in the order given)
    and ignores tradition/text_id/resume. Missing IDs are logged and skipped.
    Otherwise, the tradition/text_id/resume filters apply as before.

    Chunks flagged apparatus (status='apparatus' in staged_cleanups,
    todo:495577b7) are excluded from both paths — proposing new tags on a
    chunk the owner has already confirmed is editorial apparatus just
    refills a queue that review will reject again.
    """
    apparatus = apparatus_chunk_ids(conn)

    if chunk_ids:
        placeholders = ",".join("?" * len(chunk_ids))
        rows = conn.execute(
            f"SELECT id, label, metadata_json FROM nodes "
            f"WHERE type = 'chunk' AND id IN ({placeholders})",
            chunk_ids,
        ).fetchall()
        by_id = {r[0]: r for r in rows}
        missing = [cid for cid in chunk_ids if cid not in by_id]
        if missing:
            logger.warning(
                f"--chunk-ids-from-file: {len(missing)} ID(s) not found in DB; skipping. "
                f"First few: {missing[:5]}"
            )
        flagged = [cid for cid in chunk_ids if cid in by_id and cid in apparatus]
        if flagged:
            logger.warning(
                f"--chunk-ids-from-file: {len(flagged)} ID(s) flagged apparatus; skipping. "
                f"First few: {flagged[:5]}"
            )
        return [
            {"id": by_id[cid][0], "label": by_id[cid][1], "meta": json.loads(by_id[cid][2])}
            for cid in chunk_ids if cid in by_id and cid not in apparatus
        ]

    sql = """
        SELECT n.id, n.label, n.metadata_json
        FROM nodes n
        WHERE n.type = 'chunk'
          AND n.id NOT IN (SELECT chunk_id FROM staged_cleanups WHERE status = 'apparatus')
    """
    params: list = []

    if tradition:
        sql += " AND n.tradition_id = ?"
        params.append(tradition)

    if text_id:
        sql += " AND json_extract(n.metadata_json, '$.text_id') = ?"
        params.append(text_id)

    if resume:
        sql += " AND n.id NOT IN (SELECT chunk_id FROM tagging_progress)"

    sql += " ORDER BY n.id"
    rows = conn.execute(sql, params).fetchall()
    return [{"id": r[0], "label": r[1], "meta": json.loads(r[2])} for r in rows]


def upsert_staged_tag(
    conn: sqlite3.Connection,
    chunk_id: str,
    tag: dict,
    model: str,
    prompt_version: str = PROMPT_VERSION,
    respect_reviewed: bool = False,
    supersede_pending: bool = False,
) -> str:
    """Insert a staged_tag with provenance.

    With the partial UNIQUE on (chunk_id, concept_id, model, prompt_version)
    WHERE status='pending', re-running this for the same chunk under the
    same provenance is a no-op via ON CONFLICT DO NOTHING. Re-tagging
    under a *different* model/prompt_version produces a separate row,
    distinguishable by provenance — that's intentional, the bench
    harness/training-data export filters on these columns.

    Policy flags for re-runs against an expanded taxonomy:
      respect_reviewed — if a prior row for (chunk_id, concept_id, model)
        has status != 'pending', skip this insert. The human verdict is
        authoritative; the teacher's alternate score on the same cell is
        noise. Scope is same-model: a different model deserves a fresh look.
      supersede_pending — if a prior pending row exists for
        (chunk_id, concept_id, model), delete it inside the same
        transaction before inserting. Latest-pending wins; the reviewer
        never sees two competing pending rows for the same cell.

    Returns one of:
      'skipped_reviewed' — respect_reviewed matched a prior non-pending row
      'superseded'       — supersede_pending deleted a prior pending row
                           and the new row was inserted
      'inserted'         — fresh insert, no prior pending row
      'conflict'         — ON CONFLICT DO NOTHING swallowed the insert
                           (same provenance, pending, not superseded)
    """
    concept_id = tag["concept_id"]

    if respect_reviewed:
        reviewed = conn.execute(
            """SELECT 1 FROM staged_tags
                   WHERE chunk_id = ? AND concept_id = ? AND model = ?
                     AND status != 'pending'
                   LIMIT 1""",
            (chunk_id, concept_id, model),
        ).fetchone()
        if reviewed is not None:
            return "skipped_reviewed"

    superseded = False
    if supersede_pending:
        cur = conn.execute(
            """DELETE FROM staged_tags
                   WHERE chunk_id = ? AND concept_id = ? AND model = ?
                     AND status = 'pending'""",
            (chunk_id, concept_id, model),
        )
        superseded = cur.rowcount > 0

    cur = conn.execute(
        """INSERT INTO staged_tags
               (chunk_id, concept_id, score, justification, is_new_concept,
                new_concept_def, model, prompt_version)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT DO NOTHING""",
        (
            chunk_id,
            concept_id,
            tag["score"],
            tag["justification"],
            1 if tag["is_new_concept"] else 0,
            tag.get("new_concept_def"),
            model,
            prompt_version,
        ),
    )
    if cur.rowcount == 0:
        return "conflict"
    return "superseded" if superseded else "inserted"


def mark_complete(conn: sqlite3.Connection, chunk_id: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO tagging_progress(chunk_id) VALUES(?)",
        (chunk_id,),
    )


# ── pure per-chunk work ──────────────────────────────────────────────────────


@dataclass
class ChunkTagResult:
    """Outcome of tagging one chunk, with no DB side effects.

    On success `tags` holds the parsed list (possibly empty — a legitimate
    "nothing scored >= 1" result) and `error` is None. On failure `tags` is
    `[]` and `error` carries the exception instead of it propagating, so a
    caller iterating many chunks (serially or via a thread pool) can treat
    every chunk uniformly and decide error handling in one place.
    """

    chunk_id: str
    tags: list[dict] = field(default_factory=list)
    error: BaseException | None = None


def tag_one_chunk(
    chunk: dict,
    concepts: list[dict],
    provider_name: str,
    model: str,
    max_body_chars: int | None = None,
    base_url: str | None = None,
) -> ChunkTagResult:
    """Do the slow, DB-free part of tagging one chunk: resolve its body,
    build the prompt, call the LLM, and parse the response.

    Touches no sqlite connection and never raises — any exception (missing
    chunk file, malformed TOML, LLM/network error) is caught and returned on
    the result's `error` field instead. That makes this function safe to call
    from multiple threads and safe to drive from a ThreadPoolExecutor: a
    failure in one call can never take down a caller that's mid-iteration
    over others. call_llm's provider functions (llm.py) are stateless — each
    call opens its own urllib/SDK request with no shared client object — so
    concurrent calls from separate threads don't share mutable state.

    base_url, when given, targets this one call at a specific llama.cpp
    server instead of the process-global LLAMACPP_BASE_URL env default
    (todo:d267201a multi-endpoint fan-out). It's threaded through as a real
    argument — never an env mutation — precisely so concurrent calls from
    different worker threads can each target a different server without
    racing each other over shared process state.
    """
    chunk_id = chunk["id"]
    try:
        chunk_file = resolve_chunk_path(chunk_id)
        if chunk_file is not None:
            with open(chunk_file, "rb") as f:
                cd = tomllib.load(f)
            body = cd["content"]["body"]
        else:
            body = chunk["label"]

        citation = chunk["label"]
        prompt = build_prompt(body, citation, concepts, max_body_chars=max_body_chars)

        # base_url is only added to the call when set, mirroring
        # llm.call_llm's own "don't forward unless given" rule — so a
        # single-endpoint run (base_url=None, the default) calls call_llm
        # with exactly the same arguments it always has, and any caller or
        # test double built against the pre-multi-endpoint signature is
        # unaffected.
        call_kwargs = {"max_tokens": LLM_MAX_TOKENS}
        if base_url is not None:
            call_kwargs["base_url"] = base_url
        raw = call_llm(provider_name, model, SYSTEM_PROMPT, prompt, **call_kwargs)
        tags = parse_tags(raw)
        return ChunkTagResult(chunk_id=chunk_id, tags=tags)
    except Exception as e:
        return ChunkTagResult(chunk_id=chunk_id, error=e)


# ── DB writer (single-threaded owner of the connection) ─────────────────────


def apply_chunk_result(
    conn: sqlite3.Connection,
    result: ChunkTagResult,
    model: str,
    respect_reviewed: bool,
    supersede_pending: bool,
    outcomes: dict[str, int],
) -> None:
    """Apply one ChunkTagResult's writes: upsert every tag, mark the chunk
    complete, and commit. The only function in this module that mutates the
    DB for a tagging pass (besides mark_complete/upsert_staged_tag it calls).
    Must only ever be called from the thread that owns `conn`.
    """
    for tag in result.tags:
        outcome = upsert_staged_tag(
            conn, result.chunk_id, tag, model=model,
            respect_reviewed=respect_reviewed,
            supersede_pending=supersede_pending,
        )
        outcomes[outcome] = outcomes.get(outcome, 0) + 1

    mark_complete(conn, result.chunk_id)
    conn.commit()


def _apply_chunk_result_safe(
    conn: sqlite3.Connection,
    result: ChunkTagResult,
    model: str,
    respect_reviewed: bool,
    supersede_pending: bool,
    outcomes: dict[str, int],
) -> BaseException | None:
    """apply_chunk_result, with the DB write isolated the same way
    tag_one_chunk already isolates the LLM call: any exception (e.g. a
    sqlite3.IntegrityError from an out-of-range score parse_tags didn't
    catch — schema's CHECK(score BETWEEN 0 AND 3)) is caught and returned
    instead of propagating, so one bad chunk can't crash a multi-thousand-
    chunk run. Rolls back first so a partially-applied chunk's writes never
    linger in an open transaction; mark_complete is never reached for that
    chunk, so --resume retries it on the next run.
    """
    # outcomes is snapshotted before the attempt and restored verbatim on
    # failure. apply_chunk_result increments it per tag AS it inserts, in
    # the same loop that can raise partway through (e.g. tag 3 of 5 hits
    # the CHECK(score BETWEEN 0 AND 3) constraint) — without the snapshot,
    # tags 1-2's increments would survive conn.rollback() discarding their
    # rows, so outcomes would count inserts the DB no longer has
    # (todo:dcb3cce5 finding 4). Restoring the snapshot on any exception
    # keeps outcomes exactly in sync with what's actually committed; on
    # success the snapshot is simply discarded, since apply_chunk_result
    # already wrote the post-attempt values into outcomes directly.
    snapshot = dict(outcomes)
    try:
        apply_chunk_result(conn, result, model, respect_reviewed, supersede_pending, outcomes)
        return None
    except Exception as e:
        conn.rollback()
        outcomes.clear()
        outcomes.update(snapshot)
        return e


# Bounded submission for --parallel: keep at most this many futures in
# flight per worker thread. Submitting all chunks up front would let the
# work queue (and its held prompt/response strings) grow unboundedly ahead
# of what N workers can consume, and would queue far more requests at the
# llama.cpp server than it has slots for. 2x is a conservative cushion — a
# worker always has a next request ready the instant it frees up, without
# piling up thousands of pending futures on a multi-thousand-chunk run.
PARALLEL_INFLIGHT_MULTIPLIER = 2


def _tag_one_chunk_then_delay(
    chunk: dict,
    concepts: list[dict],
    provider_name: str,
    model: str,
    max_body_chars: int | None,
    delay: float,
    base_url: str | None = None,
) -> ChunkTagResult:
    """Worker-thread entry point for --parallel > 1: run the pure per-chunk
    work, then (--delay semantics for N>1, decided here) sleep on THIS
    worker thread before it's free to pick up its next chunk.

    --delay is a politeness throttle on how fast one lane hits the server,
    not a global rate limit across all lanes — with N workers each sleeping
    `delay` between their own calls, aggregate request rate scales with N,
    same as running N separate serial processes with --delay would. A
    global limiter (one shared sleep gate) was rejected: it would make
    --parallel N behave like --parallel 1 throughput-wise whenever delay>0,
    defeating the point of the flag.

    base_url pins this one call to a specific endpoint (todo:d267201a); see
    tag_one_chunk's docstring for why it's a parameter and not an env write.
    """
    result = tag_one_chunk(chunk, concepts, provider_name, model,
                           max_body_chars=max_body_chars, base_url=base_url)
    if delay > 0:
        time.sleep(delay)
    return result


def _run_parallel_pool(
    conn: sqlite3.Connection,
    chunks: list[dict],
    concepts: list[dict],
    provider_name: str,
    model: str,
    max_body_chars: int | None,
    delay: float,
    parallel: int,
    batch_size: int,
    respect_reviewed: bool,
    supersede_pending: bool,
    outcomes: dict[str, int],
    endpoints: list[str] | None = None,
) -> tuple[int, int]:
    """--parallel > 1 path: a bounded ThreadPoolExecutor per endpoint runs
    tag_one_chunk (DB-free, thread-safe — see its docstring) across up to
    `parallel` worker threads *per endpoint*. This function's own caller's
    thread is the only thread that ever touches `conn`: regardless of how
    many endpoints/executors are feeding it, it consumes completed futures
    one at a time and drives apply_chunk_result, so every write stays
    single-threaded despite the LLM calls that produced the data running
    concurrently across one or several servers (todo:d267201a — the
    single-writer invariant from todo:0c34642e is unchanged; only where the
    LLM call goes varies, never who writes to sqlite).

    endpoints=None (the default — no --endpoint given) reproduces today's
    behaviour exactly: one implicit endpoint whose calls pass base_url=None
    through to call_llm, i.e. the ordinary LLAMACPP_BASE_URL env
    resolution. --parallel means exactly what it always has: total worker
    threads.

    endpoints=[url, ...] (one or more, from repeated --endpoint) round-robins
    chunks across them by list position — chunk i is pinned to
    endpoints[i % len(endpoints)] for its entire lifetime, from first
    submission to completion, never migrating to another endpoint's queue.
    Each endpoint gets its OWN ThreadPoolExecutor sized to `parallel`, so
    --parallel is interpreted PER ENDPOINT here: total concurrency across
    the run is parallel * len(endpoints). Two reasons this beats treating
    --parallel as a shared total split across endpoints: (1) it keeps the
    single-endpoint case's meaning of --parallel completely unchanged — one
    endpoint's "per-endpoint" pool of `parallel` workers *is* the total, so
    a one-endpoint --endpoint run behaves identically to no --endpoint at
    all; (2) it's what the todo:5955d038 per-endpoint slot pre-flight
    actually checks — each endpoint was pre-flighted for `parallel` slots,
    so a dedicated `parallel`-sized executor per endpoint is a structural
    guarantee that no endpoint ever sees more than `parallel` concurrent
    requests, rather than a probabilistic one a single shared pool with
    per-task endpoint tagging could not promise (a shared pool's threads
    don't otherwise know or care which endpoint a queued task targets, so a
    slow endpoint's tasks could pile up occupying more than `parallel`
    threads at once — exactly the silent-non-parallelism failure mode this
    whole feature exists to avoid).

    Completion order is nondeterministic (whichever chunk's LLM call
    finishes first, on whichever endpoint), so progress is reported as
    "N/total completions" — counting how many chunks have finished, not the
    chunks' original list position — unlike the serial path's index-based
    log line.
    """
    resolved_endpoints: list[str | None] = list(endpoints) if endpoints else [None]
    n_endpoints = len(resolved_endpoints)
    total = len(chunks)
    max_in_flight_per_endpoint = parallel * PARALLEL_INFLIGHT_MULTIPLIER

    # Round-robin split by list position: bucket[e] is the ordered sub-list
    # of chunks pinned to resolved_endpoints[e] for their whole lifetime.
    buckets: list[list[dict]] = [[] for _ in range(n_endpoints)]
    for i, chunk in enumerate(chunks):
        buckets[i % n_endpoints].append(chunk)
    bucket_pos = [0] * n_endpoints

    pending: set[Future] = set()
    fut_endpoint_idx: dict[Future, int] = {}
    tagged = errors = completed = 0

    # Plain list, not an ExitStack — see the try/except/finally below for
    # why: a KeyboardInterrupt needs to shut these down with
    # cancel_futures=True *before* anything waits on them, and an ExitStack
    # would run each executor's default __exit__ (shutdown(wait=True), no
    # cancel_futures) on the way out regardless of what we do inside,
    # re-introducing the exact hang this is fixing (todo:dcb3cce5 finding 5).
    executors = [ThreadPoolExecutor(max_workers=parallel) for _ in range(n_endpoints)]

    def submit_next(e: int) -> bool:
        pos = bucket_pos[e]
        bucket = buckets[e]
        if pos >= len(bucket):
            return False
        bucket_pos[e] += 1
        # Mirror the serial path's "no trailing sleep after the last
        # unit of work" rule. Which physical worker thread ends up
        # idle last isn't knowable ahead of time (ThreadPoolExecutor
        # hands queued futures to whichever thread frees up next), but
        # the final `parallel`-sized wave of a lane's bucket is exactly
        # the set of submissions that — once done — have no next chunk
        # to submit (submit_next returns False for them): whichever
        # thread finishes one of those is done sleeping for nothing.
        # Skipping --delay for that whole tail wave, not just the
        # single last chunk, is what actually eliminates the wasted
        # sleep the unconditional version paid on every worker's exit.
        is_tail_wave = pos >= len(bucket) - parallel
        fut = executors[e].submit(
            _tag_one_chunk_then_delay, bucket[pos], concepts, provider_name,
            model, max_body_chars, 0.0 if is_tail_wave else delay,
            resolved_endpoints[e],
        )
        pending.add(fut)
        fut_endpoint_idx[fut] = e
        return True

    try:
        for e in range(n_endpoints):
            for _ in range(max_in_flight_per_endpoint):
                if not submit_next(e):
                    break

        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for fut in done:
                e = fut_endpoint_idx.pop(fut)
                try:
                    result = fut.result()
                except Exception as ex:
                    # Defensive: tag_one_chunk already catches everything it
                    # can (see its docstring), but a future can also fail
                    # for reasons outside that function (e.g. the executor
                    # itself). Either way, one bad chunk must not take down
                    # the run or the other in-flight results. KeyboardInterrupt
                    # is a BaseException, not an Exception, so it deliberately
                    # does NOT match here — it falls through to the except
                    # clause below instead.
                    result = ChunkTagResult(chunk_id="<unknown>", error=ex)

                completed += 1
                if result.error is not None:
                    logger.error(f"  [{completed}/{total}] {result.chunk_id} FAILED: {result.error}")
                    errors += 1
                else:
                    write_error = _apply_chunk_result_safe(
                        conn, result, model, respect_reviewed, supersede_pending, outcomes
                    )
                    if write_error is not None:
                        logger.error(f"  [{completed}/{total}] {result.chunk_id} DB WRITE FAILED: {write_error}")
                        errors += 1
                    else:
                        tagged += 1
                        logger.info(f"  [{completed}/{total}] {result.chunk_id}: {len(result.tags)} tags")

                if batch_size and completed % batch_size == 0:
                    logger.info(f"Batch {completed//batch_size} complete ({tagged} tagged, {errors} errors)")

                submit_next(e)
    except KeyboardInterrupt:
        # A KeyboardInterrupt here can arrive from two places: the main
        # thread blocked inside wait() above (the common real-world case —
        # an operator's Ctrl-C during the idle stretch between
        # completions), or re-raised from fut.result() when a worker itself
        # observed one. Either way, the old behaviour (bare ExitStack)
        # would let this propagate straight into each executor's
        # shutdown(wait=True): every already-queued-but-not-started chunk
        # would still run, and any chunk mid-flight could hold the whole
        # process up to DEFAULT_HTTP_TIMEOUT (1200s, llm.py) before the
        # process actually exited. Shut down promptly instead: cancel every
        # future that hasn't started, and don't wait on the ones that have
        # — a thread already inside call_llamacpp can't be force-killed
        # (Python has no API for that), but this call no longer blocks on
        # it. Chunks already committed by apply_chunk_result before the
        # interrupt are unaffected (each chunk commits its own transaction
        # — see apply_chunk_result's docstring), so --resume picks the run
        # back up from here without redoing or losing anything.
        logger.warning(
            "Ctrl-C: stopping the parallel pool. Cancelling every "
            "queued-but-not-yet-started chunk; chunks already committed "
            "before the interrupt are safe and --resume will skip them."
        )
        for ex in executors:
            ex.shutdown(wait=False, cancel_futures=True)
        raise
    finally:
        # Always release the thread pools. On the normal-completion path
        # `pending` is already empty here, so this has nothing left to wait
        # on and returns immediately. On the KeyboardInterrupt path the
        # except clause above already requested cancellation; this second
        # call is the ordinary (non-cancelling) shutdown and is safe to
        # call again — ThreadPoolExecutor.shutdown() is idempotent.
        for ex in executors:
            ex.shutdown(wait=False)

    return tagged, errors


def run_tagging(
    db_path: Path,
    provider_name: str,
    model: str,
    batch_size: int,
    resume: bool,
    tradition: str | None,
    text_id: str | None,
    delay: float,
    max_body_chars: int | None = None,
    respect_reviewed: bool = True,
    supersede_pending: bool = True,
    chunk_ids: list[str] | None = None,
    parallel: int = 1,
    allow_parallel_any_model: bool = False,
    endpoints: list[str] | None = None,
) -> None:
    call_fn = PROVIDERS.get(provider_name)
    if not call_fn:
        logger.error(f"Unknown provider: {provider_name}")
        sys.exit(1)

    if parallel < 1:
        raise InvalidTaggingArgsError(
            f"--parallel must be >= 1 (got {parallel}); 1 means serial, "
            f"there is no such thing as 0 or negative worker threads."
        )
    if endpoints and provider_name != "llamacpp":
        raise InvalidTaggingArgsError(
            f"--endpoint is only meaningful with --provider llamacpp "
            f"(other providers have no server/slot concept to fan out "
            f"across), but --provider is {provider_name!r}."
        )

    if endpoints:
        # De-duplicate, preserving first-occurrence order (todo:dcb3cce5
        # finding 6). Without this, the same URL passed twice via repeated
        # --endpoint pre-flights independently (both pass, since each check
        # only knows about itself) and then builds two separate
        # `parallel`-sized ThreadPoolExecutor pools against what is really
        # one server — 2 * parallel concurrent requests landing on a server
        # pre-flighted and sized for `parallel`, the exact silent-
        # serialization failure this whole feature exists to prevent.
        deduped_endpoints = list(dict.fromkeys(endpoints))
        if len(deduped_endpoints) != len(endpoints):
            logger.warning(
                f"--endpoint was given {len(endpoints)} times but only "
                f"{len(deduped_endpoints)} distinct URL(s) were passed; "
                f"duplicates collapse to a single pool per distinct "
                f"endpoint. Repeat a URL only if you intend two "
                f"independent llama.cpp servers at that address — "
                f"otherwise this was accidental and would have sent "
                f"{parallel * len(endpoints)} concurrent requests to a "
                f"server pre-flighted for {parallel}."
            )
        endpoints = deduped_endpoints

    # --parallel is interpreted PER ENDPOINT (see _run_parallel_pool's
    # docstring for why): with E endpoints, up to `parallel` concurrent
    # requests can be in flight against EACH of them, so total concurrency
    # is parallel * E. The finetune-only model guard (todo:5955d038) is
    # judged against that total, not the raw flag value — two endpoints at
    # --parallel 1 each is still 2-wide multiplexing of whatever model is
    # named, and the 27B teacher must not be silently multiplexed that way
    # either. With no --endpoint given, E=1 and this is exactly the
    # pre-multi-endpoint behaviour.
    n_endpoints = len(endpoints) if endpoints else 1
    check_parallel_model_guard(model, parallel, allow_parallel_any_model, n_endpoints=n_endpoints)

    # Slot pre-flight applies PER endpoint: each endpoint is dispatched up
    # to `parallel` concurrent requests (never more — see
    # _run_parallel_pool), so each is checked against `parallel`, not the
    # combined total. Endpoints are pre-flighted concurrently — a single
    # unreachable/slow endpoint's two sequential GET timeouts (/props then
    # /slots) would otherwise block every endpoint after it in a plain loop.
    preflight_targets = endpoints or [None]
    if len(preflight_targets) == 1:
        preflight_server_slots(provider_name, parallel, base_url=preflight_targets[0])
    else:
        with ThreadPoolExecutor(max_workers=len(preflight_targets)) as pool:
            futures = [
                pool.submit(preflight_server_slots, provider_name, parallel, base_url=url)
                for url in preflight_targets
            ]
            for fut in futures:
                fut.result()

    concepts = load_taxonomy()
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    # WAL allows concurrent readers but one writer; parallel worker runs
    # (--chunk-ids-from-file shards) need a wait instead of an instant
    # "database is locked" crash.
    conn.execute("PRAGMA busy_timeout=30000")

    chunks = get_chunks(conn, tradition, text_id, resume, chunk_ids=chunk_ids)
    logger.info(f"Tagging {len(chunks)} chunks with {provider_name}/{model} ...")
    logger.info(
        f"  respect_reviewed={respect_reviewed}  supersede_pending={supersede_pending}"
    )

    tagged = errors = 0
    outcomes = {"inserted": 0, "superseded": 0, "skipped_reviewed": 0, "conflict": 0}

    # No --endpoint given -> the pool only kicks in for --parallel > 1,
    # exactly as before (point 2 of todo:d267201a: "If no endpoint flag is
    # given, behaviour is exactly today's"). Any --endpoint at all routes
    # through the pool even at --parallel 1, since round-robinning across
    # servers is itself the point — one worker per endpoint still means
    # every endpoint after the first is doing something the serial
    # single-connection loop below cannot.
    use_pool = parallel > 1 or bool(endpoints)

    if not use_pool:
        # Serial path — unchanged from before --parallel existed. No thread
        # pool, no behaviour change; this is the N=1 case the concurrent
        # path in _run_parallel_pool is required to match for outcomes.
        for i, chunk in enumerate(chunks):
            result = tag_one_chunk(
                chunk, concepts, provider_name, model, max_body_chars=max_body_chars
            )

            if result.error is not None:
                logger.error(f"  [{i+1}/{len(chunks)}] {result.chunk_id} FAILED: {result.error}")
                errors += 1
            else:
                write_error = _apply_chunk_result_safe(
                    conn, result, model, respect_reviewed, supersede_pending, outcomes
                )
                if write_error is not None:
                    logger.error(f"  [{i+1}/{len(chunks)}] {result.chunk_id} DB WRITE FAILED: {write_error}")
                    errors += 1
                else:
                    tagged += 1
                    logger.info(f"  [{i+1}/{len(chunks)}] {result.chunk_id}: {len(result.tags)} tags")

            if delay > 0 and i < len(chunks) - 1:
                time.sleep(delay)

            if batch_size and (i + 1) % batch_size == 0:
                logger.info(f"Batch {(i+1)//batch_size} complete ({tagged} tagged, {errors} errors)")
    else:
        if endpoints:
            logger.info(
                f"  parallel={parallel} per endpoint x {len(endpoints)} endpoint(s) "
                f"= {parallel * len(endpoints)} total (bounded thread pools, "
                f"single DB-writer thread)"
            )
        else:
            logger.info(f"  parallel={parallel} (bounded thread pool, single DB-writer thread)")
        tagged, errors = _run_parallel_pool(
            conn, chunks, concepts, provider_name, model, max_body_chars,
            delay, parallel, batch_size, respect_reviewed, supersede_pending,
            outcomes, endpoints=endpoints,
        )

    conn.close()
    print(
        f"\nDone: {tagged} chunks tagged, {errors} errors  |  "
        f"rows: inserted={outcomes['inserted']} "
        f"superseded={outcomes['superseded']} "
        f"skipped_reviewed={outcomes['skipped_reviewed']} "
        f"conflict={outcomes['conflict']}"
    )


def build_parser() -> argparse.ArgumentParser:
    """Construct the CLI parser (extracted from main for testability)."""
    parser = argparse.ArgumentParser(description="LLM-assisted concept tagging")
    parser.add_argument("--provider", choices=list(PROVIDERS), default="llamacpp")
    parser.add_argument("--model", default="Qwen3.5-27B-UD-Q4_K_XL.gguf")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--batch-size", type=int, default=0)
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction,
                        default=True,
                        help="Skip chunks already in tagging_progress (i.e. tagged "
                             "by a prior run). Default: on — re-running tag_concepts "
                             "only tags never-seen chunks and won't redo/clobber "
                             "existing work. Pass --no-resume to re-tag everything "
                             "(e.g. after a prompt change); reviewed verdicts are "
                             "still protected by --respect-reviewed.")
    parser.add_argument("--tradition")
    parser.add_argument("--text")
    parser.add_argument("--delay", type=float, default=0.0,
                        help="Seconds to sleep after each API call (rate-limit "
                             "pacing). With --parallel N > 1, this is a PER-WORKER "
                             "sleep — each of the N worker threads pauses --delay "
                             "seconds between its own calls, so aggregate request "
                             "rate scales with N (same as running N serial "
                             "processes each with --delay would). It is not a "
                             "global throttle shared across workers.")
    parser.add_argument("--parallel", type=int, default=1,
                        help="Number of concurrent worker threads calling the LLM "
                             "from this single process. Default 1 = serial, "
                             "byte-identical to the pre-parallel behaviour (no "
                             "thread pool is created). Set to match the server's "
                             "--parallel slot count (scripts/serve-llama.sh) to "
                             "saturate it without hand-sharding --chunk-ids-from-file "
                             "across multiple terminals. All sqlite writes still "
                             "happen on the main thread; only the LLM call and "
                             "response parsing run concurrently. Scoped to the 4B "
                             "finetune (model id starting with "
                             f"{FINETUNE_MODEL_PREFIX!r}) — refused for any other "
                             "model unless --allow-parallel-any-model is also given "
                             "— and pre-flighted against the server's actual slot "
                             "count (GET /props total_slots, when reachable) before "
                             "the run starts.")
    parser.add_argument("--allow-parallel-any-model", action="store_true",
                        default=False,
                        help="Override the --parallel model guard and allow "
                             "--parallel N>1 against a model outside the 4B "
                             "finetune naming convention (e.g. the 27B teacher). "
                             "The teacher runs think-on and was never sized for "
                             "concurrent requests — only pass this if you have a "
                             "specific, deliberate reason to multiplex it anyway.")
    parser.add_argument("--endpoint", action="append", dest="endpoints",
                        metavar="URL", default=None,
                        help="A llama.cpp server base URL to fan work out to "
                             "(e.g. http://127.0.0.1:8080). Repeatable: pass "
                             "--endpoint twice to spread one run across two "
                             "servers (e.g. a second 4B on the 4070) round-robin "
                             "by chunk position, instead of both instances "
                             "contending for one. Each in-flight request is "
                             "pinned to the endpoint it started on for its whole "
                             "lifetime. --parallel is interpreted PER ENDPOINT "
                             "here — each endpoint gets its own pool of up to "
                             "--parallel concurrent workers, so total concurrency "
                             "is --parallel times the number of --endpoint flags. "
                             "Only meaningful with --provider llamacpp. Default "
                             "(not given): today's single-server behaviour, "
                             "unchanged — the env-resolved LLAMACPP_BASE_URL.")
    parser.add_argument("--max-body-chars", type=int, default=0,
                        help="optional cap on chunk body length sent to the LLM. "
                             "0 (default) = unlimited; the chunker is the source "
                             "of truth for chunk size. Set positive only if "
                             "running against a small-context model.")
    parser.add_argument("--respect-reviewed", action=argparse.BooleanOptionalAction,
                        default=True,
                        help="Skip inserting a staged_tag row if a prior row for "
                             "(chunk_id, concept_id, model) has been adjudicated "
                             "(status != 'pending'). Same-model only; different "
                             "models always emit. Default: on. Pass "
                             "--no-respect-reviewed to disable.")
    parser.add_argument("--supersede-pending", action=argparse.BooleanOptionalAction,
                        default=True,
                        help="Before inserting a new pending row for "
                             "(chunk_id, concept_id, model), delete any existing "
                             "pending row for the same triple. Latest-pending wins. "
                             "Default: on. Pass --no-supersede-pending to disable.")
    parser.add_argument("--chunk-ids-from-file",
                        help="Path to a newline-delimited file of chunk IDs. "
                             "When set, processes exactly those chunks (in the "
                             "order given) and ignores --tradition/--text/--resume. "
                             "Blank lines and '#' comments are skipped. Use for "
                             "recovery runs that target a hand-curated list.")
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stderr,
    )

    chunk_ids = None
    if args.chunk_ids_from_file:
        chunk_ids = read_chunk_ids_file(Path(args.chunk_ids_from_file))
        if not chunk_ids:
            logger.error(f"--chunk-ids-from-file is empty: {args.chunk_ids_from_file}")
            sys.exit(1)
        logger.info(f"Loaded {len(chunk_ids)} chunk IDs from {args.chunk_ids_from_file}")

    try:
        run_tagging(
            db_path=Path(args.db),
            provider_name=args.provider,
            model=args.model,
            batch_size=args.batch_size,
            resume=args.resume,
            tradition=args.tradition,
            text_id=args.text,
            delay=args.delay,
            max_body_chars=args.max_body_chars or None,
            respect_reviewed=args.respect_reviewed,
            supersede_pending=args.supersede_pending,
            chunk_ids=chunk_ids,
            parallel=args.parallel,
            allow_parallel_any_model=args.allow_parallel_any_model,
            endpoints=args.endpoints,
        )
    except (ParallelModelNotAllowedError, InsufficientServerSlotsError,
            InsufficientSlotContextError, InvalidTaggingArgsError) as e:
        logger.error(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
