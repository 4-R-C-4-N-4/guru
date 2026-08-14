"""
derive_parallels.py — parallels as a derived table, no Pass C.

Ported from rellm tools/derived_parallels.py (docs/edges/derived-parallels-
proposal.md, todo:5620391a / parent c3f479ff — "retire Pass C: parallels
become a derived table"). Replaces LLM pair-classification with EXPRESSES
(every edge of that type, any tier — see note below) x thin-student
(concept, chunk) scores: a chunk's partners are the top cross-tradition
co-expressors of its concepts, ranked by the PARTNER's own concept score
(not min-leg — min-leg clamping made panels monochrome, per the proposal's
"known prototype flaws" note) and round-robinned across via concepts so a
panel doesn't monoculture on one via concept or one work.

EXPRESSES input, precisely (PR #64 review finding 7): load_expresses()
below reads every EXPRESSES edge in guru.db regardless of `tier` — it is
NOT restricted to human-reviewed rows. As of this port, ~29% of that
supply (11,057 of 38,457 EXPRESSES rows) is `tier='proposed'`, written by
scripts/auto_promote.py's auto-promotion without per-row human review
(that script was deleted 2026-08-14, todo:68028d8f; the rows remain)
before that tool was retired 2026-05-26; the remainder is `tier='verified'`
via node 11's review queue. Whether this generator should filter to
`tier='verified'` is a live, deliberately unresolved question tracked at
todo:dd034dc4 (the tier-semantics decision — is tier a confidence
signal or a provenance timestamp?): if that ticket lands on "confidence
signal," `load_expresses()`'s query needs `AND tier='verified'` added and
this note updated; if it lands on "provenance only," this note should say
so plainly instead of hedging. This script does not add a tier filter today.

Emits corpus-export edges shape (source, target, edge_type, tier, weight,
annotation) — the same dict shape as scripts/export.py's load_edges() rows
— as a JSONL file plus a summary.json. This script does NOT write guru.db:
materializing a `derived_parallels` table is a separate future step (see
the proposal's migration sketch); this ticket only ports the generator.

Scoring reuses guru.rerank.score_pairs (CPU-only cross-encoder scoring,
already used for EDGE_RERANK at query time) rather than re-implementing
model loading — it already handles the BERT 512-position cap and the
2400-char body truncation. Scores are cached incrementally, keyed by
(concept, chunk) and a content hash, in config[scoring].score_cache — both
within a run (flushed every SCORE_CACHE_FLUSH_EVERY concepts scored, so an
interrupted cold run doesn't lose everything) and, of course, across runs.

Usage:
    python3 scripts/derive_parallels.py [--config config/derived_parallels.toml]
        [--db data/guru.db] [--out data/derived_parallels/<timestamp>]
        [--limit-concepts N] [--verbose]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import tomllib

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_DB = PROJECT_ROOT / "data" / "guru.db"
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "derived_parallels.toml"
TAXONOMY_TOML = PROJECT_ROOT / "concepts" / "taxonomy.toml"

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).parent))
from guru.corpus import resolve_chunk_path  # noqa: E402
from works import load_works, work_of  # noqa: E402

# guru.rerank truncates bodies to this many characters before tokenizing
# (guru/rerank.py score_pairs). Mirrored here only for cache-key hashing —
# hashing past this point would invalidate the cache on edits that can't
# possibly change the score. Keep in sync with guru/rerank.py.
BODY_CHAR_CAP = 2400


# ── config ────────────────────────────────────────────────────────────────

def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


# ── taxonomy ─────────────────────────────────────────────────────────────

def load_taxonomy(path: Path = TAXONOMY_TOML) -> dict[str, str]:
    """Return {node_id ("concept.<cid>"): definition} for every concept.

    Walks the three-tier ``[concepts.DOMAIN.FAMILY]`` tree to any depth and
    collects leaf-string definitions (mirrors scripts/tag_concepts.py's
    load_taxonomy). The concept.<id> prefix is applied here — taxonomy.toml
    keys are bare, but EXPRESSES edges (and every other concept node) use
    the namespaced id, so every value this function returns is already in
    graph-id form and callers never have to think about the split again.
    """
    with open(path, "rb") as f:
        data = tomllib.load(f)
    defs: dict[str, str] = {}

    def collect(node: dict) -> None:
        for k, v in node.items():
            if isinstance(v, dict):
                collect(v)
            elif isinstance(v, str):
                defs[f"concept.{k}"] = v

    collect(data.get("concepts", {}))
    return defs


def first_sentence(text: str) -> str:
    """Text up to (not including) the first period. No trailing period."""
    return text.split(".", 1)[0].strip()


def format_label(node_id: str) -> str:
    """"concept.emanation_hierarchy" -> "Emanation Hierarchy".

    Matches the label convention scripts/sync_taxonomy.py writes into
    nodes.label (cid.replace("_", " ").title()) so annotation text reads
    the same as the rest of the graph.
    """
    bare = node_id.split(".", 1)[1]
    return bare.replace("_", " ").title()


# ── DB reads ─────────────────────────────────────────────────────────────

def open_db_readonly(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def load_chunk_traditions(conn: sqlite3.Connection) -> dict[str, str]:
    return dict(conn.execute("SELECT id, tradition_id FROM nodes WHERE type='chunk'"))


def load_apparatus_chunks(conn: sqlite3.Connection) -> set[str]:
    """chunk ids flagged as whole-chunk apparatus (todo:495577b7).

    Gated on status='apparatus' only — the owner-applied terminal state
    written by the guru-review web app's reclassify->apparatus_drop apply
    path, or scripts/flag_apparatus.py's queued rows once the owner applies
    them. status='pending' rows are NOT a fact yet (queue-only; the owner
    applies), so they must never gate the generator — mirrors the same
    pending-vs-applied distinction docs/web-review/cleanups.md draws for
    scripts/apply_cleanups.py.
    """
    return {r[0] for r in conn.execute(
        "SELECT chunk_id FROM staged_cleanups WHERE status = 'apparatus'"
    )}


def exclude_apparatus_chunks(
    bycon: dict[str, set[str]], bychunk: dict[str, set[str]], apparatus: set[str],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Drop apparatus-flagged chunks from both EXPRESSES indexes so they can
    never anchor a panel or be picked as anyone else's partner. Tag review
    already keeps apparatus chunks tag-empty in the common case (nothing to
    drop), but this makes it a chunk-level fact the generator itself
    enforces rather than an emergent property of the tag queue."""
    if not apparatus:
        return bycon, bychunk
    bycon = {c: (chs - apparatus) for c, chs in bycon.items()}
    bycon = {c: chs for c, chs in bycon.items() if chs}
    bychunk = {ch: cs for ch, cs in bychunk.items() if ch not in apparatus}
    return bycon, bychunk


