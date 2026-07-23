"""
clean_bodies.py — V8 in-place boilerplate strip (todo:88a28e67).

Applies the pattern classes P1-P6 from docs/summary/boilerplate-audit.md to
chunk bodies in corpus/*/*/chunks/*.toml. Strictly id-preserving: never drops,
renumbers, or merges chunks — whole-chunk apparatus work belongs to
todo:50438e23. Recomputes chunk.token_count (chunkers.tokens, the pipeline
tokenizer) and mirrors the new count into nodes.metadata_json in the live DB.

Strips operate at paragraph / sentence / inline granularity:
  P1  trailing `Next:` / `Previous:` nav paragraphs
  P2  site-header paragraphs (Sacred-Texts breadcrumb, Index Previous Next)
  P3  digitization-credit sentences (scanned at..., redactor, public domain...)
  P4  inline [Pg N] page markers
  P5  trailing Project Gutenberg license block
  P6  Errata paragraphs
  P7  inline {p. roman} page markers, incl. paragraph-split and OCR-digit
      forms ({p.\n\nxcli}, {p. 1xxv}) — egyptian book-of-the-dead
  P8  standalone `p. NN` page-number paragraphs — mandaean john-baptizer
  P9  inline [N] footnote references (notes are not in the corpus; the
      leaked mandaean note BLOCKS are whole-chunk work, todo:50438e23)

P7-P9 added by the readability audit (todo:d5ad220f / audit report
docs/summary/readability-audit.md). Reconstruction brackets like
[comrade] / [offer] are content and MUST survive — P9 matches digits only.

Guard: a chunk whose cleaned body would shrink below (1 - --max-shrink) of the
original is refused and reported, never written (audit lists the 3 title-page
chunks expected to trip this; pass --allow-id to confirm them individually).

Usage:
    python3 scripts/clean_bodies.py --dry-run            # diffs to stdout
    python3 scripts/clean_bodies.py --apply              # write TOMLs + DB
    python3 scripts/clean_bodies.py --apply --tradition egyptian
    python3 scripts/clean_bodies.py --apply --allow-id jewish_mysticism.enoch-charles-1917.001
"""

import argparse
import difflib
import json
import logging
import re
import sqlite3
import sys
from pathlib import Path

import tomllib
import tomli_w

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from chunkers.tokens import count_tokens  # noqa: E402

logger = logging.getLogger(__name__)

CORPUS_DIR = PROJECT_ROOT / "corpus"
DEFAULT_DB = PROJECT_ROOT / "data" / "guru.db"

# ── pattern classes (docs/summary/boilerplate-audit.md) ──────────────────────

# P1: whole paragraph is a nav pointer. Length-capped so a legitimate
# paragraph that merely contains "Next:" can never match.
P1_NAV_PARA = re.compile(r"^(?:Next|Previous)\s*:\s.{0,120}$", re.S)

# P2: site-header paragraph — breadcrumb/title block. Includes the hyphenated
# "Sacred-Texts" form guru-web's NAV_PREFIX misses (the V8 reproducer).
P2_HEADER_PARA = re.compile(
    r"^(?:Sacred[- ][Tt]exts?\b|Index\s+Previous\s+Next\b)", re.I
)
P2_MAX_LEN = 500  # header paragraphs are short; content never matches anyway

# P6: errata paragraph (correction lists).
P6_ERRATA_PARA = re.compile(r"^Errata\b", re.I)
P6_MAX_LEN = 1500

# P5: everything from the Gutenberg end-of-book marker to EOF is license text.
P5_GUTENBERG_TAIL = re.compile(r"End of (?:the )?Project Gutenberg.*\Z", re.S | re.I)

# P3: digitization-credit sentences, each bounded so a runaway match is
# impossible. Applied inside paragraphs (title pages mix credits with content).
P3_SENTENCES = [
    # domain names contain dots, so match host explicitly, then run to the
    # sentence-ending period ("scanned at www.sacred-texts.com, Oct-Dec 2000.")
    re.compile(r"(?:\[\d{4}\]\s*)?[Ss]canned(?:\s+and\s+proofed)?\s+at\s+(?:www\.)?[\w-]+(?:\.[\w-]+)+[^.\n]{0,80}\."),
    re.compile(r"J\.\s?B\.\s?Hare,?\s+[Rr]edactor\.?"),
    re.compile(r"(?:Proofed|Formatted|Proofed and formatted)\s+by\s+[^.]{0,80}\."),
    re.compile(r"This text is in the public domain[^.]{0,80}\.?"),
    re.compile(r"This is a Unicode version of\s+[^.]{0,120}\."),
    re.compile(r"A more complete e-?text\s+[^.]{0,120}\."),
    # translator-credit remnant left when P2 splits a header mid-name
    # ("King Translator (from The Seven Tablets of Creation, London 1902)")
    re.compile(r"\b[A-Z][\w.]*\s+Translator\s+\(from\s[^)]{0,120}\)\.?"),
]

