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
                          headers=_key("acct"))          # not the quantity's approver (FG-508)
        assert r2.status_code == 409 and r2.json()["detail"]["code"] == "APPROVED_QUANTITY_IN_USE", r2.text
        # LAB-02 voids the approval (a re-approval) — the manual row can no longer be approved
        await op.labor_quantity_approvals.update_one({"id": "qa-1"}, {"$set": {"status": "void"}})
        r = await c.post(f"/api/labor-entries/{rid}/approve", json=_decision(cost=60.0), headers=_key("owner"))
        assert r.status_code == 409 and r.json()["detail"]["code"] == "APPROVED_QUANTITY_VOID", r.text
        assert (await op.labor_entries.find_one({"id": rid}))["approval_status"] == "pending"
    run(monkeypatch, scenario)


# ═══════════════════════════════════════════════ FLOW Guard pass 41: FG-508 (R66), FG-507 (R77)

@pytest.mark.parametrize("approver,creator", [("w1", "admin"), ("admin", "admin")])
def test_fg508_a_quantity_approved_by_the_worker_or_the_creator_is_refused(monkeypatch, approver, creator):
    async def scenario(c, op):
        await _akord_setup(op, approved_by=approver)
        r = await c.post("/api/labor-entries", json=_body(quantity_approval_id="qa-1"), headers=_key(creator))
        assert r.status_code == 409 and r.json()["detail"]["code"] == "SELF_APPROVED_QUANTITY", r.text
        assert await op.labor_entries.count_documents({"quantity_approval_id": "qa-1"}) == 0
    run(monkeypatch, scenario)


def test_fg508_old_rows_with_a_self_approved_quantity_are_not_approved_and_are_flagged(monkeypatch):
    from app.services.labor_cost import project_labor_cost

    async def scenario(c, op):
        await _akord_setup(op, approved_by="admin")
        base = {"org_id": ORG, "project_id": P, "employee_id": "w1", "execution_package_id": AK_PKG,
                "hours": 8, "pay_type": "Akord", "quantity": 12.0, "piece_rate": 5.0, "labor_cost": 60.0,
                "quantity_approval_id": "qa-1", "source": "manual", "created_by": "admin", "version": 1,
                "reversed_by_entry_id": None}
        await op.labor_entries.insert_one(dict(base, id="old-p", date=AK_DAY, approval_status="pending"))
        r = await c.post("/api/labor-entries/old-p/approve", json=_decision(cost=60.0), headers=_key("owner"))
        assert r.status_code == 409 and r.json()["detail"]["code"] == "SELF_APPROVED_QUANTITY", r.text
        await op.labor_entries.insert_one(dict(base, id="old-a", date="2026-11-11", approval_status="approved",
                                               approved_by="owner", approved_by_role="Owner"))
        lc = await project_labor_cost(ORG, P)
        rec = [x for x in lc["lines"] if x.get("manual_entry_id") == "old-a"][0]
        assert "MANUAL_AKORD_SELF_APPROVED_QUANTITY" in rec["dq"] and rec["amount"] == 60.0   # flagged, not hidden
    run(monkeypatch, scenario)


async def _approved_akord_row(c, op):
    await _akord_setup(op)
    r = await c.post("/api/labor-entries", json=_body(quantity_approval_id="qa-1"), headers=_key("admin"))
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    r = await c.post(f"/api/labor-entries/{rid}/approve", json=_decision(cost=60.0), headers=_key("owner"))
    assert r.status_code == 200, r.text
    return rid


