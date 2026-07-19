"""
promote_dossiers.py — assemble accepted staged rows into live dossier tables
(design §1.1 "Promotion = assembly", §6.1 works layer; implementation G6).

A work promotes only when its REQUIRED fields have accepted rows: `summary`,
`context`, and a structure_entry for every span in the frozen plan (degenerate
works need no structure). Partial dossiers never go live. For each field the
promoter takes the newest accepted row, preferring rows whose prompt_version
ends in '-manual' (manual fixes outrank any template version and bulk
regeneration never targets them).

themes_json is DERIVED, not generated: top-N EXPRESSES concept targets over
the work's chunks, tier-weighted with the runtime convention
(verified 1.0 / proposed 0.7 / inferred 0.4 — guru-web retriever.ts
TIER_WEIGHTS); works with fewer than THEMES_MIN_TAGS accepted tags export []
(V5 floor).

children_hash (normative, G6): sha256 of "\n".join(sha256(chunk body) for
the summary's TRANSITIVE child chunks, sorted by chunk id), bodies as stored.

Usage:
    python3 scripts/promote_dossiers.py [--work id] [--dry-run] [--db path]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sqlite3
import sys
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from works import load_works  # noqa: E402

logger = logging.getLogger(__name__)

CORPUS_DIR = PROJECT_ROOT / "corpus"
MANIFEST = PROJECT_ROOT / "sources" / "manifest.toml"
DEFAULT_DB = PROJECT_ROOT / "data" / "guru.db"

TIER_WEIGHTS = {"verified": 1.0, "proposed": 0.7, "inferred": 0.4}
THEMES_TOP_N = 8
THEMES_MIN_TAGS = 5   # V5 floor: fewer accepted tags -> themes []

REQUIRED_FIELDS = ("summary", "context")


# ── helpers ───────────────────────────────────────────────────────────────────

def chunk_body(chunk_id: str) -> str:
    trad, text, num = chunk_id.rsplit(".", 2)
    d = tomllib.load(open(CORPUS_DIR / trad / text / "chunks" / f"{num}.toml", "rb"))
    return d["content"]["body"]


def children_hash(chunk_ids: list[str]) -> str:
    parts = [hashlib.sha256(chunk_body(c).encode()).hexdigest()
             for c in sorted(chunk_ids)]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def latest_accepted_field(conn, work_id: str, field: str, span: str | None):
    """Newest accepted row for (work, field, span); manual rows outrank."""
    rows = conn.execute(
        "SELECT * FROM staged_dossier_fields WHERE work_id=? AND field=?"
        " AND COALESCE(section_span,'') = ? AND status='accepted' ORDER BY id DESC",
        (work_id, field, span or "")).fetchall()
    if not rows:
        return None
    manual = [r for r in rows if str(r["prompt_version"]).endswith("-manual")]
    return manual[0] if manual else rows[0]


def latest_accepted_summary(conn, summary_id: str):
    rows = conn.execute(
        "SELECT * FROM staged_summaries WHERE summary_id=? AND status='accepted'"
        " ORDER BY id DESC", (summary_id,)).fetchall()
    if not rows:
        return None
    manual = [r for r in rows if str(r["prompt_version"]).endswith("-manual")]
    return manual[0] if manual else rows[0]


def derive_themes(conn, chunk_ids: list[str]) -> list[str]:
    if not chunk_ids:
        return []
    qmarks = ",".join("?" for _ in chunk_ids)
    rows = conn.execute(
        f"SELECT target_id, tier FROM edges WHERE type='EXPRESSES' AND source_id IN ({qmarks})",
        chunk_ids).fetchall()
    if len(rows) < THEMES_MIN_TAGS:
        return []
    scores: dict[str, float] = {}
    for r in rows:
        scores[r["target_id"]] = scores.get(r["target_id"], 0.0) + TIER_WEIGHTS.get(r["tier"], 0.4)
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [cid for cid, _ in ranked[:THEMES_TOP_N]]


def manifest_notes_for(members) -> str | None:
    manifest = tomllib.load(open(MANIFEST, "rb"))["source"]
    by_id = {s["id"]: s for s in manifest}
    blocks = [f"[{m}] {by_id[m]['notes'].strip()}"
              for m in members if m in by_id and by_id[m].get("notes", "").strip()]
    return "\n\n".join(blocks) or None


# ── promotion ─────────────────────────────────────────────────────────────────

def promote_work(conn, wp: dict, members, dry_run: bool = False) -> str | None:
    """Returns a skip reason, or None on success."""
    work_id = wp["work_id"]
    degenerate = wp["degenerate"]
    spans = wp["spans"]

    field_rows = {}
    for f in REQUIRED_FIELDS:
        r = latest_accepted_field(conn, work_id, f, None)
        if r is None:
            return f"missing accepted {f}"
        field_rows[f] = r

    structure = []
    if not degenerate:
        for s in spans:
            r = latest_accepted_field(conn, work_id, "structure_entry", s["label"])
            if r is None:
                return f"missing accepted structure_entry for span {s['label']!r}"
            p = json.loads(r["payload_json"])
            structure.append({"section_span": s["label"], "title": p["title"],
                              "synopsis": p["synopsis"], "chunk_ids": s["chunk_ids"]})

    # summaries: L2 required; L1s required for every span unless degenerate
    l2_id = f"sum:{work_id}"
    l2 = latest_accepted_summary(conn, l2_id)
    if l2 is None:
        return "missing accepted level-2 summary"
    l1s = []
    if not degenerate:
        for s in spans:
            sid = f"sum:{s['text_id']}:{s['slug']}"
            r = latest_accepted_summary(conn, sid)
            if r is None:
                return f"missing accepted L1 {sid}"
            l1s.append((s, r))

    optional = {f: latest_accepted_field(conn, work_id, f, None)
                for f in ("key_figures", "key_terms", "reading_notes")}

    all_chunk_ids = [c for s in spans for c in s["chunk_ids"]]
    themes = derive_themes(conn, all_chunk_ids)

    versions = [f"summary-{field_rows['summary']['prompt_version']}",
                f"context-{field_rows['context']['prompt_version']}"]
    for f, r in optional.items():
        if r is not None:
            versions.append(f"{f}-{r['prompt_version']}")
    generated_by = ";".join(versions)

    if dry_run:
        logger.info(f"[dry-run] would promote {work_id}: {len(structure)} structure entries,"
                    f" {len(l1s)} L1s, themes={len(themes)}")
        return None

    conn.execute(
        "INSERT OR REPLACE INTO work_dossiers (work_id, summary, context, structure_json,"
        " key_figures_json, key_terms_json, themes_json, reading_notes, manifest_notes, generated_by)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (work_id,
         json.loads(field_rows["summary"]["payload_json"])["body"],
         json.loads(field_rows["context"]["payload_json"])["body"],
         json.dumps(structure, ensure_ascii=False),
         json.dumps(json.loads(optional["key_figures"]["payload_json"])["figures"]
                    if optional["key_figures"] else [], ensure_ascii=False),
         json.dumps(json.loads(optional["key_terms"]["payload_json"])["terms"]
                    if optional["key_terms"] else [], ensure_ascii=False),
         json.dumps(themes, ensure_ascii=False),
         (json.loads(optional["reading_notes"]["payload_json"])["body"]
          if optional["reading_notes"] else None),
         manifest_notes_for(members),
         generated_by))

    tradition = all_chunk_ids[0].split(".")[0]
    conn.execute("DELETE FROM summary_nodes WHERE work_id=?", (work_id,))
    for s, r in l1s:
        conn.execute(
            "INSERT INTO summary_nodes (id, work_id, text_id, tradition, level, section_span,"
            " child_chunk_ids, body, token_count, generated_by, children_hash)"
            " VALUES (?,?,?,?,1,?,?,?,?,?,?)",
            (r["summary_id"], work_id, s["text_id"], tradition, s["label"],
             json.dumps(s["chunk_ids"]), r["body"], r["token_count"],
             r["prompt_version"], children_hash(s["chunk_ids"])))
    text_ids = {s["text_id"] for s in spans}
    conn.execute(
        "INSERT INTO summary_nodes (id, work_id, text_id, tradition, level, section_span,"
        " child_chunk_ids, body, token_count, generated_by, children_hash)"
        " VALUES (?,?,?,?,2,NULL,?,?,?,?,?)",
        (l2_id, work_id, text_ids.pop() if len(text_ids) == 1 else None, tradition,
         json.dumps(all_chunk_ids), l2["body"], l2["token_count"],
         l2["prompt_version"], children_hash(all_chunk_ids)))
    conn.commit()
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--work")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    # Default the campaign from dossiers.toml so promote validates against the
    # CURRENT span plan; a hardcoded "c1" silently checked new works against a
    # stale plan (STAA under c3 had to pass --campaign by hand or misvalidate).
    try:
        _campaign_default = tomllib.load(
            open(PROJECT_ROOT / "config" / "dossiers.toml", "rb"))["campaign"]["campaign_id"]
    except Exception:
        _campaign_default = "c1"
    ap.add_argument("--campaign", default=_campaign_default)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    plan = json.loads((PROJECT_ROOT / "docs" / "summary" / f"span-plan-{args.campaign}.json").read_text())
    works = load_works()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    promoted = skipped = 0
    for wp in plan["works"]:
        if args.work and wp["work_id"] != args.work:
            continue
        reason = promote_work(conn, wp, works[wp["work_id"]].members, dry_run=args.dry_run)
        if reason:
            skipped += 1
            if args.work:
                logger.info(f"{wp['work_id']}: {reason}")
        else:
            promoted += 1
            logger.info(f"promoted {wp['work_id']}")
    logger.info(f"\npromoted {promoted}, skipped {skipped} (coverage {promoted}/{len(plan['works'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
