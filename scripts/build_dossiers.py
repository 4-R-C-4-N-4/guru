"""
build_dossiers.py — Pass D driver: span planning + dossier/summary generation.

Design: docs/summary/document-knowledge-data-structures.md (§1.3, §6.1) and
docs/summary/implementation-guru.md (G4 plan mode, G5 generate mode).

Plan mode (`--plan`) computes every work's span layout deterministically from the
chunk TOMLs and the campaign config, and writes the V9 FREEZE ARTIFACT:
    docs/summary/span-plan-{campaign_id}.json (machine)
    docs/summary/span-plan-{campaign_id}.md (human)
Once generation has begun, regenerating this with different totals means a
NEW campaign — never a partial re-plan.

Span rules (§1.3.5 + G4, and the G4 ticket's analysis note):
  - spans never cross member-text boundaries (id scheme sum:{text_id}:{slug})
  - natural sections first: chunks group by base section (part-letter suffix
    stripped); adjacent sections merge up to span_target; a single oversized
    section splits at chunk boundaries into "{section} (part n)"
  - bare-format fallback: a text whose sections collapse to one base while
    exceeding span_target is budget-packed into synthetic "Part n" spans
  - single-span WORKS take the degenerate rule: one summary staged directly
    at level 2, no L1 row, no structure entry
  - fold / map-reduce nodes exist only when input_budget > 0 (local provider)

Usage:
    python3 scripts/build_dossiers.py --plan
    python3 scripts/build_dossiers.py --generate --stage l1 [--work id] [--limit N]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sqlite3
import sys
import time
import tomllib
from dataclasses import dataclass, field, asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from works import load_works, Work  # noqa: E402

logger = logging.getLogger(__name__)

CORPUS_DIR = PROJECT_ROOT / "corpus"
CONFIG_PATH = PROJECT_ROOT / "config" / "dossiers.toml"
DEFAULT_DB = PROJECT_ROOT / "data" / "guru.db"

# Works whose span plan is provisional until the named ticket lands.
GATED_WORKS = {"corpus-hermeticum": "c59758f3"}


# ── config ────────────────────────────────────────────────────────────────────

def load_campaign(path: Path = CONFIG_PATH) -> dict:
    cfg = tomllib.load(open(path, "rb"))["campaign"]
    for key in ("campaign_id", "provider", "model", "span_target", "input_budget", "review_k"):
        if key not in cfg:
            raise ValueError(f"config missing campaign.{key}")
    return cfg


# ── corpus access ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Chunk:
    id: str
    section: str | None
    token_count: int
    path: str


def load_text_chunks(tradition: str, text_id: str) -> list[Chunk]:
    out = []
    for ct in sorted((CORPUS_DIR / tradition / text_id / "chunks").glob("*.toml")):
        d = tomllib.load(open(ct, "rb"))["chunk"]
        out.append(Chunk(d["id"], d.get("section"), d["token_count"], str(ct.relative_to(PROJECT_ROOT))))
    return out


# ── span planning ─────────────────────────────────────────────────────────────

_PART_SUFFIX = re.compile(r"([0-9IVXLCivxlc])[a-z]$")
# Only a LETTERED ', Section Na' tail is a sub-part marker ('Chapter II,
# Section 1a' → 'Chapter II'). An unlettered ', Section N' is real section
# identity — Plotinus is 'Select Works, Section 1..326' — and must survive.
_SECTION_TAIL = re.compile(r",\s*Section\s+\d+[a-z]$", re.I)
_PARENS_PART = re.compile(r"\s*\(part \d+\)$", re.I)


def base_section(section: str | None) -> str:
    """Collapse part markers: 'Rune Ia'→'Rune I', '1b'→'1',
    'Chapter II, Section 1a'→'Chapter II',
    'Select Works, Section 19 (part 2)'→'Select Works, Section 19'."""
    if not section:
        return ""
    s = _PARENS_PART.sub("", section.strip())
    s = _SECTION_TAIL.sub("", s)
    s = _PART_SUFFIX.sub(r"\1", s)
    return s.strip()


def _merged_label(first: str, last: str) -> str:
    """'Select Works, Section 5' + 'Select Works, Section 12'
    → 'Select Works, Section 5 – 12' (trim shared word-prefix on the right)."""
    fw, lw = first.split(" "), last.split(" ")
    i = 0
    while i < min(len(fw), len(lw)) - 1 and fw[i] == lw[i]:
        i += 1
    tail = " ".join(lw[i:])
    return f"{first} – {tail}" if tail else f"{first} – {last}"


def slugify(label: str) -> str:
    s = re.sub(r"[^0-9A-Za-z]+", "-", label.lower()).strip("-")
    s = re.sub(r"-{2,}", "-", s)
    return s or "span"


@dataclass
class Span:
    text_id: str
    label: str                    # printable section_span
    slug: str
    chunk_ids: list[str]
    token_count: int


def plan_text_spans(text_id: str, chunks: list[Chunk], span_target: int) -> list[Span]:
    """Spans for ONE member text (spans never cross texts — G4 note)."""
    if not chunks:
        return []
    # group consecutive chunks by base section (corpus order)
    groups: list[tuple[str, list[Chunk]]] = []
    for c in chunks:
        b = base_section(c.section)
        if groups and groups[-1][0] == b:
            groups[-1][1].append(c)
        else:
            groups.append((b, [c]))

    total = sum(c.token_count for c in chunks)
    # bare-format fallback: everything collapsed to one base but the text
    # exceeds the target — no real structure to respect, so pack to target
    # with synthetic labels (V1: enuma-elish, book-of-concealed-mystery)
    if len(groups) == 1 and total > span_target:
        return _budget_pack(text_id, groups[0][0], chunks, span_target, synthetic=True)

    spans: list[Span] = []
    acc: list[tuple[str, list[Chunk]]] = []
    acc_tok = 0

    def flush():
        nonlocal acc, acc_tok
        if not acc:
            return
        if len(acc) == 1:
            label = acc[0][0] or text_id
        else:
            label = _merged_label(acc[0][0], acc[-1][0])
        cs = [c for _, grp in acc for c in grp]
        spans.append(Span(text_id, label, slugify(label),
                          [c.id for c in cs], sum(c.token_count for c in cs)))
        acc, acc_tok = [], 0

    for b, grp in groups:
        gtok = sum(c.token_count for c in grp)
        if gtok > span_target * 1.5:
            flush()
            spans.extend(_budget_pack(text_id, b or text_id, grp, span_target, synthetic=False))
            continue
        if acc and acc_tok + gtok > span_target:
            flush()
        acc.append((b, grp))
        acc_tok += gtok
    flush()

    # slug uniqueness within the text
    seen: dict[str, int] = {}
    for s in spans:
        if s.slug in seen:
            seen[s.slug] += 1
            s.slug = f"{s.slug}-{seen[s.slug]}"
        else:
            seen[s.slug] = 1
    return spans


def _budget_pack(text_id: str, base_label: str, chunks: list[Chunk],
                 span_target: int, synthetic: bool) -> list[Span]:
    """Split a run of chunks into (part n) spans at chunk boundaries."""
    parts: list[list[Chunk]] = [[]]
    tok = 0
    for c in chunks:
        if parts[-1] and tok + c.token_count > span_target:
            parts.append([])
            tok = 0
        parts[-1].append(c)
        tok += c.token_count
    if len(parts) == 1:
        label = base_label if not synthetic else base_label or text_id
        return [Span(text_id, label, slugify(label),
                     [c.id for c in parts[0]], sum(c.token_count for c in parts[0]))]
    out = []
    for i, p in enumerate(parts, 1):
        label = f"Part {i}" if synthetic else f"{base_label} (part {i})"
        out.append(Span(text_id, label, slugify(label),
                        [c.id for c in p], sum(c.token_count for c in p)))
    return out


@dataclass
class WorkPlan:
    work_id: str
    label: str
    tradition: str
    grouped: bool
    degenerate: bool              # single-span work: one summary staged at L2
    gated_by: str | None
    spans: list[Span] = field(default_factory=list)
    fold_batches: int = 0         # >0 only under input_budget>0 providers
    token_count: int = 0

    @property
    def l1_calls(self) -> int:
        return 0 if self.degenerate else len(self.spans)

    @property
    def structure_calls(self) -> int:
        return self.l1_calls


def _text_name(tradition: str, text_id: str) -> str:
    meta = tomllib.load(open(CORPUS_DIR / tradition / text_id / "metadata.toml", "rb"))
    return meta.get("text_name", text_id)


def _disambiguate_labels(w: Work, spans: list[Span]) -> None:
    """Span labels are reader-facing structure_json section_spans AND the
    staged join key — they must be unique per work. Generic per-member labels
    ('Section 1' in all 17 CH tractates) are replaced with the member's
    text_name, which is also the better TOC entry (tractate/chapter title)."""
    from collections import Counter
    dup = {k for k, v in Counter(s.label for s in spans).items() if v > 1}
    if not dup:
        return
    per_text = Counter(s.text_id for s in spans)
    for s in spans:
        if s.label in dup:
            name = _text_name(w.tradition, s.text_id)
            s.label = name if per_text[s.text_id] == 1 else f"{name} — {s.label}"
            s.slug = slugify(f"{s.text_id}-{s.label}") if per_text[s.text_id] > 1 else slugify(s.label)
    # final guarantee
    seen: dict[str, int] = {}
    for s in spans:
        key = s.label
        if key in seen:
            seen[key] += 1
            s.label = f"{s.label} ({seen[key]})"
            s.slug = f"{s.slug}-{seen[key]}"
        else:
            seen[key] = 1


def plan_campaign(cfg: dict, works: dict[str, Work] | None = None) -> list[WorkPlan]:
    works = works or load_works()
    span_target = cfg["span_target"]
    input_budget = cfg["input_budget"]
    plans = []
    for w in sorted(works.values(), key=lambda x: (x.tradition, x.id)):
        spans: list[Span] = []
        for member in w.members:
            spans.extend(plan_text_spans(member, load_text_chunks(w.tradition, member), span_target))
        _disambiguate_labels(w, spans)
        total = sum(s.token_count for s in spans)
        degenerate = len(spans) == 1
        folds = 0
        if input_budget and not degenerate:
            # L1 body estimate: clamp(child_tokens/12, 80, 300) per §1.3.3
            est_l1 = sum(min(300, max(80, s.token_count // 12)) for s in spans)
            if est_l1 > input_budget:
                folds = -(-est_l1 // input_budget)  # ceil
        plans.append(WorkPlan(w.id, w.label, w.tradition, w.grouped, degenerate,
                              GATED_WORKS.get(w.id), spans, folds, total))
    return plans


# ── freeze artifact ───────────────────────────────────────────────────────────

def write_plan_artifacts(plans: list[WorkPlan], cfg: dict) -> tuple[Path, Path]:
    cid = cfg["campaign_id"]
    payload = {
        "campaign": {k: cfg[k] for k in
                     ("campaign_id", "provider", "model", "span_target", "input_budget")},
        "plan_hash": None,
        "works": [
            {**asdict(p), "l1_calls": p.l1_calls, "structure_calls": p.structure_calls}
            for p in plans
        ],
    }
    canon = json.dumps(payload["works"], sort_keys=True).encode()
    payload["plan_hash"] = hashlib.sha256(canon).hexdigest()

    json_path = PROJECT_ROOT / "docs" / "summary" / f"span-plan-{cid}.json"
    json_path.write_text(json.dumps(payload, indent=1, ensure_ascii=False))

    n_spans = sum(len(p.spans) for p in plans)
    n_degen = sum(1 for p in plans if p.degenerate)
    lines = [
        f"# Span Plan — campaign {cid} (V9 FREEZE ARTIFACT)",
        "",
        f"Generated by `build_dossiers.py --plan`. plan_hash `{payload['plan_hash'][:16]}…`.",
        f"Provider `{cfg['provider']}` · model `{cfg['model']}` · span_target {cfg['span_target']}"
        f" · input_budget {cfg['input_budget']}.",
        "",
        "**Once generation begins, this file is frozen.** A budget/grouping/provider",
        "change is a new campaign (full regenerate), never a partial re-plan.",
        "",
        f"Totals: **{len(plans)} works · {n_spans} spans** · {n_degen} degenerate"
        f" (L2-only) · L1+structure call pairs: {sum(p.l1_calls for p in plans)}"
        f" · folds: {sum(p.fold_batches for p in plans)}",
        "",
        "| work | spans | tokens | flags |",
        "|---|---|---|---|",
    ]
    for p in plans:
        flags = []
        if p.degenerate:
            flags.append("degenerate")
        if p.grouped:
            flags.append("grouped")
        if p.gated_by:
            flags.append(f"GATED by {p.gated_by} — provisional")
        if p.fold_batches:
            flags.append(f"folds:{p.fold_batches}")
        lines.append(f"| {p.work_id} | {len(p.spans)} | {p.token_count:,} | {', '.join(flags)} |")
    md_path = PROJECT_ROOT / "docs" / "summary" / f"span-plan-{cid}.md"
    md_path.write_text("\n".join(lines) + "\n")
    return json_path, md_path


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--generate", action="store_true")
    mode.add_argument("--respin", nargs="*", metavar="SUMMARY_ID",
                      help="regenerate specific rejected summaries (no ids = all fully-rejected spans);"
                           " reviewer rejection notes are fed back as corrective prompt addenda")
    ap.add_argument("--stage", choices=["l1", "structure", "l2", "summary", "context",
                                        "figures", "terms", "notes"])
    ap.add_argument("--work", help="limit to one work id")
    ap.add_argument("--limit", type=int, default=0, help="max generation calls this run")
    ap.add_argument("--provider", help="override campaign provider for --respin")
    ap.add_argument("--model", help="override campaign model for --respin")
    ap.add_argument("--config", type=Path, default=CONFIG_PATH)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    cfg = load_campaign(args.config)

    if args.plan:
        plans = plan_campaign(cfg)
        jp, mp = write_plan_artifacts(plans, cfg)
        logger.info(f"plan written: {jp.relative_to(PROJECT_ROOT)} + {mp.relative_to(PROJECT_ROOT)}")
        logger.info(f"works: {len(plans)} · spans: {sum(len(p.spans) for p in plans)}"
                    f" · degenerate: {sum(1 for p in plans if p.degenerate)}"
                    f" · folds: {sum(p.fold_batches for p in plans)}")
        return 0

    if args.respin is not None:
        from generate_dossiers import Generator, respin, rejected_targets  # noqa: PLC0415
        if args.provider:
            cfg = {**cfg, "provider": args.provider}
        if args.model:
            cfg = {**cfg, "model": args.model}
        plan = json.loads((PROJECT_ROOT / "docs" / "summary" /
                           f"span-plan-{cfg['campaign_id']}.json").read_text())
        gen = Generator(cfg, args.db, plan)
        targets = rejected_targets(gen.conn)
        if args.respin:  # explicit ids filter
            wanted = set(args.respin)
            targets = [(sid, note) for sid, note in targets if sid in wanted]
            missing = wanted - {sid for sid, _ in targets}
            for m in missing:
                logger.warning(f"--respin {m}: span still has a pending/accepted row, or unknown id — skipped")
        ok = sum(1 for sid, note in targets if respin(gen, sid, note))
        logger.info(f"respun {ok}/{len(targets)} target(s); rows are PENDING — review before accepting")
        return 0

    # --generate lands with G5 (todo:29a7116e)
    from generate_dossiers import run_generate  # noqa: PLC0415
    return run_generate(args, cfg)


if __name__ == "__main__":
    sys.exit(main())
