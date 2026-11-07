"""LAB-01-F probe (copy to <wt73>/backend/tests/, one test per process).

F1 week / 3-week / month runs over ONE 60 overpayment -> 1 record (orchestrator's ask).
F2 a DRAFT monthly run in which later UNPAID earnings absorb the 60 (earned 720 vs paid 660):
   does it supersede the pending correction? Then a new weekly run: does the record come back?
"""
import pytest
from tests.test_lab_01_labor_cost import ORG, P_END, P_START, _report, _token, run, backend  # noqa
from tests.test_lab_01_e_flow_guard_7 import _body, _old_run


def _k(x):
    return dict(_token(), **{"Idempotency-Key": x})


def test_f1_three_windows_one_record(monkeypatch, backend):
    async def scenario(c, op):
        await _old_run(op)
        ids = []
        for i, (s, e) in enumerate([(P_START, P_END), (P_START, "2026-10-25"), ("2026-10-01", "2026-10-31")]):
            r = await c.post("/api/pay-runs", json=dict(_body(), period_start=s, period_end=e), headers=_k(f"f1-{i}"))
            assert r.status_code == 200, r.text
            ids.append(r.json()["id"])
        recs = await op.payroll_corrections.find({}, {"_id": 0}).to_list(10)
        print("F1", backend, [(x["amount"], x["status"], x.get("source_pay_run_ids") or x.get("source_pay_run_id"), len(x["pay_run_ids"])) for x in recs])
        assert len(recs) == 1 and recs[0]["amount"] == 60.0
    run(monkeypatch, scenario, backend)


def test_f2_draft_netting_supersedes(monkeypatch):
    async def scenario(c, op):
        await _old_run(op)
        r = await c.post("/api/pay-runs", json=_body(), headers=_k("f2-w"))
        assert r.status_code == 200, r.text
        # later unpaid akord work: 24 m2 x 5 = 120 earned on 2026-10-20
        await op.employee_daily_reports.insert_one(_report("ak-late", "w-akord", "2026-10-20", "prj-1", 8,
                                                          quantity=24, unit="m2", execution_package_id="pkg-ak"))
        await op.labor_quantity_approvals.insert_one({"id": "qa-late", "org_id": ORG, "report_id": "ak-late",
                                                      "approved_quantity": 24, "status": "approved", "approved_by": "admin",
                                                      "execution_package_id": "pkg-ak", "approved_at": "2026-10-20T18:00:00"})
        m = await c.post("/api/pay-runs", json=dict(_body(), period_start="2026-10-01", period_end="2026-10-31"),
                         headers=_k("f2-m"))
        assert m.status_code == 200, m.text
        row = m.json()["employee_rows"][0]
        rec = await op.payroll_corrections.find_one({}, {"_id": 0})
        print("F2 month draft: earned", row.get("earned_amount"), "prev paid counted", row.get("previously_paid"),
              "prev paid total", row.get("previously_paid_total"), "receivable", row.get("receivable_from_overpayment"),
              "remaining", row.get("remaining_after_payment"),
              "item", bool(row.get("correction_item")), "-> correction status", rec["status"])
        w2 = await c.post("/api/pay-runs", json=_body(), headers=_k("f2-w2"))
        rec2 = await op.payroll_corrections.find_one({}, {"_id": 0})
        n = await op.payroll_corrections.count_documents({})
        print("F2 new weekly run:", w2.status_code, "-> status", rec2["status"], "version", rec2["version"], "amount", rec2["amount"], "records", n,
              "| weekly remaining", w2.json()["employee_rows"][0].get("remaining_after_payment"))
        assert rec["status"] == "pending_approval" and rec2["status"] == "pending_approval" and n == 1
    run(monkeypatch, scenario, "real")


def test_g1_two_runs_paid_same_days(monkeypatch):
    """G1 (LAB-01-G): run-old paid 660 and run-old-2 paid 600 for the SAME week (earned 600)
    -> receivables 60 (run-old) + 600 (run-old-2), counted 600, remaining 0."""
    async def scenario(c, op):
        await _old_run(op)
        await op.pay_runs.insert_one({
            "id": "run-old-2", "org_id": ORG, "number": "PR-0002", "status": "confirmed", "version": 1,
            "period_start": P_START, "period_end": P_END, "week_number": 42, "paid_at": None,
            "employee_rows": [{"employee_id": "w-akord", "earned_amount": 600, "paid_now_amount": 600.0}],
            "totals": {"earned": 600}, "history": []})
        r = await c.post("/api/pay-runs", json=_body(), headers=_k("g1"))
        row = r.json()["employee_rows"][0]
        recs = sorted((x["source_pay_run_id"], x["amount"]) for x in await op.payroll_corrections.find({}).to_list(10))
        print("G1", r.status_code, "counted", row.get("previously_paid"), "receivable", row.get("receivable_from_overpayment"),
              "remaining", row.get("remaining_after_payment"), "records", recs)
        assert recs == [("run-old", 60.0), ("run-old-2", 600.0)]
    run(monkeypatch, scenario, "real")


def test_g3_overpay_in_this_run(monkeypatch):
    """G3: a run that pays 700 now against 600 earned (no earlier run): is a receivable recorded
    at once, or only when a later run sees the paid line?"""
    async def scenario(c, op):
        body = dict(_body("confirmed"), rows=[{"employee_id": "w-akord", "paid_now_amount": 700.0}])
        r = await c.post("/api/pay-runs", json=body, headers=_k("g3"))
        n1 = await op.payroll_corrections.count_documents({})
        row = r.json().get("employee_rows", [{}])[0] if r.status_code == 200 else {}
        r2 = await c.post("/api/pay-runs", json=_body(), headers=_k("g3b"))
        recs = [(x["source_pay_run_id"], x["amount"]) for x in await op.payroll_corrections.find({}).to_list(10)]
        print("G3 confirm:", r.status_code, r.text[:160] if r.status_code != 200 else
              ("paid_now %s remaining %s" % (row.get("paid_now_amount"), row.get("remaining_after_payment"))),
              "| records after it", n1, "| after a later run", recs)
    run(monkeypatch, scenario, "real")
