"""
propose_edges.py — Pass C of Stage 3: cross-tradition edge proposals.

For each chunk, finds top-N nearest neighbours from other traditions via
the vector store, then asks an LLM to classify the relationship as
PARALLELS / CONTRASTS / surface_only / unrelated.

Writes proposals to staged_edges. Deduplicates: never re-proposes a pair.

NOTE: Requires Stage 4 (embed_corpus.py) to have populated the vector store.
The VectorStore interface below is wired to scripts/vector_store.py (Stage 4).

Usage:
    python3 scripts/propose_edges.py \\
        --provider ollama --model llama3 \\
        [--top-n 5] [--min-similarity 0.75] \\
        [--tradition gnosticism] [--db PATH]
"""

import argparse
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path

import tomllib

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_DB = PROJECT_ROOT / "data" / "guru.db"

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).parent))
from guru.corpus import resolve_chunk_path  # noqa: E402
from llm import call_llm, parse_json_response


# ── vector store interface (wired in Stage 4) ─────────────────────────────────

def get_vector_store():
    """
    Load the vector store wrapper.
    Falls back gracefully if Stage 4 hasn't run yet.
    """
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from vector_store import VectorStore
        return VectorStore()
    except ImportError:
        logger.warning(
            "vector_store.py not found — Stage 4 not yet complete. "
            "propose_edges.py requires embed_corpus.py to have run first."
        )
        return None


# ── prompt ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a comparative religion scholar. Given two passages from different mystical
traditions, classify their relationship. Respond ONLY with valid JSON.
"""

def build_pair_prompt(chunk_a: dict, chunk_b: dict) -> str:
    return f"""\
Passage A ({chunk_a['citation']}):
\"\"\"
{chunk_a['body'][:600]}
\"\"\"

Passage B ({chunk_b['citation']}):
\"\"\"
{chunk_b['body'][:600]}
\"\"\"

Classify the relationship between these two passages:
  PARALLELS    — genuine conceptual parallel (same insight, different tradition)
  CONTRASTS    — genuine conceptual opposition (same theme, opposite position)
  surface_only — superficially similar wording but no deep connection
  unrelated    — no meaningful connection

Respond with:
{{
  "edge_type": "<PARALLELS|CONTRASTS|surface_only|unrelated>",
  "confidence": <0.0-1.0>,
  "justification": "<one to two sentences explaining the relationship>"
}}
"""


# ── providers ─────────────────────────────────────────────────────────────────

def call_llm_pair(provider: str, model: str, prompt: str) -> dict:
    raw = call_llm(provider, model, SYSTEM_PROMPT, prompt, max_tokens=800)
    result = parse_json_response(raw)
    return result if isinstance(result, dict) else {}


# ── helpers ───────────────────────────────────────────────────────────────────

def load_chunk_body(chunk_id: str) -> str:
    f = resolve_chunk_path(chunk_id)
    if f is None:
        return ""
    with open(f, "rb") as fp:
        d = tomllib.load(fp)
    return d["content"]["body"]


def pair_key(a: str, b: str) -> tuple[str, str]:
    """Canonical order for deduplication."""
    return (a, b) if a < b else (b, a)


def get_existing_pairs(conn: sqlite3.Connection) -> set[tuple[str, str]]:
    rows = conn.execute(
        "SELECT source_chunk, target_chunk FROM staged_edges"
    ).fetchall()
    return {pair_key(r[0], r[1]) for r in rows}


def upsert_staged_edge(conn: sqlite3.Connection,
                       source: str, target: str,
                       edge_type: str, confidence: float,
                       justification: str) -> None:
    a, b = pair_key(source, target)
    conn.execute(
        """INSERT INTO staged_edges
               (source_chunk, target_chunk, edge_type, confidence, justification)
           VALUES(?,?,?,?,?)
           ON CONFLICT(source_chunk, target_chunk) DO NOTHING""",
        (a, b, edge_type, confidence, justification),
    )


# ── main ──────────────────────────────────────────────────────────────────────

def run_proposals(
    db_path: Path,
    provider: str,
    model: str,
    top_n: int,
    min_similarity: float,
    tradition_filter: str | None,
    delay: float,
) -> None:
    vs = get_vector_store()
    if vs is None:
        print("ERROR: Vector store not available. Run scripts/embed_corpus.py first.")
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")

    # Load all chunks
    sql = "SELECT id, tradition_id, label FROM nodes WHERE type='chunk'"
    params: list = []
    if tradition_filter:
        sql += " AND tradition_id=?"
        params.append(tradition_filter)
    chunks = conn.execute(sql, params).fetchall()

    existing_pairs = get_existing_pairs(conn)
    proposed = skipped = errors = 0

    for chunk_id, tradition_id, label in chunks:
        # Query top-N neighbours from other traditions
        try:
            neighbours = vs.query(
                chunk_id=chunk_id,
                top_n=top_n,
                exclude_tradition=tradition_id,
                min_similarity=min_similarity,
            )
        except Exception as e:
            logger.error(f"Vector query failed for {chunk_id}: {e}")
            errors += 1
            continue

        body_a = load_chunk_body(chunk_id)

        for nb in neighbours:
            nb_id = nb["chunk_id"]
            key = pair_key(chunk_id, nb_id)

            if key in existing_pairs:
                skipped += 1
                continue

            body_b = load_chunk_body(nb_id)
            chunk_a = {"citation": label, "body": body_a}
            chunk_b = {"citation": nb.get("label", nb_id), "body": body_b}

            prompt = build_pair_prompt(chunk_a, chunk_b)

            try:
                result = call_llm_pair(provider, model, prompt)
                edge_type = result.get("edge_type", "unrelated")
                confidence = float(result.get("confidence", 0.0))
                justification = result.get("justification", "")

                if edge_type in ("PARALLELS", "CONTRASTS"):
                    upsert_staged_edge(conn, chunk_id, nb_id,
                                       edge_type, confidence, justification)
                    existing_pairs.add(key)
                    proposed += 1
                    logger.info(f"  {chunk_id} ↔ {nb_id}: {edge_type} ({confidence:.2f})")

            except Exception as e:
                logger.error(f"  LLM failed for {chunk_id}↔{nb_id}: {e}")
                errors += 1

            if delay > 0:
                time.sleep(delay)

    conn.commit()
    conn.close()
    print(f"\nDone: {proposed} proposals written, {skipped} pairs skipped, {errors} errors")


def main() -> None:
    parser = argparse.ArgumentParser(description="Propose cross-tradition edges")
    parser.add_argument("--provider", default="llamacpp")
    parser.add_argument("--model", default="Carnice-27b-Q4_K_M.gguf")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--min-similarity", type=float, default=0.75)
    parser.add_argument("--tradition")
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stderr,
    )

    run_proposals(
        db_path=Path(args.db),
        provider=args.provider,
        model=args.model,
        top_n=args.top_n,
        min_similarity=args.min_similarity,
        tradition_filter=args.tradition,
        delay=args.delay,
    )


if __name__ == "__main__":
    main()
