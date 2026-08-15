"""call_llm and provider functions must require max_tokens explicitly.

Library-level defaults at this layer were the silent failure mode behind
the 2026-05 lost-tags run. Callers that forgot to set max_tokens silently
inherited a too-low budget. Making max_tokens positional/required forces
an informed choice at every call site.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from llm import (  # noqa: E402
    call_anthropic,
    call_llamacpp,
    call_llm,
    call_ollama,
    call_openai,
)


@pytest.mark.parametrize(
    "fn",
    [call_llamacpp, call_ollama, call_anthropic, call_openai],
    ids=lambda f: f.__name__,
)
def test_provider_function_requires_max_tokens(fn):
    """Each provider entry point must reject calls that omit max_tokens."""
    with pytest.raises(TypeError, match="max_tokens"):
        fn(model="m", system="s", prompt="p")


def test_call_llm_requires_max_tokens():
    """The public entry point must reject calls that omit max_tokens."""
    with pytest.raises(TypeError, match="max_tokens"):
        call_llm(provider="llamacpp", model="m", system="s", prompt="p")


# ── base_url is a llamacpp-only parameter (todo:dcb3cce5 finding 7) ────────
#
# Only call_llamacpp's signature accepts base_url (todo:d267201a). Before
# this fix, call_llm forwarded base_url to whichever provider function it
# resolved to whenever it was given, so calling call_llm(..., base_url=...)
# for any other provider raised a callee-side TypeError naming an internal
# kwarg the caller never typed (e.g. "call_ollama() got an unexpected
# keyword argument 'base_url'") instead of a message about the actual
# mistake. call_llm now raises its own ValueError up front, next to the
# existing unknown-provider check, so the contract lives in one place.


@pytest.mark.parametrize("provider", ["ollama", "anthropic", "openai", "claude-code"])
def test_call_llm_rejects_base_url_for_providers_that_dont_support_it(provider):
    with pytest.raises(ValueError, match=f"{provider!r} does not support base_url"):
        call_llm(provider=provider, model="m", system="s", prompt="p",
                 max_tokens=10, base_url="http://example:8080")


def test_call_llm_forwards_base_url_for_llamacpp(monkeypatch):
    """llamacpp is the one provider base_url is for — the ValueError guard
    must not catch it too; base_url must still reach the provider function
    exactly as before this fix."""
    import llm

    seen = {}

    def fake_call_llamacpp(**kwargs):
        seen.update(kwargs)
        return "ok"

    monkeypatch.setitem(llm.PROVIDERS, "llamacpp", fake_call_llamacpp)

    result = call_llm(provider="llamacpp", model="m", system="s", prompt="p",
                      max_tokens=10, base_url="http://example:8080")

    assert result == "ok"
    assert seen["base_url"] == "http://example:8080"


def test_call_llm_without_base_url_is_unaffected_for_any_provider(monkeypatch):
    """base_url=None (the default) must never trigger the new guard —
    every existing call_llm(...) call site that doesn't pass base_url at
    all is unaffected, for every provider."""
    import llm

    seen = {}
    monkeypatch.setitem(llm.PROVIDERS, "ollama",
                        lambda **kwargs: seen.update(kwargs) or "ok")

    result = call_llm(provider="ollama", model="m", system="s", prompt="p", max_tokens=10)

    assert result == "ok"
    assert "base_url" not in seen
