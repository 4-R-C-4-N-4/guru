"""
embed_summaries.py — embed live summary_nodes into summary_embeddings (G6).

Same provider/config/writer pattern as embed_corpus.py (config/embedding.toml,
float32 LE BLOBs, model tagged '{provider}/{model_name}'), targeting
summary_embeddings. Run after promote_dossiers.py; idempotent with --resume.

Usage:
    python3 scripts/embed_summaries.py [--resume] [--reindex] [--db path]
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import tomllib
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from embed_corpus import embed_ollama, embed_sentence_transformers  # noqa: E402

logger = logging.getLogger(__name__)
DEFAULT_DB = PROJECT_ROOT / "data" / "guru.db"
CONFIG_PATH = PROJECT_ROOT / "config" / "embedding.toml"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--resume", action="store_true", help="skip already-embedded summaries")
    ap.add_argument("--reindex", action="store_true", help="re-embed all")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--config", type=Path, default=CONFIG_PATH)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    cfg = tomllib.load(open(args.config, "rb"))
    provider = cfg["model"]["provider"]
    model_name = cfg["model"]["model_name"]
    dim = cfg["model"]["dimensions"]
    batch = cfg["processing"]["batch_size"]
    timeout = cfg["processing"].get("timeout", 120)
    tag = f"{provider}/{model_name}"

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, body FROM summary_nodes ORDER BY id").fetchall()
    if args.resume and not args.reindex:
        done = {r[0] for r in conn.execute("SELECT summary_id FROM summary_embeddings")}
        rows = [r for r in rows if r["id"] not in done]
    if not rows:
        logger.info("nothing to embed")
        return 0

    n = 0
    for i in range(0, len(rows), batch):
        chunk = rows[i:i + batch]
        texts = [r["body"] for r in chunk]
        if provider == "ollama":
            vecs = embed_ollama(texts, model_name, timeout=timeout)
        elif provider == "sentence_transformers":
            vecs = embed_sentence_transformers(texts, model_name)
        else:
            raise SystemExit(f"unsupported provider {provider!r}")
        for r, v in zip(chunk, vecs):
            arr = np.asarray(v, dtype="<f4")
            if arr.shape != (dim,):
                raise RuntimeError(f"{r['id']}: got dim {arr.shape}, want {dim}")
            conn.execute(
                "INSERT OR REPLACE INTO summary_embeddings (summary_id, dim, model, vector)"
                " VALUES (?,?,?,?)", (r["id"], dim, tag, arr.tobytes()))
        conn.commit()
        n += len(chunk)
        logger.info(f"  [{n}/{len(rows)}] embedded")
    logger.info(f"Done: {n} embedded. summary_embeddings rows: "
                f"{conn.execute('SELECT COUNT(*) FROM summary_embeddings').fetchone()[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
