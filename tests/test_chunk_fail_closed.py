"""Regression tests for PR #87 finding 5 (the fail-closed batch-abort):
chunk.py must surface a fail-closed config abort as a non-zero exit, not
swallow it into a benign "skipped" and exit 0 with stale chunks on disk.

This guards against the round-2 regression where the per-source except
RuntimeError masked the failure signal entirely (silent fail-open under
`--only <id>`)."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHUNK = ROOT / "scripts" / "chunk.py"
CHUNKING = ROOT / "chunking"
RAW = ROOT / "raw"
CORPUS = ROOT / "corpus"

SRC_ID = "failclosed"
TRAD = "tradition"
CFG = CHUNKING / TRAD / f"{SRC_ID}.toml"
RAWFILE = RAW / TRAD / f"{SRC_ID}-01.txt"
CORPUSDIR = CORPUS / TRAD / SRC_ID


@pytest.fixture(autouse=True)
def _scratch_config():
    CHUNKING.mkdir(parents=True, exist_ok=True)
    (CHUNKING / TRAD).mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / TRAD).mkdir(parents=True, exist_ok=True)
    yield
    # Cleanup so the repo is left untouched by the test.
    for p in (CFG, RAWFILE):
        if p.exists():
            p.unlink()
    if CORPUSDIR.exists():
        import shutil
        shutil.rmtree(CORPUSDIR)


def _write(require_marker: bool):
    CFG.write_text(
        '[chunking]\n'
        'strategy = "page-as-chunk"\n'
        'section_label_format = "Page {n}"\n'
        'number_source = "filename"\n'
        'max_tokens = 800\n'
        'drop_before_marker = "THIS_MARKER_NEVER_APPEARS_12345"\n'
        f'require_drop_before_marker = {str(require_marker).lower()}\n'
    )
    RAWFILE.write_text("Some body text without the marker.\n")


def _run():
    env = {**os.environ, "PYTHONPATH": str(ROOT / "scripts")}
    return subprocess.run(
        [sys.executable, str(CHUNK), "--only", SRC_ID],
        cwd=str(ROOT), env=env, capture_output=True, text=True,
    )


def test_drifted_marker_exits_nonzero():
    """When require_drop_before_marker is set and the marker drifts, chunk.py
    --only must exit NON-ZERO (finding 5 regression: previously the except
    swallowed it and the process exited 0 with stale chunks)."""
    _write(require_marker=True)
    proc = _run()
    assert proc.returncode != 0, (
        f"expected non-zero exit on drifted marker; stdout:\n{proc.stdout}\n"
        f"stderr:\n{proc.stderr}"
    )
    assert "ABORTED" in proc.stderr or "refusing" in proc.stderr
    # No stale corpus written for the failed source.
    assert not CORPUSDIR.exists(), "fail-closed abort must not leave chunks on disk"


def test_drifted_marker_warn_and_keep_without_require():
    """Without require_drop_before_marker, a drifted marker is a benign warn-
    and-keep, which SHOULD still exit 0 (the prior-correct behavior the
    fail-closed path must not break)."""
    _write(require_marker=False)
    proc = _run()
    assert proc.returncode == 0