def test_r77_a_voided_quantity_flags_the_row_which_still_counts_with_a_warning(monkeypatch):
    from app.services.labor_cost import project_labor_cost, void_labor_approvals
    from app.tenancy.data_access import TenantData

    async def scenario(c, op):
        rid = await _approved_akord_row(c, op)
        tenant = TenantData.for_resolved_org(op, ORG)
        await void_labor_approvals(tenant, ORG, "R-Q", "sm", "report_corrected")
        row = await op.labor_entries.find_one({"id": rid})
        flag = row["correction_required"]
        assert flag["status"] == "изисква корекция" and flag["changed_approval_id"] == "qa-1"
        assert flag["old"] == {"quantity": 12.0, "piece_rate": 5.0, "labor_cost": 60.0}
        assert flag["proposal"]["action"] == "reverse_and_reenter" and flag["proposal"]["approved_by_second_person"]
        assert (row["approval_status"], row["labor_cost"]) == ("approved", 60.0)      # unchanged
        ev = await op.audit_events.find_one({"entity_id": rid, "action": "labor.manual_entry.correction_required"})
        assert ev and ev["actor_id"] == "sm"
        al = await op.alarm_events.find_one({"type": "labor_correction_required", "context.entity_id": rid})
        assert al and al["status"] == "active" and al["site_id"] == P
        lc = await project_labor_cost(ORG, P)
        rec = [x for x in lc["lines"] if x.get("manual_entry_id") == rid][0]
        assert rec["amount"] == 60.0 and "MANUAL_ROW_CORRECTION_REQUIRED" in rec["dq"]   # old amount + warning
        assert any(w["code"] == "MANUAL_ROW_CORRECTION_REQUIRED" for w in lc["dq_warnings"])
    run(monkeypatch, scenario)


def test_r77_a_corrected_quantity_proposes_the_new_amount_and_the_fix_needs_a_second_person(monkeypatch):
    from app.services.labor_cost import flag_rows_of_changed_quantities, project_labor_cost
    from app.tenancy.data_access import TenantData

    async def scenario(c, op):
        rid = await _approved_akord_row(c, op)
        tenant = TenantData.for_resolved_org(op, ORG)
        # LAB-02 re-approval: qa-1 void, qa-2 approved at 10 (the route calls this with the new record)
        await op.labor_quantity_approvals.update_one({"id": "qa-1"}, {"$set": {"status": "void"}})
        qa2 = {"id": "qa-2", "org_id": ORG, "report_id": "R-Q", "entry_id": None, "report_version": 1,
               "worker_id": "w1", "project_id": P, "date": AK_DAY, "approved_quantity": 10.0,
               "execution_package_id": AK_PKG, "labor_pay_type": "Akord", "piece_rate": 5.0,
               "labor_terms_version": 3, "status": "approved", "approved_by": "owner", "replaces": ["qa-1"]}
        await op.labor_quantity_approvals.insert_one(dict(qa2))
        assert await flag_rows_of_changed_quantities(tenant, ORG, ["qa-1"], "owner", "corrected (re-approved)",
                                                     replacement=qa2) == 1
        prop = (await op.labor_entries.find_one({"id": rid}))["correction_required"]["proposal"]
        assert (prop["replacement_approval_id"], prop["quantity"], prop["labor_cost"]) == ("qa-2", 10.0, 50.0)
        # the fix: reverse the old row (resolves the alarm), enter the new one, a second person approves
        r = await c.post(f"/api/labor-entries/{rid}/reverse", json=_decision(version=2, cost=60.0, reason="R77"),
                         headers=_key("owner"))
        assert r.status_code == 200, r.text
        al = await op.alarm_events.find_one({"type": "labor_correction_required", "context.entity_id": rid})
        assert al["status"] == "resolved"
        r = await c.post("/api/labor-entries", json=_body(quantity_approval_id="qa-2", corrects_entry_id=rid),
                         headers=_key("admin"))
        assert r.status_code == 201, r.text
        new = r.json()
        assert (new["quantity"], new["labor_cost"], new["corrects_entry_id"]) == (10.0, 50.0, rid)
        r = await c.post(f"/api/labor-entries/{new['id']}/approve", json=_decision(cost=50.0), headers=_key("admin"))
        assert r.status_code == 403, r.text                          # forbidden: the creator (R66)
        r = await c.post(f"/api/labor-entries/{new['id']}/approve", json=_decision(cost=50.0), headers=_key("acct"))
        assert r.status_code == 200, r.text                          # a second person
        lc = await project_labor_cost(ORG, P)
        mine = [x for x in lc["lines"] if x.get("manual_entry_id") in (rid, new["id"])]
        assert [x["amount"] for x in mine] == [50.0], mine           # the old row stopped counting
    run(monkeypatch, scenario)


