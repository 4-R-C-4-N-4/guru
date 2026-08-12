"""
guru/retrieval_legs.py — retrieval components brought to guru-web parity.

`guru/retriever.py` was the pilot for guru-web and then stopped being touched,
so the two drifted badly enough that the sqlite path could not be used as an
honest stand-in for production. This module carries the pieces that were
missing. Not bit-exact with Postgres by intent — exact reproduction is what
`scripts/export.py` plus a docker staging DB is for. The goal is a baseline
that does not systematically flatter or starve any one leg.

What was missing, and now is not:

  three-tier concept resolution
      guru-web resolves a query against concept labels + concept_aliases
      (weight 1.0), family labels + family_aliases expanding to every concept
      in the family (0.5), and domain rows expanding to every concept beneath
      them (0.25). The pilot substring-matched concept ids only, so a query
      like "cosmology" or "soteriology" — both *family* names — resolved to
      nothing at all.

  the lexical leg
      Postgres uses to_tsvector/ts_rank with OR semantics; sqlite has no
      equivalent, so this builds an FTS5 sidecar index over the corpus bodies
      and ranks with bm25. Different ranking function, same job: it is what
      rescues small, commentary-heavy traditions that embed poorly (the
      Gathas being the documented case). Max-normalised like guru-web's.

  the summary leg
      831 summary_nodes carry their own embeddings and enter at tier weight
      0.4.

  quality filtering
      Drops pure nav/TOC/errata chunks and strips boilerplate. Env-gated
      (RETRIEVAL_QUALITY_FILTER) exactly as in guru-web, not on by default.

  rarity-weighted diversity
      Corpus-wide tradition rarity, log-scaled so an 841-vs-15 chunk spread
      does not blow up, rather than the pilot's "first appearance of a
      tradition" bump.

Known divergence, deliberate: bm25 is not ts_rank, so lexical *ordering*
differs even at parity. And guru-web's HOP_DEPTH=1 concept↔concept expansion
is a no-op on this corpus — there are zero concept↔concept edges — so it is
implemented and simply finds nothing, in both systems.
"""
from __future__ import annotations

import os
import re
import sqlite3
from math import log
from pathlib import Path

import numpy as np
import tomllib

from guru.corpus import resolve_chunk_path
from guru.paths import DATA_DIR

# guru-web MATCH_TIER_WEIGHTS (graph.ts): a directly matched concept counts
# full, a family-expanded concept half, a domain-expanded concept a quarter.
MATCH_TIER_WEIGHTS = {"concept": 1.0, "family": 0.5, "domain": 0.25}
MATCH_TIER_RANK = {"concept": 3, "family": 2, "domain": 1}

# Function words that must never match a label on their own. "Theology"
# substring-matching into nearly every query is the failure this prevents
# (guru-web todo:597d86a4).
STOPWORDS = {
    "the", "and", "of", "in", "to", "a", "an", "is", "it", "its", "for",
    "on", "with", "as", "at", "by", "from", "or", "that", "this", "was",
    "what", "how", "why", "who", "does", "do", "are", "be", "been",
}

APPARATUS_DROP = re.compile(r"^\s*(?:next|previous)\s*:|^\s*errata\b", re.I)
NAV_PREFIX = re.compile(
    r"^\s*(?:[Ss]acred[- ][Tt]exts?\b[^\n]{0,300}\bPrevious\s+Next\b[ \t]*"
    r"|Sacred-[Tt]exts?\b[^\n]{0,300}(?:\n+|$)"
    r"|Sacred\s+Texts\b[^\n]{0,300}(?:\n+|$)"
    r"|Index\s+Previous\s+Next\b[ \t]*)")
NAV_TAIL = re.compile(r"\s*(?:Next:|Previous:)[^\n]*$")
PAGE_MARKER = re.compile(r"\[\s*p\.?\s*\d+\s*\]", re.I)

FTS_DB = DATA_DIR / "lexical-fts.db"


# ── concept resolution ───────────────────────────────────────────────────────

