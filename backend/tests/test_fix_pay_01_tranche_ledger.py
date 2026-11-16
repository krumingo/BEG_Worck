"""
FIX-PAY-01 — decision Р97 (Krum, 16.11.2026): a paid tranche of a crew contract goes
through the single payment ledger.

"The 'Платен' button asks which account (Каса/Банка) and which date, and records the
payment in the single payment register (FLOW-006), protected against repeated requests.
The tranche becomes 'paid' only after that record. The tranche itself is an obligation
(FLOW-028), not a payment."

Canon: CLAUDE.md §2.5, §7, §14; FLOW-006, FLOW-028; R29 (a money write without an
Idempotency-Key is refused); FG-45 (a module-owned payment is not reversed in finance).

``POST /api/contract-payments/{id}/pay-tranche``:
  1. account + date + key -> ONE finance_payments Outflow (amount = tranche amount,
     counterparty = worker, category "Договорно плащане", contract_payment_id + tranche
     index), the tranche paid with ``payment_id``, ONE audit row;
  2. the same key x3 -> one row, the identical response;
  3. the same key + another body -> 409, nothing written;
  4. no key -> 428 IDEMPOTENCY_KEY_REQUIRED, nothing written;
  5. missing account / date, bad date, unknown or foreign-tenant account -> 4xx, nothing written;
  6. tranche already paid -> 400 "Tranche already paid", nothing written;
  7. Viewer / SiteManager / Technician -> 403, nothing written;
  8. tenant B cannot pay tenant A's tranche (404) nor use B's account for A (404);
  9. project P&L contract cost counted exactly once (tranche, not also the ledger row);
 10. the generic finance reversal refuses the row (409 SOURCE_MODULE_REVERSAL_REQUIRED),
     the tranche stays paid over an ACTIVE payment (never paid over a reversed one);
 11. a second key on the same tranche never writes a second Outflow;
 12. a tranche paid before FIX-PAY-01 (no payment_id) is untouched and readable as such.

Runs in PERMISSION_SERVICE_MODE off / shadow / enforce, on mongomock and, when
``W0_03_REAL_MONGO_URL`` names a disposable LOCAL MongoDB, on it as well (databases
``fixtest_pay_*``, dropped afterwards).

    PYTHONPATH=. pytest tests/test_fix_pay_01_tranche_ledger.py -q --noconftest -p no:cacheprovider
"""
import asyncio
import uuid

import pytest

from tests.test_r0_05_pay_run_selected_only import _real_refusal, _token

ORG_A, ORG_B = "ORG-FIXPAY-A", "ORG-FIXPAY-B"
USERS = {
    "owner-a": (ORG_A, "Owner"), "admin-a": (ORG_A, "Admin"), "acct-a": (ORG_A, "Accountant"),
    "viewer-a": (ORG_A, "Viewer"), "site-a": (ORG_A, "SiteManager"), "tech-a": (ORG_A, "Technician"),
    "admin-b": (ORG_B, "Admin"),
}
MODES = ["off", "shadow", "enforce"]
CASH_A, BANK_A, BANK_B = "acc-cash-a", "acc-bank-a", "acc-bank-b"
PRJ_A = "prj-a"
CP_A, CP_B, CP_LEGACY = "cp-a", "cp-b", "cp-legacy"
WATCHED = ("finance_payments", "contract_payments", "audit_events", "audit_logs",
           "audit_idempotency")
URL = "/api/contract-payments/%s/pay-tranche"


@pytest.fixture(params=["mongomock", pytest.param("real", marks=pytest.mark.skipif(
    bool(_real_refusal()), reason=_real_refusal() or "ok"))])
def backend(request):
    return request.param


@pytest.fixture(params=MODES)
def mode(request):
    return request.param


def hdr(uid, key=None):
    """``key=None`` -> a fresh key, a string -> that key, ``False`` -> no key."""
    org, role = USERS[uid]
    h = _token(uid, org, role)
    if key is None:
        key = "auto-" + uuid.uuid4().hex
    if key:
        h["Idempotency-Key"] = key
    return h


class _Dbs:
    def __init__(self, backend):
        tag = uuid.uuid4().hex[:10]
        self.backend, self.client = backend, None
        self.names = ("fixtest_pay_op_" + tag, "fixtest_pay_sys_" + tag)

    async def __aenter__(self):
        if self.backend == "real":
            from motor.motor_asyncio import AsyncIOMotorClient
            from tests.test_w0_03c_real_mongo import REAL_URL
            self.client = AsyncIOMotorClient(REAL_URL, serverSelectionTimeoutMS=5000)
        else:
            from mongomock_motor import AsyncMongoMockClient
            self.client = AsyncMongoMockClient()
        return self.client[self.names[0]], self.client[self.names[1]]

    async def __aexit__(self, *exc):
        if self.backend == "real":
            for name in self.names:
                assert name.startswith("fixtest_pay_")
                await self.client.drop_database(name)
            self.client.close()


