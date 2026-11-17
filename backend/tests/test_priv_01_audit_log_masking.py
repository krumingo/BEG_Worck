"""
PRIV-01 — pay / rate values in the legacy ``audit_logs`` (FLOW Guard pass 72 on main
3863610: FG-726, FG-725).

Canon:
  FLOW-040 §9  "банкови сметки, лични номера, заплати и PII се маскират според ролята";
               "before/after използва field-level diff и references".
  FLOW-040 §11 Администратор: "няма автоматичен достъп до payroll ... без отделно
               sensitive-domain право"; Platform support: "business content само чрез
               break-glass".
  FLOW-040 §6  R4: "structured metadata, tool calls, показана чернова, human confirmation
               и official action — наследяват R1/R2/R3 според действието".

Rows:
  1. write: ``PUT /employees/{id}`` (hr.py:164) stores no pay/rate value in clear; the key
     stays (the fact that it changed); ``PUT /work-types/{id}`` and the advance amount the
     same (unit, both legacy sinks);
  2. positive: a platform admin WITH the payroll read right (Accountant / Admin in the
     catalog) sees the values of a pre-PRIV-01 clear row — off, shadow, enforce;
  3. forbidden: a platform admin WITHOUT it (Viewer, SiteManager, Technician by role)
     gets every pay/rate value masked, the rest of the row unchanged — off, shadow,
     enforce; in enforce ``users.role = Admin`` without an active assignment is masked too
     (the Permission Service decides, not ``users.role``, not ``is_platform_admin``);
  4. tenant isolation: tenant B's platform admin (payroll right or not) never receives a
     row or value of tenant A;
  5. retention: an AI master-data proposal records R2, the same class as a human proposal
     of the same record — never R4.

Runs on ``mongomock_motor`` and, when ``W0_03_REAL_MONGO_URL`` names a disposable LOCAL
MongoDB, again against it. Authentication is real (JWT + user loaded from the database).

    PYTHONPATH=. pytest tests/test_priv_01_audit_log_masking.py -v --noconftest
"""
import asyncio

import pytest

from app.audit.pay_masking import MASKED, PAYROLL_READ_ACTION, mask_changes, mask_row
from tests.test_r0_03_roles_email import _Dbs, _app, _hash
from tests.test_r0_05_pay_run_selected_only import _real_refusal, _token

ORG_A, ORG_B = "ORG-PRIV01-A", "ORG-PRIV01-B"
MODES = ["off", "shadow", "enforce"]
USERS = {   # id -> (org, role, is_platform_admin)
    "owner-a": (ORG_A, "Owner", False),
    "acct-a": (ORG_A, "Accountant", False),
    "pa-acct-a": (ORG_A, "Accountant", True),
    "pa-admin-a": (ORG_A, "Admin", True),
    "pa-viewer-a": (ORG_A, "Viewer", True),
    "pa-sm-a": (ORG_A, "SiteManager", True),
    "pa-tech-a": (ORG_A, "Technician", True),
    "pa-revoked-a": (ORG_A, "Admin", True),   # enforce: assignment revoked
    "worker-a": (ORG_A, "Technician", False),
    "pa-acct-b": (ORG_B, "Accountant", True),
    "pa-viewer-b": (ORG_B, "Viewer", True),
}
PAYROLL_HOLDERS = ("pa-acct-a", "pa-admin-a")
NO_PAYROLL = ("pa-viewer-a", "pa-sm-a", "pa-tech-a")

# A pre-PRIV-01 row as main 3863610 wrote it (hr.py:164, in clear).
LEGACY_A = {"id": "log-legacy-a", "org_id": ORG_A, "user_id": "owner-a",
            "user_email": "owner-a@priv01.example", "action": "employee_profile_updated",
            "entity_type": "employee", "entity_id": "worker-a",
            "changes": {"hourly_rate": 18.5, "daily_rate": 148.0, "monthly_salary": 2400.0,
                        "insurance_amount": 311.0, "position": "Зидар",
                        "standard_hours_per_day": 8, "updated_at": "2026-11-01T08:00:00"},
            "timestamp": "2026-11-01T08:00:00+00:00"}
