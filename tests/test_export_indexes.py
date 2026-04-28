"""tests/test_export_indexes.py — export.py emits the expected post-load
CREATE INDEX statements (todo:ce64c410).

Regression: scripts/export.py used to leave a stub comment between
emit_inserts and emit_metadata. The export artifact then carried no
HNSW vector index and no FK-lookup btrees, so every prod load fell back
to seq-scans on the hot retrieval and graph-traversal paths.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from export import emit_indexes  # noqa: E402


def _emit_to_string() -> str:
    buf = io.StringIO()
    emit_indexes(buf)
    return buf.getvalue()


def test_emits_hnsw_index_on_chunks_embedding():
    out = _emit_to_string()
    assert "CREATE INDEX chunks_embedding_hnsw" in out
    assert "USING hnsw (embedding vector_cosine_ops)" in out


def test_emits_chunks_btrees():
    out = _emit_to_string()
    assert "CREATE INDEX chunks_text_id" in out
    assert "ON chunks (text_id)" in out
    assert "CREATE INDEX chunks_tradition" in out
    assert "ON chunks (tradition)" in out


def test_emits_edges_btrees():
    out = _emit_to_string()
    assert "CREATE INDEX edges_source" in out
    assert "ON edges (source)" in out
    assert "CREATE INDEX edges_target" in out
    assert "ON edges (target)" in out


def test_emits_exactly_five_indexes():
    out = _emit_to_string()
    assert out.count("CREATE INDEX") == 5


def test_no_create_index_anywhere_else_in_module():
    """The schema file carries no indexes (per its own header comment).
    All CREATE INDEX statements in the export pipeline must come from
    emit_indexes — keeps the build-after-bulk-insert ordering intact."""
    schema_text = (PROJECT_ROOT / "schema" / "corpus-schema.sql").read_text()
    assert "CREATE INDEX" not in schema_text