def _contract(cp_id, org, amounts, site=PRJ_A, paid=()):
    return {
        "id": cp_id, "org_id": org, "worker_name": "Бригада " + cp_id, "worker_id": None,
        "contract_type": "one_time", "description": "FIX-PAY-01", "total_amount": sum(amounts),
        "site_id": site, "activity_budget_id": None, "status": "active",
        "tranches": [{"amount": a, "due_date": "2026-11-20",
                      "status": "paid" if i in paid else "pending",
                      "paid_date": "2026-10-01" if i in paid else None,
                      "paid_by": "legacy" if i in paid else None, "notes": ""}
                     for i, a in enumerate(amounts)],
        "created_at": "2026-11-01T08:00:00+00:00", "updated_at": "2026-11-01T08:00:00+00:00",
    }


async def _seed(op, sysdb):
    from app.permissions.catalog import LEGACY_ROLE_MAP
    for org in (ORG_A, ORG_B):
        await op.organizations.insert_one({"id": org, "name": "Org " + org})
        await op.subscriptions.insert_one({"id": "sub-" + org, "org_id": org,
                                           "plan_id": "enterprise", "status": "active"})
        await sysdb.tenant_registry.insert_one({"id": org, "legacy_org_id": org,
                                                "status": "active", "database_name": op.name})
    for uid, (org, role) in USERS.items():
        await op.users.insert_one({"id": uid, "org_id": org, "role": role, "is_active": True,
                                   "email": uid + "@fixpay.example", "first_name": uid,
                                   "last_name": "T"})
        await sysdb.tenant_memberships.insert_one({"id": "tm_" + uid, "user_id": uid,
                                                   "tenant_id": org, "status": "active"})
        await sysdb.tenant_role_assignments.insert_one({
            "id": "ra_" + uid, "user_id": uid, "tenant_id": org,
            "role_id": LEGACY_ROLE_MAP[role], "scope_type": "company", "scope_id": None,
            "module": None, "permissions": [], "status": "active", "sync_source": "users.role"})
    for prj_id, org in ((PRJ_A, ORG_A), ("prj-b", ORG_B)):
        await op.projects.insert_one({"id": prj_id, "org_id": org, "code": prj_id,
                                      "name": prj_id, "status": "Active"})
    for acc_id, org, typ in ((CASH_A, ORG_A, "Cash"), (BANK_A, ORG_A, "Bank"),
                             (BANK_B, ORG_B, "Bank")):
        await op.financial_accounts.insert_one({
            "id": acc_id, "org_id": org, "name": acc_id, "type": typ, "currency": "EUR",
            "opening_balance": 1000.0, "active": True})
    await op.contract_payments.insert_one(_contract(CP_A, ORG_A, [400.0, 250.0]))
    await op.contract_payments.insert_one(_contract(CP_B, ORG_B, [90.0], site="prj-b"))
    await op.contract_payments.insert_one(_contract(CP_LEGACY, ORG_A, [70.0, 30.0], paid=(0,)))


def _app(monkeypatch, op, sysdb, mode):
    from fastapi import FastAPI
    import app.db as appdb
    from app.deps import auth as deps_auth, modules as deps_modules
    from app.master_data.deps import ENV_MODE
    from app.permissions import money_input
    from app.routes import finance as r_finance, hr as r_hr
    from app.services import project_pnl
    # LAB-R96 step 3: project_pnl reads labor through labor_cost_reader ->
    # report_normalizer, which binds app.db.db at import (TEST-ONLY integration fix)
    from app.services import report_normalizer
    from app.tenancy import guard, registry, resolver
    from app.utils import audit as u_audit

    monkeypatch.setenv(ENV_MODE, "off")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    for module in (appdb, deps_auth, deps_modules, r_finance, r_hr, project_pnl, u_audit,
                   money_input, report_normalizer):
        monkeypatch.setattr(module, "db", op)
    monkeypatch.setattr(registry, "system_db", sysdb)
    for coll in ("tenant_registry", "tenant_memberships", "tenant_role_assignments"):
        monkeypatch.setattr(registry, coll, sysdb[coll])

    async def _get_db(tenant_id, require_operational=False):
        return op
    monkeypatch.setattr(resolver, "get_tenant_db", _get_db)
    monkeypatch.setattr(guard, "get_tenant_db", _get_db)
    app = FastAPI()
    app.include_router(r_hr.router, prefix="/api")
    app.include_router(r_finance.router, prefix="/api")
    return app


