"""
Guru Graph Bootstrap — Pass A of Stage 3.

Creates (or migrates) data/guru.db and populates:
  - tradition nodes from corpus/traditions.toml
  - concept nodes from concepts/taxonomy.toml
  - chunk nodes from corpus/**/chunks/*.toml
  - BELONGS_TO edge from every chunk to its tradition node

Idempotent: upserts on every run; safe to re-run after adding new chunks.

Usage:
    python3 scripts/graph_bootstrap.py [--db path/to/guru.db] [--dry-run]
"""

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

import tomllib

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_DB = PROJECT_ROOT / "data" / "guru.db"
SCHEMA_SQL = Path(__file__).parent / "schema.sql"
CORPUS_DIR = PROJECT_ROOT / "corpus"
TRADITIONS_TOML = CORPUS_DIR / "traditions.toml"
TAXONOMY_TOML = PROJECT_ROOT / "concepts" / "taxonomy.toml"


# ── helpers ──────────────────────────────────────────────────────────────────

def apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL.read_text())
    conn.commit()


def upsert_node(conn: sqlite3.Connection, id: str, type: str,
                label: str, tradition_id: str | None = None,
                definition: str | None = None,
                metadata_json: str = "{}") -> None:
    conn.execute(
        """INSERT INTO nodes(id, type, label, tradition_id, definition, metadata_json)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
             label=excluded.label,
             tradition_id=excluded.tradition_id,
             definition=excluded.definition,
             metadata_json=excluded.metadata_json""",
        (id, type, label, tradition_id, definition, metadata_json),
    )


def upsert_edge(conn: sqlite3.Connection, source_id: str, target_id: str,
                type: str, tier: str = "inferred",
                justification: str | None = None) -> None:
    conn.execute(
        """INSERT INTO edges(source_id, target_id, type, tier, justification)
           VALUES(?,?,?,?,?)
           ON CONFLICT(source_id, target_id, type) DO NOTHING""",
        (source_id, target_id, type, tier, justification),
    )


# ── passes ───────────────────────────────────────────────────────────────────

def bootstrap_traditions(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Insert tradition nodes. Returns {tradition_id: [text_ids]}."""
    with open(TRADITIONS_TOML, "rb") as f:
        data = tomllib.load(f)

    tradition_texts: dict[str, list[str]] = {}
    for trad in data.get("tradition", []):
        tid = trad["id"]
        name = trad.get("name", tid)
        upsert_node(conn, id=tid, type="tradition", label=name)
        tradition_texts[tid] = trad.get("texts", [])
        logger.info(f"  tradition: {tid}")

    conn.commit()
    return tradition_texts


def bootstrap_concepts(conn: sqlite3.Connection) -> None:
    """Insert concept nodes from taxonomy.toml."""
    with open(TAXONOMY_TOML, "rb") as f:
        data = tomllib.load(f)

    count = 0
    for category, concepts in data.get("concepts", {}).items():
        for concept_id, definition in concepts.items():
            node_id = f"concept.{concept_id}"
            upsert_node(
                conn,
                id=node_id,
                type="concept",
                label=concept_id.replace("_", " ").title(),
                definition=definition,
            )
            count += 1

    conn.commit()
    logger.info(f"  concepts: {count}")


def bootstrap_chunks(conn: sqlite3.Connection) -> int:
    """Insert chunk nodes and BELONGS_TO edges."""
    count = 0

    if not CORPUS_DIR.exists():
        logger.warning(f"corpus dir not found: {CORPUS_DIR}")
        return 0

    for trad_dir in sorted(CORPUS_DIR.iterdir()):
        if not trad_dir.is_dir() or trad_dir.name.endswith(".toml"):
            continue
        tradition_id = trad_dir.name

        # Ensure tradition node exists (even if not in traditions.toml yet)
        upsert_node(conn, id=tradition_id, type="tradition",
                    label=tradition_id.replace("_", " ").title())

        for text_dir in sorted(trad_dir.iterdir()):
            if not text_dir.is_dir():
                continue

            chunk_dir = text_dir / "chunks"
            if not chunk_dir.exists():
                continue

            # Load text-level metadata
            meta_path = text_dir / "metadata.toml"
            text_name = text_dir.name
            translator = ""
            source_url = ""
            if meta_path.exists():
                with open(meta_path, "rb") as f:
                    meta = tomllib.load(f)
                text_name = meta.get("text_name", text_dir.name)
                translator = meta.get("translator", "")
                source_url = meta.get("source_url", "")

            for chunk_file in sorted(chunk_dir.glob("*.toml")):
                with open(chunk_file, "rb") as f:
                    d = tomllib.load(f)

                chunk_meta = d["chunk"]
                chunk_id = chunk_meta["id"]
                section = chunk_meta.get("section", "")
                token_count = chunk_meta.get("token_count", 0)

                import json
                metadata_json = json.dumps({
                    "text_id": text_dir.name,
                    "section": section,
                    "translator": translator,
                    "source_url": source_url,
                    "token_count": token_count,
                })

                upsert_node(
                    conn,
                    id=chunk_id,
                    type="chunk",
                    label=f"{text_name} — {section}",
                    tradition_id=tradition_id,
                    metadata_json=metadata_json,
                )

                # BELONGS_TO edge: chunk → tradition
                upsert_edge(
                    conn,
                    source_id=chunk_id,
                    target_id=tradition_id,
                    type="BELONGS_TO",
                    tier="inferred",
                    justification="bootstrapped from corpus metadata",
                )
                count += 1

    conn.commit()
    logger.info(f"  chunks: {count}")
    return count


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap guru.db graph")
    parser.add_argument("--db", default=str(DEFAULT_DB), metavar="PATH")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stderr,
    )

    if args.dry_run:
        logger.info("Dry run — no DB writes")
        return

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")

    logger.info(f"Applying schema to {db_path} ...")
    apply_schema(conn)

    logger.info("Bootstrapping traditions ...")
    bootstrap_traditions(conn)

    logger.info("Bootstrapping concepts ...")
    bootstrap_concepts(conn)

    logger.info("Bootstrapping chunks + BELONGS_TO edges ...")
    n = bootstrap_chunks(conn)

    # Summary
    (n_nodes,) = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()
    (n_edges,) = conn.execute("SELECT COUNT(*) FROM edges").fetchone()
    conn.close()

    print(f"\nDone: {n_nodes} nodes, {n_edges} edges ({n} chunks bootstrapped)")


if __name__ == "__main__":
    main()
