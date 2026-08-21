"""tests/test_export_derived_edges.py — derived PARALLELS + frozen
CONTRASTS in the corpus dump (todo:6da4f965, parent c3f479ff).

scripts/export.py used to source every edge_type — including PARALLELS and
CONTRASTS — straight from the live `edges` table. This ticket splits that:
PARALLELS now comes exclusively from the derive_parallels.py artifact
(load_derived_parallels), CONTRASTS from a committed snapshot carried
through unchanged (load_frozen_contrasts), and load_edges() keeps serving
everything else (EXPRESSES, BELONGS_TO, DERIVES_FROM) from the live table.

Both new loaders must fail loudly (SystemExit) rather than silently
degrade to zero PARALLELS/CONTRASTS — that's the ticket's explicit
requirement, and it's the one behavior a regression here would hide
quietly until a prod load shipped an empty edges section.

PR #64 review added two more requirements covered here:
finding 1 — both loaders must be called from main() BEFORE
next_corpus_version() commits a version bump and before OUTPUT is
truncated, so their SystemExit guards fail fast rather than fail
destructive; emit_copies() takes pre-loaded rows as parameters and does no
loading of its own.
finding 2 — both loaders validate their rows' source/target against the
exported chunk id set when one is given, and SystemExit on any endpoint
that doesn't resolve (orphan endpoints self-heal for derived PARALLELS,
which is regenerated every run, but never for the frozen CONTRASTS
snapshot).
"""
from __future__ import annotations

import inspect
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import export  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────

MIGRATION_SQL = (PROJECT_ROOT / "scripts" / "migrations"
                 / "v3_012_derived_parallels.sql").read_text()


def _make_db(tmp_path: Path) -> Path:
    """A guru.db stand-in with the v3_012 tables — created from the real
    migration file, so these tests validate the shipped DDL."""
    db = tmp_path / "guru.db"
    conn = sqlite3.connect(db)
    conn.executescript(MIGRATION_SQL)
    conn.commit()
    conn.close()
    return db


def _insert_run(db: Path, rows: list[dict], *,
                generated_at: str | None = None,
                limit_concepts: int | None = None) -> int:
    conn = sqlite3.connect(db)
    with conn:
        cur = conn.execute(
            "INSERT INTO derived_runs (generated_at, limit_concepts, edge_rows, summary_json) "
            "VALUES (?, ?, ?, ?)",
            (generated_at or datetime.now(timezone.utc).isoformat(),
             limit_concepts, len(rows), json.dumps({"unique_edge_rows": len(rows)})),
        )
        run_id = cur.lastrowid
        conn.execute("DELETE FROM derived_parallels")
        conn.executemany(
            "INSERT INTO derived_parallels (run_id, source, target, weight, annotation) "
            "VALUES (?, ?, ?, ?, ?)",
            [(run_id, r["source"], r["target"], r["weight"], r["annotation"]) for r in rows],
        )
    conn.close()
    return run_id


