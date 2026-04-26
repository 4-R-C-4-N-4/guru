"""
vector_store.py — SQLite-backed vector store.

Reads float32 little-endian blobs from data/guru.db::chunk_embeddings and
computes cosine similarity in-process with numpy. At ~2.5K chunks × 768
dims this fits in <10 MB of RAM and a single query takes ≤ 1 ms; the
class is intentionally simple with no external service.

Metadata (tradition, text_id, section, concepts, etc.) is reconstructed
on demand from the live SQLite graph:
  - tradition ← nodes.tradition_id
  - section / text_name / translator / source_url / token_count
    ← corpus/<tradition>/<text_id>/chunks/<NNN>.toml
  - concepts ← edges(source=chunk, type='EXPRESSES').target_id

The API matches the previous ChromaDB-backed implementation so callers
(HybridRetriever, propose_edges.py) don't change.
"""

from __future__ import annotations

import logging
import sqlite3
import tomllib
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable

import numpy as np

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_DB = PROJECT_ROOT / "data" / "guru.db"

import sys
sys.path.insert(0, str(PROJECT_ROOT))
from guru.corpus import resolve_chunk_path  # noqa: E402


class VectorStore:
    """SQLite-backed vector store. One instance per process; vectors
    and the chunk→metadata map are cached after the first access."""

    def __init__(self, db_path: str | Path = DEFAULT_DB):
        self._db_path = Path(db_path)
        # Lazy-loaded on first query
        self._ids: list[str] | None = None
        self._vectors: np.ndarray | None = None  # (N, dim), unit-norm
        self._idx: dict[str, int] = {}
        self._tradition: dict[str, str] = {}
        self._label: dict[str, str] = {}

    # ── loading ─────────────────────────────────────────────────────────

    def _ensure_loaded(self) -> None:
        if self._vectors is not None:
            return
        with closing(sqlite3.connect(self._db_path)) as conn, conn:
            rows = conn.execute(
                "SELECT e.chunk_id, e.dim, e.vector, n.tradition_id, n.label "
                "FROM chunk_embeddings e "
                "LEFT JOIN nodes n ON n.id = e.chunk_id "
                "ORDER BY e.chunk_id"
            ).fetchall()
        if not rows:
            self._ids = []
            self._vectors = np.zeros((0, 0), dtype=np.float32)
            return

        dim = rows[0][1]
        mat = np.empty((len(rows), dim), dtype=np.float32)
        ids: list[str] = []
        for i, (cid, _dim, vec, tradition_id, label) in enumerate(rows):
            ids.append(cid)
            mat[i] = np.frombuffer(vec, dtype=np.float32)
            self._tradition[cid] = tradition_id or ""
            self._label[cid] = label or cid
        self._ids = ids
        self._vectors = mat
        self._idx = {cid: i for i, cid in enumerate(ids)}
        logger.debug("VectorStore: loaded %d vectors (dim=%d)", len(ids), dim)

    def _invalidate(self) -> None:
        self._ids = None
        self._vectors = None
        self._idx = {}
        self._tradition = {}
        self._label = {}

    # ── writes ──────────────────────────────────────────────────────────

    def _model_tag(self, metadata: dict | None) -> str:
        """Model string stored in chunk_embeddings.model. Callers may
        pass it explicitly via metadata['_model']; otherwise we tag the
        row with an unknown sentinel so validate() can flag it later."""
        if metadata and "_model" in metadata:
            return str(metadata["_model"])
        return "unknown/unknown"

    def upsert(self, chunk_id: str, embedding: list[float], metadata: dict) -> None:
        """Write one (chunk_id, vector) row. Metadata arg is retained for
        API compatibility — everything except `_model` is ignored here
        because nodes+edges carry the canonical metadata."""
        arr = np.asarray(embedding, dtype=np.float32)
        with closing(sqlite3.connect(self._db_path)) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO chunk_embeddings "
                "(chunk_id, dim, model, vector) VALUES (?, ?, ?, ?)",
                (chunk_id, int(arr.shape[0]), self._model_tag(metadata), arr.tobytes()),
            )
            conn.commit()
        self._invalidate()

    def upsert_batch(self, items: list[dict]) -> None:
        """Each item = {chunk_id, embedding, metadata}. metadata['_model']
        (if present) tags the row."""
        if not items:
            return
        rows: list[tuple] = []
        for it in items:
            arr = np.asarray(it["embedding"], dtype=np.float32)
            rows.append((
                it["chunk_id"],
                int(arr.shape[0]),
                self._model_tag(it.get("metadata")),
                arr.tobytes(),
            ))
        with closing(sqlite3.connect(self._db_path)) as conn, conn:
            conn.executemany(
                "INSERT OR REPLACE INTO chunk_embeddings "
                "(chunk_id, dim, model, vector) VALUES (?, ?, ?, ?)",
                rows,
            )
            conn.commit()
        self._invalidate()

    # ── queries ─────────────────────────────────────────────────────────

    def query(
        self,
        embedding: list[float] | None = None,
        chunk_id: str | None = None,
        top_n: int = 10,
        where: dict | None = None,
        exclude_tradition: str | None = None,
        min_similarity: float = 0.0,
    ) -> list[dict]:
        """Cosine-similarity search. Returns [{chunk_id, similarity,
        metadata, label}] sorted descending."""
        self._ensure_loaded()
        if self._vectors is None or len(self._ids or []) == 0:
            return []

        # Resolve query vector
        if embedding is not None:
            q = np.asarray(embedding, dtype=np.float32)
        elif chunk_id is not None:
            i = self._idx.get(chunk_id)
            if i is None:
                return []
            q = self._vectors[i]
        else:
            raise ValueError("query() needs embedding or chunk_id")

        norm = float(np.linalg.norm(q))
        if norm == 0.0:
            return []
        q = q / norm

        # Dense cosine sim against all rows; stored vectors are unit-norm
        # from ollama/nomic-embed-text, so dot product == cosine.
        sims = self._vectors @ q

        # Apply filters: produce a boolean mask over rows
        mask = sims >= min_similarity
        if chunk_id is not None:
            # exclude self from neighbour search
            mask &= np.arange(len(self._ids)) != self._idx[chunk_id]
        if exclude_tradition:
            for i, cid in enumerate(self._ids):
                if self._tradition.get(cid) == exclude_tradition:
                    mask[i] = False
        if where is not None:
            _apply_where_mask(
                mask,
                ids=self._ids,
                tradition_by_id=self._tradition,
                where=where,
                db_path=self._db_path,
            )

        if not mask.any():
            return []

        # Top-N over the surviving mask
        valid = np.flatnonzero(mask)
        order = np.argsort(-sims[valid])[:top_n]
        picks = valid[order]

        out: list[dict] = []
        for i in picks:
            cid = self._ids[i]
            meta = self.get_metadata(cid)
            out.append({
                "chunk_id": cid,
                "similarity": float(sims[i]),
                "metadata": meta,
                "label": meta.get("section") or self._label.get(cid, cid),
            })
        return out

    def count(self) -> int:
        with closing(sqlite3.connect(self._db_path)) as conn, conn:
            return conn.execute(
                "SELECT COUNT(*) FROM chunk_embeddings"
            ).fetchone()[0]

    def exists(self, chunk_id: str) -> bool:
        with closing(sqlite3.connect(self._db_path)) as conn, conn:
            return conn.execute(
                "SELECT 1 FROM chunk_embeddings WHERE chunk_id = ? LIMIT 1",
                (chunk_id,),
            ).fetchone() is not None

    # ── metadata reconstruction ─────────────────────────────────────────

    def get_metadata(self, chunk_id: str) -> dict:
        """Reconstruct a chunk's display metadata from SQLite + TOML.
        Keys: tradition, text_id, text_name, section, translator,
        source_url, token_count, concepts[]."""
        self._ensure_loaded()
        meta: dict[str, Any] = {
            "tradition": self._tradition.get(chunk_id, ""),
        }
        parts = chunk_id.split(".")
        if len(parts) >= 3:
            meta["text_id"] = parts[1]
            toml_path = _chunk_toml_for(chunk_id)
            if toml_path and toml_path.exists():
                with open(toml_path, "rb") as f:
                    d = tomllib.load(f)
                chunk = d.get("chunk", {})
                meta["text_name"] = chunk.get("text_name", "")
                meta["section"] = chunk.get("section", "")
                meta["translator"] = chunk.get("translator", "")
                meta["source_url"] = chunk.get("source_url", "")
                meta["token_count"] = chunk.get("token_count", 0)

        meta["concepts"] = _concepts_for(self._db_path, chunk_id)
        return meta

    def update_metadata(self, chunk_id: str, updates: dict) -> None:
        """No-op: metadata lives in SQLite nodes/edges and corpus TOMLs,
        not in chunk_embeddings. Retained for API compatibility.
        Concepts are sourced live from EXPRESSES edges."""
        logger.debug(
            "update_metadata(%s) ignored; metadata is derived from "
            "nodes+edges, not stored alongside vectors.", chunk_id,
        )


