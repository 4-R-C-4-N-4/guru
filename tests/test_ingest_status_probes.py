"""
Node 10 probes coverage, and nodes 11/14 can say "queued, awaiting apply".

todo:1f6d2c11 — the node 10 probe asked "do any staged_tags rows exist for
this text", not "does every chunk have them", so one surviving chunk satisfied
it. After a partial re-chunk, yoga-sutras-book-02 reported

    [x] 10-tag-concepts   Propose chunk-concept tags

with 3 of 55 chunks tagged. Node 11's gate is "no pending staged_tags remain",
and 52 chunks carrying no tags at all made that trivially true, so 10 and 11
both went green and the text walked to node 12 silently under-tagged. A driver
following `status` faithfully produces an under-tagged corpus.

todo:4264c23f — the review gates test live/staged state only, so queued but
unapplied `review_actions` were invisible to them. The single most common
intermediate state in the pipeline, "every judgement is made and is sitting in
the queue waiting for you", rendered identically to "nobody has looked at this
yet". After the yoga-sutras node 14 pass, 696 validated verdicts were queued
and node 14 reported "nothing staged to review".

Run with: pytest tests/test_ingest_status_probes.py
"""

import sqlite3

import pytest

from guru.ingest import Ctx, _p_edge_review, _p_tag, _p_tag_review

SCHEMA = """
CREATE TABLE nodes (id TEXT PRIMARY KEY, type TEXT);
CREATE TABLE tagging_progress (chunk_id TEXT PRIMARY KEY);
CREATE TABLE staged_tags (
    id INTEGER PRIMARY KEY, chunk_id TEXT, status TEXT DEFAULT 'pending');
CREATE TABLE staged_edges (
    id INTEGER PRIMARY KEY, source_chunk TEXT, target_chunk TEXT,
    status TEXT DEFAULT 'pending');
CREATE TABLE review_actions (
    id INTEGER PRIMARY KEY, target_id INTEGER, target_table TEXT,
    applied_at TEXT);
"""

# christian_mysticism is deliberate: the underscore is a LIKE wildcard, so a
# probe that forgets ESCAPE counts a neighbouring tradition's chunks.
TRADITION, TEXT = "christian_mysticism", "julian-revelations"
PREFIX = f"{TRADITION}.{TEXT}."


@pytest.fixture()
def ctx():
    db = sqlite3.connect(":memory:")
    db.executescript(SCHEMA)
    return Ctx(source_id=TEXT, tradition=TRADITION, entry={}, db=db, ledger={})


def add_chunks(ctx, n, tagged=0, progress=None):
    """n chunk nodes; the first `tagged` get a staged_tag. `progress` defaults
    to "the tagger processed every chunk"."""
    progress = n if progress is None else progress
    for i in range(1, n + 1):
        cid = f"{PREFIX}{i:03d}"
        ctx.db.execute("INSERT INTO nodes VALUES (?, 'chunk')", (cid,))
        if i <= progress:
            ctx.db.execute("INSERT INTO tagging_progress VALUES (?)", (cid,))
        if i <= tagged:
            ctx.db.execute(
                "INSERT INTO staged_tags(chunk_id, status) VALUES (?, 'pending')", (cid,))


# ------------------------------------------------------- node 10, coverage


def test_tag_probe_fails_when_most_chunks_were_never_tagged(ctx):
    """The yoga-sutras-book-02 shape: 3 of 55 tagged after a partial re-chunk."""
    add_chunks(ctx, 55, tagged=3, progress=3)
    ok, msg = _p_tag(ctx)
    assert not ok
    assert "52 of 55 chunks untagged" in msg


def test_tag_probe_passes_when_every_chunk_was_processed(ctx):
    add_chunks(ctx, 55, tagged=55)
    ok, msg = _p_tag(ctx)
    assert ok
    assert "all 55 chunks tagged" in msg


def test_tag_probe_accepts_a_processed_chunk_that_produced_no_tags(ctx):
    """Why the probe keys on tagging_progress rather than staged_tags: a chunk
    the tagger read and found nothing in is legitimately tagless.
    plotinus-select-works-index has 107 of 752 such chunks with all 752
    processed — keying on staged_tags would call that a gap forever."""
    add_chunks(ctx, 752, tagged=645)
    ok, msg = _p_tag(ctx)
    assert ok, msg


def test_tag_probe_reports_no_chunk_nodes_before_node_09(ctx):
    ok, msg = _p_tag(ctx)
    assert not ok
    assert "node 09" in msg


