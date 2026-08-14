"""
flag_apparatus.py — queue chunk-level apparatus flags into staged_cleanups
(todo:495577b7, parent c3f479ff — "rule-parity fix").

Tag review (docs/ingest/11-tag-review.md, prompts/ingest/tag-review.md rule 1)
already keeps apparatus chunks out of the concept surface: a reviewer sees a
translator's preface or a footnote block and rejects every tag proposal on
it. But that verdict lives only as a trail of rejected staged_tags rows —
nothing marks the CHUNK itself as apparatus, so nothing stops the tagger from
proposing again next run, or the derived-parallels generator from picking the
chunk up if it ever acquires a stray accepted tag. This script writes that
chunk-level fact, using the existing staged_cleanups 'apparatus' status and
the reclassify->apparatus_drop review_actions path that docs/web-review/
cleanups.md already documents for the interactive deck (CleanupDeck ->
apparatus button). Nothing here is new schema or a new apply mechanism —
every row lands the same shape a human curator's "Apparatus..." click would
leave, so the existing owner-run apply gate (POST /api/apply, or the
guru-review web app) is what actually flips status to 'apparatus'.

Two sources, per the ticket:

SOURCE (a) — the guru-web todo:6e0c2a63 audit roll-up. That ticket is prose,
not a structured chunk-id list; only some of its findings name an exact
chunk or a numeric range. Those exact candidates are hardcoded below
(SOURCE_A_CANDIDATES). BUT: cross-checking them against staged_tags history
found the roll-up's one-line-per-range characterizations describe a
contamination PATTERN somewhere in the range, not "every chunk in this range
is 100% apparatus" — 67 of the 71 candidates already carry reviewer-ACCEPTED
EXPRESSES tags (dionysius-mystical-theology.001 alone has 16, including
apophatic_theology at score 3). Flagging those would silently drop
human-verified content from derive_parallels.py. So this is NOT a blind
mechanical transfer: each candidate is filtered at runtime against staged_tags
(zero accepted/pending/reassigned rows required) before it is queued. See
todo:495577b7 analysis entry 0 for the full accounting. Only 4 of 71 survive
the filter: heroic-enthusiasts-pt1.001-002, orphic-hymns.001, kalevala.273.

SOURCE (b) — the all-rejected staged_tags set: chunks where every tag
proposal was rejected (316 chunks, matching the ticket's count exactly; see
all_rejected_chunk_ids()). Each of the 316 was read (first ~700 chars) and
classified apparatus vs. taxonomy-blind per the tag-review rubric's apparatus
criteria (translator/editor front matter, footnote-numbered scholarly
apparatus, TOC, publication boilerplate, glossaries) — conservative default
is taxonomy-blind. 74 classified apparatus; the other 242 are genuine content
the taxonomy doesn't happen to score (recorded in
docs/summary/apparatus-rejected-audit.md so the review isn't lost). The
classification is hardcoded (SOURCE_B_APPARATUS) because it is judgement, not
re-derivable; at runtime each id is re-checked against the LIVE all-rejected
set as a drift guard (a chunk that has since gained an accepted tag is
skipped, never flagged).

Every row this script writes is QUEUE-ONLY: a pending staged_cleanups row
(original_body == proposed_body, i.e. no rewrite — the ask is a
classification, not an edit) plus an unapplied review_actions row
(action='reclassify', reclassify_to='apparatus_drop'). status only becomes
'apparatus' when the owner runs the existing apply gate. This script never
calls /api/apply and never flips status itself.

Usage:
    python3 scripts/flag_apparatus.py --dry-run        # report only
    python3 scripts/flag_apparatus.py --apply          # write pending rows
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

import tomllib

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from guru.corpus import resolve_chunk_path  # noqa: E402

DEFAULT_DB = PROJECT_ROOT / "data" / "guru.db"

REVIEWER = "agent:495577b7"
PROMPT_VERSION = "v1"

MODEL_SOURCE_A = "rollup:6e0c2a63"
MODEL_SOURCE_B = "judgement:495577b7"


# ── source (a): guru-web todo:6e0c2a63 audit roll-up ────────────────────────
#
# Every entry the roll-up gave an EXACT chunk id or numeric range for. Ranges
# the roll-up only described in prose ("~25/66 mandaean...", "Budge... in
# egyptian works", "Legge/Mueller... in zhuangzi + diamond-sutra") are
# deliberately left OUT — there is no chunk-id list to transcribe, and
# guessing one would be a verdict nobody earned by reading. Those remain
# unflagged; a follow-up audit that names exact chunks is the right way to
# pick them up (see the close note).

def _range(trad: str, text_id: str, lo: int, hi: int) -> list[str]:
    return [f"{trad}.{text_id}.{i:03d}" for i in range(lo, hi + 1)]


SOURCE_A_CANDIDATES: list[tuple[str, str]] = [
    (cid, "iamblichus.162-180: Taylor endnotes mislabeled as Chapter VIII continuations")
    for cid in _range("neoplatonism", "iamblichus-on-the-mysteries", 162, 180)
] + [
    ("gnosticism.gospel-of-philip.001", "gospel-of-philip.001: site header"),
    ("mesopotamian.descent-of-inanna.001", "descent-of-inanna.001: opens with navigation cruft"),
    ("sufism.masnavi-book-1.014", "masnavi.014: mostly footnotes"),
] + [
    (cid, "heroic-enthusiasts pt1.001-013: translator biography")
    for cid in _range("renaissance_hermeticism", "heroic-enthusiasts-pt1", 1, 13)
] + [
    (cid, "orphic-hymns.001-034: Taylor preface")
    for cid in _range("greek_mystery", "orphic-hymns", 1, 34)
] + [
    ("finnic.kalevala.273", "kalevala.273: name glossary"),
    ("christian_mysticism.dionysius-mystical-theology.001",
     "OCR 'Wheat is the Divine Gloom' in mystical-theology.001"),
]


# ── source (b): all-rejected staged_tags chunks, judgement-classified ───────
#
# Read (first ~700 chars of body) and classified against the tag-review
# rubric's apparatus criteria (prompts/ingest/tag-review.md rule 1):
# translator/editor front matter, footnote-numbered scholarly apparatus, TOC,
# publisher back-matter, glossaries. Conservative default is taxonomy-blind
# (real content the taxonomy doesn't score) — see
# docs/summary/apparatus-rejected-audit.md for the full 316-chunk accounting,
# including the 242 taxonomy-blind chunks this list deliberately excludes.

SOURCE_B_APPARATUS: dict[str, str] = {}

for _cid in [
    "buddhism.dhammapada-chapter-04.003",
    "buddhism.dhammapada-chapter-10.004",
    "buddhism.dhammapada-chapter-15.003",
    "buddhism.dhammapada-chapter-17.002",
]:
    SOURCE_B_APPARATUS[_cid] = "translator citation-fragment footnote (SBE-style endnote)"

for _cid in [
    "egyptian.egyptian-book-of-the-dead-index.001",
    "egyptian.egyptian-heaven-and-hell.001",
]:
    SOURCE_B_APPARATUS[_cid] = "Budge title page / publication credit"

for _cid in [
    "egyptian.egyptian-book-of-the-dead-index.004",
    "egyptian.egyptian-book-of-the-dead-index.005",
    "egyptian.egyptian-book-of-the-dead-index.007",
    "egyptian.egyptian-book-of-the-dead-index.012",
    "egyptian.egyptian-book-of-the-dead-index.013",
    "egyptian.egyptian-book-of-the-dead-index.018",
    "egyptian.egyptian-book-of-the-dead-index.036",
    "egyptian.egyptian-book-of-the-dead-index.044",
    "egyptian.egyptian-book-of-the-dead-index.107",
    "egyptian.egyptian-book-of-the-dead-index.116",
    "egyptian.egyptian-book-of-the-dead-index.241",
    "egyptian.egyptian-book-of-the-dead-index.243",
    "egyptian.egyptian-book-of-the-dead-index.245",
    "egyptian.egyptian-book-of-the-dead-index.251",
    "egyptian.egyptian-book-of-the-dead-index.252",
    "egyptian.egyptian-book-of-the-dead-index.255",
    "egyptian.egyptian-book-of-the-dead-index.258",
    "egyptian.egyptian-book-of-the-dead-index.274",
    "egyptian.egyptian-book-of-the-dead-index.311",
]:
    SOURCE_B_APPARATUS[_cid] = "Budge scholarly Introduction essay / bibliographic footnotes"

for _cid in ["finnic.kalevala.272", "finnic.kalevala.273", "finnic.kalevala.274", "finnic.kalevala.275"]:
    SOURCE_B_APPARATUS[_cid] = "back-matter mythological-name glossary"

SOURCE_B_APPARATUS["jewish_mysticism.enoch-charles-1917.006"] = \
    "R.H. Charles's scholarly Introduction (apocalyptic-literature dating discussion)"

for _cid in _range("mandaean", "gnostic-john-baptizer-1", 18, 32):
    SOURCE_B_APPARATUS[_cid] = "Mead numbered scholarly footnotes (dense citation apparatus)"
for _cid in _range("mandaean", "gnostic-john-baptizer-2", 7, 10):
    SOURCE_B_APPARATUS[_cid] = "Mead numbered scholarly footnotes (dense citation apparatus)"
for _cid in _range("mandaean", "gnostic-john-baptizer-3", 18, 24):
    SOURCE_B_APPARATUS[_cid] = "Mead numbered scholarly footnotes (dense citation apparatus)"

SOURCE_B_APPARATUS["neoplatonism.iamblichus-on-the-mysteries.217"] = \
    "publisher's book catalogue (Bertram Dobell back-matter advertisement)"
SOURCE_B_APPARATUS["neoplatonism.iamblichus-on-the-mysteries.218"] = \
    "publisher's book catalogue (Bertram Dobell back-matter advertisement)"

SOURCE_B_APPARATUS["norse.poetic-edda-hovamol.001"] = "Bellows editor's introductory note"
SOURCE_B_APPARATUS["norse.poetic-edda-voluspo.001"] = "Bellows editor's introductory note"

SOURCE_B_APPARATUS["renaissance_hermeticism.heroic-enthusiasts-pt1.001"] = \
    "translator's preface + errata (also in source a)"
SOURCE_B_APPARATUS["renaissance_hermeticism.heroic-enthusiasts-pt1.002"] = \
    "biographer's essay on Bruno's birthplace, not the dialogue text (also in source a)"

for _cid in [
    "western_esoteric.secret-teachings-of-all-ages.001",
    "western_esoteric.secret-teachings-of-all-ages.002",
    "western_esoteric.secret-teachings-of-all-ages.003",
]:
    SOURCE_B_APPARATUS[_cid] = "Manly P. Hall's author preface / acknowledgments / dedication"

SOURCE_B_APPARATUS["western_esoteric.tertium-organum.001"] = "title page + sacred-texts.com scan credit"
SOURCE_B_APPARATUS["western_esoteric.tertium-organum.003"] = "table of contents"
SOURCE_B_APPARATUS["western_esoteric.tertium-organum.006"] = "author's preface to the second edition"
SOURCE_B_APPARATUS["western_esoteric.tertium-organum.007"] = "author's preface to the second edition"
SOURCE_B_APPARATUS["western_esoteric.tertium-organum.172"] = "bibliographic footnote list"
SOURCE_B_APPARATUS["western_esoteric.tertium-organum.198"] = "bibliographic footnote list"
SOURCE_B_APPARATUS["western_esoteric.tertium-organum.225"] = "bare chapter/page-number pagination list"

SOURCE_B_APPARATUS["zoroastrianism.bundahishn.001"] = "West's scholarly Introduction to Pahlavi Texts"
SOURCE_B_APPARATUS["zoroastrianism.bundahishn.002"] = "West's scholarly Introduction to Pahlavi Texts"

assert len(SOURCE_B_APPARATUS) == 74, f"expected 74 source-b apparatus chunks, got {len(SOURCE_B_APPARATUS)}"


# ── DB reads ─────────────────────────────────────────────────────────────

def all_rejected_chunk_ids(conn: sqlite3.Connection) -> set[str]:
    """Chunks where every staged_tags proposal is status='rejected' — i.e.
    zero pending/accepted/reassigned rows survive. Matches the ticket's 316
    count exactly as of 2026-08-13."""
    rows = conn.execute(
        """SELECT chunk_id FROM staged_tags
             GROUP BY chunk_id
            HAVING SUM(CASE WHEN status != 'rejected' THEN 1 ELSE 0 END) = 0"""
    ).fetchall()
    return {r[0] for r in rows}


def has_surviving_tags(conn: sqlite3.Connection, chunk_id: str) -> bool:
    """True if the chunk has any staged_tags row that isn't rejected —
    accepted, pending, or reassigned. Any of these means a human or the
    model itself found real content here; apparatus must never claim it."""
    row = conn.execute(
        "SELECT 1 FROM staged_tags WHERE chunk_id = ? AND status != 'rejected' LIMIT 1",
        (chunk_id,),
    ).fetchone()
    return row is not None


def already_staged(conn: sqlite3.Connection, chunk_id: str) -> bool:
    """True if staged_cleanups already has a pending or apparatus row for
    this chunk, from ANY source/model. The partial unique index on
    staged_cleanups is keyed by (chunk_id, model, prompt_version), which
    would NOT stop source (a) and source (b) from double-queuing the same
    chunk under their different model labels — so idempotency here is an
    explicit app-level check, not just the DB constraint."""
    row = conn.execute(
        "SELECT 1 FROM staged_cleanups WHERE chunk_id = ? AND status IN ('pending', 'apparatus') LIMIT 1",
        (chunk_id,),
    ).fetchone()
    return row is not None


def load_body(chunk_id: str) -> str | None:
    p = resolve_chunk_path(chunk_id)
    if p is None:
        return None
    with open(p, "rb") as f:
        return tomllib.load(f)["content"]["body"]


def review_action_exists(conn: sqlite3.Connection, client_action_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM review_actions WHERE client_action_id = ? LIMIT 1",
        (client_action_id,),
    ).fetchone()
    return row is not None


# ── staging ──────────────────────────────────────────────────────────────

def stage_apparatus_flag(
    conn: sqlite3.Connection, chunk_id: str, reason: str, model: str, dry_run: bool,
    staged_this_run: set[str],
) -> str:
    """Insert a pending staged_cleanups row (no rewrite — original ==
    proposed) plus its already-queued reclassify->apparatus_drop
    review_actions row. Returns a status string for the caller's tally.
    Nothing here flips status to 'apparatus'; that is the owner's apply
    gate, exactly as it is for the web deck's own Apparatus... button.

    `staged_this_run` is the set of chunk ids this function has already
    decided to stage earlier in the SAME run (PR #64 review finding 5).
    already_staged() only sees committed DB rows, so without this, source
    (a) staging a chunk in dry-run mode (which writes nothing) is invisible
    to source (b)'s already_staged() check a moment later — three chunks
    overlap both sources — and dry-run's count silently diverges from
    --apply's. Checking staged_this_run alongside already_staged() makes
    both modes agree, since dry-run and apply both add to it identically."""
    if chunk_id in staged_this_run or already_staged(conn, chunk_id):
        return "already_staged"

    body = load_body(chunk_id)
    if body is None:
        logger.warning(f"  SKIP {chunk_id}: chunk body not found on disk")
        return "missing_body"

    client_action_id = f"apparatus-flag-{chunk_id}"
    if review_action_exists(conn, client_action_id):
        # staged_cleanups row is missing but the action already exists —
        # should not happen outside a partial prior run; don't double-file.
        return "already_staged"

    staged_this_run.add(chunk_id)

    if dry_run:
        return "would_stage"

    cur = conn.execute(
        """INSERT INTO staged_cleanups
               (chunk_id, original_body, proposed_body, justification,
                signal_score, words_preserved, status, model, prompt_version)
           VALUES (?, ?, ?, ?, 1.0, 1, 'pending', ?, ?)""",
        (chunk_id, body, body, reason, model, PROMPT_VERSION),
    )
    target_id = cur.lastrowid
    conn.execute(
        """INSERT INTO review_actions
               (target_id, target_table, action, reassign_to, reclassify_to,
                reviewer, client_action_id)
           VALUES (?, 'staged_cleanups', 'reclassify', NULL, 'apparatus_drop', ?, ?)""",
        (target_id, REVIEWER, client_action_id),
    )
    conn.commit()
    return "staged"


# ── main ─────────────────────────────────────────────────────────────────

def run(db_path: Path, dry_run: bool) -> int:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    tally: dict[str, int] = {}
    # Chunk ids staged (or, in dry-run, that would be staged) so far in THIS
    # run — shared across both sources so dry-run and --apply agree on the
    # 3-chunk source-a/source-b overlap (PR #64 review finding 5).
    staged_this_run: set[str] = set()

    def bump(key: str) -> None:
        tally[key] = tally.get(key, 0) + 1

    # source (a) — filtered mechanical transfer
    logger.info(f"source (a): {len(SOURCE_A_CANDIDATES)} candidates from todo:6e0c2a63")
    a_excluded = 0
    for chunk_id, reason in SOURCE_A_CANDIDATES:
        if has_surviving_tags(conn, chunk_id):
            a_excluded += 1
            continue
        outcome = stage_apparatus_flag(conn, chunk_id, f"[source a: todo:6e0c2a63] {reason}",
                                       MODEL_SOURCE_A, dry_run, staged_this_run)
        bump(f"a_{outcome}")
        if outcome in ("staged", "would_stage"):
            logger.info(f"  {chunk_id}: {reason}")
    logger.info(f"source (a): {a_excluded} excluded (already carry a surviving staged_tags row)")

    # source (b) — judgement pass, re-verified against the live all-rejected set
    live_rejected = all_rejected_chunk_ids(conn)
    logger.info(f"\nsource (b): all-rejected chunks live = {len(live_rejected)} "
                f"(ticket cites 316); apparatus-classified = {len(SOURCE_B_APPARATUS)}")
    b_drifted = 0
    for chunk_id, reason in sorted(SOURCE_B_APPARATUS.items()):
        if chunk_id not in live_rejected:
            # a tag has been accepted/queued for this chunk since the
            # judgement pass — the drift guard refuses to flag it.
            b_drifted += 1
            logger.warning(f"  SKIP {chunk_id}: no longer all-rejected (staged_tags state changed)")
            continue
        outcome = stage_apparatus_flag(conn, chunk_id, f"[source b: all-rejected judgement pass] {reason}",
                                       MODEL_SOURCE_B, dry_run, staged_this_run)
        bump(f"b_{outcome}")
        if outcome in ("staged", "would_stage"):
            logger.info(f"  {chunk_id}: {reason}")
    if b_drifted:
        logger.warning(f"source (b): {b_drifted} skipped (drifted off the all-rejected set)")

    conn.close()

    verb = "would stage" if dry_run else "staged"
    logger.info(f"\n{verb}: a={tally.get('a_staged', 0) + tally.get('a_would_stage', 0)}  "
                f"b={tally.get('b_staged', 0) + tally.get('b_would_stage', 0)}  "
                f"already-queued (skipped, idempotent)="
                f"{tally.get('a_already_staged', 0) + tally.get('b_already_staged', 0)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="report what would be staged; write nothing")
    mode.add_argument("--apply", dest="do_apply", action="store_true",
                      help="write pending staged_cleanups + queued review_actions rows "
                           "(NOT the owner apply gate — status stays 'pending')")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    return run(args.db, dry_run=not args.do_apply)


if __name__ == "__main__":
    sys.exit(main())