def load_expresses(
    conn: sqlite3.Connection, concept_ids: set[str]
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """EXPRESSES edges restricted to concepts the taxonomy actually defines.

    Returns (bycon: concept -> {chunk}, bychunk: chunk -> {concept}).
    """
    bycon: dict[str, set[str]] = {}
    bychunk: dict[str, set[str]] = {}
    for source_id, target_id in conn.execute(
        "SELECT source_id, target_id FROM edges WHERE type='EXPRESSES'"
    ):
        if target_id not in concept_ids:
            continue
        bycon.setdefault(target_id, set()).add(source_id)
        bychunk.setdefault(source_id, set()).add(target_id)
    return bycon, bychunk


def chunk_text_id(chunk_id: str) -> str:
    """"<tradition>.<text_id>.<seq>" -> "<text_id>" (matches resolve_chunk_path)."""
    parts = chunk_id.split(".", 2)
    return parts[1] if len(parts) >= 2 else chunk_id


def build_work_map() -> dict[str, str]:
    """chunk text_id -> work_id, over the corpus's declared works.

    Falls back to an empty map (per-work cap becomes a no-op, not a crash)
    if sources/works.toml or corpus/ can't be loaded — a generator script
    should degrade, not block, on a layer it doesn't own.
    """
    try:
        return work_of(load_works())
    except (OSError, ValueError, KeyError) as e:
        logger.warning("could not load works map, per-work cap disabled: %s", e)
        return {}


def load_chunk_body(chunk_id: str) -> str | None:
    p = resolve_chunk_path(chunk_id)
    if p is None:
        return None
    with open(p, "rb") as f:
        d = tomllib.load(f)
    return d["content"]["body"]


# ── score cache ──────────────────────────────────────────────────────────

def content_hash(definition: str, body: str) -> str:
    h = hashlib.sha256()
    h.update(definition.encode("utf-8"))
    h.update(b"\x00")
    h.update(body[:BODY_CHAR_CAP].encode("utf-8"))
    return h.hexdigest()[:16]


def load_score_cache(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("score cache unreadable, starting fresh: %s", e)
        return {}


def save_score_cache(path: Path, cache: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(cache, f, indent=0, sort_keys=True)
    tmp.replace(path)


def cache_key(concept: str, chunk: str) -> str:
    # JSON object keys must be strings; "|" cannot appear in either id (both
    # are dot-delimited).
    return f"{concept}|{chunk}"


# Flush the score cache to disk every this many *concepts* scored inside the
# model loop (PR #64 review finding 3) — save_score_cache() already writes
# via tmp-file + os.replace(), so a mid-run flush is atomic and safe to
# interleave with the next model call. Without this, save_score_cache() only
# ran once, after score_needed_pairs() returned, so an interrupted cold
# corpus-wide run (Ctrl-C, OOM, one malformed body raising inside
# rerank.score_pairs) dropped every score computed so far, contradicting the
# module header's "cached incrementally" contract. Sized for the actual
# taxonomy (~116 concepts): 5 keeps the worst-case loss to a handful of
# concepts (~4% of a cold corpus-wide run) and the write is a small JSON,
# so flushing often costs nothing. The progress print in the loop uses this
# same constant so tuning it never desyncs the two cadences.
SCORE_CACHE_FLUSH_EVERY = 5


# ── scoring ──────────────────────────────────────────────────────────────

def score_needed_pairs(
    need: list[tuple[str, str]],
    defs: dict[str, str],
    bodies: dict[str, str],
    cache: dict[str, dict],
    model_path: str,
    cache_path: Path | None = None,
) -> dict[tuple[str, str], float]:
    """Resolve every (concept, chunk) pair's score, cache-first.

    Only pairs whose cache entry is missing or stale (content hash changed)
    are actually sent to the model. Reuses guru.rerank.score_pairs, grouped
    by concept (one query per call), so it inherits that module's 512-
    position cap and CPU-only enforcement instead of re-implementing them.

    If `cache_path` is given, the cache is flushed to disk every
    SCORE_CACHE_FLUSH_EVERY concepts scored (see that constant) — not just
    once at the very end — so a run that dies partway through a long cold
    pass still has its work saved. `run()` also does a final save after this
    returns, which covers the tail end that doesn't land on a flush boundary.
    """
    score: dict[tuple[str, str], float] = {}
    todo: dict[str, list[str]] = {}  # concept -> [chunk, ...] needing a model call

    for concept, chunk in need:
        if chunk not in bodies:
            continue
        h = content_hash(defs[concept], bodies[chunk])
        entry = cache.get(cache_key(concept, chunk))
        if entry is not None and entry.get("hash") == h:
            score[(concept, chunk)] = entry["score"]
        else:
            todo.setdefault(concept, []).append(chunk)

    n_todo = sum(len(v) for v in todo.values())
    print(f"(concept, chunk) pairs to score: {len(need)} "
          f"({len(need) - n_todo} cached, {n_todo} to run)")

    if todo:
        os.environ["EDGE_RERANK_MODEL"] = model_path
        from guru import rerank

        for i, (concept, chunks) in enumerate(sorted(todo.items())):
            bodies_for_concept = {ch: bodies[ch] for ch in chunks}
            logits = rerank.score_pairs(defs[concept], bodies_for_concept)
            h_by_chunk = {ch: content_hash(defs[concept], bodies[ch]) for ch in chunks}
            for ch, s in logits.items():
                score[(concept, ch)] = s
                cache[cache_key(concept, ch)] = {"score": s, "hash": h_by_chunk[ch]}
            if i % SCORE_CACHE_FLUSH_EVERY == 0:
                print(f"  scored {i + 1}/{len(todo)} concepts", flush=True)
            if cache_path is not None and (i + 1) % SCORE_CACHE_FLUSH_EVERY == 0:
                save_score_cache(cache_path, cache)

    return score


# ── ranking / round-robin / panel cap (pure — no model, unit-tested) ──────

def build_ranked(
    bycon: dict[str, set[str]], score: dict[tuple[str, str], float]
) -> dict[str, list[str]]:
    """concept -> chunks that express it, ranked by the chunk's OWN score on
    that concept (descending), tie-broken by chunk id for determinism.
    """
    return {
        c: sorted(chs, key=lambda ch: (-score.get((c, ch), -1e9), ch))
        for c, chs in bycon.items()
    }


def build_panels(
    bychunk: dict[str, set[str]],
    ranked: dict[str, list[str]],
    score: dict[tuple[str, str], float],
    trad_of: dict[str, str],
    work_of_chunk,
    min_grade: float,
    top_k: int,
    per_work_cap: int,
) -> dict[str, list[tuple[str, str, float]]]:
    """chunk -> [(partner, via_concept, grade), ...], weight-desc + stable
    tiebreak, per-work cap applied.

    Mirrors the rellm prototype's anchor-gate + via round-robin exactly
    (partner ranked by the partner's own concept score, not min-leg; picked
    across via concepts round-robin so a panel doesn't monoculture on one
    via). Two additions per todo:5620391a: the per-work cap, and explicit
    sort-key tiebreaks everywhere the prototype relied on dict/set iteration
    order (which is not stable across runs under hash randomization).
    """
    panels: dict[str, list[tuple[str, str, float]]] = {}

    for ch in sorted(bychunk):
        concepts = bychunk[ch]
        # Anchor gate: the chunk must itself clear the floor on a concept
        # for that concept to contribute partners.
        vias = sorted(c for c in concepts if score.get((c, ch), -1e9) >= min_grade)
        iters = {c: iter(ranked.get(c, [])) for c in vias}
        best: dict[str, tuple[str, float]] = {}
        picked_n = 0
        while iters and picked_n < top_k * 2:
            for c in sorted(iters):
                other = next(iters[c], None)
                if other is None:
                    del iters[c]
                    continue
                if other == ch or trad_of.get(other) == trad_of.get(ch):
                    continue
                b = score.get((c, other))
                if b is None or b < min_grade:
                    del iters[c]
                    continue
                if other not in best:
                    best[other] = (c, b)
                    picked_n += 1

        ordered = sorted(best.items(), key=lambda kv: (-kv[1][1], kv[0]))

        capped: list[tuple[str, str, float]] = []
        work_counts: dict[str, int] = {}
        for partner, (via, grade) in ordered:
            w = work_of_chunk(partner)
            if work_counts.get(w, 0) >= per_work_cap:
                continue
            work_counts[w] = work_counts.get(w, 0) + 1
            capped.append((partner, via, grade))

        panels[ch] = capped

    return panels


def build_edges(
    panels: dict[str, list[tuple[str, str, float]]], defs: dict[str, str]
) -> list[dict]:
    """Panels -> corpus-export edges shape, one row per unique unordered
    pair (a chunk pair can appear in both endpoints' panels; the first
    encountered in sorted-chunk-id order wins, deterministically).

    Final order: weight desc, (source, target) asc as the stable tiebreak.
    """
    seen: set[tuple[str, str]] = set()
    rows: list[dict] = []
    for ch in sorted(panels):
        for partner, via, grade in panels[ch]:
            a, b = (ch, partner) if ch < partner else (partner, ch)
            key = (a, b)
            if key in seen:
                continue
            seen.add(key)
            annotation = (f"Shared concept: {format_label(via)} — "
                          f"{first_sentence(defs[via])}. (derived)")
            rows.append({
                "source": a,
                "target": b,
                "edge_type": "PARALLELS",
                "tier": "inferred",
                "weight": round(grade, 3),
                "annotation": annotation,
            })
    rows.sort(key=lambda r: (-r["weight"], r["source"], r["target"]))
    return rows


# ── main ──────────────────────────────────────────────────────────────────

def run(db_path: Path, config_path: Path, out_dir: Path,
        limit_concepts: int | None = None) -> None:
    cfg = load_config(config_path)
    scoring_cfg = cfg["scoring"]
    panels_cfg = cfg["panels"]
    top_k = int(scoring_cfg["top_k"])
    min_grade = float(scoring_cfg["min_grade"])
    per_work_cap = int(panels_cfg["per_work_cap"])
    model_path = str(scoring_cfg["model_path"])
    cache_path = Path(scoring_cfg["score_cache"])
    if not cache_path.is_absolute():
        cache_path = PROJECT_ROOT / cache_path

    defs = load_taxonomy()
    if limit_concepts:
        # Deterministic subset for smoke runs: first N concept ids, sorted.
        keep = set(sorted(defs)[:limit_concepts])
        defs = {k: v for k, v in defs.items() if k in keep}
        print(f"--limit-concepts {limit_concepts}: restricted to {len(defs)} concepts")

    conn = open_db_readonly(db_path)
    trad_of = load_chunk_traditions(conn)
    bycon, bychunk = load_expresses(conn, set(defs))
    apparatus = load_apparatus_chunks(conn)
    conn.close()
    if apparatus:
        before = len(bychunk)
        bycon, bychunk = exclude_apparatus_chunks(bycon, bychunk, apparatus)
        print(f"apparatus-flagged chunks excluded: {before - len(bychunk)} "
              f"(of {len(apparatus)} flagged; the rest had no EXPRESSES edges anyway)")

    work_map = build_work_map()

    def work_of_chunk(chunk_id: str) -> str:
        t = chunk_text_id(chunk_id)
        return work_map.get(t, t)

    need = sorted({(c, ch) for c, chs in bycon.items() for ch in chs})
    bodies: dict[str, str] = {}
    for _, ch in need:
        if ch not in bodies:
            body = load_chunk_body(ch)
            if body is not None:
                bodies[ch] = body

    cache = load_score_cache(cache_path)
    t0 = time.monotonic()
    score = score_needed_pairs(need, defs, bodies, cache, model_path, cache_path)
    save_score_cache(cache_path, cache)  # final flush covers the tail end
    elapsed = time.monotonic() - t0

    ranked = build_ranked(bycon, score)
    panels = build_panels(bychunk, ranked, score, trad_of, work_of_chunk,
                          min_grade, top_k, per_work_cap)
    rows = build_edges(panels, defs)

    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "edges_derived.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    chunks_with_partners = sum(1 for p in panels.values() if p)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db": str(db_path),
        "config": str(config_path),
        "concepts": len(defs),
        "pairs_needed": len(need),
        "pairs_resolved": len(score),
        "scoring_seconds": round(elapsed, 1),
        "chunks_total": len(bychunk),
        "chunks_with_partners": chunks_with_partners,
        "unique_edge_rows": len(rows),
        "top_k": top_k,
        "min_grade": min_grade,
        "per_work_cap": per_work_cap,
        "model_path": model_path,
    }
    with open(out_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print(f"wrote {out_dir}: {len(rows)} unique PARALLELS rows, "
          f"{chunks_with_partners}/{len(bychunk)} chunks have partners "
          f"({elapsed:.1f}s scoring)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--out", default=None,
                        help="output dir (default: data/derived_parallels/<UTC timestamp>)")
    parser.add_argument("--limit-concepts", type=int, default=None,
                        help="restrict to the first N concept ids (sorted) — "
                             "for bounded smoke runs, not a production knob")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stderr,
    )

    out_dir = Path(args.out) if args.out else (
        PROJECT_ROOT / "data" / "derived_parallels"
        / datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    )

    run(db_path=Path(args.db), config_path=Path(args.config), out_dir=out_dir,
        limit_concepts=args.limit_concepts)


if __name__ == "__main__":
    main()