def _open(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(db)


def _write_config(path: Path, max_age_days: float = 30) -> None:
    path.write_text(
        f'[scoring]\ntop_k = 5\n'
        f'model_path = "x"\nscore_cache = "x"\n'
        f'[panels]\nper_work_cap = 2\n'
        f'[export]\nmax_age_days = {max_age_days}\n'
    )


_SAMPLE_ROW = {
    "source": "buddhism.a.001", "target": "taoism.b.002",
    "edge_type": "PARALLELS", "tier": "inferred", "weight": 1.23,
    "annotation": "Shared concept: X — def. (derived)",
}


# ── load_derived_parallels (guru.db tables, todo:675a76f8) ─────────────

def test_load_derived_parallels_happy_path(tmp_path):
    db = _make_db(tmp_path)
    _insert_run(db, [_SAMPLE_ROW])
    cfg = tmp_path / "derived_parallels.toml"
    _write_config(cfg)

    rows = export.load_derived_parallels(_open(db), config_path=cfg)
    # edge_type/tier are reconstructed constants, not stored columns.
    assert rows == [_SAMPLE_ROW]


def test_load_derived_parallels_reads_latest_run(tmp_path):
    db = _make_db(tmp_path)
    _insert_run(db, [dict(_SAMPLE_ROW, source="older.chunk")])
    _insert_run(db, [dict(_SAMPLE_ROW, source="newer.chunk")])
    cfg = tmp_path / "derived_parallels.toml"
    _write_config(cfg)

    rows = export.load_derived_parallels(_open(db), config_path=cfg)
    assert [r["source"] for r in rows] == ["newer.chunk"]


def test_load_derived_parallels_missing_tables_fails_loudly(tmp_path):
    db = tmp_path / "bare.db"
    sqlite3.connect(db).close()
    cfg = tmp_path / "derived_parallels.toml"
    _write_config(cfg)

    with pytest.raises(SystemExit, match="derived-parallels tables"):
        export.load_derived_parallels(_open(db), config_path=cfg)


def test_load_derived_parallels_no_runs_fails_loudly(tmp_path):
    db = _make_db(tmp_path)
    cfg = tmp_path / "derived_parallels.toml"
    _write_config(cfg)

    with pytest.raises(SystemExit, match="No derived-parallels run"):
        export.load_derived_parallels(_open(db), config_path=cfg)


def test_load_derived_parallels_partial_run_fails_loudly(tmp_path):
    """The smoke-run trap, now enforced: a --limit-concepts run can no
    longer silently become the export's source (with the JSONL artifact it
    could — a partial run in the default dir simply won the lexicographic
    pick)."""
    db = _make_db(tmp_path)
    _insert_run(db, [_SAMPLE_ROW], limit_concepts=3)
    cfg = tmp_path / "derived_parallels.toml"
    _write_config(cfg)

    with pytest.raises(SystemExit, match="PARTIAL"):
        export.load_derived_parallels(_open(db), config_path=cfg)


def test_load_derived_parallels_stale_fails_loudly(tmp_path):
    db = _make_db(tmp_path)
    stale_ts = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    _insert_run(db, [_SAMPLE_ROW], generated_at=stale_ts)
    cfg = tmp_path / "derived_parallels.toml"
    _write_config(cfg, max_age_days=30)

    with pytest.raises(SystemExit, match="stale"):
        export.load_derived_parallels(_open(db), config_path=cfg)


def test_load_derived_parallels_empty_rows_fails_loudly(tmp_path):
    db = _make_db(tmp_path)
    _insert_run(db, [])
    cfg = tmp_path / "derived_parallels.toml"
    _write_config(cfg)

    with pytest.raises(SystemExit, match="zero PARALLELS"):
        export.load_derived_parallels(_open(db), config_path=cfg)


def test_load_derived_parallels_missing_config_fails_loudly(tmp_path):
    db = _make_db(tmp_path)
    with pytest.raises(SystemExit, match="not found"):
        export.load_derived_parallels(_open(db), config_path=tmp_path / "nope.toml")


def test_load_derived_parallels_orphan_endpoint_fails_loudly(tmp_path):
    """PR #64 review finding 2: a source/target that doesn't resolve to an
    exported chunk (e.g. a re-chunk shifted ids out from under a stale
    derived run) must SystemExit, not load silently."""
    db = _make_db(tmp_path)
    _insert_run(db, [_SAMPLE_ROW])
    cfg = tmp_path / "derived_parallels.toml"
    _write_config(cfg)

    with pytest.raises(SystemExit, match="do not resolve to a chunk"):
        export.load_derived_parallels(_open(db), config_path=cfg,
                                      chunk_ids={"some.other.chunk"})


def test_load_derived_parallels_passes_when_endpoints_resolve(tmp_path):
    db = _make_db(tmp_path)
    _insert_run(db, [_SAMPLE_ROW])
    cfg = tmp_path / "derived_parallels.toml"
    _write_config(cfg)

    rows = export.load_derived_parallels(
        _open(db), config_path=cfg,
        chunk_ids={_SAMPLE_ROW["source"], _SAMPLE_ROW["target"]},
    )
    assert rows == [_SAMPLE_ROW]


def test_load_derived_parallels_no_chunk_ids_skips_orphan_check(tmp_path):
    """chunk_ids=None (the default) skips the check entirely — used by
    callers (tests, ad hoc inspection) that aren't validating against a real
    exported chunk set. main() always passes the real set in production."""
    db = _make_db(tmp_path)
    _insert_run(db, [_SAMPLE_ROW])
    cfg = tmp_path / "derived_parallels.toml"
    _write_config(cfg)

    rows = export.load_derived_parallels(_open(db), config_path=cfg)
    assert rows == [_SAMPLE_ROW]


# ── persist_run (generator side, todo:675a76f8) ────────────────────────

import derive_parallels  # noqa: E402


def test_persist_run_writes_run_and_rows(tmp_path):
    db = _make_db(tmp_path)
    summary = {"generated_at": datetime.now(timezone.utc).isoformat()}
    run_id = derive_parallels.persist_run(db, [_SAMPLE_ROW], summary, None)
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM derived_runs").fetchone()[0] == 1
    rows = conn.execute(
        "SELECT run_id, source, target, weight, annotation FROM derived_parallels"
    ).fetchall()
    assert rows == [(run_id, _SAMPLE_ROW["source"], _SAMPLE_ROW["target"],
                     _SAMPLE_ROW["weight"], _SAMPLE_ROW["annotation"])]
    conn.close()


def test_persist_run_replaces_rows_keeps_summary_history(tmp_path):
    db = _make_db(tmp_path)
    ga = datetime.now(timezone.utc).isoformat()
    derive_parallels.persist_run(db, [_SAMPLE_ROW], {"generated_at": ga}, None)
    r2 = derive_parallels.persist_run(
        db, [dict(_SAMPLE_ROW, source="second.chunk")], {"generated_at": ga}, 3)
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM derived_runs").fetchone()[0] == 2
    rows = conn.execute("SELECT run_id, source FROM derived_parallels").fetchall()
    assert rows == [(r2, "second.chunk")]
    assert conn.execute(
        "SELECT limit_concepts FROM derived_runs WHERE run_id = ?", (r2,)
    ).fetchone()[0] == 3
    conn.close()


def test_persist_run_missing_tables_fails_loudly(tmp_path):
    db = tmp_path / "bare.db"
    sqlite3.connect(db).close()
    with pytest.raises(SystemExit, match="derived-parallels tables"):
        derive_parallels.persist_run(
            db, [_SAMPLE_ROW],
            {"generated_at": datetime.now(timezone.utc).isoformat()}, None)


# ── load_frozen_contrasts ───────────────────────────────────────────────

def test_load_frozen_contrasts_real_snapshot_shape_and_count():
    """The committed snapshot itself: 112 rows (todo:6da4f965's target),
    every row shaped like corpus.edges."""
    rows = export.load_frozen_contrasts()
    assert len(rows) == 112
    for r in rows:
        assert set(r) == {"source", "target", "edge_type", "tier", "weight", "annotation"}
        assert r["edge_type"] == "CONTRASTS"
        assert r["weight"] is None  # carried through unchanged: never had a weight


def test_load_frozen_contrasts_missing_file_fails_loudly(tmp_path):
    with pytest.raises(SystemExit, match="not found"):
        export.load_frozen_contrasts(path=tmp_path / "nope.toml")


def test_load_frozen_contrasts_empty_fails_loudly(tmp_path):
    p = tmp_path / "frozen_contrasts.toml"
    p.write_text("")
    with pytest.raises(SystemExit, match="no \\[\\[edge\\]\\] entries"):
        export.load_frozen_contrasts(path=p)


def test_load_frozen_contrasts_wrong_edge_type_fails_loudly(tmp_path):
    p = tmp_path / "frozen_contrasts.toml"
    p.write_text(
        '[[edge]]\nsource = "a"\ntarget = "b"\nedge_type = "PARALLELS"\ntier = "verified"\n'
    )
    with pytest.raises(SystemExit, match="expected 'CONTRASTS'"):
        export.load_frozen_contrasts(path=p)


def test_load_frozen_contrasts_missing_field_fails_loudly(tmp_path):
    p = tmp_path / "frozen_contrasts.toml"
    p.write_text('[[edge]]\nsource = "a"\ntarget = "b"\nedge_type = "CONTRASTS"\n')
    with pytest.raises(SystemExit, match="missing 'tier'"):
        export.load_frozen_contrasts(path=p)


def test_load_frozen_contrasts_orphan_endpoint_fails_loudly(tmp_path):
    """PR #64 review finding 2: this snapshot is the one PARALLELS/CONTRASTS
    source that can never self-heal after a re-chunk (it's a static
    committed file, never regenerated), so an orphan endpoint here is the
    most important place to fail loudly rather than silently ship a row
    that will just never match at query time."""
    p = tmp_path / "frozen_contrasts.toml"
    p.write_text(
        '[[edge]]\nsource = "a"\ntarget = "b"\nedge_type = "CONTRASTS"\ntier = "verified"\n'
    )
    with pytest.raises(SystemExit, match="do not resolve to a chunk"):
        export.load_frozen_contrasts(path=p, chunk_ids={"a", "some.other.chunk"})


def test_load_frozen_contrasts_passes_when_endpoints_resolve(tmp_path):
    p = tmp_path / "frozen_contrasts.toml"
    p.write_text(
        '[[edge]]\nsource = "a"\ntarget = "b"\nedge_type = "CONTRASTS"\ntier = "verified"\n'
    )
    rows = export.load_frozen_contrasts(path=p, chunk_ids={"a", "b"})
    assert len(rows) == 1


# ── load_edges no longer serves PARALLELS/CONTRASTS ─────────────────────

@pytest.fixture
def edges_conn():
    c = sqlite3.connect(":memory:")
    c.executescript(
        "CREATE TABLE edges (source_id TEXT, target_id TEXT, type TEXT, "
        "tier TEXT, justification TEXT);"
        "CREATE TABLE staged_tags (chunk_id TEXT, concept_id TEXT, "
        "score INTEGER, status TEXT);"
    )
    c.executescript(
        "INSERT INTO edges VALUES "
        "('c1','concept.x','EXPRESSES','verified','e'),"
        "('c2','concept.x','EXPRESSES','verified','e-unstaged'),"
        "('t1','t2','BELONGS_TO','inferred','b'),"
        "('c1','c2','PARALLELS','verified','should not appear'),"
        "('c1','c3','CONTRASTS','verified','should not appear');"
        # c1/x: two accepted rows (two models) -> MAX wins; a rejected 3 and a
        # pending 3 must not leak in. c2/x has no staged row -> weight NULL.
        "INSERT INTO staged_tags VALUES "
        "('c1','x',2,'accepted'),"
        "('c1','x',1,'accepted'),"
        "('c1','x',3,'rejected'),"
        "('c1','x',3,'pending');"
    )
    c.commit()
    yield c
    c.close()


def test_load_edges_excludes_parallels_and_contrasts(edges_conn):
    rows = export.load_edges(edges_conn)
    types = {r["edge_type"] for r in rows}
    assert types == {"EXPRESSES", "BELONGS_TO"}
    assert len(rows) == 3


def test_load_edges_expresses_weight_from_accepted_staged_score(edges_conn):
    """todo:f6af90e8 — EXPRESSES weight = MAX accepted staged_tags score;
    rejected/pending rows never contribute; unmatched rows and BELONGS_TO
    stay NULL (partial coverage is the contract, not a defect)."""
    rows = {(r["source"], r["edge_type"]): r["weight"] for r in export.load_edges(edges_conn)}
    assert rows[("c1", "EXPRESSES")] == 2.0   # MAX(2,1); rejected/pending 3s excluded
    assert rows[("c2", "EXPRESSES")] is None  # no accepted staged row
    assert rows[("t1", "BELONGS_TO")] is None


def test_load_edges_row_shape_matches_corpus_edges_columns(edges_conn):
    rows = export.load_edges(edges_conn)
    for r in rows:
        assert set(r) == {"source", "target", "edge_type", "tier", "weight", "annotation"}


# ── fail-fast ordering (PR #64 review finding 1) ────────────────────────

def test_emit_copies_takes_preloaded_rows_and_does_no_loading():
    """emit_copies() must not call load_derived_parallels()/
    load_frozen_contrasts()/load_chunks() itself. Those loaders' SystemExit
    guards need to fire in main() before next_corpus_version() and before
    the output file is truncated — which only works if emit_copies()
    receives already-loaded rows as parameters instead of loading them from
    inside the same call that main() only reaches after mutating state."""
    sig = inspect.signature(export.emit_copies)
    assert "chunks" in sig.parameters
    assert "derived_parallels_rows" in sig.parameters
    assert "frozen_contrasts_rows" in sig.parameters

    source = inspect.getsource(export.emit_copies)
    assert "load_derived_parallels(" not in source
    assert "load_frozen_contrasts(" not in source
    assert "load_chunks(" not in source


def test_main_loads_artifacts_before_version_bump_and_output_truncation():
    """Ordering regression guard: in main()'s source, both loader calls must
    appear before next_corpus_version(conn) (commits a version bump) and
    before gzip.open(OUTPUT, ...) (truncates the last good dump). Either
    loader's SystemExit firing after those two lines is exactly the
    fail-destructive bug this fix closes.

    Comment lines are stripped before searching — main()'s own explanatory
    comment names these same calls in prose, which would otherwise give a
    false pass (or, coincidentally, a false failure) independent of where
    the real code actually calls them."""
    source = inspect.getsource(export.main)
    code_lines = [ln for ln in source.splitlines() if not ln.strip().startswith("#")]
    code = "\n".join(code_lines)

    derived_pos = code.index("load_derived_parallels(")
    frozen_pos = code.index("load_frozen_contrasts(")
    version_pos = code.index("next_corpus_version(conn)")
    gzip_pos = code.index("gzip.open(OUTPUT")

    assert derived_pos < version_pos < gzip_pos
    assert frozen_pos < version_pos < gzip_pos
