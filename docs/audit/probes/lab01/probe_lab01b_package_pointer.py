"""CLAUDE AUDIT probe — #73 LAB-01-B FG-64: line.pay_type / piece_rate / approved_quantity are ignored, but the
PACKAGE that prices a line is still line.execution_package_id when no approval record names one (the worker
edits day_entries; FG-64 itself says PUT /daily-reports does not validate them). Only a cross-project package
is refused. Can a worker change their pay by pointing the line at another package of the SAME project?
 P1 time work: profile Monthly 1100 / 22 d (50 / day), hourly_rate 15; 12 h on one day.
    line → no package | package A (labor_pay_type Hourly) | package B (Daily, rate from profile).
 P2 akord: approval record (approver ≠ worker) with quantity 100 but WITHOUT execution_package_id;
    line → package C (piece 2) vs package D (piece 9).
"""
from app.services.labor_cost import compute_person_labor

prof = {"pay_type": "Monthly", "monthly_salary": 1100, "working_days_per_month": 22, "hourly_rate": 15, "daily_rate": 120}
base = {"id": "r1", "status": "APPROVED", "date": "2026-11-02", "project_id": "P", "worker_id": "w", "hours": 12}
pk = {"A": {"id": "A", "project_id": "P", "labor_pay_type": "Hourly"},
      "B": {"id": "B", "project_id": "P", "labor_pay_type": "Daily"},
      "C": {"id": "C", "project_id": "P", "labor_pay_type": "Akord", "labor_piece_rate": 2},
      "D": {"id": "D", "project_id": "P", "labor_pay_type": "Akord", "labor_piece_rate": 9}}
F = []
res = {}
for label, pkg in (("no package", None), ("package A Hourly", "A"), ("package B Daily", "B")):
    ln = dict(base, execution_package_id=pkg) if pkg else dict(base)
    res[label] = compute_person_labor(prof, [ln], {"packages": pk, "quantities": {}})["total"]
print("P1 time work, same report, worker-chosen package →", res)
if len(set(res.values())) > 1: F.append("P1 worker-chosen package changes pay: %s" % res)
q = {"r1": {"report_id": "r1", "approved_quantity": 100, "status": "approved", "approved_by": "boss"}}
r2 = {}
for pkg in ("C", "D"):
    r2[pkg] = compute_person_labor(prof, [dict(base, execution_package_id=pkg)], {"packages": pk, "quantities": q})["total"]
print("P2 akord, approval without package, worker-chosen package →", r2)
if len(set(r2.values())) > 1: F.append("P2 worker-chosen package changes akord pay: %s" % r2)
print("FAILS:", F or "none")
