"""
LAB-R96 steps 3 + 4 — "едно четене, една формула" and "плащането заключва реда" (Р100, with
Р101, Р102, Р105).

* The reader (``app/services/labor_cost_reader.py``): approved lines of BOTH stored formats,
  per-line state (reported = forecast / approved_unpaid / batched / paid), the old clock
  sessions as a separate component "часовник (стар)", approval work_sessions never added.
* One formula: P&L, pay run, „Приходи/разходи", activity budgets (summary / burn / overview),
  financial results give the same number for a 9 h day of an hourly, a daily and a monthly
  worker (the pay run's calc_earned).
* Payment: two pay runs in one week (the second is offered only the new line, nothing
  "previously paid" subtracted from it), a paid / batched line is locked (reset, edit, void →
  409), the closed day sees the old format, tenant isolation of the read.

Same harness / fixture as ``test_lab_r96_rules.py`` (W0 hourly 12, W1 daily 110, W2 monthly
2200 / 22 d; project P, activity A; mongomock and, with ``W0_03_REAL_MONGO_URL``, a real
disposable MongoDB).

    PYTHONPATH=. pytest tests/test_lab_r96_step3_one_read.py -v --noconftest -p no:cacheprovider
"""
import asyncio
import importlib

import pytest

from tests import test_lab_r96_rules as base
from tests.test_lab_r96_money_rules import (
    approved_tech_report, generate, pay, pnl, project_profit, row_of, seed_old_format_approved,
)
from tests.test_lab_r96_rules import (
    A, ORG, P, TODAY, W0, W1, W2, WEEK, approve, backend, headers, tech_report,
)

__all__ = ["backend"]

EXTRA_ROUTERS = ("activity_budgets", "financial_results", "full_cost")
B = "Боя"                     # a second activity on P


def run(monkeypatch, backend, scenario):
    """``test_lab_r96_rules.run`` with the activity-budget and financial-result routers too."""
    import httpx
    monkeypatch.setattr(base, "ROUTERS", base.ROUTERS + EXTRA_ROUTERS)

    async def body():
        async with base._Db(backend) as op:
            await base.seed(op)
            await op.activity_budgets.insert_one({
                "id": "ab-a", "org_id": ORG, "project_id": P, "type": A, "subtype": "",
                "labor_budget": 1000, "materials_budget": 0})
            base._patch_db(monkeypatch, op)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=base._app()),
                                         base_url="http://labr96") as c:
                return await scenario(c, op)
    return asyncio.run(body())


def reader():
    return importlib.import_module("app.services.labor_cost_reader")


async def clock_session(op, wid=W0, hours=3, cost=36.0, sid="ws-clock-old"):
    """An OLD clock record (Р101) on P — not written by an approval."""
    await op.work_sessions.insert_one({
        "id": sid, "org_id": ORG, "worker_id": wid, "worker_name": wid, "site_id": P,
        "smr_type_id": A, "started_at": TODAY + "T08:00:00+00:00",
        "ended_at": TODAY + "T11:00:00+00:00", "source_method": "SELF_REPORT",
        "is_flagged": False, "duration_hours": hours, "is_overtime": False,
        "hourly_rate_at_date": 12, "labor_cost": cost, "created_at": TODAY})


async def submitted_flat(op, wid=W2, hours=8, lid="flat-submitted-w2"):
    await op.employee_daily_reports.insert_one({
        "id": lid, "org_id": ORG, "worker_id": wid, "worker_name": wid, "date": TODAY,
        "project_id": P, "smr_type": A, "hours": hours, "status": "Submitted",
        "created_by": "tech", "created_at": TODAY + "T16:00:00"})


async def summary_labor(c, activity=A):
    r = await c.get("/api/projects/%s/activity-budget-summary" % P, headers=headers("admin"))
    assert r.status_code == 200, r.text
    rows = [i for i in r.json()["items"] if i["type"] == activity]
    return rows[0]["labor_spent"] if rows else 0


async def burn(c):
    r = await c.get("/api/activity-budgets/ab-a/burn", headers=headers("admin"))
    assert r.status_code == 200, r.text
    return r.json()


async def overview_cost(c):
    r = await c.get("/api/projects/%s/activities-overview" % P, headers=headers("admin"))
    assert r.status_code == 200, r.text
    rows = [a for a in r.json()["activities"] if a["activity_name"] == A]
    return rows[0]["actual_cost"]


async def financial(c):
    r = await c.get("/api/projects/%s/financial-results" % P, headers=headers("admin"))
    assert r.status_code == 200, r.text
    return r.json()


