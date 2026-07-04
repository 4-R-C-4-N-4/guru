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
    emit_indexes(buf, "corpus_new")
    return buf.getvalue()


def test_emits_hnsw_index_on_chunks_embedding():
    out = _emit_to_string()
    assert "CREATE INDEX chunks_embedding_hnsw" in out
    assert "USING hnsw (embedding vector_cosine_ops)" in out


def test_emits_chunks_btrees():
    out = _emit_to_string()
    assert "CREATE INDEX chunks_text_id" in out
    assert "ON corpus_new.chunks (text_id)" in out
    assert "CREATE INDEX chunks_tradition" in out
    assert "ON corpus_new.chunks (tradition)" in out


def test_emits_edges_btrees():
    out = _emit_to_string()
    assert "CREATE INDEX edges_source" in out
    assert "ON corpus_new.edges (source)" in out
    assert "CREATE INDEX edges_target" in out
    assert "ON corpus_new.edges (target)" in out


def test_emits_concept_hierarchy_indexes():
    out = _emit_to_string()
    assert "idx_concept_families_parent ON corpus_new.concept_families (parent_id)" in out
    # the one-primary-per-concept invariant is a partial UNIQUE index
    assert ("CREATE UNIQUE INDEX idx_concept_primary_family ON "
            "corpus_new.concept_family_membership (concept_id) WHERE is_primary") in out
    assert "idx_concept_family_membership_family ON corpus_new.concept_family_membership (family_id)" in out
    assert "idx_concept_aliases_alias ON corpus_new.concept_aliases (alias)" in out
    assert "idx_family_aliases_alias ON corpus_new.family_aliases (alias)" in out


def test_emits_exactly_ten_indexes():
    # 5 original (chunks×3, edges×2) + 5 concept-hierarchy (one is UNIQUE).
    import re
    out = _emit_to_string()
    assert len(re.findall(r"CREATE (?:UNIQUE )?INDEX", out)) == 14  # +4 v4 document-knowledge


def test_no_create_index_anywhere_else_in_module():
    """The schema file carries no indexes (per its own header comment).
    All CREATE INDEX statements in the export pipeline must come from
    emit_indexes — keeps the build-after-bulk-insert ordering intact."""
    schema_text = (PROJECT_ROOT / "schema" / "corpus-schema.sql").read_text()
    assert "CREATE INDEX" not in schema_text