def test_r77_only_approved_rows_of_the_changed_quantity_are_flagged(monkeypatch):
    from app.services.labor_cost import flag_rows_of_changed_quantities
    from app.tenancy.data_access import TenantData

    async def scenario(c, op):
        await _akord_setup(op)
        r = await c.post("/api/labor-entries", json=_body(quantity_approval_id="qa-1"), headers=_key("admin"))
        rid = r.json()["id"]                                          # pending — not counted yet
        tenant = TenantData.for_resolved_org(op, ORG)
        assert await flag_rows_of_changed_quantities(tenant, ORG, ["qa-1"], "sm", "voided") == 0
        assert "correction_required" not in await op.labor_entries.find_one({"id": rid})
        assert await op.alarm_events.count_documents({"type": "labor_correction_required"}) == 0
        assert await flag_rows_of_changed_quantities(tenant, ORG, ["qa-other"], "sm", "voided") == 0
    run(monkeypatch, scenario)


# ═══════════════════════════════════════════════ FLOW Guard pass 44: FG-531, FG-533, FG-534

def _with_lab02_and_alarms(monkeypatch):
    """The R62 app plus the LAB-02 quantity routes and the alarm routes (same db, same
    explicit no-transaction runner on mongomock)."""
    import tests.test_lab_01_s_r62_one_labor_cost as r62
    from app.routes import alarms, labor_quantities
    orig = r62._app

    def app_with(mp, op):
        app = orig(mp, op)
        app.include_router(labor_quantities.router, prefix="/api")
        app.include_router(alarms.router, prefix="/api")
        return app
    monkeypatch.setattr(r62, "_app", app_with)
    orig_mm = r62._mongomock_has_no_transactions

    def no_tx(mp):
        orig_mm(mp)

        async def body_only(body):
            return await body(None)
        mp.setattr(labor_quantities, "_run_tx", body_only, raising=False)
    monkeypatch.setattr(r62, "_mongomock_has_no_transactions", no_tx)


async def _report_of_the_quantity(op):
    await op.employee_daily_reports.insert_one({
        "id": "R-Q", "org_id": ORG, "worker_id": "w1", "submitted_by": "w1", "date": AK_DAY,
        "project_id": P, "hours": 8, "quantity": 12, "smr_type": "Боя", "status": "SUBMITTED",
        "report_version": 0})


def _reapprove(qty, replaces):
    return {"report_id": "R-Q", "entry_id": None, "report_version": 0, "approved_quantity": qty,
            "execution_package_id": AK_PKG, "replaces_approval_id": replaces, "note": "корекция"}


def test_fg531_every_later_correction_or_void_reaches_the_flagged_row(monkeypatch):
    """FG-531: the flag follows the chain — a 2nd correction (of the replacement) and a later
    void reach the row; the earlier flag is kept in correction_history; the proposal follows
    the latest approved quantity; an AuditEvent and an alarm each time."""
    from app.services.labor_cost import void_labor_approvals
    from app.tenancy.data_access import TenantData
    _with_lab02_and_alarms(monkeypatch)

    async def scenario(c, op):
        await _report_of_the_quantity(op)
        rid = await _approved_akord_row(c, op)
        r = await c.post("/api/labor-quantities/approve", json=_reapprove(10, "qa-1"), headers=_key("owner"))
        assert r.status_code == 200, r.text
        qa2 = r.json()["id"]
        f1 = (await op.labor_entries.find_one({"id": rid}))["correction_required"]
        assert (f1["sequence"], f1["chain"], f1["proposal"]["replacement_approval_id"],
                f1["proposal"]["labor_cost"]) == (1, ["qa-1", qa2], qa2, 90.0)   # 10 × the package's 9
        r = await c.post("/api/labor-quantities/approve", json=_reapprove(8, qa2), headers=_key("owner"))
        assert r.status_code == 200, r.text
        qa3 = r.json()["id"]
        row = await op.labor_entries.find_one({"id": rid})
        f2 = row["correction_required"]
        assert (f2["sequence"], f2["chain"], f2["proposal"]["replacement_approval_id"],
                f2["proposal"]["labor_cost"]) == (2, ["qa-1", qa2, qa3], qa3, 72.0)   # 8 × 9
        assert row["correction_history"] == [f1]                       # not overwritten
        # a later void of the latest quantity (the report changed): no approved quantity left
        await void_labor_approvals(TenantData.for_resolved_org(op, ORG), ORG, "R-Q", "sm", "report_corrected")
        row = await op.labor_entries.find_one({"id": rid})
        f3 = row["correction_required"]
        assert f3["sequence"] == 3 and f3["proposal"]["replacement_approval_id"] is None
        assert [h["sequence"] for h in row["correction_history"]] == [1, 2]
        assert (row["approval_status"], row["labor_cost"]) == ("approved", 60.0)   # still counts
        assert await op.audit_events.count_documents(
            {"entity_id": rid, "action": "labor.manual_entry.correction_required"}) == 3
        assert await op.alarm_events.count_documents(
            {"type": "labor_correction_required", "context.entity_id": rid}) == 3
    run(monkeypatch, scenario)


