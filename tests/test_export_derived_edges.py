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
"""
from __future__ import annotations

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

def _write_run(base_dir: Path, stamp: str, rows: list[dict], *,
                generated_at: str | None = None) -> Path:
    """Write one derive_parallels.py-shaped run directory."""
    run_dir = base_dir / stamp
    run_dir.mkdir(parents=True)
    with open(run_dir / "edges_derived.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    summary = {
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "unique_edge_rows": len(rows),
    }
    with open(run_dir / "summary.json", "w") as f:
        json.dump(summary, f)
    return run_dir


def _write_config(path: Path, derived_dir: Path, max_age_days: float = 30) -> None:
    path.write_text(
        f'[scoring]\ntop_k = 5\nmin_grade = -4.415\n'
        f'model_path = "x"\nscore_cache = "x"\n'
        f'[panels]\nper_work_cap = 2\n'
        f'[export]\nderived_dir = "{derived_dir.as_posix()}"\n'
        f'max_age_days = {max_age_days}\n'
    )


_SAMPLE_ROW = {
    "source": "buddhism.a.001", "target": "taoism.b.002",
    "edge_type": "PARALLELS", "tier": "inferred", "weight": 1.23,
    "annotation": "Shared concept: X — def. (derived)",
}


# ── load_derived_parallels ─────────────────────────────────────────────

def test_load_derived_parallels_happy_path(tmp_path):
    base = tmp_path / "derived_parallels"
    _write_run(base, "2026-01-01T00-00-00Z", [_SAMPLE_ROW])
    cfg = tmp_path / "derived_parallels.toml"
    _write_config(cfg, base)

    rows = export.load_derived_parallels(config_path=cfg)
    assert rows == [_SAMPLE_ROW]


def test_load_derived_parallels_picks_lexicographically_latest_run(tmp_path):
    base = tmp_path / "derived_parallels"
    older = dict(_SAMPLE_ROW, source="older.chunk")
    newer = dict(_SAMPLE_ROW, source="newer.chunk")
    _write_run(base, "2026-01-01T00-00-00Z", [older])
    _write_run(base, "2026-06-01T00-00-00Z", [newer])
    cfg = tmp_path / "derived_parallels.toml"
    _write_config(cfg, base)

    rows = export.load_derived_parallels(config_path=cfg)
    assert rows == [newer]


def test_load_derived_parallels_missing_base_dir_fails_loudly(tmp_path):
    cfg = tmp_path / "derived_parallels.toml"
    _write_config(cfg, tmp_path / "does_not_exist")

    with pytest.raises(SystemExit, match="does not exist"):
        export.load_derived_parallels(config_path=cfg)


def test_load_derived_parallels_no_runs_fails_loudly(tmp_path):
    base = tmp_path / "derived_parallels"
    base.mkdir()
    cfg = tmp_path / "derived_parallels.toml"
    _write_config(cfg, base)

    with pytest.raises(SystemExit, match="No derived-parallels run found"):
        export.load_derived_parallels(config_path=cfg)


def test_load_derived_parallels_incomplete_run_dir_is_skipped(tmp_path):
    """A run dir missing summary.json (crashed mid-write) must not be
    picked — it should be invisible, not silently loaded half-written."""
    base = tmp_path / "derived_parallels"
    run_dir = base / "2026-01-01T00-00-00Z"
    run_dir.mkdir(parents=True)
    (run_dir / "edges_derived.jsonl").write_text(json.dumps(_SAMPLE_ROW) + "\n")
    # no summary.json written
    cfg = tmp_path / "derived_parallels.toml"
    _write_config(cfg, base)

    with pytest.raises(SystemExit, match="No derived-parallels run found"):
        export.load_derived_parallels(config_path=cfg)


def test_load_derived_parallels_stale_fails_loudly(tmp_path):
    base = tmp_path / "derived_parallels"
    stale_ts = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    _write_run(base, "2026-01-01T00-00-00Z", [_SAMPLE_ROW], generated_at=stale_ts)
    cfg = tmp_path / "derived_parallels.toml"
    _write_config(cfg, base, max_age_days=30)

    with pytest.raises(SystemExit, match="stale"):
        export.load_derived_parallels(config_path=cfg)


def test_load_derived_parallels_empty_rows_fails_loudly(tmp_path):
    base = tmp_path / "derived_parallels"
    _write_run(base, "2026-01-01T00-00-00Z", [])
    cfg = tmp_path / "derived_parallels.toml"
    _write_config(cfg, base)

    with pytest.raises(SystemExit, match="zero PARALLELS"):
        export.load_derived_parallels(config_path=cfg)


def test_load_derived_parallels_wrong_edge_type_fails_loudly(tmp_path):
    base = tmp_path / "derived_parallels"
    bad = dict(_SAMPLE_ROW, edge_type="CONTRASTS")
    _write_run(base, "2026-01-01T00-00-00Z", [bad])
    cfg = tmp_path / "derived_parallels.toml"
    _write_config(cfg, base)

    with pytest.raises(SystemExit, match="expected 'PARALLELS'"):
        export.load_derived_parallels(config_path=cfg)


def test_load_derived_parallels_missing_field_fails_loudly(tmp_path):
    base = tmp_path / "derived_parallels"
    bad = {k: v for k, v in _SAMPLE_ROW.items() if k != "weight"}
    _write_run(base, "2026-01-01T00-00-00Z", [bad])
    cfg = tmp_path / "derived_parallels.toml"
    _write_config(cfg, base)

    with pytest.raises(SystemExit, match="missing 'weight'"):
        export.load_derived_parallels(config_path=cfg)


def test_load_derived_parallels_missing_config_fails_loudly(tmp_path):
    with pytest.raises(SystemExit, match="not found"):
        export.load_derived_parallels(config_path=tmp_path / "nope.toml")


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


# ── load_edges no longer serves PARALLELS/CONTRASTS ─────────────────────

@pytest.fixture
def edges_conn():
    c = sqlite3.connect(":memory:")
    c.executescript(
        "CREATE TABLE edges (source_id TEXT, target_id TEXT, type TEXT, "
        "tier TEXT, justification TEXT);"
    )
    c.executescript(
        "INSERT INTO edges VALUES "
        "('c1','concept.x','EXPRESSES','verified','e'),"
        "('t1','t2','BELONGS_TO','inferred','b'),"
        "('c1','c2','PARALLELS','verified','should not appear'),"
        "('c1','c3','CONTRASTS','verified','should not appear');"
    )
    c.commit()
    yield c
    c.close()


def test_load_edges_excludes_parallels_and_contrasts(edges_conn):
    rows = export.load_edges(edges_conn)
    types = {r["edge_type"] for r in rows}
    assert types == {"EXPRESSES", "BELONGS_TO"}
    assert len(rows) == 2


def test_load_edges_row_shape_matches_corpus_edges_columns(edges_conn):
    rows = export.load_edges(edges_conn)
    for r in rows:
        assert set(r) == {"source", "target", "edge_type", "tier", "weight", "annotation"}
