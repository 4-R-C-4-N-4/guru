"""
export.py — Produce export/guru-corpus.sql.gz (v2 export artifact).

One gzipped SQL file that `gunzip -c ... | psql -v ON_ERROR_STOP=1`
loads into a Postgres 17 + pgvector instance. The artifact replaces the
entire corpus atomically via an ALTER SCHEMA … RENAME swap, leaving the
`public` schema (users, sessions, queries, etc.) untouched.

Data sources combined by this script:
  - data/guru.db: nodes (traditions/concepts/chunks), edges, chunk_embeddings
  - corpus/{tradition}/{text_id}/metadata.toml: per-text metadata
  - corpus/{tradition}/{text_id}/chunks/*.toml: per-chunk body + token count
  - concepts/taxonomy.toml: concept domains + definitions
  - schema/corpus-schema.sql: canonical Postgres DDL template (unprefixed)

Schema isolation: the emitted artifact creates `corpus_new.*` tables, loads
via COPY FROM STDIN, validates inline, then swaps `corpus_new` → `corpus`.
"""

from __future__ import annotations

import gzip
import logging
import re
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
SCHEMA_VERSION = 2
EMBEDDING_MODEL = "ollama/nomic-embed-text"
EMBEDDING_DIM = 768

# Schema used for the staging area during load. The swap renames this to
# the live `corpus` schema after validation passes.
STAGING_SCHEMA = "corpus_new"
LIVE_SCHEMA = "corpus"

# Postgres role the web app authenticates as (matches systemd's DATABASE_URL
# on guru-web-prod). The artifact GRANTs USAGE/SELECT to this role on the
# staging schema before the swap, so reloads don't strand the app on a
# permission-denied corpus. Update here AND on the VPS in lockstep.
APP_ROLE = "guru"


def git_sha() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT,
    ).decode().strip()


# ── SQL value emitters (for INSERT — kept for metadata block) ─────────

def esc(s: str | None) -> str:
    """Escape a Python string to a Postgres single-quoted literal."""
    if s is None:
        return "NULL"
    return "'" + s.replace("'", "''") + "'"


def esc_array(xs: list[str] | None) -> str:
    """Emit a Postgres text[] literal: '{"a","b"}' with embedded quotes
    escaped. Empty list and None both collapse to NULL."""
    if not xs:
        return "NULL"
    inner = ",".join('"' + x.replace("\\", "\\\\").replace('"', '\\"') + '"' for x in xs)
    return f"'{{{inner}}}'"


def vec_to_pg(blob: bytes, expected_dim: int) -> str:
    """Render a float32 little-endian blob as pgvector's text format:
    '[0.1234567,...]'."""
    arr = np.frombuffer(blob, dtype=np.float32)
    if arr.shape[0] != expected_dim:
        raise ValueError(f"vector dim mismatch: {arr.shape[0]} != {expected_dim}")
    return "[" + ",".join(f"{x:.7f}" for x in arr) + "]"


# ── COPY value escape ─────────────────────────────────────────────────
# Postgres COPY FROM STDIN (text format) uses a very small escape set:
#   \ → \\, \t → \t, \n → \n, \r → \r, and NULL is represented as \N.
# Everything else (including single quotes) is literal.

_COPY_ESCAPES = str.maketrans({
    "\\": "\\\\",
    "\t": "\\t",
    "\n": "\\n",
    "\r": "\\r",
})


def copy_esc(s: str | None) -> str:
    """Escape a Python string for Postgres COPY FROM STDIN (text format).
    None → \\N. Backslashes and newlines are escaped."""
    if s is None:
        return "\\N"
    return s.translate(_COPY_ESCAPES)


# ── validation (local, before export) ─────────────────────────────────

