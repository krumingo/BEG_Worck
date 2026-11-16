"""
LAB-R96 step 3b — the remaining labor readers on the ONE reader (Р100 "P&L, ведомост, бюджет
по дейност и „Приходи/разходи" четат едните одобрени редове"; Р96 "ръчните редове не се
плащат"; Р101 old clock records kept as their own component; Р102 reported = forecast).

For each moved reader, one approved 9 h day of an hourly (W0, 12 €/h), a daily (W1, 110 €/d)
and a monthly (W2, 2200 €/22 d) worker gives the pay run's hours and cost (108 / 110 / 100);
a reported (Submitted, not approved) line of another worker on the same day is NOT cost; a
``labor_entries`` row ("ръчен ред", 5 h / 500 €) is NOT counted; a second tenant with the same
project id, worker ids and line shapes never reaches ORG's figures.

Moved readers: money_write.project_labor_workers (sessions / lines), budget_progress burn
warnings, /projects/{id}/site-workers, /projects/{id}/aggregate, alarm_engine (budget,
overtime), centralized_reports, expected_actual, pulse_generator, morning_briefing, the
worker-calendar sync, /activity-reports + /work-sessions/{id}/detail, labor_smr (recompute,
by-execution-package, labor-warnings), /profit-by-period, /financial-alerts.

Same harness as ``test_lab_r96_rules.py`` (mongomock and, with ``W0_03_REAL_MONGO_URL``, a
real disposable MongoDB).

    PYTHONPATH=. pytest tests/test_lab_r96_step3b_readers.py -v --noconftest -p no:cacheprovider
"""
import asyncio
import importlib

import pytest

from tests import test_lab_r96_rules as base
from tests.test_lab_r96_money_rules import approved_tech_report, generate, row_of
from tests.test_lab_r96_rules import A, ORG, P, TODAY, W0, W1, W2, backend, headers
from tests.test_lab_r96_step3_one_read import clock_session, submitted_flat

__all__ = ["backend"]

EXTRA_ROUTERS = ("activity_budgets", "financial_results", "full_cost", "projects",
                 "budget_progress", "labor_smr", "revenue_snapshot", "overhead_realtime",
                 "expected_actual", "centralized_reports")
SERVICES = ("alarm_engine", "pulse_generator", "morning_briefing", "centralized_reports",
            "expected_actual", "labor_cost_reader")
NINE = {W0: 108.0, W1: 110.0, W2: 100.0}      # the pay run's earned for one 9 h day
CHILD = "prj-lab-child"
PKG = "ep-lab-a"
OTHER_ORG = "ORG-LABR96-OTHER"
ADMIN = {"id": "admin", "org_id": ORG, "role": "Admin"}


def svc(name):
    return importlib.import_module("app.services." + name)


def route(name):
    return importlib.import_module("app.routes." + name)


async def _seed_more(op):
    await op.activity_budgets.insert_one({
        "id": "ab-a", "org_id": ORG, "project_id": P, "type": A, "subtype": "",
        "labor_budget": 100, "materials_budget": 0})
    await op.execution_packages.insert_one({
        "id": PKG, "org_id": ORG, "project_id": P, "activity_name": A, "qty": 10,
        "labor_budget_total": 1000, "budget_total": 1000, "sale_total": 5000})
    await op.projects.insert_one({"id": CHILD, "org_id": ORG, "name": "Под-обект",
                                  "code": "P-1-A", "status": "Active", "parent_project_id": P})
    # a "ръчен ред" (labor_entries, no screen — Р96): never labor cost
    await op.labor_entries.insert_one({
        "id": "le-manual", "org_id": ORG, "project_id": P, "execution_package_id": PKG,
        "employee_id": W0, "date": TODAY, "hours": 5, "hourly_rate": 100, "labor_cost": 500})


async def _seed_other_tenant(op):
    """The same project id, worker ids and line shapes in ANOTHER tenant — plus its own
    manual row and old clock session. None of it may reach ORG's figures."""
    for wid in (W0, W1, W2):
        await op.employee_profiles.insert_one({"org_id": OTHER_ORG, "user_id": wid,
                                               "pay_type": "Hourly", "hourly_rate": 50})
        await op.employee_daily_reports.insert_one({
            "id": "other-" + wid, "org_id": OTHER_ORG, "worker_id": wid, "worker_name": wid,
            "date": TODAY, "project_id": P, "smr_type": A, "hours": 9, "status": "APPROVED",
            "created_at": TODAY})
    await op.labor_entries.insert_one({
        "id": "le-other", "org_id": OTHER_ORG, "project_id": P, "execution_package_id": PKG,
        "employee_id": W0, "date": TODAY, "hours": 7, "labor_cost": 700})
    await op.work_sessions.insert_one({
        "id": "ws-other", "org_id": OTHER_ORG, "worker_id": W0, "site_id": P, "smr_type_id": A,
        "started_at": TODAY + "T08:00:00+00:00", "ended_at": TODAY + "T11:00:00+00:00",
        "source_method": "SELF_REPORT", "duration_hours": 3, "labor_cost": 999,
        "is_overtime": True})


