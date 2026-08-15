"""Tests for --parallel N (todo:0c34642e): a bounded ThreadPoolExecutor over
tag_one_chunk with a single DB-writer thread.

Exercises run_tagging() end-to-end against a temp sqlite file (run_tagging
owns its own connection lifecycle, so an in-memory :memory: db won't survive
across the open/close it does internally). call_llm is stubbed throughout —
no network, no GPU, no model server.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT))

import tag_concepts  # noqa: E402


SCHEMA = """
    CREATE TABLE nodes (
        id            TEXT PRIMARY KEY,
        type          TEXT NOT NULL CHECK(type IN ('tradition','concept','chunk')),
        tradition_id  TEXT REFERENCES nodes(id),
        label         TEXT NOT NULL,
        metadata_json TEXT DEFAULT '{}'
    );
    CREATE TABLE staged_tags (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        chunk_id        TEXT NOT NULL,
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
    CREATE TABLE tagging_progress (chunk_id TEXT PRIMARY KEY);
    CREATE TABLE staged_cleanups (chunk_id TEXT, status TEXT);
"""


def _make_db(path: Path, n: int) -> list[str]:
    """Seed a temp sqlite file with n chunk nodes under tradition 't'.
    Returns the ordered list of chunk ids."""
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO nodes(id, type, label) VALUES ('t', 'tradition', 'T')")
    ids = [f"t.x.{i:03d}" for i in range(n)]
    for cid in ids:
        conn.execute(
            "INSERT INTO nodes(id, type, tradition_id, label, metadata_json) "
            "VALUES (?, 'chunk', 't', ?, ?)",
            (cid, f"label:{cid}", json.dumps({"text_id": "x"})),
        )
    conn.commit()
    conn.close()
    return ids


_CITATION_RE = re.compile(r"Passage \(label:([^)]+)\):")


def _chunk_id_from_prompt(prompt: str) -> str:
    m = _CITATION_RE.search(prompt)
    assert m, f"couldn't find citation in prompt: {prompt[:200]!r}"
    return m.group(1)


def _parse_done_line(stdout: str) -> dict[str, int]:
    m = re.search(
        r"Done: (\d+) chunks tagged, (\d+) errors\s+\|\s+rows: "
        r"inserted=(\d+) superseded=(\d+) skipped_reviewed=(\d+) conflict=(\d+)",
        stdout,
    )
    assert m, f"couldn't find summary line in: {stdout!r}"
    return {
        "tagged": int(m.group(1)),
        "errors": int(m.group(2)),
        "inserted": int(m.group(3)),
        "superseded": int(m.group(4)),
        "skipped_reviewed": int(m.group(5)),
        "conflict": int(m.group(6)),
    }


@pytest.fixture(autouse=True)
def _stub_taxonomy(monkeypatch):
    monkeypatch.setattr(tag_concepts, "load_taxonomy",
                        lambda: [{"id": "gnosis", "definition": "d"}])


@pytest.fixture(autouse=True)
def _stub_slot_preflight(monkeypatch):
    """todo:5955d038's slot pre-flight would otherwise try a real HTTP
    request to LLAMACPP_BASE_URL for every --parallel > 1 run in this file.
    Stub both the slot-count and per-slot-context (todo:dcb3cce5 finding 2)
    queries to report plenty of both so these tests stay socket-free and
    keep exercising only the worker-pool behaviour they're named for."""
    monkeypatch.setattr(tag_concepts, "query_llamacpp_slots", lambda *a, **k: 64)
    monkeypatch.setattr(tag_concepts, "query_llamacpp_slot_ctx", lambda *a, **k: 32768)


def _run(db_path: Path, parallel: int, delay: float = 0.0, **kw) -> None:
    tag_concepts.run_tagging(
        db_path=db_path,
        provider_name="llamacpp",
        model="qwen-3-4b-guru-test-model",
        batch_size=0,
        resume=False,
        tradition=None,
        text_id=None,
        delay=delay,
        parallel=parallel,
        **kw,
    )


# ── N=1 stays on the serial path ─────────────────────────────────────────────


def test_parallel_1_never_touches_the_thread_pool(tmp_path, monkeypatch, capsys):
    def _boom(*a, **k):
        raise AssertionError("_run_parallel_pool must not run for --parallel 1")

    monkeypatch.setattr(tag_concepts, "_run_parallel_pool", _boom)
    monkeypatch.setattr(tag_concepts, "call_llm",
                        lambda *a, **k: '[{"concept_id": "gnosis", "score": 2, "justification": "j"}]')

    db = tmp_path / "guru.db"
    ids = _make_db(db, 5)

    _run(db, parallel=1)

    summary = _parse_done_line(capsys.readouterr().out)
    assert summary["tagged"] == 5
    assert summary["errors"] == 0
    assert summary["inserted"] == 5

    conn = sqlite3.connect(str(db))
    done = {r[0] for r in conn.execute("SELECT chunk_id FROM tagging_progress")}
    assert done == set(ids)


# ── N>1: every chunk written exactly once, no cross-contamination ───────────


def test_parallel_writes_every_chunk_exactly_once_out_of_order_completion(tmp_path, monkeypatch, capsys):
    """Later-submitted chunks are made to finish first (reversed sleep), so
    completion order is guaranteed to differ from submission order. Each
    chunk's own tag must still land on its own row — no writer mixing results
    across chunks — and every chunk completes exactly once."""
    n = 16
    parallel = 4
    db = tmp_path / "guru.db"
    ids = _make_db(db, n)

    def fake_call_llm(provider, model, system, prompt, max_tokens):
        cid = _chunk_id_from_prompt(prompt)
        idx = int(cid.rsplit(".", 1)[-1])
        time.sleep(0.002 * (n - idx))  # reverse of submission order
        return json.dumps([{
            "concept_id": f"c-{cid}", "score": 2, "justification": f"for {cid}",
        }])

    monkeypatch.setattr(tag_concepts, "call_llm", fake_call_llm)

    _run(db, parallel=parallel)

    summary = _parse_done_line(capsys.readouterr().out)
    assert summary["tagged"] == n
    assert summary["errors"] == 0
    assert summary["inserted"] == n

    conn = sqlite3.connect(str(db))
    rows = conn.execute("SELECT chunk_id, concept_id FROM staged_tags").fetchall()
    assert len(rows) == n
    # Every row's concept_id is derived from its OWN chunk_id — proves the
    # writer never attributed one chunk's LLM result to another chunk.
    assert all(concept_id == f"c-{chunk_id}" for chunk_id, concept_id in rows)

    progress = [r[0] for r in conn.execute("SELECT chunk_id FROM tagging_progress")]
    assert sorted(progress) == sorted(ids)
    assert len(progress) == len(set(progress)), "a chunk was marked complete more than once"


def test_parallel_outcome_counters_match_serial_for_same_input(tmp_path, monkeypatch):
    """Same chunk set, same (deterministic) LLM stub — --parallel N must
    produce identical staged_tags content and counters to --parallel 1,
    modulo row order."""
    n = 12

    def fake_call_llm(provider, model, system, prompt, max_tokens):
        cid = _chunk_id_from_prompt(prompt)
        return json.dumps([
            {"concept_id": "gnosis", "score": 2, "justification": f"for {cid}"},
            {"concept_id": "light", "score": 1, "justification": f"also {cid}"},
        ])

    monkeypatch.setattr(tag_concepts, "call_llm", fake_call_llm)

    db_serial = tmp_path / "serial.db"
    _make_db(db_serial, n)
    _run(db_serial, parallel=1)

    db_parallel = tmp_path / "parallel.db"
    _make_db(db_parallel, n)
    _run(db_parallel, parallel=4)

    def _rows(db_path):
        conn = sqlite3.connect(str(db_path))
        return sorted(conn.execute(
            "SELECT chunk_id, concept_id, score FROM staged_tags"
        ).fetchall())

    assert _rows(db_serial) == _rows(db_parallel)

    def _counts(db_path):
        conn = sqlite3.connect(str(db_path))
        tags = conn.execute("SELECT COUNT(*) FROM staged_tags").fetchone()[0]
        done = conn.execute("SELECT COUNT(*) FROM tagging_progress").fetchone()[0]
        return tags, done

    assert _counts(db_serial) == _counts(db_parallel) == (n * 2, n)


# ── concurrency actually bounded to N ────────────────────────────────────────


def test_parallel_never_exceeds_n_concurrent_llm_calls(tmp_path, monkeypatch):
    n = 12
    parallel = 3
    db = tmp_path / "guru.db"
    _make_db(db, n)

    lock = threading.Lock()
    state = {"outstanding": 0, "max_outstanding": 0}

    def fake_call_llm(provider, model, system, prompt, max_tokens):
        with lock:
            state["outstanding"] += 1
            state["max_outstanding"] = max(state["max_outstanding"], state["outstanding"])
        time.sleep(0.02)
        with lock:
            state["outstanding"] -= 1
        return "[]"

    monkeypatch.setattr(tag_concepts, "call_llm", fake_call_llm)

    start = time.monotonic()
    _run(db, parallel=parallel)
    elapsed = time.monotonic() - start

    # Never more concurrently-executing calls than worker threads.
    assert state["max_outstanding"] <= parallel
    # But real overlap did happen (not silently serialized) — a fully
    # serial run of n * 0.02s calls would take ~0.24s; parallel=3 should
    # finish well under that.
    assert elapsed < (n * 0.02) * 0.8
    # And parallelism was actually exercised, not just wired to 1.
    assert state["max_outstanding"] > 1


# ── an exception inside a worker doesn't kill the run ────────────────────────


def test_parallel_worker_exception_does_not_kill_run_or_lose_other_results(tmp_path, monkeypatch, capsys):
    """Simulate a failure that reaches _run_parallel_pool's future.result()
    (not the failure already-handled inside tag_one_chunk) by making the
    module-level tag_one_chunk itself raise for one specific chunk. The rest
    of the run must complete and that chunk must be counted as an error, not
    silently dropped or fatal to the process."""
    n = 8
    db = tmp_path / "guru.db"
    ids = _make_db(db, n)
    poison = ids[3]

    real_tag_one_chunk = tag_concepts.tag_one_chunk

    def flaky_tag_one_chunk(chunk, concepts, provider_name, model, max_body_chars=None, base_url=None):
        if chunk["id"] == poison:
            raise RuntimeError("simulated worker-thread crash")
        return real_tag_one_chunk(chunk, concepts, provider_name, model,
                                  max_body_chars=max_body_chars, base_url=base_url)

    monkeypatch.setattr(tag_concepts, "tag_one_chunk", flaky_tag_one_chunk)
    monkeypatch.setattr(tag_concepts, "call_llm",
                        lambda *a, **k: '[{"concept_id": "gnosis", "score": 2, "justification": "j"}]')

    _run(db, parallel=3)

    summary = _parse_done_line(capsys.readouterr().out)
    assert summary["errors"] == 1
    assert summary["tagged"] == n - 1

    conn = sqlite3.connect(str(db))
    done = {r[0] for r in conn.execute("SELECT chunk_id FROM tagging_progress")}
    assert done == set(ids) - {poison}
    assert poison not in done


# ── a DB-write failure doesn't kill the run (out-of-range score etc.) ───────


def test_serial_db_write_failure_does_not_kill_run(tmp_path, monkeypatch, capsys):
    """A score the schema's CHECK constraint rejects must be counted as one
    error and skipped, not crash the whole serial run."""
    n = 5
    db = tmp_path / "guru.db"
    ids = _make_db(db, n)
    poison = ids[2]

    def fake_call_llm(provider, model, system, prompt, max_tokens):
        cid = _chunk_id_from_prompt(prompt)
        score = 99 if cid == poison else 2
        return json.dumps([{"concept_id": "gnosis", "score": score, "justification": "j"}])

    monkeypatch.setattr(tag_concepts, "call_llm", fake_call_llm)

    _run(db, parallel=1)

    summary = _parse_done_line(capsys.readouterr().out)
    assert summary["errors"] == 1
    assert summary["tagged"] == n - 1

    conn = sqlite3.connect(str(db))
    done = {r[0] for r in conn.execute("SELECT chunk_id FROM tagging_progress")}
    assert done == set(ids) - {poison}


def test_parallel_db_write_failure_does_not_kill_run(tmp_path, monkeypatch, capsys):
    n = 8
    db = tmp_path / "guru.db"
    ids = _make_db(db, n)
    poison = ids[3]

    def fake_call_llm(provider, model, system, prompt, max_tokens):
        cid = _chunk_id_from_prompt(prompt)
        score = 99 if cid == poison else 2
        return json.dumps([{"concept_id": "gnosis", "score": score, "justification": "j"}])

    monkeypatch.setattr(tag_concepts, "call_llm", fake_call_llm)

    _run(db, parallel=3)

    summary = _parse_done_line(capsys.readouterr().out)
    assert summary["errors"] == 1
    assert summary["tagged"] == n - 1

    conn = sqlite3.connect(str(db))
    done = {r[0] for r in conn.execute("SELECT chunk_id FROM tagging_progress")}
    assert done == set(ids) - {poison}
    assert poison not in done


# ── --delay: no wasted trailing sleep per worker lane ────────────────────────


def test_parallel_skips_delay_after_each_lanes_last_chunk(tmp_path, monkeypatch):
    """Mirrors the serial path's "no sleep after the last chunk" rule per
    worker lane: with n=6 chunks round-robinned across parallel=3 lanes (2
    chunks per lane), each lane's second (last) chunk must not pay --delay,
    so total elapsed time is close to one delay period, not two."""
    n = 6
    parallel = 3
    delay = 0.2
    db = tmp_path / "guru.db"
    _make_db(db, n)

    monkeypatch.setattr(tag_concepts, "call_llm", lambda *a, **k: "[]")

    start = time.monotonic()
    _run(db, parallel=parallel, delay=delay)
    elapsed = time.monotonic() - start

    # Each lane does 2 chunks; only the first should sleep --delay. If the
    # bug were still present (unconditional sleep after every chunk), this
    # would take ~2*delay per lane instead of ~1*delay.
    assert elapsed < delay * 1.5


# ── --resume semantics preserved under --parallel ────────────────────────────


def test_parallel_resume_skips_already_tagged_chunks(tmp_path, monkeypatch):
    n = 6
    db = tmp_path / "guru.db"
    ids = _make_db(db, n)

    conn = sqlite3.connect(str(db))
    already_done = {ids[0], ids[2]}
    for cid in already_done:
        conn.execute("INSERT INTO tagging_progress VALUES (?)", (cid,))
    conn.commit()
    conn.close()

    seen = []
    lock = threading.Lock()

    def fake_call_llm(provider, model, system, prompt, max_tokens):
        cid = _chunk_id_from_prompt(prompt)
        with lock:
            seen.append(cid)
        return "[]"

    monkeypatch.setattr(tag_concepts, "call_llm", fake_call_llm)

    tag_concepts.run_tagging(
        db_path=db, provider_name="llamacpp", model="qwen-3-4b-guru-test-model", batch_size=0,
        resume=True, tradition=None, text_id=None, delay=0.0, parallel=3,
    )

    assert set(seen) == set(ids) - already_done


# ── Ctrl-C during --parallel doesn't hang (todo:dcb3cce5 finding 5) ─────────


def test_parallel_ctrl_c_cancels_queued_work_and_does_not_hang(tmp_path, monkeypatch):
    """A worker observing a KeyboardInterrupt (standing in for a real Ctrl-C
    landing on the main thread — either while it's blocked in wait() or,
    as simulated here, when it calls fut.result() on a future that raised
    one) must not be swallowed, must not be left for the old bare
    ExitStack's shutdown(wait=True) to block on, and must not silently
    drain the rest of the queue.

    Before this fix, the ExitStack around the executors called
    shutdown(wait=True) with no cancel_futures on the way out regardless of
    why the `with` block was exited — so even a prompt KeyboardInterrupt
    would still wait for every already-queued chunk to run to completion
    (up to DEFAULT_HTTP_TIMEOUT, 1200s, per in-flight call) before the
    process actually stopped.

    n=20 chunks are seeded but at most 4 (parallel=2 *
    PARALLEL_INFLIGHT_MULTIPLIER=2) are ever submitted to the executor
    before the interrupt is raised — chunks 4-19 are provably never
    touched, since submit_next() for further chunks only runs from inside
    the per-completion loop this test's poison chunk aborts out of."""
    n = 20
    parallel = 2
    db = tmp_path / "guru.db"
    _make_db(db, n)

    calls = []
    lock = threading.Lock()

    def fake_call_llm(provider, model, system, prompt, max_tokens):
        cid = _chunk_id_from_prompt(prompt)
        with lock:
            calls.append(cid)
        idx = int(cid.rsplit(".", 1)[-1])
        if idx == 0:
            raise KeyboardInterrupt()
        # Any chunk that actually starts (already claimed by a worker
        # thread before shutdown(cancel_futures=True) could stop it) keeps
        # running in the background — this must not block the function's
        # return, which is exactly the property under test.
        time.sleep(1.5)
        return "[]"

    monkeypatch.setattr(tag_concepts, "call_llm", fake_call_llm)

    start = time.monotonic()
    with pytest.raises(KeyboardInterrupt):
        _run(db, parallel=parallel)
    elapsed = time.monotonic() - start

    # Prompt: nowhere near the 1.5s a single already-running chunk sleeps
    # for, let alone what draining the rest of the queue would cost.
    assert elapsed < 1.0
    # The queue was actually cut short, not drained to completion — at
    # most the initial priming wave (parallel * PARALLEL_INFLIGHT_MULTIPLIER
    # = 4) could ever have been submitted before the bail-out.
    assert len(calls) <= parallel * tag_concepts.PARALLEL_INFLIGHT_MULTIPLIER
    assert len(calls) < n
