"""Run tagging on first 20 chunks per tradition for QA seeding."""
import json, sqlite3, sys, tomllib
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from guru.corpus import resolve_chunk_path
from tag_concepts import (load_taxonomy, build_prompt, SYSTEM_PROMPT,
                           parse_tags, upsert_staged_tag, mark_complete, call_ollama)

db = sqlite3.connect(str(ROOT / "data" / "guru.db"))
db.execute("PRAGMA foreign_keys=ON")
concepts = load_taxonomy()

for tradition in ("gnosticism", "jewish_mysticism"):
    rows = db.execute(
        "SELECT id, label, metadata_json FROM nodes "
        "WHERE type='chunk' AND tradition_id=? "
        "AND id NOT IN (SELECT chunk_id FROM tagging_progress) "
        "ORDER BY id LIMIT 20",
        (tradition,),
    ).fetchall()

    for chunk_id, label, meta_json in rows:
        chunk_file = resolve_chunk_path(chunk_id)
        body = tomllib.load(open(chunk_file, "rb"))["content"]["body"] if chunk_file else label
        prompt = build_prompt(body, label, concepts)
        try:
            raw = call_ollama("qwen3:8b", SYSTEM_PROMPT, prompt)
            tags = parse_tags(raw)
            for t in tags:
                upsert_staged_tag(db, chunk_id, t, model="qwen3-8b-seed")
            mark_complete(db, chunk_id)
            db.commit()
            print(f"{chunk_id}: {len(tags)} tags")
        except Exception as e:
            print(f"ERROR {chunk_id}: {e}")
