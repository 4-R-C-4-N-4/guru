"""Tests for todo:d267201a — spreading one tag_concepts.py run across more
than one llama.cpp server instead of contending for one.

Three layers, each tested independently and stub-only (no real sockets):
  1. llm.call_llamacpp's new base_url parameter (llm.py) — overrides the env
     default per-call, and concurrent threads passing different base_urls
     never see each other's target (no thread-local/env leakage).
  2. tag_concepts.py's --endpoint CLI flag and round-robin chunk->endpoint
     pinning through the worker pool.
  3. The per-endpoint slot pre-flight from todo:5955d038, applied once per
     --endpoint.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import threading
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT))

import tag_concepts  # noqa: E402
import llm  # noqa: E402


# ── llm.call_llamacpp(base_url=...) ──────────────────────────────────────────


class _FakeHTTPResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _chat_reply(base_used: str) -> bytes:
    return json.dumps({"choices": [{"message": {"content": f"seen:{base_used}"}}]}).encode()


def test_call_llamacpp_base_url_overrides_env(monkeypatch):
    monkeypatch.setenv("LLAMACPP_BASE_URL", "http://env-default:8080")
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        return _FakeHTTPResponse(_chat_reply(req.full_url))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = llm.call_llamacpp(model="m", system="s", prompt="p", max_tokens=10,
                                base_url="http://override:9090")

    assert seen["url"].startswith("http://override:9090")
    assert "override:9090" in result


def test_call_llamacpp_omitted_base_url_still_uses_env(monkeypatch):
    monkeypatch.setenv("LLAMACPP_BASE_URL", "http://env-default:8080")
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        return _FakeHTTPResponse(_chat_reply(req.full_url))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    llm.call_llamacpp(model="m", system="s", prompt="p", max_tokens=10)

    assert seen["url"].startswith("http://env-default:8080")


def test_call_llamacpp_base_url_does_not_leak_across_threads(monkeypatch):
    """Each thread calls with its own base_url. If base_url routing were
    done via an env write (the trap the ticket explicitly warns against)
    instead of a real parameter, concurrent threads would race and could
    see each other's target. Assert every thread's request landed on
    exactly the base_url IT passed, never another thread's."""
    n_threads = 8
    barrier = threading.Barrier(n_threads)

    def fake_urlopen(req, timeout=None):
        # Force maximum interleaving: every thread must reach this point
        # before any proceeds, so if there were shared mutable state
        # (e.g. os.environ) between the "compute base" and "issue request"
        # steps, threads would have every opportunity to stomp on it.
        barrier.wait(timeout=5)
        return _FakeHTTPResponse(_chat_reply(req.full_url))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    results: dict[int, str] = {}
    lock = threading.Lock()

    def worker(i: int):
        base = f"http://endpoint-{i}:8080"
        out = llm.call_llamacpp(model="m", system="s", prompt="p", max_tokens=10,
                                base_url=base)
        with lock:
            results[i] = out

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert len(results) == n_threads
    for i, out in results.items():
        assert out.startswith(f"seen:http://endpoint-{i}:8080"), (
            f"thread {i} saw a different thread's base_url — leakage: {out!r}"
        )


def test_call_llm_forwards_base_url_only_when_given():
    """call_llm's dispatch layer must not force every provider function to
    accept an unused base_url kwarg — it should only appear in the call
    when the caller actually passed one."""
    captured = {}

    def fake_llamacpp(model, system, prompt, max_tokens, timeout=1200, base_url=None):
        captured["base_url"] = base_url
        return "ok"

    import llm as llm_module
    orig = llm_module.PROVIDERS["llamacpp"]
    llm_module.PROVIDERS["llamacpp"] = fake_llamacpp
    try:
        llm.call_llm("llamacpp", "m", "s", "p", max_tokens=10)
        assert captured["base_url"] is None

        llm.call_llm("llamacpp", "m", "s", "p", max_tokens=10, base_url="http://x:1")
        assert captured["base_url"] == "http://x:1"
    finally:
        llm_module.PROVIDERS["llamacpp"] = orig


# ── --endpoint CLI flag ──────────────────────────────────────────────────────


def test_endpoint_flag_defaults_to_none():
    parser = tag_concepts.build_parser()
    assert parser.parse_args([]).endpoints is None


def test_endpoint_flag_is_repeatable():
    parser = tag_concepts.build_parser()
    args = parser.parse_args([
        "--endpoint", "http://127.0.0.1:8080",
        "--endpoint", "http://127.0.0.1:8081",
    ])
    assert args.endpoints == ["http://127.0.0.1:8080", "http://127.0.0.1:8081"]


