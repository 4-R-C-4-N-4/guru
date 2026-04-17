"""
tag_concepts.py — Pass B of Stage 3: LLM-assisted concept tagging.

For each chunk in guru.db, asks an LLM to score it against every concept in
the taxonomy and writes results to staged_tags. Supports --resume to skip
already-tagged chunks.

Usage:
    python3 scripts/tag_concepts.py \\
        --provider ollama --model llama3 \\
        [--batch-size 10] [--resume] \\
        [--tradition gnosticism] [--text gospel-of-thomas]
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
TAXONOMY_TOML = PROJECT_ROOT / "concepts" / "taxonomy.toml"

sys.path.insert(0, str(Path(__file__).parent))
from llm import call_llm, parse_json_response, PROVIDERS


# ── prompt ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a comparative religion scholar helping to build a concept index of mystical texts.
For each passage given, score it against every concept definition provided.
Respond ONLY with a valid JSON array (no markdown, no commentary).
"""

def build_prompt(chunk_body: str, chunk_citation: str, concepts: list[dict]) -> str:
    concepts_block = "\n".join(
        f'  {{"id": "{c["id"]}", "definition": "{c["definition"]}"}}'
        for c in concepts
    )
    return f"""\
Passage ({chunk_citation}):
\"\"\"
{chunk_body[:1200]}
\"\"\"

Rate each concept 0-3 for how strongly this passage expresses it:
  0 = not present
  1 = peripherally present
  2 = clearly present
  3 = central theme

Concepts:
[
{concepts_block}
]

Return a JSON array of objects for every concept with score >= 1:
[
  {{
    "concept_id": "<id from list above OR a new snake_case id>",
    "score": <0-3>,
    "justification": "<one sentence>",
    "is_new_concept": <true if not in list>,
    "new_concept_def": "<definition if is_new_concept else null>"
  }}
]

Return [] if nothing scores >= 1. Output only the JSON array. No preamble, no explanation, no markdown fences. Start your response with [ and end with ]. Return [] if nothing scores >= 1.
"""


# ── parsing ───────────────────────────────────────────────────────────────────

def parse_tags(raw: str) -> list[dict]:
    """Parse LLM JSON response into list of tag dicts."""
    parsed = parse_json_response(raw)

    if isinstance(parsed, dict):
        for key in ("tags", "results", "concepts", "items"):
            if key in parsed:
                parsed = parsed[key]
                break
        else:
            parsed = list(parsed.values())[0] if parsed else []

    if not isinstance(parsed, list):
        return []

    tags = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        score = int(item.get("score", 0))
        if score < 1:
            continue
        tags.append({
            "concept_id": str(item.get("concept_id", "")),
            "score": score,
            "justification": str(item.get("justification", "")),
            "is_new_concept": bool(item.get("is_new_concept", False)),
            "new_concept_def": item.get("new_concept_def"),
        })
    return tags


# ── main logic ───────────────────────────────────────────────────────────────

def load_taxonomy() -> list[dict]:
    with open(TAXONOMY_TOML, "rb") as f:
        data = tomllib.load(f)
    concepts = []
    for category, items in data.get("concepts", {}).items():
        for concept_id, definition in items.items():
            concepts.append({
                "id": concept_id,
                "definition": definition,
                "node_id": f"concept.{concept_id}",
            })
    return concepts


def get_chunks(conn: sqlite3.Connection,
               tradition: str | None,
               text_id: str | None,
               resume: bool) -> list[dict]:
    sql = """
        SELECT n.id, n.label, n.metadata_json
        FROM nodes n
        WHERE n.type = 'chunk'
    """
    params: list = []

    if tradition:
        sql += " AND n.tradition_id = ?"
        params.append(tradition)

    if text_id:
        sql += " AND json_extract(n.metadata_json, '$.text_id') = ?"
        params.append(text_id)

    if resume:
        sql += " AND n.id NOT IN (SELECT chunk_id FROM tagging_progress)"

    sql += " ORDER BY n.id"
    rows = conn.execute(sql, params).fetchall()
    return [{"id": r[0], "label": r[1], "meta": json.loads(r[2])} for r in rows]


