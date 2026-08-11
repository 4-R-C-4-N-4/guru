"""
propose_edges.py — Pass C of Stage 3: cross-tradition edge proposals.

For each chunk, finds top-N nearest neighbours from other traditions via
the vector store, then asks an LLM to classify the relationship as
PARALLELS / CONTRASTS / surface_only / unrelated.

Writes every verdict to staged_edges: positives (PARALLELS/CONTRASTS) as
pending rows for review, negatives (surface_only/unrelated) as settled
status='rejected' rows with reviewed_by='model-negative' — never shown in the
review queue, but visible to dedup so re-runs stop re-paying for known
negatives. Deduplicates: never re-proposes a pair. Records per-chunk sweep
completion in edge_progress (a chunk with any errored pair gets no progress
row and is revisited next run).

Requires migrations v3_009 (similarity, presentation_order, edge_progress)
and v3_010 (model-negative dedup index).

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

# Bump this whenever SYSTEM_PROMPT or build_pair_prompt changes shape.
# Stored in staged_edges.prompt_version so future re-runs can be filtered
# (or re-evaluated) against the prompt revision that produced them.
PROMPT_VERSION = "v2"

SYSTEM_PROMPT = """\
You are a comparative religion scholar. Given two passages from different mystical
traditions, classify their relationship. Respond ONLY with valid JSON.

A genuine PARALLEL can be conceptual (the same insight in different words) OR
structural — a shared narrative structure / mytheme carried by different
characters, names, and wording. Recurring cross-tradition mythemes count as
PARALLELS, not surface_only: the flood / deluge survivor, katabasis (descent to
and return from the underworld), the quest for immortality or the plant/food of
life, the dying-and-rising figure, theomachy (combat with a chaos-monster at
creation), judgment of the dead in the afterlife, the world-tree / axis mundi,
and the psychopomp who guides souls. Different tradition, different proper nouns,
and different surface vocabulary do NOT by themselves make a pair surface_only;
reserve surface_only for pairs whose only link is an incidental shared word or
image with no shared conceptual OR structural content.
"""

def _body_for_prompt(body: str, max_body_chars: int | None) -> str:
    """Apply optional truncation. None or 0 means unlimited (the chunker
    already enforces a token budget at chunk creation time, so downstream
    prompts trust that contract)."""
    if not max_body_chars:
        return body
    return body[:max_body_chars]


def build_pair_prompt(chunk_a: dict, chunk_b: dict,
                      max_body_chars: int | None = None) -> str:
    body_a = _body_for_prompt(chunk_a["body"], max_body_chars)
    body_b = _body_for_prompt(chunk_b["body"], max_body_chars)
    return f"""\
Passage A ({chunk_a['citation']}):
\"\"\"
{body_a}
\"\"\"

Passage B ({chunk_b['citation']}):
\"\"\"
{body_b}
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
    # 4000 leaves headroom for a thinking model's reasoning preamble. The
    # 7193-edge run used Mistral (non-thinking) which never needed more
    # than ~200 tokens, but the previous 800 ceiling would silently truncate
    # if anyone swapped in the Qwen teacher for consistency with tagging.
    raw = call_llm(provider, model, SYSTEM_PROMPT, prompt, max_tokens=4000)
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


MODEL_NEGATIVE = "model-negative"


def upsert_staged_edge(conn: sqlite3.Connection,
                       source: str, target: str,
                       edge_type: str, confidence: float,
                       justification: str,
                       model: str,
                       prompt_version: str,
                       similarity: float | None = None) -> None:
    """Stage a positive verdict (PARALLELS/CONTRASTS) as a pending row.

    presentation_order records which passage the model saw as Passage A,
    relative to the canonical stored order — pair_key() destroys it otherwise,
    and the judge flips 21% of verdicts under order reversal, so without this
    AB/BA symmetry is unauditable from the store.
    """
    a, b = pair_key(source, target)
    order = "ab" if (a, b) == (source, target) else "ba"
    # ON CONFLICT targets the partial UNIQUE index
    # idx_staged_edges_provenance_unique (source_chunk, target_chunk, model,
    # prompt_version) WHERE status='pending' — a re-propose with the same
    # model+prompt is a no-op, but a different model can coexist.
    conn.execute(
        """INSERT INTO staged_edges
               (source_chunk, target_chunk, edge_type, confidence,
                justification, model, prompt_version,
                similarity, presentation_order)
           VALUES(?,?,?,?,?,?,?,?,?)
           ON CONFLICT(source_chunk, target_chunk, model, prompt_version)
           WHERE status = 'pending'
           DO NOTHING""",
        (a, b, edge_type, confidence, justification, model, prompt_version,
         similarity, order),
    )


def insert_model_negative(conn: sqlite3.Connection,
                          source: str, target: str,
                          edge_type: str, confidence: float,
                          justification: str,
                          model: str,
                          prompt_version: str,
                          similarity: float | None = None) -> None:
    """Persist a negative verdict (surface_only/unrelated) as settled history.

    status='rejected' + reviewed_by='model-negative': never enters the review
    queue (the review app filters status='pending' everywhere and apply
    refuses non-pending rows), distinguishable from curated rejections, and
    visible to get_existing_pairs() so re-runs stop re-paying for known
    negatives. Also the easy-negative supply for reranker training.

    ON CONFLICT targets idx_staged_edges_model_negative_unique (v3_010),
    which is scoped to this sentinel — the pending-only provenance index
    cannot dedup these rows, and without the scoped index a re-run would
    silently duplicate them.
    """
    a, b = pair_key(source, target)
    order = "ab" if (a, b) == (source, target) else "ba"
    conn.execute(
        """INSERT INTO staged_edges
               (source_chunk, target_chunk, edge_type, confidence,
                justification, model, prompt_version,
                similarity, presentation_order,
                status, reviewed_by, reviewed_at)
           VALUES(?,?,?,?,?,?,?,?,?,
                  'rejected', ?, strftime('%Y-%m-%dT%H:%M:%SZ','now'))
           ON CONFLICT(source_chunk, target_chunk, model, prompt_version)
           WHERE status = 'rejected' AND reviewed_by = 'model-negative'
           DO NOTHING""",
        (a, b, edge_type, confidence, justification, model, prompt_version,
         similarity, order, MODEL_NEGATIVE),
    )


