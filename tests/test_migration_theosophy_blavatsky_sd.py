"""tests/test_migration_theosophy_blavatsky_sd.py — tradition swap (todo:4ea3dcc5).

Miniature in-memory graph: western_esoteric + optional theosophy tradition
nodes, 2–3 blavatsky-sd chunks, one other western_esoteric chunk that must
NOT move, BELONGS_TO + EXPRESSES edges, embeddings, tagging_progress,
JSON child_chunk_ids (mixed array), summary_nodes, work_dossiers.

Does not touch data/guru.db.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import tomllib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
MIGRATION_PATH = (
    PROJECT_ROOT / "scripts" / "migrations"
    / "theosophy_blavatsky_sd_tradition_swap.py"
)
MANIFEST = PROJECT_ROOT / "sources" / "manifest.toml"
CHUNKING = PROJECT_ROOT / "chunking" / "theosophy" / "blavatsky-sd.toml"

OLD_PREFIX = "western_esoteric.blavatsky-sd."
NEW_PREFIX = "theosophy.blavatsky-sd."

SCHEMA = """
CREATE TABLE nodes (
    id            TEXT PRIMARY KEY,
    type          TEXT NOT NULL,
    tradition_id  TEXT REFERENCES nodes(id),
    label         TEXT NOT NULL,
    metadata_json TEXT DEFAULT '{}'
);
CREATE TABLE edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id  TEXT NOT NULL REFERENCES nodes(id),
    target_id  TEXT NOT NULL REFERENCES nodes(id),
    type       TEXT NOT NULL,
    tier       TEXT NOT NULL DEFAULT 'inferred',
    justification TEXT
);
CREATE TABLE chunk_embeddings (
    chunk_id  TEXT PRIMARY KEY REFERENCES nodes(id) ON DELETE CASCADE,
    dim       INTEGER NOT NULL,
    model     TEXT NOT NULL,
    vector    BLOB NOT NULL
);
CREATE TABLE tagging_progress (
    chunk_id     TEXT PRIMARY KEY REFERENCES nodes(id),
    completed_at TEXT NOT NULL DEFAULT 'now'
);
CREATE TABLE staged_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id TEXT NOT NULL REFERENCES nodes(id),
    concept_id TEXT NOT NULL,
    score INTEGER NOT NULL,
    justification TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE staged_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_chunk TEXT NOT NULL REFERENCES nodes(id),
    target_chunk TEXT NOT NULL REFERENCES nodes(id),
    edge_type TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE staged_cleanups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id TEXT NOT NULL REFERENCES nodes(id),
    original_body TEXT NOT NULL,
    proposed_body TEXT NOT NULL
);
CREATE TABLE staged_concepts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposed_id TEXT NOT NULL UNIQUE,
    definition TEXT NOT NULL,
    motivating_chunk TEXT REFERENCES nodes(id),
    status TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE edge_progress (
    chunk_id TEXT NOT NULL REFERENCES nodes(id),
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    PRIMARY KEY (chunk_id, model, prompt_version)
);
CREATE TABLE staged_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    summary_id TEXT NOT NULL,
    work_id TEXT NOT NULL,
    text_id TEXT,
    level INTEGER NOT NULL,
    child_chunk_ids TEXT,
    body TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL
);
CREATE TABLE summary_nodes (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL,
    text_id TEXT,
    tradition TEXT NOT NULL,
    level INTEGER NOT NULL,
    child_chunk_ids TEXT NOT NULL,
    body TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    generated_by TEXT NOT NULL,
    children_hash TEXT NOT NULL
);
CREATE TABLE work_dossiers (
    work_id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    context TEXT NOT NULL,
    structure_json TEXT NOT NULL,
    key_figures_json TEXT NOT NULL DEFAULT '[]',
    key_terms_json TEXT NOT NULL DEFAULT '[]',
    themes_json TEXT NOT NULL DEFAULT '[]',
    generated_by TEXT NOT NULL DEFAULT 'test'
);
CREATE TABLE derived_parallels (
    run_id     INTEGER NOT NULL,
    source     TEXT NOT NULL,
    target     TEXT NOT NULL,
    weight     REAL NOT NULL,
    annotation TEXT
);
"""


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "theosophy_blavatsky_sd_tradition_swap", MIGRATION_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


migration = _load_migration()


def _seed(conn: sqlite3.Connection, *, theosophy_exists: bool = False) -> None:
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT INTO nodes(id, type, label) VALUES('western_esoteric', 'tradition', 'Western Esoteric')"
    )
    if theosophy_exists:
        conn.execute(
            "INSERT INTO nodes(id, type, label) VALUES('theosophy', 'tradition', 'Theosophy')"
        )
    conn.execute(
        "INSERT INTO nodes(id, type, label) VALUES('sevenfold_cosmos', 'concept', 'Sevenfold Cosmos')"
    )
    chunks = [
        (f"{OLD_PREFIX}001", "western_esoteric", "SD 1",
         json.dumps({"text_id": "blavatsky-sd"})),
        (f"{OLD_PREFIX}002", "western_esoteric", "SD 2",
         json.dumps({"text_id": "blavatsky-sd"})),
        (f"{OLD_PREFIX}003", "western_esoteric", "SD 3",
         json.dumps({"text_id": "blavatsky-sd"})),
        ("western_esoteric.kybalion.001", "western_esoteric", "Kybalion 1",
         json.dumps({"text_id": "kybalion"})),
    ]
    conn.executemany(
        "INSERT INTO nodes(id, type, tradition_id, label, metadata_json) "
        "VALUES(?, 'chunk', ?, ?, ?)",
        chunks,
    )
    # BELONGS_TO — three blavatsky + one kybalion, all currently western_esoteric
    for cid, _trad, _label, _meta in chunks:
        conn.execute(
            "INSERT INTO edges(source_id, target_id, type) VALUES(?, 'western_esoteric', 'BELONGS_TO')",
            (cid,),
        )
    conn.execute(
        "INSERT INTO edges(source_id, target_id, type, justification) "
        "VALUES(?, 'sevenfold_cosmos', 'EXPRESSES', ?)",
        (f"{OLD_PREFIX}001", f"mentions {OLD_PREFIX}001 only as prose"),
    )
    conn.execute(
        "INSERT INTO edges(source_id, target_id, type) "
        "VALUES('western_esoteric.kybalion.001', 'sevenfold_cosmos', 'EXPRESSES')"
    )
    blob = b"\x00\x00\x80\x3f"
    for cid in (f"{OLD_PREFIX}001", f"{OLD_PREFIX}002", "western_esoteric.kybalion.001"):
        conn.execute(
            "INSERT INTO chunk_embeddings(chunk_id, dim, model, vector) VALUES(?, 1, 'test', ?)",
            (cid, blob),
        )
    conn.execute("INSERT INTO tagging_progress(chunk_id) VALUES(?)", (f"{OLD_PREFIX}001",))
    conn.execute("INSERT INTO tagging_progress(chunk_id) VALUES('western_esoteric.kybalion.001')")
    conn.execute(
        "INSERT INTO staged_tags(chunk_id, concept_id, score, justification) "
        "VALUES(?, 'sevenfold_cosmos', 3, ?)",
        (f"{OLD_PREFIX}002", f"see also {OLD_PREFIX}001 in the commentary"),
    )
    conn.execute(
        "INSERT INTO staged_edges(source_chunk, target_chunk, edge_type) "
        "VALUES(?, 'western_esoteric.kybalion.001', 'PARALLELS')",
        (f"{OLD_PREFIX}003",),
    )
    conn.execute(
        "INSERT INTO staged_cleanups(chunk_id, original_body, proposed_body) "
        "VALUES(?, 'old', 'new')",
        (f"{OLD_PREFIX}001",),
    )
    conn.execute(
        "INSERT INTO staged_concepts(proposed_id, definition, motivating_chunk) "
        "VALUES('root_races', 'def', ?)",
        (f"{OLD_PREFIX}002",),
    )
    conn.execute(
        "INSERT INTO edge_progress(chunk_id, model, prompt_version) VALUES(?, 'm', 'v1')",
        (f"{OLD_PREFIX}001",),
    )
    mixed = json.dumps([
        f"{OLD_PREFIX}001",
        "western_esoteric.kybalion.001",
        f"{OLD_PREFIX}002",
    ])
    conn.execute(
        "INSERT INTO staged_summaries(summary_id, work_id, text_id, level, "
        "child_chunk_ids, body, token_count, model, prompt_version) "
        "VALUES('sum:blavatsky-sd:p1', 'blavatsky-sd', 'blavatsky-sd', 1, ?, 'body', 10, 'm', 'v')",
        (mixed,),
    )
    conn.execute(
        "INSERT INTO summary_nodes(id, work_id, text_id, tradition, level, "
        "child_chunk_ids, body, token_count, generated_by, children_hash) "
        "VALUES('sum:blavatsky-sd:p1', 'blavatsky-sd', 'blavatsky-sd', 'western_esoteric', "
        "1, ?, 'body', 10, 'm', 'hash')",
        (mixed,),
    )
    structure = json.dumps([
        {
            "section_span": "Page 1",
            "title": "Proem",
            "chunk_ids": [f"{OLD_PREFIX}001", f"{OLD_PREFIX}002"],
            "note": f"compare {OLD_PREFIX}001 in a non-id field",
        }
    ])
    conn.execute(
        "INSERT INTO work_dossiers(work_id, summary, context, structure_json) "
        "VALUES('blavatsky-sd', 'sum', 'ctx', ?)",
        (structure,),
    )
    # derived_parallels: one blavatsky→kybalion row (source moves), one
    # kybalion→blavatsky row (target moves), one unrelated row (untouched).
    conn.executemany(
        "INSERT INTO derived_parallels(run_id, source, target, weight, annotation) "
        "VALUES(1, ?, ?, 0.9, 'ann')",
        [
            (f"{OLD_PREFIX}001", "western_esoteric.kybalion.001"),
            ("western_esoteric.kybalion.001", f"{OLD_PREFIX}002"),
        ],
    )
    conn.commit()


def _apply(conn: sqlite3.Connection) -> dict:
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("BEGIN")
    try:
        result = migration.apply_swap(conn)
        conn.execute("COMMIT")
        return result
    except migration.MigrationAbort:
        conn.execute("ROLLBACK")
        raise


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    _seed(c)
    yield c
    c.close()


def _snapshot(conn: sqlite3.Connection) -> dict:
    return {
        "nodes": list(conn.execute("SELECT id, type, tradition_id, metadata_json FROM nodes ORDER BY id")),
        "edges": list(conn.execute("SELECT source_id, target_id, type, justification FROM edges ORDER BY id")),
        "emb": list(conn.execute("SELECT chunk_id FROM chunk_embeddings ORDER BY chunk_id")),
        "tp": list(conn.execute("SELECT chunk_id FROM tagging_progress ORDER BY chunk_id")),
        "st": list(conn.execute("SELECT chunk_id, justification FROM staged_tags")),
        "se": list(conn.execute("SELECT source_chunk, target_chunk FROM staged_edges")),
        "sc": list(conn.execute("SELECT chunk_id FROM staged_cleanups")),
        "sconc": list(conn.execute("SELECT motivating_chunk FROM staged_concepts")),
        "ep": list(conn.execute("SELECT chunk_id FROM edge_progress")),
        "ss": list(conn.execute("SELECT child_chunk_ids FROM staged_summaries")),
        "sn": list(conn.execute("SELECT child_chunk_ids, tradition FROM summary_nodes")),
        "wd": list(conn.execute("SELECT structure_json FROM work_dossiers")),
        "dp": list(conn.execute("SELECT source, target FROM derived_parallels ORDER BY source, target")),
    }


def test_dry_run_does_not_mutate(conn, tmp_path):
    before = _snapshot(conn)
    db = tmp_path / "guru.db"
    # File-backed copy of the same seed for CLI dry-run.
    disk = sqlite3.connect(db)
    _seed(disk)
    disk.close()
    rc = migration.run_db(db, apply=False)
    assert rc == 0
    after_disk = sqlite3.connect(db)
    # Compare against an independently seeded memory snap of the same shape.
    assert _snapshot(conn) == before
    disk_nodes = [
        r[0] for r in after_disk.execute(
            "SELECT id FROM nodes WHERE type='chunk' ORDER BY id"
        )
    ]
    assert f"{OLD_PREFIX}001" in disk_nodes
    assert f"{NEW_PREFIX}001" not in disk_nodes
    after_disk.close()


def test_apply_rewrites_only_blavatsky(conn):
    result = _apply(conn)
    assert result["status"] == "applied"
    assert result["theosophy_created"] is True

    chunks = [
        r[0] for r in conn.execute(
            "SELECT id FROM nodes WHERE type='chunk' ORDER BY id"
        )
    ]
    assert chunks == [
        f"{NEW_PREFIX}001",
        f"{NEW_PREFIX}002",
        f"{NEW_PREFIX}003",
        "western_esoteric.kybalion.001",
    ]
    trads = dict(conn.execute(
        "SELECT id, tradition_id FROM nodes WHERE type='chunk'"
    ))
    assert trads[f"{NEW_PREFIX}001"] == "theosophy"
    assert trads["western_esoteric.kybalion.001"] == "western_esoteric"

    meta = conn.execute(
        "SELECT metadata_json FROM nodes WHERE id=?", (f"{NEW_PREFIX}001",)
    ).fetchone()[0]
    assert json.loads(meta)["text_id"] == "blavatsky-sd"

    belongs = list(conn.execute(
        "SELECT source_id, target_id FROM edges WHERE type='BELONGS_TO' ORDER BY source_id"
    ))
    assert (f"{NEW_PREFIX}001", "theosophy") in belongs
    assert (f"{NEW_PREFIX}002", "theosophy") in belongs
    assert (f"{NEW_PREFIX}003", "theosophy") in belongs
    assert ("western_esoteric.kybalion.001", "western_esoteric") in belongs
    assert all(t != "western_esoteric" for s, t in belongs if s.startswith(NEW_PREFIX))

    expresses = list(conn.execute(
        "SELECT source_id, target_id FROM edges WHERE type='EXPRESSES' ORDER BY source_id"
    ))
    assert (f"{NEW_PREFIX}001", "sevenfold_cosmos") in expresses
    assert ("western_esoteric.kybalion.001", "sevenfold_cosmos") in expresses

    just = conn.execute(
        "SELECT justification FROM edges WHERE type='EXPRESSES' AND source_id=?",
        (f"{NEW_PREFIX}001",),
    ).fetchone()[0]
    assert OLD_PREFIX in just  # prose mention not smashed

    emb = [r[0] for r in conn.execute("SELECT chunk_id FROM chunk_embeddings ORDER BY chunk_id")]
    assert emb == [
        f"{NEW_PREFIX}001",
        f"{NEW_PREFIX}002",
        "western_esoteric.kybalion.001",
    ]
    tp = [r[0] for r in conn.execute("SELECT chunk_id FROM tagging_progress ORDER BY chunk_id")]
    assert tp == [f"{NEW_PREFIX}001", "western_esoteric.kybalion.001"]

    tag_row = conn.execute("SELECT chunk_id, justification FROM staged_tags").fetchone()
    assert tag_row[0] == f"{NEW_PREFIX}002"
    assert OLD_PREFIX in tag_row[1]

    se = conn.execute("SELECT source_chunk, target_chunk FROM staged_edges").fetchone()
    assert se == (f"{NEW_PREFIX}003", "western_esoteric.kybalion.001")
    assert conn.execute("SELECT chunk_id FROM staged_cleanups").fetchone()[0] == f"{NEW_PREFIX}001"
    assert conn.execute("SELECT motivating_chunk FROM staged_concepts").fetchone()[0] == f"{NEW_PREFIX}002"
    assert conn.execute("SELECT chunk_id FROM edge_progress").fetchone()[0] == f"{NEW_PREFIX}001"

    mixed = json.loads(conn.execute("SELECT child_chunk_ids FROM staged_summaries").fetchone()[0])
    assert mixed == [
        f"{NEW_PREFIX}001",
        "western_esoteric.kybalion.001",
        f"{NEW_PREFIX}002",
    ]
    sn_ids, sn_trad = conn.execute(
        "SELECT child_chunk_ids, tradition FROM summary_nodes"
    ).fetchone()
    assert json.loads(sn_ids) == mixed
    assert sn_trad == "theosophy"

    structure = json.loads(conn.execute("SELECT structure_json FROM work_dossiers").fetchone()[0])
    assert structure[0]["chunk_ids"] == [f"{NEW_PREFIX}001", f"{NEW_PREFIX}002"]
    assert OLD_PREFIX in structure[0]["note"]  # non-id field mentioning prefix

    # derived_parallels chunk-id endpoints move; unrelated endpoints stay.
    dp = list(conn.execute("SELECT source, target FROM derived_parallels ORDER BY source, target"))
    assert dp == [
        (f"{NEW_PREFIX}001", "western_esoteric.kybalion.001"),
        ("western_esoteric.kybalion.001", f"{NEW_PREFIX}002"),
    ]

    # BELONGS_TO retarget is accounted for in the audit, not just left to a
    # visual scan of the edges table.
    assert result["before"]["belongs_old_tradition"] == 3
    assert result["after"]["belongs_new_tradition"] == 3
    assert result["after"]["belongs_old_tradition"] == 0


def test_foreign_key_check_empty(conn):
    _apply(conn)
    conn.execute("PRAGMA foreign_keys=ON")
    violations = list(conn.execute("PRAGMA foreign_key_check"))
    assert violations == [], violations


def test_second_apply_idempotent(conn):
    first = _apply(conn)
    assert first["status"] == "applied"
    snap = _snapshot(conn)
    second = _apply(conn)
    assert second["status"] == "already_swapped"
    assert _snapshot(conn) == snap


def test_collision_aborts(conn):
    conn.execute(
        "INSERT INTO nodes(id, type, tradition_id, label) "
        "VALUES(?, 'chunk', 'theosophy', 'collision')",
        (f"{NEW_PREFIX}001",),
    )
    conn.commit()
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("BEGIN")
    with pytest.raises(migration.MigrationAbort, match="collision"):
        migration.apply_swap(conn)
    conn.execute("ROLLBACK")
    # old rows still present
    assert conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE id=?", (f"{OLD_PREFIX}001",)
    ).fetchone()[0] == 1


def test_belongs_to_retarget_guard_aborts(conn, monkeypatch):
    """If the BELONGS_TO retarget is skipped, the audit guard must abort —
    a mistargeted edge (blavatsky chunk still → western_esoteric) can't pass
    silently. Simulate the regression by no-oping the retarget helper."""
    monkeypatch.setattr(migration, "_retarget_belongs_to", lambda con: None)
    with pytest.raises(migration.MigrationAbort, match="BELONGS_TO"):
        _apply(conn)
    # rolled back: old chunk nodes still present
    assert conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE id=?", (f"{OLD_PREFIX}001",)
    ).fetchone()[0] == 1


def test_derived_parallels_orphan_free_after_apply(conn):
    """No derived_parallels endpoint keeps the old prefix (export.py would
    SystemExit on such an orphan)."""
    _apply(conn)
    rows = list(conn.execute("SELECT source, target FROM derived_parallels"))
    assert rows, "seed should have derived_parallels rows"
    for source, target in rows:
        assert not source.startswith(OLD_PREFIX)
        assert not target.startswith(OLD_PREFIX)


def test_derived_parallels_both_endpoints_blavatsky(conn):
    """A row where source AND target are both blavatsky chunks: both columns
    move, verified independently (no double-count / PK-collision abort)."""
    conn.execute(
        "INSERT INTO derived_parallels(run_id, source, target, weight, annotation) "
        "VALUES(1, ?, ?, 0.8, 'ann')",
        (f"{OLD_PREFIX}001", f"{OLD_PREFIX}003"),
    )
    conn.commit()
    result = _apply(conn)
    assert result["status"] == "applied"
    row = conn.execute(
        "SELECT source, target FROM derived_parallels WHERE weight=0.8"
    ).fetchone()
    assert row == (f"{NEW_PREFIX}001", f"{NEW_PREFIX}003")


def test_json_rewrite_does_not_smash_unrelated_text():
    raw = json.dumps({
        "child_chunk_ids": [f"{OLD_PREFIX}001", "western_esoteric.kybalion.001"],
        "justification": f"the id {OLD_PREFIX}001 appears in commentary",
    })
    rewritten = json.loads(migration.remap_json_column(raw))
    assert rewritten["child_chunk_ids"][0] == f"{NEW_PREFIX}001"
    assert rewritten["child_chunk_ids"][1] == "western_esoteric.kybalion.001"
    assert rewritten["justification"] == f"the id {OLD_PREFIX}001 appears in commentary"
    naive = raw.replace(OLD_PREFIX, NEW_PREFIX)
    assert NEW_PREFIX in json.loads(naive)["justification"]


def test_optional_tables_probed(tmp_path):
    """A fixture with only nodes+edges still applies."""
    db = tmp_path / "mini.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE nodes (
            id TEXT PRIMARY KEY, type TEXT NOT NULL,
            tradition_id TEXT, label TEXT NOT NULL
        );
        CREATE TABLE edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL REFERENCES nodes(id),
            target_id TEXT NOT NULL REFERENCES nodes(id),
            type TEXT NOT NULL
        );
    """)
    con.execute("INSERT INTO nodes VALUES('western_esoteric','tradition',NULL,'WE')")
    con.execute(
        "INSERT INTO nodes VALUES(?,?,?,?)",
        (f"{OLD_PREFIX}001", "chunk", "western_esoteric", "c"),
    )
    con.execute(
        "INSERT INTO edges(source_id, target_id, type) VALUES(?,?, 'BELONGS_TO')",
        (f"{OLD_PREFIX}001", "western_esoteric"),
    )
    con.commit()
    con.execute("PRAGMA foreign_keys=OFF")
    con.execute("BEGIN")
    result = migration.apply_swap(con)
    con.execute("COMMIT")
    assert result["status"] == "applied"
    assert con.execute("SELECT id FROM nodes WHERE type='chunk'").fetchone()[0] == f"{NEW_PREFIX}001"
    assert con.execute("SELECT target_id FROM edges").fetchone()[0] == "theosophy"
    con.close()


