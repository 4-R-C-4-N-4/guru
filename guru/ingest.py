"""
guru/ingest.py — the document-ingest state machine.

The pipeline graph lives here as data, not inside any agent harness. Any
driver — Claude Code, another agent runtime, or a human at a terminal — runs
the same loop:

    python3 -m guru ingest status <source-id>    # which node, what blocks it, what runs next
    <do the named step>
    python3 -m guru ingest status <source-id>    # gate re-checks, node advances

Every node here is mirrored one-to-one by a workbook file in ``docs/ingest/``.
Judgement nodes additionally carry a prompt contract in ``prompts/ingest/`` so
the call can be made either by a local model through
``scripts/run_contract.py`` or by the driving agent — same inputs, same output
schema, same rubric.

Node kinds
    command    deterministic script; any driver may run it
    judgement  LLM-in-the-flow; has a prompt contract and a written decision record
    gate       proposals are queued for human review; a driver may queue decisions
               but must never apply them
    user       user-only; drivers stop here and hand back

Node states
    done       artifact present / ledger entry recorded
    ready      preconditions met, nothing done yet
    blocked    an upstream node is not done
    stale      recorded as done, but an upstream artifact changed since
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import tomllib

from guru.paths import CORPUS_DIR, DEFAULT_DB, PROJECT_ROOT

MANIFEST = PROJECT_ROOT / "sources" / "manifest.toml"
RAW_DIR = PROJECT_ROOT / "raw"
CHUNKING_DIR = PROJECT_ROOT / "chunking"
LEDGER_DIR = PROJECT_ROOT / "data" / "ingest"
WORKBOOK_DIR = PROJECT_ROOT / "docs" / "ingest"
CONTRACT_DIR = PROJECT_ROOT / "prompts" / "ingest"
DECISION_DIR = WORKBOOK_DIR / "decisions"

DONE, READY, BLOCKED, STALE = "done", "ready", "blocked", "stale"

# Mirrors STRATEGY_TYPES in scripts/chunk.py, which is the source of truth.
# The three canonical names are what new configs should use; `regex`,
# `paragraph` and `heading` are accepted aliases kept for older configs.
CANONICAL_STRATEGIES = {"regex-section-split", "page-as-chunk", "paragraph-group"}
STRATEGIES = CANONICAL_STRATEGIES | {"regex", "paragraph", "heading"}


# ---------------------------------------------------------------- context


@dataclass
class Ctx:
    """Everything a probe needs to decide whether its node is satisfied."""

    source_id: str
    tradition: str | None
    entry: dict | None          # the sources/manifest.toml [[source]] block
    db: sqlite3.Connection | None
    ledger: dict

    @property
    def raw_txt(self) -> Path:
        return RAW_DIR / (self.tradition or "_") / f"{self.source_id}.txt"

    def raw_pages(self) -> list[Path]:
        """Multi-page raw files, `{id}-NN.txt`, in page order."""
        d = RAW_DIR / (self.tradition or "_")
        if not d.is_dir():
            return []
        pat = re.compile(rf"^{re.escape(self.source_id)}-(\d+)\.txt$")
        hits = [(int(m.group(1)), p) for p in d.iterdir()
                if (m := pat.match(p.name))]
        return [p for _, p in sorted(hits)]

    @property
    def chunk_config(self) -> Path:
        return CHUNKING_DIR / (self.tradition or "_") / f"{self.source_id}.toml"

    @property
    def corpus_dir(self) -> Path:
        return CORPUS_DIR / (self.tradition or "_") / self.source_id

    @property
    def chunk_prefix(self) -> str:
        return f"{self.tradition}.{self.source_id}."

    @property
    def chunk_like(self) -> str:
        """`chunk_prefix` as a LIKE pattern, wildcards escaped.

        Tradition ids contain `_` (christian_mysticism, jewish_mysticism),
        which LIKE reads as a single-character wildcard. Every probe that
        counts chunks by prefix must escape it or it counts neighbours.
        Pair with ``ESCAPE '\\'`` in the query.
        """
        esc = (self.chunk_prefix
               .replace("\\", "\\\\")
               .replace("%", "\\%")
               .replace("_", "\\_"))
        return esc + "%"

    def chunk_files(self) -> list[Path]:
        d = self.corpus_dir / "chunks"
        return sorted(d.glob("*.toml")) if d.is_dir() else []

    def corpus_mtime(self) -> float:
        """Newest mtime across generated chunk files — drives staleness."""
        files = self.chunk_files()
        return max((f.stat().st_mtime for f in files), default=0.0)

    def count(self, sql: str, *params) -> int:
        if self.db is None:
            return 0
        try:
            return int(self.db.execute(sql, params).fetchone()[0])
        except sqlite3.Error:
            return 0


# ---------------------------------------------------------------- nodes


@dataclass
class Node:
    key: str
    title: str
    kind: str
    probe: Callable[[Ctx], tuple[bool, str]]
    command: str = ""
    gate: str = ""
    contract: str = ""
    # A node marked done in the ledger goes stale when the corpus is rebuilt.
    stale_on_rechunk: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def doc(self) -> str:
        return f"docs/ingest/{self.key}.md"


def _ledger_done(ctx: Ctx, key: str) -> tuple[bool, str]:
    rec = ctx.ledger.get("nodes", {}).get(key)
    if not rec or rec.get("status") != DONE:
        return False, "no ledger entry"
    who = rec.get("by", "?")
    note = rec.get("note") or ""
    return True, f"recorded by {who}" + (f" — {note}" if note else "")


def _p_vetting(ctx: Ctx) -> tuple[bool, str]:
    return _ledger_done(ctx, "01-source-vetting")


def _p_manifest(ctx: Ctx) -> tuple[bool, str]:
    if ctx.entry is None:
        return False, f"no [[source]] with id = \"{ctx.source_id}\" in sources/manifest.toml"
    missing = [k for k in ("tradition", "url", "format", "license") if k not in ctx.entry]
    if missing:
        return False, "entry present but missing keys: " + ", ".join(missing)
    return True, f"{ctx.entry['format']} · {ctx.entry.get('license', '?')} · {ctx.entry['url']}"


def _p_acquire(ctx: Ctx) -> tuple[bool, str]:
    """Single-page sources land as {id}.txt; multi-page as {id}-NN.txt.

    Checking only the single-page name reports every `html_multi` source as
    unacquired forever — including texts that are chunked, tagged and
    embedded. The page pattern mirrors `_find_multi_raw_files` in
    scripts/chunk.py, which is what actually consumes them.
    """
    single = ctx.raw_txt
    pages = ctx.raw_pages()

    if not single.is_file() and not pages:
        return False, (f"missing {single.relative_to(PROJECT_ROOT)} "
                       f"(and no {ctx.source_id}-NN.txt pages)")

    if pages and not single.is_file():
        empty = [p for p in pages if p.stat().st_size == 0]
        if empty:
            return False, f"{len(empty)} of {len(pages)} page files are empty"
        total = sum(p.stat().st_size for p in pages)
        return True, f"{len(pages)} pages · {total:,} bytes"

    size = single.stat().st_size
    if size == 0:
        return False, f"{single.relative_to(PROJECT_ROOT)} is empty"
    detail = f"{single.relative_to(PROJECT_ROOT)} · {size:,} bytes"
    if pages:
        detail += f" (+{len(pages)} page files)"
    return True, detail


def _p_boilerplate(ctx: Ctx) -> tuple[bool, str]:
    return _ledger_done(ctx, "04-boilerplate-survey")


def _p_chunk_config(ctx: Ctx) -> tuple[bool, str]:
    p = ctx.chunk_config
    if not p.is_file():
        return False, f"missing {p.relative_to(PROJECT_ROOT)}"
    try:
        cfg = tomllib.loads(p.read_text())
    except tomllib.TOMLDecodeError as exc:
        return False, f"{p.name} does not parse: {exc}"
    strat = cfg.get("chunking", {}).get("strategy", "paragraph-group")
    if strat not in STRATEGIES:
        return False, (f"{p.name}: unknown strategy {strat!r} — "
                       f"one of {', '.join(sorted(CANONICAL_STRATEGIES))}")
    suffix = "" if strat in CANONICAL_STRATEGIES else " (back-compat alias)"
    return True, f"strategy={strat}{suffix}"


def _p_chunk(ctx: Ctx) -> tuple[bool, str]:
    meta = ctx.corpus_dir / "metadata.toml"
    files = ctx.chunk_files()
    if not meta.is_file():
        return False, f"missing {meta.relative_to(PROJECT_ROOT)}"
    if not files:
        return False, f"no chunk TOMLs under {ctx.corpus_dir.relative_to(PROJECT_ROOT)}/chunks/"
    try:
        declared = tomllib.loads(meta.read_text()).get("chunk_count")
    except (tomllib.TOMLDecodeError, OSError) as exc:
        return False, f"metadata.toml does not parse: {exc}"
    if declared is not None and int(declared) != len(files):
        return False, f"metadata.toml says chunk_count={declared} but {len(files)} files on disk"
    return True, f"{len(files)} chunks"


def _p_clean(ctx: Ctx) -> tuple[bool, str]:
    return _ledger_done(ctx, "07-clean-bodies")


def _p_readability(ctx: Ctx) -> tuple[bool, str]:
    return _ledger_done(ctx, "08-readability-gate")


def _p_graph(ctx: Ctx) -> tuple[bool, str]:
    n = ctx.count("SELECT count(*) FROM nodes WHERE type='chunk' AND id LIKE ? ESCAPE '\\'",
                  ctx.chunk_like)
    on_disk = len(ctx.chunk_files())
    if n == 0:
        return False, "no chunk nodes in guru.db"
    if on_disk and n != on_disk:
        return False, f"{n} chunk nodes in db but {on_disk} chunk files on disk"
    return True, f"{n} chunk nodes"


def _p_tag(ctx: Ctx) -> tuple[bool, str]:
    n = ctx.count("SELECT count(*) FROM staged_tags WHERE chunk_id LIKE ? ESCAPE '\\'",
                  ctx.chunk_like)
    return (n > 0), (f"{n} staged tags" if n else "no staged_tags rows for this text")


def _p_tag_review(ctx: Ctx) -> tuple[bool, str]:
    pend = ctx.count("SELECT count(*) FROM staged_tags WHERE status='pending' AND chunk_id LIKE ? ESCAPE '\\'",
                     ctx.chunk_like)
    total = ctx.count("SELECT count(*) FROM staged_tags WHERE chunk_id LIKE ? ESCAPE '\\'",
                      ctx.chunk_like)
    if total == 0:
        return False, "nothing staged to review"
    if pend:
        return False, f"{pend} of {total} staged tags still pending"
    return True, f"all {total} staged tags reviewed"


def _p_embed(ctx: Ctx) -> tuple[bool, str]:
    chunks = ctx.count("SELECT count(*) FROM nodes WHERE type='chunk' AND id LIKE ? ESCAPE '\\'",
                       ctx.chunk_like)
    if chunks == 0:
        return False, "no chunk nodes to embed"
    # Join rather than compare counts: stale embeddings for retired chunk ids
    # can make the totals agree while current chunks sit unembedded, and node
    # 13 then proposes edges off a partial vector set.
    missing = ctx.count(
        "SELECT count(*) FROM nodes n "
        "LEFT JOIN chunk_embeddings e ON e.chunk_id = n.id "
        "WHERE n.type='chunk' AND n.id LIKE ? ESCAPE '\\' AND e.chunk_id IS NULL",
        ctx.chunk_like)
    if missing:
        return False, f"{missing} of {chunks} chunks unembedded — run with --resume"
    return True, f"{chunks} chunks embedded"


def _p_edges(ctx: Ctx) -> tuple[bool, str]:
    pref = ctx.chunk_like
    n = ctx.count(
        "SELECT count(*) FROM staged_edges WHERE source_chunk LIKE ? ESCAPE '\\' "
        "OR target_chunk LIKE ? ESCAPE '\\'", pref, pref)
    return (n > 0), (f"{n} staged edges touch this text" if n else "no staged_edges for this text")


def _p_edge_review(ctx: Ctx) -> tuple[bool, str]:
    pref = ctx.chunk_like
    pend = ctx.count(
        "SELECT count(*) FROM staged_edges WHERE status='pending' "
        "AND (source_chunk LIKE ? ESCAPE '\\' OR target_chunk LIKE ? ESCAPE '\\')",
        pref, pref)
    total = ctx.count(
        "SELECT count(*) FROM staged_edges "
        "WHERE source_chunk LIKE ? ESCAPE '\\' OR target_chunk LIKE ? ESCAPE '\\'", pref, pref)
    if total == 0:
        return False, "nothing staged to review"
    if pend:
        return False, f"{pend} of {total} staged edges still pending"
    return True, f"all {total} staged edges reviewed"


def _p_publish(ctx: Ctx) -> tuple[bool, str]:
    return _ledger_done(ctx, "15-publish")


NODES: list[Node] = [
    Node("01-source-vetting", "Vet the source URL and license", "judgement",
         _p_vetting,
         contract="prompts/ingest/source-vetting.md",
         notes=["A URL that returns 200 is not a verified source. Confirm the "
                "heading chain reads the translation, not a translator's "
                "introduction essay — that was 9 of 11 wrong in the Upanishad "
                "batch (docs/corpus-expansion/url-vetting.md).",
                "Decide single-page vs multi-page here. A multi-page text "
                "behind one `format = \"html\"` entry silently ingests only "
                "its first chapter."]),

    Node("02-manifest-entry", "Add the [[source]] block", "command",
         _p_manifest,
         command="edit sources/manifest.toml",
         gate="python3 scripts/acquire.py --dry-run --only {id}",
         notes=["Carry the vetting evidence into a comment on the entry — "
                "what was checked, when, what the heading chain said. The "
                "pistis-sophia block is the model."]),

    Node("03-acquire", "Download the raw text", "command",
         _p_acquire,
         command="python3 scripts/acquire.py --only {id}",
         gate="python3 -m guru ingest status {id}",
         notes=["Downloader is chosen by URL host — see scripts/downloaders/. "
                "A host with no downloader falls back to generic_html.py."]),

    Node("04-boilerplate-survey", "Identify nav, credit and page-marker cruft", "judgement",
         _p_boilerplate,
         contract="prompts/ingest/boilerplate-survey.md",
         notes=["Read the head and tail of the raw file, not the middle. "
                "Site headers lead; `Next:` nav lines and Gutenberg license "
                "blocks trail.",
                "Strip at paragraph or sentence granularity only. Never "
                "substring surgery mid-paragraph, never drop a chunk — chunk "
                "ids are load-bearing citations.",
                "Known classes and their strip strategies are tabulated in "
                "docs/summary/boilerplate-audit.md (P1–P6)."]),

    Node("05-chunk-config", "Author chunking/{tradition}/{id}.toml", "judgement",
         _p_chunk_config,
         contract="prompts/ingest/chunk-config.md",
         gate="python3 scripts/chunk.py --dry-run --only {id}",
         notes=["Strategy follows the text's own division system. Canonical "
                "names are regex-section-split (explicit markers like `(N)`), "
                "paragraph-group (undifferentiated prose — the default and by "
                "far the most common), and page-as-chunk (multi-page sources "
                "where each page is one citable unit).",
                "docs/chunking-schema.md documents `regex` / `paragraph` / "
                "`heading`. Those are accepted back-compat aliases, not the "
                "names the corpus uses — scripts/chunk.py STRATEGY_TYPES is "
                "the source of truth.",
                "`pattern` must be a TOML literal string (single quotes) or "
                "the backslashes double-escape."]),

    Node("06-chunk", "Generate corpus TOMLs", "command",
         _p_chunk,
         command="python3 scripts/chunk.py --only {id}",
         gate="python3 -m guru ingest status {id}",
         notes=["Output is pre-clean by construction — node 07 is not "
                "optional after any chunk or re-chunk run."]),

    Node("07-clean-bodies", "Strip boilerplate from chunk bodies", "command",
         _p_clean,
         command="python3 scripts/clean_bodies.py --apply --text {id}",
         gate="python3 scripts/clean_bodies.py --dry-run --text {id}",
         stale_on_rechunk=True,
         notes=["Dry-run first and read the diff. `--max-shrink` defaults to "
                "0.25; a chunk that wants to lose more than a quarter of "
                "itself is a bug in the strip plan, not a dirty chunk.",
                "This node goes stale automatically whenever chunk files are "
                "regenerated. That is the intent."]),

    Node("08-readability-gate", "Score the rendered bodies", "judgement",
         _p_readability,
         command="python3 scripts/audit_readability.py --text {id} --format markdown",
         contract="prompts/ingest/readability-gate.md",
         stale_on_rechunk=True,
         notes=["Bodies are served verbatim to the public reader, so damage "
                "here is user-facing.",
                "A high score is a prompt to look, not an automatic failure — "
                "bracketed lacunae in Gilgamesh are the text, not damage. "
                "Judgement is whether the signal is scholarly apparatus or "
                "ingest breakage."]),

    Node("09-graph-bootstrap", "Create chunk and tradition nodes", "command",
         _p_graph,
         command="python3 scripts/graph_bootstrap.py",
         gate="python3 -m guru ingest status {id}",
         notes=["Run scripts/sync_taxonomy.py --apply too if the text "
                "introduced concepts that are not yet in "
                "concepts/taxonomy.toml."]),

    Node("10-tag-concepts", "Propose chunk→concept tags", "command",
         _p_tag,
         command=("python3 scripts/tag_concepts.py --text {id} "
                  "--provider llamacpp --model Qwen3.5-27B-UD-Q4_K_XL.gguf"),
         gate="python3 -m guru ingest status {id}",
         notes=["Writes to staged_tags with status='pending'. Nothing reaches "
                "the live graph from this node.",
                "Needs a llama.cpp server that is up AND FREE. `llm status` "
                "reporting healthy does not mean idle — check for another "
                "tag_concepts or propose_edges process first "
                "(`pgrep -af 'tag_concepts|propose_edges'`). Two runs against "
                "one slot do not fail, they both crawl, which reads exactly "
                "like a hang.",
                "scripts/run-qwen.sh serves the 27B, "
                "scripts/run-qwen-4b-guru.sh the fine-tune; confirm which mode "
                "the script launches before a long run.",
                "`llm stop` only a server you started yourself. A server "
                "started outside `llm` belongs to someone else's session, and "
                "stopping it destroys their state."]),

    Node("11-tag-review", "Curate the staged tags", "gate",
         _p_tag_review,
         command="python3 scripts/review_tags.py --text {id}",
         contract="prompts/ingest/tag-review.md",
         notes=["A driver may queue accept / reject / reassign decisions. "
                "Applying them is the user's call, always.",
                "Model ids differ by tagger: 4B batches are 70xxx, 27B are "
                "71xxx. A mistyped id is silently rejected, so check the "
                "accepted count matches what you intended."]),

    Node("12-embed", "Embed the chunks", "command",
         _p_embed,
         command="python3 scripts/embed_corpus.py --resume --text {id}",
         gate="python3 -m guru ingest status {id}",
         notes=["Must run after node 07 — embedding dirty bodies bakes the "
                "boilerplate into the vectors and node 13 then proposes edges "
                "off nav-line similarity."]),

    Node("13-propose-edges", "Propose cross-tradition edges", "command",
         _p_edges,
         command=("python3 scripts/propose_edges.py --text {id} "
                  "--provider llamacpp --model Qwen3.5-27B-UD-Q4_K_XL.gguf"),
         gate="python3 -m guru ingest status {id}",
         notes=["Requires embeddings (node 12) — candidate pairs come from "
                "vector similarity above --min-similarity, default 0.75.",
                "Same server discipline as node 10: check the slot is free "
                "before starting, and only stop what you started."]),

    Node("14-edge-review", "Curate the staged edges", "gate",
         _p_edge_review,
         command="python3 scripts/review_edges.py --min-confidence 0.7",
         contract="prompts/ingest/edge-review.md",
         notes=["The 0.85-confidence tier left behind by auto_promote_edges "
                "is the noisy one and the reason this node exists.",
                "Queue accept / reclassify / reject. Never apply."]),

    Node("15-publish", "Ship the corpus", "user",
         _p_publish,
         notes=["USER ONLY. Drivers stop here and hand back — no "
                "scripts/sync_corpus.sh, no ssh to the prod VPS, not even as "
                "part of a larger 'run the whole thing' instruction.",
                "Both guru and guru-web protect main: branch and open a PR, "
                "never push main directly."]),
]

NODES_BY_KEY = {n.key: n for n in NODES}


# ---------------------------------------------------------------- ledger


def ledger_path(source_id: str) -> Path:
    return LEDGER_DIR / f"{source_id}.json"


def load_ledger(source_id: str) -> dict:
    p = ledger_path(source_id)
    if not p.is_file():
        return {"source": source_id, "nodes": {}}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {"source": source_id, "nodes": {}}


def save_ledger(source_id: str, ledger: dict) -> None:
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    ledger_path(source_id).write_text(json.dumps(ledger, indent=2) + "\n")


# ---------------------------------------------------------------- evaluation


def load_entry(source_id: str) -> dict | None:
    if not MANIFEST.is_file():
        return None
    try:
        data = tomllib.loads(MANIFEST.read_text())
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise SystemExit(f"sources/manifest.toml does not parse: {exc}")
    for src in data.get("source", []):
        if src.get("id") == source_id:
            return src
    return None


def build_ctx(source_id: str, db_path: Path = DEFAULT_DB) -> Ctx:
    entry = load_entry(source_id)
    db = None
    if db_path.is_file():
        db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    return Ctx(
        source_id=source_id,
        tradition=(entry or {}).get("tradition"),
        entry=entry,
        db=db,
        ledger=load_ledger(source_id),
    )


def evaluate(ctx: Ctx) -> list[dict]:
    """Walk the graph in order, returning one row per node."""
    rows: list[dict] = []
    upstream_ok = True
    corpus_mtime = ctx.corpus_mtime()

    for node in NODES:
        ok, detail = node.probe(ctx)

        state = DONE if ok else (READY if upstream_ok else BLOCKED)

        if ok and node.stale_on_rechunk and corpus_mtime:
            rec = ctx.ledger.get("nodes", {}).get(node.key, {})
            at = rec.get("at_epoch")
            if at is not None and float(at) < corpus_mtime:
                state = STALE
                detail += " — but chunk files changed after it was recorded"

        rows.append({
            "key": node.key,
            "title": node.title,
            "kind": node.kind,
            "state": state,
            "detail": detail,
            "doc": node.doc,
            "contract": node.contract,
            "command": node.command.format(id=ctx.source_id, tradition=ctx.tradition or ""),
            "gate": node.gate.format(id=ctx.source_id, tradition=ctx.tradition or ""),
            "notes": node.notes,
        })

        if state != DONE:
            upstream_ok = False

    return rows


# ---------------------------------------------------------------- commands

_MARK = {DONE: "[x]", READY: "[ ]", BLOCKED: "[-]", STALE: "[!]"}


def cmd_status(args: argparse.Namespace) -> None:
    ctx = build_ctx(args.source_id, Path(args.db))
    rows = evaluate(ctx)

    if args.json:
        print(json.dumps({"source": args.source_id, "tradition": ctx.tradition,
                          "nodes": rows}, indent=2))
        return

    print(f"\n  {args.source_id}" + (f"  ({ctx.tradition})" if ctx.tradition else "  (unknown tradition)"))
    print(f"  {'─' * 66}")
    for r in rows:
        kind = "" if r["kind"] == "command" else f"  ·{r['kind']}"
        print(f"  {_MARK[r['state']]} {r['key']:<22}{r['title']}{kind}")
        if r["state"] != DONE or args.verbose:
            print(f"      {r['detail']}")

    nxt = next((r for r in rows if r["state"] in (READY, STALE)), None)
    print()
    if nxt is None:
        print("  all nodes satisfied — nothing to do\n")
        return

    print(f"  next: {nxt['key']} — {nxt['title']}")
    print(f"  read: {nxt['doc']}")
    if nxt["contract"]:
        print(f"  contract: {nxt['contract']}")
    if nxt["command"]:
        print(f"  run:  {nxt['command']}")
    if nxt["gate"]:
        print(f"  gate: {nxt['gate']}")
    if nxt["kind"] == "gate":
        print("  ── queue decisions only; the user applies them")
    if nxt["kind"] == "user":
        print("  ── USER GATE: stop here and hand back")
    for note in nxt["notes"]:
        print(f"  note: {note}")
    print()


def cmd_done(args: argparse.Namespace) -> None:
    if args.node not in NODES_BY_KEY:
        raise SystemExit(f"unknown node {args.node!r}; see `guru ingest nodes`")
    ledger = load_ledger(args.source_id)
    now = time.time()
    ledger.setdefault("nodes", {})[args.node] = {
        "status": DONE,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
        "at_epoch": now,
        "by": args.by,
        "note": args.note or "",
    }
    save_ledger(args.source_id, ledger)
    print(f"recorded {args.node} done for {args.source_id} (by {args.by})")


def cmd_reset(args: argparse.Namespace) -> None:
    if args.node not in NODES_BY_KEY:
        raise SystemExit(f"unknown node {args.node!r}; see `guru ingest nodes`")
    ledger = load_ledger(args.source_id)
    if ledger.get("nodes", {}).pop(args.node, None) is None:
        print(f"no ledger entry for {args.node}")
        return
    save_ledger(args.source_id, ledger)
    print(f"cleared {args.node} for {args.source_id}")


def cmd_nodes(args: argparse.Namespace) -> None:
    for n in NODES:
        print(f"  {n.key:<22}{n.kind:<11}{n.title}")


def register(sub: argparse._SubParsersAction) -> None:
    """Attach `guru ingest ...` to the main CLI parser."""
    ip = sub.add_parser("ingest", help="Document-ingest pipeline state machine")
    isub = ip.add_subparsers(dest="ingest_command", required=True)

    sp = isub.add_parser("status", help="Show pipeline state for one source")
    sp.add_argument("source_id")
    sp.add_argument("--db", default=str(DEFAULT_DB))
    sp.add_argument("--json", action="store_true", help="machine-readable output")
    sp.add_argument("--verbose", "-v", action="store_true")
    sp.set_defaults(func=cmd_status)

    dp = isub.add_parser("done", help="Record a judgement or manual node as done")
    dp.add_argument("source_id")
    dp.add_argument("node")
    dp.add_argument("--by", default="agent", help="who made the call")
    dp.add_argument("--note", default="", help="one-line summary; full reasoning goes in docs/ingest/decisions/")
    dp.set_defaults(func=cmd_done)

    rp = isub.add_parser("reset", help="Clear a ledger entry")
    rp.add_argument("source_id")
    rp.add_argument("node")
    rp.set_defaults(func=cmd_reset)

    np_ = isub.add_parser("nodes", help="List the pipeline nodes")
    np_.set_defaults(func=cmd_nodes)