def test_fg533_the_alarm_closes_only_after_a_reversal_and_the_row_is_listed_until_then(monkeypatch):
    from app.services.labor_cost import void_labor_approvals
    from app.tenancy.data_access import TenantData
    _with_lab02_and_alarms(monkeypatch)

    async def scenario(c, op):
        await _report_of_the_quantity(op)
        rid = await _approved_akord_row(c, op)
        await void_labor_approvals(TenantData.for_resolved_org(op, ORG), ORG, "R-Q", "sm", "report_corrected")
        al = await op.alarm_events.find_one({"type": "labor_correction_required", "context.entity_id": rid})
        from tests.test_lab_01_s_r62_one_labor_cost import _token
        lst = await c.get("/api/labor-entries", params={"project_id": P, "correction_required": "true"},
                          headers=_token("owner"))
        assert [x["id"] for x in lst.json()] == [rid], lst.text
        r = await c.put(f"/api/alarms/{al['id']}/resolve", json={"notes": "видяно"}, headers=_token("owner"))
        assert r.status_code == 409 and r.json()["detail"]["code"] == "CORRECTION_REQUIRED", r.text   # forbidden
        assert (await op.alarm_events.find_one({"id": al["id"]}))["status"] == "active"
        r = await c.post(f"/api/labor-entries/{rid}/reverse", json=_decision(version=2, cost=60.0, reason="R77"),
                         headers=_key("owner"))
        assert r.status_code == 200, r.text
        assert (await op.alarm_events.find_one({"id": al["id"]}))["status"] == "resolved"
        r = await c.put(f"/api/alarms/{al['id']}/resolve", json={"notes": "ok"}, headers=_token("owner"))
        assert r.status_code == 200, r.text                             # allowed after the reversal
        lst = await c.get("/api/labor-entries", params={"project_id": P, "correction_required": "true"},
                          headers=_token("owner"))
        assert lst.json() == []
    run(monkeypatch, scenario)


@pytest.mark.skipif(bool(__import__("tests.test_lab_01_s_r62_one_labor_cost", fromlist=["x"])._real_refusal()),
                    reason="real Mongo only (a transaction)")
def test_fg534_the_correction_void_insert_and_flag_are_one_transaction(monkeypatch):
    """A failure while flagging the rows rolls the whole correction back: the old approval
    stays approved, no new one, no flag, no AuditEvent of it."""
    from app.services import labor_cost
    _with_lab02_and_alarms(monkeypatch)

    async def scenario(c, op):
        await _report_of_the_quantity(op)
        rid = await _approved_akord_row(c, op)

        async def boom(*a, **k):
            raise RuntimeError("simulated failure while flagging")
        monkeypatch.setattr(labor_cost, "flag_rows_of_changed_quantities", boom)
        r = await c.post("/api/labor-quantities/approve", json=_reapprove(10, "qa-1"), headers=_key("owner"))
        assert r.status_code >= 500 or r.status_code == 409, r.text
        assert (await op.labor_quantity_approvals.find_one({"id": "qa-1"}))["status"] == "approved"
        assert await op.labor_quantity_approvals.count_documents({"report_id": "R-Q"}) == 1
        assert "correction_required" not in await op.labor_entries.find_one({"id": rid})
        assert await op.audit_events.count_documents({"action": "labor_quantity.corrected"}) == 0
    run(monkeypatch, scenario, backend="real")
