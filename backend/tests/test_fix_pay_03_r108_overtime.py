"""
FIX-PAY-03 / Р108 (Krum 16.11.2026) — overtime is paid with the APPROVED coefficient.

A premium exists only when the approver put a coefficient on the line (the approval override:
regular / overtime split + ``overtime_coefficient`` + reason); without one there is no premium.
Hourly: hours over the norm × rate × coefficient. Daily / Monthly (and mixed): hours over 8 in
the day × (day rate ÷ 8) × coefficient, the base day paid once. The premium is rounded to the
cent half up (20.625 → 20.63). P&L / reader == pay run (Р100).

Same harness as ``test_lab_r96_rules.py`` (W0 hourly 12, W1 daily 110, W2 monthly 2200 / 22 d).

    PYTHONPATH=. pytest tests/test_fix_pay_03_r108_overtime.py -v --noconftest -p no:cacheprovider
"""
import importlib

import pytest

from tests.test_lab_r96_money_rules import generate, pay, pnl, row_of
from tests.test_lab_r96_rules import ORG, P, W0, W1, W2, backend, headers, run, tech_report

__all__ = ["backend"]

OVERRIDE = {"regular_hours": 8, "overtime_hours": 1, "overtime_coefficient": 1.5,
            "reason": "извънреден труд, одобрен"}


async def approved_9h(c, wid, override):
    r = await tech_report(c, wid=wid, hours=9)
    assert r.status_code == 200, r.text
    rid = r.json()["draft_report_ids"][0]
    body = {"override": override} if override else {}
    ra = await c.post("/api/daily-reports/%s/approve" % rid, headers=headers("admin"), json=body)
    assert ra.status_code == 200, ra.text
    return rid


async def reader_cost(rid):
    rd = importlib.import_module("app.services.labor_cost_reader")
    return {ln["line_id"]: ln["cost"] for ln in await rd.labor_lines(ORG, project_id=P)}[rid]


CASES = {
    # case: (worker, override, expected)
    "hourly_1.5": (W0, OVERRIDE, 114.0),          # 8 × 12 + 1 × 12 × 1.5
    "hourly_none": (W0, None, 108.0),             # 9 × 12, no premium
    "daily_1.5": (W1, OVERRIDE, 130.63),          # 110 + 1 × (110 / 8) × 1.5 = 130.625 → 130.63
    "daily_none": (W1, None, 110.0),
    "monthly_1.5": (W2, OVERRIDE, 118.75),        # 100 + 1 × (100 / 8) × 1.5
    "monthly_none": (W2, None, 100.0),
}


@pytest.mark.parametrize("case", list(CASES))
def test_overtime_with_approved_coefficient_same_in_pay_run_and_pnl(monkeypatch, backend, case):
    wid, override, expected = CASES[case]

    async def scenario(c, op):
        rid = await approved_9h(c, wid, override)
        w = row_of(await generate(c), wid)
        assert w["earned_amount"] == expected, w["earned_formula"]
        assert await reader_cost(rid) == expected
        assert (await pnl(c))["labor_cost"] == expected
        await pay(c, wid, expected)
        assert await reader_cost(rid) == expected        # paid: what was paid
        assert (await pnl(c))["labor_cost"] == expected
        assert row_of(await generate(c), wid) is None
    run(monkeypatch, backend, scenario)


def test_mixed_pay_type_uses_the_approved_coefficient_not_an_automatic_1_5(monkeypatch, backend):
    """mixed (pay_type not Hourly/Daily/Monthly/Akord, salary 2200 / 22 d): 9 h without an
    approved coefficient → 100 (the former rule paid 100 + 1 × 12.5 × 1.5 = 118.75 by itself);
    with coefficient 1.5 → 118.75."""
    async def scenario(c, op):
        await op.employee_profiles.update_one({"user_id": W2}, {"$set": {"pay_type": "Mixed"}})
        rid = await approved_9h(c, W2, None)
        assert row_of(await generate(c), W2)["earned_amount"] == 100
        assert await reader_cost(rid) == 100
        await op.employee_daily_reports.update_one({"id": rid}, {"$set": {
            "overtime_coefficient": 1.5, "overtime_reason": "одобрено", "regular_hours": 8,
            "overtime_hours": 1}})
        assert row_of(await generate(c), W2)["earned_amount"] == 118.75
        assert await reader_cost(rid) == 118.75
    run(monkeypatch, backend, scenario)
