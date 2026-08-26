#!/usr/bin/env python3
"""todo:4ea3dcc5 — move blavatsky-sd from western_esoteric to theosophy.

USER DECISION (2026-08-26): The Secret Doctrine is the theosophical root;
Steiner's Occult Science should land in the same tradition later. Chunk ids
embed the tradition prefix, so this is a rewrite, not a metadata-only flip.

OLD_PREFIX = western_esoteric.blavatsky-sd.
NEW_PREFIX = theosophy.blavatsky-sd.

Default is --dry-run. Do NOT --apply against the shared gitignored
data/guru.db while the blavatsky-sd dossier stream is in flight. Park the
stream first; never race generation. Never run scripts/backup_db.sh against
the live shared DB from a worktree unless the operator explicitly intends
that. Tests use in-memory / tmp sqlite only.

Failure modes (worth reading twice before --apply):

  * JSON child_chunk_ids / structure_json.chunk_ids MUST be rewritten
    elementwise after json.loads — a naive string replace on the column
    would smash justification text that merely *mentions* the prefix, and
    can corrupt JSON list structure. Same walk as mabinogion_023_shift.py.
  * BELONGS_TO retarget is scoped to blavatsky-sd chunks only. Other
    western_esoteric texts keep their BELONGS_TO → western_esoteric.
  * nodes.id has no ON UPDATE CASCADE. Disable PRAGMA foreign_keys around
    the rewrite (v3_004 pattern); PRAGMA foreign_key_check after.
  * Collision: abort if any theosophy.blavatsky-sd.* node already exists
    while old-prefix rows remain (half-applied / mixed state).
  * Idempotent: if already swapped (no old-prefix chunk nodes, new-prefix
    present), second apply is a clean no-op success.
  * Optional tables (staged_tags, staged_edges, staged_cleanups,
    staged_concepts, edge_progress, staged_summaries, summary_nodes,
    work_dossiers) are probed via sqlite_master — fixtures need not have
    every table.
  * nodes.metadata_json.text_id stays 'blavatsky-sd'.
  * Never rewrite other western_esoteric.* texts.

Tracked source changes (this PR, not this script):
  sources/manifest.toml tradition, chunking/theosophy/blavatsky-sd.toml.
Corpus TOMLs may be untracked on feat/blavatsky — use --rewrite-corpus
(also defaults to dry-run) rather than git-adding 727 large files.

Usage:
    python3 scripts/migrations/theosophy_blavatsky_sd_tradition_swap.py
    python3 scripts/migrations/theosophy_blavatsky_sd_tradition_swap.py --db PATH --apply
    python3 scripts/migrations/theosophy_blavatsky_sd_tradition_swap.py --rewrite-corpus
    python3 scripts/migrations/theosophy_blavatsky_sd_tradition_swap.py --rewrite-corpus --apply
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from guru.paths import CORPUS_DIR, DEFAULT_DB  # noqa: E402

OLD_TRADITION = "western_esoteric"
NEW_TRADITION = "theosophy"
TEXT_ID = "blavatsky-sd"
OLD_PREFIX = f"{OLD_TRADITION}.{TEXT_ID}."
NEW_PREFIX = f"{NEW_TRADITION}.{TEXT_ID}."
OLD_GLOB = f"{OLD_PREFIX}%"
NEW_GLOB = f"{NEW_PREFIX}%"

# Chunk-id columns that exist on some DBs and not others.
OPTIONAL_ID_COLUMNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("chunk_embeddings", ("chunk_id",)),
    ("tagging_progress", ("chunk_id",)),
    ("staged_tags", ("chunk_id",)),
    ("staged_edges", ("source_chunk", "target_chunk")),
    ("staged_cleanups", ("chunk_id",)),
    ("staged_concepts", ("motivating_chunk",)),
    ("edge_progress", ("chunk_id",)),
)


class MigrationAbort(RuntimeError):
    """Guard failed; caller rolls back."""


def remap_chunk_id(value: str | None) -> str | None:
    """Rewrite a single chunk id; leave unrelated strings (and None) alone."""
    if value is None:
        return None
    if value.startswith(OLD_PREFIX):
        return NEW_PREFIX + value[len(OLD_PREFIX):]
    return value


def remap_json_value(value: Any) -> Any:
    """Walk JSON, rewriting only exact-string chunk ids (not substrings)."""
    if isinstance(value, str):
        return remap_chunk_id(value)
    if isinstance(value, list):
        return [remap_json_value(item) for item in value]
    if isinstance(value, dict):
        return {k: remap_json_value(v) for k, v in value.items()}
    return value


def remap_json_column(raw: str | None) -> str | None:
    if raw is None:
        return None
    return json.dumps(remap_json_value(json.loads(raw)), separators=(",", ":"))


def _tables(con: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in con.execute(f"PRAGMA table_info({table})")}


def _count(con: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    return int(con.execute(sql, params).fetchone()[0])


def _like_count(con: sqlite3.Connection, table: str, column: str, glob: str) -> int:
    return _count(
        con,
        f"SELECT COUNT(*) FROM {table} WHERE {column} LIKE ?",
        (glob,),
    )


def audit_counts(con: sqlite3.Connection) -> dict[str, int]:
    tables = _tables(con)
    counts: dict[str, int] = {}
    if "nodes" in tables:
        counts["nodes_old"] = _count(
            con,
            "SELECT COUNT(*) FROM nodes WHERE type='chunk' AND id LIKE ?",
            (OLD_GLOB,),
        )
        counts["nodes_new"] = _count(
            con,
            "SELECT COUNT(*) FROM nodes WHERE type='chunk' AND id LIKE ?",
            (NEW_GLOB,),
        )
        counts["other_western"] = _count(
            con,
            "SELECT COUNT(*) FROM nodes WHERE type='chunk' AND id LIKE ? "
            "AND id NOT LIKE ?",
            (f"{OLD_TRADITION}.%", OLD_GLOB),
        )
    if "edges" in tables:
        counts["edges_src_old"] = _like_count(con, "edges", "source_id", OLD_GLOB)
        counts["edges_tgt_old"] = _like_count(con, "edges", "target_id", OLD_GLOB)
        counts["edges_src_new"] = _like_count(con, "edges", "source_id", NEW_GLOB)
        counts["edges_tgt_new"] = _like_count(con, "edges", "target_id", NEW_GLOB)
        counts["belongs_old_tradition"] = _count(
            con,
            "SELECT COUNT(*) FROM edges WHERE type='BELONGS_TO' "
            "AND source_id LIKE ? AND target_id=?",
            (OLD_GLOB, OLD_TRADITION),
        )
        counts["belongs_new_tradition"] = _count(
            con,
            "SELECT COUNT(*) FROM edges WHERE type='BELONGS_TO' "
            "AND source_id LIKE ? AND target_id=?",
            (NEW_GLOB, NEW_TRADITION),
        )
    for table, columns in OPTIONAL_ID_COLUMNS:
        if table not in tables:
            continue
        present = _columns(con, table)
        for col in columns:
            if col not in present:
                continue
            counts[f"{table}.{col}_old"] = _like_count(con, table, col, OLD_GLOB)
            counts[f"{table}.{col}_new"] = _like_count(con, table, col, NEW_GLOB)
    return counts


def _print_audit(label: str, counts: dict[str, int]) -> None:
    print(f"== {label} ==")
    for key, value in counts.items():
        print(f"  {key}: {value}")


def ensure_theosophy_node(con: sqlite3.Connection) -> bool:
    """Insert tradition node `theosophy` if missing. Returns True if created."""
    row = con.execute(
        "SELECT id FROM nodes WHERE id=?", (NEW_TRADITION,)
    ).fetchone()
    if row is not None:
        return False
    cols = _columns(con, "nodes")
    label = NEW_TRADITION.replace("_", " ").title()
    fields = ["id", "type", "label"]
    values: list[Any] = [NEW_TRADITION, "tradition", label]
    if "tradition_id" in cols:
        fields.append("tradition_id")
        values.append(None)
    if "metadata_json" in cols:
        fields.append("metadata_json")
        values.append("{}")
    placeholders = ", ".join("?" for _ in fields)
    con.execute(
        f"INSERT INTO nodes({', '.join(fields)}) VALUES({placeholders})",
        values,
    )
    return True


def collision_ids(con: sqlite3.Connection) -> list[str]:
    rows = con.execute(
        "SELECT id FROM nodes WHERE type='chunk' AND id LIKE ?",
        (NEW_GLOB,),
    ).fetchall()
    return [r[0] for r in rows]


def _rewrite_column(
    con: sqlite3.Connection, table: str, column: str
) -> int:
    """Prefix-swap one TEXT column. Returns rows rewritten."""
    rows = con.execute(
        f"SELECT rowid, {column} FROM {table} WHERE {column} LIKE ?",
        (OLD_GLOB,),
    ).fetchall()
    for rowid, value in rows:
        new = remap_chunk_id(value)
        if new == value:
            continue
        con.execute(
            f"UPDATE {table} SET {column}=? WHERE rowid=?",
            (new, rowid),
        )
    return len(rows)


def _rewrite_json_child_ids(
    con: sqlite3.Connection, table: str, pk: str, column: str
) -> int:
    if table not in _tables(con):
        return 0
    cols = _columns(con, table)
    if column not in cols or pk not in cols:
        return 0
    rows = con.execute(
        f"SELECT {pk}, {column} FROM {table} WHERE {column} LIKE ?",
        (f"%{OLD_PREFIX}%",),
    ).fetchall()
    n = 0
    for key, raw in rows:
        if raw is None:
            continue
        rewritten = remap_json_column(raw)
        if rewritten != raw:
            con.execute(
                f"UPDATE {table} SET {column}=? WHERE {pk}=?",
                (rewritten, key),
            )
            n += 1
    return n


def _rewrite_work_dossiers(con: sqlite3.Connection) -> int:
    if "work_dossiers" not in _tables(con):
        return 0
    rows = con.execute(
        "SELECT work_id, structure_json FROM work_dossiers "
        "WHERE structure_json LIKE ?",
        (f"%{OLD_PREFIX}%",),
    ).fetchall()
    n = 0
    for work_id, raw in rows:
        structure = json.loads(raw)
        rewritten = remap_json_value(structure)
        dumped = json.dumps(rewritten, separators=(",", ":"))
        if dumped != json.dumps(structure, separators=(",", ":")):
            con.execute(
                "UPDATE work_dossiers SET structure_json=? WHERE work_id=?",
                (dumped, work_id),
            )
            n += 1
    return n


def apply_swap(con: sqlite3.Connection) -> dict[str, Any]:
    """Run the rewrite inside an already-open connection (FK off)."""
    tables = _tables(con)
    if "nodes" not in tables or "edges" not in tables:
        raise MigrationAbort("nodes/edges tables required")

    old_chunks = _count(
        con,
        "SELECT COUNT(*) FROM nodes WHERE type='chunk' AND id LIKE ?",
        (OLD_GLOB,),
    )
    new_chunks = _count(
        con,
        "SELECT COUNT(*) FROM nodes WHERE type='chunk' AND id LIKE ?",
        (NEW_GLOB,),
    )
    if old_chunks == 0 and new_chunks > 0:
        return {"status": "already_swapped", "old_chunks": 0, "new_chunks": new_chunks}
    if old_chunks == 0 and new_chunks == 0:
        return {"status": "nothing_to_do", "old_chunks": 0, "new_chunks": 0}

    collisions = collision_ids(con)
    if collisions:
        raise MigrationAbort(
            f"collision: {len(collisions)} existing {NEW_PREFIX}* node(s) "
            f"(e.g. {collisions[0]})"
        )

    before = audit_counts(con)
    created = ensure_theosophy_node(con)

    # Chunk nodes: id + tradition_id. metadata_json.text_id is left alone.
    node_rows = con.execute(
        "SELECT id, tradition_id FROM nodes WHERE type='chunk' AND id LIKE ?",
        (OLD_GLOB,),
    ).fetchall()
    for old_id, tradition_id in node_rows:
        new_id = remap_chunk_id(old_id)
        new_trad = NEW_TRADITION if tradition_id == OLD_TRADITION else tradition_id
        con.execute(
            "UPDATE nodes SET id=?, tradition_id=? WHERE id=?",
            (new_id, new_trad, old_id),
        )

    # Edges: rewrite endpoints, then retarget BELONGS_TO for these chunks only.
    _rewrite_column(con, "edges", "source_id")
    _rewrite_column(con, "edges", "target_id")
    con.execute(
        "UPDATE edges SET target_id=? WHERE type='BELONGS_TO' "
        "AND source_id LIKE ? AND target_id=?",
        (NEW_TRADITION, NEW_GLOB, OLD_TRADITION),
    )

    for table, columns in OPTIONAL_ID_COLUMNS:
        if table not in tables:
            continue
        present = _columns(con, table)
        for col in columns:
            if col in present:
                _rewrite_column(con, table, col)

    json_rewrites = {
        "staged_summaries": _rewrite_json_child_ids(
            con, "staged_summaries", "id", "child_chunk_ids"
        ),
        "summary_nodes": _rewrite_json_child_ids(
            con, "summary_nodes", "id", "child_chunk_ids"
        ),
        "work_dossiers": _rewrite_work_dossiers(con),
    }
    if "summary_nodes" in tables and "tradition" in _columns(con, "summary_nodes"):
        con.execute(
            "UPDATE summary_nodes SET tradition=? WHERE tradition=? "
            "AND (text_id=? OR child_chunk_ids LIKE ? OR child_chunk_ids LIKE ?)",
            (
                NEW_TRADITION,
                OLD_TRADITION,
                TEXT_ID,
                f"%{OLD_PREFIX}%",
                f"%{NEW_PREFIX}%",
            ),
        )

    after = audit_counts(con)
    if after["nodes_old"] != 0:
        raise MigrationAbort(
            f"old-prefix chunk nodes remain: {after['nodes_old']}"
        )
    if after["nodes_new"] != old_chunks:
        raise MigrationAbort(
            f"new-prefix chunk count {after['nodes_new']} != before {old_chunks}"
        )
    if after.get("other_western") != before.get("other_western"):
        raise MigrationAbort("other western_esoteric chunk counts changed")
    if after.get("edges_src_old", 0) != 0 or after.get("edges_tgt_old", 0) != 0:
        raise MigrationAbort("old-prefix edge endpoints remain")
    expected_src = before.get("edges_src_old", 0)
    expected_tgt = before.get("edges_tgt_old", 0)
    # BELONGS_TO target_id was western_esoteric (not OLD_PREFIX), so tgt_new
    # counts only endpoints that were themselves chunk ids.
    if after.get("edges_src_new", 0) != expected_src:
        raise MigrationAbort(
            f"edges source rewrite mismatch: {after.get('edges_src_new')} "
            f"!= {expected_src}"
        )
    if after.get("edges_tgt_new", 0) != expected_tgt:
        raise MigrationAbort(
            f"edges target rewrite mismatch: {after.get('edges_tgt_new')} "
            f"!= {expected_tgt}"
        )
    for table, columns in OPTIONAL_ID_COLUMNS:
        for col in columns:
            old_key = f"{table}.{col}_old"
            new_key = f"{table}.{col}_new"
            if old_key not in before:
                continue
            if after.get(old_key, 0) != 0:
                raise MigrationAbort(f"{old_key} still nonzero after apply")
            if after.get(new_key, 0) != before[old_key]:
                raise MigrationAbort(
                    f"{new_key}={after.get(new_key)} != before {before[old_key]}"
                )

    fk_violations = list(con.execute("PRAGMA foreign_key_check"))
    if fk_violations:
        raise MigrationAbort(f"foreign_key_check: {fk_violations[:5]}")

    return {
        "status": "applied",
        "old_chunks": old_chunks,
        "new_chunks": after["nodes_new"],
        "theosophy_created": created,
        "json_rewrites": json_rewrites,
        "before": before,
        "after": after,
    }


def run_db(db_path: Path, apply: bool) -> int:
    if not db_path.exists() and str(db_path) != ":memory:":
        print(f"DB not found: {db_path}", file=sys.stderr)
        return 2
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys=OFF")
    before = audit_counts(con)
    _print_audit("pre-migration", before)

    old_chunks = before.get("nodes_old", 0)
    new_chunks = before.get("nodes_new", 0)
    if old_chunks == 0 and new_chunks > 0:
        print("already swapped — nothing to do")
        con.close()
        return 0

    if not apply:
        print("(dry-run — re-run with --apply to write; park dossier stream first)")
        con.close()
        return 0

    con.execute("BEGIN")
    try:
        result = apply_swap(con)
        con.execute("COMMIT")
    except MigrationAbort as exc:
        con.execute("ROLLBACK")
        con.close()
        print(f"ABORT: rolled back — {exc}", file=sys.stderr)
        return 1

    _print_audit("post-migration", result.get("after") or audit_counts(con))
    print(f"committed: {result}")
    con.close()
    return 0


def corpus_src() -> Path:
    return CORPUS_DIR / OLD_TRADITION / TEXT_ID


def corpus_dst() -> Path:
    return CORPUS_DIR / NEW_TRADITION / TEXT_ID


def rewrite_chunk_toml(path: Path) -> bool:
    """Rewrite id + tradition in a chunk TOML without touching the body."""
    text = path.read_text(encoding="utf-8")
    original = text
    text = text.replace(
        f'id = "{OLD_PREFIX}',
        f'id = "{NEW_PREFIX}',
    )
    # Only the metadata tradition field, not body mentions.
    text = text.replace(
        f'tradition = "{OLD_TRADITION}"',
        f'tradition = "{NEW_TRADITION}"',
        1,
    )
    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def rewrite_metadata_toml(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text
    text = text.replace(
        f'tradition = "{OLD_TRADITION}"',
        f'tradition = "{NEW_TRADITION}"',
        1,
    )
    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def run_corpus(apply: bool) -> int:
    src = corpus_src()
    dst = corpus_dst()
    if dst.exists() and not src.exists():
        print(f"corpus already at {dst} — nothing to do")
        return 0
    if not src.exists():
        print(
            f"corpus dir missing ({src}); operator can run this after "
            "checkout of untracked blavatsky-sd chunks"
        )
        return 0

    chunk_files = sorted((src / "chunks").glob("*.toml")) if (src / "chunks").is_dir() else []
    meta = src / "metadata.toml"
    print(f"plan: move {src} -> {dst} ({len(chunk_files)} chunk tomls)")
    if not apply:
        print("(dry-run — re-run with --apply --rewrite-corpus to write)")
        return 0

    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        shutil.move(str(src), str(dst))
    n = 0
    chunks_dir = dst / "chunks"
    if chunks_dir.is_dir():
        for path in sorted(chunks_dir.glob("*.toml")):
            if rewrite_chunk_toml(path):
                n += 1
    meta_dst = dst / "metadata.toml"
    if meta_dst.exists():
        rewrite_metadata_toml(meta_dst)
    print(f"rewrote {n} chunk tomls under {dst}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument(
        "--rewrite-corpus",
        action="store_true",
        help="move corpus/western_esoteric/blavatsky-sd → corpus/theosophy/ "
        "and rewrite chunk toml id/tradition (also dry-run unless --apply)",
    )
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan, write nothing (default)",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="commit the rewrite (only after the dossier stream is parked)",
    )
    args = ap.parse_args(argv)
    apply = bool(args.apply)
    rc = 0
    if args.rewrite_corpus:
        rc = run_corpus(apply=apply)
        if rc != 0:
            return rc
        # Corpus-only invocation skips the DB unless --db was given and exists.
        # Always still audit the DB when it exists so operators see both plans.
    if args.db.exists() or str(args.db) == ":memory:":
        rc = run_db(args.db, apply=apply)
    elif not args.rewrite_corpus:
        print(f"DB not found: {args.db} (dry-run of a missing DB is a no-op)")
        return 0
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
