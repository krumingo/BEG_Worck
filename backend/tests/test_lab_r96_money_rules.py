"""
LAB-R96-T — the money side of Р100 "Един вход за труда": rules 2, 3, 4, 7, 10.

Same fixture, harness and marker convention as ``test_lab_r96_rules.py`` (read its docstring):
W0 hourly 12 €/h, W1 daily 110 €/day, W2 monthly 2200 €/month (22 d × 8 h), one project P,
activity A, attendance Present today. An xfail(strict) test encodes a target rule that does
not hold on de720f94; a plain test protects a rule that already holds.

    PYTHONPATH=. pytest tests/test_lab_r96_rules.py tests/test_lab_r96_money_rules.py -v --noconftest -p no:cacheprovider
"""
import pytest

from tests.test_lab_r96_rules import (
    A, ORG, P, TODAY, W0, W1, W2, WEEK, approve, backend, daily_report, headers, r100, run,
    tech_report, work_report_draft,
)

__all__ = ["backend"]   # the fixture is imported for pytest


# ═══════════════════════════════════════════════════════════════════ helpers
async def approved_tech_report(c, wid, hours=8):
    r = await tech_report(c, wid=wid, hours=hours)
    assert r.status_code == 200, r.text
    rid = r.json()["draft_report_ids"][0]
    ra = await approve(c, rid, who="admin")
    assert ra.status_code == 200, ra.text
    return rid


async def generate(c):
    r = await c.get("/api/pay-runs/generate", headers=headers("admin"),
                    params={"period_start": WEEK[0], "period_end": WEEK[1]})
    assert r.status_code == 200, r.text
    return r.json()


def row_of(gen, wid):
    rows = [r for r in gen["rows"] if r["employee_id"] == wid]
    return rows[0] if rows else None


async def pnl(c):
    r = await c.get("/api/projects/%s/pnl" % P, headers=headers("admin"))
    assert r.status_code == 200, r.text
    return r.json()["expense"]


async def project_profit(c):
    """„Приходи/разходи“ — ``GET /project-profit/{project_id}``."""
    r = await c.get("/api/project-profit/%s" % P, headers=headers("admin"))
    assert r.status_code == 200, r.text
    return r.json()["expenses"]


async def pay(c, wid, amount):
    r = await c.post("/api/pay-runs", headers=headers("admin"), json={
        "run_type": "weekly", "period_start": WEEK[0], "period_end": WEEK[1],
        "rows": [{"employee_id": wid, "paid_now_amount": amount}], "status": "confirmed"})
    assert r.status_code == 200, r.text
    run_id = r.json()["id"]
    rp = await c.post("/api/pay-runs/%s/mark-paid" % run_id, headers=headers("admin"),
                      json={"payment_method": "cash", "payment_reference": "", "payment_note": ""})
    assert rp.status_code == 200, rp.text
    return run_id


async def seed_old_format_approved(op, wid=W0, hours=8, rid="old-fmt-w0"):
    """A stored report in the OLD format (employee_id / report_date / day_entries), approved —
    the shape ``/daily-reports`` and ``batch-save`` write and real data still holds."""
    await op.employee_daily_reports.insert_one({
        "id": rid, "org_id": ORG, "employee_id": wid, "report_date": TODAY,
        "day_status": "WORKING", "day_entries": [{"id": "e1", "project_id": P,
                                                  "work_description": A, "hours_worked": hours}],
        "total_hours": hours, "approval_status": "APPROVED", "status": "APPROVED",
        "created_by": "admin", "approved_by": "owner", "created_at": TODAY + "T17:00:00"})
    return rid


# ═══════════════════════════════════════════════════════════════════ rule 2
async def _second_daily_report(c, op):
    r = await daily_report(c)
    return [r.json()["id"]] if r.status_code < 300 else []


async def _second_tech_report(c, op):
    r = await tech_report(c)
    return r.json()["draft_report_ids"] if r.status_code < 300 else []


SECOND = {"daily_reports": _second_daily_report, "technician_again": _second_tech_report}


