"""R0-06-C02 probe (Codex F-02a) — the payment breaks AFTER the slips were written "paid".
Prints what each payment_slips reader reports. No assertions.

    cd backend
    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27018/?directConnection=true' \
        PYTHONPATH=. python ../docs/evidence/R0-06/slip_readers_probe.py
"""
import json

import pytest

from tests import test_r0_06_paid_pay_run as t


def scenario_for(mp):
    async def scenario(c, op):
        run_id = await t._create(c)
        t._fail_after_slips(mp)
        try:
            await t._mark_paid(c, run_id)
        except RuntimeError:
            pass
        pr = await op.pay_runs.find_one({"id": run_id}, {"_id": 0})
        raw = await op.payment_slips.find({"pay_run_id": run_id}, {"_id": 0}).to_list(10)
        v = await t._slip_views(c, op, run_id)
        return {
            "run_status": pr["status"],
            "raw_slip_statuses": sorted(s["status"] for s in raw),
            "hr_legacy_payslips": [p["status"] for p in v["legacy"]],
            "hr_legacy_payslip_one": [p["status"] for p in v["legacy_one"]],
            "api_payment_slips": [s["status"] for s in v["api_list"]["items"]],
            "api_payment_slips_status_paid_total": v["api_paid"]["total"],
            "api_payment_slip_one": [s["status"] for s in v["api_one"]],
            "payroll_weeks_slip_status": v["week_slip_statuses"],
            "my_pay_summary_owed": v["my_pay"]["owed"],
            "cashflow_payroll_estimate": [i["amount"] for i in v["payroll_items"]],
            "paid_labor_v3_rows": len(v["paid_labor_v3"]),
            "paid_alloc_rows": len(v["paid_alloc_rows"]),
        }
    return scenario


out = {}
for backend in ("real", "mongomock"):
    mp = pytest.MonkeyPatch()
    try:
        out[backend] = t.run_c02(mp, scenario_for(mp), backend)
    finally:
        mp.undo()
print(json.dumps(out))
