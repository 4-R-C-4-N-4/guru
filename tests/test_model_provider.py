"""tests/test_model_provider.py — ModelProvider config loading.

Regression: guru/model.py:42 used to silently fall back to "Carnice-27b-Q4_K_M.gguf"
when [provider].model was missing, which silently mismatched config/model.toml.
We now raise instead.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from guru.model import ModelProvider


def _write_cfg(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "model.toml"
    p.write_text(body)
    return p


def test_loads_model_from_config(tmp_path):
    cfg = _write_cfg(tmp_path, """
[provider]
name = "llamacpp"
model = "Foo-7B.gguf"
max_tokens = 1024
timeout = 60
""")
    mp = ModelProvider(config_path=cfg)
    assert mp.model == "Foo-7B.gguf"
    assert mp.provider == "llamacpp"
    assert mp.max_tokens == 1024
    assert mp.timeout == 60.0


def test_timeout_default_when_omitted(tmp_path):
    cfg = _write_cfg(tmp_path, """
[provider]
name = "llamacpp"
model = "Foo.gguf"
""")
    mp = ModelProvider(config_path=cfg)
    assert mp.timeout == 1200.0


def test_missing_model_raises(tmp_path):
    cfg = _write_cfg(tmp_path, """
[provider]
name = "llamacpp"
""")
    with pytest.raises(ValueError, match="provider.*model"):
        ModelProvider(config_path=cfg)


def test_empty_model_string_raises(tmp_path):
    cfg = _write_cfg(tmp_path, """
[provider]
name = "llamacpp"
max_tokens = 1024
model = ""
""")
    with pytest.raises(ValueError):
        ModelProvider(config_path=cfg)


def test_repo_model_config_has_thinking_budget():
    """The committed config/model.toml must leave room for a thinking model's
    reasoning preamble. 2048 was the value that silently cut Qwen off
    mid-reasoning on the interactive query path; 8192 is the floor."""
    mp = ModelProvider()
    assert mp.max_tokens >= 8192, (
        f"config/model.toml [provider].max_tokens={mp.max_tokens} is too low "
        f"to carry a thinking model's preamble through to a JSON answer."
    )
