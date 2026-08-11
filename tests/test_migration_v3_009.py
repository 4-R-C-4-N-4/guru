"""tests/test_migration_v3_009.py — edge provenance schema (Phase 0.2).

Two jobs, and the second is the one worth having.

1. The migration produces what it claims from a pre-v3_009 database:
   staged_edges.similarity, staged_edges.presentation_order, and an
   edge_progress table keyed by (chunk_id, model, prompt_version) so a
   second model's sweep cannot overwrite the first's record.

2. **scripts/schema.sql agrees with the migration.** A fresh checkout builds
   its database from the canonical DDL, not from the migration chain, so a
   migration-only change leaves every new write path broken there while every
   workbench DB works fine — invisible to any test that defines its own
   inline schema copy. These tests build from scripts/schema.sql itself, so
   they fail if the two ever drift apart.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
SCHEMA_SQL = PROJECT_ROOT / "scripts" / "schema.sql"
MIGRATIONS_DIR = PROJECT_ROOT / "scripts" / "migrations"

# Migrations that shape staged_edges / edge_progress, in application order.
# Append future ones here so the drift comparison keeps covering them.
EDGE_SCHEMA_MIGRATIONS = ["v3_009_edge_provenance.sql"]

# staged_edges as v3_005 left it — the pre-v3_009 state the migration must
# upgrade. A frozen historical snapshot: it describes what was, so unlike an
# inline copy of the *current* schema it cannot drift.
PRE_V3_009 = """
CREATE TABLE nodes (
    id    TEXT PRIMARY KEY,
    type  TEXT NOT NULL,
    label TEXT NOT NULL
);
CREATE TABLE staged_edges (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_chunk    TEXT NOT NULL REFERENCES nodes(id),
    target_chunk    TEXT NOT NULL REFERENCES nodes(id),
    edge_type       TEXT NOT NULL CHECK(edge_type IN ('PARALLELS','CONTRASTS','surface_only','unrelated')),
    confidence      REAL NOT NULL DEFAULT 0.0,
    justification   TEXT,
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending','accepted','rejected','reclassified')),
    tier            TEXT NOT NULL DEFAULT 'proposed'
                        CHECK(tier IN ('verified','proposed')),
    reviewed_by     TEXT,
    reviewed_at     TEXT,
    model           TEXT,
    prompt_version  TEXT
);
CREATE UNIQUE INDEX idx_staged_edges_provenance_unique
    ON staged_edges(source_chunk, target_chunk, model, prompt_version)
    WHERE status = 'pending';
"""


def _script(path: Path) -> str:
    """Migration text minus sqlite3-CLI dot-commands, which executescript
    cannot run."""
    return "\n".join(
        line for line in path.read_text().splitlines()
        if not line.startswith(".")
    )


def _node(conn: sqlite3.Connection, chunk_id: str) -> None:
    conn.execute("INSERT INTO nodes(id, type, label) VALUES(?, 'chunk', ?)",
                 (chunk_id, chunk_id))


def _columns(conn: sqlite3.Connection, table: str) -> list[tuple]:
    """(name, type, notnull, pk position) per column, ordered by name so the
    comparison is about shape rather than declaration order."""
    return sorted(
        (r[1], r[2].upper(), r[3], r[5])
        for r in conn.execute(f"PRAGMA table_info({table})")
    )


@pytest.fixture()
def from_schema_sql() -> sqlite3.Connection:
    """A database as a fresh checkout builds it."""
    c = sqlite3.connect(":memory:")
    c.executescript(SCHEMA_SQL.read_text())
    yield c
    c.close()


@pytest.fixture()
def from_migration() -> sqlite3.Connection:
    """A workbench database: pre-v3_009 state, migrations applied."""
    c = sqlite3.connect(":memory:")
    c.executescript(PRE_V3_009)
    for name in EDGE_SCHEMA_MIGRATIONS:
        c.executescript(_script(MIGRATIONS_DIR / name))
    yield c
    c.close()


# ── the migration does what it says ──────────────────────────────────────────

def test_migration_adds_staged_edges_columns(from_migration):
    cols = {r[0] for r in _columns(from_migration, "staged_edges")}
    assert {"similarity", "presentation_order"} <= cols


def test_migration_preserves_existing_rows(from_migration):
    """Additive only: ALTER TABLE ADD COLUMN, no table recreation."""
    _node(from_migration, "a")
    _node(from_migration, "b")
    from_migration.execute(
        """INSERT INTO staged_edges(source_chunk, target_chunk, edge_type)
           VALUES('a','b','PARALLELS')""")
    row = from_migration.execute(
        "SELECT similarity, presentation_order FROM staged_edges").fetchone()
    assert row == (None, None)


def test_presentation_order_check_constraint(from_migration):
    _node(from_migration, "a")
    _node(from_migration, "b")
    with pytest.raises(sqlite3.IntegrityError):
        from_migration.execute(
            """INSERT INTO staged_edges
                   (source_chunk, target_chunk, edge_type, presentation_order)
               VALUES('a','b','PARALLELS','sideways')""")


@pytest.mark.parametrize("fixture", ["from_schema_sql", "from_migration"])
def test_edge_progress_keyed_by_provenance(fixture, request):
    """The bug this PK fixes: with chunk_id alone, a second model's sweep
    silently replaces the first's record, so per-model coverage — the
    Phase 2 question — becomes unanswerable."""
    conn = request.getfixturevalue(fixture)
    _node(conn, "c1")
    for model in ("mistral.gguf", "qwen.gguf"):
        conn.execute(
            """INSERT OR REPLACE INTO edge_progress
                   (chunk_id, model, prompt_version, top_n, min_similarity)
               VALUES('c1', ?, 'v2', 5, 0.75)""", (model,))
    assert conn.execute("SELECT COUNT(*) FROM edge_progress").fetchone()[0] == 2

    # Same provenance twice is still one row, latest wins.
    conn.execute(
        """INSERT OR REPLACE INTO edge_progress
               (chunk_id, model, prompt_version, top_n, min_similarity)
           VALUES('c1', 'qwen.gguf', 'v2', 50, NULL)""")
    assert conn.execute("SELECT COUNT(*) FROM edge_progress").fetchone()[0] == 2
    assert conn.execute(
        "SELECT top_n, min_similarity FROM edge_progress WHERE model='qwen.gguf'"
    ).fetchone() == (50, None)


# ── schema.sql and the migration agree ───────────────────────────────────────

def test_schema_sql_matches_migration_staged_edges(from_schema_sql, from_migration):
    assert _columns(from_schema_sql, "staged_edges") == \
           _columns(from_migration, "staged_edges")


def test_schema_sql_matches_migration_edge_progress(from_schema_sql, from_migration):
    assert _columns(from_schema_sql, "edge_progress") == \
           _columns(from_migration, "edge_progress")


def test_schema_sql_has_edge_indexes(from_schema_sql, from_migration):
    def indexes(conn):
        return {r[0] for r in conn.execute(
            """SELECT name FROM sqlite_master WHERE type='index'
                 AND tbl_name IN ('staged_edges','edge_progress')
                 AND name NOT LIKE 'sqlite_%'""")}
    assert indexes(from_migration) <= indexes(from_schema_sql)