# P4: inline Gutenberg page markers. Replacement is a single space; split-word
# artifacts around removed markers are pre-existing ingest damage (50438e23).
P4_PG_MARKER = re.compile(r"\s*\[[Pp]g\.?\s?\d+\]\s*")

# P1b: nav pointer glued to the END of a content paragraph rather than its own
# paragraph ("…Museum [1895] … Oct-Dec 2000. Next: Preface"). Tail-anchored
# with the same length cap as P1.
P1B_NAV_TAIL = re.compile(r"\s*(?:Next|Previous)\s*:\s[^\n]{0,80}$")

# P7: sacred-texts {p. roman} page markers. The marker frequently splits
# across a paragraph boundary ("…a cake.] {p.\n\nxcli} given unto thee") so
# it must be stripped BEFORE the paragraph split, like P5. OCR sometimes
# reads roman 'l' as '1' ({p. 1xxv}), hence digits in the numeral class.
# The closing brace is optional so a truncated marker still dies.
P7_PAGE_CURLY = re.compile(r"\s*\{p\.\s*[ivxlcdm0-9]{0,12}\}?\s*", re.I)

# P7b: the orphaned second half of a {p. roman} marker that chunking split
# ACROSS chunks — the "{p." tail landed at the end of the previous chunk
# (P7's optional brace eats it) and the body starts "lxvii} supported by…".
# Anchored to body start; roman/OCR-digit chars + } only.
P7B_LEAD_ORPHAN = re.compile(r"^\s*[ivxlcdm0-9]{1,12}\}\s*", re.I)

# P8: a paragraph that is nothing but a printed page number ("p. 81").
P8_PAGE_PARA = re.compile(r"^p\.\s?\d{1,4}$", re.I)

# P9: inline numeric footnote references ("the whole [1]," / "G eta[1]").
# Digits only — bracketed WORDS are translator reconstructions (gilgamesh
# "[shall ye listen]", egyptian "[offer]") and are content.
P9_FOOTNOTE_REF = re.compile(r"\s*\[\d{1,3}\]")

# P9 exclusion: texts where bracketed numbers ARE content. In the Timaeus,
# [1] [2] [3] [4] [9] [8] [27] gloss the harmonic-proportion values of the
# world-soul division (the Platonic lambda) — dry-run caught them being
# stripped as refs (todo:d5ad220f).
P9_EXCLUDE_TEXTS = {"plato-timaeus"}

PARA_SEP = re.compile(r"\n{2,}")


def clean_body(body: str, *, strip_footnote_refs: bool = True) -> str:
    # P5 first: the license tail may contain paragraphs P1/P2 would then see.
    body = P5_GUTENBERG_TAIL.sub("", body)
    # P7 before the paragraph split — the {p. roman} marker spans paragraph
    # boundaries, which no per-paragraph pass can see. A single space keeps
    # the two rejoined halves from gluing into one word.
    body = P7_PAGE_CURLY.sub(" ", body)
    body = P7B_LEAD_ORPHAN.sub("", body, count=1)

    paras = PARA_SEP.split(body)
    kept = []
    prev_was_nav = False
    for idx, p in enumerate(paras):
        s = p.strip()
        if not s:
            continue
        if P1_NAV_PARA.match(s):
            prev_was_nav = True
            continue
        # P1c: orphaned next-chapter TITLE — chunking splits the nav line
        # "Next: Chapter II. On Earnestness." into a nav paragraph plus a
        # title paragraph (at chunk ends AND at mid-chunk page boundaries,
        # e.g. boehme). A title-short paragraph directly after dropped nav is
        # part of the nav — the real heading follows in the source text.
        if prev_was_nav and len(s) <= 60 \
                and len(s.split()) <= 10 and not s.endswith(":"):
            # stay armed: nav apparatus can chain ('Next: X.' / 'I.' /
            # '<title>') — disarms at the first paragraph that fails the
            # title guards
            continue
        prev_was_nav = False
        if len(s) <= P2_MAX_LEN and P2_HEADER_PARA.match(s):
            continue
        if len(s) <= P6_MAX_LEN and P6_ERRATA_PARA.match(s):
            continue
        if P8_PAGE_PARA.match(s):
            continue
        for pat in P3_SENTENCES:
            s = pat.sub(" ", s)
        s = P4_PG_MARKER.sub(" ", s)
        if strip_footnote_refs:
            s = P9_FOOTNOTE_REF.sub("", s)
        before_tail = s
        s = P1B_NAV_TAIL.sub("", s)
        # an inline nav tail also arms P1c: the orphaned next-chapter title
        # can follow a paragraph that merely ENDED in the nav pointer
        prev_was_nav = s != before_tail
        s = re.sub(r"[ \t]{2,}", " ", s).strip()
        if s:
            kept.append(s)
        else:
            # paragraph vanished entirely under strips — also arms P1c
            prev_was_nav = True
    return "\n\n".join(kept)


