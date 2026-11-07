"""
LAB-01-L — FG-99: POST /daily-reports/{id}/reset follows the same rules as the edit paths.

* the payroll lock is decided from the Pay Run lines (LAB-01-J / FG-91), for both report
  formats and for confirmed runs too: a report in payroll is 409, nothing is changed and
  its quantity approvals stay;
* the R36 role rule: Admin, Owner or the SiteManager of the report's project(s) — not the
  author, not another project's SiteManager, not finance;
* every reset writes a canonical AuditEvent (daily_report.reset) with before / after.

    pytest tests/test_lab_01_l_reset.py -v --noconftest
"""
import asyncio

import pytest
from fastapi import HTTPException

from tests.test_lab_01_j_payroll_lock import DAY, ORG, _harness

USERS = {"admin": "Admin", "owner": "Owner", "sm-p": "SiteManager", "sm-q": "SiteManager",
         "t2": "Technician", "acct": "Accountant"}


def U(uid):
    return {"id": uid, "org_id": ORG, "role": USERS[uid], "email": uid + "@l01l.example"}


async def _setup(monkeypatch, name):
    from app.tenancy import project_team
    from app.tenancy.data_access import TenantData
    op = await _harness(monkeypatch, name)
    for uid, role in USERS.items():
        await op.users.insert_one({"id": uid, "org_id": ORG, "role": role, "is_active": True,
                                   "email": uid + "@l01l.example"})
    await op.projects.insert_many([{"id": "P", "org_id": ORG, "name": "P"},
                                   {"id": "Q", "org_id": ORG, "name": "Q"}])
    tenant = TenantData.for_resolved_org(op, ORG)
    await project_team.add_member(tenant, member_id="m1", project_id="P", user_id="sm-p",
                                  role_in_project=project_team.ROLE_SITE_MANAGER)
    await project_team.add_member(tenant, member_id="m2", project_id="Q", user_id="sm-q",
                                  role_in_project=project_team.ROLE_SITE_MANAGER)
    await op.labor_quantity_approvals.insert_many([
        {"id": f"qa-{r}", "org_id": ORG, "report_id": r, "entry_id": None, "report_version": 0,
         "approved_quantity": 10, "status": "approved", "approved_by": "sm-p"}
        for r in ("OLD", "NEW", "FREE")])
    return op


async def _audits(op, rid):
    return [a async for a in op.audit_events.find({"entity_id": rid}, {"_id": 0})]


@pytest.mark.parametrize("rid,run", [("OLD", "PR-0001"), ("NEW", "PR-0002")])
def test_fg99_reset_of_a_report_in_payroll_is_409_for_everyone(monkeypatch, rid, run):
    """old format in a PAID run (lines <report>_<entry>), new format in a CONFIRMED run."""
    async def body():
        from app.routes import daily_reports
        op = await _setup(monkeypatch, "l01l_lock_" + rid)
        before = await op.employee_daily_reports.find_one({"id": rid}, {"_id": 0})
        for who in ("admin", "owner", "sm-p"):
            with pytest.raises(HTTPException) as ex:
                await daily_reports.reset_daily_report(rid, U(who))
            assert ex.value.status_code == 409 and run in ex.value.detail, who
        assert await op.employee_daily_reports.find_one({"id": rid}, {"_id": 0}) == before
        assert (await op.labor_quantity_approvals.find_one({"id": f"qa-{rid}"}))["status"] == "approved"
        assert await _audits(op, rid) == []
    asyncio.run(body())


@pytest.mark.parametrize("who", ["admin", "owner", "sm-p"])
def test_fg99_reset_by_a_corrector_writes_an_audit_event(monkeypatch, who):
    async def body():
        from app.routes import daily_reports
        op = await _setup(monkeypatch, "l01l_ok_" + who)
        out = await daily_reports.reset_daily_report("FREE", U(who))
        assert out["approval_status"] == "SUBMITTED" and out["approved_by"] is None
        assert (await op.labor_quantity_approvals.find_one({"id": "qa-FREE"}))["status"] == "void"
        audits = await _audits(op, "FREE")
        assert [(a["action"], a["actor_id"]) for a in audits] == [("daily_report.reset", who)]
        diff = audits[0]["structured_diff"]
        assert (diff["before"]["approval_status"], diff["after"]["approval_status"]) == ("APPROVED", "SUBMITTED")
        assert audits[0]["occurred_at"] and audits[0]["tool_or_endpoint"] == "POST /daily-reports/{id}/reset"
    asyncio.run(body())


@pytest.mark.parametrize("who", ["sm-q", "t2", "acct"])
def test_fg99_others_cannot_reset(monkeypatch, who):
    """another project's SiteManager, the author (t2), finance → 403, nothing changed."""
    async def body():
        from app.routes import daily_reports
        op = await _setup(monkeypatch, "l01l_no_" + who)
        before = await op.employee_daily_reports.find_one({"id": "FREE"}, {"_id": 0})
        with pytest.raises(HTTPException) as ex:
            await daily_reports.reset_daily_report("FREE", U(who))
        assert ex.value.status_code == 403
        assert await op.employee_daily_reports.find_one({"id": "FREE"}, {"_id": 0}) == before
        assert (await op.labor_quantity_approvals.find_one({"id": "qa-FREE"}))["status"] == "approved"
        assert await _audits(op, "FREE") == []
    asyncio.run(body())


def test_fg99_only_an_approved_report_is_reset(monkeypatch):
    async def body():
        from app.routes import daily_reports
        op = await _setup(monkeypatch, "l01l_status")
        await op.employee_daily_reports.update_one({"id": "FREE"}, {"$set": {"status": "SUBMITTED",
                                                                            "approval_status": "SUBMITTED"}})
        with pytest.raises(HTTPException) as ex:
            await daily_reports.reset_daily_report("FREE", U("admin"))
        assert ex.value.status_code == 400
        assert await _audits(op, "FREE") == []
    asyncio.run(body())


@pytest.mark.parametrize("role", ["Technician", "Accountant", "Worker", "Viewer", "Driver", "Warehousekeeper",
                                  "SiteManager"])
def test_pm73_01_a_non_resetting_role_gets_403_before_the_lookup(monkeypatch, role):
    """deny by default: 403 for a missing report too, so existence is not revealed."""
    async def body():
        from app.routes import daily_reports
        await _setup(monkeypatch, "l01l_pm_" + role)
        u = {"id": "x", "org_id": ORG, "role": role}
        for rid in ("FREE", "does-not-exist"):
            with pytest.raises(HTTPException) as ex:
                await daily_reports.reset_daily_report(rid, u)
            assert ex.value.status_code == 403, (role, rid)
    asyncio.run(body())


def test_pm73_01_admin_gets_404_for_a_missing_report(monkeypatch):
    async def body():
        from app.routes import daily_reports
        await _setup(monkeypatch, "l01l_pm_admin404")
        with pytest.raises(HTTPException) as ex:
            await daily_reports.reset_daily_report("does-not-exist", U("admin"))
        assert ex.value.status_code == 404
    asyncio.run(body())
