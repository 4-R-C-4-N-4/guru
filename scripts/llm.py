"""
llm.py — Shared LLM provider abstraction for all Guru scripts.

Supported providers:
  llamacpp   — llama.cpp server (OpenAI-compatible, local)
  ollama     — Ollama (OpenAI-compatible, local)
  anthropic  — Anthropic Claude API
  openai     — OpenAI API

Usage:
    from llm import call_llm
    response = call_llm(provider="llamacpp", model="Carnice-27b-Q4_K_M.gguf",
                        system="...", prompt="...", max_tokens=1024)
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


def call_llamacpp(model: str, system: str, prompt: str, max_tokens: int = 1500, timeout: float = DEFAULT_HTTP_TIMEOUT) -> str:
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


def call_ollama(model: str, system: str, prompt: str, max_tokens: int = 2048, timeout: float = DEFAULT_HTTP_TIMEOUT) -> str:
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


def call_anthropic(model: str, system: str, prompt: str, max_tokens: int = 2048, timeout: float = DEFAULT_HTTP_TIMEOUT) -> str:
    import anthropic
    client = anthropic.Anthropic(timeout=timeout)
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def call_openai(model: str, system: str, prompt: str, max_tokens: int = 2048, timeout: float = DEFAULT_HTTP_TIMEOUT) -> str:
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


PROVIDERS = {
    "llamacpp": call_llamacpp,
    "ollama": call_ollama,
    "anthropic": call_anthropic,
    "openai": call_openai,
}


def call_llm(
    provider: str,
    model: str,
    system: str,
    prompt: str,
    max_tokens: int = 1500,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
) -> str:
    """
    Call an LLM and return the response string.

    For thinking models (llama.cpp Carnice, etc.): set max_tokens >= 800 so the
    reasoning phase completes before the answer is emitted.
    """
    fn = PROVIDERS.get(provider)
    if fn is None:
        raise ValueError(f"Unknown provider '{provider}'. Choose from: {list(PROVIDERS)}")
    return fn(model=model, system=system, prompt=prompt, max_tokens=max_tokens, timeout=timeout)


def parse_json_response(raw: str) -> list | dict:
    """
    Robustly extract JSON from an LLM response.
    Handles markdown fences, thinking model preamble, partial wrapping.
    """
    if not raw:
        return []

    raw = raw.strip()
    # Strip markdown fences
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    # Handle two-stage responses if you add the ===JSON=== marker later
    if "===JSON===" in raw:
        raw = raw.split("===JSON===", 1)[1].strip()
    # Try to find a JSON array
    match = re.search(r'\[.*', raw, re.DOTALL)
    if match:
        raw = match.group(0)
    # First attempt: parse as-is
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Repair attempt: truncate to the last complete object, close the array
    # Walk back from the end to find the last complete object
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
        if c == '"' and not escape_next:
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
        # Take everything up to and including the last complete object, then close the array
        repaired = raw[:last_complete + 1] + "]"
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass
    # Give up, return empty
    return []
