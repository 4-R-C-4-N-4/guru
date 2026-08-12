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
import logging
import os
import sqlite3
import sys
from pathlib import Path

import numpy as np
import tomllib

logger = logging.getLogger(__name__)

from guru.paths import (
    CONFIG_MODEL as CONFIG_PATH,
    DEFAULT_DB,
    SCRIPTS_DIR,
    TAXONOMY_TOML,
)

sys.path.insert(0, str(SCRIPTS_DIR))
from vector_store import VectorStore  # noqa: E402

from guru import retrieval_legs as legs
from guru.corpus import resolve_chunk_path
from guru.preferences import UserPreferences
from guru.prompt import RetrievedChunk


def _load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def _load_taxonomy_labels() -> dict[str, str]:
    """Return {concept_id: definition} for keyword matching.

    Tolerates both the legacy flat ``[concepts.DOMAIN]`` layout and the
    three-tier ``[concepts.DOMAIN.FAMILY]`` layout (design.md §6): walks the
    ``concepts`` tree and collects every leaf string as a concept definition,
    regardless of nesting depth.
    """
    with open(TAXONOMY_TOML, "rb") as f:
        data = tomllib.load(f)
    labels: dict[str, str] = {}

    def _collect(node: dict) -> None:
        for key, val in node.items():
            if isinstance(val, dict):
                _collect(val)
            elif isinstance(val, str):
                labels[key] = val

    _collect(data.get("concepts", {}))
    return labels


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
        self._max_concept_walks = int(self._rcfg.get("max_concept_walks", 5))
        self._concept_min_word_len = int(self._rcfg.get("concept_match_min_word_len", 3))
        self._diversity_boost = float(self._rkcfg.get("diversity_boost", 0.1))
        self._vector_weight = float(self._rkcfg.get("vector_weight", 0.7))
        self._graph_weight = float(self._rkcfg.get("graph_weight", 0.3))
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
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            # 1. Vector search
            vector_hits = self._vector_search(query_embedding, user_prefs, k * 2)

            # 2. Concept leg. GRAPH_LEG=off isolates its contribution, matching
            #    guru-web's measurement toggle.
            graph_chunks = ([] if os.environ.get("GRAPH_LEG") == "off"
                            else self._graph_walk(query, user_prefs, conn))

            # 3. Lexical leg — what rescues small, commentary-heavy traditions
            #    that embed poorly. Absent from the pilot entirely.
            lex = legs.lexical_search(conn, query, k * 2)

            # 4. Summary leg
            summaries = legs.summary_search(conn, np.asarray(query_embedding,
                                                             dtype=np.float32), k)

            # 5. Edge leg — chunk↔chunk PARALLELS. Off unless EDGE_LEG=on;
            #    guru-web has never had it. See retrieval_legs.edge_partners.
            anchors = ({h["chunk_id"] for h in vector_hits}
                       | {h["chunk_id"] for h in graph_chunks})
            edge_chunks = legs.edge_partners(conn, anchors)

            return self._merge_and_rank(
                vector_hits, graph_chunks + edge_chunks, user_prefs, k,
                conn=conn, lexical=lex, summaries=summaries)[:k]
        finally:
            conn.close()

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

    def _graph_walk(self, query: str, prefs: UserPreferences,
                    conn: sqlite3.Connection) -> list[dict]:
        """Concept leg, at guru-web parity.

        Resolves the query across three match tiers — concept label/alias,
        family (expanding to its members), domain (expanding to every concept
        beneath it) — then collects the chunks that EXPRESS the resolved
        concepts, carrying the strongest match weight through to scoring.

        The pilot substring-matched concept ids only, so family- and
        domain-level queries ("cosmology", "soteriology") resolved to nothing.
        """
        concepts = legs.resolve_concepts(conn, query)
        if not concepts:
            return []
        concepts = legs.expand_concepts(conn, concepts)

        cap = self._max_concept_walks
        if cap:
            concepts = dict(sorted(concepts.items(), key=lambda kv: -kv[1])[:cap * 25])

        ph = ",".join("?" for _ in concepts)
        rows = conn.execute(
            f"""SELECT e.source_id AS chunk_id, e.tier, e.target_id AS concept_id,
                       n.tradition_id AS tradition, n.metadata_json
                  FROM edges e JOIN nodes n ON n.id = e.source_id
                 WHERE e.type = 'EXPRESSES' AND e.target_id IN ({ph})""",
            list(concepts)).fetchall()

        out: dict[str, dict] = {}
        for r in rows:
            trad = r["tradition"] or ""
            if not prefs.is_chunk_allowed(trad):
                continue
            w = concepts.get(r["concept_id"], 0.0)
            cur = out.get(r["chunk_id"])
            if cur is None:
                out[r["chunk_id"]] = {
                    "chunk_id": r["chunk_id"], "tier": r["tier"], "tradition": trad,
                    "metadata": json.loads(r["metadata_json"] or "{}"),
                    "similarity": 0.0, "match_weight": w,
                }
            else:
                cur["match_weight"] = max(cur["match_weight"], w)
        return list(out.values())

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
        conn: sqlite3.Connection | None = None,
        lexical: dict[str, float] | None = None,
        summaries: list[dict] | None = None,
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

        # Merge graph hits. Vector hits arrive tagged 'inferred' (vector
        # search has no tier signal), so this loop adopts the graph-side
        # tier whenever it carries more weight, and contributes graph_score
        # for the final ranking.
        for hit in graph_chunks:
            cid = hit["chunk_id"]
            trad = hit.get("tradition", "")
            if not prefs.is_chunk_allowed(trad):
                continue
            if cid in seen:
                existing_w = self._tier_w.get(seen[cid]["tier"], self._tier_w["inferred"])
                new_w = self._tier_w.get(hit.get("tier", "inferred"), self._tier_w["inferred"])
                if new_w > existing_w:
                    seen[cid]["tier"] = hit["tier"]
                seen[cid]["graph_score"] = max(seen[cid]["graph_score"], new_w)
                seen[cid]["match_weight"] = max(seen[cid].get("match_weight", 1.0),
                                                hit.get("match_weight", 1.0))
            else:
                tier = hit.get("tier", "inferred")
                seen[cid] = {
                    "chunk_id": cid,
                    "similarity": 0.0,
                    "tier": tier,
                    "tradition": trad,
                    "metadata": hit.get("metadata", {}),
                    "graph_score": self._tier_w.get(tier, self._tier_w["inferred"]),
                    "match_weight": hit.get("match_weight", 1.0),
                }

        # Summary leg — its own embeddings, entering at tier weight 0.4.
        for hit in (summaries or []):
            cid = hit["chunk_id"]
            if not prefs.is_chunk_allowed(hit.get("tradition", "")):
                continue
            if cid not in seen:
                seen[cid] = {
                    "chunk_id": cid, "similarity": hit["similarity"],
                    "tier": "summary", "tradition": hit.get("tradition", ""),
                    "metadata": {}, "graph_score": 0.0, "body": hit.get("body", ""),
                }

        # Lexical leg contributes candidates of its own, not just a score on
        # chunks another leg already found.
        lexical = lexical or {}
        if lexical and conn is not None:
            missing = [c for c in lexical if c not in seen]
            for i in range(0, len(missing), 400):
                batch = missing[i:i + 400]
                ph = ",".join("?" for _ in batch)
                for cid, trad in conn.execute(
                        f"SELECT id, tradition_id FROM nodes WHERE id IN ({ph})", batch):
                    if not prefs.is_chunk_allowed(trad or ""):
                        continue
                    seen[cid] = {
                        "chunk_id": cid, "similarity": 0.0, "tier": "inferred",
                        "tradition": trad or "", "metadata": {}, "graph_score": 0.0,
                    }

        # ts_rank and bm25 are both unbounded and corpus-relative, so the
        # lexical term is max-normalised across the candidate set before the
        # weight is applied — guru-web does the same (todo:0c38a006).
        max_lex = max(lexical.values(), default=0.0)
        lex_weight = float(os.environ.get("RETRIEVAL_LEXICAL_WEIGHT")
                           or self._rkcfg.get("lexical_weight", 1.0))
        graph_weight = float(os.environ.get("RETRIEVAL_GRAPH_WEIGHT")
                             or self._graph_weight)
        rarity = legs.corpus_rarity(conn) if conn is not None else {}

        scored: list[tuple[float, dict]] = []
        for item in seen.values():
            tier_w = self._tier_w.get(item["tier"], 0.4)
            # Only the graph term is scaled by the query-expansion match weight:
            # a domain-tier hit contributes a quarter of a concept-tier hit.
            graph_term = (max(tier_w, item.get("graph_score", 0.0))
                          * item.get("match_weight", 1.0))
            lex_term = (lex_weight * (lexical.get(item["chunk_id"], 0.0) / max_lex)
                        if max_lex > 0 else 0.0)
            # Corpus-wide tradition rarity, not "first appearance in this pool".
            diversity = self._diversity_boost * rarity.get(item["tradition"], 0.0)
            score = (self._vector_weight * item["similarity"]
                     + graph_weight * graph_term + lex_term + diversity)
            item["_score"] = score
            scored.append((score, item))

        scored.sort(key=lambda x: -x[0])
        if os.environ.get("RETRIEVAL_TRACE"):
            logger.info("[retrieval-trace] %d candidates (vec_w=%s graph_w=%s "
                        "lex_w=%s cap=%s)", len(scored), self._vector_weight,
                        graph_weight, lex_weight, self._max_per_trad)
            for sc, it in scored[:k]:
                logger.info("  %.3f %-22s sim=%.3f tier=%-9s mw=%.2f %s", sc,
                            it["tradition"], it["similarity"], it["tier"],
                            it.get("match_weight", 1.0), it["chunk_id"])

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
            if item.get("body"):            # summary nodes carry their own body
                body = item["body"]
            # guru-web filters per leg before merge; bodies only exist here, so
            # this applies at selection time instead. Env-gated exactly as there.
            if legs.quality_filter_enabled():
                keep, body = legs.quality_ok(body)
                if not keep:
                    continue
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
                try:
                    raw_concepts = json.loads(raw_concepts)
                except json.JSONDecodeError as e:
                    logger.warning(
                        "concepts metadata for %s is not valid JSON (%s); falling back to []. raw=%r",
                        cid, e, raw_concepts[:200],
                    )
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
