"""
LAB-01-I — LAB01H-1 (CLAUDE.md §8/§16 four-eyes): no self-approval through a correction.

* correcting an APPROVED report (any role, R36) sends it back to SUBMITTED: approved_by
  cleared, payroll_ready off, quantity approvals void, work sessions flagged, DQ alert;
* nobody approves a report they authored or corrected; a second approver can;
* payroll counts the corrected hours only after the re-approval;
* a report already in payroll stays 409.

    pytest tests/test_lab_01_i_four_eyes.py -v --noconftest
"""
import asyncio

import pytest
from fastapi import HTTPException

ORG = "ORG-L01I"
DAY = "2026-11-02"
USERS = {"admin": "Admin", "owner": "Owner", "sm": "SiteManager", "w": "Worker"}


def U(uid):
    return {"id": uid, "org_id": ORG, "role": USERS[uid], "email": uid + "@l01i.example"}


async def _harness(monkeypatch, name, author="w", approved_by="sm", payroll="none"):
    from mongomock_motor import AsyncMongoMockClient
    from app.deps import auth as deps_auth
    from app.routes import daily_reports, pay_runs, technician
    from app.services import labor_cost, payroll_sync, report_normalizer
    import sys
    import app.db as appdb
    op = AsyncMongoMockClient()[name]
    # every loaded app module that holds the global handle (the approval path reads through
    # several of them: resolve_hourly_rate, counters, …) gets the test database
    real = appdb.db
    for mod in list(sys.modules.values()):
        if getattr(mod, "__name__", "").startswith("app") and getattr(mod, "db", None) is real:
            monkeypatch.setattr(mod, "db", op)
    for m in (daily_reports, technician, labor_cost, deps_auth, pay_runs, payroll_sync, report_normalizer):
        monkeypatch.setattr(m, "db", op)
    await op.organizations.insert_one({"id": ORG, "name": "L01I"})
    for uid, role in USERS.items():
        await op.users.insert_one({"id": uid, "org_id": ORG, "role": role, "is_active": True,
                                   "email": uid + "@l01i.example", "first_name": uid, "last_name": "X"})
        await op.employee_profiles.insert_one({"org_id": ORG, "user_id": uid, "pay_type": "Hourly",
                                               "hourly_rate": 10})
    await op.projects.insert_one({"id": "P", "org_id": ORG, "name": "P"})
    await op.employee_daily_reports.insert_one({
        "id": "R", "org_id": ORG, "worker_id": author, "submitted_by": author, "date": DAY, "hours": 8,
        "project_id": "P", "smr_type": "Шпакловка", "status": "APPROVED", "approval_status": "APPROVED",
        "approved_by": approved_by, "approved_at": DAY + "T18:00:00", "payroll_status": payroll,
        "payroll_ready": True, "created_at": DAY + "T17:00:00"})
    await op.work_sessions.insert_one({"id": "ws", "org_id": ORG, "approved_report_id": "R", "labor_cost": 80})
    await op.labor_quantity_approvals.insert_one({
        "id": "qa", "org_id": ORG, "report_id": "R", "entry_id": None, "report_version": 0,
        "approved_quantity": 10, "status": "approved", "approved_by": approved_by})
    return op


async def _earned(op, who="w"):
    from app.routes import pay_runs
    preview = await pay_runs.generate_pay_run(U("admin"), period_start=DAY, period_end=DAY)
    return {r["employee_id"]: r["earned_amount"] for r in preview["rows"]}.get(who, 0.0)


async def _approve(rid, who):
    from app.routes import daily_reports
    return await daily_reports.approve_daily_report(rid, {}, U(who))