@pytest.mark.parametrize("second", list(SECOND))   # xfail removed: fixed by LAB-R96 step 2
def test_r2_pay_run_pays_the_day_once_even_through_a_second_path(monkeypatch, backend, second):
    """Rule 2 (Р100 "ведомост не се плаща два пъти" — taken from #73/#75; FLOW-028: the pay
    run pays approved daily reports once).

    Technician report W0 8 h on P / A today, approved by Admin; then the same day entered
    again through ``second`` and (if accepted) approved too. ``GET /pay-runs/generate`` for the
    week must show W0 with 8 h and 96 €.

    Today on de720f94 both entries are accepted and approved: daily_reports → W0 16 h,
    earned 192 (8 h flat + 8 h old-format line); technician_again → W0 16 h, earned 192.
    """
    async def scenario(c, op):
        await approved_tech_report(c, W0)
        for rid in await SECOND[second](c, op):
            await approve(c, rid, who="owner")
        w = row_of(await generate(c), W0)
        assert (w["approved_hours"], w["earned_amount"]) == (8, 96), (
            w["approved_hours"], w["earned_amount"])
    run(monkeypatch, backend, scenario)


def test_r2_holds_today_single_approved_report_pays_96(monkeypatch, backend):
    """Rule 2, single path: one approved technician report W0 8 h → generate W0 8 h, 96 €,
    one day, one selectable report."""
    async def scenario(c, op):
        rid = await approved_tech_report(c, W0)
        w = row_of(await generate(c), W0)
        assert (w["approved_hours"], w["approved_days"], w["earned_amount"]) == (8, 1, 96)
        assert [x for d in w["day_cells"] for x in d["selectable_report_ids"]] == [rid]
    run(monkeypatch, backend, scenario)


# ═══════════════════════════════════════════════════════════════════ rule 3
def test_r3_holds_today_pnl_labor_equals_pay_run_for_approved_8h_days(monkeypatch, backend):
    """Rule 3 (Р100 "P&L, ведомост … четат едните одобрени редове"; "P&L = ведомост" from
    #73/#75; FLOW-008).

    W0, W1, W2 each 8 h on P, technician path, approved by Admin. ``/projects/P/pnl`` labor
    equals the pay-run preview: 24 h and 306 € (96 + 110 + 100). Holds today for 8 h days.
    """
    async def scenario(c, op):
        for wid in (W0, W1, W2):
            await approved_tech_report(c, wid)
        gen, exp = await generate(c), await pnl(c)
        assert (gen["totals"]["hours"], gen["totals"]["earned"]) == (24, 306)
        assert (exp["labor_hours"], exp["labor_cost"]) == (24, 306), exp
    run(monkeypatch, backend, scenario)


# xfail removed: fixed by LAB-R96 step 3 (P&L reads labor_cost_reader)
def test_r3_pnl_counts_an_approved_old_format_report_like_the_pay_run(monkeypatch, backend):
    """Rule 3 with an approved report in the OLD stored format (employee_id/day_entries, W0
    8 h on P): the pay run and the P&L must show the same hours and cost.

    Today on de720f94: pay run W0 8 h / 96 €; P&L labor 0 h / 0 € (P&L reads work_sessions,
    which approval never writes for an old-format report — it has no worker_id).
    """
    async def scenario(c, op):
        await seed_old_format_approved(op)
        w, exp = row_of(await generate(c), W0), await pnl(c)
        assert (exp["labor_hours"], exp["labor_cost"]) == (w["approved_hours"], w["earned_amount"]), (
            "pnl", exp["labor_hours"], exp["labor_cost"], "pay run", w["approved_hours"],
            w["earned_amount"])
    run(monkeypatch, backend, scenario)


# xfail removed: fixed by LAB-R96 step 3 (project-profit reads labor_cost_reader)
def test_r3_revenue_expense_labor_equals_pay_run(monkeypatch, backend):
    """Rule 3 on „Приходи/разходи“ (``/project-profit/P``, Р100 names it explicitly): W0, W1,
    W2 each 8 h, technician path, approved. Labor must equal the pay run (24 h, 306 €).

    Today on de720f94: 0 h / 0 € — it reads labor_entries, else work_reports lines; the
    technician path writes a work_reports summary without lines.
    """
    async def scenario(c, op):
        for wid in (W0, W1, W2):
            await approved_tech_report(c, wid)
        gen, exp = await generate(c), await project_profit(c)
        assert (exp["labor_hours"], exp["labor"]) == (gen["totals"]["hours"], gen["totals"]["earned"]), (
            "project-profit", exp["labor_hours"], exp["labor"], "pay run", gen["totals"])
    run(monkeypatch, backend, scenario)


