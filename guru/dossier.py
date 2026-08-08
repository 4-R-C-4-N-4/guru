"""
guru/dossier.py — the Pass D state machine (dossiers and summaries).

The second ingest stream. It shares the corpus with ``guru/ingest.py`` but not
its unit: ingest operates on a **text** (a manifest source id), Pass D operates
on a **work** — a dossier and level-2 summary unit, declared in
``sources/works.toml``, with every unlisted corpus text an implicit singleton.
Agrippa's sixty-odd chapter files are sixty ingest runs and one work.

The streams meet in one place: D1 requires every member text of a work to have
cleared ingest node 07, because a summary generated over dirty bodies
summarises the boilerplate too.

    python3 -m guru dossier status <work-id>
    python3 -m guru dossier survey            # every work, one line each
    python3 -m guru dossier drift             # live dossiers the frozen plan doesn't know about

Node kinds match ``guru/ingest.py``: command, judgement, gate, user.

The freeze rule (V9, and the reason ``drift`` exists): the span plan is an
artifact, not a cache. Once generation has begun against it, a corpus change
that alters any work's spans requires a NEW campaign — bump ``campaign_id`` in
``config/dossiers.toml`` and re-plan. A partial re-plan is never correct, and
promoting a work the frozen plan has never heard of is the same error wearing
a different hat.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import tomllib

from guru.paths import DEFAULT_DB, PROJECT_ROOT, SCRIPTS_DIR

sys.path.insert(0, str(SCRIPTS_DIR))

CAMPAIGN_CONFIG = PROJECT_ROOT / "config" / "dossiers.toml"
PLAN_DIR = PROJECT_ROOT / "docs" / "summary"
WORKBOOK_DIR = PROJECT_ROOT / "docs" / "dossiers"

DONE, READY, BLOCKED, STALE = "done", "ready", "blocked", "stale"

# promote_dossiers.py refuses a work whose required fields lack accepted rows.
REQUIRED_FIELDS = ("summary", "context")
ALL_FIELDS = ("summary", "context", "structure_entry",
              "key_figures", "key_terms", "reading_notes")

# review_dossiers.py RUBRIC, mirrored so `status` can name the codes.
RUBRIC = ("GROUND", "HEDGE", "REGISTER", "COVERAGE", "LEAK", "FORMAT", "COMPARE")


# ---------------------------------------------------------------- context


def load_campaign(path: Path = CAMPAIGN_CONFIG) -> dict:
    if not path.is_file():
        return {}
    return tomllib.loads(path.read_text()).get("campaign", {})


def plan_path(campaign_id: str) -> Path:
    return PLAN_DIR / f"span-plan-{campaign_id}.json"


def load_plan(campaign_id: str) -> dict | None:
    p = plan_path(campaign_id)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


@dataclass
class Ctx:
    work_id: str
    campaign: dict
    plan: dict | None
    plan_entry: dict | None      # this work's block in the frozen plan
    work: object | None          # works.Work, or None if the work is unknown
    db: sqlite3.Connection | None

    @property
    def campaign_id(self) -> str:
        # Must match the default build_ctx/find_drift use for the plan lookup,
        # or _p_plan reports a path that was never opened.
        return self.campaign.get("campaign_id", "")

    @property
    def spans(self) -> list[dict]:
        return (self.plan_entry or {}).get("spans", [])

    @property
    def degenerate(self) -> bool:
        """A work small enough to need no structure entries."""
        return bool((self.plan_entry or {}).get("degenerate"))

    def count(self, sql: str, *params) -> int:
        if self.db is None:
            return 0
        try:
            return int(self.db.execute(sql, params).fetchone()[0])
        except sqlite3.Error:
            return 0

    def rows(self, sql: str, *params) -> list[tuple]:
        if self.db is None:
            return []
        try:
            return list(self.db.execute(sql, params))
        except sqlite3.Error:
            return []


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
    notes: list[str] = field(default_factory=list)

    @property
    def doc(self) -> str:
        return f"docs/dossiers/{self.key}.md"


def _p_plan(ctx: Ctx) -> tuple[bool, str]:
    if not ctx.campaign_id:
        return False, "no campaign_id in config/dossiers.toml"
    if ctx.plan is None:
        return False, f"no frozen plan at {plan_path(ctx.campaign_id).relative_to(PROJECT_ROOT)}"
    if ctx.plan_entry is None:
        return False, (f"work is absent from the frozen {ctx.campaign_id} plan — "
                       f"this needs a NEW campaign, not a partial re-plan")
    n = len(ctx.spans)
    return True, (f"{ctx.campaign_id} · {n} span{'' if n == 1 else 's'}"
                  + (" · degenerate" if ctx.degenerate else ""))


def _p_generate(ctx: Ctx) -> tuple[bool, str]:
    fields = ctx.count(
        "SELECT count(*) FROM staged_dossier_fields WHERE work_id=? AND status!='rejected'",
        ctx.work_id)
    sums = ctx.count(
        "SELECT count(*) FROM staged_summaries WHERE work_id=? AND status!='rejected'",
        ctx.work_id)
    if not fields and not sums:
        return False, "no staged rows for this work"

    # A degenerate work is one span and skips the L1 tier entirely: no
    # structure entries, no per-span summaries, straight to a single L2.
    # Requiring an L1 for it reports every small text as unstarted forever.
    if ctx.degenerate:
        l2 = ctx.count(
            "SELECT count(DISTINCT summary_id) FROM staged_summaries "
            "WHERE work_id=? AND level=2 AND status!='rejected'", ctx.work_id)
        if not l2:
            return False, "degenerate work with no L2 summary staged"
        return True, f"degenerate · {fields} field rows · {sums} summary rows"

    want = len(ctx.spans)
    # DISTINCT summary_id: a span regenerated under a bumped template has one
    # row per version, and counting rows lets 5 regenerated spans stand in for
    # 10 planned ones.
    l1 = ctx.count(
        "SELECT count(DISTINCT summary_id) FROM staged_summaries "
        "WHERE work_id=? AND level=1 AND status!='rejected'", ctx.work_id)
    if want and l1 < want:
        return False, f"{l1} of {want} L1 summaries staged"
    return True, f"{fields} field rows · {sums} summary rows"


def _p_review(ctx: Ctx) -> tuple[bool, str]:
    pf = ctx.count(
        "SELECT count(*) FROM staged_dossier_fields WHERE work_id=? AND status='pending'",
        ctx.work_id)
    ps = ctx.count(
        "SELECT count(*) FROM staged_summaries WHERE work_id=? AND status='pending'",
        ctx.work_id)
    if pf or ps:
        parts = []
        if pf:
            parts.append(f"{pf} field row{'' if pf == 1 else 's'}")
        if ps:
            parts.append(f"{ps} summary row{'' if ps == 1 else 's'}")
        return False, "pending: " + ", ".join(parts)
    total = ctx.count(
        "SELECT count(*) FROM staged_dossier_fields WHERE work_id=?", ctx.work_id
    ) + ctx.count("SELECT count(*) FROM staged_summaries WHERE work_id=?", ctx.work_id)
    if total == 0:
        return False, "nothing staged to review"
    return True, f"all {total} staged rows settled"


def _p_promote(ctx: Ctx) -> tuple[bool, str]:
    live = ctx.count("SELECT count(*) FROM work_dossiers WHERE work_id=?", ctx.work_id)
    if not live:
        missing = [f for f in REQUIRED_FIELDS if not ctx.count(
            "SELECT count(*) FROM staged_dossier_fields "
            "WHERE work_id=? AND field=? AND status='accepted'", ctx.work_id, f)]
        if missing:
            return False, "no live dossier; required fields unaccepted: " + ", ".join(missing)
        return False, "required fields accepted but not promoted"

    # A promoted work still owes a structure entry per planned span.
    if ctx.spans and not ctx.degenerate:
        got = ctx.count(
            "SELECT count(DISTINCT section_span) FROM staged_dossier_fields "
            "WHERE work_id=? AND field='structure_entry' AND status='accepted'",
            ctx.work_id)
        if got < len(ctx.spans):
            return False, f"live, but {got} of {len(ctx.spans)} structure entries accepted"
    return True, "live dossier present"


def _p_embed(ctx: Ctx) -> tuple[bool, str]:
    nodes = ctx.count("SELECT count(*) FROM summary_nodes WHERE work_id=?", ctx.work_id)
    if not nodes:
        return False, "no summary_nodes for this work"
    missing = ctx.count(
        "SELECT count(*) FROM summary_nodes n "
        "LEFT JOIN summary_embeddings e ON e.summary_id = n.id "
        "WHERE n.work_id=? AND e.summary_id IS NULL", ctx.work_id)
    if missing:
        return False, f"{missing} of {nodes} summary_nodes unembedded"
    return True, f"{nodes} summary_nodes, all embedded"


def _p_export(ctx: Ctx) -> tuple[bool, str]:
    return False, "user gate"


NODES: list[Node] = [
    Node("D1-plan-freeze", "Freeze the span plan", "command",
         _p_plan,
         command="python3 scripts/build_dossiers.py --plan",
         gate="python3 -m guru dossier status {work}",
         notes=["The plan is a freeze artifact, not a cache. If the corpus "
                "grew since the current plan froze, bump campaign_id in "
                "config/dossiers.toml and re-plan — never re-plan in place.",
                "Requires every member text through ingest node 07. A summary "
                "over dirty bodies summarises the boilerplate too."]),

    Node("D2-generate", "Generate summaries and dossier fields", "command",
         _p_generate,
         command="python3 scripts/build_dossiers.py --generate --work {work}",
         gate="python3 -m guru dossier status {work}",
         notes=["Walks the frozen plan in DAG order. Every node is idempotent "
                "— a pending or accepted row for (unit, model, "
                "prompt_version) is skipped, so re-runs resume.",
                "Upstream inputs are ACCEPTED rows only: L2 reads accepted "
                "L1s. Generating L2 before reviewing L1 produces nothing.",
                "Provider comes from the campaign, not the session. "
                "`claude-code` is headless Claude Code; `local` is the 3090 "
                "path and is the only one that uses folds."]),

    Node("D3-review", "Converge the templates", "gate",
         _p_review,
         command="python3 scripts/review_dossiers.py sample --field <field>",
         contract="prompts/dossier/contracts/review-rubric.md",
         notes=["The converging unit is the TEMPLATE, not the row. Sample K "
                "works stratified by tradition and size, judge against the "
                "rubric codes, revise the template on clustered failures, "
                "then bulk-accept the passing batch.",
                "Codes: " + " / ".join(RUBRIC) + ".",
                "`show` prints the row's reconstructed stage INPUT next to its "
                "output. With a frontier-model generator you cannot check "
                "GROUND or LEAK without seeing what the model was allowed to "
                "know."]),

    Node("D4-promote", "Assemble accepted rows into live tables", "gate",
         _p_promote,
         command="python3 scripts/promote_dossiers.py --work {work}",
         gate="python3 scripts/promote_dossiers.py --work {work} --dry-run",
         notes=["Promotion is assembly: newest accepted row per field, "
                "preferring prompt_versions ending '-manual'. A work with any "
                "required field unaccepted does not go live — partial "
                "dossiers never exist.",
                "themes_json is DERIVED from live EXPRESSES edges, not "
                "generated, and is '[]' below the five-tag floor. It is "
                "display only and is never an edge.",
                "This writes live tables. See the node file — it is the one "
                "place the dossier stream's apply gate differs from the tag "
                "and edge streams, and the difference is unresolved."]),

    Node("D5-embed", "Embed the summary nodes", "command",
         _p_embed,
         command="python3 scripts/embed_summaries.py --resume",
         gate="python3 -m guru dossier status {work}",
         notes=["Only summary_nodes are retrievable, and only in study mode. "
                "Dossiers carry no embedding by design — a dossier is fetched "
                "by primary key and injected, never retrieved.",
                "export.py hard-fails on a summary_node with no embedding, so "
                "a gap here blocks the whole export."]),

    Node("D6-export", "Ship", "user",
         _p_export,
         notes=["USER ONLY, exactly as ingest node 15. Building "
                "export/guru-corpus.sql.gz locally is fine; shipping it is "
                "not. No sync_corpus.sh, no prod VPS, whatever the "
                "instruction said.",
                "export.py refuses to emit if any summary_node lacks an "
                "embedding — fix D5 rather than working around it."]),
]

NODES_BY_KEY = {n.key: n for n in NODES}


# ---------------------------------------------------------------- evaluation


def build_ctx(work_id: str, db_path: Path = DEFAULT_DB) -> Ctx:
    import works as works_mod

    campaign = load_campaign()
    plan = load_plan(campaign.get("campaign_id", ""))
    entry = None
    if plan:
        entry = next((w for w in plan.get("works", []) if w.get("work_id") == work_id), None)

    try:
        work = works_mod.load_works().get(work_id)
    except ValueError:
        work = None

    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) if db_path.is_file() else None
    return Ctx(work_id=work_id, campaign=campaign, plan=plan,
               plan_entry=entry, work=work, db=db)


def evaluate(ctx: Ctx) -> list[dict]:
    rows: list[dict] = []
    upstream_ok = True
    for node in NODES:
        ok, detail = node.probe(ctx)
        state = DONE if ok else (READY if upstream_ok else BLOCKED)
        rows.append({
            "key": node.key, "title": node.title, "kind": node.kind,
            "state": state, "detail": detail, "doc": node.doc,
            "contract": node.contract,
            "command": node.command.format(work=ctx.work_id),
            "gate": node.gate.format(work=ctx.work_id),
            "notes": node.notes,
        })
        if state != DONE:
            upstream_ok = False
    return rows


def find_drift(db_path: Path = DEFAULT_DB) -> dict:
    """Reconcile three views of the corpus that can disagree.

    The frozen span plan, the live dossier tables, and the works resolvable
    from ``corpus/`` on the current checkout. Two distinct failures show up as
    the same symptom — a live dossier the plan has never heard of — and they
    want opposite responses:

    ``off_plan``
        The work's texts are on disk and it has a live dossier, but the frozen
        plan does not contain it. This is the freeze violation V9 forbids: the
        plan artifact no longer describes the corpus. Fix by bumping the
        campaign and re-planning.

    ``orphaned``
        A live dossier for a work whose texts are not in ``corpus/`` at all.
        ``data/guru.db`` is git-ignored and therefore shared across every
        branch, while ``corpus/`` and ``sources/manifest.toml`` are tracked —
        so Pass D run on a feature branch leaves live rows that every other
        branch can see and cannot explain. Nothing is wrong with the rows;
        they belong to a checkout you are not on. Fix by checking out that
        branch, not by deleting anything.
    """
    campaign = load_campaign()
    cid = campaign.get("campaign_id", "")
    plan = load_plan(cid)
    planned = {w.get("work_id") for w in (plan or {}).get("works", [])}

    live: set[str] = set()
    if db_path.is_file():
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as db:
            try:
                live = {r[0] for r in db.execute("SELECT work_id FROM work_dossiers")}
            except sqlite3.Error:
                # A DB predating the v3_007 migration has no Pass D tables.
                live = set()

    import works as works_mod
    try:
        on_disk = set(works_mod.load_works())
        resolves = True
    except ValueError:
        on_disk, resolves = set(), False

    unplanned = live - planned
    return {
        "campaign_id": cid,
        "plan_exists": plan is not None,
        "works_toml_resolves": resolves,
        "planned": len(planned),
        "live": len(live),
        "on_disk": len(on_disk),
        "off_plan": sorted(unplanned & on_disk),
        "orphaned": sorted(unplanned - on_disk),
        "planned_unpromoted": sorted(planned - live),
        "on_disk_unplanned": sorted(on_disk - planned) if plan else [],
    }


# ---------------------------------------------------------------- commands

_MARK = {DONE: "[x]", READY: "[ ]", BLOCKED: "[-]", STALE: "[!]"}


def cmd_status(args: argparse.Namespace) -> None:
    ctx = build_ctx(args.work_id, Path(args.db))
    rows = evaluate(ctx)

    if args.json:
        print(json.dumps({"work": args.work_id, "campaign": ctx.campaign_id,
                          "nodes": rows}, indent=2))
        return

    label = getattr(ctx.work, "label", None) or "(not a known work)"
    print(f"\n  {args.work_id}  —  {label}")
    print(f"  campaign {ctx.campaign_id} · provider {ctx.campaign.get('provider', '?')}"
          f" · model {ctx.campaign.get('model', '?')}")
    print(f"  {'─' * 66}")
    for r in rows:
        kind = "" if r["kind"] == "command" else f"  ·{r['kind']}"
        print(f"  {_MARK[r['state']]} {r['key']:<18}{r['title']}{kind}")
        if r["state"] != DONE or args.verbose:
            print(f"      {r['detail']}")

    nxt = next((r for r in rows if r["state"] == READY), None)
    print()
    if nxt is None:
        print("  all nodes satisfied\n")
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
        print("  ── review gate; promotion to live tables is the user's call")
    if nxt["kind"] == "user":
        print("  ── USER GATE: stop here and hand back")
    for note in nxt["notes"]:
        print(f"  note: {note}")
    print()


def cmd_survey(args: argparse.Namespace) -> None:
    import works as works_mod
    try:
        all_works = works_mod.load_works()
    except ValueError as exc:
        raise SystemExit(f"works.toml does not resolve: {exc}")

    db_path = Path(args.db)
    stuck: dict[str, int] = {}
    for wid in sorted(all_works):
        ctx = build_ctx(wid, db_path)
        try:
            rows = evaluate(ctx)
        finally:
            if ctx.db is not None:
                ctx.db.close()
        nxt = next((r for r in rows if r["state"] == READY), None)
        where = nxt["key"] if nxt else "complete"
        stuck[where] = stuck.get(where, 0) + 1
        if args.verbose or (nxt and nxt["key"] != "D6-export"):
            print(f"  {where:<18}{wid:<38}{nxt['detail'] if nxt else ''}")

    print(f"\n  {len(all_works)} works")
    for k, v in sorted(stuck.items()):
        print(f"    {k:<18}{v}")
    print()


def cmd_drift(args: argparse.Namespace) -> None:
    d = find_drift(Path(args.db))
    if args.json:
        print(json.dumps(d, indent=2))
        return

    print(f"\n  campaign {d['campaign_id']} · {d['planned']} works planned · "
          f"{d['live']} dossiers live")
    if not d["plan_exists"]:
        print(f"  no frozen plan for campaign {d['campaign_id'] or '(unset)'}\n")
        return

    if not d["works_toml_resolves"]:
        print("\n  CANNOT CLASSIFY — sources/works.toml does not resolve.")
        print("  Without it there is no way to tell which live dossiers have")
        print("  texts on disk, so every unplanned work below would be filed")
        print("  as an orphan and told to be left alone. Fix works.toml first:")
        print("    python3 -c \'import sys;sys.path.insert(0,\"scripts\");"
              "import works;works.load_works()\'")
        print(f"\n  unplanned, unclassified ({len(d['orphaned'])}):")
        for w in d["orphaned"]:
            print(f"    {w}")
        print()
        return

    if d["off_plan"]:
        print(f"\n  FREEZE VIOLATION — live, on disk, not in the plan ({len(d['off_plan'])}):")
        for w in d["off_plan"]:
            print(f"    {w}")
        print("\n  The plan artifact no longer describes the corpus. The next")
        print("  --plan run must be a NEW campaign that reconciles these —")
        print("  never a re-plan in place.")

    if d["orphaned"]:
        print(f"\n  ORPHANED — live dossier, texts not in corpus/ ({len(d['orphaned'])}):")
        for w in d["orphaned"]:
            print(f"    {w}")
        print("\n  data/guru.db is git-ignored and shared across branches;")
        print("  corpus/ and sources/manifest.toml are tracked. These rows were")
        print("  almost certainly generated on a branch this checkout is not on.")
        print("  Find it with:  git log --oneline --all -- corpus/<tradition>")
        print("  Do not delete them to make this message go away.")

    if d["on_disk_unplanned"]:
        print(f"\n  on disk, not planned, no dossier yet ({len(d['on_disk_unplanned'])}):")
        for w in d["on_disk_unplanned"]:
            print(f"    {w}")

    if d["planned_unpromoted"]:
        print(f"\n  planned, not yet promoted ({len(d['planned_unpromoted'])}):")
        for w in d["planned_unpromoted"]:
            print(f"    {w}")

    if not (d["off_plan"] or d["orphaned"] or d["on_disk_unplanned"]):
        print("  no drift — every live dossier is in the frozen plan")
    print()


def cmd_nodes(args: argparse.Namespace) -> None:
    for n in NODES:
        print(f"  {n.key:<18}{n.kind:<11}{n.title}")


def register(sub: argparse._SubParsersAction) -> None:
    dp = sub.add_parser("dossier", help="Pass D (dossier + summary) state machine")
    dsub = dp.add_subparsers(dest="dossier_command", required=True)

    sp = dsub.add_parser("status", help="Show Pass D state for one work")
    sp.add_argument("work_id")
    sp.add_argument("--db", default=str(DEFAULT_DB))
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--verbose", "-v", action="store_true")
    sp.set_defaults(func=cmd_status)

    vp = dsub.add_parser("survey", help="Where every work is stuck")
    vp.add_argument("--db", default=str(DEFAULT_DB))
    vp.add_argument("--verbose", "-v", action="store_true",
                    help="include works that are complete")
    vp.set_defaults(func=cmd_survey)

    fp = dsub.add_parser("drift", help="Live dossiers the frozen plan doesn't know about")
    fp.add_argument("--db", default=str(DEFAULT_DB))
    fp.add_argument("--json", action="store_true")
    fp.set_defaults(func=cmd_drift)

    np_ = dsub.add_parser("nodes", help="List the Pass D nodes")
    np_.set_defaults(func=cmd_nodes)
