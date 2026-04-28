"""guru/corpus.py — corpus path resolution helper.

Maps a chunk_id to its on-disk TOML path. After todo:9ec1dcee normalized
chunk_ids to snake_case (matching the corpus directory layout), this is
a straight directory join — no fallback or normalization needed.
"""

from __future__ import annotations

from pathlib import Path

from guru.paths import CORPUS_DIR


def resolve_chunk_path(chunk_id: str, corpus_dir: Path = CORPUS_DIR) -> Path | None:
    """Map chunk_id "<trad>.<text_id>.<seq>" → corpus/<trad>/<text_id>/chunks/<seq>.toml.

    Returns None if the path doesn't exist or the chunk_id is malformed.
    """
    parts = chunk_id.split(".", 2)
    if len(parts) < 3:
        return None
    trad, text_id, seq = parts
    p = corpus_dir / trad / text_id / "chunks" / f"{seq}.toml"
    return p if p.exists() else None
