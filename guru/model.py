"""
guru/model.py — LLM provider abstraction for the Guru query pipeline.

Wraps scripts/llm.py with a typed interface, reads config/model.toml,
and provides a single generate() entrypoint used by the retriever and CLI.
"""

from __future__ import annotations

import sys
from pathlib import Path

import tomllib

from guru.paths import CONFIG_MODEL as CONFIG_PATH, SCRIPTS_DIR

# Make scripts/ importable
sys.path.insert(0, str(SCRIPTS_DIR))
from llm import call_llm  # noqa: E402


def _load_config(config_path: Path = CONFIG_PATH) -> dict:
    with open(config_path, "rb") as f:
        return tomllib.load(f)


class ModelProvider:
    """
    Thin wrapper around llm.call_llm that reads provider/model from
    config/model.toml and exposes a generate() method.

    Example:
        model = ModelProvider()
        response = model.generate(system_prompt, user_query)
    """

    def __init__(self, config_path: Path = CONFIG_PATH):
        cfg = _load_config(config_path)
        prov = cfg.get("provider", {})
        self.provider = prov.get("name", "llamacpp")
        model = prov.get("model")
        if not model:
            raise ValueError(
                f"[provider].model missing from {config_path}. "
                "No silent default — set it explicitly to the model your backend serves."
            )
        self.model = model
        self.max_tokens = int(prov.get("max_tokens", 2048))
        self.timeout = float(prov.get("timeout", 1200))

    def generate(self, system: str, prompt: str, max_tokens: int | None = None) -> str:
        """
        Call the configured LLM provider and return the response string.

        Args:
            system:     The system prompt (Guru persona + citation rules + context).
            prompt:     The user query (passed as the final user message).
            max_tokens: Override token budget; uses config default if None.
        """
        return call_llm(
            provider=self.provider,
            model=self.model,
            system=system,
            prompt=prompt,
            max_tokens=max_tokens or self.max_tokens,
            timeout=self.timeout,
        )

    def __repr__(self) -> str:
        return f"ModelProvider(provider={self.provider!r}, model={self.model!r})"
