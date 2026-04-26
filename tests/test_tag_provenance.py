"""Regression test for v3 Phase 1 provenance writes (todo:20891195).

upsert_staged_tag must write model + prompt_version on every insert.
The partial UNIQUE on (chunk_id, concept_id, model, prompt_version)
WHERE status='pending' must permit different-model inserts and reject
same-model dupes via ON CONFLICT DO NOTHING.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT))
from tag_concepts import upsert_staged_tag  # noqa: E402
from guru.prompt import PROMPT_VERSION  # noqa: E402


def _seed_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE nodes (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL CHECK(type IN ('tradition','concept','chunk')),
            tradition_id TEXT REFERENCES nodes(id),
            label TEXT NOT NULL,
            definition TEXT,
            metadata_json TEXT DEFAULT '{}'
        );
        CREATE TABLE staged_tags (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            chunk_id        TEXT NOT NULL REFERENCES nodes(id),
            concept_id      TEXT NOT NULL,
            score           INTEGER NOT NULL CHECK(score BETWEEN 0 AND 3),
            justification   TEXT,
            is_new_concept  INTEGER NOT NULL DEFAULT 0,
            new_concept_def TEXT,
            status          TEXT NOT NULL DEFAULT 'pending'
                                CHECK(status IN ('pending','accepted','rejected','reassigned')),
            reviewed_by     TEXT,
            reviewed_at     TEXT,
            model           TEXT,
            prompt_version  TEXT
        );
        CREATE UNIQUE INDEX idx_staged_tags_provenance_unique
            ON staged_tags(chunk_id, concept_id, model, prompt_version)
            WHERE status='pending';
        INSERT INTO nodes(id, type, label) VALUES ('gnosticism', 'tradition', 'Gnosticism');
        INSERT INTO nodes(id, type, tradition_id, label)
            VALUES ('gnosticism.gospel-of-thomas.001', 'chunk', 'gnosticism', 'Logion 1');
    """)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    _seed_schema(c)
    yield c
    c.close()


def _tag(concept_id: str, score: int, is_new: bool = False) -> dict:
    return {
        "concept_id": concept_id,
        "score": score,
        "justification": f"test for {concept_id}",
        "is_new_concept": is_new,
        "new_concept_def": "proposed def" if is_new else None,
    }


def test_upsert_writes_provenance(conn: sqlite3.Connection) -> None:
    upsert_staged_tag(conn, "gnosticism.gospel-of-thomas.001", _tag("gnosis", 3), model="qwen3.5-27b")
    row = conn.execute(
        "SELECT model, prompt_version, score FROM staged_tags WHERE concept_id='gnosis'"
    ).fetchone()
    assert row == ("qwen3.5-27b", "v1", 3)


def test_default_prompt_version_uses_module_constant(conn: sqlite3.Connection) -> None:
    upsert_staged_tag(conn, "gnosticism.gospel-of-thomas.001", _tag("gnosis", 2), model="m")
    row = conn.execute("SELECT prompt_version FROM staged_tags").fetchone()
    assert row == (PROMPT_VERSION,)


def test_unique_blocks_same_provenance_dupe(conn: sqlite3.Connection) -> None:
    upsert_staged_tag(conn, "gnosticism.gospel-of-thomas.001", _tag("gnosis", 3), model="qwen3.5-27b")
    # Re-insert same tag, same model — ON CONFLICT DO NOTHING swallows it
    upsert_staged_tag(conn, "gnosticism.gospel-of-thomas.001", _tag("gnosis", 1), model="qwen3.5-27b")
    rows = conn.execute("SELECT score FROM staged_tags WHERE concept_id='gnosis'").fetchall()
    assert rows == [(3,)], "second insert under same provenance must be a no-op"


def test_unique_permits_different_model(conn: sqlite3.Connection) -> None:
    upsert_staged_tag(conn, "gnosticism.gospel-of-thomas.001", _tag("gnosis", 3), model="qwen3.5-27b")
    upsert_staged_tag(conn, "gnosticism.gospel-of-thomas.001", _tag("gnosis", 2), model="qwen-finetune-v1")
    rows = conn.execute(
        "SELECT model, score FROM staged_tags WHERE concept_id='gnosis' ORDER BY id"
    ).fetchall()
    assert rows == [("qwen3.5-27b", 3), ("qwen-finetune-v1", 2)]


def test_unique_permits_same_model_different_prompt_version(conn: sqlite3.Connection) -> None:
    upsert_staged_tag(conn, "gnosticism.gospel-of-thomas.001", _tag("gnosis", 3), model="m", prompt_version="v1")
    upsert_staged_tag(conn, "gnosticism.gospel-of-thomas.001", _tag("gnosis", 2), model="m", prompt_version="v2")
    rows = conn.execute(
        "SELECT prompt_version FROM staged_tags WHERE concept_id='gnosis' ORDER BY id"
    ).fetchall()
    assert rows == [("v1",), ("v2",)]


def test_partial_index_only_constrains_pending(conn: sqlite3.Connection) -> None:
    """Once a row transitions out of pending, a new pending row with same
    provenance can land — settled audit history is preserved."""
    upsert_staged_tag(conn, "gnosticism.gospel-of-thomas.001", _tag("gnosis", 3), model="m")
    conn.execute("UPDATE staged_tags SET status='accepted' WHERE concept_id='gnosis'")
    upsert_staged_tag(conn, "gnosticism.gospel-of-thomas.001", _tag("gnosis", 1), model="m")
    rows = conn.execute(
        "SELECT status, score FROM staged_tags WHERE concept_id='gnosis' ORDER BY id"
    ).fetchall()
    assert rows == [("accepted", 3), ("pending", 1)]
