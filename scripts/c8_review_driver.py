#!/usr/bin/env python3
"""Blind paired rubric review: judge both arms of the c8 benchmark with opus.

Blinding: the judge receives ONLY stage_input, output, field, work_label and
prompt_version — never the model that produced the row, and never which arm it
belongs to. Rows are shuffled with a fixed seed so any judge drift over the run
cannot correlate with arm.
"""
import json, random, re, sqlite3, subprocess, sys, time
from pathlib import Path

W = Path("/home/ivy/Work/guru-worktrees/feat-c8-local-dossier-bench")
SP = Path("/tmp/claude-1000/-home-ivy-Work/1acc0339-98d8-41ca-bce4-3cf6a76a2e10/scratchpad")
DB = W / "data" / "guru.db"
RUBRIC = W / "prompts" / "dossier" / "contracts" / "review-rubric.md"
OUT = SP / "review_results.jsonl"
LOCAL = "Qwen3.8-27B-UD-Q4_K_XL.gguf"
FRONTIER = "claude-opus-4-8"

labels = {w["work_id"]: w["label"]
          for w in json.load(open(W / "docs/summary/span-plan-c8-bench.json"))["works"]}

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
con.row_factory = sqlite3.Row
paired = [r["summary_id"] for r in con.execute(
    "SELECT summary_id FROM staged_summaries WHERE model=? AND prompt_version='l1-v3'", (LOCAL,))]

rows = []
for sid in paired:
    for model, arm in ((LOCAL, "local"), (FRONTIER, "frontier")):
        r = con.execute(
            "SELECT id, work_id FROM staged_summaries WHERE summary_id=? AND model=?"
            " AND prompt_version='l1-v3' ORDER BY (status='accepted') DESC, id DESC LIMIT 1",
            (sid, model)).fetchone()
        if r:
            rows.append({"row_id": f"s{r['id']}", "summary_id": sid,
                         "work_id": r["work_id"], "arm": arm})

random.Random(20260816).shuffle(rows)
print(f"{len(rows)} rows to judge "
      f"({sum(r['arm']=='local' for r in rows)} local / "
      f"{sum(r['arm']=='frontier' for r in rows)} frontier)", flush=True)

done = set()
if OUT.exists():
    done = {json.loads(l)["row_id"] for l in OUT.open() if l.strip()}
    print(f"resuming — {len(done)} already judged", flush=True)

for n, row in enumerate(rows, 1):
    if row["row_id"] in done:
        continue
    show = subprocess.run(
        ["python3", "scripts/review_dossiers.py", "--db", str(DB), "show", row["row_id"]],
        capture_output=True, text=True, cwd=W).stdout
    try:
        out_txt = show.split("---- OUTPUT ----")[1].split("---- STAGE INPUT ----")[0].strip()
        in_txt = show.split("---- STAGE INPUT ----")[1].strip()
    except IndexError:
        print(f"  [{n}/{len(rows)}] {row['row_id']}: show parse failed", flush=True)
        continue

    (SP / "_si.txt").write_text(in_txt)
    (SP / "_out.txt").write_text(out_txt)

    t0 = time.time()
    p = subprocess.run(
        ["python3", "scripts/run_contract.py", str(RUBRIC),
         "--provider", "claude-code", "--model", FRONTIER,
         "--budget", "200000",
         "--input", f"stage_input={SP/'_si.txt'}",
         "--input", f"output={SP/'_out.txt'}",
         "--var", "field=l1",
         "--var", f"work_label={labels.get(row['work_id'], row['work_id'])}",
         "--var", "prompt_version=l1-v3"],
        capture_output=True, text=True, cwd=W)

    verdict = None
    for blob in re.findall(r"\{.*\}", p.stdout, re.DOTALL):
        try:
            verdict = json.loads(blob); break
        except json.JSONDecodeError:
            continue
    rec = {**row, "elapsed": round(time.time() - t0, 1),
           "verdict": verdict, "rc": p.returncode,
           "stderr": (p.stderr or "")[-300:] if verdict is None else ""}
    with OUT.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    v = (verdict or {}).get("verdict", "PARSE-FAIL")
    c = (verdict or {}).get("code") or "-"
    print(f"  [{n}/{len(rows)}] {row['row_id']:7} {row['arm']:8} {v:18} {c:9} {rec['elapsed']}s", flush=True)

print("done", flush=True)
