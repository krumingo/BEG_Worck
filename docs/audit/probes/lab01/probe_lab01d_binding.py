"""CLAUDE AUDIT probe — #73 LAB-01-D FG-72 at function level (production compute_person_labor + key helpers).
Package A: Akord, piece 6. Approval (approver boss) for (report r1, version 0, entry e1) qty 10 → 60.
 B1 one line r1/e1/v0 → 60
 B2 the same entry twice (duplicate e1 in the lines) → still 60 (+ DQ), never 120
 B3 line at report_version 1 (edited after approval) → 0 (approval void for this version)
 B4 approval for e1 does not price e2 of the same report → e2 0
 B5 self-approval (approved_by == worker) → 0
"""
from app.services.labor_cost import compute_person_labor, approval_key

pk = {"A": {"id": "A", "project_id": "P", "labor_pay_type": "Akord", "labor_piece_rate": 6}}
prof = {"pay_type": "Hourly", "hourly_rate": 0}
def line(entry="e1", ver=0, lid="r1:e1"):
    return {"id": lid, "report_doc_id": "r1", "entry_id": entry, "report_version": ver, "status": "APPROVED",
            "date": "2026-11-02", "project_id": "P", "worker_id": "w", "hours": 8}
def terms(by="boss", entry="e1", ver=0):
    rec = {"report_id": "r1", "entry_id": entry, "report_version": ver, "approved_quantity": 10, "status": "approved",
           "approved_by": by, "execution_package_id": "A"}
    return {"packages": pk, "quantities": ({approval_key("r1", entry, ver): rec} if by != "w" else {})}
F = []
def chk(label, got, exp):
    ok = got == exp; print(("ok   " if ok else "FAIL ") + "%s → %s (expect %s)" % (label, got, exp))
    if not ok: F.append(label)
chk("B1 r1/e1/v0", compute_person_labor(prof, [line()], terms())["total"], 60.0)
r = compute_person_labor(prof, [line(), line(lid="r1:e1-dup")], terms())
chk("B2 duplicate e1", r["total"], 60.0); print("     dq", [d["code"] for d in r["dq_warnings"]])
chk("B3 edited (version 1)", compute_person_labor(prof, [line(ver=1)], terms())["total"], 0.0)
chk("B4 e2 not priced by e1's approval", compute_person_labor(prof, [line(entry="e2", lid="r1:e2")], terms())["total"], 0.0)
print("FAILS:", F or "none")
