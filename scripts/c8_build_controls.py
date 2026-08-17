#!/usr/bin/env python3
"""Build negative-control rows: accepted outputs with a known injected failure.

The natural review is 71/72 accept, so agreement alone cannot separate a
discriminating judge from a rubber stamp. Each control takes a row the opus
judge ACCEPTED and injects exactly one unambiguous rubric violation, so a
grader that fails to reject it has demonstrably missed that code.
"""
import json, sqlite3, subprocess, sys
from pathlib import Path

W = Path("/home/ivy/Work/guru-worktrees/feat-c8-local-dossier-bench")
SP = Path("/tmp/claude-1000/-home-ivy-Work/1acc0339-98d8-41ca-bce4-3cf6a76a2e10/scratchpad")
DB = W / "data" / "guru.db"

accepted = [json.loads(l) for l in (SP / "review_results.jsonl").open() if l.strip()]
accepted = [r for r in accepted if (r["verdict"] or {}).get("verdict") == "accept"]

def show(row_id):
    o = subprocess.run(["python3", "scripts/review_dossiers.py", "--db", str(DB), "show", row_id],
                       capture_output=True, text=True, cwd=W).stdout
    out = o.split("---- OUTPUT ----")[1].split("---- STAGE INPUT ----")[0].strip()
    si = o.split("---- STAGE INPUT ----")[1].strip()
    return out, si

# One injection per code. Each is checkable against the stage input by hand.
INJECTIONS = [
    ("GROUND", "append",
     " The text was composed in Alexandria in the year 213 CE, during the reign "
     "of Caracalla, and its author served as high priest for eleven years."),
    ("GROUND", "append",
     " The narrator states that he had already been initiated at Eleusis before "
     "these events, and that his brother later recanted the teaching."),
    ("LEAK", "append",
     " This account parallels the treatment in Plotinus' Enneads IV.8 and is "
     "cited approvingly in Ficino's Theologia Platonica."),
    ("LEAK", "append",
     " Compare the Gospel of Thomas, logion 77, where the same doctrine appears "
     "in a compressed form."),
    ("REGISTER", "prepend",
     "You will find this passage to be the most profound and beautiful section "
     "of the entire work, and it rewards careful devotional reading. "),
    ("COVERAGE", "truncate", None),
]

rows = []
for i, (code, mode, text) in enumerate(INJECTIONS):
    src = accepted[i * 5 % len(accepted)]
    out, si = show(src["row_id"])
    if mode == "append":
        mutated = out.rstrip() + text
    elif mode == "prepend":
        mutated = text + out
    else:  # truncate — drop everything after the first third, losing later episodes
        paras = [p for p in out.split("\n\n") if p.strip()]
        keep = max(1, len(paras) // 3)
        mutated = "\n\n".join(paras[:keep])
    rows.append({"control_id": f"ctl{i+1}", "injected_code": code, "mode": mode,
                 "src_row": src["row_id"], "src_arm": src["arm"],
                 "work_id": src["work_id"], "output": mutated, "stage_input": si})

(SP / "controls.json").write_text(json.dumps(rows, indent=1))
print(f"built {len(rows)} controls")
for r in rows:
    print(f"  {r['control_id']}  {r['injected_code']:9} {r['mode']:8} from {r['src_row']} ({r['src_arm']}) "
          f"{len(r['output'])} chars")
