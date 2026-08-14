"""tests/test_migration_v3_011.py — staged_edges Pass C retirement (todo:aaaa5258).

Two jobs, mirroring test_migration_v3_009.py:

1. The migration does what it claims against a pre-migration database:
   extends the status CHECK with 'retired_passc' and transitions every
   'pending' row to it, without dropping the table or deleting a row.
   --dry-run writes nothing; --apply is idempotent.

2. scripts/schema.sql agrees with the migration — a fresh checkout must
   accept the same terminal status the migration writes into existing DBs.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
SCHEMA_SQL = PROJECT_ROOT / "scripts" / "schema.sql"
MIGRATION_PATH = (PROJECT_ROOT / "scripts" / "migrations"
                   / "v3_011_staged_edges_retire_pending.py")

# staged_edges as v3_010 left it — the pre-migration state this migration must
# upgrade. Frozen historical snapshot, mirrors test_migration_v3_009's
# PRE_V3_009: it describes what was, so unlike an inline copy of the *current*
# schema it cannot drift.
PRE_V3_011 = """
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
    prompt_version  TEXT,
    similarity      REAL,
    presentation_order TEXT CHECK(presentation_order IN ('ab','ba'))
);
CREATE UNIQUE INDEX idx_staged_edges_provenance_unique
    ON staged_edges(source_chunk, target_chunk, model, prompt_version)
    WHERE status = 'pending';
CREATE UNIQUE INDEX idx_staged_edges_model_negative_unique
    ON staged_edges(source_chunk, target_chunk, model, prompt_version)
    WHERE status = 'rejected' AND reviewed_by = 'model-negative';
