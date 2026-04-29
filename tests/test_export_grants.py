"""tests/test_export_grants.py — export.py emits GRANT statements for
the app role so it can read corpus.* after the swap (todo:875642fe).

Regression: v2 export ran as postgres superuser, leaving corpus.*
unreadable by the app role and failing the Next.js boot check with
"permission denied for schema corpus".
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from export import emit_grants, APP_ROLE  # noqa: E402


def _emit(role: str = "guru", schema: str = "corpus_new") -> str:
    buf = io.StringIO()
    emit_grants(buf, schema, role)
    return buf.getvalue()


def test_emits_usage_on_schema():
    assert "GRANT USAGE ON SCHEMA corpus_new TO guru;" in _emit()


def test_emits_select_on_all_tables():
    assert "GRANT SELECT ON ALL TABLES IN SCHEMA corpus_new TO guru;" in _emit()


def test_grants_target_staging_schema_not_live():
    """Grants must be on the staging schema so they ride the rename — if
    they were on `corpus` directly, the staging-only design breaks."""
    out = _emit(schema="corpus_new")
    assert "ON SCHEMA corpus_new" in out
    assert "ON SCHEMA corpus " not in out
    assert "ON SCHEMA corpus;" not in out


def test_app_role_is_guru():
    """Locks the constant so a typo against the live VPS role is caught
    in CI rather than at the next prod load."""
    assert APP_ROLE == "guru"