def resolve_concepts(conn: sqlite3.Connection, query: str) -> dict[str, float]:
    """{concept_node_id: match_weight} across guru-web's three match tiers.

    A concept reached by several tiers keeps the strongest.
    """
    q = f" {query.lower()} "

    def hit(label: str | None) -> bool:
        if not label:
            return False
        lab = label.strip().lower()
        if not lab or lab in STOPWORDS or len(lab) < 3:
            return False
        return lab in q or lab.replace("_", " ") in q

    def rows(sql: str, params: list | None = None) -> list:
        """Optional-table tolerant. The concept hierarchy arrives with
        v3_006; a database without it still resolves concept labels rather
        than raising."""
        try:
            return conn.execute(sql, params or []).fetchall()
        except sqlite3.Error:
            return []

    best: dict[str, tuple[int, float]] = {}

    def offer(cid: str, tier: str) -> None:
        rank, w = MATCH_TIER_RANK[tier], MATCH_TIER_WEIGHTS[tier]
        if cid not in best or rank > best[cid][0]:
            best[cid] = (rank, w)

    # 1. concept — node label, id, and concept_aliases
    for cid, label in rows("SELECT id, label FROM nodes WHERE type='concept'"):
        if hit(label) or hit(cid.removeprefix("concept.")):
            offer(cid, "concept")
    for cid, alias in rows("SELECT concept_id, alias FROM concept_aliases"):
        if hit(alias):
            offer(cid if cid.startswith("concept.") else f"concept.{cid}", "concept")

    # 2. family — label or family alias expands to every member concept
    fam_rows = rows("SELECT id, label, parent_id FROM concept_families")
    alias_by_fam: dict[str, list[str]] = {}
    for fid, alias in rows("SELECT family_id, alias FROM family_aliases"):
        alias_by_fam.setdefault(fid, []).append(alias)

    matched_fams, matched_domains = set(), set()
    for fid, label, parent in fam_rows:
        names = [label, fid] + alias_by_fam.get(fid, [])
        if any(hit(n) for n in names):
            (matched_domains if parent is None else matched_fams).add(fid)

    def members(family_ids: set[str], tier: str) -> None:
        if not family_ids:
            return
        ph = ",".join("?" for _ in family_ids)
        for (cid,) in rows(f"SELECT concept_id FROM concept_family_membership "
                          f"WHERE family_id IN ({ph})", list(family_ids)):
            offer(cid if cid.startswith("concept.") else f"concept.{cid}", tier)

    members(matched_fams, "family")

    # 3. domain — every concept whose family's parent is the matched domain
    if matched_domains:
        ph = ",".join("?" for _ in matched_domains)
        child = {r[0] for r in rows(
            f"SELECT id FROM concept_families WHERE parent_id IN ({ph})",
            list(matched_domains))}
        members(child, "domain")

    return {cid: w for cid, (_, w) in best.items()}


def expand_concepts(conn: sqlite3.Connection, concepts: dict[str, float],
                    hops: int = 1) -> dict[str, float]:
    """guru-web HOP_DEPTH: concept↔concept PARALLELS/DERIVES_FROM reachability.

    A no-op on this corpus — there are no concept↔concept edges — but kept so
    the leg matches production if any are ever created.
    """
    out = dict(concepts)
    frontier = set(concepts)
    for _ in range(hops):
        if not frontier:
            break
        ph = ",".join("?" for _ in frontier)
        params = list(frontier) * 2
        nxt: set[str] = set()
        try:
            hops_rows = conn.execute(
                f"SELECT e.source_id, e.target_id FROM edges e "
                f"JOIN nodes s ON s.id=e.source_id JOIN nodes t ON t.id=e.target_id "
                f"WHERE s.type='concept' AND t.type='concept' "
                f"AND e.type IN ('PARALLELS','DERIVES_FROM') "
                f"AND (e.source_id IN ({ph}) OR e.target_id IN ({ph}))", params).fetchall()
        except sqlite3.Error:
            hops_rows = []
        for src, tgt in hops_rows:
            for a, b in ((src, tgt), (tgt, src)):
                if a in out and b not in out:
                    out[b] = out[a]
                    nxt.add(b)
        frontier = nxt
    return out


# ── lexical leg ──────────────────────────────────────────────────────────────

def _corpus_mtime(conn: sqlite3.Connection) -> float:
    newest = 0.0
    for (cid,) in conn.execute("SELECT id FROM nodes WHERE type='chunk' LIMIT 400"):
        p = resolve_chunk_path(cid)
        if p:
            newest = max(newest, p.stat().st_mtime)
    return newest


def ensure_fts(conn: sqlite3.Connection, path: Path = FTS_DB) -> Path | None:
    """Build (or refresh) the FTS5 sidecar over corpus bodies.

    A sidecar rather than a table in guru.db deliberately: this is a derived
    index, rebuildable at any time, and it keeps the schema out of migrations.
    """
    stamp = _corpus_mtime(conn)
    if path.exists():
        fts = sqlite3.connect(str(path))
        try:
            got = fts.execute("SELECT v FROM meta WHERE k='corpus_mtime'").fetchone()
            if got and abs(float(got[0]) - stamp) < 1.0:
                fts.close()
                return path
        except sqlite3.Error:
            pass
        fts.close()
        path.unlink(missing_ok=True)

    rows = []
    for (cid,) in conn.execute("SELECT id FROM nodes WHERE type='chunk'"):
        p = resolve_chunk_path(cid)
        if p is None:
            continue
        try:
            with open(p, "rb") as f:
                rows.append((cid, tomllib.load(f)["content"]["body"]))
        except (KeyError, tomllib.TOMLDecodeError):
            continue
    if not rows:
        return None

    fts = sqlite3.connect(str(path))
    fts.executescript(
        "CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id UNINDEXED, body);"
        "CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);")
    fts.executemany("INSERT INTO chunks_fts(chunk_id, body) VALUES(?,?)", rows)
    fts.execute("INSERT INTO meta(k,v) VALUES('corpus_mtime',?)", (str(stamp),))
    fts.commit()
    fts.close()
    return path