def test_tag_probe_says_so_when_it_could_not_check_coverage(ctx):
    """Ctx.count returns 0 on any sqlite error, and 0 is also a clean coverage
    result. Without has_table, a database with no tagging_progress reports a
    green node on the strength of a query that never ran."""
    add_chunks(ctx, 10, tagged=1)
    ctx.db.execute("DROP TABLE tagging_progress")
    ok, msg = _p_tag(ctx)
    assert ok, "pre-tagging_progress databases keep the old existence probe"
    assert "coverage unverified" in msg


def test_tag_probe_does_not_count_a_neighbouring_tradition(ctx):
    add_chunks(ctx, 4, tagged=4)
    # christian#mysticism matches christian_mysticism if '_' is left unescaped.
    for i in range(1, 40):
        ctx.db.execute("INSERT INTO nodes VALUES (?, 'chunk')",
                       (f"christianXmysticism.{TEXT}.{i:03d}",))
    ok, msg = _p_tag(ctx)
    assert ok and "all 4 chunks tagged" in msg


# --------------------------------------- nodes 11 and 14, the unapplied queue


def queue(ctx, target_table, target_id, applied=False):
    ctx.db.execute(
        "INSERT INTO review_actions(target_id, target_table, applied_at) VALUES (?,?,?)",
        (target_id, target_table, "2026-08-11T00:00:00Z" if applied else None))


def test_tag_review_reports_a_queue_sitting_behind_a_clean_gate(ctx):
    """Reachable through reassign: the donor goes to 'reassigned' and a new
    pending row is inserted, so nothing is pending while verdicts wait."""
    add_chunks(ctx, 3, tagged=3)
    ctx.db.execute("UPDATE staged_tags SET status='accepted'")
    for tag_id in (1, 2, 3):
        queue(ctx, "staged_tags", tag_id)
    ok, msg = _p_tag_review(ctx)
    assert not ok, "a queued verdict is not an applied one — the node stays open"
    assert "3 tag verdicts queued, awaiting your apply" in msg


def test_tag_review_passes_once_the_queue_is_applied(ctx):
    add_chunks(ctx, 3, tagged=3)
    ctx.db.execute("UPDATE staged_tags SET status='accepted'")
    for tag_id in (1, 2, 3):
        queue(ctx, "staged_tags", tag_id, applied=True)
    ok, msg = _p_tag_review(ctx)
    assert ok
    assert "all 3 staged tags reviewed" in msg


def test_tag_review_mentions_the_queue_alongside_pending_rows(ctx):
    add_chunks(ctx, 5, tagged=5)
    ctx.db.execute("UPDATE staged_tags SET status='accepted' WHERE id <= 2")
    queue(ctx, "staged_tags", 1)
    ok, msg = _p_tag_review(ctx)
    assert not ok
    assert "3 of 5 staged tags still pending" in msg
    assert "1 tag verdict queued" in msg, "singular, and not swallowed by the pending count"


def test_edge_review_reports_the_queue_rather_than_an_absence(ctx):
    """The yoga-sutras node 14 case: 696 verdicts queued and validated clean,
    and the gate said "nothing staged to review" — indistinguishable from a
    text nobody had started."""
    add_chunks(ctx, 2)
    ctx.db.execute(
        "INSERT INTO staged_edges(source_chunk, target_chunk, status) "
        "VALUES (?, 'hinduism.bhagavad-gita-chapter-02.001', 'rejected')",
        (f"{PREFIX}001",))
    queue(ctx, "staged_edges", 1)
    ok, msg = _p_edge_review(ctx)
    assert not ok
    assert "1 edge verdict queued, awaiting your apply" in msg


def test_edge_review_counts_a_queue_on_an_edge_pointing_at_this_text(ctx):
    """Edges are scoped by either endpoint, and the queue has to follow."""
    add_chunks(ctx, 2)
    ctx.db.execute(
        "INSERT INTO staged_edges(source_chunk, target_chunk, status) "
        "VALUES ('hinduism.bhagavad-gita-chapter-02.001', ?, 'pending')",
        (f"{PREFIX}001",))
    queue(ctx, "staged_edges", 1)
    ok, msg = _p_edge_review(ctx)
    assert not ok
    assert "1 edge verdict queued" in msg


def test_review_queues_do_not_cross_target_tables(ctx):
    """review_actions.target_id is polymorphic with no FK — staged_tags row 1
    and staged_edges row 1 are different rows that share an id."""
    add_chunks(ctx, 1, tagged=1)
    ctx.db.execute("UPDATE staged_tags SET status='accepted'")
    ctx.db.execute(
        "INSERT INTO staged_edges(source_chunk, target_chunk, status) "
        "VALUES (?, 'hinduism.bhagavad-gita-chapter-02.001', 'rejected')",
        (f"{PREFIX}001",))
    queue(ctx, "staged_edges", 1)
    ok, _ = _p_tag_review(ctx)
    assert ok, "an edge verdict must not hold node 11 open"
