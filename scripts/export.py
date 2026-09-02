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
import json
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

# ── derived PARALLELS + frozen CONTRASTS (todo:6da4f965) ───────────────
# PARALLELS rows in the corpus dump come exclusively from the derived-
# parallels artifact (scripts/derive_parallels.py), not from the live
# `edges` table — see load_derived_parallels(). CONTRASTS rows come
# exclusively from a committed snapshot — see load_frozen_contrasts().
# load_edges() below now only serves the remaining live-table types
# (EXPRESSES, BELONGS_TO, DERIVES_FROM).
DERIVED_PARALLELS_CONFIG = PROJECT_ROOT / "config" / "derived_parallels.toml"
CONTRASTS_SNAPSHOT = PROJECT_ROOT / "config" / "frozen_contrasts.toml"

# ── canonical v2 pinning ──────────────────────────────────────────────
# Bump SCHEMA_VERSION when schema/corpus-schema.sql changes; guru-web's
# EXPECTED_SCHEMA_VERSION must advance in the same deploy.
SCHEMA_VERSION = 4
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


def copy_esc_array(items: list[str]) -> str:
    """Escape a Python list for a Postgres TEXT[] column under COPY:
    {"a","b"} with element-level quote/backslash escaping, then COPY-level
    escaping of the whole literal. (The chunks emitter's section_path
    comment has wanted this since v1 — v4 summary_nodes lands it.)"""
    elems = []
    for it in items:
        e = str(it).replace("\\", "\\\\").replace('"', '\\"')
        elems.append(f'"{e}"')
    return copy_esc("{" + ",".join(elems) + "}")


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
    from works import load_works, work_of
    mapping = work_of(load_works())
    for r in rows:
        r["work_id"] = mapping[r["id"]]
    rows.sort(key=lambda r: r["id"])
    return rows


def load_works_rows() -> list[dict]:
    """All 52 works (grouped + singletons) from the works layer."""
    from works import load_works
    return [{"id": w.id, "tradition": w.tradition, "label": w.label,
             "members": list(w.members), "kind": w.kind}
            for w in sorted(load_works().values(), key=lambda x: x.id)]


