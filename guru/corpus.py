"""guru/corpus.py — corpus path resolution helpers.

Bridges the case/space mismatch between chunk_id tradition prefixes
(display names like "Christian Mysticism") and corpus directory names
(snake_case like "christian_mysticism"). Becomes dead code once
todo:9ec1dcee unifies the two forms.
"""

from __future__ import annotations

from pathlib import Path

from guru.paths import CORPUS_DIR


def resolve_chunk_path(chunk_id: str, corpus_dir: Path = CORPUS_DIR) -> Path | None:
    """Map chunk_id "<trad>.<text_id>.<seq>" -> corpus/<dir>/<text_id>/chunks/<seq>.toml.

    The tradition segment may be a display name ("Christian Mysticism") while
    directories are snake_case ("christian_mysticism"). Tries the raw segment
    first, then a normalized snake_case form.
    """
    parts = chunk_id.split(".")
    if len(parts) < 3:
        return None
    raw_trad, text_id, seq = parts[0], parts[1], parts[2]
    for trad in (raw_trad, raw_trad.lower().replace(" ", "_")):
        p = corpus_dir / trad / text_id / "chunks" / f"{seq}.toml"
        if p.exists():
            return p
    return None
