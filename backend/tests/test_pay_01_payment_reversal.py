"""
PAY-01 — payments are reversed, never deleted (decision R23, Krum 06.11.2026; FG-34).

Package: ``docs/architecture/tasks/PAY-01_PAYMENT_REVERSAL_NO_HARD_DELETE.md``.
Canon: CLAUDE.md §2.9, §7; FLOW-006 §Корекции; FLOW-043 D-03, D-08.

  1. DELETE payment → the original stays (status reversed), a reversal row exists
     (opposite direction, same amount/account), a canonical AuditEvent, every report
     shows net 0; a second DELETE → 409 (new key or no key);
  2. the same Idempotency-Key replays the first result, nothing written twice;
  3. no reason → 400, nothing written;
  4. cancelling an invoice allocation deletes nothing, invoice/payment balances are
     recomputed from active rows (full and partial);
  5. Viewer / SiteManager / Technician → 403, nothing written;
  6. used invoice → 409, unused draft still removable;
  7. used account (also by a reversed payment) → 409, unused still removable;
  8. both legs of an own-account transfer are reversed together;
  9. project P&L "other" cost of a reversed expense → 0;
 10. a reversed original whose reversal row is missing (crash) is repaired by the next
     request, still one reversal row;
 11. tenant B cannot reverse tenant A's payment (404, nothing changed);
 12. a reversed payment cannot be allocated → 409.

Every scenario runs in PERMISSION_SERVICE_MODE off / shadow / enforce, on mongomock and,
when ``W0_03_REAL_MONGO_URL`` names a disposable LOCAL MongoDB, on it as well.

    PYTHONPATH=. pytest tests/test_pay_01_payment_reversal.py -q --noconftest -p no:cacheprovider
"""
import asyncio
import uuid

import pytest

from tests.test_r0_05_pay_run_selected_only import _real_refusal, _token

ORG_A, ORG_B = "ORG-PAY01-A", "ORG-PAY01-B"
USERS = {
    "owner-a": (ORG_A, "Owner"), "admin-a": (ORG_A, "Admin"), "acct-a": (ORG_A, "Accountant"),
    "viewer-a": (ORG_A, "Viewer"), "site-a": (ORG_A, "SiteManager"), "tech-a": (ORG_A, "Technician"),
    "admin-b": (ORG_B, "Admin"),
}
MODES = ["off", "shadow", "enforce"]
CASH_A, BANK_A, BANK_B = "acc-cash-a", "acc-bank-a", "acc-bank-b"
OPENING = {CASH_A: 1000.0, BANK_A: 5000.0, BANK_B: 700.0}
MONEY = ("finance_payments", "payment_allocations", "invoices", "financial_accounts",
         "audit_events", "audit_logs", "audit_idempotency")


@pytest.fixture(params=["mongomock", pytest.param("real", marks=pytest.mark.skipif(
    bool(_real_refusal()), reason=_real_refusal() or "ok"))])
def backend(request):
    return request.param


@pytest.fixture(params=MODES)
def mode(request):
    return request.param


def hdr(uid, key=None):
    """Auth headers. R29: every money write needs an Idempotency-Key — ``key=None`` sends a
    fresh one, a string sends that key, ``key=False`` sends none (the 428 cases)."""
    org, role = USERS[uid]
    h = _token(uid, org, role)
    if key is None:
        key = "auto-" + uuid.uuid4().hex
    if key:
        h["Idempotency-Key"] = key
    return h


# ═══════════════════════════════════════════════════════════════════ harness
class _Dbs:
    def __init__(self, backend):
        tag = uuid.uuid4().hex[:10]
        self.backend, self.client = backend, None
        self.names = ("pay01_op_" + tag, "pay01_sys_" + tag)

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
                await self.client.drop_database(name)
            self.client.close()


