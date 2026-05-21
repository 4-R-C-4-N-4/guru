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