# ═══════════════════════════════════════════════════════════════════ the reader
def test_reader_both_formats_states_and_separate_clock(monkeypatch, backend):
    """W0 flat approved 8 h (96), W1 old-format approved 8 h (110), W2 flat Submitted 8 h
    (forecast 100), one old clock session W0 3 h / 36. The reader returns 3 lines, both
    formats, with their states; the approval work_session of W0 is NOT a fourth line; the
    clock session is only in the separate component; the forecast is not in the totals."""
    async def scenario(c, op):
        await approved_tech_report(c, W0)
        await seed_old_format_approved(op, wid=W1, rid="old-w1")
        await submitted_flat(op)
        await clock_session(op)
        assert await op.work_sessions.count_documents({"source_method": "APPROVED_REPORT"}) == 1
        rd = reader()
        lab = await rd.project_labor(ORG, P)
        by = {ln["worker_id"]: ln for ln in lab["lines"]}
        assert sorted(by) == [W0, W1, W2]
        assert (by[W0]["format"], by[W0]["state"], by[W0]["cost"]) == ("flat", "approved_unpaid", 96)
        assert (by[W1]["format"], by[W1]["state"], by[W1]["cost"]) == ("old", "approved_unpaid", 110)
        assert by[W1]["line_id"] == "old-w1_e1"
        assert (by[W2]["state"], by[W2]["cost"], by[W2]["cost_basis"]) == ("reported", 100, "forecast")
        t = lab["totals"]
        assert (t["hours"], t["cost"], t["forecast_cost"], t["unpaid_cost"]) == (16, 206, 100, 206)
        assert t["clock"] == {"label": "часовник (стар)", "sessions": 1, "hours": 3, "cost": 36,
                              "overtime_cost": 0}
        assert [s["session_id"] for s in lab["clock"]] == ["ws-clock-old"]
        # per activity / per person / per period
        assert rd.group_by(lab["lines"], "activity_key")["шпакловка"]["cost"] == 206
        assert rd.group_by(lab["lines"], "worker_id")[W1]["hours"] == 8
        assert await rd.labor_lines(ORG, project_id=P, date_from="2000-01-01", date_to="2000-01-02") == []
    run(monkeypatch, backend, scenario)


def test_pnl_counts_clock_visibly_revenue_expense_does_not(monkeypatch, backend):
    """Same data: P&L labor = 206 approved + 36 clock (today's behaviour of the P&L, now a
    visible component); „Приходи/разходи" = 206 (it never counted clock sessions) with the
    clock shown, not counted. Neither adds the approval work_session (no 96 twice)."""
    async def scenario(c, op):
        await approved_tech_report(c, W0)
        await seed_old_format_approved(op, wid=W1, rid="old-w1")
        await submitted_flat(op)
        await clock_session(op)
        exp = await pnl(c)
        assert (exp["labor_hours"], exp["labor_cost"]) == (19, 242)
        comp = exp["labor_components"]
        assert (comp["approved_lines"]["cost"], comp["clock_legacy"]["cost"], comp["forecast_cost"]) == (206, 36, 100)
        pp = await project_profit(c)
        assert (pp["labor_hours"], pp["labor"]) == (16, 206)
        assert pp["labor_detail"]["clock_legacy"]["cost"] == 36
        assert pp["labor_detail"]["clock_legacy"]["counted"] is False
    run(monkeypatch, backend, scenario)


# ═══════════════════════════════════════════════════════════════════ one formula
@pytest.mark.parametrize("wid,cost", [(W0, 108.0), (W1, 110.0), (W2, 100.0)])
def test_nine_hour_day_one_number_everywhere(monkeypatch, backend, wid, cost):
    """One approved 9 h line: pay run earned == P&L == „Приходи/разходи" == activity budget
    summary == burn == activities overview == financial results (reported value)."""
    async def scenario(c, op):
        await approved_tech_report(c, wid, hours=9)
        w = row_of(await generate(c), wid)
        assert (w["approved_hours"], w["earned_amount"]) == (9, cost)
        exp = await pnl(c)
        pp = await project_profit(c)
        b = await burn(c)
        fin = await financial(c)
        got = {"pnl": exp["labor_cost"], "project_profit": pp["labor"],
               "budget_summary": await summary_labor(c), "burn": b["actual_cost"],
               "overview": await overview_cost(c),
               "financial_results": fin["labor"]["reported_labor_value"]}
        assert set(got.values()) == {cost}, got
        assert (exp["labor_hours"], pp["labor_hours"], b["actual_hours"]) == (9, 9, 9)
        assert exp["labor_components"]["approved_lines"]["overtime_hours"] == 1
    run(monkeypatch, backend, scenario)


