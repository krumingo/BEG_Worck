"""Group run/process.jsonl into the same columns as data/main_process_grouped.csv
(flow, step, ok, times, role, method, path, status, expected, actual_first, rule_note).
Only the last detached run (from the last `run start`)."""
import csv
import json
import sys
from collections import OrderedDict

src = sys.argv[1] if len(sys.argv) > 1 else "/tmp/claude-0/demo_int/run/process.jsonl"
dst = sys.argv[2] if len(sys.argv) > 2 else "/tmp/claude-0/demo_int/run/int_process_grouped.csv"
rows = [json.loads(l) for l in open(src, encoding="utf8") if l.strip()]
starts = [i for i, r in enumerate(rows) if r.get("flow") == "run" and r.get("step") == "start"]
rows = rows[starts[-1]:] if starts else rows
g = OrderedDict()
for r in rows:
    if r["flow"] == "run":
        continue
    g.setdefault((r["flow"], r["step"], r["ok"]), []).append(r)
with open(dst, "w", newline="", encoding="utf8") as f:
    w = csv.writer(f)
    w.writerow(["flow", "step", "ok", "times", "role", "method", "path", "status", "expected", "actual_first", "rule_note"])
    for (flow, step, ok), v in g.items():
        a = v[0]
        w.writerow([flow, step, ok, len(v), a.get("role"), a.get("method"), a.get("path"), a.get("status"),
                    a.get("expected"), a.get("actual"), a.get("note")])
print("cycles:", sum(1 for r in rows if r["step"].startswith("cycle_end_")), "groups:", len(g))
