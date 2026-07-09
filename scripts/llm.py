"""
llm.py — Shared LLM provider abstraction for all Guru scripts.

Supported providers:
  llamacpp   — llama.cpp server (OpenAI-compatible, local)
  ollama     — Ollama (OpenAI-compatible, local)
  anthropic  — Anthropic Claude API
  openai     — OpenAI API

Usage:
    from llm import call_llm
    response = call_llm(provider="llamacpp", model="Qwen3.5-27B-UD-Q4_K_XL.gguf",
                        system="...", prompt="...", max_tokens=8192)

    max_tokens is a required argument — there is no library-level default
    because the right value depends on the model (thinking models need
    headroom for a reasoning preamble) and on the task.
"""

import json
import logging
import re

logger = logging.getLogger(__name__)

# Default base URLs (overridable via LLAMACPP_BASE_URL / OLLAMA_BASE_URL env vars)
LLAMACPP_BASE_URL = "http://127.0.0.1:8080"
OLLAMA_BASE_URL = "http://localhost:11434"


def ollama_base_url() -> str:
    """Resolve OLLAMA_BASE_URL from env or default. Used by embedding callers
    that don't go through the chat path."""
    import os
    return os.environ.get("OLLAMA_BASE_URL", OLLAMA_BASE_URL)


def ollama_embed_url() -> str:
    return f"{ollama_base_url()}/api/embed"


DEFAULT_HTTP_TIMEOUT = 1200


def _chat_openai_compat(
    base_url: str,
    model: str,
    system: str,
    prompt: str,
    max_tokens: int,
    api_key: str = "none",
) -> str:
    """
    Generic OpenAI-compatible chat completion.
    Handles thinking models: returns content if non-empty, else reasoning_content.
    """
    from openai import OpenAI

    client = OpenAI(base_url=f"{base_url}/v1", api_key=api_key)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        max_tokens=max_tokens,
    )
    choice = resp.choices[0].message
    # Thinking models put the answer in content; reasoning phase in reasoning_content.
    # If content is empty (max_tokens too small to finish thinking), fall back to
    # extracting any JSON from reasoning_content.
    content = getattr(choice, "content", "") or ""
    reasoning = getattr(choice, "reasoning_content", "") or ""

    if content.strip():
        return content
    if reasoning.strip():
        logger.debug("Content empty — extracting from reasoning_content")
        return reasoning
    return ""


def call_llamacpp(model: str, system: str, prompt: str, max_tokens: int, timeout: float = DEFAULT_HTTP_TIMEOUT) -> str:
    """
    Call the local llama.cpp server via raw HTTP (no openai SDK dependency).
    Uses urllib so there's no DNS lookup or connection overhead at import time.
    Handles thinking models: returns content if non-empty, else full text including
    reasoning_content so parse_json_response can extract JSON from it.
    """
    import os
    import urllib.request
    base = os.environ.get("LLAMACPP_BASE_URL", LLAMACPP_BASE_URL)
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(
        f"{base}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())

    msg = data["choices"][0]["message"]
    content = msg.get("content") or ""
    reasoning = msg.get("reasoning_content") or ""

    if content.strip():
        return content
    # Thinking model: reasoning came first, actual answer follows after </think>
    # Return full reasoning so parse_json_response can scan it for JSON
    return reasoning


def call_ollama(model: str, system: str, prompt: str, max_tokens: int, timeout: float = DEFAULT_HTTP_TIMEOUT) -> str:
    """Call Ollama via its native chat API (no openai SDK)."""
    import os
    import urllib.request
    base = os.environ.get("OLLAMA_BASE_URL", OLLAMA_BASE_URL)
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"num_predict": max_tokens},
    }).encode()
    req = urllib.request.Request(
        f"{base}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return data["message"]["content"]


def call_anthropic(model: str, system: str, prompt: str, max_tokens: int, timeout: float = DEFAULT_HTTP_TIMEOUT) -> str:
    import anthropic
    client = anthropic.Anthropic(timeout=timeout)
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def call_openai(model: str, system: str, prompt: str, max_tokens: int, timeout: float = DEFAULT_HTTP_TIMEOUT) -> str:
    from openai import OpenAI
    resp = OpenAI(timeout=timeout).chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content


class ProviderBusy(RuntimeError):
    """Provider hit a usage/rate limit; caller should sleep and resume.

    Staged rows make every generation node idempotent (design §1.3.6), so
    the correct response is back off and re-run, never model substitution.
    """

    def __init__(self, message: str, retry_after: float = 300.0):
        super().__init__(message)
        self.retry_after = retry_after


_CLAUDE_BUSY_MARKERS = ("usage limit", "session limit", "rate limit", "overloaded", "429", "resets ")


class ContentBlocked(RuntimeError):
    """Safety classifier declined the request/output. May be transient
    (retry once) or deterministic for a given input (skip the node)."""


def call_claude_code(model: str, system: str, prompt: str, max_tokens: int, timeout: float = DEFAULT_HTTP_TIMEOUT) -> str:
    """Headless Claude Code on the subscription (design §1.3.6).

    Shells to `claude -p --output-format json` with the prompt on stdin and
    the template's system block via --system-prompt. --model is always pinned
    explicitly: the configured string is provenance (staged rows' `model`).
    max_tokens is accepted for signature parity but not enforceable through
    the CLI; field contracts bound output length instead. Tools are disabled
    — generation nodes are pure text completion.
    """
    import subprocess

    cmd = [
        "claude", "-p",
        "--model", model,
        "--output-format", "json",
        "--system-prompt", system,
        "--disallowedTools", "*",
    ]
    try:
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"claude-code timed out after {timeout}s") from e
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    # The CLI exits nonzero for API-level errors but still writes the JSON
    # envelope to stdout — always try the envelope first.
    envelope = None
    try:
        envelope = json.loads(out)
    except json.JSONDecodeError:
        pass
    if envelope is None:
        low = (out + " " + err).lower()
        if any(m in low for m in _CLAUDE_BUSY_MARKERS):
            raise ProviderBusy(f"claude-code busy: {err or out[:200]}")
        if proc.returncode == 0:
            # exit 0 with an unparseable envelope is an output problem, not a
            # process failure — say so, or triage chases the wrong thing
            raise RuntimeError(f"claude-code exit 0 but non-JSON envelope: {out[:200]!r}")
        raise RuntimeError(f"claude-code exit {proc.returncode}: {err or out[:200]}")
    if envelope.get("is_error"):
        result_low = str(envelope.get("result", "")).lower()
        if any(m in result_low for m in _CLAUDE_BUSY_MARKERS):
            raise ProviderBusy(f"claude-code busy: {envelope.get('result', '')[:200]}")
        if "content filtering" in result_low or "blocked" in result_low:
            raise ContentBlocked(f"claude-code content filter: {envelope.get('result', '')[:200]}")
        raise RuntimeError(f"claude-code error result: {envelope.get('result', '')[:200]}")
    result = envelope.get("result")
    if not isinstance(result, str) or not result.strip():
        raise RuntimeError("claude-code envelope had empty result")
    return result


