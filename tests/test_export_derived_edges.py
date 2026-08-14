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


def test_load_derived_parallels_orphan_endpoint_fails_loudly(tmp_path):
    """PR #64 review finding 2: a source/target that doesn't resolve to an
    exported chunk (e.g. a re-chunk shifted ids out from under a stale
    derived run) must SystemExit, not load silently."""
    base = tmp_path / "derived_parallels"
    _write_run(base, "2026-01-01T00-00-00Z", [_SAMPLE_ROW])
    cfg = tmp_path / "derived_parallels.toml"
    _write_config(cfg, base)

    with pytest.raises(SystemExit, match="do not resolve to a chunk"):
        export.load_derived_parallels(config_path=cfg, chunk_ids={"some.other.chunk"})


def test_load_derived_parallels_passes_when_endpoints_resolve(tmp_path):
    base = tmp_path / "derived_parallels"
    _write_run(base, "2026-01-01T00-00-00Z", [_SAMPLE_ROW])
    cfg = tmp_path / "derived_parallels.toml"
    _write_config(cfg, base)

    rows = export.load_derived_parallels(
        config_path=cfg,
        chunk_ids={_SAMPLE_ROW["source"], _SAMPLE_ROW["target"]},
    )
    assert rows == [_SAMPLE_ROW]


def test_load_derived_parallels_no_chunk_ids_skips_orphan_check(tmp_path):
    """chunk_ids=None (the default) skips the check entirely — used by
    callers (tests, ad hoc inspection) that aren't validating against a real
    exported chunk set. main() always passes the real set in production."""
    base = tmp_path / "derived_parallels"
    _write_run(base, "2026-01-01T00-00-00Z", [_SAMPLE_ROW])
    cfg = tmp_path / "derived_parallels.toml"
    _write_config(cfg, base)

    rows = export.load_derived_parallels(config_path=cfg)
    assert rows == [_SAMPLE_ROW]


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