def validate(conn: sqlite3.Connection) -> int:
    """Refuse to export if the corpus is inconsistent.

    Returns the chunk count so the emitted validation block can hardcode it.
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
    return n_chunks


def next_corpus_version(conn: sqlite3.Connection) -> int:
    """Monotonic counter persisted in data/guru.db::_export_state."""
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

def load_traditions(conn: sqlite3.Connection) -> list[dict]:
    """From nodes WHERE type='tradition'. SQLite is the live source of truth."""
    rows = []
    for node_id, label in conn.execute(
        "SELECT id, label FROM nodes WHERE type='tradition' ORDER BY id"
    ):
        rows.append({"id": node_id, "label": label})
    return rows


def load_texts() -> list[dict]:
    """From corpus/{tradition_dir}/{text_id}/metadata.toml."""
    rows = []
    for p in sorted(CORPUS_DIR.rglob("metadata.toml")):
        with open(p, "rb") as fp:
            d = tomllib.load(fp)
        tradition_dir = p.parts[-3]
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
    """Merge SQLite node rows with concepts/taxonomy.toml."""
    with open(TAXONOMY_TOML, "rb") as fp:
        tax = tomllib.load(fp)
    lookup: dict[str, tuple[str, str]] = {}
    for domain, members in tax["concepts"].items():
        for cid, definition in members.items():
            lookup[cid] = (domain, definition)

    rows = []
    for node_id, label in conn.execute(
        "SELECT id, label FROM nodes WHERE type='concept' ORDER BY id"
    ):
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
    """Yield chunk rows joining corpus TOMLs with chunk_embeddings."""
    emb = {
        cid: vec for cid, vec in conn.execute(
            "SELECT chunk_id, vector FROM chunk_embeddings"
        )
    }
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
        tradition_dir = p.parts[-4]
        parts = cid.split(".")
        text_id = parts[1] if len(parts) >= 3 else chunk.get("text_id")
        yield {
            "id": cid,
            "text_id": text_id,
            "tradition": tradition_dir,
            "text_name": chunk["text_name"],
            "section": chunk.get("section"),
            "section_path": None,
            "translator": chunk.get("translator"),
            "body": d["content"]["body"],
            "token_count": int(chunk.get("token_count", 0)),
            "vector": emb[cid],
        }


def load_edges(conn: sqlite3.Connection) -> list[dict]:
    """SQLite edges → Postgres column names."""
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


# ── DDL prefixer ──────────────────────────────────────────────────────
# schema/corpus-schema.sql is kept unprefixed so it stays byte-identical
# with the copy in guru-web.  export.py prefixes table names on the fly.

def prefix_ddl(sql: str, schema: str) -> str:
    """Prefix every table name in the canonical DDL with `schema.`.

    Line-oriented — relies on each clause fitting on one line in the
    schema. The CI hash check keeps both repos' schemas in lock-step,
    so reformatting is detectable; if a multi-line clause is ever added,
    this function needs a real parser.

    Handles:
      CREATE TABLE traditions (...)   → CREATE TABLE corpus_new.traditions (...)
      CREATE INDEX idx ON chunks (...) → CREATE INDEX idx ON corpus_new.chunks (...)
      text_id TEXT NOT NULL REFERENCES texts(id) → REFERENCES corpus_new.texts(id)
    """
    out = []
    for line in sql.splitlines():
        line = re.sub(
            r"(CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?)(\w+)",
            rf"\1{schema}.\2",
            line,
        )
        line = re.sub(
            r"(CREATE\s+(?:UNIQUE\s+)?INDEX\s+\S+\s+ON\s+)(\w+)",
            rf"\1{schema}.\2",
            line,
        )
        line = re.sub(
            r"(REFERENCES\s+)(\w+)",
            rf"\1{schema}.\2",
            line,
        )
        out.append(line)
    return "\n".join(out)


# ── emitters (COPY FORMAT) ────────────────────────────────────────────

def emit_copy_start(f, schema: str, table: str, cols: list[str]) -> None:
    f.write(f"COPY {schema}.{table} ({', '.join(cols)}) FROM STDIN;\n")


def emit_copy_end(f) -> None:
    f.write("\\.\n\n")


def emit_copies(conn: sqlite3.Connection, f, schema: str) -> int:
    """Write COPY blocks for traditions, texts, concepts, chunks, edges.
    Returns chunk count for the validation block."""
    # traditions
    emit_copy_start(f, schema, "traditions", ["id", "label", "description", "color"])
    for r in load_traditions(conn):
        f.write(f"{copy_esc(r['id'])}\t{copy_esc(r['label'])}\t\\N\t\\N\n")
    emit_copy_end(f)

    # texts
    emit_copy_start(f, schema, "texts",
                    ["id", "tradition", "label", "translator", "source_url", "sections_format"])
    for r in load_texts():
        f.write(
            f"{copy_esc(r['id'])}\t{copy_esc(r['tradition'])}\t{copy_esc(r['label'])}\t"
            f"{copy_esc(r['translator'])}\t{copy_esc(r['source_url'])}\t"
            f"{copy_esc(r['sections_format'])}\n"
        )
    emit_copy_end(f)

    # concepts
    emit_copy_start(f, schema, "concepts", ["id", "label", "domain", "definition"])
    for r in load_concepts(conn):
        f.write(
            f"{copy_esc(r['id'])}\t{copy_esc(r['label'])}\t"
            f"{copy_esc(r['domain'])}\t{copy_esc(r['definition'])}\n"
        )
    emit_copy_end(f)

    # chunks
    emit_copy_start(f, schema, "chunks",
                    ["id", "text_id", "tradition", "text_name", "section",
                     "section_path", "translator", "body", "token_count", "embedding"])
    chunks = sorted(load_chunks(conn), key=lambda r: r["id"])
    for r in chunks:
        # section_path is always None in v1 (TOMLs don't populate it).
        # When that changes, write a copy_esc_array() — esc_array() emits
        # SQL literal form with surrounding quotes, wrong for COPY.
        assert r["section_path"] is None, "section_path COPY emitter not implemented"
        # vectors are already in pgvector text format, no ::vector needed for COPY
        vector = vec_to_pg(r["vector"], EMBEDDING_DIM)
        f.write(
            f"{copy_esc(r['id'])}\t{copy_esc(r['text_id'])}\t{copy_esc(r['tradition'])}\t"
            f"{copy_esc(r['text_name'])}\t{copy_esc(r['section'])}\t"
            f"\\N\t{copy_esc(r['translator'])}\t"
            f"{copy_esc(r['body'])}\t{r['token_count']}\t{vector}\n"
        )
    emit_copy_end(f)

    # edges
    emit_copy_start(f, schema, "edges",
                    ["source", "target", "edge_type", "tier", "weight", "annotation"])
    for r in load_edges(conn):
        weight = "\\N" if r["weight"] is None else str(r["weight"])
        f.write(
            f"{copy_esc(r['source'])}\t{copy_esc(r['target'])}\t"
            f"{copy_esc(r['edge_type'])}\t{copy_esc(r['tier'])}\t"
            f"{weight}\t{copy_esc(r['annotation'])}\n"
        )
    emit_copy_end(f)

    return len(chunks)


def emit_indexes(f, schema: str) -> None:
    """Emit CREATE INDEX statements after bulk COPY."""
    f.write("-- ── post-load indexes (vector + FK lookups) ──\n")
    f.write(f"CREATE INDEX chunks_embedding_hnsw ON {schema}.chunks "
            f"USING hnsw (embedding vector_cosine_ops);\n")
    f.write(f"CREATE INDEX chunks_text_id   ON {schema}.chunks (text_id);\n")
    f.write(f"CREATE INDEX chunks_tradition ON {schema}.chunks (tradition);\n")
    f.write(f"CREATE INDEX edges_source     ON {schema}.edges (source);\n")
    f.write(f"CREATE INDEX edges_target     ON {schema}.edges (target);\n")
    f.write("\n")


def emit_validation(f, schema: str, expected_chunks: int) -> None:
    """Inline PL/pgSQL validation block. Raises on mismatch → rolls back tx."""
    f.write("-- ── inline validation ──\n")
    f.write("DO $$\n")
    f.write("DECLARE\n")
    f.write("  v_schema_version INT;\n")
    f.write(f"  v_expected_chunks INT := {expected_chunks};\n")
    f.write("  v_actual_chunks INT;\n")
    f.write("BEGIN\n")
    f.write(f"  SELECT value::int INTO v_schema_version "
            f"FROM {schema}.corpus_metadata WHERE key = 'schema_version';\n")
    f.write(f"  IF v_schema_version != {SCHEMA_VERSION} THEN\n")
    f.write("    RAISE EXCEPTION 'schema version mismatch: expected %, got %', "
            f"{SCHEMA_VERSION}, v_schema_version;\n")
    f.write("  END IF;\n")
    f.write(f"  SELECT COUNT(*) INTO v_actual_chunks FROM {schema}.chunks;\n")
    f.write("  IF v_actual_chunks != v_expected_chunks THEN\n")
    f.write("    RAISE EXCEPTION 'chunk count mismatch: expected %, got %', "
            "v_expected_chunks, v_actual_chunks;\n")
    f.write("  END IF;\n")
    f.write("END $$;\n\n")


def emit_grants(f, schema: str, role: str) -> None:
    """Emit GRANTs so the app role can read corpus.* after the swap.
    Postgres ACLs are stored against schema/table OIDs, so they survive
    ALTER SCHEMA RENAME — granting on the staging schema is sufficient."""
    f.write("-- ── grants for app role ──\n")
    f.write(f"GRANT USAGE ON SCHEMA {schema} TO {role};\n")
    f.write(f"GRANT SELECT ON ALL TABLES IN SCHEMA {schema} TO {role};\n\n")


def emit_swap(f, staging: str, live: str) -> None:
    """Atomic schema swap via ALTER SCHEMA … RENAME. Postgres has no
    `ALTER SCHEMA IF EXISTS`, so the first rename is gated on
    pg_namespace; the rest of the swap stays plain SQL. Sub-millisecond."""
    f.write("-- ── atomic schema swap ──\n")
    f.write("DO $$\n")
    f.write("BEGIN\n")
    f.write(f"  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = '{live}') THEN\n")
    f.write(f"    EXECUTE 'ALTER SCHEMA {live} RENAME TO {live}_old';\n")
    f.write("  END IF;\n")
    f.write("END $$;\n")
    f.write(f"ALTER SCHEMA {staging} RENAME TO {live};\n")
    f.write(f"DROP SCHEMA IF EXISTS {live}_old CASCADE;\n\n")


def emit_metadata(f, schema: str, version: int, commit: str, exported_at: str) -> None:
    """corpus_metadata block. Atomicity comes from the schema swap below
    — live `corpus` is untouched until the swap, so order within the
    staging schema doesn't affect what consumers see."""
    f.write(f"-- corpus_metadata\n")
    emit_copy_start(f, schema, "corpus_metadata", ["key", "value"])
    rows = [
        ("schema_version",    str(SCHEMA_VERSION)),
        ("embedding_model",   EMBEDDING_MODEL),
        ("embedding_dim",     str(EMBEDDING_DIM)),
        ("corpus_version",    str(version)),
        ("exported_at",       exported_at),
        ("source_commit_sha", commit),
    ]
    for k, v in rows:
        f.write(f"{copy_esc(k)}\t{copy_esc(v)}\n")
    emit_copy_end(f)