def run(monkeypatch, backend, scenario, other_tenant=False):
    import httpx
    monkeypatch.setattr(base, "ROUTERS", base.ROUTERS + EXTRA_ROUTERS)
    for name in SERVICES:
        svc(name)

    async def body():
        async with base._Db(backend) as op:
            await base.seed(op)
            await _seed_more(op)
            if other_tenant:
                await _seed_other_tenant(op)
            base._patch_db(monkeypatch, op)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=base._app()),
                                         base_url="http://labr96") as c:
                return await scenario(c, op)
    return asyncio.run(body())


async def get(c, path, **params):
    r = await c.get("/api" + path, headers=headers("admin"), params=params or None)
    assert r.status_code == 200, (path, r.text)
    return r.json()


def other_of(wid):
    return W1 if wid == W0 else W0


async def nine_hour_day(c, op, wid):
    """The fixture day: ``wid`` approved 9 h on P/A; another worker reported (Submitted, not
    approved) 8 h on P/A; the manual row. Returns the pay run's earned for ``wid``."""
    await approved_tech_report(c, wid, hours=9)
    await submitted_flat(op, wid=other_of(wid), hours=8)
    gen = await generate(c)
    w, o = row_of(gen, wid), row_of(gen, other_of(wid))
    assert (w["approved_hours"], w["earned_amount"]) == (9, NINE[wid])
    assert o is None or o["earned_amount"] == 0          # the pay run: not approved, not paid
    return w["earned_amount"]