# ═══════════════════════════════════════════════════════════════════ payment
def test_two_pay_runs_in_one_week_pay_each_line_once(monkeypatch, backend):
    """W0: line A 8 h approved → run 1 paid 96. Then line B 4 h approved the same week →
    generate offers ONLY line B: 4 h, earned 48, previously paid 0, remaining 48 (the former
    "latest run of the week" subtraction gave remaining −48 and refused the payment). Run 2
    pays 48; nothing unpaid is left; P&L labor 144 == what both runs paid."""
    async def scenario(c, op):
        rid_a = await approved_tech_report(c, W0)
        run1 = await pay(c, W0, 96)
        r = await c.post("/api/technician/daily-report", headers=headers("tech"), json={
            "project_id": P, "date": TODAY,
            "entries": [{"worker_id": W0, "worker_name": "W0", "smr_type": B, "hours": 4}]})
        assert r.status_code == 200, r.text
        rid_b = r.json()["draft_report_ids"][0]
        assert (await approve(c, rid_b, who="admin")).status_code == 200
        w = row_of(await generate(c), W0)
        ids = [x for d in w["day_cells"] for x in d["selectable_report_ids"]]
        assert (w["approved_hours"], w["earned_amount"], w["previously_paid"],
                w["remaining_after_payment"], ids) == (4, 48, 0, 48, [rid_b])
        run2 = await pay(c, W0, 48)
        assert row_of(await generate(c), W0) is None
        lines = {ln["line_id"]: ln for ln in await reader().labor_lines(ORG, project_id=P)}
        assert (lines[rid_a]["state"], lines[rid_a]["pay_run_id"]) == ("paid", run1)
        assert (lines[rid_b]["state"], lines[rid_b]["pay_run_id"]) == ("paid", run2)
        assert (await pnl(c))["labor_cost"] == 144
        review = await c.get("/api/pay-runs/generate", headers=headers("admin"), params={
            "period_start": WEEK[0], "period_end": WEEK[1], "review_mode": "true"})
        assert row_of(review.json(), W0)["previously_paid"] == 144
    run(monkeypatch, backend, scenario)


def test_paid_old_format_line_is_paid_per_entry_and_cost_frozen(monkeypatch, backend):
    """Old-format report with two entries (P 6 h, P2 2 h): one pay run pays both lines; each
    day entry carries payroll_status "paid" and the run; the report-level status follows.
    After the rate changes (12 → 20), the paid line still costs what was paid (Р105)."""
    async def scenario(c, op):
        await op.employee_daily_reports.insert_one({
            "id": "old2", "org_id": ORG, "employee_id": W0, "report_date": TODAY,
            "day_status": "WORKING", "day_entries": [
                {"id": "e1", "project_id": P, "work_description": A, "hours_worked": 6},
                {"id": "e2", "project_id": base.P2, "work_description": A, "hours_worked": 2}],
            "approval_status": "APPROVED", "status": "APPROVED", "created_by": "admin",
            "approved_by": "owner", "created_at": TODAY + "T17:00:00"})
        run_id = await pay(c, W0, 96)
        doc = await op.employee_daily_reports.find_one({"id": "old2"}, {"_id": 0})
        assert [(e["payroll_status"], e["payroll_source"]) for e in doc["day_entries"]] == [
            ("paid", "pay_run:" + run_id)] * 2
        assert doc["payroll_status"] == "paid"
        await op.employee_profiles.update_one({"user_id": W0}, {"$set": {"hourly_rate": 20}})
        exp = await pnl(c)
        assert (exp["labor_hours"], exp["labor_cost"]) == (6, 72)
        ln = (await reader().labor_lines(ORG, project_id=P))[0]
        assert (ln["state"], ln["cost_basis"], ln["cost"]) == ("paid", "pay_run_frozen", 72)
    run(monkeypatch, backend, scenario)