def test_admin_correcting_an_approved_report_cannot_reapprove_it_a_second_approver_can(monkeypatch):
    async def body():
        from app.routes import technician
        op = await _harness(monkeypatch, "l01i_a")
        assert await _earned(op) == 80.0                               # 8 h × 10, approved
        out = await technician.update_draft("R", technician.DraftLineUpdate(hours=12), U("admin"))
        # back to SUBMITTED: nothing of it is payable until a new approval
        assert (out["status"], out["approval_status"], out["approved_by"]) == ("SUBMITTED", "SUBMITTED", None)
        assert out["payroll_ready"] is False and out["correctors"] == ["admin"]
        assert out["reopened_by_correction"]["previous_approved_by"] == "sm"
        assert (await op.labor_quantity_approvals.find_one({"id": "qa"}))["status"] == "void"
        assert (await op.work_sessions.find_one({"id": "ws"}))["flag_reason"] == "voided_by_correction"
        dq = await op.dq_alerts.find_one({"code": "DAILY_REPORT_CORRECTED_AFTER_APPROVAL"}, {"_id": 0})
        assert dq["status"] == "open" and dq["entity_id"] == "R" and dq["corrected_by"] == "admin"
        assert await _earned(op) == 0.0                                # not paid while SUBMITTED
        # the corrector cannot approve it
        with pytest.raises(HTTPException) as ex:
            await _approve("R", "admin")
        assert ex.value.status_code == 403
        assert (await op.employee_daily_reports.find_one({"id": "R"}))["status"] == "SUBMITTED"
        assert await _earned(op) == 0.0
        # a second approver (Owner) can — only now are the 12 h payable
        res = await _approve("R", "owner")
        assert res["approval_status"] == "APPROVED" and res["approved_by"] == "owner"
        assert await _earned(op) == 120.0
    asyncio.run(body())


def test_admin_correcting_their_own_report_cannot_reapprove_it(monkeypatch):
    async def body():
        from app.routes import technician
        op = await _harness(monkeypatch, "l01i_b", author="admin", approved_by="sm")
        await technician.update_draft("R", technician.DraftLineUpdate(hours=12), U("admin"))
        with pytest.raises(HTTPException) as ex:
            await _approve("R", "admin")                               # author AND corrector
        assert ex.value.status_code == 403
        res = await _approve("R", "sm")                                 # someone else
        assert res["approved_by"] == "sm"
        assert await _earned(op, "admin") == 120.0
    asyncio.run(body())


def test_site_manager_correction_via_put_also_reopens_and_blocks_self_approval(monkeypatch):
    async def body():
        from app.routes import daily_reports
        from app.tenancy import project_team
        from app.tenancy.data_access import TenantData
        op = await _harness(monkeypatch, "l01i_c")
        await project_team.add_member(TenantData.for_resolved_org(op, ORG), member_id="m", project_id="P",
                                      user_id="sm", role_in_project=project_team.ROLE_SITE_MANAGER)
        out = await daily_reports.update_daily_report("R", {"notes": "12 h"}, U("sm"))
        assert out["approval_status"] == "SUBMITTED" and out["approved_by"] is None
        with pytest.raises(HTTPException) as ex:
            await _approve("R", "sm")
        assert ex.value.status_code == 403
        assert (await _approve("R", "admin"))["approved_by"] == "admin"
    asyncio.run(body())


def test_the_worker_cannot_approve_their_own_report(monkeypatch):
    async def body():
        op = await _harness(monkeypatch, "l01i_d")
        await op.employee_daily_reports.update_one({"id": "R"}, {"$set": {
            "status": "SUBMITTED", "approval_status": "SUBMITTED", "approved_by": None}})
        await op.users.update_one({"id": "w"}, {"$set": {"role": "SiteManager"}})
        USERS["w"] = "SiteManager"
        try:
            with pytest.raises(HTTPException) as ex:
                await _approve("R", "w")
            assert ex.value.status_code == 403
        finally:
            USERS["w"] = "Worker"
    asyncio.run(body())


def test_a_report_in_payroll_stays_409(monkeypatch):
    async def body():
        from app.routes import technician
        await _harness(monkeypatch, "l01i_e", payroll="paid")
        with pytest.raises(HTTPException) as ex:
            await technician.update_draft("R", technician.DraftLineUpdate(hours=12), U("admin"))
        assert ex.value.status_code == 409
    asyncio.run(body())