def load_work_dossiers(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM work_dossiers ORDER BY work_id")]


def load_summary_nodes(conn: sqlite3.Connection) -> list[dict]:
    """Live summary rows joined to their embeddings; a summary without an
    embedding is a pipeline error (run embed_summaries.py), so raise."""
    rows = [dict(r) for r in conn.execute(
        "SELECT sn.*, se.vector, se.dim AS emb_dim FROM summary_nodes sn"
        " LEFT JOIN summary_embeddings se ON se.summary_id = sn.id ORDER BY sn.id")]
    missing = [r["id"] for r in rows if r["vector"] is None]
    if missing:
        raise SystemExit(f"summary_nodes missing embeddings: {missing[:5]}"
                         f" ({len(missing)} total) — run embed_summaries.py")
    return rows


def load_concepts(conn: sqlite3.Connection) -> list[dict]:
    """Merge SQLite node rows with concepts/taxonomy.toml, enriched with the
    primary family (design.md §10.3). `definition` comes from the TOML (walked
    to any depth so the three-tier [concepts.DOMAIN.FAMILY] layout works);
    `family_id` and `domain` are derived from the DB's primary membership —
    domain is the family's parent, not the TOML section, per §10.2."""
    with open(TAXONOMY_TOML, "rb") as fp:
        tax = tomllib.load(fp)
    defn_by_cid: dict[str, str] = {}

    def _walk(node: dict) -> None:
        for k, v in node.items():
            if isinstance(v, dict):
                _walk(v)
            elif isinstance(v, str):
                defn_by_cid[k] = v

    _walk(tax.get("concepts", {}))

    # primary family + its domain (parent) per concept node
    fam_by_node: dict[str, tuple[str, str]] = {}
    for node_id, family_id, domain in conn.execute(
        """SELECT m.concept_id, m.family_id, f.parent_id
             FROM concept_family_membership m
             JOIN concept_families f ON f.id = m.family_id
            WHERE m.is_primary = 1"""
    ):
        fam_by_node[node_id] = (family_id, domain)

    rows = []
    for node_id, label in conn.execute(
        "SELECT id, label FROM nodes WHERE type='concept' ORDER BY id"
    ):
        short = node_id.removeprefix("concept.")
        family_id, domain = fam_by_node.get(node_id, (None, None))
        rows.append({
            "id": node_id,
            "label": label,
            "domain": domain,
            "definition": defn_by_cid.get(short),
            "family_id": family_id,
        })
    return rows


def load_families(conn: sqlite3.Connection) -> list[dict]:
    """concept_families rows — domains (parent NULL) ordered before families so
    the self-referential FK is satisfied during a row-by-row COPY."""
    rows = []
    for r in conn.execute(
        "SELECT id, parent_id, label, definition FROM concept_families "
        "ORDER BY (parent_id IS NOT NULL), id"
    ):
        rows.append({"id": r[0], "parent_id": r[1], "label": r[2], "definition": r[3]})
    return rows


def load_concept_family_membership(conn: sqlite3.Connection) -> list[dict]:
    """Membership rows; SQLite 0/1 is_primary → Postgres BOOLEAN at emit time."""
    rows = []
    for r in conn.execute(
        "SELECT concept_id, family_id, is_primary FROM concept_family_membership "
        "ORDER BY concept_id, family_id"
    ):
        rows.append({"concept_id": r[0], "family_id": r[1], "is_primary": bool(r[2])})
    return rows


def load_concept_aliases(conn: sqlite3.Connection) -> list[dict]:
    rows = []
    for r in conn.execute(
        "SELECT concept_id, alias FROM concept_aliases ORDER BY concept_id, alias"
    ):
        rows.append({"concept_id": r[0], "alias": r[1]})
    return rows


def load_family_aliases(conn: sqlite3.Connection) -> list[dict]:
    rows = []
    for r in conn.execute(
        "SELECT family_id, alias FROM family_aliases ORDER BY family_id, alias"
    ):
        rows.append({"family_id": r[0], "alias": r[1]})
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
    """SQLite edges → Postgres column names, for every type EXCEPT the two
    with their own dedicated source (todo:6da4f965): PARALLELS comes from
    the derived-parallels artifact (load_derived_parallels) and CONTRASTS
    from the frozen snapshot (load_frozen_contrasts). Live rows of those
    two types (if any linger in guru.db, e.g. pre-freeze CONTRASTS or
    staged-edge-promoted PARALLELS) are deliberately NOT read here.

    EXPRESSES weight (todo:f6af90e8, owner decision 2026-08-21): the accepted
    staged_tags score (an INTEGER 1-3 — the tagging model's own strength
    rating, kept through review) rides along as `weight`, MAX over accepted
    rows when several models proposed the same pair. Coverage is deliberately
    partial: rows with no surviving accepted staged row — chiefly the
    Apr-May 2026 auto-promote residue — keep weight NULL, and no consumer may
    treat NULL as 0. This is persistence, not ranking: the retriever half of
    guru-web todo:9f401f76 stays eval-gated (the graph leg held ~1% of top-K
    in the 2026-08-21 golden A/B). Other types (BELONGS_TO) stay NULL."""
    rows = []
    for r in conn.execute(
        "SELECT e.source_id, e.target_id, e.type, e.tier, e.justification, "
        "       CASE WHEN e.type = 'EXPRESSES' THEN "
        "         (SELECT MAX(st.score) FROM staged_tags st "
        "           WHERE st.status = 'accepted' "
        "             AND st.chunk_id = e.source_id "
        "             AND 'concept.' || st.concept_id = e.target_id) "
        "       END AS weight "
        "FROM edges e "
        "WHERE e.type NOT IN ('PARALLELS', 'CONTRASTS') "
        "ORDER BY e.source_id, e.target_id, e.type"
    ):
        rows.append({
            "source": r[0],
            "target": r[1],
            "edge_type": r[2],
            "tier": r[3],
            "weight": float(r[5]) if r[5] is not None else None,
            "annotation": r[4],
        })
    return rows


def load_derived_parallels(
    conn: sqlite3.Connection,
    config_path: Path = DERIVED_PARALLELS_CONFIG,
    *,
    chunk_ids: set[str] | None = None,
) -> list[dict]:
    """The sole source of PARALLELS rows in the corpus dump (todo:6da4f965).

    Reads the latest run from guru.db's derived_runs/derived_parallels
    tables (todo:675a76f8 — the JSONL run-directory artifact is retired)
    and refuses to proceed — loudly, via SystemExit — if no run exists,
    the latest run is PARTIAL (--limit-concepts; the old artifact let a
    smoke run silently become the next export's source, this guard is why
    the trap is gone), the run is older than config[export].max_age_days,
    or it contains zero rows. Silence here would mean a bad export quietly
    ships zero PARALLELS instead of failing the build.

    If `chunk_ids` is given (main() always passes the set of chunk ids this
    run is about to emit), every row's source/target is checked against it
    and any orphan endpoint is a SystemExit — a re-chunk can shift chunk ids
    out from under a derived run that was generated against the old set, and
    an orphan row would otherwise load into Postgres silently (untyped TEXT
    columns, no FK) and just never match at query time.
    """
    if not config_path.exists():
        raise SystemExit(f"derived-parallels config not found: {config_path}")
    with open(config_path, "rb") as fp:
        cfg = tomllib.load(fp)
    export_cfg = cfg.get("export")
    if not export_cfg:
        raise SystemExit(
            f"{config_path} has no [export] section (max_age_days)"
        )
    max_age_days = float(export_cfg["max_age_days"])

    have = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name IN ('derived_runs', 'derived_parallels')")}
    if have != {"derived_runs", "derived_parallels"}:
        raise SystemExit(
            "guru.db has no derived-parallels tables. Apply "
            "scripts/migrations/v3_012_derived_parallels.sql, then run "
            "scripts/derive_parallels.py."
        )
    latest = conn.execute(
        "SELECT run_id, generated_at, limit_concepts, edge_rows "
        "FROM derived_runs ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    if latest is None:
        raise SystemExit(
            "No derived-parallels run in guru.db. "
            "Run scripts/derive_parallels.py first."
        )
    run_id, generated_at_s, limit_concepts, _edge_rows = latest
    if limit_concepts is not None:
        raise SystemExit(
            f"Latest derived-parallels run (run_id {run_id}) is PARTIAL "
            f"(--limit-concepts {limit_concepts}) — a smoke run, not an "
            f"exportable graph. Run scripts/derive_parallels.py without "
            f"--limit-concepts."
        )
    generated_at = datetime.fromisoformat(generated_at_s)
    age_days = (datetime.now(timezone.utc) - generated_at).total_seconds() / 86400
    if age_days > max_age_days:
        raise SystemExit(
            f"Derived-parallels run {run_id} is stale: generated "
            f"{age_days:.1f} days ago, max_age_days={max_age_days}. "
            f"Re-run scripts/derive_parallels.py."
        )

    rows = [
        {
            "source": r[0],
            "target": r[1],
            "edge_type": "PARALLELS",
            "tier": "inferred",
            "weight": r[2],
            "annotation": r[3],
        }
        for r in conn.execute(
            "SELECT source, target, weight, annotation FROM derived_parallels "
            "WHERE run_id = ? ORDER BY source, target",
            (run_id,),
        )
    ]

    if not rows:
        raise SystemExit(
            f"Derived-parallels run {run_id} contains zero PARALLELS "
            f"rows — refusing to export an empty PARALLELS set. If this is "
            f"genuinely expected, delete this check, don't work around it."
        )

    if chunk_ids is not None:
        orphans = sorted({
            cid for row in rows for cid in (row["source"], row["target"])
            if cid not in chunk_ids
        })
        if orphans:
            raise SystemExit(
                f"derived_parallels run {run_id}: {len(orphans)} PARALLELS "
                f"endpoint(s) do not resolve to a chunk in this export "
                f"(re-chunk drift?): {orphans[:5]}"
                f"{' ...' if len(orphans) > 5 else ''}. Re-run "
                f"scripts/derive_parallels.py against the current corpus."
            )

    logger.info(
        "derived PARALLELS: %d rows from guru.db run %d (generated %.1f days ago)",
        len(rows), run_id, age_days,
    )
    return rows


def load_frozen_contrasts(
    path: Path = CONTRASTS_SNAPSHOT,
    *,
    chunk_ids: set[str] | None = None,
) -> list[dict]:
    """The sole source of CONTRASTS rows in the corpus dump (todo:6da4f965):
    a committed snapshot, carried through export unchanged. Editing the
    live `edges` table's CONTRASTS rows after the freeze has no effect on
    what ships — see the header comment in config/frozen_contrasts.toml for
    how to retire the freeze.

    If `chunk_ids` is given, every row's source/target is checked against
    it and any orphan endpoint is a SystemExit. This snapshot is the one
    source that cannot self-heal after a re-chunk — CONTRASTS rows here are
    never regenerated, so a shifted chunk id would otherwise ship a row that
    quietly never matches in production (see PR #64 review finding 2)."""
    if not path.exists():
        raise SystemExit(f"Frozen CONTRASTS snapshot not found: {path}")
    with open(path, "rb") as fp:
        data = tomllib.load(fp)
    rows = data.get("edge", [])
    if not rows:
        raise SystemExit(f"{path} has no [[edge]] entries")
    out = []
    for i, row in enumerate(rows):
        for key in ("source", "target", "edge_type", "tier"):
            if key not in row:
                raise SystemExit(f"{path} entry {i} missing '{key}'")
        if row["edge_type"] != "CONTRASTS":
            raise SystemExit(
                f"{path} entry {i} has edge_type={row['edge_type']!r}, "
                f"expected 'CONTRASTS'"
            )
        out.append({
            "source": row["source"],
            "target": row["target"],
            "edge_type": row["edge_type"],
            "tier": row["tier"],
            "weight": row.get("weight"),
            "annotation": row.get("annotation"),
        })

    if chunk_ids is not None:
        orphans = sorted({
            cid for row in out for cid in (row["source"], row["target"])
            if cid not in chunk_ids
        })
        if orphans:
            raise SystemExit(
                f"{path}: {len(orphans)} CONTRASTS endpoint(s) do not "
                f"resolve to a chunk in this export (re-chunk drift?): "
                f"{orphans[:5]}{' ...' if len(orphans) > 5 else ''}. This "
                f"snapshot cannot self-heal — update the affected rows in "
                f"{path} to the current chunk ids."
            )

    logger.info("frozen CONTRASTS: %d rows from %s", len(out), path)
    return out


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
        line = re.sub(
            r"(ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?)(\w+)",
            rf"\1{schema}.\2",
            line,
        )
        line = re.sub(
            r"(COMMENT\s+ON\s+COLUMN\s+)(\w+)(\.\w+)",
            rf"\1{schema}.\2\3",
            line,
        )
        out.append(line)
    return "\n".join(out)


# ── emitters (COPY FORMAT) ────────────────────────────────────────────

def emit_copy_start(f, schema: str, table: str, cols: list[str]) -> None:
    f.write(f"COPY {schema}.{table} ({', '.join(cols)}) FROM STDIN;\n")


def emit_copy_end(f) -> None:
    f.write("\\.\n\n")


def emit_copies(
    conn: sqlite3.Connection,
    f,
    schema: str,
    chunks: list[dict],
    derived_parallels_rows: list[dict],
    frozen_contrasts_rows: list[dict],
) -> dict:
    """Write COPY blocks for traditions, texts, concepts, chunks, edges.

    `chunks`, `derived_parallels_rows`, and `frozen_contrasts_rows` are
    loaded by main() *before* this is called (PR #64 review finding 1) —
    this function does no loading of its own for those three, only assembly
    and emission. That hoist is what makes the two PARALLELS/CONTRASTS
    artifact loaders' SystemExit guards fail-fast: they used to run from
    inside here, which main() only reaches after next_corpus_version() has
    already committed a version bump and after OUTPUT has already been
    truncated by gzip.open() — so a guard tripping mid-emit_copies burned a
    version number and destroyed the last good dump on the way out.

    Returns per-table counts for the validation block."""
    # traditions
    emit_copy_start(f, schema, "traditions", ["id", "label", "description", "color"])
    for r in load_traditions(conn):
        f.write(f"{copy_esc(r['id'])}\t{copy_esc(r['label'])}\t\\N\t\\N\n")
    emit_copy_end(f)

    # works — before texts (texts.work_id FK)
    emit_copy_start(f, schema, "works", ["id", "tradition", "label", "member_text_ids", "kind"])
    for r in load_works_rows():
        f.write(f"{copy_esc(r['id'])}\t{copy_esc(r['tradition'])}\t"
                f"{copy_esc(r['label'])}\t{copy_esc_array(r['members'])}\t{copy_esc(r['kind'])}\n")
    emit_copy_end(f)

    # texts
    emit_copy_start(f, schema, "texts",
                    ["id", "tradition", "label", "translator", "source_url", "sections_format", "work_id"])
    for r in load_texts():
        f.write(
            f"{copy_esc(r['id'])}\t{copy_esc(r['tradition'])}\t{copy_esc(r['label'])}\t"
            f"{copy_esc(r['translator'])}\t{copy_esc(r['source_url'])}\t"
            f"{copy_esc(r['sections_format'])}\t{copy_esc(r['work_id'])}\n"
        )
    emit_copy_end(f)

    # concept_families — before concepts (concepts.family_id FK) and before
    # membership/aliases. Domains (parent NULL) are ordered first by the loader
    # so the self-referential parent_id FK holds row-by-row during COPY.
    emit_copy_start(f, schema, "concept_families", ["id", "parent_id", "label", "definition"])
    for r in load_families(conn):
        f.write(
            f"{copy_esc(r['id'])}\t{copy_esc(r['parent_id'])}\t"
            f"{copy_esc(r['label'])}\t{copy_esc(r['definition'])}\n"
        )
    emit_copy_end(f)

    # concepts (now carrying the denormalised primary family_id)
    emit_copy_start(f, schema, "concepts", ["id", "label", "domain", "definition", "family_id"])
    for r in load_concepts(conn):
        f.write(
            f"{copy_esc(r['id'])}\t{copy_esc(r['label'])}\t"
            f"{copy_esc(r['domain'])}\t{copy_esc(r['definition'])}\t"
            f"{copy_esc(r['family_id'])}\n"
        )
    emit_copy_end(f)

    # concept_family_membership — after concepts + concept_families. 0/1 → t/f.
    emit_copy_start(f, schema, "concept_family_membership", ["concept_id", "family_id", "is_primary"])
    for r in load_concept_family_membership(conn):
        f.write(
            f"{copy_esc(r['concept_id'])}\t{copy_esc(r['family_id'])}\t"
            f"{'t' if r['is_primary'] else 'f'}\n"
        )
    emit_copy_end(f)

    # concept_aliases (empty in v1 until aliases are populated)
    emit_copy_start(f, schema, "concept_aliases", ["concept_id", "alias"])
    for r in load_concept_aliases(conn):
        f.write(f"{copy_esc(r['concept_id'])}\t{copy_esc(r['alias'])}\n")
    emit_copy_end(f)

    # family_aliases (same shape; empty in v1)
    emit_copy_start(f, schema, "family_aliases", ["family_id", "alias"])
    for r in load_family_aliases(conn):
        f.write(f"{copy_esc(r['family_id'])}\t{copy_esc(r['alias'])}\n")
    emit_copy_end(f)

    # chunks
    emit_copy_start(f, schema, "chunks",
                    ["id", "text_id", "tradition", "text_name", "section",
                     "section_path", "translator", "body", "token_count", "embedding"])
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

    # edges — PARALLELS from the derived-parallels artifact and CONTRASTS
    # from the frozen snapshot (todo:6da4f965), everything else from the
    # live table. Sorted for a deterministic COPY block, matching the old
    # single-source ORDER BY. Both artifact loads already happened in
    # main() before this function was ever called — see the docstring above.
    edges = (
        load_edges(conn) + derived_parallels_rows + frozen_contrasts_rows
    )
    edges.sort(key=lambda r: (r["source"], r["target"], r["edge_type"]))
    emit_copy_start(f, schema, "edges",
                    ["source", "target", "edge_type", "tier", "weight", "annotation"])
    for r in edges:
        weight = "\\N" if r["weight"] is None else str(r["weight"])
        f.write(
            f"{copy_esc(r['source'])}\t{copy_esc(r['target'])}\t"
            f"{copy_esc(r['edge_type'])}\t{copy_esc(r['tier'])}\t"
            f"{weight}\t{copy_esc(r['annotation'])}\n"
        )
    emit_copy_end(f)

    # work_dossiers — after works (FK). JSON TEXT columns pass through
    # copy_esc unchanged: valid JSON text is valid JSONB input under COPY.
    dossiers = load_work_dossiers(conn)
    emit_copy_start(f, schema, "work_dossiers",
                    ["work_id", "summary", "context", "structure", "key_figures",
                     "key_terms", "themes", "reading_notes", "manifest_notes", "generated_by"])
    for r in dossiers:
        f.write(
            f"{copy_esc(r['work_id'])}\t{copy_esc(r['summary'])}\t{copy_esc(r['context'])}\t"
            f"{copy_esc(r['structure_json'])}\t{copy_esc(r['key_figures_json'])}\t"
            f"{copy_esc(r['key_terms_json'])}\t{copy_esc(r['themes_json'])}\t"
            f"{copy_esc(r['reading_notes'])}\t{copy_esc(r['manifest_notes'])}\t"
            f"{copy_esc(r['generated_by'])}\n"
        )
    emit_copy_end(f)

    # summary_nodes — after chunks (logical child integrity) + works + texts.
    summaries = load_summary_nodes(conn)
    emit_copy_start(f, schema, "summary_nodes",
                    ["id", "work_id", "text_id", "tradition", "level", "section_span",
                     "child_chunk_ids", "body", "token_count", "embedding"])
    for r in summaries:
        vector = vec_to_pg(r["vector"], EMBEDDING_DIM)   # same 768-dim guard as chunks
        f.write(
            f"{copy_esc(r['id'])}\t{copy_esc(r['work_id'])}\t{copy_esc(r['text_id'])}\t"
            f"{copy_esc(r['tradition'])}\t{r['level']}\t{copy_esc(r['section_span'])}\t"
            f"{copy_esc_array(json.loads(r['child_chunk_ids']))}\t"
            f"{copy_esc(r['body'])}\t{r['token_count']}\t{vector}\n"
        )
    emit_copy_end(f)

    return {"chunks": len(chunks), "works": len(load_works_rows()),
            "dossiers": len(dossiers), "summaries": len(summaries)}


def emit_indexes(f, schema: str) -> None:
    """Emit CREATE INDEX statements after bulk COPY."""
    f.write("-- ── post-load indexes (vector + FK lookups) ──\n")
    f.write(f"CREATE INDEX chunks_embedding_hnsw ON {schema}.chunks "
            f"USING hnsw (embedding vector_cosine_ops);\n")
    f.write(f"CREATE INDEX chunks_text_id   ON {schema}.chunks (text_id);\n")
    f.write(f"CREATE INDEX chunks_tradition ON {schema}.chunks (tradition);\n")
    f.write(f"CREATE INDEX edges_source     ON {schema}.edges (source);\n")
    f.write(f"CREATE INDEX edges_target     ON {schema}.edges (target);\n")
    # concept-hierarchy indexes (kept here, not in corpus-schema.sql, per the
    # schema header rule that all indexes are built post-bulk-load).
    f.write(f"CREATE INDEX idx_concept_families_parent ON {schema}.concept_families (parent_id);\n")
    f.write(f"CREATE UNIQUE INDEX idx_concept_primary_family ON {schema}.concept_family_membership (concept_id) WHERE is_primary;\n")
    f.write(f"CREATE INDEX idx_concept_family_membership_family ON {schema}.concept_family_membership (family_id);\n")
    f.write(f"CREATE INDEX idx_concept_aliases_alias ON {schema}.concept_aliases (alias);\n")
    f.write(f"CREATE INDEX idx_family_aliases_alias ON {schema}.family_aliases (alias);\n")
    # v4 document-knowledge indexes
    f.write(f"CREATE INDEX summary_nodes_embedding_hnsw ON {schema}.summary_nodes "
            f"USING hnsw (embedding vector_cosine_ops);\n")
    f.write(f"CREATE INDEX summary_nodes_text_id ON {schema}.summary_nodes (text_id);\n")
    f.write(f"CREATE INDEX summary_nodes_work_id ON {schema}.summary_nodes (work_id);\n")
    f.write(f"CREATE INDEX texts_work_id ON {schema}.texts (work_id);\n")
    f.write("\n")


def emit_validation(f, schema: str, counts: dict) -> None:
    """Inline PL/pgSQL validation block. Raises on mismatch → rolls back tx.
    v4 (§3.3): row counts for works/work_dossiers/summary_nodes, every
    summary child chunk id resolves, exactly one L2 per dossiered work.
    Dossier COVERAGE is reported, never enforced."""
    expected_chunks = counts["chunks"]
    f.write("-- ── inline validation ──\n")
    f.write("DO $$\n")
    f.write("DECLARE\n")
    f.write("  v_schema_version INT;\n")
    f.write(f"  v_expected_chunks INT := {expected_chunks};\n")
    f.write("  v_actual_chunks INT;\n")
    f.write("  v_n INT;\n")
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
    for table, key in (("works", "works"), ("work_dossiers", "dossiers"),
                       ("summary_nodes", "summaries")):
        f.write(f"  SELECT COUNT(*) INTO v_n FROM {schema}.{table};\n")
        f.write(f"  IF v_n != {counts[key]} THEN\n")
        f.write(f"    RAISE EXCEPTION '{table} count mismatch: expected "
                f"{counts[key]}, got %', v_n;\n")
        f.write("  END IF;\n")
    # every summary child chunk id resolves against emitted chunks
    f.write(f"  SELECT COUNT(*) INTO v_n FROM (SELECT unnest(child_chunk_ids) AS cid "
            f"FROM {schema}.summary_nodes) x LEFT JOIN {schema}.chunks c ON c.id = x.cid "
            f"WHERE c.id IS NULL;\n")
    f.write("  IF v_n != 0 THEN\n")
    f.write("    RAISE EXCEPTION 'summary_nodes reference % unknown chunk ids', v_n;\n")
    f.write("  END IF;\n")
    # every dossiered work has exactly one level-2 summary
    f.write(f"  SELECT COUNT(*) INTO v_n FROM {schema}.work_dossiers d WHERE "
            f"(SELECT COUNT(*) FROM {schema}.summary_nodes s WHERE s.work_id = d.work_id "
            f"AND s.level = 2) != 1;\n")
    f.write("  IF v_n != 0 THEN\n")
    f.write("    RAISE EXCEPTION '% dossiered works lack exactly one L2 summary', v_n;\n")
    f.write("  END IF;\n")
    # coverage is optional per work — report, never fail (§3.3)
    f.write(f"  SELECT COUNT(*) INTO v_n FROM {schema}.work_dossiers;\n")
    n_works = counts["works"]
    f.write(f"  RAISE NOTICE 'dossier coverage: % of {n_works} works', v_n;\n")
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


def _dossier_model() -> str | None:
    cfg_path = PROJECT_ROOT / "config" / "dossiers.toml"
    if not cfg_path.exists():
        return None
    return tomllib.load(open(cfg_path, "rb"))["campaign"].get("model")


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
    if (dm := _dossier_model()):
        rows.append(("dossier_model", dm))
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

    # Load the chunk set and both PARALLELS/CONTRASTS sources BEFORE
    # anything is mutated (PR #64 review findings 1 + 2). load_derived_
    # parallels() and load_frozen_contrasts() are pure validation — they
    # touch neither `conn` nor the output file — so their SystemExit guards
    # (missing/stale/empty artifact, orphan endpoints) must all fire here,
    # before next_corpus_version() commits a version bump and before
    # gzip.open(OUTPUT, "wt") truncates the last good dump. The chunk id
    # set doubles as the orphan-endpoint check both loaders run against.
    chunks = sorted(load_chunks(conn), key=lambda r: r["id"])
    chunk_ids = {r["id"] for r in chunks}
    derived_parallels_rows = load_derived_parallels(conn, chunk_ids=chunk_ids)
    frozen_contrasts_rows = load_frozen_contrasts(chunk_ids=chunk_ids)

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
        counts = emit_copies(conn, f, STAGING_SCHEMA, chunks,
                             derived_parallels_rows, frozen_contrasts_rows)

        # 4. Post-load indexes
        emit_indexes(f, STAGING_SCHEMA)

        # 5. Metadata (last)
        emit_metadata(f, STAGING_SCHEMA, version, commit, exported_at)

        # 6. Grants — must precede the swap so they ride the ALTER SCHEMA RENAME
        emit_grants(f, STAGING_SCHEMA, APP_ROLE)

        # 7. Validation + atomic swap
        counts["chunks"] = n_chunks  # pre-export validate() is authoritative
        emit_validation(f, STAGING_SCHEMA, counts)
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
