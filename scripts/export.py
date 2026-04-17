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
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_DB = PROJECT_ROOT / "data" / "guru.db"
SCHEMA_FILE = PROJECT_ROOT / "schema" / "corpus-schema.sql"
OUTPUT = PROJECT_ROOT / "export" / "guru-corpus.sql.gz"
CORPUS_DIR = PROJECT_ROOT / "corpus"
TAXONOMY_TOML = PROJECT_ROOT / "concepts" / "taxonomy.toml"

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
    """Refuse to export if the corpus is inconsistent.

    Three checks:
      1. every chunk node has a chunk_embeddings row
      2. every chunk_embeddings row references a real chunk node
      3. every vector is at the pinned dim and model
    """
    n_chunks = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE type='chunk'"
    ).fetchone()[0]
    n_embeddings = conn.execute(
        "SELECT COUNT(*) FROM chunk_embeddings"
    ).fetchone()[0]
    if n_chunks != n_embeddings:
        raise SystemExit(
            f"Corpus inconsistent: {n_chunks} chunk nodes vs "
            f"{n_embeddings} chunk_embeddings rows. "
            f"Run scripts/embed_corpus.py."
        )

    orphan = conn.execute(
        "SELECT COUNT(*) FROM chunk_embeddings e "
        "LEFT JOIN nodes n ON n.id = e.chunk_id AND n.type = 'chunk' "
        "WHERE n.id IS NULL"
    ).fetchone()[0]
    if orphan:
        raise SystemExit(
            f"{orphan} chunk_embeddings rows reference chunk_ids "
            f"that are not present in nodes(type='chunk'). "
            f"Re-run scripts/embed_corpus.py to rebuild."
        )

    bad = conn.execute(
        "SELECT COUNT(*) FROM chunk_embeddings "
        "WHERE dim != ? OR model != ?",
        (EMBEDDING_DIM, EMBEDDING_MODEL),
    ).fetchone()[0]
    if bad:
        raise SystemExit(
            f"{bad} chunk_embeddings rows do not match the pinned "
            f"{EMBEDDING_MODEL} @ {EMBEDDING_DIM}d. Re-run embed_corpus.py."
        )

    logger.info(
        "validate: %d chunks, all pinned to %s @ %dd",
        n_chunks, EMBEDDING_MODEL, EMBEDDING_DIM,
    )