async def _bootstrap_indexes(op):
    from scripts.w0_04_bootstrap_audit_indexes import PLANNED_INDEXES
    for coll, keys, opts in PLANNED_INDEXES:
        await op[coll].create_index(keys, **opts)


def run(monkeypatch, backend, mode, scenario):
    import httpx

    async def go():
        async with _Dbs(backend) as (op, sysdb):
            await _bootstrap_indexes(op)
            await _seed(op, sysdb)
            app = _app(monkeypatch, op, sysdb, mode)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://fixpay01") as c:
                return await scenario(c, op)
    return asyncio.run(go())


async def snap(op, colls=WATCHED):
    import bson
    out = {}
    for coll in colls:
        docs = await op[coll].find({}, {"_id": 0}).to_list(None)
        out[coll] = sorted(bson.BSON.encode({k: d[k] for k in sorted(d)}) for d in docs)
    return out


def body(idx=0, account=CASH_A, date="2026-11-16", **extra):
    return {"tranche_index": idx, "account_id": account, "date": date, **extra}


async def outflows(op, org=ORG_A):
    return await op.finance_payments.find({"org_id": org, "direction": "Outflow"},
                                          {"_id": 0}).to_list(None)


async def tranche(op, cp_id=CP_A, idx=0):
    doc = await op.contract_payments.find_one({"id": cp_id}, {"_id": 0})
    return doc["tranches"][idx], doc


async def pay_audits(op):
    return await op.audit_logs.find({"action": "contract_tranche_paid"}, {"_id": 0}).to_list(None)


# ═════════════════════════════════════════════════════════════════════ 1. the payment
def test_01_pay_writes_one_ledger_outflow_then_marks_tranche(monkeypatch, backend, mode):
    async def scenario(c, op):
        r = await c.post(URL % CP_A, json=body(0, CASH_A, notes="аванс"), headers=hdr("acct-a", "k-1"))
        assert r.status_code == 200, r.text
        rows = await outflows(op)
        assert len(rows) == 1, rows
        row = rows[0]
        assert row["amount"] == 400.0 and row["date"] == "2026-11-16"
        assert row["method"] == "Cash" and row["account_id"] == CASH_A
        assert row["counterparty_name"] == "Бригада cp-a"
        assert row["category"] == "Договорно плащане"
        assert row["contract_payment_id"] == CP_A and row["tranche_index"] == 0
        assert row["project_id"] == PRJ_A and row["org_id"] == ORG_A
        assert "status" not in row                                  # an active payment
        tr, doc = await tranche(op)
        assert tr["status"] == "paid" and tr["payment_id"] == row["id"]
        assert tr["paid_date"] == "2026-11-16" and tr["paid_by"] == "acct-a"
        assert tr["account_id"] == CASH_A and tr["notes"] == "аванс"
        assert doc["status"] == "active"
        assert r.json()["tranches"][0]["payment_id"] == row["id"]
        audits = await pay_audits(op)
        assert len(audits) == 1 and audits[0]["entity_id"] == row["id"]
        assert audits[0]["changes"]["contract_payment_id"] == CP_A

        # the second tranche from the bank -> BankTransfer, the contract completed
        r2 = await c.post(URL % CP_A, json=body(1, BANK_A, "2026-11-17"), headers=hdr("admin-a"))
        assert r2.status_code == 200, r2.text
        rows = await outflows(op)
        assert len(rows) == 2
        bank = next(x for x in rows if x["tranche_index"] == 1)
        assert bank["method"] == "BankTransfer" and bank["amount"] == 250.0
        assert r2.json()["status"] == "completed"
        assert len(await pay_audits(op)) == 2
    run(monkeypatch, backend, mode, scenario)


