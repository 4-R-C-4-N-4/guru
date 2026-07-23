"""
audit_readability.py — heuristic readability audit of chunk bodies (todo:82e3a09d).

guru-web serves chunk bodies verbatim to the public reader (guru-ai.org/read),
so pipeline-era formatting artifacts are now user-facing. This scanner scores
every corpus/*/*/chunks/*.toml body on cheap textual signals of damage and
ranks texts by how badly they read, to size the curation problem BEFORE any
hand- or model-driven cleanup (the staged_cleanups phase is its own ticket).

Read-only: touches no TOML and no DB. Signals, each normalized 0..1 per chunk:

  hard_wrap      intra-paragraph newlines where a short line continues in
                 lowercase on the next — OCR/plaintext hard wrapping
  hyphen_break   line ends with `-` and the next line starts lowercase —
                 a word split by a line break
  caps_runs      whole lines in ALL CAPS (>= 12 chars) — shouty headers
                 baked into body text
  page_marks     leftover page apparatus: [p. 143], p. 143, [Pg 12],
                 standalone bare-number lines
  footnotes      inline footnote markers: [1], {1}, ^1, dagger/asterisk runs
  brackets       editorial/transliteration noise: [...], [sic], (?), and
                 general bracket density
  dot_leaders    ".... "/"____" leader runs — TOC and fill artifacts
  whitespace     multi-space runs mid-line and 3+ blank-line gaps

score = weighted sum scaled to 0-100 (higher = worse). The absolute number is
only meaningful for ranking; the per-signal columns say what KIND of damage a
text has, which decides the fix (regex strip vs. model rewrite vs. re-ingest).

Usage:
    python3 scripts/audit_readability.py                       # ranked text table
    python3 scripts/audit_readability.py --tradition egyptian  # one tradition
    python3 scripts/audit_readability.py --worst 20            # top offender chunks
    python3 scripts/audit_readability.py --format json         # machine output
    python3 scripts/audit_readability.py --format markdown     # docs snapshot
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import tomllib

PROJECT_ROOT = Path(__file__).parent.parent
CORPUS_DIR = PROJECT_ROOT / "corpus"

# ── signal patterns ──────────────────────────────────────────────────────────

# Hard wrap: a "short" line whose successor starts lowercase is prose broken
# mid-sentence. 65 chars is well under the corpus's natural paragraph widths.
HARD_WRAP_MAX_LEN = 65

CAPS_LINE = re.compile(r"^[^a-z]{12,}$")
HAS_LETTER = re.compile(r"[A-Z]")

PAGE_MARK = re.compile(
    r"\[\s*[Pp]g?\.?\s*\d+\s*\]"      # [p. 143] [Pg 12]
    r"|(?:^|\s)[Pp]\.\s?\d+(?:\s|$)"  # bare p. 143
)
BARE_NUMBER_LINE = re.compile(r"^\s*\d{1,4}\s*$")

FOOTNOTE_MARK = re.compile(
    r"\[\d{1,3}\]"          # [1]
    r"|\{\d{1,3}\}"         # {1}
    r"|\^\d{1,3}"           # ^1
    r"|[*†‡]{2,}"           # symbol runs
)

BRACKET_NOISE = re.compile(
    r"\[\s*(?:\.\.\.|…|sic|\?)\s*\]"  # [...] [sic] [?]
    r"|\(\s*\?\s*\)"                  # (?)
)
ANY_BRACKET = re.compile(r"[\[\]]")

DOT_LEADER = re.compile(r"\.{4,}|_{4,}")

MULTI_SPACE = re.compile(r"\S {2,}\S")
BLANK_GAP = re.compile(r"\n{4,}")

WEIGHTS = {
    "hard_wrap":    30.0,
    "hyphen_break": 15.0,
    "caps_runs":    10.0,
    "page_marks":   15.0,
    "footnotes":    10.0,
    "brackets":     10.0,
    "dot_leaders":   5.0,
    "whitespace":    5.0,
}


def _per_kchars(n: int, body_len: int, saturate: float) -> float:
    """Occurrences per 1000 chars, clamped to 0..1 at `saturate`/kchar."""
    if body_len == 0:
        return 0.0
    rate = n * 1000.0 / body_len
    return min(rate / saturate, 1.0)


def score_body(body: str) -> dict[str, float]:
    """Score one chunk body. Returns per-signal 0..1 values plus 'score' 0-100."""
    lines = body.split("\n")
    n_lines = max(len(lines), 1)

    hard_wraps = 0
    hyphen_breaks = 0
    caps = 0
    bare_numbers = 0
    for i, line in enumerate(lines):
        s = line.rstrip()
        nxt = lines[i + 1].lstrip() if i + 1 < len(lines) else ""
        if s and nxt and len(s) <= HARD_WRAP_MAX_LEN and nxt[:1].islower():
            if s.endswith("-"):
                hyphen_breaks += 1
            else:
                hard_wraps += 1
        if CAPS_LINE.match(s.strip()) and HAS_LETTER.search(s):
            caps += 1
        if BARE_NUMBER_LINE.match(s):
            bare_numbers += 1

    body_len = len(body)
    signals = {
        "hard_wrap":    min(hard_wraps / n_lines * 3.0, 1.0),
        "hyphen_break": min(hyphen_breaks / n_lines * 10.0, 1.0),
        "caps_runs":    min(caps / n_lines * 10.0, 1.0),
        "page_marks":   _per_kchars(len(PAGE_MARK.findall(body)) + bare_numbers, body_len, 3.0),
        "footnotes":    _per_kchars(len(FOOTNOTE_MARK.findall(body)), body_len, 5.0),
        "brackets":     _per_kchars(
            len(BRACKET_NOISE.findall(body)) * 3 + len(ANY_BRACKET.findall(body)) // 2,
            body_len, 10.0),
        "dot_leaders":  _per_kchars(len(DOT_LEADER.findall(body)), body_len, 2.0),
        "whitespace":   _per_kchars(
            len(MULTI_SPACE.findall(body)) + 3 * len(BLANK_GAP.findall(body)),
            body_len, 10.0),
    }
    signals["score"] = sum(WEIGHTS[k] * v for k, v in signals.items() if k in WEIGHTS)
    return signals


# ── corpus walk ──────────────────────────────────────────────────────────────

@dataclass
class TextReport:
    tradition: str
    text_id: str
    chunks: int = 0
    total: float = 0.0
    worst_score: float = 0.0
    worst_chunk: str = ""
    signal_totals: dict[str, float] = field(default_factory=dict)

    @property
    def mean(self) -> float:
        return self.total / self.chunks if self.chunks else 0.0

    def dominant_signals(self, n: int = 3) -> list[str]:
        ranked = sorted(self.signal_totals.items(), key=lambda kv: -kv[1])
        return [k for k, v in ranked[:n] if v / max(self.chunks, 1) >= 0.05]


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


def audit(tradition: str | None = None, text: str | None = None):
    texts: dict[str, TextReport] = {}
    chunk_rows: list[tuple[str, float, dict[str, float]]] = []
    for trad, text_dir, path in iter_chunk_files(tradition, text):
        data = tomllib.load(open(path, "rb"))
        body = data["content"]["body"]
        cid = data["chunk"]["id"]
        s = score_body(body)
        chunk_rows.append((cid, s["score"], s))
        key = f"{trad}/{text_dir}"
        rep = texts.setdefault(key, TextReport(tradition=trad, text_id=text_dir))
        rep.chunks += 1
        rep.total += s["score"]
        for k in WEIGHTS:
            rep.signal_totals[k] = rep.signal_totals.get(k, 0.0) + s[k]
        if s["score"] > rep.worst_score:
            rep.worst_score = s["score"]
            rep.worst_chunk = cid
    return texts, chunk_rows


# ── output ───────────────────────────────────────────────────────────────────

def print_table(texts: dict[str, TextReport], min_score: float, markdown: bool) -> None:
    ranked = sorted(texts.values(), key=lambda r: -r.mean)
    shown = [r for r in ranked if r.mean >= min_score]
    out = sys.stdout
    if markdown:
        out.write("| text | chunks | mean | worst (chunk) | dominant signals |\n")
        out.write("|---|---|---|---|---|\n")
        for r in shown:
            out.write(
                f"| {r.tradition}/{r.text_id} | {r.chunks} | {r.mean:.1f} "
                f"| {r.worst_score:.1f} ({r.worst_chunk}) "
                f"| {', '.join(r.dominant_signals()) or '—'} |\n")
    else:
        out.write(f"{'text':52} {'chunks':>6} {'mean':>6} {'worst':>6}  dominant signals\n")
        for r in shown:
            out.write(
                f"{r.tradition + '/' + r.text_id:52} {r.chunks:>6} {r.mean:>6.1f} "
                f"{r.worst_score:>6.1f}  {', '.join(r.dominant_signals()) or '—'}\n")
    hidden = len(ranked) - len(shown)
    if hidden:
        out.write(f"\n({hidden} texts below --min-score {min_score:g} not shown)\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tradition", help="limit to one tradition directory")
    ap.add_argument("--text", help="limit to one text directory")
    ap.add_argument("--format", choices=["table", "json", "markdown"], default="table")
    ap.add_argument("--min-score", type=float, default=1.0,
                    help="hide texts with mean score below this (table/markdown; default 1.0)")
    ap.add_argument("--worst", type=int, default=0, metavar="N",
                    help="also list the N worst individual chunks")
    args = ap.parse_args()

    texts, chunk_rows = audit(args.tradition, args.text)
    if not texts:
        print("no chunks found", file=sys.stderr)
        return 1

    if args.format == "json":
        payload = {
            "texts": [
                {
                    "tradition": r.tradition, "text_id": r.text_id, "chunks": r.chunks,
                    "mean": round(r.mean, 2), "worst_score": round(r.worst_score, 2),
                    "worst_chunk": r.worst_chunk,
                    "signals": {k: round(v / r.chunks, 3) for k, v in r.signal_totals.items()},
                }
                for r in sorted(texts.values(), key=lambda r: -r.mean)
            ],
        }
        if args.worst:
            payload["worst_chunks"] = [
                {"id": cid, "score": round(sc, 2)}
                for cid, sc, _ in sorted(chunk_rows, key=lambda t: -t[1])[: args.worst]
            ]
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    print_table(texts, args.min_score, markdown=args.format == "markdown")
    if args.worst:
        print(f"\nworst {args.worst} chunks:")
        for cid, sc, sig in sorted(chunk_rows, key=lambda t: -t[1])[: args.worst]:
            tops = sorted(
                ((k, v) for k, v in sig.items() if k in WEIGHTS), key=lambda kv: -kv[1]
            )[:3]
            print(f"  {sc:6.1f}  {cid}  ({', '.join(f'{k}={v:.2f}' for k, v in tops if v > 0)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