async def _seed(op, sysdb):
    from app.permissions.catalog import LEGACY_ROLE_MAP
    for org in (ORG_A, ORG_B):
        await op.organizations.insert_one({"id": org, "name": "Org " + org})
        await op.subscriptions.insert_one({"id": "sub-" + org, "org_id": org, "plan_id": "enterprise",
                                           "status": "active"})
        await sysdb.tenant_registry.insert_one({"id": org, "legacy_org_id": org, "status": "active",
                                                "database_name": op.name})
    for uid, (org, role) in USERS.items():
        await op.users.insert_one({"id": uid, "org_id": org, "role": role, "is_active": True,
                                   "email": uid + "@pay01.example", "first_name": uid, "last_name": "T"})
        await sysdb.tenant_memberships.insert_one({"id": "tm_" + uid, "user_id": uid, "tenant_id": org,
                                                   "status": "active"})
        await sysdb.tenant_role_assignments.insert_one({
            "id": "ra_" + uid, "user_id": uid, "tenant_id": org, "role_id": LEGACY_ROLE_MAP[role],
            "scope_type": "company", "scope_id": None, "module": None, "permissions": [],
            "status": "active", "sync_source": "users.role"})
    # FG-50: money writes may only name a project of their own tenant
    for prj_id, org in (("prj-1", ORG_A), ("prj-a", ORG_A), ("prj-b", ORG_B)):
        await op.projects.insert_one({"id": prj_id, "org_id": org, "code": prj_id, "name": prj_id,
                                      "status": "Active"})
    for acc_id, org, typ in ((CASH_A, ORG_A, "Cash"), (BANK_A, ORG_A, "Bank"), (BANK_B, ORG_B, "Bank")):
        await op.financial_accounts.insert_one({
            "id": acc_id, "org_id": org, "name": acc_id, "type": typ, "currency": "EUR",
            "opening_balance": OPENING[acc_id], "active": True, "is_default": typ == "Bank"})
    for inv_id, status in (("inv-a1", "Sent"), ("inv-a2", "Sent"), ("inv-draft", "Draft")):
        await op.invoices.insert_one({
            "id": inv_id, "org_id": ORG_A, "invoice_no": inv_id, "direction": "Issued", "kind": "Invoice",
            "status": status, "issue_date": "2026-11-01", "due_date": "2099-12-31", "currency": "EUR",
            "lines": [], "subtotal": 100.0, "vat_percent": 0, "vat_amount": 0, "total": 100.0,
            "paid_amount": 0, "remaining_amount": 100.0, "counterparty_name": "Клиент"})


def _app(monkeypatch, op, sysdb, mode):
    from fastapi import FastAPI
    import app.db as appdb
    from app.deps import auth as deps_auth, modules as deps_modules
    from app.master_data.deps import ENV_MODE
    from app.routes import finance as r_finance
    from app.services import project_pnl
    from app.tenancy import guard, registry, resolver
    from app.utils import audit as u_audit

    monkeypatch.setenv(ENV_MODE, "off")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    # INV-CN-01 FG-572: the invoice cancel / edit routes now take require_money_write, whose
    # legacy data-path guard (enforce) reads the money_write module's db handle
    from app.permissions import money_write as perm_money
    for module in (appdb, deps_auth, deps_modules, r_finance, project_pnl, u_audit, perm_money):
        monkeypatch.setattr(module, "db", op)
    monkeypatch.setattr(registry, "system_db", sysdb)
    for coll in ("tenant_registry", "tenant_memberships", "tenant_role_assignments"):
        monkeypatch.setattr(registry, coll, sysdb[coll])

    async def _get_db(tenant_id, require_operational=False):
        return op
    monkeypatch.setattr(resolver, "get_tenant_db", _get_db)
    monkeypatch.setattr(guard, "get_tenant_db", _get_db)
    app = FastAPI()
    app.include_router(r_finance.router, prefix="/api")
    return app


async def _bootstrap_indexes(op):
    """The W0-04 audit indexes, exactly as the bootstrap creates them (IDEM-IDX-1 itself — the
    index missing at startup — is fixed separately in W0-04-C01; not duplicated here)."""
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
                                         base_url="http://pay01") as c:
                return await scenario(c, op)
    return asyncio.run(go())


async def snap(op, colls=MONEY):
    import bson
    out = {}
    for coll in colls:
        docs = await op[coll].find({}, {"_id": 0}).to_list(None)
        out[coll] = sorted(bson.BSON.encode({k: d[k] for k in sorted(d)}) for d in docs)
    return out


