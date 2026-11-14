"""AUDIT-2 probe R91-M1: an approved manual row of a DAY-paid worker (profile Monthly / Daily)
is not an "hourly row" — does R91 put it into the Pay Run at hours × hourly_rate on top of the
day the approved report already pays (another project, the same day)?"""
import pytest

from app.routes import pay_runs  # noqa: F401
from tests.test_lab_01_s_r62_one_labor_cost import ORG, P, DAY, PKG, _decision, _key, backend, run  # noqa: F401
from tests.test_lab_02_r85_akord_in_payroll import _w1, _manual_reports

P2 = P + "-two"


@pytest.mark.parametrize("pay", ["Monthly", "Daily"])
def test_probe_r91_day_paid_worker_manual_row(monkeypatch, backend, pay):
    async def scenario(c, op):
        await op.employee_profiles.update_one({"user_id": "w1"}, {"$set": {
            "pay_type": pay, "monthly_salary": 2200, "working_days_per_month": 22, "daily_rate": 100,
            "hourly_rate": 12.5, "standard_hours_per_day": 8}})
        await op.projects.insert_one({"id": P2, "org_id": ORG, "name": "втори обект", "status": "Active"})
        before = await _w1()
        print("BEFORE", before["earned_amount"], before["earned_formula"])
        # the manual row: the same day as the approved report R-OK, another object, 4 h
        await op.labor_entries.update_one({"id": "le-man"}, {"$set": {
            "project_id": P2, "date": DAY, "hours": 4, "hourly_rate": 12.5, "labor_cost": 50.0,
            "pay_type": pay, "execution_package_id": None}})
        r = await c.post("/api/labor-entries/le-man/approve", json=_decision(), headers=_key("owner"))
        assert r.status_code == 200, r.text
        after = await _w1()
        man = _manual_reports(after)
        print("AFTER", after["earned_amount"], after["earned_formula"], [(m["kind"], m["value"]) for m in man])
        # a day-paid worker's day is paid once (by its day rate); the manual row must not add 50
        assert after["earned_amount"] == before["earned_amount"], (before["earned_amount"], after["earned_amount"], man)
    run(monkeypatch, scenario, backend)
