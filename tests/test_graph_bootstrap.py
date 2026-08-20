"""Regression: graph_bootstrap must not crash on the v2 three-tier taxonomy.

The old bootstrap_concepts() pass assumed the flat v1 taxonomy and bound a dict
as a node 'definition' (sqlite ProgrammingError 'type dict is not supported')
the moment concepts/taxonomy.toml became three-tier ([concepts.DOMAIN.FAMILY]).
It ran before bootstrap_chunks in main(), so the whole script aborted. Concept
nodes are now scripts/sync_taxonomy.py's responsibility, so that pass was
removed. todo:13f72b3d.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import graph_bootstrap as gb  # noqa: E402


def test_graph_bootstrap_builds_chunk_graph_without_taxonomy_crash(tmp_path):
    """apply_schema + bootstrap_chunks must complete (this path used to be
    unreachable — the concepts pass crashed first) and produce the chunk +
    tradition graph."""
    db = tmp_path / "gb.db"
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA foreign_keys=ON")
    gb.apply_schema(conn)
    n = gb.bootstrap_chunks(conn)
    assert n > 0, "no chunk nodes bootstrapped"
    (chunks,) = conn.execute("SELECT COUNT(*) FROM nodes WHERE type='chunk'").fetchone()
    (trads,) = conn.execute("SELECT COUNT(*) FROM nodes WHERE type='tradition'").fetchone()
    assert chunks == n
    assert trads > 0, "no tradition nodes created"
    conn.close()


def test_graph_bootstrap_delegates_concepts_to_sync_taxonomy():
    """The broken, obsolete concepts pass is gone — concept nodes are created by
    scripts/sync_taxonomy.py, not here."""
    assert not hasattr(gb, "bootstrap_concepts")


def _first_chunked_text():
    """(tradition, text) of some real corpus text with chunk TOMLs, or None."""
    if not gb.CORPUS_DIR.exists():
        return None
    for trad in sorted(gb.CORPUS_DIR.iterdir()):
        if not trad.is_dir() or trad.name.endswith(".toml"):
            continue
        for text in sorted(trad.iterdir()):
            if text.is_dir() and (text / "chunks").exists() \
                    and any((text / "chunks").glob("*.toml")):
                return trad.name, text.name
    return None


def test_only_text_restricts_to_one_text(tmp_path):
    """--text bootstraps exactly one source-id's chunks, not the whole corpus —
    the property node 09 relies on so a driver cannot sweep another in-flight
    text into the graph."""
    picked = _first_chunked_text()
    if picked is None:
        import pytest
        pytest.skip("no chunked corpus text available")
    tradition, text_id = picked

    conn = sqlite3.connect(str(tmp_path / "one.db"))
    conn.execute("PRAGMA foreign_keys=ON")
    gb.apply_schema(conn)
    n = gb.bootstrap_chunks(conn, only_text=text_id)

    assert n > 0, f"--text {text_id} bootstrapped nothing"
    # Every chunk node belongs to the requested text.
    import json
    rows = conn.execute(
        "SELECT metadata_json FROM nodes WHERE type='chunk'").fetchall()
    assert rows and all(json.loads(m)["text_id"] == text_id for (m,) in rows)
    # Exactly one tradition node — the target's — was touched.
    trads = [r[0] for r in conn.execute(
        "SELECT id FROM nodes WHERE type='tradition'").fetchall()]
    assert trads == [tradition]

    # And it is strictly a subset of the whole-corpus walk.
    whole = sqlite3.connect(str(tmp_path / "all.db"))
    whole.execute("PRAGMA foreign_keys=ON")
    gb.apply_schema(whole)
    total = gb.bootstrap_chunks(whole)
    assert n <= total
    conn.close()
    whole.close()


def test_only_text_no_match_bootstraps_nothing(tmp_path):
    """A --text that matches no corpus dir is a clean no-op, not a whole-corpus
    fallback."""
    conn = sqlite3.connect(str(tmp_path / "none.db"))
    conn.execute("PRAGMA foreign_keys=ON")
    gb.apply_schema(conn)
    n = gb.bootstrap_chunks(conn, only_text="no-such-text-zzz")
    assert n == 0
    (nodes,) = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()
    assert nodes == 0
    conn.close()
