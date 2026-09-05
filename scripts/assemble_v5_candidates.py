"""
assemble_v5_candidates.py — child 1 of the tagger-v5 targeted backfill
(todo:7b1d7388 / todo:a08fe227).

v4 could not backfill the 12 genuinely cross-tradition drift concepts onto
older traditions: every training positive for them came from the new corpus
(theosophy / western_esoteric / gnosticism), so the finetune never saw them
attached to an older tradition. This assembles the candidate chunk set the
27B teacher (child 2) will adjudicate: for each target concept, the chunks
from OLDER traditions most likely to express it, gathered two ways —

  1. definition-embedding kNN over chunk_embeddings (semantic), and
  2. lexical FTS over data/lexical-fts.db on the concept's signature
     language (fallback / recall for terms the embedder blurs).

The new corpus is excluded on both paths — its rows already exist. Lexical
hits whose only matched signature terms are false-friend-prone (e.g. a
qliphoth "shells" match that is really seashells) are flagged so the 27B
step scrutinises them rather than trusting the lexical match.

Outputs (under --out-dir, default data/backfill-v5/, which is git-ignored
like guru.db — the reproducible record is this script plus the committed
counts snapshot in docs/ingest/):

  candidates.jsonl    one record per (concept, chunk) with method/score/flag
  union-chunk-ids.txt  deduped chunk-id union, the --chunk-ids-from-file
                       input for scripts/tag_concepts.py in child 2
  counts.md            per-concept and per-concept×tradition counts

This script only READS guru.db and lexical-fts.db; it writes nothing to the
graph and stages nothing.

Usage:
    python3 scripts/assemble_v5_candidates.py \\
        [--embed-top-n 40] [--min-sim 0.55] [--fts-top-n 25] \\
        [--out-dir data/backfill-v5]
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
import tomllib
from collections import defaultdict
from contextlib import closing
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from embed_corpus import embed_ollama  # noqa: E402
from vector_store import VectorStore  # noqa: E402

DEFAULT_DB = PROJECT_ROOT / "data" / "guru.db"
LEXICAL_DB = PROJECT_ROOT / "data" / "lexical-fts.db"
TAXONOMY_TOML = PROJECT_ROOT / "concepts" / "taxonomy.toml"
EMBED_MODEL = "nomic-embed-text"

# Where the drift concepts already have their training rows — excluded on
# both retrieval paths so we gather only the missing older-tradition signal.
NEW_CORPUS = ["theosophy", "western_esoteric", "gnosticism"]

# The 12 genuinely cross-tradition concepts. Psychism concepts native to the
# new corpus (psychic_attack, etheric_projection, aura, thought_form, …) are
# deliberately absent: they have no ancient home to backfill onto.
TARGET_CONCEPTS = [
    "trinity", "stellar_determinism", "divine_immanence", "initiation",
    "divination", "esoteric_lineage", "exorcism", "gender",
    "spirit_conjuration", "incarnation", "qliphoth", "talisman_magic",
]

# Signature language for the lexical FTS leg. `terms` are OR-ed into one FTS5
# MATCH query; `false_friends` is the subset whose surface form is ambiguous
# out of context — a lexical hit matched ONLY by these gets flagged for the
# 27B step. Terms are matched as whole words for the flag analysis.
SIGNATURES: dict[str, dict[str, list[str]]] = {
    "trinity": {
        "terms": ["trinity", "triad", "triune", "threefold", "three persons",
                  "father son and", "holy ghost", "holy trinity", "tripartite"],
        "false_friends": ["triad", "threefold", "tripartite"],
    },
    "stellar_determinism": {
        "terms": ["stellar", "planetary", "astrological", "zodiac", "horoscope",
                  "rulers of the stars", "error of the stars", "governors",
                  "fate", "destiny", "spheres"],
        "false_friends": ["spheres", "fate", "destiny", "governors"],
    },
    "divine_immanence": {
        "terms": ["immanent", "immanence", "indwelling", "pervades", "pervading",
                  "omnipresent", "present in all", "dwells in all", "God in all"],
        "false_friends": ["indwelling", "dwells in all"],
    },
    "initiation": {
        "terms": ["initiation", "initiate", "initiated", "rite of passage",
                  "ordeal", "admission", "neophyte", "adept", "mysteries"],
        "false_friends": ["mysteries", "adept", "initiate", "initiated"],
    },
    "divination": {
        "terms": ["divination", "oracle", "augury", "auspices", "sortilege",
                  "casting lots", "omen", "entrails", "foretell", "soothsayer",
                  "prophecy", "geomancy"],
        "false_friends": ["prophecy", "omen", "foretell"],
    },
    "esoteric_lineage": {
        "terms": ["lineage", "succession", "transmission", "handed down",
                  "master to disciple", "unbroken chain", "passed down",
                  "apostolic succession", "chain of teachers"],
        "false_friends": ["lineage", "succession", "transmission", "handed down",
                          "passed down"],
    },
    "exorcism": {
        "terms": ["exorcism", "exorcise", "exorcist", "cast out", "drive out",
                  "expel the spirit", "unclean spirit", "cast forth"],
        "false_friends": ["cast out", "drive out", "cast forth"],
    },
    "gender": {
        "terms": ["masculine and feminine", "male and female", "generative principle",
                  "gender", "sex", "androgyne", "hermaphrodite", "polarity of sex"],
        "false_friends": ["gender", "sex", "male and female"],
    },
    "spirit_conjuration": {
        "terms": ["conjuration", "conjure", "conjuring", "evocation", "grimoire",
                  "summon the spirit", "bind the spirit", "magic circle",
                  "seal of solomon", "compel"],
        "false_friends": ["summon the spirit", "compel", "seal", "magic circle"],
    },
    "incarnation": {
        "terms": ["incarnation", "incarnate", "made flesh", "avatar", "avatara",
                  "word made flesh", "descended into", "took on flesh",
                  "born as", "tulku"],
        "false_friends": ["born as", "descended into"],
    },
    "qliphoth": {
        "terms": ["qliphoth", "qlippoth", "qlippothic", "klippot", "shells",
                  "husks", "shadow sphere", "habitations of hell"],
        "false_friends": ["shells", "husks"],
    },
    "talisman_magic": {
        "terms": ["talisman", "talismanic", "amulet", "pentacle", "phylactery",
                  "consecrated seal", "inscribed charm", "graven image", "sigil"],
        "false_friends": ["charm", "seal", "sigil", "graven image"],
    },
}

WORD_RE_CACHE: dict[str, re.Pattern] = {}


def load_definitions() -> dict[str, str]:
    """Flatten the nested family→subfamily→concept:def taxonomy."""
    data = tomllib.load(open(TAXONOMY_TOML, "rb"))
    flat: dict[str, str] = {}

    def walk(node: dict) -> None:
        for k, v in node.items():
            if isinstance(v, dict):
                walk(v)
            elif isinstance(v, str):
                flat[k] = v

    walk(data["concepts"])
    missing = [c for c in TARGET_CONCEPTS if c not in flat]
    if missing:
        raise SystemExit(f"target concepts missing from taxonomy: {missing}")
    return {c: flat[c] for c in TARGET_CONCEPTS}


def chunk_tradition_map(db_path: Path) -> dict[str, str]:
    with closing(sqlite3.connect(db_path)) as conn:
        return {
            cid: trad or ""
            for cid, trad in conn.execute(
                "SELECT id, tradition_id FROM nodes WHERE type = 'chunk'"
            )
        }


def term_present(body_lower: str, term: str) -> bool:
    """Whole-word (phrase) presence test, case-insensitive."""
    pat = WORD_RE_CACHE.get(term)
    if pat is None:
        pat = re.compile(r"\b" + re.escape(term.lower()) + r"\b")
        WORD_RE_CACHE[term] = pat
    return pat.search(body_lower) is not None


def fts_query(lex: sqlite3.Connection, terms: list[str], top_n: int,
              trad_of: dict[str, str], exclude: set[str],
              overshoot: int = 8) -> list[tuple[str, float, str]]:
    """Return [(chunk_id, bm25, body)] for older-tradition FTS hits, best
    (most-negative bm25) first. Over-fetch, then filter by tradition."""
    match = " OR ".join(f'"{t}"' for t in terms)
    rows = lex.execute(
        "SELECT chunk_id, bm25(chunks_fts) AS rank, body "
        "FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank "
        "LIMIT ?",
        (match, top_n * overshoot),
    ).fetchall()
    out: list[tuple[str, float, str]] = []
    for cid, rank, body in rows:
        trad = trad_of.get(cid, "")
        if not trad or trad in exclude:
            continue
        out.append((cid, float(rank), body))
        if len(out) >= top_n:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--lexical-db", default=str(LEXICAL_DB))
    ap.add_argument("--embed-top-n", type=int, default=40,
                    help="max semantic (embedding kNN) hits per concept")
    ap.add_argument("--min-sim", type=float, default=0.62,
                    help="cosine floor for the embedding leg; nomic runs hot "
                         "(rank-40 hits sit ~0.69), so this mainly guards thin "
                         "concepts rather than trimming the top-N")
    ap.add_argument("--fts-top-n", type=int, default=25,
                    help="max lexical (FTS bm25) hits per concept")
    ap.add_argument("--out-dir", default=str(PROJECT_ROOT / "data" / "backfill-v5"))
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    db_path = Path(args.db)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    exclude = set(NEW_CORPUS)

    defs = load_definitions()
    trad_of = chunk_tradition_map(db_path)
    store = VectorStore(db_path)
    lex = sqlite3.connect(args.lexical_db)

    # Embed all 12 definitions in one batched ollama call.
    logger.info("Embedding %d concept definitions (%s) ...", len(defs), EMBED_MODEL)
    vectors = embed_ollama([defs[c] for c in TARGET_CONCEPTS], EMBED_MODEL)
    def_vec = dict(zip(TARGET_CONCEPTS, vectors))

    # Per (concept, chunk) candidate record, merged across both legs.
    records: dict[tuple[str, str], dict] = {}
    body_of: dict[str, str] = {}

    for concept in TARGET_CONCEPTS:
        sig = SIGNATURES[concept]

        # --- embedding leg ---
        hits = store.query(
            embedding=def_vec[concept],
            where={"tradition": {"$nin": NEW_CORPUS}},
            top_n=args.embed_top_n,
            min_similarity=args.min_sim,
        )
        for h in hits:
            cid = h["chunk_id"]
            rec = records.setdefault((concept, cid), {
                "concept_id": concept, "chunk_id": cid,
                "tradition": trad_of.get(cid, ""), "methods": [],
                "embed_sim": None, "bm25": None,
                "matched_terms": [], "false_friend_prone": False,
            })
            rec["methods"].append("embed")
            rec["embed_sim"] = round(h["similarity"], 4)

        # --- lexical FTS leg ---
        fts_hits = fts_query(lex, sig["terms"], args.fts_top_n, trad_of, exclude)
        ff_set = set(sig["false_friends"])
        for cid, rank, body in fts_hits:
            body_of[cid] = body
            body_lower = body.lower()
            matched = [t for t in sig["terms"] if term_present(body_lower, t)]
            rec = records.setdefault((concept, cid), {
                "concept_id": concept, "chunk_id": cid,
                "tradition": trad_of.get(cid, ""), "methods": [],
                "embed_sim": None, "bm25": None,
                "matched_terms": [], "false_friend_prone": False,
            })
            rec["methods"].append("fts")
            rec["bm25"] = round(rank, 3)
            rec["matched_terms"] = matched
            # Flag when the only signature terms present are false-friend-prone
            # AND the semantic leg did not independently surface this chunk.
            only_ff = bool(matched) and all(t in ff_set for t in matched)
            if only_ff and "embed" not in rec["methods"]:
                rec["false_friend_prone"] = True

        n_embed = sum(1 for (c, _), r in records.items()
                      if c == concept and "embed" in r["methods"])
        n_fts = sum(1 for (c, _), r in records.items()
                    if c == concept and "fts" in r["methods"])
        logger.info("  %-20s embed=%-3d fts=%-3d", concept, n_embed, n_fts)

    # Snippets for anything without a body yet (embedding-only hits).
    need_body = [cid for (_, cid) in records if cid not in body_of]
    for i in range(0, len(need_body), 500):
        batch = need_body[i:i + 500]
        ph = ",".join("?" * len(batch))
        for cid, body in lex.execute(
            f"SELECT chunk_id, body FROM chunks_fts WHERE chunk_id IN ({ph})", batch
        ):
            body_of[cid] = body

    # ── write candidates.jsonl (one record per (concept, chunk) line) ──
    jsonl_path = out_dir / "candidates.jsonl"
    ordered = sorted(records.values(),
                     key=lambda r: (r["concept_id"], r["chunk_id"]))
    with jsonl_path.open("w") as f:
        for rec in ordered:
            body = body_of.get(rec["chunk_id"], "")
            snippet = " ".join(body.split())[:240]
            out = dict(rec)
            out["methods"] = sorted(set(rec["methods"]))
            out["snippet"] = snippet
            f.write(json.dumps(out, ensure_ascii=False) + "\n")

    # ── write union-chunk-ids.txt (child 2's --chunk-ids-from-file) ──
    union = sorted({cid for (_, cid) in records})
    union_path = out_dir / "union-chunk-ids.txt"
    with union_path.open("w") as f:
        f.write(f"# tagger-v5 backfill candidate union (todo:a08fe227)\n")
        f.write(f"# {len(union)} chunks across {len(TARGET_CONCEPTS)} concepts, "
                f"older traditions only (excl. {', '.join(NEW_CORPUS)})\n")
        f.write(f"# embed-top-n={args.embed_top_n} min-sim={args.min_sim} "
                f"fts-top-n={args.fts_top_n}\n")
        for cid in union:
            f.write(cid + "\n")

    # ── write counts.md ──
    per_concept: dict[str, int] = defaultdict(int)
    per_cell: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    ff_per_concept: dict[str, int] = defaultdict(int)
    for rec in records.values():
        per_concept[rec["concept_id"]] += 1
        per_cell[rec["concept_id"]][rec["tradition"]] += 1
        if rec["false_friend_prone"]:
            ff_per_concept[rec["concept_id"]] += 1

    counts_path = out_dir / "counts.md"
    with counts_path.open("w") as f:
        f.write("# tagger-v5 backfill candidate counts (todo:a08fe227)\n\n")
        f.write(f"- union chunks: **{len(union)}**\n")
        f.write(f"- candidate (concept, chunk) pairs: **{len(records)}**\n")
        f.write(f"- excluded traditions (new corpus): {', '.join(NEW_CORPUS)}\n")
        f.write(f"- params: embed-top-n={args.embed_top_n} min-sim={args.min_sim} "
                f"fts-top-n={args.fts_top_n}\n\n")
        f.write("## Per concept\n\n")
        f.write("| concept | candidates | false-friend-flagged |\n")
        f.write("|---|---:|---:|\n")
        for c in TARGET_CONCEPTS:
            f.write(f"| {c} | {per_concept[c]} | {ff_per_concept[c]} |\n")
        f.write("\n## Per concept × tradition\n\n")
        f.write("| concept | tradition | candidates |\n")
        f.write("|---|---|---:|\n")
        for c in TARGET_CONCEPTS:
            for trad in sorted(per_cell[c], key=lambda t: -per_cell[c][t]):
                f.write(f"| {c} | {trad} | {per_cell[c][trad]} |\n")

    lex.close()
    logger.info("")
    logger.info("union chunks:        %d", len(union))
    logger.info("candidate pairs:     %d", len(records))
    logger.info("false-friend flags:  %d", sum(ff_per_concept.values()))
    logger.info("wrote: %s", jsonl_path)
    logger.info("wrote: %s", union_path)
    logger.info("wrote: %s", counts_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