LEGACY_B = {"id": "log-legacy-b", "org_id": ORG_B, "user_id": "pa-acct-b",
            "user_email": "pa-acct-b@priv01.example", "action": "employee_profile_updated",
            "entity_type": "employee", "entity_id": "someone-b",
            "changes": {"monthly_salary": 3100.0, "position": "Кранист"},
            "timestamp": "2026-11-02T08:00:00+00:00"}
A_VALUES = (18.5, 148.0, 2400.0, 311.0)
PAY_KEYS_A = ("hourly_rate", "daily_rate", "monthly_salary", "insurance_amount")


@pytest.fixture(params=["mongomock", pytest.param("real", marks=pytest.mark.skipif(
    bool(_real_refusal()), reason=_real_refusal() or "ok"))])
def backend(request):
    return request.param


@pytest.fixture(params=MODES)
def mode(request):
    return request.param


def hdr(uid):
    org, role, _pa = USERS[uid]
    return _token(uid, org, role)


async def _seed(op, sysdb):
    from app.permissions.catalog import LEGACY_ROLE_MAP
    for org in (ORG_A, ORG_B):
        await op.organizations.insert_one({"id": org, "name": "Org " + org})
        await op.subscriptions.insert_one({"id": "sub-" + org, "org_id": org,
                                           "plan_id": "enterprise", "status": "active"})
        await sysdb.tenant_registry.insert_one({"id": org, "legacy_org_id": org,
                                                "status": "active", "database_name": op.name})
    for uid, (org, role, pa) in USERS.items():
        await op.users.insert_one({"id": uid, "org_id": org, "role": role, "is_active": True,
                                   "is_platform_admin": pa, "email": uid + "@priv01.example",
                                   "password_hash": _hash(), "first_name": uid,
                                   "last_name": "Staff", "phone": "000"})
        await sysdb.tenant_memberships.insert_one({"id": "tm_" + uid, "user_id": uid,
                                                   "tenant_id": org, "status": "active"})
        await sysdb.tenant_role_assignments.insert_one({
            "id": "ra_" + uid, "user_id": uid, "tenant_id": org,
            "role_id": LEGACY_ROLE_MAP[role], "scope_type": "company", "scope_id": None,
            "module": None, "permissions": [],
            "status": "revoked" if uid == "pa-revoked-a" else "active",
            "sync_source": "users.role"})
    await op.audit_logs.insert_many([dict(LEGACY_A), dict(LEGACY_B)])


def run(monkeypatch, backend, mode, scenario):
    import httpx

    async def go():
        async with _Dbs(backend) as (op, sysdb):
            await _seed(op, sysdb)
            app = _app(monkeypatch, op, sysdb, mode)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://priv01") as c:
                return await scenario(c, op)
    return asyncio.run(go())


async def _logs(c, uid):
    r = await c.get("/api/audit-logs", headers=hdr(uid))
    assert r.status_code == 200, r.text
    return {row["id"]: row for row in r.json()["logs"]}, r.json()


# ═══════════════════════════════════════════════════════════════════ 1. write side
def test_write_hr_profile_update_stores_no_pay_value_in_clear(monkeypatch, backend, mode):
    async def scenario(c, op):
        r = await c.put("/api/employees/worker-a", headers=hdr("owner-a"), json={
            "hourly_rate": 21.75, "monthly_salary": 3333.0, "insurance_pct": 0.328,
            "position": "Бригадир", "pay_type": "Hourly"})
        assert r.status_code == 200, r.text
        assert r.json()["hourly_rate"] == 21.75            # the source record keeps it
        rows = await op.audit_logs.find({"action": "employee_profile_updated",
                                         "entity_id": "worker-a",
                                         "id": {"$ne": "log-legacy-a"}}, {"_id": 0}).to_list(None)
        assert len(rows) == 1
        ch = rows[0]["changes"]
        for key in ("hourly_rate", "monthly_salary", "insurance_pct"):
            assert ch[key] == MASKED                        # key kept: "it changed"
        assert ch["position"] == "Бригадир" and ch["pay_type"] == "Hourly"
        blob = repr(rows[0])
        assert "21.75" not in blob and "3333" not in blob and "0.328" not in blob
        # the row names its source record: the reference to the real value
        assert (rows[0]["entity_type"], rows[0]["entity_id"]) == ("employee", "worker-a")
        # the pre-PRIV-01 row is untouched: append-only, no rewrite, no delete
        legacy = await op.audit_logs.find_one({"id": "log-legacy-a"}, {"_id": 0})
        assert legacy == LEGACY_A
    run(monkeypatch, backend, mode, scenario)


