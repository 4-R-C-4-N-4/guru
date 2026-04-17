"""
export.py — Produce export/guru-corpus.sql.gz (v2 export artifact).

One gzipped SQL file that `gunzip -c ... | psql $DATABASE_URL` loads into
a fresh or existing Postgres 17 + pgvector instance. The artifact is a
single transaction — a load failure leaves any prior corpus intact. All
bulk INSERTs run before index creation; corpus_metadata is written last
so mid-load failures leave the web app's version check unset.

Data sources combined by this script:
  - data/guru.db: nodes (traditions/concepts/chunks), edges, chunk_embeddings
  - corpus/traditions.toml: tradition registry
  - corpus/{tradition}/{text_id}/metadata.toml: per-text metadata
  - corpus/{tradition}/{text_id}/chunks/*.toml: per-chunk body + token count
  - concepts/taxonomy.toml: concept domains + definitions
  - schema/corpus-schema.sql: canonical Postgres DDL

Child tickets flesh out the stubs below (helpers, validate, version
counter, INSERT emitters, metadata block).
"""

from __future__ import annotations

import gzip
import logging
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_DB = PROJECT_ROOT / "data" / "guru.db"
SCHEMA_FILE = PROJECT_ROOT / "schema" / "corpus-schema.sql"
OUTPUT = PROJECT_ROOT / "export" / "guru-corpus.sql.gz"

# ── canonical v2 pinning ──────────────────────────────────────────────
# Bump SCHEMA_VERSION when schema/corpus-schema.sql changes; guru-web's
# EXPECTED_SCHEMA_VERSION must advance in the same deploy.
SCHEMA_VERSION = 1
EMBEDDING_MODEL = "ollama/nomic-embed-text"
EMBEDDING_DIM = 768

# Tables the export fully replaces on each load. Ordered for drop with
# CASCADE fallback — edges first (no inbound FKs), corpus_metadata last.
CORPUS_TABLES = ["edges", "chunks", "concepts", "texts", "traditions", "corpus_metadata"]


def git_sha() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT,
    ).decode().strip()


# ── SQL value emitters ────────────────────────────────────────────────
# All three return a bare SQL fragment suitable for splicing into an
# INSERT VALUES list. None/empty inputs emit literal NULL.

def esc(s: str | None) -> str:
    """Escape a Python string to a Postgres single-quoted literal."""
    if s is None:
        return "NULL"
    return "'" + s.replace("'", "''") + "'"


def esc_array(xs: list[str] | None) -> str:
    """Emit a Postgres text[] literal: '{"a","b"}' with embedded quotes
    escaped. Empty list and None both collapse to NULL so export.py can
    forward a missing section_path without special-casing upstream."""
    if not xs:
        return "NULL"
    inner = ",".join('"' + x.replace("\\", "\\\\").replace('"', '\\"') + '"' for x in xs)
    return f"'{{{inner}}}'"


def vec_to_pg(blob: bytes, expected_dim: int) -> str:
    """Render a float32 little-endian blob as pgvector's text format:
    '[0.1234567,...]'. Callers wrap this in ::vector in the INSERT."""
    arr = np.frombuffer(blob, dtype=np.float32)
    if arr.shape[0] != expected_dim:
        raise ValueError(f"vector dim mismatch: {arr.shape[0]} != {expected_dim}")
    # 7 significant digits is within float32 precision; more wastes bytes.
    return "'[" + ",".join(f"{x:.7f}" for x in arr) + "]'"


def validate(conn: sqlite3.Connection) -> None:
    """Pre-flight: refuse to export if the corpus is inconsistent.

    Filled in by todo:849f3e29.
    """
    pass


def next_corpus_version(conn: sqlite3.Connection) -> int:
    """Monotonic counter persisted in data/guru.db::_export_state.

    Filled in by todo:c4d42fb5.
    """
    return 0


def emit_inserts(conn: sqlite3.Connection, f) -> None:
    """Write INSERTs for traditions, texts, concepts, chunks, edges.

    Filled in by todo:f23d63a4.
    """
    pass


def emit_metadata(f, version: int, commit: str, exported_at: str) -> None:
    """Final corpus_metadata INSERT block (schema_version, embedding_model,
    embedding_dim, corpus_version, exported_at, source_commit_sha).

    Filled in by todo:b6ce9e3c.
    """
    pass


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stderr,
    )

    if not DEFAULT_DB.exists():
        raise SystemExit(f"Database not found: {DEFAULT_DB}")
    if not SCHEMA_FILE.exists():
        raise SystemExit(f"Schema not found: {SCHEMA_FILE}")

    conn = sqlite3.connect(DEFAULT_DB)
    conn.row_factory = sqlite3.Row

    validate(conn)
    version = next_corpus_version(conn)
    commit = git_sha()
    exported_at = datetime.now(timezone.utc).isoformat()

    OUTPUT.parent.mkdir(exist_ok=True)

    with gzip.open(OUTPUT, "wt", encoding="utf-8") as f:
        f.write(f"-- guru-corpus.sql.gz\n")
        f.write(f"-- Exported:       {exported_at}\n")
        f.write(f"-- Source commit:  {commit}\n")
        f.write(f"-- Corpus version: {version}\n")
        f.write(f"-- Schema version: {SCHEMA_VERSION}\n")
        f.write(f"-- Embedding:      {EMBEDDING_MODEL} @ {EMBEDDING_DIM}d\n\n")

        f.write("BEGIN;\n\n")

        # 1. Drop existing corpus tables (CASCADE drops dependent indexes/views)
        f.write(
            f"DROP TABLE IF EXISTS {', '.join(CORPUS_TABLES)} CASCADE;\n\n"
        )

        # 2. Canonical schema (byte-identical to guru-web's copy)
        f.write("-- ── canonical schema (schema/corpus-schema.sql) ──\n")
        f.write(SCHEMA_FILE.read_text())
        f.write("\n\n")

        # 3. Data — traditions, texts, concepts, chunks, edges in FK order
        emit_inserts(conn, f)

        # 4. Post-load indexes (HNSW, FK lookups) land here once the
        #    emit_inserts step populates rows. Separate ticket may cover
        #    this; for now schema/corpus-schema.sql carries no indexes
        #    and we add them inline in a later ticket.

        # 5. Metadata last — mid-load failure leaves this unset and the
        #    web app refuses to serve.
        emit_metadata(f, version, commit, exported_at)

        f.write("COMMIT;\n")

    conn.close()

    size_mb = OUTPUT.stat().st_size / (1024 * 1024)
    print(f"Exported {OUTPUT} ({size_mb:.2f} MB)")
    print(f"  corpus_version:  {version}")
    print(f"  source_commit:   {commit[:12]}")
    print(f"  embedding_model: {EMBEDDING_MODEL}")


if __name__ == "__main__":
    main()