# ── round-robin distribution through run_tagging ────────────────────────────


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


@pytest.fixture(autouse=True)
def _stub_taxonomy_and_slots(monkeypatch):
    monkeypatch.setattr(tag_concepts, "load_taxonomy",
                        lambda: [{"id": "gnosis", "definition": "d"}])
    # Keep these tests socket-free: report plenty of slots (and plenty of
    # per-slot context, todo:dcb3cce5 finding 2) everywhere so the
    # todo:5955d038 pre-flight (exercised separately below) never fires
    # here, and never falls through to a real HTTP request against these
    # fake hostnames (which would otherwise cost several seconds per test
    # waiting on DNS/connect failures instead of failing fast).
    monkeypatch.setattr(tag_concepts, "query_llamacpp_slots", lambda *a, **k: 64)
    monkeypatch.setattr(tag_concepts, "query_llamacpp_slot_ctx", lambda *a, **k: 32768)


def test_round_robin_pins_each_chunk_to_its_endpoint_by_position(tmp_path):
    n = 9
    db = tmp_path / "guru.db"
    ids = _make_db(db, n)
    endpoints = ["http://ep-a:8080", "http://ep-b:8080", "http://ep-c:8080"]

    calls: list[tuple[str, str]] = []
    lock = threading.Lock()

    def fake_call_llm(provider, model, system, prompt, max_tokens, base_url=None):
        # citation is embedded as "label:<chunk_id>" in the prompt (see
        # tag_concepts.build_prompt / SCHEMA above)
        cid = next(c for c in ids if f"label:{c}" in prompt)
        with lock:
            calls.append((cid, base_url))
        return "[]"

    import unittest.mock as mock
    with mock.patch.object(tag_concepts, "call_llm", fake_call_llm):
        tag_concepts.run_tagging(
            db_path=db, provider_name="llamacpp", model="qwen-3-4b-guru-test",
            batch_size=0, resume=False, tradition=None, text_id=None, delay=0.0,
            parallel=1, endpoints=endpoints,
        )

    assert len(calls) == n
    got = dict(calls)
    assert len(got) == n, "a chunk was called more or fewer than once"
    for i, cid in enumerate(ids):
        expected_endpoint = endpoints[i % len(endpoints)]
        assert got[cid] == expected_endpoint, (
            f"{cid} (position {i}) should be pinned to {expected_endpoint}, "
            f"got {got[cid]}"
        )


def test_single_endpoint_default_passes_no_base_url(tmp_path):
    """No --endpoint given -> base_url must never even appear in the
    call_llm invocation, matching pre-multi-endpoint behaviour exactly."""
    n = 4
    db = tmp_path / "guru.db"
    _make_db(db, n)

    seen_base_urls = []

    def fake_call_llm(provider, model, system, prompt, max_tokens):
        # Deliberately no base_url parameter — if tag_one_chunk ever passes
        # it unconditionally, this raises TypeError and the test fails.
        seen_base_urls.append("called-without-base_url-kwarg")
        return "[]"

    import unittest.mock as mock
    with mock.patch.object(tag_concepts, "call_llm", fake_call_llm):
        tag_concepts.run_tagging(
            db_path=db, provider_name="llamacpp", model="qwen-3-4b-guru-test",
            batch_size=0, resume=False, tradition=None, text_id=None, delay=0.0,
            parallel=2, endpoints=None,
        )

    assert len(seen_base_urls) == n


def test_two_endpoints_each_get_their_own_parallel_sized_pool(tmp_path):
    """--parallel is per-endpoint: with --parallel 2 and 2 endpoints, total
    concurrency is 4, but no single endpoint should ever see more than 2
    concurrent calls."""
    import time

    n = 12
    db = tmp_path / "guru.db"
    _make_db(db, n)
    endpoints = ["http://ep-a:8080", "http://ep-b:8080"]

    lock = threading.Lock()
    outstanding = {ep: 0 for ep in endpoints}
    max_outstanding = {ep: 0 for ep in endpoints}

    def fake_call_llm(provider, model, system, prompt, max_tokens, base_url=None):
        with lock:
            outstanding[base_url] += 1
            max_outstanding[base_url] = max(max_outstanding[base_url], outstanding[base_url])
        time.sleep(0.02)
        with lock:
            outstanding[base_url] -= 1
        return "[]"

    import unittest.mock as mock
    with mock.patch.object(tag_concepts, "call_llm", fake_call_llm):
        tag_concepts.run_tagging(
            db_path=db, provider_name="llamacpp", model="qwen-3-4b-guru-test",
            batch_size=0, resume=False, tradition=None, text_id=None, delay=0.0,
            parallel=2, endpoints=endpoints,
        )

    for ep in endpoints:
        assert max_outstanding[ep] <= 2, f"{ep} exceeded its per-endpoint --parallel budget"
        assert max_outstanding[ep] > 1, f"{ep} never actually ran concurrently"