def test_both_legacy_sinks_mask_and_keep_non_pay_values():
    changes = {"hourly_rate": 10, "default_hourly_rate": 12.5, "akord_note": "5 €/м2",
               "vat_rate": 20, "name": "Зидария", "nested": [{"daily_rate": 80}]}
    masked = mask_changes(changes, "work_type")
    assert masked["hourly_rate"] == masked["default_hourly_rate"] == MASKED
    assert masked["akord_note"] == MASKED and masked["nested"][0]["daily_rate"] == MASKED
    assert masked["vat_rate"] == 20 and masked["name"] == "Зидария"
    assert changes["hourly_rate"] == 10                    # input not mutated
    # an advance to a person is pay; a payment / overhead amount is not
    assert mask_changes({"amount": 300, "type": "Advance"}, "advance")["amount"] == MASKED
    assert mask_changes({"amount": 300}, "payment")["amount"] == 300
    assert mask_changes(None, "employee") is None

    import mongomock_motor
    from app.services import audit as s_audit
    from app.utils import audit as u_audit

    async def go():
        db = mongomock_motor.AsyncMongoMockClient()["priv01_unit"]
        await u_audit.log_audit("o", "u", "e", "updated", "work_type", "wt1",
                                {"default_hourly_rate": 12.5, "name": "x"}, db_handle=db)
        from app.tenancy.data_access import TenantData
        orig = TenantData.for_resolved_org
        TenantData.for_resolved_org = staticmethod(lambda _db, org: orig(db, org))
        try:
            await s_audit.log_audit("o", "u", "e", "advance_created", "advance", "a1",
                                    {"amount": 300, "recipient": "R"})
        finally:
            TenantData.for_resolved_org = orig
        return await db.audit_logs.find({}, {"_id": 0}).to_list(None)
    rows = {r["entity_id"]: r for r in asyncio.run(go())}
    assert rows["wt1"]["changes"] == {"default_hourly_rate": MASKED, "name": "x"}
    assert rows["a1"]["changes"] == {"amount": MASKED, "recipient": "R"}


# ═══════════════════════════════════════════════════════════════════ 2. positive
@pytest.mark.parametrize("uid", PAYROLL_HOLDERS)
def test_payroll_holder_sees_the_values(monkeypatch, backend, mode, uid):
    async def scenario(c, op):
        rows, _ = await _logs(c, uid)
        assert rows["log-legacy-a"]["changes"] == LEGACY_A["changes"]
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════════════ 3. forbidden
@pytest.mark.parametrize("uid", NO_PAYROLL)
def test_platform_admin_without_payroll_right_gets_values_masked(monkeypatch, backend, mode, uid):
    async def scenario(c, op):
        rows, body = await _logs(c, uid)
        row = rows["log-legacy-a"]
        for key in PAY_KEYS_A:
            assert row["changes"][key] == MASKED
        assert row["changes"]["position"] == "Зидар"        # non-pay values stay
        assert row["changes"]["standard_hours_per_day"] == 8
        assert {k: v for k, v in row.items() if k != "changes"} == \
            {k: v for k, v in LEGACY_A.items() if k != "changes"}
        for value in A_VALUES:
            assert repr(value) not in repr(body)
        # the stored row is not rewritten by the read
        assert await op.audit_logs.find_one({"id": "log-legacy-a"}, {"_id": 0}) == LEGACY_A
    run(monkeypatch, backend, mode, scenario)