@pytest.mark.parametrize("fmt", ["flat", "old"])
@pytest.mark.parametrize("paid", [True, False], ids=["paid", "batched"])
def test_paid_or_batched_line_is_locked(monkeypatch, backend, fmt, paid):
    """A line in a pay run (batched) or paid cannot be reset to Submitted, edited or voided
    through the service (409 LABOR_LINE_PAID); the attendance day is closed for both formats."""
    async def scenario(c, op):
        if fmt == "flat":
            rid = await approved_tech_report(c, W0)
        else:
            rid = await seed_old_format_approved(op)
        svc = importlib.import_module("app.services.attendance_void")
        tenant = importlib.import_module("app.tenancy.data_access").TenantData.for_resolved_org(op, ORG)
        entry = {"org_id": ORG, "user_id": W0, "date": TODAY, "project_id": P}
        assert await svc.correction_locked(tenant, entry) == "report_approved"
        if paid:
            await pay(c, W0, 96)
        else:
            r = await c.post("/api/pay-runs", headers=headers("admin"), json={
                "run_type": "weekly", "period_start": WEEK[0], "period_end": WEEK[1],
                "rows": [{"employee_id": W0, "paid_now_amount": 96}], "status": "confirmed"})
            assert r.status_code == 200, r.text
        r = await c.post("/api/daily-reports/%s/reset" % rid, headers=headers("admin"))
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error_code"] == "LABOR_LINE_PAID"
        assert await svc.correction_locked(tenant, entry) in ("report_in_payroll", "pay_run_paid",
                                                              "pay_run_confirmed")
        labor = importlib.import_module("app.services.labor_report_service")
        doc = await op.employee_daily_reports.find_one({"id": rid}, {"_id": 0})
        actor = {"id": "owner", "org_id": ORG, "role": "Owner"}
        for call in (labor.update_line(actor, doc, {"hours": 1}),
                     labor.void_lines(actor, [doc], "x")):
            with pytest.raises(Exception) as exc:
                await call
            assert getattr(exc.value, "status_code", None) == 409
        doc2 = await op.employee_daily_reports.find_one({"id": rid}, {"_id": 0})
        assert (doc2.get("approval_status") or doc2.get("status")).upper() == "APPROVED"
    run(monkeypatch, backend, scenario)


def test_reopen_releases_both_formats(monkeypatch, backend):
    """A confirmed (not paid) pay run reopened → the flat and the old-format line are unpaid
    again and offered by generate."""
    async def scenario(c, op):
        rid = await approved_tech_report(c, W0)
        await seed_old_format_approved(op, wid=W1, rid="old-w1")
        r = await c.post("/api/pay-runs", headers=headers("admin"), json={
            "run_type": "weekly", "period_start": WEEK[0], "period_end": WEEK[1],
            "rows": [{"employee_id": W0, "paid_now_amount": 96},
                     {"employee_id": W1, "paid_now_amount": 110}], "status": "confirmed"})
        assert r.status_code == 200, r.text
        states = {ln["line_id"]: ln["state"] for ln in await reader().labor_lines(ORG, project_id=P)}
        assert states == {rid: "batched", "old-w1_e1": "batched"}
        assert (await generate(c))["rows"] == []
        rr = await c.post("/api/pay-runs/%s/reopen" % r.json()["id"], headers=headers("admin"),
                          json={"reason": "грешка"})
        assert rr.status_code == 200, rr.text
        states = {ln["line_id"]: ln["state"] for ln in await reader().labor_lines(ORG, project_id=P)}
        assert states == {rid: "approved_unpaid", "old-w1_e1": "approved_unpaid"}
        assert sorted(x["employee_id"] for x in (await generate(c))["rows"]) == [W0, W1]
    run(monkeypatch, backend, scenario)


# ═══════════════════════════════════════════════════════════════════ tenant isolation
def test_reader_and_marking_are_tenant_isolated(monkeypatch, backend):
    """A second tenant with the SAME project id, worker id and report shape: the reader of
    ORG never returns its lines, ORG's pay run never marks them, its P&L is not touched."""
    async def scenario(c, op):
        other = "ORG-OTHER"
        await op.employee_profiles.insert_one({"org_id": other, "user_id": W0, "pay_type": "Hourly",
                                               "hourly_rate": 50})
        await op.employee_daily_reports.insert_one({
            "id": "other-old", "org_id": other, "employee_id": W0, "report_date": TODAY,
            "day_entries": [{"id": "e1", "project_id": P, "work_description": A, "hours_worked": 8}],
            "approval_status": "APPROVED", "status": "APPROVED", "created_at": TODAY})
        await op.employee_daily_reports.insert_one({
            "id": "other-flat", "org_id": other, "worker_id": W0, "date": TODAY, "project_id": P,
            "smr_type": A, "hours": 5, "status": "APPROVED", "created_at": TODAY})
        await seed_old_format_approved(op)
        rd = reader()
        mine = await rd.labor_lines(ORG, project_id=P)
        assert [(ln["line_id"], ln["cost"]) for ln in mine] == [("old-fmt-w0_e1", 96)]
        theirs = await rd.labor_lines(other, project_id=P)
        assert sorted((ln["line_id"], ln["cost"]) for ln in theirs) == [("other-flat", 250), ("other-old_e1", 400)]
        await pay(c, W0, 96)
        for lid in ("other-old", "other-flat"):
            d = await op.employee_daily_reports.find_one({"id": lid}, {"_id": 0})
            assert d.get("payroll_status") in (None, "none")
            assert all("payroll_status" not in e for e in d.get("day_entries") or [])
        assert (await pnl(c))["labor_cost"] == 96
    run(monkeypatch, backend, scenario)
