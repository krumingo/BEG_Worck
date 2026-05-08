import csv
import os
import sys

# важно: да сочи към backend папката
sys.path.append(os.path.abspath("./app/backend"))

from server import app  # FastAPI instance

OUT = "audit_endpoints.csv"

rows = []
for r in app.routes:
    methods = getattr(r, "methods", None)
    if not methods:
        continue
    path = getattr(r, "path", "")
    name = getattr(r, "name", "")
    endpoint = getattr(r, "endpoint", None)
    func = getattr(endpoint, "__name__", "") if endpoint else ""
    # пропускай docs/openapi, ако искаш:
    if path.startswith("/openapi") or path.startswith("/docs") or path.startswith("/redoc"):
        continue
    rows.append([path, ",".join(sorted(methods)), name, func])

rows.sort(key=lambda x: (x[0], x[1]))

with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["path", "methods", "route_name", "handler_func"])
    w.writerows(rows)

print(f"OK: wrote {len(rows)} routes to {OUT}")
