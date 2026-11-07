"""
LAB-01-H — R36 (LAB-01 Addendum A, Krum 07.11.2026): correcting daily reports, per role.

* the author corrects only their own draft / returned report;
* Admin, Owner and the SiteManager of the report's project correct ANY report,
  an approved one included, with an AuditEvent (who, when, before / after);
* correcting an approved report bumps its version and voids its quantity approvals;
* a report already in payroll (batched / paid) is not edited by anyone (409);
* for PUT /daily-reports/{id}, PUT /technician/draft/{id} and POST /daily-reports/batch-save.

    pytest tests/test_lab_01_h_r36.py -v --noconftest
"""
import asyncio

import pytest
from fastapi import HTTPException

ORG = "ORG-R36"
DAY = "2026-11-02"
USERS = {
    "admin": "Admin", "owner": "Owner", "sm-p": "SiteManager", "sm-other": "SiteManager",
    "tech": "Technician", "w": "Worker", "acct": "Accountant",
}


async def _harness(monkeypatch, name):
    from mongomock_motor import AsyncMongoMockClient
    from app.deps import auth as deps_auth
    from app.routes import daily_reports, technician
    from app.services import labor_cost
    from app.tenancy import project_team
    from app.tenancy.data_access import TenantData
    op = AsyncMongoMockClient()[name]
    for m in (daily_reports, technician, labor_cost, deps_auth):
        monkeypatch.setattr(m, "db", op)
    await op.organizations.insert_one({"id": ORG, "name": "R36"})
    for uid, role in USERS.items():
        await op.users.insert_one({"id": uid, "org_id": ORG, "role": role, "is_active": True,
                                   "email": uid + "@r36.example"})
    await op.projects.insert_many([{"id": "P", "org_id": ORG, "name": "P"},
                                   {"id": "Q", "org_id": ORG, "name": "Q"}])
    tenant = TenantData.for_resolved_org(op, ORG)
    await project_team.add_member(tenant, member_id="m1", project_id="P", user_id="sm-p",
                                  role_in_project=project_team.ROLE_SITE_MANAGER)
    await project_team.add_member(tenant, member_id="m2", project_id="Q", user_id="sm-other",
                                  role_in_project=project_team.ROLE_SITE_MANAGER)
    return op


def U(uid):
    return {"id": uid, "org_id": ORG, "role": USERS[uid], "email": uid + "@r36.example"}


async def _old_report(op, status="APPROVED", payroll="none"):
    await op.employee_daily_reports.insert_one({
        "id": "REP", "org_id": ORG, "employee_id": "w", "created_by": "w", "report_date": DAY,
        "approval_status": status, "status": status, "payroll_status": payroll,
        "day_entries": [{"id": "e1", "project_id": "P", "hours_worked": 8}], "total_hours": 8})
    await op.labor_quantity_approvals.insert_one({
        "id": "qa", "org_id": ORG, "report_id": "REP", "entry_id": "e1", "report_version": 0,
        "approved_quantity": 10, "status": "approved", "approved_by": "sm-p"})


async def _audits(op, entity="REP"):
    return [a async for a in op.audit_events.find({"entity_id": entity}, {"_id": 0}).sort("sequence", 1)]


# ═══════════════════════════════════════════════════════════════ PUT /daily-reports/{id}
@pytest.mark.parametrize("who", ["admin", "owner", "sm-p"])
def test_r36_put_corrector_corrects_an_approved_report_with_audit(monkeypatch, who):
    async def body():
        from app.routes import daily_reports
        op = await _harness(monkeypatch, "r36_put_" + who)
        await _old_report(op)
        out = await daily_reports.update_daily_report("REP", {"day_entries": [
            {"id": "e1", "project_id": "P", "hours_worked": 6}]}, U(who))
        assert out["total_hours"] == 6 and out["approval_status"] == "APPROVED"
        assert out["report_version"] == 1 and out["corrected_by"] == who
        assert (await op.labor_quantity_approvals.find_one({"id": "qa"}))["status"] == "void"
        audits = await _audits(op)
        assert len(audits) == 1
        a = audits[0]
        assert (a["action"], a["actor_id"], a["entity_version"]) == ("daily_report.corrected", who, "1")
        assert a["structured_diff"]["before"]["total_hours"] == 8
        assert a["structured_diff"]["after"]["total_hours"] == 6
        assert a["occurred_at"]                                         # when
    asyncio.run(body())