# ── helpers ───────────────────────────────────────────────────────────


def _chunk_toml_for(chunk_id: str) -> Path | None:
    return resolve_chunk_path(chunk_id)


def _concepts_for(db_path: Path, chunk_id: str) -> list[str]:
    """List of concept IDs this chunk expresses, via EXPRESSES edges."""
    with closing(sqlite3.connect(db_path)) as conn, conn:
        rows = conn.execute(
            "SELECT target_id FROM edges "
            "WHERE source_id = ? AND type = 'EXPRESSES'",
            (chunk_id,),
        ).fetchall()
    return [r[0] for r in rows]


def _apply_where_mask(
    mask: np.ndarray,
    *,
    ids: list[str],
    tradition_by_id: dict[str, str],
    where: dict,
    db_path: Path,
) -> None:
    """Interpret a ChromaDB-style where-clause against already-loaded
    tradition and on-demand text_id. Mutates `mask` in place."""
    text_id_by_id: dict[str, str] | None = None

    def ensure_text_ids() -> dict[str, str]:
        nonlocal text_id_by_id
        if text_id_by_id is None:
            text_id_by_id = {}
            for cid in ids:
                parts = cid.split(".")
                text_id_by_id[cid] = parts[1] if len(parts) >= 3 else ""
        return text_id_by_id

    def eval_clause(clause: dict) -> Iterable[bool]:
        if "$and" in clause:
            sub_masks = [list(eval_clause(c)) for c in clause["$and"]]
            return [all(col) for col in zip(*sub_masks)] if sub_masks else [True] * len(ids)
        if "$or" in clause:
            sub_masks = [list(eval_clause(c)) for c in clause["$or"]]
            return [any(col) for col in zip(*sub_masks)] if sub_masks else [True] * len(ids)

        # Single field condition: {"tradition": {"$ne": "X"}} or
        # {"text_id": {"$in": [...]}} etc.
        assert len(clause) == 1, f"expected one field per clause, got {clause!r}"
        field, cond = next(iter(clause.items()))
        if field == "tradition":
            values = [tradition_by_id.get(cid, "") for cid in ids]
        elif field == "text_id":
            values = [ensure_text_ids()[cid] for cid in ids]
        else:
            logger.warning("VectorStore where: unsupported field %r — skipped", field)
            return [True] * len(ids)

        if isinstance(cond, dict):
            if "$ne" in cond:
                target = cond["$ne"]
                return [v != target for v in values]
            if "$eq" in cond:
                target = cond["$eq"]
                return [v == target for v in values]
            if "$in" in cond:
                targets = set(cond["$in"])
                return [v in targets for v in values]
            if "$nin" in cond:
                targets = set(cond["$nin"])
                return [v not in targets for v in values]
            logger.warning("VectorStore where: unsupported op in %r — skipped", cond)
            return [True] * len(ids)
        # Bare scalar -> equality
        return [v == cond for v in values]

    result = list(eval_clause(where))
    for i, keep in enumerate(result):
        if not keep:
            mask[i] = False