# ── main ──────────────────────────────────────────────────────────────

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

    n_chunks = validate(conn)
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

        # 1. Drop/create staging schema
        f.write(f"DROP SCHEMA IF EXISTS {STAGING_SCHEMA} CASCADE;\n")
        f.write(f"CREATE SCHEMA {STAGING_SCHEMA};\n\n")

        # 2. Canonical DDL (prefix table names with staging schema)
        f.write("-- ── canonical schema (schema/corpus-schema.sql) ──\n")
        ddl = prefix_ddl(SCHEMA_FILE.read_text(), STAGING_SCHEMA)
        f.write(ddl)
        f.write("\n\n")

        # 3. Data — COPY blocks in FK order
        emit_copies(conn, f, STAGING_SCHEMA)

        # 4. Post-load indexes
        emit_indexes(f, STAGING_SCHEMA)

        # 5. Metadata (last)
        emit_metadata(f, STAGING_SCHEMA, version, commit, exported_at)

        # 6. Grants — must precede the swap so they ride the ALTER SCHEMA RENAME
        emit_grants(f, STAGING_SCHEMA, APP_ROLE)

        # 7. Validation + atomic swap
        emit_validation(f, STAGING_SCHEMA, n_chunks)
        emit_swap(f, STAGING_SCHEMA, LIVE_SCHEMA)

        f.write("COMMIT;\n")

    conn.close()

    size_mb = OUTPUT.stat().st_size / (1024 * 1024)
    print(f"Exported {OUTPUT} ({size_mb:.2f} MB)")
    print(f"  corpus_version:  {version}")
    print(f"  source_commit:   {commit[:12]}")
    print(f"  embedding_model: {EMBEDDING_MODEL}")


if __name__ == "__main__":
    main()
