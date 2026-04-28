"""tests/test_migration_v3_004.py — chunk_id normalization migration (todo:9e650f2c).

Builds a small in-memory DB matching the schema's chunk_id columns,
applies scripts/migrations/v3_004_normalize_chunk_ids.sql, and checks
that every chunk_id reference is normalized + foreign_key_check passes.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
MIGRATION = PROJECT_ROOT / "scripts" / "migrations" / "v3_004_normalize_chunk_ids.sql"


# Minimal schema covering every chunk_id-shaped column the migration touches.
SCHEMA = """
CREATE TABLE nodes (
    id            TEXT PRIMARY KEY,
    type          TEXT NOT NULL,
    tradition_id  TEXT REFERENCES nodes(id),
    label         TEXT NOT NULL
);
CREATE TABLE edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id  TEXT NOT NULL REFERENCES nodes(id),
    target_id  TEXT NOT NULL REFERENCES nodes(id),
    type       TEXT NOT NULL,
    tier       TEXT NOT NULL DEFAULT 'inferred'
);
CREATE TABLE chunk_embeddings (
    chunk_id  TEXT PRIMARY KEY REFERENCES nodes(id) ON DELETE CASCADE,
    dim       INTEGER NOT NULL,
    model     TEXT NOT NULL,
    vector    BLOB NOT NULL
);
CREATE TABLE staged_tags (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id   TEXT NOT NULL REFERENCES nodes(id),
    concept_id TEXT NOT NULL,
    score      INTEGER NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE staged_edges (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source_chunk  TEXT NOT NULL REFERENCES nodes(id),
    target_chunk  TEXT NOT NULL REFERENCES nodes(id),
    edge_type     TEXT NOT NULL,
    confidence    REAL NOT NULL DEFAULT 0.0,
    status        TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE tagging_progress (
    chunk_id     TEXT PRIMARY KEY REFERENCES nodes(id),
    completed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TABLE staged_concepts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    proposed_id       TEXT NOT NULL UNIQUE,
    definition        TEXT NOT NULL,
    motivating_chunk  TEXT REFERENCES nodes(id),
    status            TEXT NOT NULL DEFAULT 'pending'
);
"""


def _seed(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    # Tradition rows (already snake_case — left untouched by migration)
    conn.executemany("INSERT INTO nodes(id, type, label) VALUES(?, 'tradition', ?)", [
        ("buddhism", "Buddhism"),
        ("greek_mystery", "Greek Mystery"),
        ("christian_mysticism", "Christian Mysticism"),
        ("gnosticism", "Gnosticism"),
    ])
    # Chunk rows in display-name form (one per affected case shape)
    conn.executemany(
        "INSERT INTO nodes(id, type, tradition_id, label) VALUES(?, 'chunk', ?, ?)",
        [
            ("Buddhism.diamond.001",                "buddhism",            "B1"),
            ("Greek Mystery.orphic.063",            "greek_mystery",       "G1"),
            ("Christian Mysticism.boehme.001",      "christian_mysticism", "C1"),
            # Already-correct row to verify it stays untouched
            ("gnosticism.thomas.077",               "gnosticism",          "G2"),
        ],
    )
    # An edge spanning two display-name chunks
    conn.execute(
        "INSERT INTO edges(source_id, target_id, type, tier) "
        "VALUES('Buddhism.diamond.001', 'Greek Mystery.orphic.063', 'PARALLELS', 'proposed')"
    )
    # An edge involving an already-correct chunk
    conn.execute(
        "INSERT INTO edges(source_id, target_id, type, tier) "
        "VALUES('gnosticism.thomas.077', 'Christian Mysticism.boehme.001', 'PARALLELS', 'verified')"
    )
    # chunk_embeddings: dummy 4-byte blob to satisfy NOT NULL
    conn.executemany(
        "INSERT INTO chunk_embeddings(chunk_id, dim, model, vector) VALUES(?, 1, 'test', ?)",
        [
            ("Buddhism.diamond.001",           b"\x00\x00\x80\x3f"),
            ("Greek Mystery.orphic.063",       b"\x00\x00\x80\x3f"),
            ("Christian Mysticism.boehme.001", b"\x00\x00\x80\x3f"),
        ],
    )
    # staged_tags
    conn.executemany(
        "INSERT INTO staged_tags(chunk_id, concept_id, score) VALUES(?, ?, 3)",
        [
            ("Buddhism.diamond.001",           "emptiness"),
            ("Christian Mysticism.boehme.001", "divine_light"),
        ],
    )
    # staged_edges
    conn.execute(
        "INSERT INTO staged_edges(source_chunk, target_chunk, edge_type, confidence) "
        "VALUES('Greek Mystery.orphic.063', 'Buddhism.diamond.001', 'PARALLELS', 0.9)"
    )
    # tagging_progress
    conn.execute("INSERT INTO tagging_progress(chunk_id) VALUES('Buddhism.diamond.001')")
    conn.execute("INSERT INTO tagging_progress(chunk_id) VALUES('gnosticism.thomas.077')")
    # staged_concepts (with a motivating_chunk for coverage)
    conn.execute(
        "INSERT INTO staged_concepts(proposed_id, definition, motivating_chunk) "
        "VALUES('new_concept', 'a definition', 'Christian Mysticism.boehme.001')"
    )
    conn.commit()


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    _seed(c)
    yield c
    c.close()


def _apply_migration(conn: sqlite3.Connection) -> None:
    sql = MIGRATION.read_text()
    # The migration toggles PRAGMA foreign_keys outside the transaction,
    # which works the same way against an in-memory DB.
    conn.executescript(sql)


# ── full-graph migration ───────────────────────────────────────────────


def test_migration_normalizes_every_chunk_id_column(conn):
    _apply_migration(conn)

    # nodes — chunk rows should all be snake_case now
    chunks = [r[0] for r in conn.execute(
        "SELECT id FROM nodes WHERE type='chunk' ORDER BY id"
    ).fetchall()]
    assert chunks == [
        "buddhism.diamond.001",
        "christian_mysticism.boehme.001",
        "gnosticism.thomas.077",
        "greek_mystery.orphic.063",
    ]

    # edges — both endpoint columns rewritten
    edges = sorted(conn.execute("SELECT source_id, target_id FROM edges").fetchall())
    assert edges == [
        ("buddhism.diamond.001",   "greek_mystery.orphic.063"),
        ("gnosticism.thomas.077",  "christian_mysticism.boehme.001"),
    ]

    # chunk_embeddings — PK rewritten
    embed_ids = sorted(r[0] for r in conn.execute("SELECT chunk_id FROM chunk_embeddings"))
    assert embed_ids == [
        "buddhism.diamond.001",
        "christian_mysticism.boehme.001",
        "greek_mystery.orphic.063",
    ]

    # staged_tags
    tag_chunks = sorted(r[0] for r in conn.execute("SELECT chunk_id FROM staged_tags"))
    assert tag_chunks == ["buddhism.diamond.001", "christian_mysticism.boehme.001"]

    # staged_edges
    se_rows = sorted(conn.execute("SELECT source_chunk, target_chunk FROM staged_edges").fetchall())
    assert se_rows == [("greek_mystery.orphic.063", "buddhism.diamond.001")]

    # tagging_progress — both should be present, both snake_case
    tp_rows = sorted(r[0] for r in conn.execute("SELECT chunk_id FROM tagging_progress"))
    assert tp_rows == ["buddhism.diamond.001", "gnosticism.thomas.077"]

    # staged_concepts — motivating_chunk rewritten
    sc_motiv = conn.execute("SELECT motivating_chunk FROM staged_concepts").fetchone()[0]
    assert sc_motiv == "christian_mysticism.boehme.001"


def test_migration_leaves_no_fk_violations(conn):
    _apply_migration(conn)
    violations = list(conn.execute("PRAGMA foreign_key_check"))
    assert violations == [], f"FK violations after migration: {violations}"


def test_migration_does_not_touch_already_correct_rows(conn):
    """The gnosticism.* row is already snake_case — its id must be byte-
    identical after the migration runs."""
    _apply_migration(conn)
    row = conn.execute(
        "SELECT id FROM nodes WHERE id = 'gnosticism.thomas.077'"
    ).fetchone()
    assert row is not None
    assert row[0] == "gnosticism.thomas.077"


def test_migration_idempotent(conn):
    """Running it twice should be a no-op the second time — no rows change,
    no errors. Confirms the WHERE clauses correctly skip already-rewritten
    ids."""
    _apply_migration(conn)
    snap1 = sorted(conn.execute("SELECT id FROM nodes ORDER BY id").fetchall())
    _apply_migration(conn)
    snap2 = sorted(conn.execute("SELECT id FROM nodes ORDER BY id").fetchall())
    assert snap1 == snap2


def test_migration_preserves_row_counts(conn):
    """Row counts in every affected table must be unchanged — the migration
    rewrites in place, never inserts or deletes."""
    counts_before = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("nodes", "edges", "chunk_embeddings", "staged_tags",
                  "staged_edges", "tagging_progress", "staged_concepts")
    }
    _apply_migration(conn)
    counts_after = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in counts_before
    }
    assert counts_before == counts_after


def test_tradition_rows_in_nodes_untouched(conn):
    """nodes.tradition_id can reference other nodes(id) — but tradition
    rows are already snake_case. The migration's WHERE filters on
    type='chunk', so tradition rows must be byte-identical post-run."""
    before = sorted(conn.execute(
        "SELECT id FROM nodes WHERE type='tradition' ORDER BY id"
    ).fetchall())
    _apply_migration(conn)
    after = sorted(conn.execute(
        "SELECT id FROM nodes WHERE type='tradition' ORDER BY id"
    ).fetchall())
    assert before == after