def upsert_staged_tag(conn: sqlite3.Connection, chunk_id: str, tag: dict) -> None:
    conn.execute(
        """INSERT INTO staged_tags
               (chunk_id, concept_id, score, justification, is_new_concept, new_concept_def)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT DO NOTHING""",
        (
            chunk_id,
            tag["concept_id"],
            tag["score"],
            tag["justification"],
            1 if tag["is_new_concept"] else 0,
            tag.get("new_concept_def"),
        ),
    )


def mark_complete(conn: sqlite3.Connection, chunk_id: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO tagging_progress(chunk_id) VALUES(?)",
        (chunk_id,),
    )


def run_tagging(
    db_path: Path,
    provider_name: str,
    model: str,
    batch_size: int,
    resume: bool,
    tradition: str | None,
    text_id: str | None,
    delay: float,
) -> None:
    call_fn = PROVIDERS.get(provider_name)
    if not call_fn:
        logger.error(f"Unknown provider: {provider_name}")
        sys.exit(1)
    concepts = load_taxonomy()
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")

    chunks = get_chunks(conn, tradition, text_id, resume)
    logger.info(f"Tagging {len(chunks)} chunks with {provider_name}/{model} ...")

    tagged = skipped = errors = 0

    for i, chunk in enumerate(chunks):
        chunk_id = chunk["id"]
        meta = chunk["meta"]

        # Load body from corpus chunk file
        parts = chunk_id.split(".")
        if len(parts) >= 3:
            trad = parts[0].lower().replace(" ", "_")
            tid = parts[1]
            idx = parts[2]
            chunk_file = PROJECT_ROOT / "corpus" / trad / tid / "chunks" / f"{idx}.toml"
            if chunk_file.exists():
                with open(chunk_file, "rb") as f:
                    cd = tomllib.load(f)
                body = cd["content"]["body"]
            else:
                body = chunk["label"]
        else:
            body = chunk["label"]

        citation = chunk["label"]
        prompt = build_prompt(body, citation, concepts)

        try:
            print(f"\n[DEBUG prompt]\n{prompt}\n{"="*60}\n", flush=True)
            raw = call_llm(provider_name, model, SYSTEM_PROMPT, prompt, max_tokens=4000)
            print(f"\n[DEBUG raw response]\n{raw!r}\n{"="*60}\n", flush=True)
            tags = parse_tags(raw)

            for tag in tags:
                upsert_staged_tag(conn, chunk_id, tag)

            mark_complete(conn, chunk_id)
            conn.commit()
            tagged += 1
            logger.info(f"  [{i+1}/{len(chunks)}] {chunk_id}: {len(tags)} tags")

        except Exception as e:
            logger.error(f"  [{i+1}/{len(chunks)}] {chunk_id} FAILED: {e}")
            errors += 1

        if delay > 0 and i < len(chunks) - 1:
            time.sleep(delay)

        if batch_size and (i + 1) % batch_size == 0:
            logger.info(f"Batch {(i+1)//batch_size} complete ({tagged} tagged, {errors} errors)")

    conn.close()
    print(f"\nDone: {tagged} chunks tagged, {skipped} skipped, {errors} errors")


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM-assisted concept tagging")
    parser.add_argument("--provider", choices=list(PROVIDERS), default="llamacpp")
    parser.add_argument("--model", default="Carnice-27b-Q4_K_M.gguf")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--batch-size", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--tradition")
    parser.add_argument("--text")
    parser.add_argument("--delay", type=float, default=0.0,
                        help="Seconds between API calls (rate-limit pacing)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stderr,
    )

    run_tagging(
        db_path=Path(args.db),
        provider_name=args.provider,
        model=args.model,
        batch_size=args.batch_size,
        resume=args.resume,
        tradition=args.tradition,
        text_id=args.text,
        delay=args.delay,
    )


if __name__ == "__main__":
    main()