async def pay(c, amount=200.0, direction="Inflow", account=BANK_A, who="acct-a"):
    r = await c.post("/api/finance/payments", headers=hdr(who), json={
        "direction": direction, "amount": amount, "date": "2026-11-05", "method": "BankTransfer",
        "account_id": account, "counterparty_name": "X"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def reverse(c, pid, who="acct-a", key=None, reason="грешно въведено"):
    body = {"reason": reason} if reason is not None else {}
    return await c.request("DELETE", "/api/finance/payments/" + pid, json=body, headers=hdr(who, key))


async def balances(c):
    r = await c.get("/api/finance/accounts", headers=hdr("acct-a"))
    assert r.status_code == 200, r.text
    return {a["id"]: a["current_balance"] for a in r.json()}


async def stats(c):
    r = await c.get("/api/finance/stats", headers=hdr("acct-a"))
    assert r.status_code == 200, r.text
    d = r.json()
    return d["cash_balance"], d["bank_balance"], d["receivables_total"]


async def events(op, action):
    return await op.audit_events.find({"action": action}, {"_id": 0}).to_list(None)


# ═══════════════════════════════════════════════════════════════ 1. reversal
def test_01_delete_payment_reverses_it(monkeypatch, backend, mode):
    async def scenario(c, op):
        stats0 = await stats(c)
        pid = await pay(c, 200.0)
        assert (await balances(c))[BANK_A] == 5200.0
        r = await reverse(c, pid, key="k-01")
        assert r.status_code == 200, r.text
        rev_id = r.json()["reversals"][0]["reversal_payment_id"]

        rows = {p["id"]: p for p in await op.finance_payments.find({}, {"_id": 0}).to_list(None)}
        assert set(rows) == {pid, rev_id}                       # nothing deleted, one reversal
        orig, rev = rows[pid], rows[rev_id]
        assert orig["status"] == "reversed" and orig["reversed_by_payment_id"] == rev_id
        assert orig["reversed_by"] == "acct-a" and orig["reversal_reason"] == "грешно въведено"
        assert orig["amount"] == 200.0 and orig["direction"] == "Inflow"     # original unchanged
        assert rev["status"] == "reversal" and rev["reverses_payment_id"] == pid
        assert rev["direction"] == "Outflow" and rev["amount"] == 200.0 and rev["account_id"] == BANK_A
        assert rev["org_id"] == ORG_A

        ev = await events(op, "finance.payment.reversed")
        assert len(ev) == 1 and ev[0]["entity_id"] == pid and ev[0]["tenant_id"] == ORG_A
        assert ev[0]["actor_id"] == "acct-a" and ev[0]["source_flow"] == "FLOW-006"
        assert ev[0]["reason"] == "грешно въведено" and ev[0]["idempotency_key"] == "k-01"

        # reports: net 0
        assert (await balances(c))[BANK_A] == 5000.0
        assert await stats(c) == stats0
        listed = (await c.get("/api/finance/payments", headers=hdr("acct-a"))).json()
        assert listed == []
        full = (await c.get("/api/finance/payments?include_reversed=true", headers=hdr("acct-a"))).json()
        assert {p["id"] for p in full} == {pid, rev_id}

        # second reversal → 409, nothing written
        before = await snap(op)
        for key in ("k-01b", None):
            r2 = await reverse(c, pid, key=key)
            assert r2.status_code == 409, r2.text
        r3 = await reverse(c, rev_id)                           # the reversal row itself
        assert r3.status_code == 409, r3.text
        after = await snap(op)
        for coll in ("finance_payments", "payment_allocations", "audit_events"):
            assert after[coll] == before[coll], coll
    run(monkeypatch, backend, mode, scenario)


def test_02_same_idempotency_key_replays(monkeypatch, backend, mode):
    async def scenario(c, op):
        pid = await pay(c, 50.0)
        r1 = await reverse(c, pid, key="same-key")
        before = await snap(op)
        r2 = await reverse(c, pid, key="same-key")
        assert r1.status_code == r2.status_code == 200, (r1.text, r2.text)
        assert r1.json() == r2.json()
        assert await snap(op) == before
        assert await op.finance_payments.count_documents({"reverses_payment_id": pid}) == 1
        assert len(await events(op, "finance.payment.reversed")) == 1
        # the same key for ANOTHER request → 409
        other = await pay(c, 10.0)
        r3 = await reverse(c, other, key="same-key")
        assert r3.status_code == 409, r3.text
        assert (await op.finance_payments.find_one({"id": other}, {"_id": 0})).get("status") is None
    run(monkeypatch, backend, mode, scenario)


def test_03_reason_is_required(monkeypatch, backend, mode):
    async def scenario(c, op):
        pid = await pay(c, 50.0)
        before = await snap(op)
        for reason in (None, "", "   "):
            r = await reverse(c, pid, reason=reason, key="k3")
            assert r.status_code == 400, r.text
            assert r.json()["detail"]["error_code"] == "REASON_REQUIRED"
        assert await snap(op) == before
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════ 4. invoice allocations
async def quick_pay(c, inv, amount):
    r = await c.post("/api/finance/invoices/%s/payments" % inv, headers=hdr("acct-a"), json={
        "amount": amount, "method": "BankTransfer", "account_id": BANK_A, "date": "2026-11-05"})
    assert r.status_code == 201, r.text
    return r.json()


def test_04_cancel_allocation_keeps_rows_and_balances(monkeypatch, backend, mode):
    async def scenario(c, op):
        p1 = await quick_pay(c, "inv-a1", 60.0)
        p2 = await quick_pay(c, "inv-a1", 40.0)
        inv = await op.invoices.find_one({"id": "inv-a1"})
        assert inv["status"] == "Paid" and inv["remaining_amount"] == 0
        n_pay = await op.finance_payments.count_documents({})
        n_alloc = await op.payment_allocations.count_documents({})

        r = await c.request("DELETE", "/api/finance/invoices/inv-a1/payments/" + p1["allocation_id"],
                            json={"reason": "върнато"}, headers=hdr("acct-a", "k4"))
        assert r.status_code == 200, r.text
        assert await op.finance_payments.count_documents({}) == n_pay + 1   # + reversal row
        assert await op.payment_allocations.count_documents({}) == n_alloc  # nothing deleted
        alloc = await op.payment_allocations.find_one({"id": p1["allocation_id"]})
        assert alloc["status"] == "cancelled" and alloc["cancel_reason"] == "върнато"
        orig = await op.finance_payments.find_one({"id": p1["payment_id"]})
        assert orig["status"] == "reversed"
        inv = await op.invoices.find_one({"id": "inv-a1"})
        assert (inv["paid_amount"], inv["remaining_amount"], inv["status"]) == (40.0, 60.0, "PartiallyPaid")
        listed = (await c.get("/api/finance/invoices/inv-a1/payments", headers=hdr("acct-a"))).json()
        assert [x["id"] for x in listed] == [p2["allocation_id"]]
        got = (await c.get("/api/finance/invoices/inv-a1", headers=hdr("acct-a"))).json()
        assert [a["id"] for a in got["allocations"]] == [p2["allocation_id"]]
        assert (await balances(c))[BANK_A] == 5040.0
        assert {e["entity_id"] for e in await events(op, "finance.allocation.cancelled")} == {p1["allocation_id"]}
        assert {e["entity_id"] for e in await events(op, "finance.payment.reversed")} == {p1["payment_id"]}

        # again → 409, nothing written
        before = await snap(op)
        r2 = await c.request("DELETE", "/api/finance/invoices/inv-a1/payments/" + p1["allocation_id"],
                             json={"reason": "пак"}, headers=hdr("acct-a"))
        assert r2.status_code == 409, r2.text
        assert (await snap(op))["finance_payments"] == before["finance_payments"]
        assert (await snap(op))["payment_allocations"] == before["payment_allocations"]

        # the second one too → invoice back to Sent, nothing paid
        r3 = await c.request("DELETE", "/api/finance/invoices/inv-a1/payments/" + p2["allocation_id"],
                             json={"reason": "върнато"}, headers=hdr("acct-a"))
        assert r3.status_code == 200, r3.text
        inv = await op.invoices.find_one({"id": "inv-a1"})
        assert (inv["paid_amount"], inv["remaining_amount"], inv["status"]) == (0, 100.0, "Sent")
        assert (await balances(c))[BANK_A] == 5000.0
        # INV-CN-01 / Р49.2 (Krum 08.11.2026): a SENT invoice is no longer cancelled — even
        # with no active allocation the correction is a credit note (409 USE_CREDIT_NOTE)
        r4 = await c.post("/api/finance/invoices/inv-a1/cancel", headers=hdr("acct-a"),
                          json={"reason": "върнато"})
        assert r4.status_code == 409, r4.text
        assert r4.json()["detail"]["error_code"] == "USE_CREDIT_NOTE"
    run(monkeypatch, backend, mode, scenario)


def test_04b_standalone_payment_allocated_then_cancelled(monkeypatch, backend, mode):
    async def scenario(c, op):
        pid = await pay(c, 100.0)
        r = await c.post("/api/finance/payments/%s/allocate" % pid, headers=hdr("acct-a"),
                         json={"allocations": [{"invoice_id": "inv-a2", "amount": 30.0}]})
        assert r.status_code == 200, r.text
        alloc_id = r.json()["allocations"][0]["id"]
        rd = await reverse(c, pid)
        assert rd.status_code == 400, rd.text                         # unchanged rule
        r = await c.request("DELETE", "/api/finance/invoices/inv-a2/payments/" + alloc_id,
                            json={"reason": "грешна фактура"}, headers=hdr("acct-a"))
        assert r.status_code == 200, r.text
        got = (await c.get("/api/finance/payments/" + pid, headers=hdr("acct-a"))).json()
        assert got["allocations"] == [] and got["status"] == "reversed"
        assert (await op.invoices.find_one({"id": "inv-a2"}))["remaining_amount"] == 100.0
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════════ 5. forbidden
@pytest.mark.parametrize("who", ["viewer-a", "site-a", "tech-a"])
def test_05_non_finance_roles_get_403(monkeypatch, backend, mode, who):
    async def scenario(c, op):
        pid = await pay(c, 70.0)
        q = await quick_pay(c, "inv-a1", 20.0)
        before = await snap(op)
        r1 = await reverse(c, pid, who=who, key="k5")
        r2 = await c.request("DELETE", "/api/finance/invoices/inv-a1/payments/" + q["allocation_id"],
                             json={"reason": "x"}, headers=hdr(who, "k5b"))
        r3 = await c.request("DELETE", "/api/finance/invoices/inv-draft", headers=hdr(who))
        r4 = await c.request("DELETE", "/api/finance/accounts/" + CASH_A, headers=hdr(who))
        assert [r.status_code for r in (r1, r2, r3, r4)] == [403] * 4
        assert await snap(op) == before
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════ 6–7. used invoice / account
def test_06_used_invoice_cannot_be_deleted(monkeypatch, backend, mode):
    async def scenario(c, op):
        r = await c.delete("/api/finance/invoices/inv-a1", headers=hdr("acct-a"))   # Sent
        assert r.status_code == 409, r.text
        await op.invoices.insert_one({"id": "inv-draft2", "org_id": ORG_A, "invoice_no": "d2",
                                      "direction": "Issued", "status": "Draft", "total": 10.0})
        pid = await pay(c, 10.0)
        await op.payment_allocations.insert_one({"id": "al-d2", "org_id": ORG_A, "payment_id": pid,
                                                 "invoice_id": "inv-draft2", "amount_allocated": 10.0,
                                                 "status": "cancelled"})
        r = await c.delete("/api/finance/invoices/inv-draft2", headers=hdr("acct-a"))
        assert r.status_code == 409, r.text
        assert await op.invoices.find_one({"id": "inv-draft2"})
        # INV-CN-01 / Р49 + CLAUDE.md §2.9: a draft that carries a number is never deleted …
        r = await c.delete("/api/finance/invoices/inv-draft", headers=hdr("acct-a"))
        assert r.status_code == 409, r.text
        # … an unused draft without a number (Р49.1: numbered only at issue) still is
        await op.invoices.insert_one({"id": "inv-draft3", "org_id": ORG_A, "invoice_no": None,
                                      "direction": "Issued", "status": "Draft", "total": 10.0})
        r = await c.delete("/api/finance/invoices/inv-draft3", headers=hdr("acct-a"))   # unused draft
        assert r.status_code == 200, r.text
    run(monkeypatch, backend, mode, scenario)


def test_07_used_account_cannot_be_deleted(monkeypatch, backend, mode):
    async def scenario(c, op):
        pid = await pay(c, 10.0)
        assert (await reverse(c, pid)).status_code == 200
        r = await c.delete("/api/finance/accounts/" + BANK_A, headers=hdr("acct-a"))
        assert r.status_code == 409, r.text                     # used — even if reversed
        assert await op.financial_accounts.find_one({"id": BANK_A})
        await op.financial_accounts.insert_one({"id": "acc-unused", "org_id": ORG_A, "name": "u",
                                                "type": "Bank", "opening_balance": 0})
        r = await c.delete("/api/finance/accounts/acc-unused", headers=hdr("acct-a"))
        assert r.status_code == 200, r.text
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════ 8–12. edge cases
def test_08_transfer_reversed_as_a_pair(monkeypatch, backend, mode):
    async def scenario(c, op):
        r = await c.post("/api/finance/transfers", headers=hdr("acct-a"), json={
            "from_account_id": BANK_A, "to_account_id": CASH_A, "amount": 300})
        assert r.status_code == 201, r.text
        assert await balances(c) == {CASH_A: 1300.0, BANK_A: 4700.0}
        leg = await op.finance_payments.find_one({"transfer_id": r.json()["transfer_id"], "direction": "Inflow"})
        rr = await reverse(c, leg["id"])
        assert rr.status_code == 200, rr.text
        assert len(rr.json()["reversals"]) == 2
        assert await balances(c) == {CASH_A: 1000.0, BANK_A: 5000.0}
        assert await op.finance_payments.count_documents({}) == 4
    run(monkeypatch, backend, mode, scenario)


def test_09_project_pnl_other_cost_nets_to_zero(monkeypatch, backend, mode):
    async def scenario(c, op):
        from app.services.project_pnl import compute_project_pnl
        r = await c.post("/api/finance/other-expense", headers=hdr("acct-a"), json={
            "project_id": "prj-a", "amount": 25, "method": "Cash"})
        assert r.status_code == 201, r.text

        before = await compute_project_pnl(ORG_A, "prj-a")
        assert before["expense"]["other_cost"] == 25.0
        assert (await reverse(c, r.json()["id"])).status_code == 200
        after = await compute_project_pnl(ORG_A, "prj-a")
        assert after["expense"]["other_cost"] == 0
        assert round(before["expense"]["total_expense"] - after["expense"]["total_expense"], 2) == 25.0
        assert (await balances(c))[CASH_A] == 1000.0
    run(monkeypatch, backend, mode, scenario)


def test_10_crash_between_writes_is_repaired(monkeypatch, backend, mode):
    async def scenario(c, op):
        from app.routes.finance import _reversal_id
        pid = await pay(c, 80.0)
        # state left by a crash after the conditional write, before the reversal row
        await op.finance_payments.update_one({"id": pid}, {"$set": {
            "status": "reversed", "reversed_by_payment_id": _reversal_id(pid), "reversal_reason": "crash"}})
        r = await reverse(c, pid)
        assert r.status_code == 409, r.text
        rows = await op.finance_payments.find({"reverses_payment_id": pid}).to_list(None)
        assert len(rows) == 1 and rows[0]["direction"] == "Outflow"
        await reverse(c, pid)
        assert await op.finance_payments.count_documents({"reverses_payment_id": pid}) == 1
        assert (await balances(c))[BANK_A] == 5000.0
    run(monkeypatch, backend, mode, scenario)


def test_11_other_tenant_cannot_reverse(monkeypatch, backend, mode):
    async def scenario(c, op):
        pid = await pay(c, 90.0)
        before = await snap(op)
        r = await reverse(c, pid, who="admin-b", key="kb")
        assert r.status_code == 404, r.text
        after = await snap(op)
        assert after["finance_payments"] == before["finance_payments"]
        assert after["audit_events"] == before["audit_events"]
    run(monkeypatch, backend, mode, scenario)


def test_12_reversed_payment_cannot_be_allocated(monkeypatch, backend, mode):
    async def scenario(c, op):
        pid = await pay(c, 90.0)
        assert (await reverse(c, pid)).status_code == 200
        business = tuple(c_ for c_ in MONEY if c_ != "audit_idempotency")
        before = await snap(op, business)
        r = await c.post("/api/finance/payments/%s/allocate" % pid, headers=hdr("acct-a", "k-12"),
                         json={"allocations": [{"invoice_id": "inv-a2", "amount": 10.0}]})
        assert r.status_code == 409, r.text
        assert await snap(op, business) == before
        # R29: the refused attempt is kept as a FAILED key (W0-04), never as a replayable success
        rec = await op.audit_idempotency.find_one({"key": "k-12"}, {"_id": 0})
        assert rec["status"] == "failed" and rec["action"] == "finance.payment.allocate"
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════ static: no hard delete
def test_13_no_hard_delete_of_payments_or_allocations():
    import re
    from pathlib import Path
    app_dir = Path(__file__).resolve().parent.parent / "app"
    bad = []
    for f in app_dir.rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        for m in re.finditer(r"(finance_payments|payment_allocations)\s*\.\s*(delete_one|delete_many|"
                             r"find_one_and_delete)", text):
            bad.append("%s:%d" % (f.relative_to(app_dir), text[:m.start()].count("\n") + 1))
    assert bad == []