# ═══════════════════════════════════════════════════════════════════ rule 4
def test_r4_holds_today_paid_flat_report_is_not_shown_unpaid(monkeypatch, backend):
    """Rule 4 (Р100 "Плащането заключва реда"; FLOW-028 / FLOW-006), flat format
    (worker_id/date/hours): W0 8 h approved → pay run confirmed and marked paid (96 €) →
    the report is ``payroll_status`` "paid" and generate shows no W0 row. Holds today."""
    async def scenario(c, op):
        rid = await approved_tech_report(c, W0)
        await pay(c, W0, 96)
        doc = await op.employee_daily_reports.find_one({"id": rid}, {"_id": 0})
        assert doc["payroll_status"] == "paid"
        assert row_of(await generate(c), W0) is None
    run(monkeypatch, backend, scenario)


# xfail removed: fixed by LAB-R96 step 4 (payroll_sync marks old-format lines per entry)
def test_r4_paid_old_format_report_is_not_shown_unpaid(monkeypatch, backend):
    """Rule 4 for the OLD stored format (employee_id/report_date/day_entries): W0 8 h approved
    → pay run confirmed and marked paid (96 €) → generate must show nothing unpaid for W0.

    Today on de720f94: the report keeps payroll_status "none" (payroll_sync marks reports by
    ``worker_id`` only) and generate still offers W0: 8 h, earned 96, previously_paid 96,
    with the report selectable for another pay run.
    """
    async def scenario(c, op):
        rid = await seed_old_format_approved(op)
        await pay(c, W0, 96)
        doc = await op.employee_daily_reports.find_one({"id": rid}, {"_id": 0})
        w = row_of(await generate(c), W0)
        assert w is None, (doc.get("payroll_status"), w and (w["approved_hours"], w["earned_amount"],
                                                             w["previously_paid"]))
        assert doc.get("payroll_status") == "paid"
    run(monkeypatch, backend, scenario)


# ═══════════════════════════════════════════════════════════════════ rule 7
def test_r7_holds_today_unapproved_report_is_not_in_pay_run_nor_pnl(monkeypatch, backend):
    """Rule 7 (Р102 "не влизат в разход, без да са одобрени"; FLOW-028:20): W0 8 h technician
    report left as Draft → no pay-run row, P&L labor 0 h / 0 €. Holds today."""
    async def scenario(c, op):
        assert (await tech_report(c)).status_code == 200
        assert row_of(await generate(c), W0) is None
        exp = await pnl(c)
        assert (exp["labor_hours"], exp["labor_cost"]) == (0, 0), exp
    run(monkeypatch, backend, scenario)


# xfail (step 3) removed by LAB-R96 step 2 as a side effect: "Моят ден" lines are labor lines
# now, the work_reports header stores none, so the fallback has nothing unapproved to sum.
def test_r7_unapproved_worker_report_creates_no_revenue_expense_labor(monkeypatch, backend):
    """Rule 7 on „Приходи/разходи“: the worker's own report (``/work-reports/draft`` + line
    A 8 h), never submitted or approved → ``/project-profit/P`` labor must be 0.

    Today on de720f94: 8 h / 96 € — its fallback sums every work_reports line × hourly_rate,
    whatever the status.
    """
    async def scenario(c, op):
        assert (await work_report_draft(c)).status_code == 201
        exp = await project_profit(c)
        assert (exp["labor_hours"], exp["labor"]) == (0, 0), (exp["labor_hours"], exp["labor"])
    run(monkeypatch, backend, scenario)


# ═══════════════════════════════════════════════════════════════════ rule 10
NINE_HOURS = {   # worker → (approved-report labor_cost, pay-run earned) on de720f94
    W0: (108.0, 108.0),     # 8×12 + 1×12×1.0 | 9 h × 12
    W1: (123.75, 110.0),    # 8×13.75 + 1×13.75×1.0 | 1 day × 110
    W2: (112.5, 100.0),     # 8×12.5 + 1×12.5×1.0 | 2200/22 × 1 day
}


