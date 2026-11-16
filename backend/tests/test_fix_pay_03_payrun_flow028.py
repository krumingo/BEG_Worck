"""
FIX-PAY-03 — two pay-run defects against FLOW-028.

A. "един отчетен ред не може да бъде платен два пъти" / "Pay Run използва само одобрени и
   неплатени source records": a Daily / Monthly worker's day rate is earned ONCE per worker ×
   calendar day across all pay runs. Lines of one day on two projects, the second approved
   after pay run 1 paid the first → pay run 2 offers nothing more for that day (paying it again
   is refused as overpayment); the day amount is split over the projects by hours in the
   reader / P&L. Hourly is unchanged.
B. "заработка = одобрено измерено количество × договорена единична цена труд"; "Без одобрено
   количество или цена не възниква окончателно задължение и не може да има плащане": an akord
   line earns approved quantity × unit labor price (``labor_quantity_approvals``, the LAB-02
   data model), regardless of hours; without one it is blocked with a reason — 0 payable,
   never hours × rate. Self-approval and another tenant's record do not count. The reader /
   P&L equals the pay run.

Same harness as ``test_lab_r96_rules.py`` (mongomock and, with ``W0_03_REAL_MONGO_URL``, a real
disposable MongoDB).

    PYTHONPATH=. pytest tests/test_fix_pay_03_payrun_flow028.py -v --noconftest -p no:cacheprovider
"""
import importlib

import pytest

from tests.test_lab_r96_money_rules import generate, pay, pnl, row_of
from tests.test_lab_r96_rules import (
    A, ORG, P, P2, TODAY, W0, W1, W2, WEEK, backend, headers, run,
)

__all__ = ["backend"]

W3 = "w3-akord"


def reader():
    return importlib.import_module("app.services.labor_cost_reader")


async def flat_line(op, lid, wid, project, hours, created="T10:00:00", org=ORG, status="APPROVED"):
    """An approved flat labor line (the shape the labor service writes)."""
    await op.employee_daily_reports.insert_one({
        "id": lid, "org_id": org, "worker_id": wid, "worker_name": wid, "date": TODAY,
        "project_id": project, "smr_type": A, "hours": hours, "status": status,
        "created_by": "tech", "approved_by": "admin", "created_at": TODAY + created})
    return lid


async def create_run(c, wid, amount, report_ids=None, status="confirmed"):
    row = {"employee_id": wid, "paid_now_amount": amount}
    if report_ids:
        row["selected_report_ids"] = report_ids
    return await c.post("/api/pay-runs", headers=headers("admin"), json={
        "run_type": "weekly", "period_start": WEEK[0], "period_end": WEEK[1],
        "rows": [row], "status": status})


async def by_project(wid):
    lines = await reader().labor_lines(ORG, worker_id=wid, date_from=TODAY, date_to=TODAY)
    out = {}
    for ln in lines:
        out[ln["project_id"]] = round(out.get(ln["project_id"], 0) + ln["cost"], 2)
    return out


# ═══════════════════════════════════════════════════════════════════ A — day rate once
@pytest.mark.parametrize("wid,day", [(W1, 110.0), (W2, 100.0)], ids=["daily", "monthly"])
def test_day_rate_is_paid_once_across_two_pay_runs(monkeypatch, backend, wid, day):
    """Line P 6 h approved → pay run 1 pays the day. Line P2 2 h of the SAME day approved later
    → generate: earned 0, the day marked already paid; paying the day again → refused; a
    confirmed pay run 2 holds the line at 0. Reader / P&L: the day amount ONCE in total,
    split by hours P 6/8, P2 2/8."""
    async def scenario(c, op):
        await flat_line(op, "ln-p", wid, P, 6)
        w = row_of(await generate(c), wid)
        assert (w["approved_days"], w["earned_amount"]) == (1, day)
        await pay(c, wid, day)
        await flat_line(op, "ln-p2", wid, P2, 2, created="T15:00:00")
        w = row_of(await generate(c), wid)
        ids = [x for d in w["day_cells"] for x in d["selectable_report_ids"]]
        assert (ids, w["approved_hours"], w["approved_days"], w["earned_amount"],
                w["previously_paid"], w["remaining_after_payment"]) == (["ln-p2"], 2, 0, 0, 0, 0)
        assert w["already_paid_dates"] == [TODAY]
        again = await create_run(c, wid, day)
        assert again.status_code == 400, again.text          # the day rate a second time
        r2 = await create_run(c, wid, 0, ["ln-p2"])
        assert r2.status_code == 200, r2.text
        er = r2.json()["employee_rows"][0]
        assert (er["earned_amount"], er["day_rate_dates"], er["already_paid_dates"]) == (0, [], [TODAY])
        cost = await by_project(wid)
        assert cost == {P: round(day * 6 / 8, 2), P2: round(day - round(day * 6 / 8, 2), 2)}
        assert round(sum(cost.values()), 2) == day           # the day once
        assert (await pnl(c))["labor_cost"] == cost[P]       # P&L == reader
        w = row_of(await generate(c), wid)
        assert w["earned_amount"] == 0                       # nothing more for that day
    run(monkeypatch, backend, scenario)