# ═════════════════════════════════════════════════════════════════════ 2./3. the key
def test_02_same_key_replays_and_other_body_is_409(monkeypatch, backend, mode):
    async def scenario(c, op):
        r1 = await c.post(URL % CP_A, json=body(), headers=hdr("acct-a", "k-same"))
        assert r1.status_code == 200, r1.text
        after_first = await snap(op)
        for _ in range(2):                                          # x3 in total
            r = await c.post(URL % CP_A, json=body(), headers=hdr("acct-a", "k-same"))
            assert r.status_code == 200 and r.json() == r1.json(), r.text
        assert await snap(op) == after_first                        # nothing written again
        assert len(await outflows(op)) == 1 and len(await pay_audits(op)) == 1
        # the same key, another body -> 409, nothing written
        r3 = await c.post(URL % CP_A, json=body(0, BANK_A), headers=hdr("acct-a", "k-same"))
        assert r3.status_code == 409, r3.text
        assert await snap(op) == after_first
    run(monkeypatch, backend, mode, scenario)


# ═════════════════════════════════════════════════════════════════════ 4. no key
def test_03_no_key_is_428_and_writes_nothing(monkeypatch, backend, mode):
    async def scenario(c, op):
        before = await snap(op)
        for key in (False, "", "   "):
            r = await c.post(URL % CP_A, json=body(), headers=hdr("acct-a", key))
            assert r.status_code == 428, (repr(key), r.text)
            assert r.json()["detail"]["error_code"] == "IDEMPOTENCY_KEY_REQUIRED"
        assert await snap(op) == before
        assert (await tranche(op))[0]["status"] == "pending"
    run(monkeypatch, backend, mode, scenario)


# ═════════════════════════════════════════════════════════════════════ 5. account / date
@pytest.mark.parametrize("bad, status", [
    ({"account_id": None}, 422), ({"account_id": ""}, 422), ({"date": None}, 422),
    ({"date": "16.11.2026"}, 422), ({"date": "2026-02-30"}, 422), ({"date": 20261116}, 422),
    ({"account_id": "acc-missing"}, 404), ({"account_id": BANK_B}, 404),   # B's account
])
def test_04_account_and_date_required(monkeypatch, backend, mode, bad, status):
    async def scenario(c, op):
        before = await snap(op)
        b = body()
        b.update(bad)
        b = {k: v for k, v in b.items() if v is not None}
        r = await c.post(URL % CP_A, json=b, headers=hdr("acct-a"))
        assert r.status_code == status, r.text
        assert await snap(op) == before                             # not even a key record
    run(monkeypatch, backend, mode, scenario)


# ═════════════════════════════════════════════════════════════════════ 6. already paid
def test_05_already_paid_is_400(monkeypatch, backend, mode):
    async def scenario(c, op):
        r = await c.post(URL % CP_A, json=body(), headers=hdr("acct-a"))
        assert r.status_code == 200, r.text
        snap0 = await snap(op, ("finance_payments", "contract_payments", "audit_logs"))
        for who, acc in (("acct-a", CASH_A), ("owner-a", BANK_A)):   # another key, any body
            r2 = await c.post(URL % CP_A, json=body(0, acc), headers=hdr(who))
            assert r2.status_code == 400 and r2.json()["detail"] == "Tranche already paid", r2.text
        assert await snap(op, ("finance_payments", "contract_payments", "audit_logs")) == snap0
    run(monkeypatch, backend, mode, scenario)


# ═════════════════════════════════════════════════════════════════════ 7. forbidden
@pytest.mark.parametrize("who", ["viewer-a", "site-a", "tech-a"])
def test_06_forbidden_roles_are_403(monkeypatch, backend, mode, who):
    async def scenario(c, op):
        before = await snap(op)
        for key in (None, False):
            r = await c.post(URL % CP_A, json=body(), headers=hdr(who, key))
            assert r.status_code == 403, r.text
        assert await snap(op) == before and await outflows(op) == []
    run(monkeypatch, backend, mode, scenario)


# ═════════════════════════════════════════════════════════════════════ 8. tenants
def test_07_tenant_isolation(monkeypatch, backend, mode):
    async def scenario(c, op):
        before = await snap(op)
        r = await c.post(URL % CP_A, json=body(0, BANK_B), headers=hdr("admin-b"))
        assert r.status_code == 404, r.text                         # A's contract is not B's
        r = await c.post(URL % CP_B, json=body(0, CASH_A), headers=hdr("admin-a"))
        assert r.status_code == 404, r.text                         # B's contract is not A's
        r = await c.post(URL % CP_B, json=body(0, CASH_A), headers=hdr("admin-b"))
        assert r.status_code == 404, r.text                         # A's account for B
        assert await snap(op) == before
        # B pays its own tranche into its own account; A sees nothing of it
        r = await c.post(URL % CP_B, json=body(0, BANK_B), headers=hdr("admin-b", "k-shared"))
        assert r.status_code == 200, r.text
        r = await c.post(URL % CP_A, json=body(0, CASH_A), headers=hdr("admin-a", "k-shared"))
        assert r.status_code == 200, r.text                          # keys are per tenant/user
        assert [x["account_id"] for x in await outflows(op, ORG_B)] == [BANK_B]
        assert [x["account_id"] for x in await outflows(op, ORG_A)] == [CASH_A]
    run(monkeypatch, backend, mode, scenario)


