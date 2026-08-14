"""tests/test_flag_apparatus.py — coverage for scripts/flag_apparatus.py
(todo:495577b7).

Covers the two things the ticket calls out explicitly: the all-rejected
staged_tags query (source b's targeting) and the skip/idempotency logic
(never double-queue, never claim a chunk that still has a surviving tag).
No corpus files are touched — stage_apparatus_flag's body lookup is
monkeypatched, since the load-bearing behaviour under test is the DB
read/write logic, not TOML I/O (already covered elsewhere).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import flag_apparatus as fa  # noqa: E402


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE staged_tags (chunk_id TEXT, status TEXT)")
    conn.execute(
        """CREATE TABLE staged_cleanups (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               chunk_id TEXT,
               original_body TEXT,
               proposed_body TEXT,
               justification TEXT,
               signal_score REAL,
               words_preserved INTEGER,
               status TEXT,
               model TEXT,
               prompt_version TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE review_actions (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               target_id INTEGER,
               target_table TEXT,
               action TEXT,
               reassign_to TEXT,
               reclassify_to TEXT,
               reviewer TEXT,
               client_action_id TEXT UNIQUE,
               applied_at TEXT
        )"""
    )
    return conn


# ── all_rejected_chunk_ids ───────────────────────────────────────────────────


def test_all_rejected_includes_chunk_with_every_row_rejected():
    conn = _conn()
    conn.executemany(
        "INSERT INTO staged_tags VALUES (?, ?)",
        [("a.t.001", "rejected"), ("a.t.001", "rejected")],
    )
    conn.commit()
    assert fa.all_rejected_chunk_ids(conn) == {"a.t.001"}


def test_all_rejected_excludes_chunk_with_one_accepted_row():
    conn = _conn()
    conn.executemany(
        "INSERT INTO staged_tags VALUES (?, ?)",
        [("a.t.001", "rejected"), ("a.t.001", "accepted")],
    )
    conn.commit()
    assert fa.all_rejected_chunk_ids(conn) == set()


def test_all_rejected_excludes_chunk_with_pending_or_reassigned_row():
    conn = _conn()
    conn.executemany(
        "INSERT INTO staged_tags VALUES (?, ?)",
        [
            ("pending.t.001", "rejected"), ("pending.t.001", "pending"),
            ("reassigned.t.001", "rejected"), ("reassigned.t.001", "reassigned"),
        ],
    )
    conn.commit()
    assert fa.all_rejected_chunk_ids(conn) == set()


def test_all_rejected_ignores_chunk_with_no_staged_tags_rows_at_all():
    """A chunk that was tagged and produced zero proposals never appears in
    staged_tags — it is not 'all-rejected', it is simply untagged."""
    conn = _conn()
    conn.execute("INSERT INTO staged_tags VALUES ('other.t.001', 'rejected')")
    conn.commit()
    assert "never-tagged.t.001" not in fa.all_rejected_chunk_ids(conn)


# ── has_surviving_tags (source-a safety gate) ────────────────────────────────


def test_has_surviving_tags_true_for_accepted():
    conn = _conn()
    conn.execute("INSERT INTO staged_tags VALUES ('a.t.001', 'accepted')")
    conn.commit()
    assert fa.has_surviving_tags(conn, "a.t.001")


def test_has_surviving_tags_false_when_all_rejected():
    conn = _conn()
    conn.execute("INSERT INTO staged_tags VALUES ('a.t.001', 'rejected')")
    conn.commit()
    assert not fa.has_surviving_tags(conn, "a.t.001")


def test_has_surviving_tags_false_when_no_rows():
    conn = _conn()
    assert not fa.has_surviving_tags(conn, "untagged.t.001")


# ── already_staged / review_action_exists (idempotency) ─────────────────────


def test_already_staged_true_for_pending():
    conn = _conn()
    conn.execute(
        "INSERT INTO staged_cleanups (chunk_id, status) VALUES ('a.t.001', 'pending')"
    )
    conn.commit()
    assert fa.already_staged(conn, "a.t.001")


def test_already_staged_true_for_apparatus():
    conn = _conn()
    conn.execute(
        "INSERT INTO staged_cleanups (chunk_id, status) VALUES ('a.t.001', 'apparatus')"
    )
    conn.commit()
    assert fa.already_staged(conn, "a.t.001")


def test_already_staged_false_for_rejected_or_accepted():
    conn = _conn()
    conn.executemany(
        "INSERT INTO staged_cleanups (chunk_id, status) VALUES (?, ?)",
        [("a.t.001", "rejected"), ("a.t.002", "accepted")],
    )
    conn.commit()
    assert not fa.already_staged(conn, "a.t.001")
    assert not fa.already_staged(conn, "a.t.002")


# ── stage_apparatus_flag: writes + idempotency + missing body ───────────────


def test_stage_apparatus_flag_writes_pending_row_and_queued_reclassify(monkeypatch):
    conn = _conn()
    monkeypatch.setattr(fa, "load_body", lambda cid: "the body text")

    outcome = fa.stage_apparatus_flag(conn, "a.t.001", "test reason", "model:x", dry_run=False,
                                      staged_this_run=set())
    assert outcome == "staged"

    row = conn.execute(
        "SELECT chunk_id, original_body, proposed_body, status, words_preserved, model "
        "FROM staged_cleanups"
    ).fetchone()
    assert row == ("a.t.001", "the body text", "the body text", "pending", 1, "model:x")

    action = conn.execute(
        "SELECT target_table, action, reclassify_to, reassign_to, applied_at FROM review_actions"
    ).fetchone()
    assert action == ("staged_cleanups", "reclassify", "apparatus_drop", None, None)


def test_stage_apparatus_flag_is_idempotent(monkeypatch):
    conn = _conn()
    monkeypatch.setattr(fa, "load_body", lambda cid: "the body text")

    first = fa.stage_apparatus_flag(conn, "a.t.001", "reason", "model:x", dry_run=False,
                                    staged_this_run=set())
    second = fa.stage_apparatus_flag(conn, "a.t.001", "reason", "model:x", dry_run=False,
                                     staged_this_run=set())
    assert first == "staged"
    assert second == "already_staged"
    assert conn.execute("SELECT COUNT(*) FROM staged_cleanups").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM review_actions").fetchone()[0] == 1


def test_stage_apparatus_flag_two_sources_same_chunk_dedupe(monkeypatch):
    """Source (a) and source (b) use different model labels, so the DB's own
    partial-unique index (chunk_id, model, prompt_version) would NOT stop a
    double-queue — already_staged()'s app-level, any-model check must."""
    conn = _conn()
    monkeypatch.setattr(fa, "load_body", lambda cid: "the body text")

    from_a = fa.stage_apparatus_flag(conn, "shared.t.001", "reason a", fa.MODEL_SOURCE_A, dry_run=False,
                                     staged_this_run=set())
    from_b = fa.stage_apparatus_flag(conn, "shared.t.001", "reason b", fa.MODEL_SOURCE_B, dry_run=False,
                                     staged_this_run=set())
    assert from_a == "staged"
    assert from_b == "already_staged"
    assert conn.execute("SELECT COUNT(*) FROM staged_cleanups").fetchone()[0] == 1


def test_stage_apparatus_flag_dry_run_writes_nothing(monkeypatch):
    conn = _conn()
    monkeypatch.setattr(fa, "load_body", lambda cid: "the body text")

    outcome = fa.stage_apparatus_flag(conn, "a.t.001", "reason", "model:x", dry_run=True,
                                      staged_this_run=set())
    assert outcome == "would_stage"
    assert conn.execute("SELECT COUNT(*) FROM staged_cleanups").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM review_actions").fetchone()[0] == 0


def test_stage_apparatus_flag_missing_body_refuses(monkeypatch):
    conn = _conn()
    monkeypatch.setattr(fa, "load_body", lambda cid: None)

    outcome = fa.stage_apparatus_flag(conn, "ghost.t.001", "reason", "model:x", dry_run=False,
                                      staged_this_run=set())
    assert outcome == "missing_body"
    assert conn.execute("SELECT COUNT(*) FROM staged_cleanups").fetchone()[0] == 0


def test_stage_apparatus_flag_dry_run_sees_staging_from_earlier_in_same_run(monkeypatch):
    """PR #64 review finding 5: dry-run writes nothing to the DB, so
    already_staged() alone can't catch a chunk source (a) already decided
    to stage a moment earlier in the same dry-run pass. staged_this_run
    must catch it instead."""
    conn = _conn()
    monkeypatch.setattr(fa, "load_body", lambda cid: "the body text")
    staged_this_run: set[str] = set()

    first = fa.stage_apparatus_flag(conn, "shared.t.001", "reason a", fa.MODEL_SOURCE_A,
                                    dry_run=True, staged_this_run=staged_this_run)
    second = fa.stage_apparatus_flag(conn, "shared.t.001", "reason b", fa.MODEL_SOURCE_B,
                                     dry_run=True, staged_this_run=staged_this_run)
    assert first == "would_stage"
    assert second == "already_staged"
    # dry-run never writes, regardless
    assert conn.execute("SELECT COUNT(*) FROM staged_cleanups").fetchone()[0] == 0


def test_stage_apparatus_flag_dry_run_and_apply_agree_on_overlap(monkeypatch):
    """PR #64 review finding 5, the concrete case: source (a) and source (b)
    both target a chunk (renaissance_hermeticism.heroic-enthusiasts-pt1.001-
    style overlap). Dry-run and --apply must report the identical pair of
    outcomes for that chunk, not diverge because dry-run never commits."""
    monkeypatch.setattr(fa, "load_body", lambda cid: "the body text")

    def run_both_sources(dry_run: bool) -> tuple[str, str]:
        conn = _conn()
        staged_this_run: set[str] = set()
        first = fa.stage_apparatus_flag(conn, "shared.t.001", "reason a", fa.MODEL_SOURCE_A,
                                        dry_run=dry_run, staged_this_run=staged_this_run)
        second = fa.stage_apparatus_flag(conn, "shared.t.001", "reason b", fa.MODEL_SOURCE_B,
                                         dry_run=dry_run, staged_this_run=staged_this_run)
        return first, second

    dry_outcomes = run_both_sources(dry_run=True)
    apply_outcomes = run_both_sources(dry_run=False)

    # would_stage/staged are the dry-run/apply names for "the same decision";
    # what must match is which call staged and which was recognized as a dupe.
    assert dry_outcomes == ("would_stage", "already_staged")
    assert apply_outcomes == ("staged", "already_staged")


# ── classification data sanity ───────────────────────────────────────────────


def test_source_b_apparatus_has_no_duplicate_or_empty_ids():
    ids = list(fa.SOURCE_B_APPARATUS)
    assert len(ids) == len(set(ids))
    assert all(cid.count(".") == 2 for cid in ids)


def test_source_a_candidates_have_no_duplicate_ids():
    ids = [cid for cid, _reason in fa.SOURCE_A_CANDIDATES]
    assert len(ids) == len(set(ids))
