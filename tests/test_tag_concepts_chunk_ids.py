"""Tests for the --chunk-ids-from-file targeting path in tag_concepts.

Drives recovery runs that need to process exactly a hand-curated set of
chunks regardless of tagging_progress state.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from tag_concepts import get_chunks, read_chunk_ids_file  # noqa: E402


# ── read_chunk_ids_file ──────────────────────────────────────────────────────


def test_reads_simple_list(tmp_path):
    f = tmp_path / "ids.txt"
    f.write_text("a.b.001\na.b.002\nc.d.003\n")
    assert read_chunk_ids_file(f) == ["a.b.001", "a.b.002", "c.d.003"]


def test_strips_whitespace_and_blank_lines(tmp_path):
    f = tmp_path / "ids.txt"
    f.write_text("  a.b.001  \n\n  \na.b.002\n")
    assert read_chunk_ids_file(f) == ["a.b.001", "a.b.002"]


def test_ignores_comment_lines(tmp_path):
    f = tmp_path / "ids.txt"
    f.write_text("# recovery sample, 2026-05-21\na.b.001\n# inline note\na.b.002\n")
    assert read_chunk_ids_file(f) == ["a.b.001", "a.b.002"]


def test_dedupes_preserving_first_occurrence(tmp_path):
    f = tmp_path / "ids.txt"
    f.write_text("a.b.001\na.b.002\na.b.001\na.b.003\n")
    assert read_chunk_ids_file(f) == ["a.b.001", "a.b.002", "a.b.003"]


def test_empty_file_returns_empty(tmp_path):
    f = tmp_path / "ids.txt"
    f.write_text("\n# just comments\n   \n")
    assert read_chunk_ids_file(f) == []


# ── get_chunks(chunk_ids=...) ────────────────────────────────────────────────


def _seed_chunks(conn: sqlite3.Connection, ids: list[str]) -> None:
    conn.execute(
        """CREATE TABLE nodes (
              id TEXT PRIMARY KEY,
              type TEXT,
              label TEXT,
              tradition_id TEXT,
              metadata_json TEXT
        )"""
    )
    for cid in ids:
        conn.execute(
            "INSERT INTO nodes VALUES (?, 'chunk', ?, 'test', ?)",
            (cid, f"label:{cid}", json.dumps({"text_id": "test.text"})),
        )
    conn.execute("CREATE TABLE tagging_progress (chunk_id TEXT PRIMARY KEY)")
    conn.commit()


def test_get_chunks_returns_requested_in_order():
    conn = sqlite3.connect(":memory:")
    _seed_chunks(conn, ["a.b.001", "a.b.002", "a.b.003"])
    result = get_chunks(conn, tradition=None, text_id=None, resume=False,
                        chunk_ids=["a.b.003", "a.b.001"])
    assert [r["id"] for r in result] == ["a.b.003", "a.b.001"]


def test_get_chunks_skips_missing_ids(caplog):
    import logging
    conn = sqlite3.connect(":memory:")
    _seed_chunks(conn, ["a.b.001", "a.b.002"])
    with caplog.at_level(logging.WARNING, logger="tag_concepts"):
        result = get_chunks(conn, tradition=None, text_id=None, resume=False,
                            chunk_ids=["a.b.001", "nope.xxx.999", "a.b.002"])
    assert [r["id"] for r in result] == ["a.b.001", "a.b.002"]
    assert any("not found" in r.message for r in caplog.records)


def test_chunk_ids_path_ignores_resume_filter():
    """A chunk in tagging_progress must still be returned when given by id."""
    conn = sqlite3.connect(":memory:")
    _seed_chunks(conn, ["a.b.001", "a.b.002"])
    conn.execute("INSERT INTO tagging_progress VALUES ('a.b.001')")
    conn.commit()
    result = get_chunks(conn, tradition=None, text_id=None, resume=True,
                        chunk_ids=["a.b.001"])
    assert [r["id"] for r in result] == ["a.b.001"]
