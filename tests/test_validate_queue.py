"""The queue validator must actually fail on the hazards it claims to catch.

`scripts/validate_queue.py` reported a clean queue on its first run against
real data. That is the least trustworthy possible result for a new checker, so
each hazard is reconstructed here and the validator has to find it.

The collision case is the one that matters: `POST /api/apply` drains the whole
queue in one `rw.transaction`, so a single UNIQUE violation rolls back every
other verdict in the batch.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "validate_queue", ROOT / "scripts" / "validate_queue.py"
)
validate_queue = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validate_queue)

MODEL = "qwen-3-4b-guru-Q4_K_M.gguf"
PV = "v1"


@pytest.fixture
def db() -> sqlite3.Connection:
    """Minimal schema, mirroring the constraints the validator reasons about."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE staged_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chunk_id TEXT NOT NULL,
            concept_id TEXT NOT NULL,
            score INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'pending',
            model TEXT, prompt_version TEXT
        );
        -- The real index is partial; the validator's correctness depends on it.
        CREATE UNIQUE INDEX idx_staged_tags_provenance_unique
            ON staged_tags(chunk_id, concept_id, model, prompt_version)
            WHERE status = 'pending';
        CREATE TABLE edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL, target_id TEXT NOT NULL, type TEXT NOT NULL
        );
        CREATE TABLE review_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_table TEXT NOT NULL DEFAULT 'staged_tags',
            target_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            reassign_to TEXT,
            applied_at TEXT
        );
        """
    )
    return conn


def add_tag(conn, chunk, concept, status="pending") -> int:
    cur = conn.execute(
        "INSERT INTO staged_tags(chunk_id, concept_id, status, model, prompt_version)"
        " VALUES(?,?,?,?,?)",
        (chunk, concept, status, MODEL, PV),
    )
    return cur.lastrowid


def queue(conn, target_id, action, reassign_to=None) -> int:
    cur = conn.execute(
        "INSERT INTO review_actions(target_id, action, reassign_to) VALUES(?,?,?)",
        (target_id, action, reassign_to),
    )
    return cur.lastrowid


def kinds(findings, level=None):
    return {f["kind"] for f in findings if level is None or f["level"] == level}


def test_clean_queue_is_clean(db):
    donor = add_tag(db, "c.001", "meditation")
    queue(db, donor, "reject")
    assert validate_queue.validate(db) == []


def test_reassign_onto_pending_concept_is_an_error(db):
    """The failure that rolls back the entire batch."""
    donor = add_tag(db, "c.001", "paradox_as_teaching")
    add_tag(db, "c.001", "inner_silence")  # target already pending — collision
    queue(db, donor, "reassign", "inner_silence")

    findings = validate_queue.validate(db)
    assert "reassign_collision" in kinds(findings, "ERROR")


def test_reassign_onto_free_concept_is_fine(db):
    donor = add_tag(db, "c.001", "paradox_as_teaching")
    queue(db, donor, "reassign", "inner_silence")
    assert validate_queue.validate(db) == []


def test_reassign_does_not_collide_with_its_own_donor(db):
    """Donor leaves the partial index (status='reassigned') before the insert.

    A validator that pops the donor *after* checking would flag this, and the
    false positive would be indistinguishable from the real collision above.
    """
    donor = add_tag(db, "c.001", "inner_silence")
    queue(db, donor, "reassign", "inner_silence")
    assert validate_queue.validate(db) == []


def test_two_reassigns_to_same_target_on_one_chunk_collide(db):
    """The second insert hits the row the first one invented."""
    a = add_tag(db, "c.001", "paradox_as_teaching")
    b = add_tag(db, "c.001", "prayer")
    queue(db, a, "reassign", "inner_silence")
    queue(db, b, "reassign", "inner_silence")

    findings = validate_queue.validate(db)
    assert "reassign_collision" in kinds(findings, "ERROR")


def test_clearing_reject_must_be_queued_after_the_reassign(db):
    """Apply order is `ra.id DESC`, so later-queued actions run first.

    Queueing the clearing reject *first* (lower id) means it applies *last* —
    too late to free the concept. This is the counterintuitive case the
    validator exists to catch, so both orderings are asserted.
    """
    donor = add_tag(db, "c.001", "paradox_as_teaching")
    occupant = add_tag(db, "c.001", "inner_silence")

    queue(db, occupant, "reject")                     # lower id → applied last
    queue(db, donor, "reassign", "inner_silence")     # higher id → applied first
    assert "reassign_collision" in kinds(validate_queue.validate(db), "ERROR")

    db.execute("DELETE FROM review_actions")
    queue(db, donor, "reassign", "inner_silence")     # lower id → applied last
    queue(db, occupant, "reject")                     # higher id → applied first
    assert validate_queue.validate(db) == []


def test_reject_of_promoted_tag_warns_about_live_edge(db):
    """`reject` calls deleteEdge unconditionally — silent loss of live state."""
    tag = add_tag(db, "c.001", "meditation")
    db.execute(
        "INSERT INTO edges(source_id, target_id, type) VALUES(?,?,?)",
        ("c.001", "concept.meditation", "EXPRESSES"),
    )
    queue(db, tag, "reject")

    findings = validate_queue.validate(db)
    assert "reject_deletes_live_edge" in kinds(findings, "WARN")
    assert not [f for f in findings if f["level"] == "ERROR"]


def test_reassign_missing_target_is_an_error(db):
    tag = add_tag(db, "c.001", "meditation")
    queue(db, tag, "reassign", None)
    assert "reassign_missing_target" in kinds(validate_queue.validate(db), "ERROR")


def test_orphaned_target_is_an_error(db):
    queue(db, 999999, "reject")
    assert "orphaned_target" in kinds(validate_queue.validate(db), "ERROR")


def test_already_resolved_tag_is_reported_as_skipped(db):
    tag = add_tag(db, "c.001", "meditation", status="accepted")
    queue(db, tag, "reject")

    findings = validate_queue.validate(db)
    assert "already_resolved" in kinds(findings, "INFO")
    assert not [f for f in findings if f["level"] == "ERROR"]


def test_resolved_tag_does_not_block_a_reassign(db):
    """Only pending rows are in the partial index; other statuses cannot collide."""
    donor = add_tag(db, "c.001", "paradox_as_teaching")
    add_tag(db, "c.001", "inner_silence", status="rejected")
    queue(db, donor, "reassign", "inner_silence")
    assert validate_queue.validate(db) == []


def test_different_provenance_does_not_collide(db):
    """The index is keyed on (chunk, concept, model, prompt_version)."""
    donor = add_tag(db, "c.001", "paradox_as_teaching")
    db.execute(
        "INSERT INTO staged_tags(chunk_id, concept_id, status, model, prompt_version)"
        " VALUES(?,?,?,?,?)",
        ("c.001", "inner_silence", "pending", "some-other-model.gguf", PV),
    )
    queue(db, donor, "reassign", "inner_silence")
    assert validate_queue.validate(db) == []