def test_single_writer_invariant_holds_across_endpoints(tmp_path):
    """Regardless of how many endpoints fan the LLM calls out to, every
    sqlite write must land — same guarantee todo:0c34642e proved for a
    single endpoint, now checked with several."""
    n = 10
    db = tmp_path / "guru.db"
    ids = _make_db(db, n)
    endpoints = ["http://ep-a:8080", "http://ep-b:8080"]

    def fake_call_llm(provider, model, system, prompt, max_tokens, base_url=None):
        cid = next(c for c in ids if f"label:{c}" in prompt)
        return json.dumps([{"concept_id": f"c-{cid}", "score": 2, "justification": "j"}])

    import unittest.mock as mock
    with mock.patch.object(tag_concepts, "call_llm", fake_call_llm):
        tag_concepts.run_tagging(
            db_path=db, provider_name="llamacpp", model="qwen-3-4b-guru-test",
            batch_size=0, resume=False, tradition=None, text_id=None, delay=0.0,
            parallel=3, endpoints=endpoints,
        )

    conn = sqlite3.connect(str(db))
    rows = conn.execute("SELECT chunk_id, concept_id FROM staged_tags").fetchall()
    assert len(rows) == n
    assert all(concept_id == f"c-{chunk_id}" for chunk_id, concept_id in rows)
    progress = [r[0] for r in conn.execute("SELECT chunk_id FROM tagging_progress")]
    assert sorted(progress) == sorted(ids)
    assert len(progress) == len(set(progress))


# ── per-endpoint slot pre-flight (todo:5955d038, applied per --endpoint) ────


def test_preflight_runs_once_per_endpoint_with_the_right_base_url(monkeypatch, tmp_path):
    n = 2
    db = tmp_path / "guru.db"
    _make_db(db, n)
    endpoints = ["http://ep-a:8080", "http://ep-b:8080"]

    queried = []

    def fake_query_slots(base_url=None, timeout=5.0):
        queried.append(base_url)
        return 8

    monkeypatch.setattr(tag_concepts, "load_taxonomy",
                        lambda: [{"id": "gnosis", "definition": "d"}])
    monkeypatch.setattr(tag_concepts, "query_llamacpp_slots", fake_query_slots)
    monkeypatch.setattr(tag_concepts, "call_llm", lambda *a, **k: "[]")

    tag_concepts.run_tagging(
        db_path=db, provider_name="llamacpp", model="qwen-3-4b-guru-test",
        batch_size=0, resume=False, tradition=None, text_id=None, delay=0.0,
        parallel=4, endpoints=endpoints,
    )

    assert sorted(queried) == sorted(endpoints)


def test_preflight_refuses_when_one_of_several_endpoints_is_too_small(monkeypatch, tmp_path):
    n = 2
    db = tmp_path / "guru.db"
    _make_db(db, n)
    endpoints = ["http://plenty:8080", "http://tiny:8080"]

    def fake_query_slots(base_url=None, timeout=5.0):
        return 8 if base_url == "http://plenty:8080" else 1

    monkeypatch.setattr(tag_concepts, "load_taxonomy",
                        lambda: [{"id": "gnosis", "definition": "d"}])
    monkeypatch.setattr(tag_concepts, "query_llamacpp_slots", fake_query_slots)
    monkeypatch.setattr(tag_concepts, "call_llm", lambda *a, **k: "[]")

    with pytest.raises(tag_concepts.InsufficientServerSlotsError, match="tiny"):
        tag_concepts.run_tagging(
            db_path=db, provider_name="llamacpp", model="qwen-3-4b-guru-test",
            batch_size=0, resume=False, tradition=None, text_id=None, delay=0.0,
            parallel=4, endpoints=endpoints,
        )


