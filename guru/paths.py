"""guru/paths.py — canonical filesystem paths for the project.

Single source of truth so renames (e.g. data/ → state/) touch one file.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB = DATA_DIR / "guru.db"

CORPUS_DIR = PROJECT_ROOT / "corpus"
SCHEMA_DIR = PROJECT_ROOT / "schema"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

CONFIG_DIR = PROJECT_ROOT / "config"
CONFIG_MODEL = CONFIG_DIR / "model.toml"
CONFIG_EMBEDDING = CONFIG_DIR / "embedding.toml"

TAXONOMY_TOML = PROJECT_ROOT / "concepts" / "taxonomy.toml"