def mark_edge_progress(conn: sqlite3.Connection, chunk_id: str,
                       model: str, prompt_version: str) -> None:
    """Record a completed sweep of one chunk (mirrors tagging_progress)."""
    conn.execute(
        """INSERT OR REPLACE INTO edge_progress(chunk_id, model, prompt_version)
           VALUES(?,?,?)""",
        (chunk_id, model, prompt_version),
    )


# ── main ──────────────────────────────────────────────────────────────────────

def run_proposals(
    db_path: Path,
    provider: str,
    model: str,
    top_n: int,
    min_similarity: float,
    tradition_filter: str | None,
    text_filter: str | None,
    delay: float,
    max_body_chars: int | None = None,
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
    if text_filter:
        # Chunk node ids are '<tradition>.<text_id>.<nnn>' — scope the sweep to
        # one text so a fresh ingest can be edge-mined without re-walking the
        # whole tradition (todo:038c5ed0; the Julian run's Boehme-first sweep
        # was the motivating case).
        sql += " AND id LIKE ?"
        params.append(f"%.{text_filter}.%")
    chunks = conn.execute(sql, params).fetchall()

    existing_pairs = get_existing_pairs(conn)
    proposed = negatives = skipped = errors = 0

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
        chunk_errors = 0

        for nb in neighbours:
            nb_id = nb["chunk_id"]
            key = pair_key(chunk_id, nb_id)

            if key in existing_pairs:
                skipped += 1
                continue

            body_b = load_chunk_body(nb_id)
            chunk_a = {"citation": label, "body": body_a}
            chunk_b = {"citation": nb.get("label", nb_id), "body": body_b}

            prompt = build_pair_prompt(chunk_a, chunk_b, max_body_chars=max_body_chars)

            try:
                result = call_llm_pair(provider, model, prompt)
                edge_type = result.get("edge_type")
                if edge_type not in ("PARALLELS", "CONTRASTS",
                                     "surface_only", "unrelated"):
                    # Parse failure or invalid verdict. Persisting nothing is
                    # deliberate: the old `.get("edge_type", "unrelated")`
                    # default would turn an unparseable response into a
                    # permanent model rejection.
                    logger.error(f"  unparseable verdict for "
                                 f"{chunk_id}↔{nb_id}: {result!r}")
                    errors += 1
                    chunk_errors += 1
                    continue
                try:
                    confidence = float(result.get("confidence", 0.0))
                except (TypeError, ValueError):
                    confidence = 0.0
                justification = result.get("justification", "")
                sim = nb.get("similarity")
                sim = float(sim) if sim is not None else None

                if edge_type in ("PARALLELS", "CONTRASTS"):
                    upsert_staged_edge(conn, chunk_id, nb_id,
                                       edge_type, confidence, justification,
                                       model=model,
                                       prompt_version=PROMPT_VERSION,
                                       similarity=sim)
                    proposed += 1
                    logger.info(f"  {chunk_id} ↔ {nb_id}: {edge_type} ({confidence:.2f})")
                else:
                    insert_model_negative(conn, chunk_id, nb_id,
                                          edge_type, confidence, justification,
                                          model=model,
                                          prompt_version=PROMPT_VERSION,
                                          similarity=sim)
                    negatives += 1
                existing_pairs.add(key)

            except Exception as e:
                logger.error(f"  LLM failed for {chunk_id}↔{nb_id}: {e}")
                errors += 1
                chunk_errors += 1

            if delay > 0:
                time.sleep(delay)

        # "Done" only when every neighbour of this chunk got a persisted
        # verdict (or was already settled). An errored pair means the sweep
        # must revisit this chunk, so no progress row.
        if chunk_errors == 0:
            mark_edge_progress(conn, chunk_id, model, PROMPT_VERSION)

    conn.commit()
    conn.close()
    print(f"\nDone: {proposed} proposals written, {negatives} negatives persisted, "
          f"{skipped} pairs skipped, {errors} errors")


def main() -> None:
    parser = argparse.ArgumentParser(description="Propose cross-tradition edges")
    parser.add_argument("--provider", default="llamacpp")
    parser.add_argument("--model",
                        default="Mistral-Small-3.2-24B-Instruct-2506-UD-Q5_K_XL.gguf",
                        help="Provenance label written to staged_edges.model. "
                             "Should match whatever's actually serving at the "
                             "llamacpp endpoint (start via scripts/run-mistral.sh).")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--min-similarity", type=float, default=0.75)
    parser.add_argument("--tradition")
    parser.add_argument("--text",
                        help="restrict the sweep to one text_id (chunk ids "
                             "'<tradition>.<text_id>.<nnn>'); combine with "
                             "--tradition or use alone")
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--max-body-chars", type=int, default=0,
                        help="optional cap on per-passage body length sent to "
                             "the LLM. 0 (default) = unlimited; the chunker is "
                             "the source of truth for chunk size. Set positive "
                             "only if running against a small-context model.")
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
        text_filter=args.text,
        delay=args.delay,
        max_body_chars=args.max_body_chars or None,
    )


if __name__ == "__main__":
    main()
