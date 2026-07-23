"""
apply_cleanups.py — write ACCEPTED staged_cleanups rewrites to the corpus
TOMLs (todo:b44966d0).

The web review deck queues decisions; the apply gate flips
staged_cleanups.status to 'accepted' — and stops there, because the server
never writes the corpus. This script is the corpus half, mirroring
clean_bodies.py --apply: rewrite the chunk TOML, recompute token_count via
the pipeline tokenizer, mirror the count into nodes.metadata_json, and
stamp staged_cleanups.applied_at.

Applicability is decided from TOML STATE, not the applied_at stamp
(todo:4133d6c1) — this is what makes accepted rewrites survive a
from-zero corpus rebuild:
  - TOML body == proposed_body  → already applied (stamp if missing);
  - TOML body == original_body  → applicable — a fresh re-chunk of the
    raw source regenerates exactly the original hard-wrapped body, so
    accepted rewrites re-apply mechanically after a rebuild;
  - anything else               → stale refusal (the body changed under
    us — clean_bodies re-run, re-chunk drift — human eyes needed).
applied_at is an audit stamp only. The whole pass is idempotent by
construction: run it as many times as you like.

Safety gates, all hard-refusals (reported, never written):
  - the TOML-state check above;
  - words_preserved: recomputed here, not trusted from the row — the
    character stream minus whitespace/hyphens must match exactly;
  - length ratio outside [0.85, 1.15] (whitespace repair barely moves it).

After applying: re-embed the changed texts (embed_corpus.py --reindex
--tradition X --text Y) and re-export. The script prints the exact
commands for the texts it touched.

Operator pre-flight: scripts/backup_db.sh pre-apply-cleanups

Usage:
    python3 scripts/apply_cleanups.py --dry-run     # diffs of accepted rows
    python3 scripts/apply_cleanups.py --apply
"""

from __future__ import annotations

import argparse
import difflib
import json
import logging
import sqlite3
import sys
from pathlib import Path

import tomllib
import tomli_w

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from chunkers.tokens import count_tokens  # noqa: E402
from propose_cleanups import words_preserved  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_DB = PROJECT_ROOT / "data" / "guru.db"
CORPUS_DIR = PROJECT_ROOT / "corpus"


def toml_path(chunk_id: str) -> Path:
    trad, text_id, seq = chunk_id.split(".")
    return CORPUS_DIR / trad / text_id / "chunks" / f"{seq}.toml"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="print diffs, write nothing")
    mode.add_argument("--apply", action="store_true", help="write TOMLs and update DB")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    # ALL accepted rows — applicability is decided per-row from TOML state
    # below, never from applied_at (rebuild-proof; see docstring).
    rows = conn.execute(
        """SELECT id, chunk_id, original_body, proposed_body
             FROM staged_cleanups
            WHERE status = 'accepted'
            ORDER BY chunk_id"""
    ).fetchall()
    if not rows:
        logger.info("nothing to apply (no accepted cleanups)")
        return 0

    applied, refused = [], []
    already = 0
    touched_texts: set[tuple[str, str]] = set()
    for r in rows:
        cid = r["chunk_id"]
        path = toml_path(cid)
        data = tomllib.load(open(path, "rb"))
        current = data["content"]["body"]

        if current == r["proposed_body"]:
            # Already in the desired state; ensure the audit stamp exists.
            if not args.dry_run:
                conn.execute(
                    "UPDATE staged_cleanups SET applied_at = COALESCE(applied_at, "
                    "strftime('%Y-%m-%dT%H:%M:%SZ','now')) WHERE id = ?",
                    (r["id"],),
                )
                conn.commit()
            already += 1
            continue
        if current != r["original_body"]:
            refused.append((cid, "stale: TOML body matches neither original nor proposed"))
            continue
        if not words_preserved(current, r["proposed_body"]):
            refused.append((cid, "words_preserved recheck failed"))
            continue
        ratio = len(r["proposed_body"]) / max(len(current), 1)
        if not 0.85 <= ratio <= 1.15:
            refused.append((cid, f"length ratio {ratio:.2f} outside [0.85, 1.15]"))
            continue

        if args.dry_run:
            diff = difflib.unified_diff(
                current.splitlines(keepends=True),
                r["proposed_body"].splitlines(keepends=True),
                fromfile=f"a/{cid}", tofile=f"b/{cid}",
            )
            sys.stdout.writelines(diff)
            sys.stdout.write("\n")
        else:
            data["content"]["body"] = r["proposed_body"]
            data["chunk"]["token_count"] = count_tokens(r["proposed_body"])
            with open(path, "wb") as f:
                tomli_w.dump(data, f)
            node = conn.execute(
                "SELECT metadata_json FROM nodes WHERE id = ? AND type = 'chunk'", (cid,)
            ).fetchone()
            if node is not None:
                meta = json.loads(node["metadata_json"] or "{}")
                meta["token_count"] = data["chunk"]["token_count"]
                conn.execute(
                    "UPDATE nodes SET metadata_json = ? WHERE id = ?",
                    (json.dumps(meta, ensure_ascii=False), cid),
                )
            conn.execute(
                "UPDATE staged_cleanups SET applied_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') "
                "WHERE id = ?",
                (r["id"],),
            )
            conn.commit()
        applied.append(cid)
        trad, text_id, _ = cid.split(".")
        touched_texts.add((trad, text_id))

    verb = "would apply" if args.dry_run else "applied"
    logger.info(f"\n{verb}: {len(applied)} · already in desired state: {already} · refused: {len(refused)}")
    for cid, why in refused:
        logger.warning(f"  REFUSED {cid}: {why}")
    if applied and not args.dry_run:
        logger.info("\nnow re-embed the touched texts:")
        for trad, text_id in sorted(touched_texts):
            logger.info(f"  python3 scripts/embed_corpus.py --reindex --tradition {trad} --text {text_id}")
        logger.info("then re-export: python3 scripts/export.py")
    conn.close()
    return 0 if not refused else 1


if __name__ == "__main__":
    sys.exit(main())
