"""Hierarchical fold merge (todo:0a81a956) — extends test_dossier_fold_degradation.

Live evidence (blavatsky-sd c12): the two residual L1 gaps (~6k tokens each)
folded their ~20 leaf sub-summaries fine, then the FLAT MERGE had to squeeze
~5,000 tokens into a 300-token band in one call — ~17:1 under keep-all-claims.
Outcomes: merge-at-777 (8% over band) or verbatim-echo escape. The fix groups
leaves into clusters of <=BRANCH_FACTOR and merges level by level; depth is
ceil(log_BRANCH_FACTOR(n_leaves)), provenance stays '{L1_TPL}-folded'.
"""
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location(
    "generate_dossiers", PROJECT_ROOT / "scripts" / "generate_dossiers.py")
gd = importlib.util.module_from_spec(_spec)
sys.modules["generate_dossiers"] = gd
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
_spec.loader.exec_module(gd)

import build_dossiers as bd  # noqa: E402

BF = gd.BRANCH_FACTOR


def _fake_v_prose(raw, lo, hi, source=None):
    n = len(raw.strip().split())
    if not (lo * 0.5 <= n <= hi * 2):
        raise ValueError(f"prose length {n} outside sanity band [{lo}, {hi}]")
    return raw.strip()


@pytest.fixture()
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE staged_summaries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        summary_id TEXT, work_id TEXT, text_id TEXT, level INTEGER,
        section_span TEXT, child_chunk_ids TEXT, child_summary_ids TEXT,
        body TEXT, token_count INTEGER, model TEXT, prompt_version TEXT,
        status TEXT DEFAULT 'pending')""")
    yield conn


class FakeGen(gd.Generator):
    def __init__(self, responses, conn):
        self.cfg = {"provider": "test", "model": "test-model"}
        self.conn = conn
        self.plan = {"works": []}
        self.limit = 0
        self.calls = 0
        self.prompts = []
        self.responses = list(responses)
        self.inserted = []

    def _llm(self, system, prompt):
        self.calls += 1
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("ran out of canned responses")
        return self.responses.pop(0)

    def _preamble(self, wp):
        return "PREAMBLE"

    def _insert_summary(self, summary_id, wp, text_id, level, span, chunk_ids,
                        child_sids, body, pv):
        self.inserted.append((summary_id, pv))
        super()._insert_summary(summary_id, {"work_id": "w"}, text_id, level,
                                span, chunk_ids, child_sids, body, pv)


def _setup(n_chunks=20, span_tokens=6000):
    """A deep span that packs into n_chunks leaves."""
    span = {"text_id": "t", "slug": "deep", "label": "Page 79 part 2",
            "chunk_ids": [f"x.t.{i:03d}" for i in range(1, n_chunks + 1)],
            "token_count": span_tokens}
    wp = {"work_id": "w", "label": "Work W", "tradition": "x",
          "degenerate": False, "spans": [span], "gated_by": None}
    return span, wp


def _patch(monkeypatch, n_chunks):
    monkeypatch.setattr(bd, "load_text_chunks",
                        lambda trad, tid: [bd.Chunk(f"x.t.{i:03d}", None, 300,
                                                    f"p{i}") for i in range(1, n_chunks + 1)])
    monkeypatch.setattr(gd, "_chunk_bodies", lambda ids: "body text " * 50)
    monkeypatch.setattr(gd, "_v_prose", _fake_v_prose)


def _in_band(words, budget):
    return budget * 0.5 <= words <= budget * 2


# ── grouping math ─────────────────────────────────────────────────────────────

def test_grouping_math_20_leaves_two_levels(db, monkeypatch):
    """20 leaves -> 4 clusters of 5 -> 1 final. Two merge LEVELS, and every
    single call sees at most BRANCH_FACTOR inputs."""
    n_leaves = 20
    span, wp = _setup(n_chunks=n_leaves)
    _patch(monkeypatch, n_leaves)

    sub_ok = "Sub summary prose about the section. " * 12   # ~84 words
    # Cluster budget = min(300, max(80, target*len(cluster))); with ~5 subs of
    # ~84 words the intermediate must land in its own band — use a mid-band
    # ~250-word response.
    cluster_ok = "Cluster intermediate merge prose. " * 48   # ~288 words
    final_ok = "Final merged summary. " * 100               # ~300 words, mid-band

    # 20 leaves, then level 1: 4 clusters, then final: 1 call.
    responses = ([sub_ok] * n_leaves
                 + [cluster_ok] * -(-n_leaves // BF)   # ceil(20/5) = 4
                 + [final_ok])
    gen = FakeGen(responses, db)
    assert gen._fold_l1(wp, span, f"sum:{span['text_id']}:{span['slug']}") is True

    # Call count check: leaves + 4 intermediates + 1 final.
    assert gen.calls == n_leaves + 4 + 1

    # Every compress call must carry at most BRANCH_FACTOR "Part"-blocks or
    # at most BRANCH_FACTOR cluster outputs — no call ever saw 20 parts.
    compress_calls = [p for p in gen.prompts[n_leaves:]]
    assert len(compress_calls) == 5
    for p in compress_calls[:-1]:
        # intermediate calls reference at most 5 distinct part/cluster blocks
        assert p.count("Sub summary") <= BF or p.count("Cluster intermediate") <= BF
    # The final call carries only the 4 cluster outputs, not the raw leaves:
    # count cluster SENTENCES, not substring occurrences (each canned cluster
    # body repeats the phrase 48 times).
    n_cluster_sentences = sum(
        1 for i in range(len(gen.prompts[-1]))
        if gen.prompts[-1].startswith("Cluster intermediate merge prose", i)
    )
    assert n_cluster_sentences / 48 == 4
    assert "Part 7:" not in gen.prompts[-1]

    row = db.execute("SELECT prompt_version FROM staged_summaries").fetchone()
    assert row["prompt_version"] == "l1-v3-folded"   # provenance stable


def test_cluster_merge_failure_aborts_span(db, monkeypatch):
    """Any intermediate merge exhausting its attempts aborts the whole fold;
    nothing staged — give-up semantics unchanged from the flat path."""
    n_leaves = 20
    span, wp = _setup(n_chunks=n_leaves)
    _patch(monkeypatch, n_leaves)

    sub_ok = "Sub summary prose about the section. " * 12
    over = "word " * 2000   # never in any band
    # 20 leaves ok; first INTERMEDIATE merge fails generate->compress.
    responses = ([sub_ok] * n_leaves + [over, over])
    gen = FakeGen(responses, db)
    assert gen._fold_l1(wp, span, f"sum:{span['text_id']}:{span['slug']}") is False
    assert db.execute("SELECT COUNT(*) FROM staged_summaries").fetchone()[0] == 0


def test_provenance_stable_across_depths(db, monkeypatch):
    """25 leaves -> 5 clusters -> final: still one 'l1-v3-folded' flag."""
    n_leaves = 25
    span, wp = _setup(n_chunks=n_leaves)
    _patch(monkeypatch, n_leaves)

    sub_ok = "Sub summary prose about the section. " * 12
    cluster_ok = "Cluster intermediate merge prose. " * 48
    final_ok = "Final merged summary. " * 100
    responses = ([sub_ok] * n_leaves
                 + [cluster_ok] * -(-n_leaves // BF)   # 5
                 + [final_ok])
    gen = FakeGen(responses, db)
    sid = f"sum:{span['text_id']}:{span['slug']}"
    assert gen._fold_l1(wp, span, sid) is True
    assert gen.inserted == [(sid, "l1-v3-folded")]
    # depth math: 25 -> 5 -> 1 is two levels, same as 20 leaves
    assert gen.calls == n_leaves + 5 + 1


def test_shallow_fold_unchanged_when_leaves_within_branch_factor(db, monkeypatch):
    """<=BF leaves: zero intermediate levels — exactly the old flat shape
    (4 subs + 1 merge), proving the tree only triggers past the factor."""
    span, wp = _setup(n_chunks=4, span_tokens=4800)
    _patch(monkeypatch, 4)
    sub_ok = "Sub summary prose about the section. " * 20
    final_ok = "Final merged summary. " * 40
    gen = FakeGen([sub_ok] * 4 + [final_ok], db)
    assert gen._fold_l1(wp, span, f"sum:{span['text_id']}:{span['slug']}") is True
    assert gen.calls == 5