def test_model_guard_sees_total_concurrency_across_endpoints(monkeypatch, tmp_path):
    """Two endpoints at --parallel 1 each is still 2-wide multiplexing —
    the model guard must judge the combined total, not the raw flag, so it
    can't be dodged by spreading the same disallowed model across servers."""
    n = 2
    db = tmp_path / "guru.db"
    _make_db(db, n)

    monkeypatch.setattr(tag_concepts, "load_taxonomy",
                        lambda: [{"id": "gnosis", "definition": "d"}])
    monkeypatch.setattr(tag_concepts, "query_llamacpp_slots", lambda *a, **k: 64)

    with pytest.raises(tag_concepts.ParallelModelNotAllowedError):
        tag_concepts.run_tagging(
            db_path=db, provider_name="llamacpp", model="Qwen3.5-27B-UD-Q4_K_XL.gguf",
            batch_size=0, resume=False, tradition=None, text_id=None, delay=0.0,
            parallel=1, endpoints=["http://a:8080", "http://b:8080"],
        )


# ── duplicate --endpoint is de-duplicated (todo:dcb3cce5 finding 6) ────────


def test_duplicate_endpoint_collapses_to_one_pool_not_two(tmp_path, monkeypatch, caplog):
    """Passing the same URL twice used to build two independent
    `parallel`-sized ThreadPoolExecutor pools against what is really one
    server — 2 * parallel concurrent requests landing on a server
    pre-flighted (and, before this fix, actually launched) for `parallel`.
    De-duping must collapse it to exactly one pool, so max concurrency
    against that one server never exceeds `parallel`."""
    import time

    n = 12
    db = tmp_path / "guru.db"
    _make_db(db, n)
    dup = "http://only-one:8080"

    lock = threading.Lock()
    outstanding = {"n": 0, "max": 0}

    def fake_call_llm(provider, model, system, prompt, max_tokens, base_url=None):
        assert base_url == dup
        with lock:
            outstanding["n"] += 1
            outstanding["max"] = max(outstanding["max"], outstanding["n"])
        time.sleep(0.02)
        with lock:
            outstanding["n"] -= 1
        return "[]"

    with caplog.at_level("WARNING"):
        import unittest.mock as mock
        with mock.patch.object(tag_concepts, "call_llm", fake_call_llm):
            tag_concepts.run_tagging(
                db_path=db, provider_name="llamacpp", model="qwen-3-4b-guru-test",
                batch_size=0, resume=False, tradition=None, text_id=None, delay=0.0,
                parallel=2, endpoints=[dup, dup],
            )

    # If the dedupe were missing, two 2-worker pools against the same
    # server would let up to 4 requests run concurrently.
    assert outstanding["max"] <= 2
    assert any("distinct" in r.message for r in caplog.records)


def test_endpoint_dedupe_preserves_first_occurrence_order(tmp_path, monkeypatch):
    """Round-robin pinning (todo:d267201a) is by list position, so dedupe
    must preserve first-occurrence order, not e.g. sort or set-scramble
    it, or chunks would pin to the wrong endpoint."""
    n = 6
    db = tmp_path / "guru.db"
    ids = _make_db(db, n)
    endpoints = ["http://ep-b:8080", "http://ep-a:8080", "http://ep-b:8080"]
    expected_deduped = ["http://ep-b:8080", "http://ep-a:8080"]

    calls: list[tuple[str, str]] = []
    lock = threading.Lock()

    def fake_call_llm(provider, model, system, prompt, max_tokens, base_url=None):
        cid = next(c for c in ids if f"label:{c}" in prompt)
        with lock:
            calls.append((cid, base_url))
        return "[]"

    import unittest.mock as mock
    with mock.patch.object(tag_concepts, "call_llm", fake_call_llm):
        tag_concepts.run_tagging(
            db_path=db, provider_name="llamacpp", model="qwen-3-4b-guru-test",
            batch_size=0, resume=False, tradition=None, text_id=None, delay=0.0,
            parallel=1, endpoints=endpoints,
        )

    got = dict(calls)
    for i, cid in enumerate(ids):
        expected_endpoint = expected_deduped[i % len(expected_deduped)]
        assert got[cid] == expected_endpoint


def test_endpoints_without_duplicates_logs_no_dedupe_warning(tmp_path, caplog):
    """No duplicates -> no warning; the log line is specifically about
    collapsed duplicates, not a routine per-run notice."""
    n = 2
    db = tmp_path / "guru.db"
    _make_db(db, n)
    endpoints = ["http://ep-a:8080", "http://ep-b:8080"]

    import unittest.mock as mock
    with caplog.at_level("WARNING"):
        with mock.patch.object(tag_concepts, "call_llm", lambda *a, **k: "[]"):
            tag_concepts.run_tagging(
                db_path=db, provider_name="llamacpp", model="qwen-3-4b-guru-test",
                batch_size=0, resume=False, tradition=None, text_id=None, delay=0.0,
                parallel=1, endpoints=endpoints,
            )

    assert not any("distinct" in r.message for r in caplog.records)
