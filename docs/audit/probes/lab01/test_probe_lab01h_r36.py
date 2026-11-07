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