@pytest.mark.parametrize("who,code", [("sm-other", 403), ("tech", 403), ("acct", 403), ("w", 400)])
def test_r36_put_others_cannot_correct_an_approved_report(monkeypatch, who, code):
    async def body():
        from app.routes import daily_reports
        op = await _harness(monkeypatch, "r36_put_no_" + who)
        await _old_report(op)
        before = await op.employee_daily_reports.find_one({"id": "REP"}, {"_id": 0})
        with pytest.raises(HTTPException) as ex:
            await daily_reports.update_daily_report("REP", {"day_entries": [
                {"id": "e1", "project_id": "P", "hours_worked": 14}]}, U(who))
        assert ex.value.status_code == code
        assert await op.employee_daily_reports.find_one({"id": "REP"}, {"_id": 0}) == before
        assert (await op.labor_quantity_approvals.find_one({"id": "qa"}))["status"] == "approved"
        assert await _audits(op) == []
    asyncio.run(body())


def test_r36_put_author_corrects_own_draft_and_returned_with_audit(monkeypatch):
    async def body():
        from app.routes import daily_reports
        for status in ("DRAFT", "REJECTED"):
            op = await _harness(monkeypatch, "r36_put_author_" + status)
            await _old_report(op, status)
            out = await daily_reports.update_daily_report("REP", {"notes": "fix"}, U("w"))
            assert out["notes"] == "fix" and "corrected_by" not in out
            assert [a["action"] for a in await _audits(op)] == ["daily_report.edited"]
    asyncio.run(body())


def test_r36_put_a_SiteManager_needs_every_project_of_the_report(monkeypatch):
    async def body():
        from app.routes import daily_reports
        op = await _harness(monkeypatch, "r36_put_two_projects")
        await _old_report(op)
        # moving / adding an entry to project Q (not his) is refused for the SiteManager of P
        with pytest.raises(HTTPException) as ex:
            await daily_reports.update_daily_report("REP", {"day_entries": [
                {"id": "e1", "project_id": "P", "hours_worked": 4},
                {"id": "e2", "project_id": "Q", "hours_worked": 4}]}, U("sm-p"))
        assert ex.value.status_code == 403
    asyncio.run(body())


@pytest.mark.parametrize("payroll", ["batched", "paid"])
def test_r36_put_a_report_in_payroll_is_not_edited_by_anyone(monkeypatch, payroll):
    async def body():
        from app.routes import daily_reports
        op = await _harness(monkeypatch, "r36_put_payroll_" + payroll)
        await _old_report(op, payroll=payroll)
        for who in ("admin", "owner", "sm-p", "w"):
            with pytest.raises(HTTPException) as ex:
                await daily_reports.update_daily_report("REP", {"notes": "x"}, U(who))
            assert ex.value.status_code == 409, who
        assert await _audits(op) == []
    asyncio.run(body())


# ═══════════════════════════════════════════════════════════════ PUT /technician/draft/{id}
async def _new_report(op, status="Approved"):
    await op.employee_daily_reports.insert_one({
        "id": "D", "org_id": ORG, "worker_id": "tech", "submitted_by": "tech", "date": DAY,
        "hours": 8, "status": status, "project_id": "P"})


@pytest.mark.parametrize("who,code", [("admin", 200), ("owner", 200), ("sm-p", 200), ("sm-other", 403),
                                      ("w", 403), ("tech", 400)])
