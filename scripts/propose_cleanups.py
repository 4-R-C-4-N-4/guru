"""
propose_cleanups.py — stage model-proposed rewrites of hard-wrapped chunk
bodies into staged_cleanups (todo:b44966d0).

The readability audit (docs/summary/readability-audit.md) left one damage
class the regex passes cannot safely fix: hard-wrapped prose (lines broken
mid-sentence, words split by end-of-line hyphens — the mandaean
gnostic-john-baptizer texts). Unwrapping needs judgment about which line
breaks are real paragraph boundaries, so a local model proposes the rewrite
and a human reviews it as a diff in guru-review. Nothing here touches the
corpus: proposals land in staged_cleanups(status='pending'); the web apply
gate flips status; scripts/apply_cleanups.py writes accepted TOMLs.

The task is deliberately constrained to WHITESPACE REPAIR: the model may
join lines, merge hyphen-split words, and normalize paragraph breaks — and
nothing else. Every proposal is validated mechanically: the character
stream minus whitespace/hyphens must be IDENTICAL to the original
(words_preserved=1). Failing proposals are still staged (flagged 0) so the
reviewer sees the model drifted, but apply_cleanups.py refuses them.

Targets come from the audit scanner: chunks whose hard_wrap signal is at or
above --min-hard-wrap (default 0.15 — currently 40 chunks, all mandaean).

Usage:
    python3 scripts/propose_cleanups.py --dry-run              # list targets
    python3 scripts/propose_cleanups.py                        # propose all targets
    python3 scripts/propose_cleanups.py --chunk-id mandaean.gnostic-john-baptizer-3.021
    python3 scripts/propose_cleanups.py --tradition mandaean --limit 5
    python3 scripts/propose_cleanups.py --provider llamacpp --model <gguf>
"""

from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import sys
import time
from pathlib import Path

import tomllib

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from audit_readability import audit, score_body  # noqa: E402
from llm import call_llm  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_DB = PROJECT_ROOT / "data" / "guru.db"
CORPUS_DIR = PROJECT_ROOT / "corpus"

PROMPT_VERSION = "v1"

SYSTEM_PROMPT = """\
You repair hard-wrapped plain text. The passage you receive was digitized
with line breaks inserted mid-sentence and words split across lines with
hyphens. Repair ONLY the whitespace:

- Join lines that break mid-sentence into flowing paragraphs.
- Rejoin words split by an end-of-line hyphen (e.g. "splen-\\ndour" -> "splendour").
- Keep REAL paragraph boundaries (blank lines) as blank lines.
- Keep every word, number, punctuation mark, and bracketed phrase exactly
  as written, in the same order. Do not fix spelling, grammar, or archaic
  usage. Do not add, remove, or reword anything.

Output ONLY the repaired text. No preamble, no explanation, no code fences."""

THINK_BLOCK = re.compile(r"\A\s*<think>.*?</think>\s*", re.S)
CODE_FENCE = re.compile(r"\A\s*```[a-z]*\n(.*?)\n```\s*\Z", re.S)


def strip_wrapping(raw: str) -> str:
    """Remove a leading <think> block (thinking models) and code fences."""
    raw = THINK_BLOCK.sub("", raw)
    m = CODE_FENCE.match(raw)
    return (m.group(1) if m else raw).strip()


def content_fingerprint(text: str) -> str:
    """The character stream minus whitespace and hyphens — invariant under
    the only two edits the task permits (line joining, dehyphenation)."""
    return re.sub(r"[\s\-­]+", "", text)


def words_preserved(original: str, proposed: str) -> bool:
    return content_fingerprint(original) == content_fingerprint(proposed)


def mechanical_justification(original: str, proposed: str) -> str:
    """Deterministic note for the reviewer — computed, not model-claimed."""
    o_lines = original.count("\n") + 1
    p_lines = proposed.count("\n") + 1
    o_score = score_body(original)
    p_score = score_body(proposed)
    return (
        f"unwrapped {o_lines} lines -> {p_lines}; "
        f"hard_wrap {o_score['hard_wrap']:.2f} -> {p_score['hard_wrap']:.2f}; "
        f"audit score {o_score['score']:.1f} -> {p_score['score']:.1f}"
    )