def _nine(wid):
    # xfail markers (W1, W2) removed: fixed by LAB-R96 step 3 (P&L costs through calc_earned)
    return pytest.param(wid, id=wid)


@pytest.mark.parametrize("wid", [_nine(w) for w in NINE_HOURS])
def test_r10_nine_hour_day_costs_the_same_in_pnl_and_pay_run(monkeypatch, backend, wid):
    """Rule 10 (Р100 "Една формула за ставка и извънреден труд"; FLOW-028).

    One approved technician report of 9 h on P. The approval writes the work_session that
    P&L reads (daily_reports.py approve_report_one: 8 h × rate + 1 h × rate × 1.0, rate from
    resolve_worker_hourly_rate); the pay-run preview uses calc_earned (pay_runs.py: hourly →
    h × rate, daily → days × daily_rate, monthly → days × salary/22). Both must give one number.

    Today on de720f94 (P&L | pay run): W0 hourly 108 | 108 (holds); W1 daily 123.75 | 110;
    W2 monthly 112.5 | 100.
    """
    async def scenario(c, op):
        await approved_tech_report(c, wid, hours=9)
        exp, w = await pnl(c), row_of(await generate(c), wid)
        observed = (exp["labor_cost"], w["earned_amount"])     # today: NINE_HOURS[wid]
        assert exp["labor_cost"] == w["earned_amount"], observed
    run(monkeypatch, backend, scenario)


CLOCK_DAY = "2026-11-11"    # a Wednesday: no weekend / after-20:00 coefficient


async def _clock_session_9h(c, op):
    """An old clock record of W1 (rate snapshot 110/8 = 13.75), saved by the SiteManager on
    the work-sessions edit screen as 08:00–17:00 (9 h) — first save and an unchanged re-save."""
    await op.work_sessions.insert_one({
        "id": "ws-w1", "org_id": ORG, "worker_id": W1, "worker_name": "W1", "site_id": P,
        "site_name": "Обект P", "smr_type_id": A, "started_at": CLOCK_DAY + "T08:00:00+00:00",
        "ended_at": None, "source_method": "SELF_REPORT", "is_flagged": False,
        "duration_hours": None, "is_overtime": False, "overtime_coefficient": 1.0,
        "hourly_rate_at_date": 13.75, "labor_cost": None, "created_at": CLOCK_DAY})
    costs = []
    for _ in range(2):
        r = await c.put("/api/work-sessions/ws-w1", headers=headers("sm"), json={
            "started_at": CLOCK_DAY + "T08:00:00+00:00", "ended_at": CLOCK_DAY + "T17:00:00+00:00"})
        assert r.status_code == 200, r.text
        costs.append(r.json()["labor_cost"])
    return costs


async def _approved_9h_cost(c, op):
    rid = await approved_tech_report(c, W1, hours=9)
    return (await op.work_sessions.find_one({"approved_report_id": rid}))["labor_cost"]


def test_r10_holds_today_clock_first_save_equals_approved_report(monkeypatch, backend):
    """Rule 10, what holds: W1's 9 h clock record, first save on the edit screen → 123.75,
    the same as the approved 9 h report (8 × 13.75 + 1 × 13.75 × 1.0 = 123.75)."""
    async def scenario(c, op):
        first, _ = await _clock_session_9h(c, op)
        approved = await _approved_9h_cost(c, op)
        assert first == approved, (first, approved)            # today: 123.75 == 123.75
    run(monkeypatch, backend, scenario)


# xfail removed: fixed by LAB-R96 step 3 (detect_overtime excludes the edited session)
def test_r10_clock_resave_costs_the_same_as_approved_report(monkeypatch, backend):
    """Rule 10 on the clock path (work_sessions.py update_session/detect_overtime ~64-123,
    ~496): saving the same 08:00–17:00 record again must not change its cost, and it must
    equal the approved-report cost.

    Today on de720f94: first save 123.75, unchanged re-save 185.62 (the record now counts
    itself as "> 8 h that day" → the WHOLE 9 h × 13.75 × 1.5 over_8h), approved report 123.75.
    """
    async def scenario(c, op):
        first, again = await _clock_session_9h(c, op)
        approved = await _approved_9h_cost(c, op)
        assert first == again == approved, (first, again, approved)
    run(monkeypatch, backend, scenario)
