"""
vector_store.py — Abstract vector store wrapper.

Backed by ChromaDB (default) or Qdrant, configured via config/embedding.toml.
Used by embed_corpus.py, propose_edges.py, backfill_concepts.py, and retriever.py.
"""

import json
import logging
from pathlib import Path
from typing import Any

import tomllib

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "embedding.toml"


class VectorStore:
    """
    Thin wrapper around ChromaDB (or Qdrant) with a stable interface
    for upsert, query, get_metadata, and update_metadata.
    """

    def __init__(self, config_path: Path = CONFIG_PATH):
        with open(config_path, "rb") as f:
            cfg = tomllib.load(f)

        backend = cfg.get("backend", {})
        self._backend_type = backend.get("type", "chromadb")
        self._collection_name = backend.get("collection_name", "guru_corpus")
        self._cfg = cfg

        if self._backend_type == "chromadb":
            self._init_chroma(backend)
        elif self._backend_type == "qdrant":
            self._init_qdrant(backend)
        else:
            raise ValueError(f"Unknown backend: {self._backend_type}")

    # ── ChromaDB ────────────────────────────────────────────────────────────

    def _init_chroma(self, backend: dict) -> None:
        import chromadb
        chroma_path = PROJECT_ROOT / backend.get("chroma_path", "data/vectordb")
        chroma_path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(chroma_path))
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.debug(f"ChromaDB collection '{self._collection_name}' at {chroma_path}")

    # ── Qdrant ───────────────────────────────────────────────────────────────

    def _init_qdrant(self, backend: dict) -> None:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams
        url = backend.get("qdrant_url", "http://localhost:6333")
        dims = self._cfg.get("model", {}).get("dimensions", 768)
        self._client = QdrantClient(url=url)
        # Create collection if not exists
        existing = [c.name for c in self._client.get_collections().collections]
        if self._collection_name not in existing:
            self._client.create_collection(
                self._collection_name,
                vectors_config=VectorParams(size=dims, distance=Distance.COSINE),
            )
        logger.debug(f"Qdrant collection '{self._collection_name}' at {url}")

    # ── Public interface ─────────────────────────────────────────────────────

    def upsert(self, chunk_id: str, embedding: list[float], metadata: dict) -> None:
        """Upsert a single vector with metadata."""
        if self._backend_type == "chromadb":
            self._collection.upsert(
                ids=[chunk_id],
                embeddings=[embedding],
                metadatas=[{k: (json.dumps(v) if isinstance(v, list) else v)
                            for k, v in metadata.items()}],
            )
        else:
            from qdrant_client.models import PointStruct
            self._client.upsert(
                self._collection_name,
                points=[PointStruct(id=self._id_to_int(chunk_id),
                                    vector=embedding,
                                    payload={**metadata, "_chunk_id": chunk_id})],
            )

    def upsert_batch(self, items: list[dict]) -> None:
        """Upsert a batch: each item has keys chunk_id, embedding, metadata."""
        if self._backend_type == "chromadb":
            self._collection.upsert(
                ids=[x["chunk_id"] for x in items],
                embeddings=[x["embedding"] for x in items],
                metadatas=[
                    {k: (json.dumps(v) if isinstance(v, list) else v)
                     for k, v in x["metadata"].items()}
                    for x in items
                ],
            )
        else:
            from qdrant_client.models import PointStruct
            points = [
                PointStruct(
                    id=self._id_to_int(x["chunk_id"]),
                    vector=x["embedding"],
                    payload={**x["metadata"], "_chunk_id": x["chunk_id"]},
                )
                for x in items
            ]
            self._client.upsert(self._collection_name, points=points)

    def query(
        self,
        embedding: list[float] | None = None,
        chunk_id: str | None = None,
        top_n: int = 10,
        where: dict | None = None,
        exclude_tradition: str | None = None,
        min_similarity: float = 0.0,
    ) -> list[dict]:
        """
        Query for nearest neighbours.
        Returns list of {chunk_id, similarity, metadata}.
        """
        if embedding is None and chunk_id is not None:
            # Look up the stored embedding for this chunk
            result = self._collection.get(ids=[chunk_id], include=["embeddings"])
            if result["embeddings"]:
                embedding = result["embeddings"][0]
            else:
                return []

        if self._backend_type == "chromadb":
            kw: dict[str, Any] = {}
            conditions = []
            if exclude_tradition:
                conditions.append({"tradition": {"$ne": exclude_tradition}})
            if where:
                conditions.append(where)
            if conditions:
                kw["where"] = {"$and": conditions} if len(conditions) > 1 else conditions[0]

            results = self._collection.query(
                query_embeddings=[embedding],
                n_results=top_n,
                include=["metadatas", "distances"],
                **kw,
            )
            out = []
            for cid, dist, meta in zip(
                results["ids"][0],
                results["distances"][0],
                results["metadatas"][0],
            ):
                similarity = 1.0 - dist  # cosine distance → similarity
                if similarity < min_similarity:
                    continue
                out.append({"chunk_id": cid, "similarity": similarity,
                            "metadata": meta, "label": meta.get("section", cid)})
            return out
        else:
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            filt = None
            if exclude_tradition:
                filt = Filter(must_not=[
                    FieldCondition(key="tradition", match=MatchValue(value=exclude_tradition))
                ])
            hits = self._client.search(
                self._collection_name,
                query_vector=embedding,
                limit=top_n,
                query_filter=filt,
                with_payload=True,
            )
            return [
                {"chunk_id": h.payload["_chunk_id"], "similarity": h.score,
                 "metadata": h.payload, "label": h.payload.get("section", "")}
                for h in hits if h.score >= min_similarity
            ]

    def count(self) -> int:
        if self._backend_type == "chromadb":
            return self._collection.count()
        else:
            return self._client.get_collection(self._collection_name).vectors_count or 0

    def get_metadata(self, chunk_id: str) -> dict:
        if self._backend_type == "chromadb":
            result = self._collection.get(ids=[chunk_id], include=["metadatas"])
            metas = result.get("metadatas") or []
            if metas:
                meta = dict(metas[0])
                # Deserialise JSON-encoded lists
                for k, v in meta.items():
                    if isinstance(v, str) and v.startswith("["):
                        try:
                            meta[k] = json.loads(v)
                        except Exception:
                            pass
                return meta
        return {}

    def update_metadata(self, chunk_id: str, updates: dict) -> None:
        if self._backend_type == "chromadb":
            existing = self.get_metadata(chunk_id)
            existing.update({k: (json.dumps(v) if isinstance(v, list) else v)
                              for k, v in updates.items()})
            self._collection.update(ids=[chunk_id], metadatas=[existing])
        else:
            self._client.set_payload(
                self._collection_name,
                payload=updates,
                points=[self._id_to_int(chunk_id)],
            )

    def exists(self, chunk_id: str) -> bool:
        if self._backend_type == "chromadb":
            result = self._collection.get(ids=[chunk_id])
            return bool(result["ids"])
        return False

    @staticmethod
    def _id_to_int(chunk_id: str) -> int:
        """Convert dotted chunk ID to stable integer for Qdrant."""
        return abs(hash(chunk_id)) % (2**63)