"""


def _load_migration():
    spec = importlib.util.spec_from_file_location("v3_011_migration", MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


migration = _load_migration()


def _node(conn: sqlite3.Connection, chunk_id: str) -> None:
    conn.execute("INSERT INTO nodes(id, type, label) VALUES(?, 'chunk', ?)",
                 (chunk_id, chunk_id))


def _edge(conn: sqlite3.Connection, src: str, tgt: str, status: str = "pending",
          **extra) -> None:
    cols = ["source_chunk", "target_chunk", "edge_type", "status", *extra]
    vals = [src, tgt, "PARALLELS", status, *extra.values()]
    placeholders = ",".join("?" for _ in vals)
    conn.execute(f"INSERT INTO staged_edges({','.join(cols)}) VALUES({placeholders})", vals)


@pytest.fixture()
def pre_db(tmp_path):
    """A file-backed pre-v3_011 database — the migration connects by path,
    not by in-memory handle, so the fixture must too."""
    path = tmp_path / "pre.db"
    conn = sqlite3.connect(path)
    conn.executescript(PRE_V3_011)
    yield path, conn
    conn.close()


# ── the migration does what it says ──────────────────────────────────────────


def test_dry_run_writes_nothing(pre_db):
    path, conn = pre_db
    _node(conn, "a")
    _node(conn, "b")
    _edge(conn, "a", "b", status="pending")
    conn.commit()

    rc = migration.run(path, apply=False)
    assert rc == 0

    status = conn.execute("SELECT status FROM staged_edges").fetchone()[0]
    assert status == "pending", "dry-run must not transition rows"
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='staged_edges'").fetchone()[0]
    assert "retired_passc" not in sql, "dry-run must not touch the CHECK constraint"


def test_apply_transitions_only_pending_rows(pre_db):
    path, conn = pre_db
    _node(conn, "a")
    _node(conn, "b")
    _node(conn, "c")
    _edge(conn, "a", "b", status="pending")
    _edge(conn, "a", "c", status="accepted")
    _edge(conn, "b", "c", status="rejected")
    conn.commit()

    rc = migration.run(path, apply=True)
    assert rc == 0

    rows = dict(conn.execute(
        "SELECT status, COUNT(*) FROM staged_edges GROUP BY status").fetchall())
    assert rows == {"retired_passc": 1, "accepted": 1, "rejected": 1}


def test_apply_deletes_nothing_and_keeps_the_table(pre_db):
    path, conn = pre_db
    _node(conn, "a")
    _node(conn, "b")
    _edge(conn, "a", "b", status="pending")
    _edge(conn, "a", "b", status="accepted")
    conn.commit()
    before_total = conn.execute("SELECT COUNT(*) FROM staged_edges").fetchone()[0]

    migration.run(path, apply=True)

    assert conn.execute(
        "SELECT COUNT(*) FROM staged_edges").fetchone()[0] == before_total
    assert conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='staged_edges'"
    ).fetchone()[0] == 1


def test_apply_stamps_reviewed_by_and_reviewed_at(pre_db):
    path, conn = pre_db
    _node(conn, "a")
    _node(conn, "b")
    _edge(conn, "a", "b", status="pending")
    conn.commit()

    migration.run(path, apply=True)

    reviewed_by, reviewed_at = conn.execute(
        "SELECT reviewed_by, reviewed_at FROM staged_edges "
        "WHERE status='retired_passc'").fetchone()
    assert reviewed_by == "pass-c-retirement"
    assert reviewed_at


def test_apply_does_not_overwrite_an_existing_reviewed_by(pre_db):
    """A pending row that somehow already carries reviewed_by (a partial
    prior run, a hand edit) keeps it — COALESCE, not overwrite."""
    path, conn = pre_db
    _node(conn, "a")
    _node(conn, "b")
    _edge(conn, "a", "b", status="pending", reviewed_by="somebody")
    conn.commit()

    migration.run(path, apply=True)

    reviewed_by = conn.execute(
        "SELECT reviewed_by FROM staged_edges").fetchone()[0]
    assert reviewed_by == "somebody"


def test_migration_is_idempotent(pre_db):
    path, conn = pre_db
    _node(conn, "a")
    _node(conn, "b")
    _edge(conn, "a", "b", status="pending")
    conn.commit()

    migration.run(path, apply=True)
    first = conn.execute(
        "SELECT id, status, reviewed_at FROM staged_edges ORDER BY id").fetchall()

    rc = migration.run(path, apply=True)
    assert rc == 0
    second = conn.execute(
        "SELECT id, status, reviewed_at FROM staged_edges ORDER BY id").fetchall()
    assert first == second


def test_indexes_survive_the_rebuild(pre_db):
    path, conn = pre_db
    _node(conn, "a")
    _node(conn, "b")
    _edge(conn, "a", "b", status="pending")
    conn.commit()

    migration.run(path, apply=True)

    idx = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='staged_edges'")}
    assert {
        "idx_staged_edges_source", "idx_staged_edges_target",
        "idx_staged_edges_status", "idx_staged_edges_type",
        "idx_staged_edges_provenance_unique",
        "idx_staged_edges_model_negative_unique",
    } <= idx


def test_schema_extends_even_when_nothing_is_pending(pre_db):
    """apply always ensures the CHECK includes retired_passc, whether or not
    there is a pending row to move — a DB with zero pending rows still gets
    the schema step. Only a *second* application, once the CHECK is already
    extended, is a genuine no-op."""
    path, conn = pre_db
    _node(conn, "a")
    _node(conn, "b")
    _edge(conn, "a", "b", status="accepted")
    conn.commit()

    rc = migration.run(path, apply=True)
    assert rc == 0
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='staged_edges'").fetchone()[0]
    assert "retired_passc" in sql

    before = conn.execute(
        "SELECT id, status, reviewed_at FROM staged_edges ORDER BY id").fetchall()
    rc2 = migration.run(path, apply=True)
    assert rc2 == 0
    after = conn.execute(
        "SELECT id, status, reviewed_at FROM staged_edges ORDER BY id").fetchall()
    assert before == after, "schema already extended, nothing pending — true no-op"


# ── schema.sql agrees ────────────────────────────────────────────────────────


def test_schema_sql_accepts_retired_passc():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA_SQL.read_text())
    conn.execute(
        "INSERT INTO nodes(id, type, label) VALUES ('a','chunk','a'), ('b','chunk','b')")
    conn.execute(
        "INSERT INTO staged_edges(source_chunk,target_chunk,edge_type,status) "
        "VALUES('a','b','PARALLELS','retired_passc')")
    status = conn.execute("SELECT status FROM staged_edges").fetchone()[0]
    assert status == "retired_passc"


def test_schema_sql_still_rejects_an_unknown_status():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA_SQL.read_text())
    conn.execute(
        "INSERT INTO nodes(id, type, label) VALUES ('a','chunk','a'), ('b','chunk','b')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO staged_edges(source_chunk,target_chunk,edge_type,status) "
            "VALUES('a','b','PARALLELS','made_up_status')")