def test_r36_technician_draft_per_role_on_an_approved_report(monkeypatch, who, code):
    async def body():
        from app.routes import technician
        op = await _harness(monkeypatch, "r36_tech_" + who)
        await _new_report(op)
        if code == 200:
            out = await technician.update_draft("D", technician.DraftLineUpdate(hours=6), U(who))
            assert out["hours"] == 6 and out["report_version"] == 1 and out["corrected_by"] == who
            audits = await _audits(op, "D")
            assert [a["action"] for a in audits] == ["daily_report.corrected"]
            assert audits[0]["structured_diff"] == {"before": {"hours": 8}, "after": {"hours": 6}}
        else:
            with pytest.raises(HTTPException) as ex:
                await technician.update_draft("D", technician.DraftLineUpdate(hours=0.5), U(who))
            assert ex.value.status_code == code
            assert (await op.employee_daily_reports.find_one({"id": "D"}))["hours"] == 8
            assert await _audits(op, "D") == []
    asyncio.run(body())


def test_r36_technician_author_corrects_own_draft_and_returned(monkeypatch):
    async def body():
        from app.routes import technician
        for status in ("Draft", "Rejected"):
            op = await _harness(monkeypatch, "r36_tech_author_" + status)
            await _new_report(op, status)
            out = await technician.update_draft("D", technician.DraftLineUpdate(hours=7), U("tech"))
            assert out["hours"] == 7
            assert [a["action"] for a in await _audits(op, "D")] == ["daily_report.edited"]
        # a SUBMITTED report is not the author's to change any more
        op = await _harness(monkeypatch, "r36_tech_author_sub")
        await _new_report(op, "Submitted")
        with pytest.raises(HTTPException) as ex:
            await technician.update_draft("D", technician.DraftLineUpdate(hours=7), U("tech"))
        assert ex.value.status_code == 400
    asyncio.run(body())


# ═══════════════════════════════════════════════════════════════ POST /daily-reports/batch-save
def _batch(hours=6, project="P", emps=("w",)):
    return {"project_id": project, "report_date": DAY,
            "entries": [{"employee_id": e, "hours_worked": hours} for e in emps]}


@pytest.mark.parametrize("who", ["admin", "owner", "sm-p"])
def test_r36_batch_corrector_corrects_an_approved_report_with_audit(monkeypatch, who):
    async def body():
        from app.routes import daily_reports
        op = await _harness(monkeypatch, "r36_batch_" + who)
        await _old_report(op)
        res = await daily_reports.batch_save_daily_entries(_batch(6), U(who))
        assert res["employees_saved"] == 1
        rep = await op.employee_daily_reports.find_one({"id": "REP"}, {"_id": 0})
        assert rep["total_hours"] == 6 and rep["report_version"] == 1 and rep["approval_status"] == "APPROVED"
        assert (await op.labor_quantity_approvals.find_one({"id": "qa"}))["status"] == "void"
        audits = await _audits(op)
        assert [a["action"] for a in audits] == ["daily_report.corrected"]
        assert audits[0]["structured_diff"]["before"]["total_hours"] == 8
        assert audits[0]["structured_diff"]["after"]["total_hours"] == 6
    asyncio.run(body())


@pytest.mark.parametrize("who,code", [("sm-other", 403), ("tech", 403), ("w", 400)])
def test_r36_batch_others_cannot_correct_an_approved_report(monkeypatch, who, code):
    async def body():
        from app.routes import daily_reports
        op = await _harness(monkeypatch, "r36_batch_no_" + who)
        await _old_report(op)
        before = await op.employee_daily_reports.find({}, {"_id": 0}).to_list(10)
        with pytest.raises(HTTPException) as ex:
            await daily_reports.batch_save_daily_entries(_batch(14, emps=("w", "new-worker")), U(who))
        assert ex.value.status_code == code
        # nothing written — not even the new worker's report of the same batch
        assert await op.employee_daily_reports.find({}, {"_id": 0}).to_list(10) == before
        assert await _audits(op) == []
    asyncio.run(body())


def test_r36_batch_in_payroll_is_refused_for_everyone(monkeypatch):
    async def body():
        from app.routes import daily_reports
        op = await _harness(monkeypatch, "r36_batch_paid")
        await _old_report(op, payroll="paid")
        with pytest.raises(HTTPException) as ex:
            await daily_reports.batch_save_daily_entries(_batch(6), U("admin"))
        assert ex.value.status_code == 409
    asyncio.run(body())
