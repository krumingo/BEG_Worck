"""LAB-02 x #72@13dd8d7 probe (copy to a #75+#72 merged tree's backend/tests/):
the key of a FAILED approve is retried by 6 concurrent identical requests -> how many approval records?"""
import asyncio
from tests.test_lab_02_quantity_approval import ORG, H, _token, _set_rate, run  # noqa


def test_r1_approve_retake_of_failed_key(monkeypatch):
    async def scenario(c, op):
        from app.audit.idempotency import begin_idempotent, fail_idempotent, request_fingerprint
        from app.routes import labor_quantities as lq
        assert (await _set_rate(c)).status_code == 200
        await c.put("/api/labor-quantities/entry", json={"report_id": "R-AK", "quantity": 120}, headers=H("w-ak", False))
        await op.employee_daily_reports.update_one({"id": "R-AK"}, {"$set": {"status": "APPROVED"}})
        ver = (await op.employee_daily_reports.find_one({"id": "R-AK"}))["report_version"]
        body = {"report_id": "R-AK", "report_version": ver, "approved_quantity": 120,
                "execution_package_id": "pkg-sh", "note": ""}
        payload = lq.QuantityApprovalInput(**body).model_dump()
        await begin_idempotent(lq.db, tenant_id=ORG, key="retake", action="labor_quantity.approve",
                               request_fingerprint=request_fingerprint(payload))
        await fail_idempotent(lq.db, tenant_id=ORG, key="retake", action="labor_quantity.approve", error_code="x")
        h = dict(_token("sm"), **{"Idempotency-Key": "retake"})
        rs = await asyncio.gather(*[c.post("/api/labor-quantities/approve", json=body, headers=h) for _ in range(6)])
        n = await op.labor_quantity_approvals.count_documents({})
        print("R1 codes", sorted(r.status_code for r in rs), "approval records", n)
        assert n == 1, f"R1 FAIL: {n} approval records from one failed-key retake"
    run(monkeypatch, scenario, "real")