# ═══════════════════════════════════════════════════════════════════ the readers
async def _all_readers(c, op, wid, cost):
    """Every moved reader on the fixture day → {reader: (hours, cost)} for ``wid``'s labor,
    plus the checks that the reported line and the manual row are not counted."""
    other = other_of(wid)
    got = {}

    # money_write.project_labor_workers — the Technical Manager's 2+ worker count
    mw = importlib.import_module("app.permissions.money_write")
    for source in ("sessions", "lines"):
        by_smr, n = await mw.project_labor_workers(ADMIN, P, source)
        assert (by_smr, n) == ({A.lower(): {wid}}, 1), (source, by_smr, n)

    # budget_progress burn warnings (labor budget 100): the burn % is the cost
    pw = await get(c, "/progress-warnings/%s" % P)
    msgs = " | ".join(w_["message"] for w_ in pw["warnings"])
    assert ("%s%%" % round(cost / 100 * 100, 1)) in msgs, msgs

    # /site-workers
    sw = {w_["worker_id"]: w_ for w_ in (await get(c, "/projects/%s/site-workers" % P))["workers"]}
    got["site_workers"] = (sw[wid]["approved_hours"], sw[wid]["total_earned"])
    assert sw[other]["total_earned"] == 0 and sw[other]["earned_forecast"] > 0

    # /aggregate (own project)
    ag = await get(c, "/projects/%s/aggregate" % P)
    got["aggregate"] = (ag["work"]["own"]["hours"], ag["work"]["own"]["labor_cost"])
    assert ag["work"]["own"]["forecast_cost"] > 0

    # alarm_engine budget (spent %) and overtime (1 h over the 8 h day)
    ev = await svc("alarm_engine").evaluate_rule(
        {"id": "r-b", "type": "budget", "condition": {"operator": ">", "threshold": 0}}, ORG)
    got["alarm_budget_pct"] = (None, [e["context"]["metric_value"] for e in ev
                                      if e["site_id"] == P][0])
    ev = await svc("alarm_engine").evaluate_rule(
        {"id": "r-o", "type": "overtime", "condition": {"operator": ">", "threshold": 0}}, ORG)
    assert {(e["context"]["entity_id"], e["context"]["metric_value"]) for e in ev} == {(wid, 1.0)}

    # centralized reports
    cr = await svc("centralized_reports").build_centralized_reports(ORG, P)
    act = [a for a in cr["activities"] if a["activity_name"] == A][0]
    got["centralized"] = (act["approved_hours"], cr["finance"]["total_clean_labor"])
    assert cr["finance"]["draft_clean_labor"] > 0          # the reported line: forecast only
    assert cr["finance"]["labor_components"]["clock_legacy"]["cost"] == 0

    # expected vs actual
    ea = await svc("expected_actual").build_expected_actual(ORG, P)
    a = [x for x in ea["activities"] if x["name"] == A][0]
    got["expected_actual"] = (a["actual_hours"], a["actual_cost"])

    # pulse of the day
    pu = await svc("pulse_generator").generate_pulse(ORG, P, TODAY)
    got["pulse"] = (pu["total_hours"], pu["total_labor_cost"])
    assert pu["overtime_hours"] == 1 and pu["total_workers"] == 1
    assert pu["budget_snapshot"]["total_spent"] == cost
    assert pu["forecast_labor_cost"] > 0

    # morning briefing: people with labor today (approved + reported) = 2
    mb = await svc("morning_briefing").build_morning_briefing(ORG, TODAY)
    assert mb["summary"]["workers_today"] == 2

    # worker calendar sync: the approved day only
    r = await route("overhead_realtime").sync_from_sessions(date=TODAY, _sec01={}, user=ADMIN)
    assert r["ok"]
    cal = {d["worker_id"]: d async for d in op.worker_calendar.find({"org_id": ORG}, {"_id": 0})}
    assert set(cal) == {wid} and cal[wid]["hours"] == 9

    # activity drill-down (Level 2) + worker-day detail (Level 3)
    ar = await get(c, "/projects/%s/activity-reports/%s" % (P, A))
    rows = {r_["worker_id"]: r_ for r_ in ar["reports"]}
    got["activity_reports"] = (ar["totals"]["total_hours"], ar["totals"]["total_cost"])
    assert (rows[other]["state"], rows[other]["counted"]) == ("reported", False)
    det = await get(c, "/work-sessions/%s/detail" % rows[wid]["session_ids"][0])
    got["session_detail"] = (det["hours"], det["total_cost"])
    assert det["state"] == "approved_unpaid" and det["is_overtime"] is True
    ws = await op.work_sessions.find_one({"org_id": ORG, "source_method": "APPROVED_REPORT"},
                                         {"_id": 0, "id": 1})
    det2 = await get(c, "/work-sessions/%s/detail" % ws["id"])     # an approval session
    got["approval_session_detail"] = (det2["hours"], det2["total_cost"])

    # labor_smr: recompute → package cache; by-execution-package; labor-warnings
    await route("labor_smr")._recompute_package_labor(P, ADMIN)
    pkg = await op.execution_packages.find_one({"id": PKG}, {"_id": 0})
    got["package_recompute"] = (pkg["used_hours"], pkg["actual_labor_cost"])
    assert pkg["manual_entries_not_counted"] == {"counted": False, "hours": 5, "cost": 500}
    bp = await get(c, "/labor-cost/by-execution-package/%s" % PKG)
    got["by_execution_package"] = (bp["used_hours"], bp["labor_actual_cost"])
    assert bp["manual_entries_not_counted"]["cost"] == 500
    lw = await get(c, "/labor-warnings/%s" % P)
    assert (lw["total_entries"], lw["unmapped_entries"]) == (1, 0)
    assert lw["manual_entries_not_counted"] == {"counted": False, "entries": 1}

    # profit by period
    pp = await get(c, "/profit-by-period/%s" % P)
    month = [x for x in pp["periods"] if x["period"] == TODAY[:7]][0]
    got["profit_by_period"] = (month["labor_hours"], month["labor"])
    assert month["manual_entries_not_counted"]["cost"] == 500
    assert pp["manual_entries_not_counted"]["cost"] == 500

    # financial alerts: the approved line is attributed to the package → no unmapped alert
    fa = await get(c, "/financial-alerts/%s" % P)
    assert not [x for x in fa.get("alerts", []) if x.get("type") == "unmapped_labor"]
    return got


@pytest.mark.parametrize("wid", [W0, W1, W2])
def test_every_moved_reader_gives_the_pay_run_number(monkeypatch, backend, wid):
    """One approved 9 h day: every moved reader shows 9 h and the pay run's earned (108 /
    110 / 100); the reported line and the manual row add nothing."""
    async def scenario(c, op):
        cost = await nine_hour_day(c, op, wid)
        got = await _all_readers(c, op, wid, cost)
        alarm = got.pop("alarm_budget_pct")[1]
        assert alarm == round(cost / 100 * 100, 1)
        assert set(got.values()) == {(9, cost)}, got
    run(monkeypatch, backend, scenario)


