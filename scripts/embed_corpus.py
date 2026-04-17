"""
embed_corpus.py — Stage 4: Embed every chunk into data/guru.db.

Reads corpus/**/chunks/*.toml, embeds each body via the configured provider,
and writes (chunk_id, dim, model, vector BLOB) rows into chunk_embeddings.
Vectors are stored as float32 little-endian blobs; `model` is tagged
`{provider}/{model_name}` so mixed-model rows stay self-describing.

Usage:
    python3 scripts/embed_corpus.py [--resume] [--reindex]
        [--tradition X] [--text Y] [--db data/guru.db]
        [--config config/embedding.toml]
"""

import argparse
import logging
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import tomllib

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
CORPUS_DIR = PROJECT_ROOT / "corpus"
CONFIG_PATH = PROJECT_ROOT / "config" / "embedding.toml"
DEFAULT_DB = PROJECT_ROOT / "data" / "guru.db"


# ── embedding providers ───────────────────────────────────────────────────────

def embed_ollama(texts: list[str], model: str) -> list[list[float]]:
    import json
    import urllib.request
    results = []
    for text in texts:
        payload = json.dumps({"model": model, "input": text}).encode()
        req = urllib.request.Request(
            "http://localhost:11434/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        results.append(data["embeddings"][0])
    return results


def embed_sentence_transformers(texts: list[str], model: str) -> list[list[float]]:
    from sentence_transformers import SentenceTransformer
    encoder = SentenceTransformer(model)
    return encoder.encode(texts, show_progress_bar=False).tolist()


def embed_api(texts: list[str], model: str) -> list[list[float]]:
    """OpenAI-compatible embedding API."""
    from openai import OpenAI
    client = OpenAI()
    resp = client.embeddings.create(input=texts, model=model)
    return [item.embedding for item in resp.data]


EMBED_FNS = {
    "ollama": embed_ollama,
    "sentence_transformers": embed_sentence_transformers,
    "api": embed_api,
}


# ── corpus walking ────────────────────────────────────────────────────────────

def collect_chunks(tradition_filter=None, text_filter=None) -> list[dict]:
    chunks = []
    if not CORPUS_DIR.exists():
        return chunks
    for trad_dir in sorted(CORPUS_DIR.iterdir()):
        if not trad_dir.is_dir() or trad_dir.name.endswith(".toml"):
            continue
        if tradition_filter and trad_dir.name != tradition_filter:
            continue
        for text_dir in sorted(trad_dir.iterdir()):
            if not text_dir.is_dir():
                continue
            if text_filter and text_dir.name != text_filter:
                continue
            chunk_dir = text_dir / "chunks"
            if not chunk_dir.exists():
                continue
            for chunk_file in sorted(chunk_dir.glob("*.toml")):
                with open(chunk_file, "rb") as f:
                    d = tomllib.load(f)
                meta = d["chunk"]
                chunks.append({
                    "chunk_id": meta["id"],
                    "body": d["content"]["body"],
                    "metadata": {
                        "tradition": meta.get("tradition", trad_dir.name),
                        "text_id": text_dir.name,
                        "section": meta.get("section", ""),
                        "text_name": meta.get("text_name", text_dir.name),
                        "translator": meta.get("translator", ""),
                        "source_url": meta.get("source_url", ""),
                        "token_count": meta.get("token_count", 0),
                        "concepts": [],  # derived from EXPRESSES edges at query time
                    },
                })
    return chunks


# ── main ──────────────────────────────────────────────────────────────────────

def existing_chunk_ids(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT chunk_id FROM chunk_embeddings")}


def upsert_embeddings(
    conn: sqlite3.Connection,
    items: list[tuple[str, list[float]]],
    model_tag: str,
) -> None:
    """items = [(chunk_id, vector), ...]. Writes float32 little-endian blobs."""
    rows = []
    for chunk_id, vec in items:
        arr = np.asarray(vec, dtype=np.float32)
        rows.append((chunk_id, int(arr.shape[0]), model_tag, arr.tobytes()))
    conn.executemany(
        "INSERT OR REPLACE INTO chunk_embeddings "
        "(chunk_id, dim, model, vector) VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Embed corpus into SQLite chunk_embeddings")
    parser.add_argument("--resume", action="store_true",
                        help="Skip chunks already embedded")
    parser.add_argument("--reindex", action="store_true",
                        help="Re-embed even if already present")
    parser.add_argument("--tradition")
    parser.add_argument("--text")
    parser.add_argument("--config", default=str(CONFIG_PATH))
    parser.add_argument("--db", default=str(DEFAULT_DB), type=Path)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stderr,
    )

    cfg_path = Path(args.config)
    with open(cfg_path, "rb") as f:
        cfg = tomllib.load(f)

    model_cfg = cfg.get("model", {})
    proc_cfg = cfg.get("processing", {})
    provider = model_cfg.get("provider", "ollama")
    model_name = model_cfg.get("model_name", "nomic-embed-text")
    batch_size = int(proc_cfg.get("batch_size", 32))
    delay = float(proc_cfg.get("delay", 0.0))
    model_tag = f"{provider}/{model_name}"

    embed_fn = EMBED_FNS.get(provider)
    if not embed_fn:
        logger.error(f"Unknown embedding provider: {provider}")
        sys.exit(1)

    if not args.db.exists():
        logger.error(f"Database not found: {args.db}")
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys=ON")

    chunks = collect_chunks(args.tradition, args.text)
    if not chunks:
        logger.warning("No chunks found. Run scripts/chunk.py first.")
        sys.exit(0)

    logger.info(f"Embedding {len(chunks)} chunks with {model_tag} ...")

    if args.resume and not args.reindex:
        have = existing_chunk_ids(conn)
        chunks = [c for c in chunks if c["chunk_id"] not in have]
        logger.info(f"  {len(chunks)} to embed after --resume filter")

    embedded = errors = 0

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i: i + batch_size]
        texts = [c["body"] for c in batch]

        try:
            embeddings = embed_fn(texts, model_name)
        except Exception as e:
            logger.error(f"Embedding batch {i//batch_size+1} failed: {e}")
            errors += len(batch)
            continue

        upsert_embeddings(
            conn,
            [(c["chunk_id"], emb) for c, emb in zip(batch, embeddings)],
            model_tag,
        )
        embedded += len(batch)
        logger.info(f"  [{i+len(batch)}/{len(chunks)}] embedded batch")

        if delay > 0:
            time.sleep(delay)

    total = conn.execute("SELECT COUNT(*) FROM chunk_embeddings").fetchone()[0]
    conn.close()
    print(f"\nDone: {embedded} embedded, {errors} errors. chunk_embeddings rows: {total}")


if __name__ == "__main__":
    main()