def iter_chunk_files(tradition: str | None, text: str | None):
    for meta_p in sorted(CORPUS_DIR.glob("*/*/metadata.toml")):
        trad_dir = meta_p.parent.parent.name
        text_dir = meta_p.parent.name
        if tradition and trad_dir != tradition:
            continue
        if text and text_dir != text:
            continue
        for ct in sorted((meta_p.parent / "chunks").glob("*.toml")):
            yield trad_dir, text_dir, ct


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="print diffs, write nothing")
    mode.add_argument("--apply", action="store_true", help="write TOMLs and update DB token counts")
    ap.add_argument("--tradition", help="limit to one tradition directory")
    ap.add_argument("--text", help="limit to one text directory")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--max-shrink", type=float, default=0.25,
                    help="refuse a clean removing more than this fraction of a body (default 0.25)")
    ap.add_argument("--allow-id", action="append", default=[],
                    help="chunk id exempted from the shrink guard (repeatable)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    changed, refused = [], []
    per_tradition = {}
    for trad, text, path in iter_chunk_files(args.tradition, args.text):
        data = tomllib.load(open(path, "rb"))
        old = data["content"]["body"]
        new = clean_body(old, strip_footnote_refs=text not in P9_EXCLUDE_TEXTS)
        if new == old:
            continue
        cid = data["chunk"]["id"]
        if len(new) < (1 - args.max_shrink) * len(old) and cid not in args.allow_id:
            refused.append((cid, len(old), len(new)))
            continue
        if args.dry_run:
            diff = difflib.unified_diff(
                old.splitlines(keepends=True), new.splitlines(keepends=True),
                fromfile=f"a/{cid}", tofile=f"b/{cid}",
            )
            sys.stdout.writelines(diff)
            sys.stdout.write("\n")
        else:
            data["content"]["body"] = new
            data["chunk"]["token_count"] = count_tokens(new)
            with open(path, "wb") as f:
                tomli_w.dump(data, f)
        changed.append((cid, len(old), len(new)))
        per_tradition.setdefault(trad, 0)
        per_tradition[trad] += 1

    if args.apply and changed:
        conn = sqlite3.connect(args.db)
        n_db = 0
        for cid, _, _ in changed:
            row = conn.execute(
                "SELECT metadata_json FROM nodes WHERE id = ? AND type = 'chunk'", (cid,)
            ).fetchone()
            if row is None:
                logger.warning(f"  {cid}: not in nodes — TOML cleaned, DB untouched")
                continue
            meta = json.loads(row[0] or "{}")
            # body lives only in the TOMLs; the DB mirror is token_count
            toml_path = CORPUS_DIR / cid.split(".")[0] / cid.split(".")[1] / "chunks" / f"{cid.split('.')[2]}.toml"
            meta["token_count"] = tomllib.load(open(toml_path, "rb"))["chunk"]["token_count"]
            conn.execute(
                "UPDATE nodes SET metadata_json = ? WHERE id = ?",
                (json.dumps(meta, ensure_ascii=False), cid),
            )
            n_db += 1
        conn.commit()
        conn.close()
        logger.info(f"DB: {n_db} nodes.metadata_json token_counts updated")

    logger.info(f"\nchanged: {len(changed)} chunks across {len(per_tradition)} traditions")
    for t, n in sorted(per_tradition.items()):
        logger.info(f"  {t}: {n}")
    if refused:
        logger.warning(f"REFUSED by shrink guard ({len(refused)}) — confirm with --allow-id:")
        for cid, lo, ln in refused:
            logger.warning(f"  {cid}: {lo} -> {ln} chars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
