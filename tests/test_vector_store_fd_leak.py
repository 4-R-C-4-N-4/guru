"""Regression test for vector_store.py SQLite-connection fd leak (todo:898ee5f9).

Per Python docs, `with sqlite3.connect(path) as conn:` does NOT close the
connection — only the transaction. Combined with propose_edges.py's tight
loop calling _concepts_for() per neighbor, this leaked thousands of fds
mid-run and produced OSError [Errno 24] when later TOML opens couldn't
acquire a descriptor.

The fix wraps each connect in contextlib.closing(). This test exercises
_concepts_for in a tight loop and asserts the process's fd count doesn't
grow — directly catching any regression to the leaky pattern.

Linux-only (uses /proc/self/fd). Skipped on macOS / Windows.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from vector_store import _concepts_for  # noqa: E402


pytestmark = pytest.mark.skipif(
    not Path("/proc/self/fd").exists(),
    reason="needs Linux /proc/self/fd to count open file descriptors",
)


def _open_fd_count() -> int:
    return len(os.listdir("/proc/self/fd"))


def test_concepts_for_does_not_leak_fds(tmp_path: Path) -> None:
    """Tight loop of 200 _concepts_for calls must not accumulate fds.

    Without the closing() wrapper, each call leaks ~3 fds (db + wal + shm)
    until GC runs — deterministically reproducing the propose_edges
    failure mode at scale. With the fix, fd count is stable.
    """
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript("""
            CREATE TABLE nodes (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                label TEXT NOT NULL
            );
            CREATE TABLE edges (
                source_id TEXT NOT NULL REFERENCES nodes(id),
                target_id TEXT NOT NULL REFERENCES nodes(id),
                type TEXT NOT NULL
            );
            INSERT INTO nodes(id, type, label) VALUES
                ('chunk-1', 'chunk', 'X'),
                ('concept.gnosis', 'concept', 'Gnosis');
            INSERT INTO edges(source_id, target_id, type) VALUES
                ('chunk-1', 'concept.gnosis', 'EXPRESSES');
        """)
        conn.commit()
    finally:
        conn.close()

    # Warm-up: first few calls may allocate stable internal fds (logging,
    # imports, etc.). Sample after warm-up.
    for _ in range(5):
        _concepts_for(db, "chunk-1")
    baseline = _open_fd_count()

    for _ in range(200):
        result = _concepts_for(db, "chunk-1")
    # sanity: function still returns the right thing
    assert result == ["concept.gnosis"]

    delta = _open_fd_count() - baseline
    # Without closing(): delta ≈ 600 (200 calls × ~3 fds each).
    # With closing(): delta should be 0 or near-zero (perhaps tiny noise
    # from stdlib internals). 50 is a generous ceiling that still catches
    # the regression decisively.
    assert delta < 50, (
        f"vector_store._concepts_for leaked fds: {delta} new fds after "
        f"200 calls (baseline={baseline}). The 'with sqlite3.connect()' "
        f"context-manager pattern doesn't close — wrap with contextlib.closing()."
    )
