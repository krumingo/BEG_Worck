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
        print("F1", backend, [(x["amount"], x["status"], x["source_pay_run_ids"], len(x["pay_run_ids"])) for x in recs])
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
        print("F2 month draft: earned", row.get("earned_amount"), "remaining", row.get("remaining_after_payment"),
              "item", bool(row.get("correction_item")), "-> correction status", rec["status"])
        w2 = await c.post("/api/pay-runs", json=_body(), headers=_k("f2-w2"))
        rec2 = await op.payroll_corrections.find_one({}, {"_id": 0})
        n = await op.payroll_corrections.count_documents({})
        print("F2 new weekly run:", w2.status_code, "-> status", rec2["status"], "version", rec2["version"], "records", n)
    run(monkeypatch, scenario, "real")