def test_enforce_users_role_admin_without_assignment_is_masked(monkeypatch, backend):
    """enforce: the Permission Service decides — users.role = Admin and is_platform_admin
    with a REVOKED assignment hold no payroll right. off/shadow keep the legacy role rule."""
    async def scenario(c, op):
        rows, _ = await _logs(c, "pa-revoked-a")
        return rows["log-legacy-a"]["changes"]["monthly_salary"]
    assert run(monkeypatch, backend, "enforce", scenario) == MASKED
    assert run(monkeypatch, backend, "off", scenario) == 2400.0


def test_audit_logs_still_needs_platform_admin(monkeypatch, backend, mode):
    async def scenario(c, op):
        for uid in ("acct-a", "owner-a"):
            r = await c.get("/api/audit-logs", headers=hdr(uid))
            assert r.status_code == 403, (uid, r.text)
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════════════ 4. tenant isolation
@pytest.mark.parametrize("uid", ("pa-acct-b", "pa-viewer-b"))
def test_tenant_b_never_receives_tenant_a(monkeypatch, backend, mode, uid):
    async def scenario(c, op):
        rows, body = await _logs(c, uid)
        assert set(rows) == {"log-legacy-b"} and body["total"] == 1
        for value in A_VALUES:
            assert repr(value) not in repr(body)
        salary = rows["log-legacy-b"]["changes"]["monthly_salary"]
        assert salary == (3100.0 if uid == "pa-acct-b" else MASKED)
    run(monkeypatch, backend, mode, scenario)


def test_tenant_a_payroll_holder_never_receives_tenant_b(monkeypatch, backend, mode):
    async def scenario(c, op):
        rows, body = await _logs(c, "pa-acct-a")
        assert "log-legacy-b" not in rows and "3100" not in repr(body)
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════════════ 5. retention class
def test_ai_proposal_inherits_the_retention_class_of_its_record():
    from tests.test_w0_03b2_pending_mapping import (MODEL, SOURCE_AI, SOURCE_OCR, Ctx, SpyDb,
                                                     propose_ok)
    from app.master_data.repository import MasterDataRepository
    classes = {}
    for channel in (SOURCE_AI, SOURCE_OCR):
        spy = SpyDb()
        extra = {"model_and_version": MODEL} if channel == SOURCE_AI else {}
        propose_ok(Ctx(db=spy), repository=MasterDataRepository("tenant-a", db=spy),
                   source_channel=channel, **extra)
        (event,) = spy.collections["audit_events"].inserted
        classes[channel] = (event["retention_class"], event["actor_type"])
    assert classes[SOURCE_AI] == ("R2", "ai")
    assert classes[SOURCE_OCR][0] == "R2"                  # same record -> same class


def test_canon_lines_quoted_in_code_match_flow_040():
    from pathlib import Path
    canon = (Path(__file__).resolve().parents[2] / "docs" / "flows" / "FLOW-040.md").read_text()
    assert ("structured metadata, tool calls, показана чернова, human confirmation и "
            "official action — наследяват R1/R2/R3 според действието") in canon
    assert "банкови сметки, лични номера, заплати и PII се маскират според ролята" in canon
    assert PAYROLL_READ_ACTION == "finance.pay_run.read"
    from app.permissions.catalog import role_actions
    assert {r for r in ("owner", "admin", "accountant", "site_manager", "LEGACY_VIEWER",
                        "LEGACY_TECHNICIAN", "warehouse", "driver")
            if PAYROLL_READ_ACTION in role_actions(r)} == {"owner", "admin", "accountant"}
    assert mask_row({"entity_type": "employee", "changes": {"monthly_salary": 1}}) == \
        {"entity_type": "employee", "changes": {"monthly_salary": MASKED}}
