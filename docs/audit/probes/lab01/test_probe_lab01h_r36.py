"""LAB-01-H (R36) probe — copy to <wt73>/backend/tests/ (harness from test_lab_01_h_r36).

H1 SELF-CORRECTION: the SiteManager of project P is himself the worker of an APPROVED report
   on P -> can he raise his own hours (8 -> 12)? Does the report stay APPROVED (counted by
   payroll) without anybody else approving?
H2 the same for an Admin who is the worker of the report.
H3 a report inside a CONFIRMED (not paid) pay run: payroll_status? editable by Admin?
"""
import asyncio
from tests.test_lab_01_h_r36 import ORG, DAY, U, _harness, USERS  # noqa


def _rep(uid, status="APPROVED"):
    return {"id": "SELF-" + uid, "org_id": ORG, "employee_id": uid, "created_by": uid, "report_date": DAY,
            "approval_status": status, "status": status, "payroll_status": "none", "approved_by": "admin",
            "day_entries": [{"id": "e1", "project_id": "P", "hours_worked": 8}], "total_hours": 8}


def test_h1_h2_self_correction(monkeypatch):
    async def body():
        from app.routes import daily_reports
        op = await _harness(monkeypatch, "r36_self")
        for uid in ("sm-p", "admin"):
            await op.employee_daily_reports.insert_one(_rep(uid))
            try:
                out = await daily_reports.update_daily_report("SELF-" + uid, {"day_entries": [
                    {"id": "e1", "project_id": "P", "hours_worked": 12}]}, U(uid))
                print("H %s self-correct own APPROVED report: OK total_hours %s status %s approved_by %s corrected_by %s"
                      % (uid, out["total_hours"], out["approval_status"], out.get("approved_by"), out.get("corrected_by")))
            except Exception as exc:
                print("H %s self-correct refused: %s %s" % (uid, getattr(exc, "status_code", ""), getattr(exc, "detail", exc)))
    asyncio.run(body())


def test_h4_reapproval_after_self_correction(monkeypatch):
    """H4 (LAB-01-I): after sm-p corrects his own APPROVED report (8 -> 12): status? then
    sm-p approves it -> refused? admin approves it -> OK? bulk path the same?"""
    async def body():
        from app.routes import daily_reports
        op = await _harness(monkeypatch, "r36_reapprove")
        await op.employee_daily_reports.insert_one(_rep("sm-p"))
        out = await daily_reports.update_daily_report("SELF-sm-p", {"day_entries": [
            {"id": "e1", "project_id": "P", "hours_worked": 12}]}, U("sm-p"))
        res_self = await daily_reports.approve_report_one(
            await op.employee_daily_reports.find_one({"id": "SELF-sm-p"}), U("sm-p"))
        # someone corrects via admin, then admin tries to approve his own correction
        res_admin = await daily_reports.approve_report_one(
            await op.employee_daily_reports.find_one({"id": "SELF-sm-p"}), U("admin"))
        res_owner = await daily_reports.approve_report_one(
            await op.employee_daily_reports.find_one({"id": "SELF-sm-p"}), U("owner"))
        doc = await op.employee_daily_reports.find_one({"id": "SELF-sm-p"}, {"_id": 0})
        dq = await op.dq_alerts.count_documents({"entity_id": "SELF-sm-p", "code": "DAILY_REPORT_CORRECTED_AFTER_APPROVAL"})
        print("H4 after self-correction: status", out["approval_status"], "approved_by", out.get("approved_by"),
              "| sm-p approves:", res_self.get("status"), res_self.get("reason"),
              "| admin approves:", res_admin.get("status"), res_admin.get("reason"),
              "| owner approves:", res_owner.get("status"), res_owner.get("reason"),
              "| final", doc["approval_status"], doc.get("approved_by"), "dq", dq)
        assert out["approval_status"] == "SUBMITTED" and out.get("approved_by") is None
        assert res_self["status"] == "failed" and res_self["reason"] == "self_approval"
    asyncio.run(body())


def test_h5_sm_self_correction_end_to_end(monkeypatch):
    """H5 (LAB-01-I, PR harness test_lab_01_i_four_eyes): SM sm is the WORKER of an approved 8 h
    report on his project P. He raises it to 12 h via PUT /technician/draft -> status?
    Pay Run earned before re-approval? sm approves -> 403? admin approves -> earned 120?"""
    async def body():
        from fastapi import HTTPException
        from app.routes import technician
        from app.tenancy import project_team
        from app.tenancy.data_access import TenantData
        from tests import test_lab_01_i_four_eyes as T
        op = await T._harness(monkeypatch, "h5", author="sm", approved_by="admin")
        await project_team.add_member(TenantData.for_resolved_org(op, T.ORG), member_id="m", project_id="P",
                                      user_id="sm", role_in_project=project_team.ROLE_SITE_MANAGER)
        e0 = await T._earned(op, "sm")
        out = await technician.update_draft("R", technician.DraftLineUpdate(hours=12), T.U("sm"))
        e1 = await T._earned(op, "sm")
        try:
            await T._approve("R", "sm"); self_res = "approved!"
        except HTTPException as exc:
            self_res = exc.status_code
        await T._approve("R", "admin")
        e2 = await T._earned(op, "sm")
        doc = await op.employee_daily_reports.find_one({"id": "R"}, {"_id": 0})
        print("H5 earned before", e0, "| after self-correction: status", out.get("approval_status"), "earned", e1,
              "| sm approves ->", self_res, "| admin approves -> status", doc["approval_status"],
              "approved_by", doc.get("approved_by"), "earned", e2)
        assert out.get("approval_status") == "SUBMITTED" and e1 == 0 and self_res == 403 and e2 == 120.0
    asyncio.run(body())