PROVIDERS = {
    "llamacpp": call_llamacpp,
    "ollama": call_ollama,
    "anthropic": call_anthropic,
    "openai": call_openai,
    "claude-code": call_claude_code,
}


def call_llm(
    provider: str,
    model: str,
    system: str,
    prompt: str,
    max_tokens: int,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
) -> str:
    """
    Call an LLM and return the response string.

    max_tokens is required: the right value depends on the model (thinking
    models need 8k+ for the reasoning preamble alone) and on the task,
    and a library-level default was the silent failure mode that lost
    ~12% of chunks on the 2026-05 tagging run.
    """
    fn = PROVIDERS.get(provider)
    if fn is None:
        raise ValueError(f"Unknown provider '{provider}'. Choose from: {list(PROVIDERS)}")
    return fn(model=model, system=system, prompt=prompt, max_tokens=max_tokens, timeout=timeout)


_THINKING_MARKERS = (
    "Thinking Process",
    "Analyze the Request",
    "Analyze the Passage",
    "<think>",
    "Final list",
    "Final List",
    "Okay, final",
    "Step-by-step",
    "Let me analyze",
)


def _looks_like_thinking_overflow(raw: str) -> bool:
    """Did the model burn the token budget on reasoning prose without
    closing JSON?

    A response from a thinking model that ran out of max_tokens mid-reasoning
    is long (≥5000 chars), contains a reasoning-mode marker, and lacks a
    closing top-level bracket. parse_json_response will return [] for this
    shape — indistinguishable from a legitimate empty answer. The canary
    surfaces it as a logger warning so the caller can raise max_tokens
    before another multi-day run silently drops chunks.
    """
    if len(raw) < 5000:
        return False
    head = raw[:1000]
    tail = raw[-2000:]
    if not any(m in head or m in tail for m in _THINKING_MARKERS):
        return False
    stripped = raw.rstrip()
    return not (stripped.endswith("]") or stripped.endswith("}"))


def parse_json_response(raw: str) -> list | dict:
    """
    Robustly extract JSON from an LLM response.

    Handles markdown fences, thinking-model preamble, and partial wrapping
    for both top-level arrays and top-level objects. For arrays, attempts
    to repair truncated output by closing the array after the last complete
    inner object. Returns [] on total failure.

    Emits a logger warning when the input looks like a thinking-budget
    overflow (long, reasoning-marker preamble, no closing bracket) so
    silent failures show up in run logs immediately.
    """
    if not raw:
        return []

    original_raw = raw
    raw = raw.strip()
    # Strip markdown fences
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    # Handle two-stage responses if you add the ===JSON=== marker later
    if "===JSON===" in raw:
        raw = raw.split("===JSON===", 1)[1].strip()
    # Skip preamble — locate the first '[' or '{' and parse from there.
    match = re.search(r'[\[\{]', raw)
    if match:
        raw = raw[match.start():]
    # First attempt: parse as-is
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Repair: only meaningful for arrays. For a truncated object we'd need
    # a smarter parser; callers should retry with a higher max_tokens budget.
    if not raw.startswith("["):
        if _looks_like_thinking_overflow(original_raw):
            logger.warning(
                "LLM response (%d chars) looks like a thinking-budget overflow: "
                "reasoning prose, no closing JSON bracket. Raise max_tokens on the calling site.",
                len(original_raw),
            )
        return []
    # Walk forward, tracking string/escape state, to find the last complete
    # top-level object. Then close the array.
    depth = 0
    last_complete = -1
    in_string = False
    escape_next = False
    for i, c in enumerate(raw):
        if escape_next:
            escape_next = False
            continue
        if c == '\\':
            escape_next = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                last_complete = i
    if last_complete > 0:
        repaired = raw[:last_complete + 1] + "]"
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass
    if _looks_like_thinking_overflow(original_raw):
        logger.warning(
            "LLM response (%d chars) looks like a thinking-budget overflow: "
            "reasoning prose, no closing JSON bracket. Raise max_tokens on the calling site.",
            len(original_raw),
        )
    return []