def lexical_search(conn: sqlite3.Connection, query: str, limit: int) -> dict[str, float]:
    """{chunk_id: bm25-derived score}. OR semantics, mirroring guru-web's
    deliberate flip of plainto_tsquery's AND to OR so a multi-term query is
    not all-or-nothing."""
    path = ensure_fts(conn)
    if path is None:
        return {}
    terms = [re.sub(r"\W+", "", t) for t in query.lower().split()]
    terms = [t for t in terms if len(t) > 2 and t not in STOPWORDS]
    if not terms:
        return {}
    fts = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = fts.execute(
            "SELECT chunk_id, bm25(chunks_fts) FROM chunks_fts "
            "WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT ?",
            (" OR ".join(terms), limit)).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        fts.close()
    # bm25() is negative-better in sqlite; flip so larger is better.
    return {cid: -score for cid, score in rows}


# ── summary leg ──────────────────────────────────────────────────────────────

def summary_search(conn: sqlite3.Connection, qvec: np.ndarray,
                   limit: int) -> list[dict]:
    rows = conn.execute(
        "SELECT se.summary_id, se.vector, sn.tradition, sn.body "
        "FROM summary_embeddings se JOIN summary_nodes sn ON sn.id = se.summary_id"
    ).fetchall()
    if not rows:
        return []
    M = np.stack([np.frombuffer(r[1], dtype=np.float32) for r in rows])
    M = M / np.linalg.norm(M, axis=1, keepdims=True)
    sims = M @ (qvec / np.linalg.norm(qvec))
    order = np.argsort(-sims)[:limit]
    return [{"chunk_id": rows[i][0], "similarity": float(sims[i]),
             "tradition": rows[i][2], "tier": "summary",
             "body": rows[i][3], "metadata": {}} for i in order]


# ── quality filter ───────────────────────────────────────────────────────────

def clean_body(body: str) -> str:
    body = NAV_PREFIX.sub("", body)
    body = PAGE_MARKER.sub(" ", body)
    body = NAV_TAIL.sub("", body)
    return re.sub(r"[ \t]{2,}", " ", body).strip()


def quality_ok(body: str) -> tuple[bool, str]:
    """(keep?, cleaned body). Mirrors guru-web applyQualityFilter."""
    if APPARATUS_DROP.search(body or ""):
        return False, body
    cleaned = clean_body(body or "")
    if len(re.sub(r"\W", "", cleaned)) < 3:
        return False, cleaned
    return True, cleaned


def quality_filter_enabled() -> bool:
    return bool(os.environ.get("RETRIEVAL_QUALITY_FILTER"))


# ── diversity ────────────────────────────────────────────────────────────────

def corpus_rarity(conn: sqlite3.Connection) -> dict[str, float]:
    """Corpus-wide tradition rarity in [0,1], rarest = 1, log-scaled."""
    rows = conn.execute(
        "SELECT tradition_id, COUNT(*) FROM nodes WHERE type='chunk' "
        "AND tradition_id IS NOT NULL GROUP BY tradition_id").fetchall()
    if not rows:
        return {}
    logs = {t: log(max(n, 1)) for t, n in rows}
    hi, lo = max(logs.values()), min(logs.values())
    span = (hi - lo) or 1.0
    return {t: (hi - v) / span for t, v in logs.items()}


# ── the edge leg, opt-in ─────────────────────────────────────────────────────

def edge_partners(conn: sqlite3.Connection, anchors: set[str]) -> list[dict]:
    """Cross-tradition partners one chunk↔chunk PARALLELS/CONTRASTS hop out.

    OFF unless EDGE_LEG=on. guru-web has never had this leg — its graph walk
    is concept↔concept — so the pilot traversing it was the single largest
    behavioural difference between the two systems, and left the sqlite path
    unusable as a baseline for measuring whether the edge graph earns its
    place. Making it an explicit toggle is what lets that be A/B'd.
    """
    if not anchors or os.environ.get("EDGE_LEG") != "on":
        return []
    out: dict[str, dict] = {}
    ids = list(anchors)
    for i in range(0, len(ids), 400):
        batch = ids[i:i + 400]
        ph = ",".join("?" for _ in batch)
        for src, tgt, tier, s_tr, t_tr in conn.execute(
                f"SELECT e.source_id, e.target_id, e.tier, "
                f"       ns.tradition_id, nt.tradition_id "
                f"FROM edges e "
                f"JOIN nodes ns ON ns.id = e.source_id "
                f"JOIN nodes nt ON nt.id = e.target_id "
                f"WHERE e.type IN ('PARALLELS','CONTRASTS') "
                f"AND (e.source_id IN ({ph}) OR e.target_id IN ({ph}))",
                batch + batch):
            for anchor, partner, trad, other in ((src, tgt, t_tr, s_tr),
                                                 (tgt, src, s_tr, t_tr)):
                if anchor in anchors and partner not in anchors and trad != other:
                    out.setdefault(partner, {
                        "chunk_id": partner, "similarity": 0.0, "tier": tier,
                        "tradition": trad or "", "metadata": {}})
    return list(out.values())