def next_corpus_version(conn: sqlite3.Connection) -> int:
    """Monotonic counter persisted in data/guru.db::_export_state.

    Every call increments and returns the new value, so each export
    carries a strictly higher corpus_version than the previous one even
    across machine reboots or a moved checkout.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS _export_state ("
        "  key TEXT PRIMARY KEY, value TEXT NOT NULL"
        ")"
    )
    row = conn.execute(
        "SELECT value FROM _export_state WHERE key = 'corpus_version'"
    ).fetchone()
    current = int(row[0]) if row else 0
    nxt = current + 1
    conn.execute(
        "INSERT OR REPLACE INTO _export_state (key, value) VALUES (?, ?)",
        ("corpus_version", str(nxt)),
    )
    conn.commit()
    return nxt


# ── data loaders ──────────────────────────────────────────────────────
# Each loader returns rows already sorted by primary key so the emitter
# layer stays deterministic without re-sorting.

def load_traditions(conn: sqlite3.Connection) -> list[dict]:
    """From nodes WHERE type='tradition'. traditions.toml is stale
    (auto-derived once, never refreshed) — SQLite is the live source of
    truth for which traditions actually exist in the graph."""
    rows = []
    for node_id, label in conn.execute(
        "SELECT id, label FROM nodes WHERE type='tradition' ORDER BY id"
    ):
        rows.append({"id": node_id, "label": label})
    return rows


def load_texts() -> list[dict]:
    """From corpus/{tradition_dir}/{text_id}/metadata.toml. Uses the
    parent-parent directory name as the canonical tradition id — the
    'tradition' field in metadata.toml is unreliable (mixed case)."""
    rows = []
    for p in sorted(CORPUS_DIR.rglob("metadata.toml")):
        with open(p, "rb") as fp:
            d = tomllib.load(fp)
        tradition_dir = p.parts[-3]  # .../corpus/<dir>/<text_id>/metadata.toml
        rows.append({
            "id": d["text_id"],
            "tradition": tradition_dir,
            "label": d["text_name"],
            "translator": d.get("translator"),
            "source_url": d.get("source_url"),
            "sections_format": d.get("sections_format"),
        })
    rows.sort(key=lambda r: r["id"])
    return rows


def load_concepts(conn: sqlite3.Connection) -> list[dict]:
    """Merge SQLite node rows (id, label) with concepts/taxonomy.toml
    (domain, definition). Taxonomy is the canonical source for the two
    descriptive fields; SQLite is canonical for which concepts actually
    exist in the live graph."""
    with open(TAXONOMY_TOML, "rb") as fp:
        tax = tomllib.load(fp)
    # taxonomy.toml shape: { concepts: { domain: { concept_id: definition }}}
    lookup: dict[str, tuple[str, str]] = {}
    for domain, members in tax["concepts"].items():
        for cid, definition in members.items():
            lookup[cid] = (domain, definition)

    rows = []
    for node_id, label in conn.execute(
        "SELECT id, label FROM nodes WHERE type='concept' ORDER BY id"
    ):
        # SQLite ids are "concept.<short_id>"; taxonomy uses <short_id>
        short = node_id.removeprefix("concept.")
        domain, definition = lookup.get(short, (None, None))
        rows.append({
            "id": node_id,
            "label": label,
            "domain": domain,
            "definition": definition,
        })
    return rows


def load_chunks(conn: sqlite3.Connection):
    """Yield chunk rows joining corpus TOMLs with chunk_embeddings.
    Streams one chunk at a time so the 2531-row corpus never fully
    materializes in memory."""
    # Pre-load all (chunk_id → vector) from SQLite into a dict keyed by
    # chunk_id. 2531 rows × 3 KB ≈ 7.5 MB — fine to hold in memory.
    emb = {
        cid: vec for cid, vec in conn.execute(
            "SELECT chunk_id, vector FROM chunk_embeddings"
        )
    }
    # Walk TOMLs in a deterministic order; text_id comes from the
    # dotted id's middle segment (always canonical kebab-case).
    paths = sorted(CORPUS_DIR.rglob("chunks/*.toml"))
    for p in paths:
        with open(p, "rb") as fp:
            d = tomllib.load(fp)
        chunk = d["chunk"]
        cid = chunk["id"]
        if cid not in emb:
            raise SystemExit(
                f"chunk {cid} has a TOML but no chunk_embeddings row"
            )
        # corpus/<tradition_dir>/<text_id>/chunks/NNN.toml → tradition_dir
        tradition_dir = p.parts[-4]
        # id format is "<raw_tradition>.<text_id>.<seq>"; text_id =
        # middle segment. Split on dots from the LEFT then take [1].
        parts = cid.split(".")
        text_id = parts[1] if len(parts) >= 3 else chunk.get("text_id")
        yield {
            "id": cid,
            "text_id": text_id,
            "tradition": tradition_dir,
            "text_name": chunk["text_name"],
            "section": chunk.get("section"),
            "section_path": None,  # not populated in v1 TOMLs
            "translator": chunk.get("translator"),
            "body": d["content"]["body"],
            "token_count": int(chunk.get("token_count", 0)),
            "vector": emb[cid],
        }
    # Sort order: sorted(rglob(...)) gives lexicographic path order,
    # which for this layout matches chunk.id primary-key order closely
    # but not exactly (Title Case vs lowercase sorts differently). The
    # emitter sorts explicitly, so this is just a streaming detail.


def load_edges(conn: sqlite3.Connection) -> list[dict]:
    """SQLite edges → Postgres column names. v1 schema has no `weight`
    column, so the Postgres `weight` column is always NULL from this
    pipeline (the column exists for downstream ranking hooks)."""
    rows = []
    for r in conn.execute(
        "SELECT source_id, target_id, type, tier, justification "
        "FROM edges ORDER BY source_id, target_id, type"
    ):
        rows.append({
            "source": r[0],
            "target": r[1],
            "edge_type": r[2],
            "tier": r[3],
            "weight": None,
            "annotation": r[4],
        })
    return rows


# ── emitters ──────────────────────────────────────────────────────────

def emit_inserts(conn: sqlite3.Connection, f) -> None:
    """Write INSERTs for traditions, texts, concepts, chunks, edges in
    FK-dependency order. Every row is deterministic (stable sort, fixed
    float precision) so re-exports of unchanged data are byte-identical
    except for the corpus_version counter."""
    f.write("-- traditions\n")
    for r in load_traditions(conn):
        f.write(
            f"INSERT INTO traditions (id, label, description, color) "
            f"VALUES ({esc(r['id'])}, {esc(r['label'])}, NULL, NULL);\n"
        )
    f.write("\n")

    f.write("-- texts\n")
    for r in load_texts():
        f.write(
            f"INSERT INTO texts (id, tradition, label, translator, "
            f"source_url, sections_format) VALUES ("
            f"{esc(r['id'])}, {esc(r['tradition'])}, {esc(r['label'])}, "
            f"{esc(r['translator'])}, {esc(r['source_url'])}, "
            f"{esc(r['sections_format'])});\n"
        )
    f.write("\n")

    f.write("-- concepts\n")
    for r in load_concepts(conn):
        f.write(
            f"INSERT INTO concepts (id, label, domain, definition) "
            f"VALUES ({esc(r['id'])}, {esc(r['label'])}, "
            f"{esc(r['domain'])}, {esc(r['definition'])});\n"
        )
    f.write("\n")

    f.write("-- chunks\n")
    # Materialize + sort by id for byte-stable output
    chunks = sorted(load_chunks(conn), key=lambda r: r["id"])
    for r in chunks:
        f.write(
            f"INSERT INTO chunks (id, text_id, tradition, text_name, "
            f"section, section_path, translator, body, token_count, "
            f"embedding) VALUES ("
            f"{esc(r['id'])}, {esc(r['text_id'])}, {esc(r['tradition'])}, "
            f"{esc(r['text_name'])}, {esc(r['section'])}, "
            f"{esc_array(r['section_path'])}, {esc(r['translator'])}, "
            f"{esc(r['body'])}, {r['token_count']}, "
            f"{vec_to_pg(r['vector'], EMBEDDING_DIM)}::vector);\n"
        )
    f.write("\n")

    f.write("-- edges\n")
    for r in load_edges(conn):
        weight = "NULL" if r["weight"] is None else f"{r['weight']}"
        f.write(
            f"INSERT INTO edges (source, target, edge_type, tier, "
            f"weight, annotation) VALUES ("
            f"{esc(r['source'])}, {esc(r['target'])}, "
            f"{esc(r['edge_type'])}, {esc(r['tier'])}, {weight}, "
            f"{esc(r['annotation'])});\n"
        )
    f.write("\n")


def emit_metadata(f, version: int, commit: str, exported_at: str) -> None:
    """Final corpus_metadata block. Written LAST so a mid-load failure
    leaves the table unset, and the web app's schema-version check then
    refuses to serve a half-loaded corpus."""
    f.write("-- corpus_metadata (written last — mid-load failure leaves it unset)\n")
    f.write("INSERT INTO corpus_metadata (key, value) VALUES\n")
    rows = [
        ("schema_version",    str(SCHEMA_VERSION)),
        ("embedding_model",   EMBEDDING_MODEL),
        ("embedding_dim",     str(EMBEDDING_DIM)),
        ("corpus_version",    str(version)),
        ("exported_at",       exported_at),
        ("source_commit_sha", commit),
    ]
    for i, (k, v) in enumerate(rows):
        comma = "," if i < len(rows) - 1 else ";"
        f.write(f"  ({esc(k)}, {esc(v)}){comma}\n")
    f.write("\n")


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
