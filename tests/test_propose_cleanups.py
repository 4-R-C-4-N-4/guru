"""Tests for the staged_cleanups pipeline halves (todo:b44966d0).

The load-bearing invariant is words_preserved: a proposal may ONLY change
whitespace and end-of-line hyphenation, and both propose (flagging) and
apply (hard refusal) check it mechanically. Apply is additionally tested
for its staleness guard against a scratch corpus + DB.
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import tomllib
import tomli_w

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from propose_cleanups import (  # noqa: E402
    content_fingerprint,
    mechanical_justification,
    strip_wrapping,
    words_preserved,
)

WRAPPED = "the temple of the ever-\nlasting horizon stood in splen-\ndour upon the\nplain of heaven"
UNWRAPPED = "the temple of the everlasting horizon stood in splendour upon the plain of heaven"


def test_words_preserved_accepts_unwrap_and_dehyphenation():
    assert words_preserved(WRAPPED, UNWRAPPED)


def test_words_preserved_rejects_reworded_text():
    assert not words_preserved(WRAPPED, UNWRAPPED.replace("temple", "shrine"))
    assert not words_preserved(WRAPPED, UNWRAPPED + " amen")
    assert not words_preserved(WRAPPED, UNWRAPPED.replace(" upon the plain of heaven", ""))


def test_fingerprint_ignores_paragraph_reflow():
    a = "one two\nthree\n\nfour five"
    b = "one two three\n\nfour five"
    assert content_fingerprint(a) == content_fingerprint(b)


def test_strip_wrapping_removes_think_block_and_fences():
    assert strip_wrapping("<think>hmm\nokay</think>\nrepaired text") == "repaired text"
    assert strip_wrapping("```text\nrepaired text\n```") == "repaired text"
    assert strip_wrapping("repaired text\n") == "repaired text"


def test_strip_wrapping_removes_stray_unpaired_think_tags():
    # qwen3 sometimes emits a bare trailing </think> with no opening tag —
    # the drift class observed in the first proposal batch.
    assert strip_wrapping("repaired text\n</think>") == "repaired text"
    assert strip_wrapping("<think>\nrepaired text") == "repaired text"


def test_strip_wrapping_removes_trailing_bare_think_token():
    # The soft-switch token leaks as PLAIN text too: "… goods. /think"
    assert strip_wrapping("renounced this world's goods. /think") == "renounced this world's goods."
    assert strip_wrapping("repaired text /no_think") == "repaired text"
    # anchored: a mid-text "/think" (however unlikely) survives
    assert "/think about" in strip_wrapping("do /think about it later")


def test_mechanical_justification_reports_score_drop():
    j = mechanical_justification(WRAPPED, UNWRAPPED)
    assert "hard_wrap" in j and "->" in j


def test_ratio_guard_bounds():
    # The propose-side ratio guard treats non-repair-shaped output (e.g. a
    # reasoning transcript several times the body length) as a call error.
    body, transcript = "short body text", "Thinking Process: " + "analysis " * 50
    assert not 0.8 <= len(transcript) / len(body) <= 1.25
    assert 0.8 <= len(UNWRAPPED) / len(WRAPPED) <= 1.25


# ── apply_cleanups guards against a scratch corpus + DB ──────────────────────

def _scratch(tmp_path: Path, body: str, proposed: str, status: str = "accepted"):
    """Build corpus/<t>/<x>/chunks/001.toml + a DB with one staged row."""
    chunk_dir = tmp_path / "corpus" / "trad" / "text-a" / "chunks"
    chunk_dir.mkdir(parents=True)
    with open(chunk_dir / "001.toml", "wb") as f:
        tomli_w.dump({"chunk": {"id": "trad.text-a.001", "token_count": 1},
                      "content": {"body": body}}, f)
    db = tmp_path / "guru.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE nodes (id TEXT PRIMARY KEY, type TEXT, metadata_json TEXT DEFAULT '{}');
        CREATE TABLE staged_cleanups (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chunk_id TEXT NOT NULL,
            original_body TEXT NOT NULL, proposed_body TEXT NOT NULL,
            justification TEXT, signal_score REAL DEFAULT 0.0,
            words_preserved INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending', reviewed_by TEXT, reviewed_at TEXT,
            applied_at TEXT, model TEXT, prompt_version TEXT);
        INSERT INTO nodes VALUES ('trad.text-a.001', 'chunk', '{}');
    """)
    conn.execute(
        "INSERT INTO staged_cleanups (chunk_id, original_body, proposed_body, words_preserved, status) "
        "VALUES ('trad.text-a.001', ?, ?, 1, ?)",
        (body, proposed, status),
    )
    conn.commit()
    conn.close()
    return db


def _run_apply(tmp_path: Path, db: Path, mode: str = "--apply"):
    """Run apply_cleanups.py with CORPUS_DIR pointed at the scratch tree."""
    code = (
        "import sys; sys.path.insert(0, r'%s');\n"
        "import apply_cleanups as ac; from pathlib import Path\n"
        "ac.CORPUS_DIR = Path(r'%s')\n"
        "import propose_cleanups\n"
        "sys.argv = ['apply_cleanups.py', '%s', '--db', r'%s']\n"
        "raise SystemExit(ac.main())\n"
    ) % (PROJECT_ROOT / "scripts", tmp_path / "corpus", mode, db)
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)


def test_apply_writes_accepted_rewrite_and_stamps_applied_at(tmp_path):
    db = _scratch(tmp_path, WRAPPED, UNWRAPPED)
    res = _run_apply(tmp_path, db)
    assert res.returncode == 0, res.stderr
    written = tomllib.load(open(tmp_path / "corpus/trad/text-a/chunks/001.toml", "rb"))
    assert written["content"]["body"] == UNWRAPPED
    assert written["chunk"]["token_count"] > 1
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT applied_at FROM staged_cleanups").fetchone()[0] is not None


def test_apply_refuses_stale_toml(tmp_path):
    db = _scratch(tmp_path, WRAPPED, UNWRAPPED)
    # Simulate clean_bodies re-running after the proposal: body changed on disk.
    p = tmp_path / "corpus/trad/text-a/chunks/001.toml"
    with open(p, "wb") as f:
        tomli_w.dump({"chunk": {"id": "trad.text-a.001", "token_count": 1},
                      "content": {"body": WRAPPED + " newly appended"}}, f)
    res = _run_apply(tmp_path, db)
    assert res.returncode == 1
    assert "stale" in res.stderr + res.stdout
    written = tomllib.load(open(p, "rb"))
    assert "newly appended" in written["content"]["body"]  # untouched


def test_apply_refuses_word_drift_even_if_flag_lied(tmp_path):
    # Row claims words_preserved=1 but the proposal drifted — apply recomputes.
    db = _scratch(tmp_path, WRAPPED, UNWRAPPED.replace("temple", "shrine"))
    res = _run_apply(tmp_path, db)
    assert res.returncode == 1
    assert "words_preserved" in res.stderr + res.stdout
    written = tomllib.load(open(tmp_path / "corpus/trad/text-a/chunks/001.toml", "rb"))
    assert written["content"]["body"] == WRAPPED  # untouched