def load_body(chunk_id: str) -> str:
    trad, text_id, seq = chunk_id.split(".")
    path = CORPUS_DIR / trad / text_id / "chunks" / f"{seq}.toml"
    return tomllib.load(open(path, "rb"))["content"]["body"]


def find_targets(args) -> list[tuple[str, float]]:
    """(chunk_id, hard_wrap) for chunks at/above the hard-wrap floor."""
    if args.chunk_id:
        return [(cid, score_body(load_body(cid))["hard_wrap"]) for cid in args.chunk_id]
    _, chunk_rows = audit(args.tradition, args.text)
    targets = [
        (cid, sig["hard_wrap"])
        for cid, _score, sig in chunk_rows
        if sig["hard_wrap"] >= args.min_hard_wrap
    ]
    targets.sort(key=lambda t: -t[1])
    return targets[: args.limit] if args.limit else targets


def existing_pending(conn: sqlite3.Connection, model: str) -> set[str]:
    rows = conn.execute(
        "SELECT chunk_id FROM staged_cleanups "
        "WHERE status = 'pending' AND model = ? AND prompt_version = ?",
        (model, PROMPT_VERSION),
    ).fetchall()
    return {r[0] for r in rows}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--provider", default="ollama")
    ap.add_argument("--model", default="qwen3:8b")
    ap.add_argument("--max-tokens", type=int, default=6000)
    ap.add_argument("--min-hard-wrap", type=float, default=0.15)
    ap.add_argument("--tradition")
    ap.add_argument("--text")
    ap.add_argument("--chunk-id", action="append",
                    help="propose for a specific chunk id (repeatable; bypasses the audit sweep)")
    ap.add_argument("--limit", type=int, default=0, help="cap number of proposals (0 = all)")
    ap.add_argument("--delay", type=float, default=0.5, help="seconds between LLM calls")
    ap.add_argument("--dry-run", action="store_true", help="list targets, call no model, write nothing")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    targets = find_targets(args)
    if not targets:
        logger.info("no targets at or above the hard-wrap floor")
        return 0

    if args.dry_run:
        for cid, hw in targets:
            logger.info(f"  {hw:.2f}  {cid}")
        logger.info(f"\n{len(targets)} targets (dry-run; nothing proposed)")
        return 0

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON")
    skip = existing_pending(conn, args.model)

    staged = flagged = errors = 0
    for cid, hw in targets:
        if cid in skip:
            logger.info(f"  skip {cid} (pending proposal exists for this model+prompt)")
            continue
        body = load_body(cid)
        try:
            raw = call_llm(args.provider, args.model, SYSTEM_PROMPT, body,
                           max_tokens=args.max_tokens)
        except Exception as e:  # noqa: BLE001 — one bad call shouldn't kill the run
            logger.warning(f"  ERROR {cid}: {e}")
            errors += 1
            continue
        proposed = strip_wrapping(raw)
        if not proposed:
            logger.warning(f"  ERROR {cid}: empty proposal")
            errors += 1
            continue
        ok = words_preserved(body, proposed)
        conn.execute(
            """INSERT INTO staged_cleanups
                   (chunk_id, original_body, proposed_body, justification,
                    signal_score, words_preserved, status, model, prompt_version)
               VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
               ON CONFLICT(chunk_id, model, prompt_version)
                   WHERE status = 'pending' DO NOTHING""",
            (cid, body, proposed, mechanical_justification(body, proposed),
             hw, int(ok), args.model, PROMPT_VERSION),
        )
        conn.commit()
        staged += 1
        if not ok:
            flagged += 1
            logger.warning(f"  {cid}: staged but words_preserved=0 — model drifted; apply will refuse")
        else:
            logger.info(f"  {cid}: staged (hard_wrap {hw:.2f})")
        time.sleep(args.delay)

    conn.close()
    logger.info(f"\nstaged: {staged} ({flagged} flagged words_preserved=0) · errors: {errors}")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