def test_hourly_unchanged_across_two_pay_runs(monkeypatch, backend):
    """Hourly 12 €/h: P 6 h paid 72 in run 1, P2 2 h the same day → run 2 earns 24 (as before)."""
    async def scenario(c, op):
        await flat_line(op, "ln-p", W0, P, 6)
        await pay(c, W0, 72)
        await flat_line(op, "ln-p2", W0, P2, 2, created="T15:00:00")
        w = row_of(await generate(c), W0)
        assert (w["approved_days"], w["earned_amount"]) == (1, 24)
        await pay(c, W0, 24)
        assert await by_project(W0) == {P: 72, P2: 24}
        assert (await pnl(c))["labor_cost"] == 72
    run(monkeypatch, backend, scenario)


def test_legacy_double_paid_day_keeps_what_was_paid(monkeypatch, backend):
    """A pay run row written BEFORE the fix (no ``day_rate_dates``) that paid the day a second
    time is not changed: the reader still costs what each run paid (2 × 110 over the day)."""
    async def scenario(c, op):
        await flat_line(op, "ln-p", W1, P, 6)
        await pay(c, W1, 110)
        await flat_line(op, "ln-p2", W1, P2, 2, created="T15:00:00")
        run2 = await create_run(c, W1, 0, ["ln-p2"])
        assert run2.status_code == 200, run2.text
        rid = run2.json()["id"]
        # simulate the pre-fix row: it paid a full day for ln-p2 and has no FIX-PAY-03 fields
        await op.pay_runs.update_one({"id": rid}, {"$set": {
            "employee_rows.0.earned_amount": 110, "employee_rows.0.paid_now_amount": 110},
            "$unset": {"employee_rows.0.day_rate_dates": "", "employee_rows.0.already_paid_dates": ""}})
        await op.employee_daily_reports.update_one({"id": "ln-p2"}, {"$set": {
            "payroll_status": "paid", "payroll_source": "pay_run:" + rid}})
        assert round(sum((await by_project(W1)).values()), 2) == 220
    run(monkeypatch, backend, scenario)


# ═══════════════════════════════════════════════════════════════════ B — akord
async def akord_worker(op, org=ORG):
    await op.users.insert_one({"id": W3, "org_id": org, "role": "Worker", "is_active": True,
                               "email": W3 + "@labr96.example", "first_name": "W3",
                               "last_name": "Akord"})
    await op.employee_profiles.insert_one({"org_id": org, "user_id": W3, "pay_type": "Akord",
                                           "hourly_rate": 15})


async def approval(op, lid, qty=20, rate=12, by="sm", org=ORG, rec_id="lqa-1"):
    await op.labor_quantity_approvals.insert_one({
        "id": rec_id, "org_id": org, "report_id": lid, "entry_id": None, "report_version": 0,
        "worker_id": W3, "project_id": P, "date": TODAY, "approved_quantity": qty, "unit": "m2",
        "execution_package_id": None, "labor_pay_type": "Akord", "piece_rate": rate,
        "status": "approved", "approved_by": by, "approved_at": TODAY + "T18:00:00"})


