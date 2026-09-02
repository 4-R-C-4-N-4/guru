"""Guard against the blavatsky-sd class of bug (todo:c35d1671).

blavatsky-sd was migrated to a new `theosophy` tradition in the live DB, but
its corpus chunk .toml files were never materialized under `corpus/theosophy/`
and the tradition swap never landed on main (manifest + chunking still said
`western_esoteric`). Because `graph_bootstrap.py` builds chunk nodes *only*
from `corpus/**/chunks/*.toml`, a from-scratch corpus rebuild would omit every
blavatsky chunk — silently dropping all 727 nodes and orphaning their
embeddings, tags, edges, and dossiers.

Two guards:

1. ``test_manifest_corpus_dir_matches`` — general: for every manifest source
   that *is* materialized in the corpus, the manifest tradition must equal the
   corpus directory it lives under. That directory name is authoritative —
   ``graph_bootstrap.py`` derives each chunk's ``tradition_id`` (and id prefix)
   from it, not from the cosmetic ``metadata.toml`` ``tradition`` field (which
   is inconsistently cased across the corpus: ``Buddhism`` vs ``theosophy``).
   Catches any future tradition swap that touches the DB/manifest but leaves
   the corpus under the old tradition directory (or vice versa).

2. ``test_blavatsky_sd_materialized`` — specific regression pin for the ticket:
   blavatsky-sd is materialized under `theosophy` with contiguous chunk ids and
   its chunking config lives under the new tradition, not the old one.
"""
from pathlib import Path

import tomllib

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
MANIFEST = PROJECT_ROOT / "sources" / "manifest.toml"
CORPUS = PROJECT_ROOT / "corpus"
CHUNKING = PROJECT_ROOT / "chunking"


def _manifest_traditions() -> dict[str, str]:
    data = tomllib.loads(MANIFEST.read_text())
    return {s["id"]: s["tradition"] for s in data["source"]}


def _materialized_texts() -> list[tuple[str, str, Path]]:
    """(tradition_dir, text_id, text_dir) for every materialized corpus text."""
    out = []
    for trad_dir in sorted(CORPUS.iterdir()):
        if not trad_dir.is_dir():
            continue
        for text_dir in sorted(trad_dir.iterdir()):
            if (text_dir / "chunks").is_dir():
                out.append((trad_dir.name, text_dir.name, text_dir))
    return out


def test_manifest_corpus_dir_matches() -> None:
    manifest = _manifest_traditions()
    mismatches = []
    for trad_dir_name, text_id, _text_dir in _materialized_texts():
        manifest_trad = manifest.get(text_id)
        if manifest_trad is None:
            continue  # corpus text not tracked in the source manifest — skip
        if manifest_trad != trad_dir_name:
            mismatches.append(
                f"{text_id}: manifest={manifest_trad} but corpus dir={trad_dir_name}"
            )
    assert not mismatches, "manifest/corpus tradition mismatches:\n" + "\n".join(mismatches)


def test_blavatsky_sd_materialized() -> None:
    manifest = _manifest_traditions()
    assert manifest.get("blavatsky-sd") == "theosophy", (
        "blavatsky-sd must be declared under the theosophy tradition in the manifest"
    )

    text_dir = CORPUS / "theosophy" / "blavatsky-sd"
    assert text_dir.is_dir(), (
        "corpus/theosophy/blavatsky-sd/ is not materialized — a corpus rebuild "
        "would drop every blavatsky chunk from the graph"
    )

    meta = tomllib.loads((text_dir / "metadata.toml").read_text())
    assert meta["tradition"] == "theosophy"
    assert meta["text_id"] == "blavatsky-sd"

    chunk_files = sorted((text_dir / "chunks").glob("*.toml"))
    assert len(chunk_files) == meta["chunk_count"] == 727

    ids = []
    for f in chunk_files:
        chunk = tomllib.loads(f.read_text())["chunk"]
        ids.append(chunk["id"])
        assert chunk["tradition"] == "theosophy", f"{chunk['id']} tradition != theosophy"
        body = tomllib.loads(f.read_text()).get("content", {}).get("body", "")
        assert body.strip(), f"{chunk['id']} has an empty body"

    expected = [f"theosophy.blavatsky-sd.{n:03d}" for n in range(1, 728)]
    assert ids == expected, "blavatsky-sd chunk ids are not the contiguous theosophy.* set"

    # Chunking config must have moved with the tradition, so a future re-chunk
    # writes back to corpus/theosophy/ rather than resurrecting the old path.
    assert (CHUNKING / "theosophy" / "blavatsky-sd.toml").exists()
    assert not (CHUNKING / "western_esoteric" / "blavatsky-sd.toml").exists()
