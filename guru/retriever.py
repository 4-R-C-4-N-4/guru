"""
guru/retriever.py — HybridRetriever combining vector search and concept graph walk.

Pipeline:
  1. Vector search with user-pref filters → candidate pool (top_k * 2)
  2. Concept extraction from query (keyword match against taxonomy)
  3. Graph walk: concepts → PARALLELS/CONTRASTS → EXPRESSES → chunks
  4. Merge + re-rank: diversity boost + edge-tier weight + similarity score
  5. Post-filter: apply is_chunk_allowed, cap per-tradition, return top_k
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import tomllib

from guru.paths import (
    CONFIG_MODEL as CONFIG_PATH,
    DEFAULT_DB,
    SCRIPTS_DIR,
    TAXONOMY_TOML,
)

sys.path.insert(0, str(SCRIPTS_DIR))
from vector_store import VectorStore  # noqa: E402

from guru.corpus import resolve_chunk_path
from guru.preferences import UserPreferences
from guru.prompt import RetrievedChunk


def _load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def _load_taxonomy_labels() -> dict[str, str]:
    """Return {concept_id: definition} for keyword matching."""
    with open(TAXONOMY_TOML, "rb") as f:
        data = tomllib.load(f)
    labels: dict[str, str] = {}
    for cat_concepts in data.get("concepts", {}).values():
        for cid, defn in cat_concepts.items():
            labels[cid] = defn
    return labels


TIER_WEIGHTS = {"verified": 1.0, "proposed": 0.7, "inferred": 0.4}


class HybridRetriever:
    def __init__(
        self,
        db_path: Path = DEFAULT_DB,
        config_path: Path = CONFIG_PATH,
        vector_store: VectorStore | None = None,
    ):
        cfg = _load_config(config_path)
        self._rcfg = cfg.get("retrieval", {})
        self._rkcfg = cfg.get("ranking", {})
        self._top_k = int(self._rcfg.get("top_k", 10))
        self._min_sim = float(self._rcfg.get("min_similarity", 0.50))
        self._max_per_trad = int(self._rcfg.get("max_per_tradition", 3))
        self._diversity_boost = float(self._rkcfg.get("diversity_boost", 0.1))
        self._tier_w = {
            "verified": float(self._rkcfg.get("tier_verified", 1.0)),
            "proposed": float(self._rkcfg.get("tier_proposed", 0.7)),
            "inferred": float(self._rkcfg.get("tier_inferred", 0.4)),
        }
        self._vs = vector_store or VectorStore()
        self._db_path = db_path
        self._taxonomy = _load_taxonomy_labels()

    # ── public ───────────────────────────────────────────────────────────────

    def retrieve(
        self,
        query: str,
        query_embedding: list[float],
        user_prefs: UserPreferences,
        top_k: int | None = None,
    ) -> list[RetrievedChunk]:
        k = top_k or self._top_k

        # 1. Vector search
        vector_hits = self._vector_search(query_embedding, user_prefs, k * 2)

        # 2. Graph walk from query concepts
        graph_chunks = self._graph_walk(query, user_prefs)

        # 3. Merge & score
        scored = self._merge_and_rank(vector_hits, graph_chunks, user_prefs, k)

        return scored[:k]

    # ── internal ─────────────────────────────────────────────────────────────

    def _vector_search(
        self, embedding: list[float], prefs: UserPreferences, n: int
    ) -> list[dict]:
        where = prefs.to_vector_filters()
        results = self._vs.query(
            embedding=embedding,
            top_n=n,
            where=where,
            min_similarity=self._min_sim,
        )
        return results

    def _graph_walk(self, query: str, prefs: UserPreferences) -> list[dict]:
        """
        Find concept IDs matching the query, then walk the graph to find chunks.
        Returns list of {chunk_id, tier, tradition} dicts.
        """
        query_lower = query.lower()
        matched_concept_ids = [
            f"concept.{cid}"
            for cid, defn in self._taxonomy.items()
            if cid.replace("_", " ") in query_lower
            or any(word in query_lower for word in cid.split("_") if len(word) > 4)
        ]

        if not matched_concept_ids:
            return []

        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        results: list[dict] = []

        try:
            for concept_id in matched_concept_ids[:5]:  # cap graph walk breadth
                # Direct EXPRESSES edges: chunks that express this concept
                rows = conn.execute(
                    """SELECT e.source_id as chunk_id, e.tier,
                              n.tradition_id as tradition, n.metadata_json
                       FROM edges e
                       JOIN nodes n ON n.id = e.source_id
                       WHERE e.target_id = ? AND e.type = 'EXPRESSES'""",
                    (concept_id,),
                ).fetchall()
                for row in rows:
                    trad = row["tradition"] or ""
                    if prefs.is_chunk_allowed(trad):
                        meta = json.loads(row["metadata_json"] or "{}")
                        results.append({
                            "chunk_id": row["chunk_id"],
                            "tier": row["tier"],
                            "tradition": trad,
                            "metadata": meta,
                            "similarity": 0.0,  # no vector score for graph hits
                        })

                # PARALLELS/CONTRASTS from this concept node's chunks to other traditions
                rows2 = conn.execute(
                    """SELECT se.source_id, se.target_id, se.tier,
                              ns.tradition_id as s_trad, nt.tradition_id as t_trad
                       FROM edges se
                       JOIN nodes ns ON ns.id = se.source_id
                       JOIN nodes nt ON nt.id = se.target_id
                       WHERE se.type IN ('PARALLELS','CONTRASTS')
                         AND (se.source_id IN (
                               SELECT source_id FROM edges
                               WHERE target_id=? AND type='EXPRESSES')
                              OR se.target_id IN (
                               SELECT source_id FROM edges
                               WHERE target_id=? AND type='EXPRESSES'))""",
                    (concept_id, concept_id),
                ).fetchall()
                for row in rows2:
                    for cid, trad in ((row["source_id"], row["s_trad"]),
                                      (row["target_id"], row["t_trad"])):
                        if prefs.is_chunk_allowed(trad or ""):
                            results.append({
                                "chunk_id": cid,
                                "tier": row["tier"],
                                "tradition": trad or "",
                                "metadata": {},
                                "similarity": 0.0,
                            })
        finally:
            conn.close()

        return results

    def _load_chunk_body(self, chunk_id: str) -> tuple[str, dict]:
        """Load body and chunk metadata from corpus TOML."""
        path = resolve_chunk_path(chunk_id)
        if path is None:
            return "", {}
        with open(path, "rb") as f:
            d = tomllib.load(f)
        return d["content"]["body"], d["chunk"]

    def _merge_and_rank(
        self,
        vector_hits: list[dict],
        graph_chunks: list[dict],
        prefs: UserPreferences,
        k: int,
    ) -> list[RetrievedChunk]:
        seen: dict[str, dict] = {}

        # Ingest vector hits
        for hit in vector_hits:
            cid = hit["chunk_id"]
            meta = hit.get("metadata", {})
            tradition = meta.get("tradition", cid.split(".")[0] if "." in cid else "")
            if not prefs.is_chunk_allowed(tradition, meta.get("text_id", "")):
                continue
            seen[cid] = {
                "chunk_id": cid,
                "similarity": hit.get("similarity", 0.0),
                "tier": "inferred",
                "tradition": tradition,
                "metadata": meta,
                "graph_score": 0.0,
            }

        # Merge graph hits — upgrade tier if better
        for hit in graph_chunks:
            cid = hit["chunk_id"]
            trad = hit.get("tradition", "")
            if not prefs.is_chunk_allowed(trad):
                continue
            if cid in seen:
                # Upgrade tier if graph provides a stronger signal
                existing_w = TIER_WEIGHTS.get(seen[cid]["tier"], 0.4)
                new_w = TIER_WEIGHTS.get(hit.get("tier", "inferred"), 0.4)
                if new_w > existing_w:
                    seen[cid]["tier"] = hit["tier"]
                seen[cid]["graph_score"] = max(seen[cid]["graph_score"], new_w)
            else:
                seen[cid] = {
                    "chunk_id": cid,
                    "similarity": 0.0,
                    "tier": hit.get("tier", "inferred"),
                    "tradition": trad,
                    "metadata": hit.get("metadata", {}),
                    "graph_score": TIER_WEIGHTS.get(hit.get("tier", "inferred"), 0.4),
                }

        # Score each candidate
        traditions_seen: set[str] = set()
        scored: list[tuple[float, dict]] = []

        for item in seen.values():
            sim = item["similarity"]
            tier_w = self._tier_w.get(item["tier"], 0.4)
            graph_s = item.get("graph_score", 0.0)
            diversity = self._diversity_boost if item["tradition"] not in traditions_seen else 0.0
            score = 0.7 * sim + 0.3 * max(tier_w, graph_s) + diversity
            traditions_seen.add(item["tradition"])
            scored.append((score, item))

        scored.sort(key=lambda x: -x[0])

        # Build RetrievedChunk objects, cap per tradition
        trad_counts: dict[str, int] = {}
        output: list[RetrievedChunk] = []

        for _, item in scored:
            if len(output) >= k:
                break
            trad = item["tradition"]
            if self._max_per_trad > 0:
                if trad_counts.get(trad, 0) >= self._max_per_trad:
                    continue

            cid = item["chunk_id"]
            body, chunk_meta = self._load_chunk_body(cid)
            meta = item["metadata"] or {}

            # Merge meta sources
            section = chunk_meta.get("section", meta.get("section", ""))
            text_name = chunk_meta.get("text_name", meta.get("text_name", cid))
            translator = chunk_meta.get("translator", meta.get("translator", ""))
            source_url = chunk_meta.get("source_url", meta.get("source_url", ""))
            token_count = chunk_meta.get("token_count", meta.get("token_count", 0))

            # Concept tags come from live EXPRESSES edges (VectorStore.get_metadata)
            raw_concepts = meta.get("concepts", [])
            if isinstance(raw_concepts, str):
                import json as _json
                try:
                    raw_concepts = _json.loads(raw_concepts)
                except Exception:
                    raw_concepts = []

            output.append(RetrievedChunk(
                chunk_id=cid,
                tradition=trad,
                text_name=text_name,
                section=section,
                translator=translator,
                body=body,
                token_count=int(token_count),
                similarity=item["similarity"],
                tier=item["tier"],
                concepts=raw_concepts,
                source_url=source_url,
            ))
            trad_counts[trad] = trad_counts.get(trad, 0) + 1

        return output
