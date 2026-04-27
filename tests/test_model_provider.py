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
""")
    mp = ModelProvider(config_path=cfg)
    assert mp.model == "Foo-7B.gguf"
    assert mp.provider == "llamacpp"
    assert mp.max_tokens == 1024


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
model = ""
""")
    with pytest.raises(ValueError):
        ModelProvider(config_path=cfg)