def test_corpus_toml_rewriter(tmp_path):
    src = tmp_path / "001.toml"
    src.write_text(
        '[chunk]\n'
        f'id = "{OLD_PREFIX}001"\n'
        'tradition = "western_esoteric"\n'
        'text_name = "The Secret Doctrine"\n\n'
        '[content]\n'
        f'body = "see western_esoteric as a word and id {OLD_PREFIX}001 maybe"\n',
        encoding="utf-8",
    )
    assert migration.rewrite_chunk_toml(src) is True
    text = src.read_text(encoding="utf-8")
    assert f'id = "{NEW_PREFIX}001"' in text
    assert 'tradition = "theosophy"' in text
    # body left intact (replace on tradition field is count=1, id only in quoted id=)
    assert "see western_esoteric as a word" in text


def test_manifest_and_chunking_tradition_consistent():
    manifest = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
    sources = manifest["source"]
    ids = {s["id"] for s in sources}
    trads = {s["tradition"] for s in sources}
    assert "theosophy" not in ids
    blav = next(s for s in sources if s["id"] == "blavatsky-sd")
    assert blav["tradition"] == "theosophy"
    assert "theosophy" in trads
    chunking = tomllib.loads(CHUNKING.read_text(encoding="utf-8"))
    assert chunking["metadata"]["tradition"] == "theosophy"
    stale = PROJECT_ROOT / "chunking" / "western_esoteric" / "blavatsky-sd.toml"
    assert not stale.exists()
