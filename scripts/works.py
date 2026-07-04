"""
works.py — the works layer (V10, docs/summary/work-grouping.md).

A *work* is the dossier and level-2 summary unit. Grouped works are declared
in sources/works.toml; every corpus text not listed there is implicitly a
singleton work with work_id == text_id. Used by build_dossiers.py,
promote_dossiers.py, and export.py.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
CORPUS_DIR = PROJECT_ROOT / "corpus"
WORKS_TOML = PROJECT_ROOT / "sources" / "works.toml"


@dataclass(frozen=True)
class Work:
    id: str
    label: str
    tradition: str          # tradition *directory* name (chunk-id prefix)
    members: tuple[str, ...]  # text_ids in reading order
    grouped: bool           # False for implicit singletons


def _corpus_texts() -> dict[str, tuple[str, str]]:
    """text_id -> (tradition_dir, display text_name) for every corpus text."""
    out: dict[str, tuple[str, str]] = {}
    for meta_p in sorted(CORPUS_DIR.glob("*/*/metadata.toml")):
        meta = tomllib.load(open(meta_p, "rb"))
        out[meta["text_id"]] = (meta_p.parent.parent.name, meta.get("text_name", meta["text_id"]))
    return out


def load_works(works_toml: Path = WORKS_TOML) -> dict[str, Work]:
    """Materialize the full work map (grouped + implicit singletons).

    Raises ValueError on: unknown member text, a text claimed by more than
    one work, or a grouped work whose members span traditions.
    """
    texts = _corpus_texts()
    works: dict[str, Work] = {}
    claimed: dict[str, str] = {}

    declared = tomllib.load(open(works_toml, "rb")).get("work", [])
    for w in declared:
        wid = w["id"]
        members = tuple(w["members"])
        for m in members:
            if m not in texts:
                raise ValueError(f"work {wid}: member {m!r} not in corpus")
            if m in claimed:
                raise ValueError(f"text {m!r} claimed by both {claimed[m]} and {wid}")
            claimed[m] = wid
        trads = {texts[m][0] for m in members}
        if len(trads) != 1:
            raise ValueError(f"work {wid}: members span traditions {sorted(trads)}")
        if (declared_trad := w["tradition"]) not in trads:
            raise ValueError(f"work {wid}: declared tradition {declared_trad!r} != members' {trads.pop()!r}")
        works[wid] = Work(wid, w["label"], declared_trad, members, grouped=True)

    for text_id, (trad, name) in texts.items():
        if text_id in claimed:
            continue
        if text_id in works:
            raise ValueError(f"singleton {text_id} collides with a declared work id")
        works[text_id] = Work(text_id, name, trad, (text_id,), grouped=False)

    return works


def work_of(works: dict[str, Work]) -> dict[str, str]:
    """text_id -> work_id over the full map."""
    return {m: w.id for w in works.values() for m in w.members}