def test_unapproved_line_is_not_cost_anywhere(monkeypatch, backend):
    """Only a reported (Submitted) 8 h line and the manual row: no moved reader shows cost."""
    async def scenario(c, op):
        await submitted_flat(op, wid=W2, hours=8)
        _by, n = await importlib.import_module("app.permissions.money_write") \
            .project_labor_workers(ADMIN, P, "sessions")
        assert n == 0
        cr = await svc("centralized_reports").build_centralized_reports(ORG, P)
        assert cr["finance"]["total_clean_labor"] == 0 and cr["finance"]["draft_clean_labor"] == 100
        ea = await svc("expected_actual").build_expected_actual(ORG, P)
        assert ea["summary"]["total_actual_cost"] == 0
        pu = await svc("pulse_generator").generate_pulse(ORG, P, TODAY)
        assert (pu["total_labor_cost"], pu["budget_snapshot"]["total_spent"]) == (0, 0)
        assert pu["forecast_labor_cost"] == 100
        sw = (await get(c, "/projects/%s/site-workers" % P))["workers"]
        assert {w_["worker_id"]: w_["total_earned"] for w_ in sw}.get(W2) == 0
        ar = await get(c, "/projects/%s/activity-reports/%s" % (P, A))
        assert (ar["totals"]["total_cost"], ar["totals"]["forecast_cost"]) == (0, 100)
        await route("labor_smr")._recompute_package_labor(P, ADMIN)
        pkg = await op.execution_packages.find_one({"id": PKG}, {"_id": 0})
        assert (pkg["used_hours"], pkg["actual_labor_cost"]) == (0, 0)  # 5 h / 500 manual: no
        pp = await get(c, "/profit-by-period/%s" % P)
        assert all(x["labor"] == 0 for x in pp["periods"])
        pw = await get(c, "/progress-warnings/%s" % P)
        assert not [w_ for w_ in pw["warnings"] if w_["type"].startswith("budget_")]
    run(monkeypatch, backend, scenario)


def test_old_clock_session_stays_a_visible_component(monkeypatch, backend):
    """Р101: an old clock session (3 h / 36) is counted where the screen counted every work
    session before — and is shown as its own component, never merged silently."""
    async def scenario(c, op):
        await approved_tech_report(c, W0, hours=8)        # 96
        await clock_session(op)                            # W0 3 h / 36, SELF_REPORT
        cr = await svc("centralized_reports").build_centralized_reports(ORG, P)
        assert cr["finance"]["total_clean_labor"] == 132
        assert cr["finance"]["labor_components"]["approved_lines"] == 96
        assert cr["finance"]["labor_components"]["clock_legacy"]["cost"] == 36
        ea = await svc("expected_actual").build_expected_actual(ORG, P)
        a = [x for x in ea["activities"] if x["name"] == A][0]
        assert (a["actual_cost"], a["clock_legacy_cost"]) == (132, 36)
        assert ea["summary"]["labor_components"]["clock_legacy"]["cost"] == 36
        pu = await svc("pulse_generator").generate_pulse(ORG, P, TODAY)
        assert (pu["total_labor_cost"], pu["labor_components"]["clock_legacy"]["cost"]) == (132, 36)
        sw = {w_["worker_id"]: w_ for w_ in (await get(c, "/projects/%s/site-workers" % P))["workers"]}
        assert (sw[W0]["total_earned"], sw[W0]["earned_clock_legacy"]) == (132, 36)
        ag = await get(c, "/projects/%s/aggregate" % P)
        assert (ag["work"]["own"]["labor_cost"], ag["work"]["own"]["clock_legacy"]["cost"]) == (132, 36)
        ar = await get(c, "/projects/%s/activity-reports/%s" % (P, A))
        assert (ar["totals"]["total_cost"], ar["totals"]["clock_legacy"]["cost"]) == (132, 36)
        clock_row = [r_ for r_ in ar["reports"] if r_["state"] == "clock_legacy"][0]
        det = await get(c, "/work-sessions/%s/detail" % clock_row["session_ids"][0])
        assert (det["state"], det["total_cost"], det["counted"]) == ("clock_legacy", 36, True)
        # the approval work_session of the 8 h line is NOT a second 96 anywhere
        by, n = await importlib.import_module("app.permissions.money_write") \
            .project_labor_workers(ADMIN, P, "sessions")
        assert (by, n) == ({A.lower(): {W0}}, 1)
        # „Приходи/разходи"-like screens that never counted clock: profit-by-period
        pp = await get(c, "/profit-by-period/%s" % P)
        month = [x for x in pp["periods"] if x["period"] == TODAY[:7]][0]
        assert month["labor"] == 96 and pp["clock_legacy"] == dict(
            pp["clock_legacy"], cost=36, counted=False)
    run(monkeypatch, backend, scenario)


def test_moved_readers_are_tenant_isolated(monkeypatch, backend):
    """Another tenant with the same project id, worker ids and line shapes (+ its manual row
    and clock session): ORG's figures are exactly the 9 h day of W0 (108)."""
    async def scenario(c, op):
        cost = await nine_hour_day(c, op, W0)
        got = await _all_readers(c, op, W0, cost)
        got.pop("alarm_budget_pct")
        assert set(got.values()) == {(9, cost)}, got
    run(monkeypatch, backend, scenario, other_tenant=True)
