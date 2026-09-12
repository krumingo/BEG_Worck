#!/usr/bin/env python3
"""
W0-02 — Inventory of remaining legacy permission checks.

A MIGRATION / DEVELOPMENT tool ONLY. It is never imported by the application
and takes no part in the production request path (guardrail G4). It scans the
source for ad-hoc role checks so we can track progress toward "no protected
route bypasses the Permission Service" (the real Definition of Done for W0-02).

Usage:
    python scripts/w0_02_permission_inventory.py           # table to stdout
    python scripts/w0_02_permission_inventory.py --csv out.csv
"""
import os
import re
import sys
import csv
from pathlib import Path

APP_DIR = Path(__file__).parent.parent / "app"

# Lines that represent a legacy, role-based authorization decision.
CHECK_RE = re.compile(r'user\s*\[\s*[\'"]role[\'"]\s*\]|require_admin|can_access_project|can_manage_project|REVIEW_ROLES')
ROUTE_RE = re.compile(r'@router\.(get|post|put|patch|delete)\(\s*[\'"]([^\'"]+)[\'"]')
# Routes already migrated to require_permission in PR-1.
MIGRATED = {
    ("POST", "/users"),
    ("PUT", "/users/{user_id}"),
    ("GET", "/projects/{project_id}/activity-budgets"),
    ("POST", "/assets/intake/{intake_id}/approve"),
}


def scan():
    rows = []
    for path in sorted(APP_DIR.rglob("*.py")):
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        last_route = ("", "")   # (method, path)
        for i, line in enumerate(lines, start=1):
            m = ROUTE_RE.search(line)
            if m:
                last_route = (m.group(1).upper(), m.group(2))
                continue
            if CHECK_RE.search(line) and "require_permission" not in line:
                method, route = last_route
                migrated = (method, route) in MIGRATED
                rows.append({
                    "file": str(path.relative_to(APP_DIR.parent)),
                    "line": i,
                    "route": route,
                    "http_method": method,
                    "legacy_role_check": line.strip()[:120],
                    "presumed_module": "",
                    "presumed_action": "",
                    "migration_status": "migrated" if migrated else "pending",
                    "target_pr_or_wave": "PR-1" if migrated else "W0-02-followup",
                })
    return rows


def main():
    rows = scan()
    pending = [r for r in rows if r["migration_status"] == "pending"]
    if "--csv" in sys.argv:
        out = sys.argv[sys.argv.index("--csv") + 1]
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
            w.writeheader()
            w.writerows(rows)
        print(f"Wrote {len(rows)} rows to {out}")
    else:
        for r in rows:
            flag = "OK " if r["migration_status"] == "migrated" else "TODO"
            print(f"[{flag}] {r['file']}:{r['line']}  {r['http_method']} {r['route']}  | {r['legacy_role_check']}")
    print()
    print(f"Total legacy checks: {len(rows)}  |  migrated: {len(rows) - len(pending)}  |  remaining: {len(pending)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
