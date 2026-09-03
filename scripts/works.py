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

# Valid work kinds (todo:9445cd73). The SQL CHECK in schema/corpus-schema.sql
# mirrors this list (SQL can't import it) — keep the two in sync.
WORK_KINDS = ("primary", "synthesis")
PRIMARY, SYNTHESIS = WORK_KINDS


class WorksConfigError(Exception):
    """A works.toml configuration error (malformed/unknown `synthesis` entry).

    Deliberately NOT a ValueError: callers that catch ValueError to mean "work
    not found" (guru/dossier.py `build_ctx`) would otherwise silently mask a
    corpus-wide parse failure as a per-work "not a known work" for every work_id.
    """


@dataclass(frozen=True)
class Work:
    id: str
    label: str
    tradition: str          # tradition *directory* name (chunk-id prefix)
    members: tuple[str, ...]  # text_ids in reading order
    grouped: bool           # False for implicit singletons
    kind: str = PRIMARY     # PRIMARY root text | SYNTHESIS survey (works.toml `synthesis`)


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

    data = tomllib.load(open(works_toml, "rb"))
    declared = data.get("work", [])
    # Work kind (todo:9445cd73): only synthesis works are listed; everything else
    # defaults to "primary". Keys on work_id, so it applies to grouped works and
    # implicit singletons alike.
    syn_raw = data.get("synthesis", [])
    if not isinstance(syn_raw, list):
        raise WorksConfigError(
            f"works.toml: 'synthesis' must be a list of work ids, got {type(syn_raw).__name__}")
    synthesis_ids = set(syn_raw)
    kind_of = lambda wid: SYNTHESIS if wid in synthesis_ids else PRIMARY
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
        works[wid] = Work(wid, w["label"], declared_trad, members, grouped=True, kind=kind_of(wid))

    for text_id, (trad, name) in texts.items():
        if text_id in claimed:
            continue
        if text_id in works:
            raise ValueError(f"singleton {text_id} collides with a declared work id")
        works[text_id] = Work(text_id, name, trad, (text_id,), grouped=False, kind=kind_of(text_id))

    # A synthesis id that names no work is a typo — fail loudly rather than
    # silently classify nothing (todo:9445cd73). Runs here, not earlier, because the
    # full work id set (declared + implicit singletons) only exists once both loops
    # above have materialized it. WorksConfigError (not ValueError) so build_ctx
    # can't mask it.
    if unknown := (synthesis_ids - works.keys()):
        raise WorksConfigError(f"works.toml synthesis: unknown work id(s) {sorted(unknown)}")

    return works


def work_of(works: dict[str, Work]) -> dict[str, str]:
    """text_id -> work_id over the full map."""
    return {m: w.id for w in works.values() for m in w.members}


if __name__ == "__main__":
    # Ingest gate for docs/ingest/02-manifest-entry.md (todo:9445cd73,fb522ee1):
    # materialize the works layer, which raises on any works.toml misconfiguration
    # — a malformed or unknown `synthesis` id (WorksConfigError), an unknown member,
    # or a cross-tradition group. CWD-independent: WORKS_TOML/corpus resolve from
    # __file__, so `python3 scripts/works.py` validates from any directory.
    _w = load_works()
    _syn = sorted(k for k, v in _w.items() if v.kind == SYNTHESIS)
    print(f"works layer OK — {len(_w)} works, {len(_syn)} synthesis: {', '.join(_syn)}")