@pytest.mark.parametrize("hours", [8, 3])
def test_akord_is_approved_quantity_times_unit_price(monkeypatch, backend, hours):
    """20 m² × 12 €/m² = 240, whatever the hours (8 h × 15 or 3 h × 15 is never paid).
    Reader == pay run == P&L, before and after payment."""
    async def scenario(c, op):
        await akord_worker(op)
        await flat_line(op, "ln-ak", W3, P, hours)
        await approval(op, "ln-ak")
        w = row_of(await generate(c), W3)
        assert (w["earned_amount"], w["blocked_lines"]) == (240, [])
        rep = w["day_cells"][0]["reports"][0]
        assert (rep["akord_amount"], rep["approved_quantity"], rep["piece_rate"]) == (240, 20, 12)
        ln = (await reader().labor_lines(ORG, project_id=P))[0]
        assert (ln["cost"], ln["state"]) == (240, "approved_unpaid")
        assert (await pnl(c))["labor_cost"] == 240
        await pay(c, W3, 240)
        ln = (await reader().labor_lines(ORG, project_id=P))[0]
        assert (ln["cost"], ln["state"]) == (240, "paid")
        assert (await pnl(c))["labor_cost"] == 240
        assert row_of(await generate(c), W3) is None
    run(monkeypatch, backend, scenario)


@pytest.mark.parametrize("case", ["no_record", "self_approved", "no_price", "other_tenant"])
def test_akord_without_approved_quantity_or_price_is_blocked(monkeypatch, backend, case):
    """No (valid) approved quantity or no unit price → 0 payable, the line blocked with its
    reason, not selectable, not payable, 0 in the reader / P&L — never 8 h × 15 = 120."""
    async def scenario(c, op):
        await akord_worker(op)
        await flat_line(op, "ln-ak", W3, P, 8)
        if case == "self_approved":
            await approval(op, "ln-ak", by=W3)
        elif case == "no_price":
            await approval(op, "ln-ak", rate=None)
        elif case == "other_tenant":
            await approval(op, "ln-ak", org="ORG-OTHER")
        reason = ("Акорд: няма договорена единична цена труд" if case == "no_price"
                  else "Акорд: няма одобрено количество")
        w = row_of(await generate(c), W3)
        assert (w["earned_amount"], w["day_cells"]) == (0, [])
        assert [(b["report_id"], b["reason"]) for b in w["blocked_lines"]] == [("ln-ak", reason)]
        r = await create_run(c, W3, 0, ["ln-ak"])
        assert r.status_code == 400 and reason in r.text, r.text
        r = await create_run(c, W3, 120)
        assert r.status_code == 400, r.text                  # nothing to pay
        ln = (await reader().labor_lines(ORG, project_id=P))[0]
        assert (ln["cost"], ln["akord_blocked"]) == (0, reason)
        assert (await pnl(c))["labor_cost"] == 0
        doc = await op.employee_daily_reports.find_one({"id": "ln-ak"}, {"_id": 0})
        assert doc.get("payroll_status") in (None, "none")
    run(monkeypatch, backend, scenario)


def test_akord_terms_are_tenant_isolated(monkeypatch, backend):
    """Another tenant with the same line id and its own approval: each tenant reads only its
    own record (ORG 20 × 12 = 240, ORG-OTHER 5 × 10 = 50)."""
    async def scenario(c, op):
        other = "ORG-OTHER"
        await akord_worker(op)
        await akord_worker(op, org=other)
        await flat_line(op, "ln-ak", W3, P, 8)
        await approval(op, "ln-ak")
        await op.employee_daily_reports.insert_one({
            "id": "ln-ak-o", "org_id": other, "worker_id": W3, "date": TODAY, "project_id": P,
            "smr_type": A, "hours": 8, "status": "APPROVED", "created_at": TODAY})
        await approval(op, "ln-ak-o", qty=5, rate=10, org=other, rec_id="lqa-o")
        await approval(op, "ln-ak", qty=99, rate=99, org=other, rec_id="lqa-o2")
        mine = await reader().labor_lines(ORG, project_id=P)
        theirs = await reader().labor_lines(other, project_id=P)
        assert [(ln["line_id"], ln["cost"]) for ln in mine] == [("ln-ak", 240)]
        assert [(ln["line_id"], ln["cost"]) for ln in theirs] == [("ln-ak-o", 50)]
        assert row_of(await generate(c), W3)["earned_amount"] == 240
    run(monkeypatch, backend, scenario)
