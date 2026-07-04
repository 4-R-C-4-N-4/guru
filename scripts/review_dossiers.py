"""
review_dossiers.py — rubric review loop for staged dossier rows (§1.3.4, G6).

The converging unit is the TEMPLATE, not the row: sample K works stratified by
tradition and size, review each sampled row against the rubric codes (GROUND /
HEDGE / REGISTER / COVERAGE / LEAK / FORMAT / COMPARE), revise the template on
clustered failures, then bulk-accept the passing batch. `show` prints the
row's stage INPUT alongside the output — with a frontier-model generator the
reviewer must see what the model was allowed to know to check GROUND/LEAK
(design §1.3.4 caveat).

Commands:
    sample            stratified review sample for a field/level
    show ID           one staged row + its reconstructed stage input
    accept ID / reject ID --code GROUND [--note ...]
    bulk-accept --field summary --prompt-version summary-v1 [--model m]
    status            pending/accepted/rejected counts per field/level

IDs are 'f<row>' (staged_dossier_fields) or 's<row>' (staged_summaries).
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

logger = logging.getLogger(__name__)
DEFAULT_DB = PROJECT_ROOT / "data" / "guru.db"

RUBRIC = ("GROUND", "HEDGE", "REGISTER", "COVERAGE", "LEAK", "FORMAT", "COMPARE")


def _conn(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def _table(rid: str) -> tuple[str, int]:
    if rid[0] == "f":
        return "staged_dossier_fields", int(rid[1:])
    if rid[0] == "s":
        return "staged_summaries", int(rid[1:])
    raise SystemExit(f"bad id {rid!r} (want f<n> or s<n>)")


def cmd_sample(conn, args):
    cfg_k = args.k
    if args.level:
        rows = conn.execute(
            "SELECT * FROM staged_summaries WHERE level=? AND status='pending'", (args.level,)).fetchall()
        keyfn = lambda r: r["work_id"].split(".")[0]
    else:
        rows = conn.execute(
            "SELECT * FROM staged_dossier_fields WHERE field=? AND status='pending'", (args.field,)).fetchall()
        keyfn = lambda r: r["work_id"]
    if not rows:
        logger.info("nothing pending")
        return
    rng = random.Random(args.seed)
    by_stratum: dict[str, list] = {}
    for r in rows:
        by_stratum.setdefault(keyfn(r), []).append(r)
    picks, strata = [], sorted(by_stratum)
    while len(picks) < min(cfg_k, len(rows)) and strata:
        for st in list(strata):
            if by_stratum[st]:
                picks.append(by_stratum[st].pop(rng.randrange(len(by_stratum[st]))))
                if len(picks) >= cfg_k:
                    break
            else:
                strata.remove(st)
    prefix = "s" if args.level else "f"
    for r in picks:
        span = r["section_span"] or "-"
        logger.info(f"{prefix}{r['id']}\t{r['work_id']}\t{span}\t{r['prompt_version']}")


def _stage_input(conn, table, row) -> str:
    """Reconstruct what the generator fed this row (best effort, for GROUND/LEAK)."""
    if table == "staged_summaries":
        if row["child_chunk_ids"]:
            from generate_dossiers import _chunk_bodies
            return _chunk_bodies(json.loads(row["child_chunk_ids"]))
        if row["child_summary_ids"]:
            sids = json.loads(row["child_summary_ids"])
            qs = ",".join("?" for _ in sids)
            rs = conn.execute(f"SELECT section_span, body FROM staged_summaries"
                              f" WHERE summary_id IN ({qs}) AND status='accepted'", sids).fetchall()
            return "\n\n".join(f"[{r['section_span']}] {r['body']}" for r in rs)
        return "(input unavailable)"
    field = row["field"]
    if field == "structure_entry":
        r = conn.execute("SELECT body FROM staged_summaries WHERE work_id=? AND section_span=?"
                         " AND status='accepted' ORDER BY id DESC LIMIT 1",
                         (row["work_id"], row["section_span"])).fetchone()
        return r["body"] if r else "(accepted L1 not found)"
    if field in ("summary", "context"):
        from generate_dossiers import _manifest_notes
        from works import load_works
        l2 = conn.execute("SELECT body FROM staged_summaries WHERE work_id=? AND level=2"
                          " AND status='accepted' ORDER BY id DESC LIMIT 1", (row["work_id"],)).fetchone()
        notes = _manifest_notes(load_works()[row["work_id"]].members)
        return f"L2 SUMMARY:\n{l2['body'] if l2 else '(missing)'}\n\nCURATOR'S NOTES:\n{notes}"
    rs = conn.execute("SELECT section_span, body FROM staged_summaries WHERE work_id=?"
                      " AND status='accepted' ORDER BY id", (row["work_id"],)).fetchall()
    return "\n\n".join(f"[{r['section_span'] or 'whole work'}] {r['body']}" for r in rs)


def cmd_show(conn, args):
    table, rid = _table(args.id)
    row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (rid,)).fetchone()
    if row is None:
        raise SystemExit("no such row")
    print(f"== {args.id} [{table}] {row['work_id']} / "
          f"{row['section_span'] if 'section_span' in row.keys() else ''} "
          f"({row['status']}, {row['model']}, {row['prompt_version']})\n")
    out = row["payload_json"] if table == "staged_dossier_fields" else row["body"]
    print("---- OUTPUT ----\n" + str(out) + "\n")
    print("---- STAGE INPUT ----\n" + _stage_input(conn, table, row))


def _transition(conn, rid_s, status, code=None, note=None):
    table, rid = _table(rid_s)
    marker = f"agent:{code}" if code else "agent"
    if note:
        marker += f" — {note}"
    n = conn.execute(
        f"UPDATE {table} SET status=?, reviewed_by=?, reviewed_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')"
        f" WHERE id=? AND status='pending'", (status, marker, rid)).rowcount
    conn.commit()
    if n == 0:
        raise SystemExit("row not pending (or missing)")
    logger.info(f"{rid_s} -> {status}")


def cmd_bulk_accept(conn, args):
    if args.level:
        q = ("UPDATE staged_summaries SET status='accepted', reviewed_by='bulk',"
             " reviewed_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')"
             " WHERE level=? AND prompt_version=? AND status='pending'")
        params = [args.level, args.prompt_version]
    else:
        q = ("UPDATE staged_dossier_fields SET status='accepted', reviewed_by='bulk',"
             " reviewed_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')"
             " WHERE field=? AND prompt_version=? AND status='pending'")
        params = [args.field, args.prompt_version]
    if args.model:
        q += " AND model=?"
        params.append(args.model)
    n = conn.execute(q, params).rowcount
    conn.commit()
    logger.info(f"bulk-accepted {n} rows")


def cmd_status(conn, _args):
    for r in conn.execute("SELECT field, status, COUNT(*) n FROM staged_dossier_fields"
                          " GROUP BY 1,2 ORDER BY 1,2"):
        logger.info(f"field {r['field']:16s} {r['status']:9s} {r['n']}")
    for r in conn.execute("SELECT level, status, COUNT(*) n FROM staged_summaries"
                          " GROUP BY 1,2 ORDER BY 1,2"):
        logger.info(f"summary L{r['level']}        {r['status']:9s} {r['n']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("sample")
    sp.add_argument("--field")
    sp.add_argument("--level", type=int)
    sp.add_argument("--k", type=int, default=15)
    sp.add_argument("--seed", type=int, default=0)
    sh = sub.add_parser("show")
    sh.add_argument("id")
    for name, status in (("accept", "accepted"), ("reject", "rejected")):
        p = sub.add_parser(name)
        p.add_argument("id")
        p.add_argument("--code", choices=RUBRIC, required=(name == "reject"))
        p.add_argument("--note")
        p.set_defaults(status=status)
    ba = sub.add_parser("bulk-accept")
    ba.add_argument("--field")
    ba.add_argument("--level", type=int)
    ba.add_argument("--prompt-version", required=True)
    ba.add_argument("--model")
    sub.add_parser("status")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    conn = _conn(args.db)
    if args.cmd == "sample":
        if bool(args.field) == bool(args.level):
            raise SystemExit("pass exactly one of --field / --level")
        cmd_sample(conn, args)
    elif args.cmd == "show":
        cmd_show(conn, args)
    elif args.cmd in ("accept", "reject"):
        _transition(conn, args.id, args.status, args.code, args.note)
    elif args.cmd == "bulk-accept":
        if bool(args.field) == bool(args.level):
            raise SystemExit("pass exactly one of --field / --level")
        cmd_bulk_accept(conn, args)
    elif args.cmd == "status":
        cmd_status(conn, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
