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
