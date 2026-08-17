#!/usr/bin/env python3
"""Run one grader over the 72 paired rows + 6 negative controls.

usage: run_grader.py <label> <provider> <model>
Writes grader_<label>.jsonl. Resumable.
"""
import json, random, re, sqlite3, subprocess, sys, time
from pathlib import Path

label, provider, model = sys.argv[1], sys.argv[2], sys.argv[3]
W = Path("/home/ivy/Work/guru-worktrees/feat-c8-local-dossier-bench")
SP = Path("/tmp/claude-1000/-home-ivy-Work/1acc0339-98d8-41ca-bce4-3cf6a76a2e10/scratchpad")
DB = W / "data" / "guru.db"
RUBRIC = W / "prompts" / "dossier" / "contracts" / "review-rubric.md"
OUT = SP / f"grader_{label}.jsonl"
LOCAL, FRONTIER = "Qwen3.8-27B-UD-Q4_K_XL.gguf", "claude-opus-4-8"

labels = {w["work_id"]: w["label"]
          for w in json.load(open(W / "docs/summary/span-plan-c8.json"))["works"]}
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True); con.row_factory = sqlite3.Row

items = []
for sid, in con.execute("SELECT summary_id FROM staged_summaries WHERE model=? AND prompt_version='l1-v3'", (LOCAL,)):
    for m, arm in ((LOCAL, "local"), (FRONTIER, "frontier")):
        r = con.execute("SELECT id, work_id FROM staged_summaries WHERE summary_id=? AND model=?"
                        " AND prompt_version='l1-v3' ORDER BY (status='accepted') DESC, id DESC LIMIT 1",
                        (sid, m)).fetchone()
        if r:
            items.append({"key": f"s{r['id']}", "arm": arm, "work_id": r["work_id"], "kind": "paired"})
for c in json.load((SP / "controls.json").open()):
    items.append({"key": c["control_id"], "arm": "control", "work_id": c["work_id"],
                  "kind": "control", "injected_code": c["injected_code"]})

random.Random(20260816).shuffle(items)
done = {json.loads(l)["key"] for l in OUT.open()} if OUT.exists() else set()
print(f"[{label}] {len(items)} items, {len(done)} already done", flush=True)

controls = {c["control_id"]: c for c in json.load((SP / "controls.json").open())}

for n, it in enumerate(items, 1):
    if it["key"] in done:
        continue
    if it["kind"] == "control":
        c = controls[it["key"]]
        out_txt, in_txt = c["output"], c["stage_input"]
    else:
        o = subprocess.run(["python3", "scripts/review_dossiers.py", "--db", str(DB), "show", it["key"]],
                           capture_output=True, text=True, cwd=W).stdout
        try:
            out_txt = o.split("---- OUTPUT ----")[1].split("---- STAGE INPUT ----")[0].strip()
            in_txt = o.split("---- STAGE INPUT ----")[1].strip()
        except IndexError:
            continue
    (SP / f"_si_{label}.txt").write_text(in_txt)
    (SP / f"_out_{label}.txt").write_text(out_txt)

    t0 = time.time()
    p = subprocess.run(
        ["python3", "scripts/run_contract.py", str(RUBRIC),
         "--provider", provider, "--model", model, "--budget", "200000",
         # the contract sets max_tokens=2048; claude-code ignores it entirely
         # (not enforceable through the CLI) so opus judged unbounded. Local
         # graders get comparable room, else a thinking pass alone exhausts the
         # allowance and no verdict is ever emitted.
         "--max-tokens", "6000",
         "--input", f"stage_input={SP/f'_si_{label}.txt'}",
         "--input", f"output={SP/f'_out_{label}.txt'}",
         "--var", "field=l1", "--var", f"work_label={labels.get(it['work_id'], it['work_id'])}",
         "--var", "prompt_version=l1-v3"],
        capture_output=True, text=True, cwd=W)
    verdict = None
    for blob in re.findall(r"\{.*\}", p.stdout, re.DOTALL):
        try:
            verdict = json.loads(blob); break
        except json.JSONDecodeError:
            continue
    rec = {**it, "grader": label, "elapsed": round(time.time()-t0, 1),
           "verdict": verdict, "rc": p.returncode,
           "err": (p.stderr or "")[-200:] if verdict is None else ""}
    with OUT.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    v = (verdict or {}).get("verdict", "PARSE-FAIL")
    print(f"  [{n}/{len(items)}] {it['key']:7} {it['arm']:8} {v:18} {rec['elapsed']}s", flush=True)
print("done", flush=True)