# ═════════════════════════════════════════════════════════════════════ 9. P&L once
def test_08_project_pnl_counts_contract_cost_once(monkeypatch, backend, mode):
    async def scenario(c, op):
        from app.services.project_pnl import compute_project_pnl
        p0 = (await compute_project_pnl(ORG_A, PRJ_A))["expense"]
        r = await c.post(URL % CP_A, json=body(0, CASH_A), headers=hdr("acct-a"))
        assert r.status_code == 200, r.text
        p1 = (await compute_project_pnl(ORG_A, PRJ_A))["expense"]
        # cp-a 400 paid now; cp-legacy (same project) 70 paid before FIX-PAY-01
        assert p1["contract_cost"] - p0["contract_cost"] == 400.0
        assert p1["other_cost"] == p0["other_cost"]                 # the ledger row is not "Други"
        assert round(p1["total_expense"] - p0["total_expense"], 2) == 400.0
    run(monkeypatch, backend, mode, scenario)


# ═════════════════════════════════════════════════════════════════════ 10. correction
def test_09_finance_reversal_refused_tranche_never_paid_over_reversed(monkeypatch, backend, mode):
    async def scenario(c, op):
        r = await c.post(URL % CP_A, json=body(), headers=hdr("acct-a"))
        assert r.status_code == 200, r.text
        pid = r.json()["tranches"][0]["payment_id"]
        before = await snap(op, ("finance_payments", "contract_payments", "audit_events"))
        rr = await c.request("DELETE", "/api/finance/payments/" + pid,
                             json={"reason": "грешка"}, headers=hdr("acct-a"))
        assert rr.status_code == 409, rr.text
        d = rr.json()["detail"]
        assert d["error_code"] == "SOURCE_MODULE_REVERSAL_REQUIRED"
        assert d["source_module"] == "contract_payment"
        assert await snap(op, ("finance_payments", "contract_payments", "audit_events")) == before
        row = await op.finance_payments.find_one({"id": pid}, {"_id": 0})
        assert "status" not in row                                  # still active, not deleted
        assert (await tranche(op))[0]["status"] == "paid"
    run(monkeypatch, backend, mode, scenario)


# ═════════════════════════════════════════════════════════════════════ 11. two keys
def test_10_two_keys_one_tranche_one_outflow(monkeypatch, backend, mode):
    """Even if a request with another key reads the tranche as pending (a race), the ledger
    row id belongs to the tranche: the second insert is refused, one Outflow only."""
    async def scenario(c, op):
        r = await c.post(URL % CP_A, json=body(), headers=hdr("acct-a", "k-first"))
        assert r.status_code == 200, r.text
        # simulate the race: the tranche read as pending by a second request
        await op.contract_payments.update_one(
            {"id": CP_A}, {"$set": {"tranches.0.status": "pending"}})
        r2 = await c.post(URL % CP_A, json=body(0, BANK_A), headers=hdr("acct-a", "k-second"))
        assert r2.status_code == 409, r2.text
        assert r2.json()["detail"]["error_code"] == "TRANCHE_PAYMENT_IN_PROGRESS"
        assert len(await outflows(op)) == 1
        assert len(await pay_audits(op)) == 1
    run(monkeypatch, backend, mode, scenario)


# ═════════════════════════════════════════════════════════════════════ 12. legacy data
def test_11_legacy_paid_tranche_untouched(monkeypatch, backend, mode):
    async def scenario(c, op):
        tr0, _ = await tranche(op, CP_LEGACY, 0)
        assert tr0["status"] == "paid" and "payment_id" not in tr0    # paid without a ledger row
        r = await c.post(URL % CP_LEGACY, json=body(0), headers=hdr("acct-a"))
        assert r.status_code == 400, r.text                         # never re-paid, no backfill
        assert await outflows(op) == []
        r = await c.post(URL % CP_LEGACY, json=body(1), headers=hdr("acct-a"))
        assert r.status_code == 200, r.text
        legacy, new = r.json()["tranches"]
        assert "payment_id" not in legacy and legacy["paid_date"] == "2026-10-01"
        assert new["payment_id"] and r.json()["status"] == "completed"
    run(monkeypatch, backend, mode, scenario)
