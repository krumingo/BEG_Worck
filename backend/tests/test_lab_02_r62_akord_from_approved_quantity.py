"""R62 + R33 on LAB-02 (#75): a manual akord labor row is priced ONLY from the LAB-02
APPROVED quantity of that worker, package, project and day (labor_quantity_approvals,
status approved) — quantity × the piece rate snapshotted in that approval. A manual row
never brings a second, typed quantity; without an approved quantity it is refused.

Reuses the R62 harness (tests/test_lab_01_s_r62_one_labor_cost.py): the same tenant,
project P, worker w1, the same app and both backends.
"""
import pytest

from tests.test_lab_01_s_r62_one_labor_cost import (  # noqa: F401
    ORG, P, _decision, _key, run)

AK_PKG = "pkg-ak"
AK_DAY = "2026-11-12"


async def _akord_setup(op, status="approved", **kw):
    await op.execution_packages.insert_one({
        "id": AK_PKG, "org_id": ORG, "project_id": P, "activity_name": "Боя",
        "labor_pay_type": "Akord", "labor_piece_rate": 9, "labor_terms_version": 4})
    appr = {"id": "qa-1", "org_id": ORG, "report_id": "R-Q", "entry_id": None, "report_version": 0,
            "worker_id": "w1", "project_id": P, "date": AK_DAY, "approved_quantity": 12.0,
            "unit": "м2", "execution_package_id": AK_PKG, "labor_pay_type": "Akord",
            "piece_rate": 5.0, "labor_terms_version": 3, "status": status, "approved_by": "owner"}
    appr.update(kw)
    await op.labor_quantity_approvals.insert_one(appr)


def _body(**kw):
    b = {"project_id": P, "employee_id": "w1", "hours": 8, "date": AK_DAY, "execution_package_id": AK_PKG}
    b.update(kw)
    return b


def test_an_akord_row_is_the_approved_quantity_times_its_snapshotted_rate(monkeypatch):
    async def scenario(c, op):
        await _akord_setup(op)
        r = await c.post("/api/labor-entries", json=_body(), headers=_key("admin"))
        assert r.status_code == 422 and r.json()["detail"]["code"] == "AKORD_NEEDS_APPROVED_QUANTITY", r.text
        r = await c.post("/api/labor-entries", json=_body(quantity_approval_id="qa-1"), headers=_key("admin"))
        assert r.status_code == 201, r.text
        row = r.json()
        # 12 (approved) × 5 (the rate IN the approval, not the package's current 9)
        assert (row["pay_type"], row["quantity"], row["piece_rate"], row["labor_cost"],
                row["labor_terms_version"], row["quantity_approval_id"]) == ("Akord", 12.0, 5.0, 60.0, 3, "qa-1")
        assert row["hourly_rate"] is None                                  # never hours × rate
    run(monkeypatch, scenario)


def test_a_typed_second_quantity_is_refused(monkeypatch):
    async def scenario(c, op):
        await _akord_setup(op)
        r = await c.post("/api/labor-entries", json=_body(quantity_approval_id="qa-1", quantity=20),
                         headers=_key("admin"))
        assert r.status_code == 422 and r.json()["detail"]["code"] == "SECOND_QUANTITY", r.text
        r = await c.post("/api/labor-entries", json=_body(quantity_approval_id="qa-1", quantity=12),
                         headers=_key("admin"))
        assert r.status_code == 201, r.text                                 # the same number is fine
        assert await op.labor_entries.count_documents({"quantity_approval_id": "qa-1"}) == 1
    run(monkeypatch, scenario)


@pytest.mark.parametrize("field,value", [
    ("worker_id", "sm"), ("execution_package_id", "pkg-other"), ("project_id", "prj-x"),
    ("date", "2026-11-13"), ("status", "void")])
def test_the_approval_must_be_the_approved_one_of_that_worker_package_and_day(monkeypatch, field, value):
    async def scenario(c, op):
        await _akord_setup(op, **{field: value})
        r = await c.post("/api/labor-entries", json=_body(quantity_approval_id="qa-1"), headers=_key("admin"))
        assert r.status_code == 422 and r.json()["detail"]["code"] == "AKORD_APPROVAL_MISMATCH", (field, r.text)
        assert await op.labor_entries.count_documents({"execution_package_id": AK_PKG}) == 0
    run(monkeypatch, scenario)


def test_one_approved_quantity_backs_one_live_row_and_a_voided_one_is_not_approved(monkeypatch):
    async def scenario(c, op):
        await _akord_setup(op)
        r = await c.post("/api/labor-entries", json=_body(quantity_approval_id="qa-1"), headers=_key("admin"))
        assert r.status_code == 201, r.text
        rid = r.json()["id"]
        r2 = await c.post("/api/labor-entries", json=_body(quantity_approval_id="qa-1", date="2026-11-12"),
                          headers=_key("owner"))
        assert r2.status_code == 409 and r2.json()["detail"]["code"] == "APPROVED_QUANTITY_IN_USE", r2.text
        # LAB-02 voids the approval (a re-approval) — the manual row can no longer be approved
        await op.labor_quantity_approvals.update_one({"id": "qa-1"}, {"$set": {"status": "void"}})
        r = await c.post(f"/api/labor-entries/{rid}/approve", json=_decision(cost=60.0), headers=_key("owner"))
        assert r.status_code == 409 and r.json()["detail"]["code"] == "APPROVED_QUANTITY_VOID", r.text
        assert (await op.labor_entries.find_one({"id": rid}))["approval_status"] == "pending"
    run(monkeypatch, scenario)
