"""
CP-01 — counterparties: verified IBAN before payment, never deleted, hidden ЕГН, rights, audit.

Package: docs/architecture/tasks/CP-01_COUNTERPARTY_IBAN_EGN_NO_DELETE.md (branch
claude/happy-meitner-bmcnel @ e96cde8). Decision R48 (Krum, 08.11.2026). Oracle Q003.
Canon: FLOW-010 §3.3/§8/§12, FLOW-006, FLOW-025 L146/L187, FLOW-032 L105/L109-112,
FLOW-040 §9, CLAUDE.md §2, §8, §14.

Red on main cd03324 (proved before the fix, see docs/evidence/CP-01):
  * a payment to an unverified / changed IBAN is executed;
  * DELETE of a counterparty / client / company / person deletes or soft-deletes it;
  * Viewer / SiteManager create and edit clients, companies, persons, subcontractors and
    change the client of a project;
  * a Viewer reads the full ЕГН.

Every scenario runs in PERMISSION_SERVICE_MODE = BANK_ACCOUNT_GUARD_MODE = off / shadow /
enforce, on mongomock and on a disposable LOCAL MongoDB replica set (W0_03_REAL_MONGO_URL).

    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' \\
        PYTHONPATH=. pytest tests/test_cp_01_counterparty_iban_egn.py -q --noconftest -p no:cacheprovider
"""
import asyncio
import json
import uuid

import pytest

from tests.test_r0_05_pay_run_selected_only import _real_refusal, _token

ORG_A, ORG_B = "ORG-CP01-A", "ORG-CP01-B"
USERS = {
    "owner-a": (ORG_A, "Owner"), "admin-a": (ORG_A, "Admin"), "acct-a": (ORG_A, "Accountant"),
    "acct2-a": (ORG_A, "Accountant"), "viewer-a": (ORG_A, "Viewer"),
    "site-a": (ORG_A, "SiteManager"), "tech-a": (ORG_A, "Technician"),
    "admin-b": (ORG_B, "Admin"), "owner-b": (ORG_B, "Owner"),
}
MODES = ["off", "shadow", "enforce"]
BANK_A, CASH_A = "acc-bank-a", "acc-cash-a"
EGN = "8001011234"           # synthetic 10-digit ЕГН of a test person
EGN_MASKED = "******1234"


def make_iban(bban: str) -> str:
    """A BG IBAN with correct ISO 13616 check digits for the given 18-char BBAN."""
    rearranged = bban + "BG00"
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    check = 98 - int(digits) % 97
    return "BG%02d%s" % (check, bban)


IBAN_OLD = make_iban("UNCR70001522123456")
IBAN_NEW = make_iban("STSA93000012345678")
IBAN_OTHER = make_iban("BPBI79401011111111")


@pytest.fixture(params=["mongomock", pytest.param("real", marks=pytest.mark.skipif(
    bool(_real_refusal()), reason=_real_refusal() or "ok"))])
def backend(request):
    return request.param


@pytest.fixture(params=MODES)
def mode(request):
    return request.param


def hdr(uid, key=None):
    """``key=None`` → a fresh Idempotency-Key, a string → that key, ``False`` → none."""
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
        self.names = ("cp01_op_" + tag, "cp01_sys_" + tag)

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
                                   "email": uid + "@cp01.example", "first_name": uid, "last_name": "T"})
        await sysdb.tenant_memberships.insert_one({"id": "tm_" + uid, "user_id": uid, "tenant_id": org,
                                                   "status": "active"})
        await sysdb.tenant_role_assignments.insert_one({
            "id": "ra_" + uid, "user_id": uid, "tenant_id": org, "role_id": LEGACY_ROLE_MAP[role],
            "scope_type": "company", "scope_id": None, "module": None, "permissions": [],
            "status": "active", "sync_source": "users.role"})
    for acc_id, typ in ((BANK_A, "Bank"), (CASH_A, "Cash")):
        await op.financial_accounts.insert_one({
            "id": acc_id, "org_id": ORG_A, "name": acc_id, "type": typ, "account_type": typ,
            "currency": "EUR", "opening_balance": 10000.0, "active": True, "is_default": typ == "Bank"})
    await op.financial_accounts.insert_one({"id": "acc-bank-b", "org_id": ORG_B, "name": "b", "type": "Bank",
                                            "currency": "EUR", "opening_balance": 0, "active": True,
                                            "is_default": True})
    # counterparties: cp1 used (an invoice), cp2 unused
    for cp_id, eik in (("cp1", "111111111"), ("cp2", "222222222")):
        await op.counterparties.insert_one({"id": cp_id, "org_id": ORG_A, "name": "Доставчик " + cp_id,
                                            "type": "supplier", "eik": eik, "active": True})
    await op.counterparties.insert_one({"id": "cp-b", "org_id": ORG_B, "name": "B", "type": "supplier",
                                        "eik": "999999999", "active": True})
    await op.invoices.insert_one({
        "id": "inv-r1", "org_id": ORG_A, "invoice_no": "R-1", "direction": "Received", "kind": "Invoice",
        "status": "Sent", "issue_date": "2026-11-01", "due_date": "2099-12-31", "currency": "EUR",
        "lines": [], "subtotal": 1000.0, "vat_percent": 0, "vat_amount": 0, "total": 1000.0,
        "paid_amount": 0, "remaining_amount": 1000.0, "counterparty_name": "Доставчик cp1",
        "counterparty_eik": "111111111", "supplier_counterparty_id": "cp1"})
    await op.clients.insert_one({"id": "cl1", "org_id": ORG_A, "first_name": "Иван", "last_name": "К",
                                 "phone": "0888111222", "phone_normalized": "0888111222", "is_active": True})
    await op.persons.insert_one({"id": "pe1", "org_id": ORG_A, "first_name": "Мария", "last_name": "П",
                                 "egn": EGN, "phone": "0888333444", "is_active": True})
    await op.companies.insert_one({"id": "co1", "org_id": ORG_A, "name": "Фирма", "eik": "333333333",
                                   "is_active": True})
    await op.projects.insert_one({"id": "prj-1", "org_id": ORG_A, "code": "P1", "name": "P1",
                                  "status": "Active", "owner_type": "person", "owner_id": "pe1"})
    await op.subcontractors.insert_one({"id": "sub1", "org_id": ORG_A, "name": "Бригада", "active": True})
    await op.subcontractor_packages.insert_one({
        "id": "pkg1", "org_id": ORG_A, "project_id": "prj-1", "subcontractor_id": "sub1",
        "subcontractor_name": "Бригада", "currency": "EUR", "status": "confirmed",
        "certified_total": 5000.0})


def _app(monkeypatch, op, sysdb, mode):
    from fastapi import FastAPI
    import app.db as appdb
    from app.deps import auth as deps_auth, modules as deps_modules
    from app.master_data.deps import ENV_MODE
    from app.routes import clients as r_clients, counterparties as r_cp, finance as r_finance
    from app.routes import projects as r_projects, subcontractors as r_subs
    from app.tenancy import guard, registry, resolver
    from app.utils import audit as u_audit
    mods = [appdb, deps_auth, deps_modules, r_finance, r_cp, r_clients, r_projects, r_subs, u_audit]
    try:
        from app.routes import bank_accounts as r_bank
        mods.append(r_bank)
    except ImportError:                     # main: the register does not exist
        r_bank = None

    monkeypatch.setenv(ENV_MODE, "off")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    monkeypatch.setenv("BANK_ACCOUNT_GUARD_MODE", mode)
    for module in mods:
        monkeypatch.setattr(module, "db", op)
    monkeypatch.setattr(registry, "system_db", sysdb)
    for coll in ("tenant_registry", "tenant_memberships", "tenant_role_assignments"):
        monkeypatch.setattr(registry, coll, sysdb[coll])

    async def _get_db(tenant_id, require_operational=False):
        return op
    monkeypatch.setattr(resolver, "get_tenant_db", _get_db)
    monkeypatch.setattr(guard, "get_tenant_db", _get_db)
    app = FastAPI()
    for r in (r_finance, r_cp, r_clients, r_projects, r_subs, r_bank):
        if r is not None:
            app.include_router(r.router, prefix="/api")
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
                                         base_url="http://cp01") as c:
                return await scenario(c, op)
    return asyncio.run(go())


async def rows(op, coll, flt=None):
    return await op[coll].find(flt or {}, {"_id": 0}).to_list(None)


async def seed_account(op, acc_id, iban, status, party="cp1", party_type="counterparty", entered_by="acct-a"):
    await op.verified_bank_accounts.insert_one({
        "id": acc_id, "org_id": ORG_A, "party_type": party_type, "counterparty_id": party,
        "iban": iban, "status": status, "is_change": False, "entered_by": entered_by,
        "verification": None, "approvals": [], "version": 1, "created_at": "2026-11-01"})


async def manual_pay(c, who="acct-a", **extra):
    body = {"direction": "Outflow", "amount": 100.0, "date": "2026-11-08", "method": "BankTransfer",
            "account_id": BANK_A, "counterparty_name": "Доставчик cp1"}
    body.update(extra)
    return await c.post("/api/finance/payments", headers=hdr(who), json=body)


SOURCES = [{"kind": "contract", "description": "договор №12, чл. 7", "source_origin": "contract"},
           {"kind": "phone_known", "description": "обаждане на записания телефон",
            "source_origin": "known_contact"}]


async def register(c, iban, who="acct-a", party="cp1", kind="counterparties"):
    return await c.post("/api/%s/%s/bank-accounts" % (kind, party), headers=hdr(who),
                        json={"iban": iban, "holder": "Доставчик", "evidence_file_ids": ["file_abc"]})


async def verify(c, acc, who="owner-a", sources=None, version=None):
    return await c.post("/api/bank-accounts/%s/verify" % acc["id"], headers=hdr(who), json={
        "sources": SOURCES if sources is None else sources, "version": version or acc["version"],
        "counterparty_confirmed_by": "Георги, управител", "evidence_file_ids": ["file_contract_12"]})


def no_full(value, needle):
    return needle not in json.dumps(value, ensure_ascii=False, default=str)


# ═══════════════════════════════════════════════ RED on main: payment to unverified IBAN
def test_red_payment_to_an_unverified_account_is_refused(monkeypatch, backend, mode):
    async def scenario(c, op):
        await seed_account(op, "ba-pending", IBAN_NEW, "pending_verification")
        before = await rows(op, "finance_payments")
        r = await manual_pay(c, counterparty_id="cp1", bank_account_id="ba-pending")
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error_code"] == "BANK_ACCOUNT_NOT_VERIFIED"
        assert await rows(op, "finance_payments") == before          # nothing written
        # no account named, only an unverified one registered → still refused
        r = await manual_pay(c, counterparty_id="cp1")
        assert r.status_code == 409, r.text
        assert await rows(op, "finance_payments") == before
        # a draft is still allowed (FLOW-010 L250): an incoming / cash payment is not checked
        r = await manual_pay(c, counterparty_id="cp1", method="Cash", account_id=CASH_A)
        assert r.status_code == 201, r.text
    run(monkeypatch, backend, mode, scenario)


def test_red_quick_pay_with_an_invoice_iban_that_is_not_verified_is_refused(monkeypatch, backend, mode):
    async def scenario(c, op):
        await seed_account(op, "ba-old", IBAN_OLD, "verified")
        await op.invoices.update_one({"id": "inv-r1"}, {"$set": {"counterparty_iban": IBAN_OTHER}})
        r = await c.post("/api/finance/invoices/inv-r1/payments", headers=hdr("acct-a"),
                         json={"amount": 100.0, "method": "BankTransfer", "account_id": BANK_A})
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["reason"] == "INVOICE_IBAN_MISMATCH"
        assert await rows(op, "finance_payments") == []
        assert await rows(op, "payment_allocations") == []
        dq = await rows(op, "dq_issues", {"code": "INVOICE_IBAN_MISMATCH"})
        assert len(dq) == 1 and dq[0]["severity"] == "critical"
        assert no_full(dq, IBAN_OTHER)
        # the invoice IBAN equal to the verified account → paid, stamped with that account
        await op.invoices.update_one({"id": "inv-r1"}, {"$set": {"counterparty_iban": IBAN_OLD}})
        r = await c.post("/api/finance/invoices/inv-r1/payments", headers=hdr("acct-a"),
                         json={"amount": 100.0, "method": "BankTransfer", "account_id": BANK_A})
        assert r.status_code == 201, r.text
        pay = (await rows(op, "finance_payments"))[0]
        assert pay["bank_account_id"] == "ba-old"
    run(monkeypatch, backend, mode, scenario)


def test_red_subcontractor_payment_to_an_unverified_account_is_refused(monkeypatch, backend, mode):
    async def scenario(c, op):
        await seed_account(op, "ba-sub", IBAN_NEW, "pending_verification", party="sub1",
                           party_type="subcontractor")
        r = await c.post("/api/subcontractor-payments", headers=hdr("acct-a"), json={
            "package_id": "pkg1", "amount": 300.0, "payment_method": "bank", "account_id": BANK_A,
            "bank_account_id": "ba-sub"})
        assert r.status_code == 409, r.text
        assert await rows(op, "subcontractor_payments") == []
        assert await rows(op, "finance_payments") == []
    run(monkeypatch, backend, mode, scenario)


def test_red_payment_during_an_iban_change_goes_only_to_the_verified_account(monkeypatch, backend, mode):
    async def scenario(c, op):
        await seed_account(op, "ba-old", IBAN_OLD, "verified")
        await seed_account(op, "ba-new", IBAN_NEW, "pending_verification")
        r = await manual_pay(c, counterparty_id="cp1", bank_account_id="ba-new")
        assert r.status_code == 409, r.text                     # never to the unconfirmed one
        r = await manual_pay(c, counterparty_id="cp1")
        assert r.status_code == 201, r.text
        assert r.json()["bank_account_id"] == "ba-old"          # the verified account
        assert r.json()["bank_account_iban_masked"].endswith(IBAN_OLD[-4:])
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════ RED on main: hard delete
@pytest.mark.parametrize("url,coll,rid", [
    ("/api/counterparties/%s", "counterparties", "cp1"),     # used (an invoice)
    ("/api/counterparties/%s", "counterparties", "cp2"),     # unused — R48.4: never either
    ("/api/clients/%s", "clients", "cl1"),
    ("/api/persons/%s", "persons", "pe1"),
    ("/api/companies/%s", "companies", "co1"),
])
def test_red_delete_never_deletes(monkeypatch, backend, mode, url, coll, rid):
    async def scenario(c, op):
        before = await rows(op, coll)
        r = await c.delete(url % rid, headers=hdr("admin-a"))
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error_code"] == "COUNTERPARTY_NO_DELETE"
        assert "deactivate" in r.json()["detail"]["alternatives"]
        assert await rows(op, coll) == before                    # not deleted, not changed
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════ RED on main: rights
WRITES = [
    ("post", "/api/clients/person", {"full_name": "Нов Човек", "egn": "9001011111"}, "persons"),
    ("post", "/api/clients/company", {"company_name": "Нова", "eik": "444444444"}, "companies"),
    ("post", "/api/persons", {"phone": "0899000111", "first_name": "А", "last_name": "Б"}, "persons"),
    ("post", "/api/companies", {"eik": "555555555", "name": "Друга"}, "companies"),
    ("post", "/api/subcontractors", {"name": "Нова бригада"}, "subcontractors"),
    ("post", "/api/counterparties", {"name": "Нов доставчик"}, "counterparties"),
    ("post", "/api/clients", {"first_name": "А", "last_name": "Б", "phone": "0899999999"}, "clients"),
    ("post", "/api/clients/find-or-create", {"first_name": "А", "last_name": "Б", "phone": "0877777777"},
     "clients"),
    ("put", "/api/persons/pe1", {"first_name": "Хакната"}, "persons"),
    ("put", "/api/companies/co1", {"name": "Хакната"}, "companies"),
    ("put", "/api/counterparties/cp1", {"name": "Хакнат"}, "counterparties"),
    ("patch", "/api/projects/prj-1/client-link", {"client_id": "co1", "client_type": "company"}, "projects"),
]


@pytest.mark.parametrize("who", ["viewer-a", "site-a", "tech-a"])
@pytest.mark.parametrize("method,url,body,coll", WRITES, ids=[w[1] + ":" + w[0] for w in WRITES])
def test_red_other_roles_cannot_create_or_edit(monkeypatch, backend, mode, who, method, url, body, coll):
    async def scenario(c, op):
        before = await rows(op, coll)
        r = await c.request(method.upper(), url, json=body, headers=hdr(who))
        assert r.status_code == 403, (who, url, r.status_code, r.text)
        assert await rows(op, coll) == before
        assert await rows(op, "audit_events", {"action": {"$regex": "created|updated"}}) == []
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════ RED on main: ЕГН
READERS = ["/api/persons", "/api/persons/pe1", "/api/persons/find-by-phone?phone=0888333444",
           "/api/clients/search/unified?query=Мария", "/api/clients/search/unified?query=" + EGN,
           "/api/projects/prj-1/client-info", "/api/projects/prj-1/invoice-context"]


@pytest.mark.parametrize("who", ["owner-a", "admin-a", "acct-a", "viewer-a", "site-a", "tech-a"])
def test_red_no_reader_returns_the_full_egn(monkeypatch, backend, mode, who):
    async def scenario(c, op):
        for url in READERS:
            r = await c.get(url, headers=hdr(who))
            if r.status_code != 200:
                continue                                   # a reader this role may not use at all
            body = r.json()
            if isinstance(body, dict):
                body = {k: v for k, v in body.items() if k != "query"}   # the caller's own text echoed
            assert no_full(body, EGN), (who, url, r.text)
        # a project import copies no full ЕГН (it may be refused for this role — then nothing)
        r = await c.post("/api/projects/prj-1/import-client-invoice", headers=hdr(who))
        prj = (await rows(op, "projects", {"id": "prj-1"}))[0]
        assert no_full(prj, EGN), prj
        r = await c.get("/api/persons/pe1", headers=hdr(who))
        assert r.json()["egn"] == EGN_MASKED
    run(monkeypatch, backend, mode, scenario)


def test_egn_reveal_only_owner_and_accountant_and_audited(monkeypatch, backend, mode):
    async def scenario(c, op):
        for who in ("site-a", "viewer-a", "admin-a", "tech-a"):
            r = await c.post("/api/persons/pe1/egn/reveal", headers=hdr(who))
            assert r.status_code == 403, (who, r.text)
        assert await rows(op, "audit_events", {"action": "person.egn.revealed"}) == []
        for who in ("owner-a", "acct-a"):
            r = await c.post("/api/persons/pe1/egn/reveal", headers=hdr(who))
            assert r.status_code == 200 and r.json()["egn"] == EGN
        ev = await rows(op, "audit_events", {"action": "person.egn.revealed"})
        assert [e["actor_id"] for e in ev] == ["owner-a", "acct-a"]
        assert all(e["entity_id"] == "pe1" and e["tenant_id"] == ORG_A for e in ev)
        assert no_full(ev, EGN)                            # the event itself never holds it
        r = await c.post("/api/persons/pe1/egn/reveal", headers=hdr("owner-b"))
        assert r.status_code == 404                        # another tenant
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════ positive: verification → payment
def test_first_iban_verified_by_another_person_then_payment_passes(monkeypatch, backend, mode):
    async def scenario(c, op):
        r = await register(c, IBAN_OLD.lower()[:4] + " " + IBAN_OLD[4:], who="acct-a")
        assert r.status_code == 201, r.text
        acc = r.json()
        assert acc["status"] == "pending_verification" and acc["iban"] == IBAN_OLD
        r = await manual_pay(c, counterparty_id="cp1")
        assert r.status_code == 409                        # „за проверка“ → blocked
        r = await verify(c, acc, who="owner-a")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "verified"
        stored = (await rows(op, "verified_bank_accounts"))[0]
        v = stored["verification"]
        assert v["verified_by"] == "owner-a" and len(v["sources"]) == 2
        assert v["counterparty_confirmed_by"] and v["evidence_file_ids"] == ["file_contract_12"]
        assert stored["entered_by"] == "acct-a"
        r = await manual_pay(c, counterparty_id="cp1")
        assert r.status_code == 201, r.text
        assert r.json()["bank_account_id"] == acc["id"]
        ev = await rows(op, "audit_events", {"entity_type": "bank_account"})
        assert [e["action"] for e in ev] == ["bank_account.registered", "bank_account.verified"]
        assert no_full(ev, IBAN_OLD)                       # IBAN masked in every event
    run(monkeypatch, backend, mode, scenario)


def test_iban_change_needs_verification_and_double_approval(monkeypatch, backend, mode):
    async def scenario(c, op):
        old = (await register(c, IBAN_OLD, who="acct-a")).json()
        assert (await verify(c, old, who="owner-a")).status_code == 200
        r = await register(c, IBAN_NEW, who="admin-a")
        assert r.status_code == 201, r.text
        new = r.json()
        assert new["is_change"] is True and new["replaces_account_id"] == old["id"]
        notes = await rows(op, "notifications", {"type": "bank_account_change"})
        assert {n["user_id"] for n in notes} == {"owner-a", "acct-a", "acct2-a"}   # immediately
        assert no_full(notes, IBAN_NEW)
        r = await c.post("/api/bank-accounts/%s/approve-change" % new["id"], headers=hdr("owner-a"),
                         json={"version": new["version"]})
        assert r.status_code == 409 and r.json()["detail"]["error_code"] == "VERIFICATION_REQUIRED"
        r = await verify(c, new, who="acct-a")
        assert r.status_code == 200, r.text
        new = r.json()
        assert new["status"] == "pending_verification"     # not active before the approvals
        assert (await manual_pay(c, counterparty_id="cp1")).json()["bank_account_id"] == old["id"]
        r = await c.post("/api/bank-accounts/%s/approve-change" % new["id"], headers=hdr("owner-a"),
                         json={"version": new["version"]})
        assert r.status_code == 200, r.text
        new = r.json()
        assert new["status"] == "pending_verification" and len(new["approvals"]) == 1
        r = await c.post("/api/bank-accounts/%s/approve-change" % new["id"], headers=hdr("owner-a"),
                         json={"version": new["version"]})
        assert r.status_code == 409 and r.json()["detail"]["error_code"] == "ALREADY_APPROVED"
        r = await c.post("/api/bank-accounts/%s/approve-change" % new["id"], headers=hdr("acct2-a"),
                         json={"version": new["version"]})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "verified" and r.json()["replaced_account_ids"] == [old["id"]]
        accs = {a["id"]: a for a in await rows(op, "verified_bank_accounts")}
        assert accs[old["id"]]["status"] == "replaced"
        assert accs[old["id"]]["replaced_by_account_id"] == new["id"]
        done = await rows(op, "notifications", {"type": "bank_account_changed"})
        assert {n["user_id"] for n in done} == {"owner-a", "acct-a", "acct2-a"}
        r = await manual_pay(c, counterparty_id="cp1")
        assert r.status_code == 201 and r.json()["bank_account_id"] == new["id"]
        r = await manual_pay(c, counterparty_id="cp1", bank_account_id=old["id"])
        assert r.status_code == 409                        # the replaced account is never paid
        ev = await rows(op, "audit_events", {"entity_type": "bank_account"})
        approvals = [e for e in ev if e["action"] == "bank_account.change_approved"]
        assert len(approvals) == 2 and all(e["approval_id"] for e in approvals)
        assert no_full(ev, IBAN_NEW) and no_full(ev, IBAN_OLD)
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════ forbidden
def test_the_person_who_entered_cannot_verify(monkeypatch, backend, mode):
    async def scenario(c, op):
        acc = (await register(c, IBAN_OLD, who="acct-a")).json()
        r = await verify(c, acc, who="acct-a")
        assert r.status_code == 409 and r.json()["detail"]["error_code"] == "SAME_PERSON_VERIFICATION"
        for who in ("admin-a", "site-a", "viewer-a"):     # only Owner / Accountant verify
            assert (await verify(c, acc, who=who)).status_code == 403
        assert (await rows(op, "verified_bank_accounts"))[0]["status"] == "pending_verification"
    run(monkeypatch, backend, mode, scenario)


def test_two_independent_sources_are_required(monkeypatch, backend, mode):
    async def scenario(c, op):
        acc = (await register(c, IBAN_OLD, who="acct-a")).json()
        one = SOURCES[:1]
        same_kind = [SOURCES[0], dict(SOURCES[0], description="второ копие")]
        both_invoice = [{"kind": "invoice", "description": "фактура", "source_origin": "invoice"},
                        {"kind": "phone_known", "description": "телефонът от фактурата",
                         "source_origin": "invoice"}]
        for sources, code in ((one, "TWO_SOURCES_REQUIRED"), (same_kind, "SOURCES_NOT_INDEPENDENT"),
                              (both_invoice, "SOURCES_NOT_INDEPENDENT"), ([], "TWO_SOURCES_REQUIRED")):
            r = await verify(c, acc, who="owner-a", sources=sources)
            assert r.status_code == 422 and r.json()["detail"]["error_code"] == code, r.text
        assert (await rows(op, "verified_bank_accounts"))[0]["verification"] is None
        bad = await c.post("/api/counterparties/cp1/bank-accounts", headers=hdr("acct-a"),
                           json={"iban": "BG00UNCR70001522123456"})
        assert bad.status_code == 422                      # mod-97
        url = await c.post("/api/counterparties/cp1/bank-accounts", headers=hdr("acct-a"),
                           json={"iban": IBAN_NEW, "evidence_file_ids": ["https://drive/x.pdf"]})
        assert url.status_code == 422                      # evidence is a file_id, not a URL
    run(monkeypatch, backend, mode, scenario)


def test_legacy_payment_without_an_account_follows_the_mode(monkeypatch, backend, mode):
    async def scenario(c, op):
        r = await manual_pay(c)                            # no counterparty, no account
        if mode == "enforce":
            assert r.status_code == 409, r.text
            assert await rows(op, "finance_payments") == []
        else:
            assert r.status_code == 201, r.text
        dq = await rows(op, "dq_issues", {"code": "PAYMENT_WITHOUT_VERIFIED_ACCOUNT"})
        assert len(dq) == (1 if mode == "shadow" else 0)
        r = await manual_pay(c, direction="Inflow")       # incoming money is never blocked
        assert r.status_code == 201
    run(monkeypatch, backend, mode, scenario)


def test_eik_change_needs_a_reason_and_a_second_person(monkeypatch, backend, mode):
    async def scenario(c, op):
        r = await c.put("/api/counterparties/cp1", headers=hdr("acct-a"), json={"eik": "777777777"})
        assert r.status_code == 400 and r.json()["detail"]["error_code"] == "REASON_REQUIRED"
        r = await c.put("/api/counterparties/cp1", headers=hdr("acct-a"),
                        json={"eik": "222222222", "eik_change_reason": "грешка"})
        assert r.status_code == 409 and r.json()["detail"]["error_code"] == "EIK_ALREADY_EXISTS"
        r = await c.put("/api/counterparties/cp1", headers=hdr("acct-a"),
                        json={"eik": "777777777", "eik_change_reason": "преобразуване"})
        assert r.status_code == 200 and r.json()["eik_change_pending"] is True
        cp = (await rows(op, "counterparties", {"id": "cp1"}))[0]
        assert cp["eik"] == "111111111"                    # not applied yet
        req = cp["eik_change_request"]["request_id"]
        r = await c.post("/api/counterparties/cp1/eik-change/approve", headers=hdr("acct-a"),
                         json={"request_id": req})
        assert r.status_code == 409 and r.json()["detail"]["error_code"] == "SAME_PERSON_APPROVAL"
        r = await c.post("/api/counterparties/cp1/eik-change/approve", headers=hdr("viewer-a"),
                         json={"request_id": req})
        assert r.status_code == 403
        r = await c.post("/api/counterparties/cp1/eik-change/approve", headers=hdr("owner-a"),
                         json={"request_id": req})
        assert r.status_code == 200, r.text
        assert r.json()["eik"] == "777777777"
        ev = await rows(op, "audit_events", {"action": "counterparty.eik_change_approved"})
        assert len(ev) == 1 and ev[0]["approval_id"] and ev[0]["actor_id"] == "owner-a"
    run(monkeypatch, backend, mode, scenario)


def test_duplicate_eik_is_refused_with_dq(monkeypatch, backend, mode):
    async def scenario(c, op):
        before = await rows(op, "counterparties")
        r = await c.post("/api/counterparties", headers=hdr("acct-a"),
                         json={"name": "Дубликат", "eik": " 111 111 111 "})
        assert r.status_code == 409 and r.json()["detail"]["error_code"] == "EIK_ALREADY_EXISTS"
        assert await rows(op, "counterparties") == before
        assert len(await rows(op, "dq_issues", {"code": "DUPLICATE_EIK"})) == 1
        r = await c.post("/api/companies", headers=hdr("acct-a"), json={"eik": "333333333", "name": "X"})
        assert r.status_code == 409 and r.json()["detail"]["error_code"] == "EIK_ALREADY_EXISTS"
    run(monkeypatch, backend, mode, scenario)


def test_writes_without_a_key_are_428_and_write_nothing(monkeypatch, backend, mode):
    async def scenario(c, op):
        before = {k: await rows(op, k) for k in ("counterparties", "persons", "verified_bank_accounts")}
        for method, url, body in (("post", "/api/counterparties", {"name": "Х"}),
                                  ("put", "/api/counterparties/cp1", {"name": "Х"}),
                                  ("post", "/api/counterparties/cp1/deactivate", {"reason": "x"}),
                                  ("post", "/api/persons", {"phone": "0811", "first_name": "a",
                                                            "last_name": "b"}),
                                  ("post", "/api/counterparties/cp1/bank-accounts", {"iban": IBAN_NEW})):
            r = await c.request(method.upper(), url, json=body, headers=hdr("owner-a", key=False))
            assert r.status_code == 428, (url, r.text)
        for k, v in before.items():
            assert await rows(op, k) == v
    run(monkeypatch, backend, mode, scenario)


def test_create_is_idempotent_and_audited(monkeypatch, backend, mode):
    async def scenario(c, op):
        body = {"name": "Нов доставчик", "eik": "888888888"}
        r1 = await c.post("/api/counterparties", headers=hdr("acct-a", "k-create"), json=body)
        r2 = await c.post("/api/counterparties", headers=hdr("acct-a", "k-create"), json=body)
        assert r1.status_code == 201 and r2.status_code == 201 and r1.json() == r2.json()
        assert len(await rows(op, "counterparties", {"eik": "888888888"})) == 1
        r3 = await c.post("/api/counterparties", headers=hdr("acct-a", "k-create"), json={"name": "друг"})
        assert r3.status_code == 409
        ev = await rows(op, "audit_events", {"action": "counterparty.created"})
        assert len(ev) == 1 and ev[0]["idempotency_key"] == "k-create" and ev[0]["source_flow"] == "FLOW-010"
        r = await c.put("/api/counterparties/cp2", headers=hdr("admin-a"), json={"name": "Ново име"})
        assert r.status_code == 200 and r.json()["version"] == 1
        ev = await rows(op, "audit_events", {"action": "counterparty.updated"})
        assert ev[0]["structured_diff"]["name"]["after"] == "Ново име"
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════ correction: deactivate ↔ reactivate, archive
def test_deactivate_reactivate_archive(monkeypatch, backend, mode):
    async def scenario(c, op):
        r = await c.post("/api/counterparties/cp1/deactivate", headers=hdr("acct-a"), json={})
        assert r.status_code == 400                        # a reason is required
        r = await c.post("/api/counterparties/cp1/deactivate", headers=hdr("site-a"), json={"reason": "x"})
        assert r.status_code == 403
        r = await c.post("/api/counterparties/cp1/deactivate", headers=hdr("acct-a"),
                         json={"reason": "не работим"})
        assert r.status_code == 200 and r.json()["lifecycle_status"] == "inactive"
        r = await manual_pay(c, counterparty_id="cp1")
        assert r.status_code == 422 and r.json()["detail"]["error_code"] == "COUNTERPARTY_NOT_SELECTABLE"
        r = await c.post("/api/finance/invoices", headers=hdr("acct-a"), json={
            "direction": "Received", "invoice_no": "R-9", "counterparty_eik": "111111111",
            "issue_date": "2026-11-08", "due_date": "2026-12-08", "lines": []})
        assert r.status_code == 422
        assert (await c.get("/api/counterparties/cp1", headers=hdr("acct-a"))).status_code == 200
        r = await c.post("/api/counterparties/cp1/reactivate", headers=hdr("acct-a"),
                         json={"reason": "отново работим"})
        assert r.status_code == 200 and r.json()["lifecycle_status"] == "active"
        r = await c.post("/api/counterparties/cp1/archive", headers=hdr("acct-a"), json={"reason": "стар"})
        assert r.status_code == 403                        # only Admin / Owner archive
        r = await c.post("/api/counterparties/cp1/archive", headers=hdr("admin-a"), json={"reason": "стар"})
        assert r.status_code == 200 and r.json()["lifecycle_status"] == "archived"
        listed = (await c.get("/api/counterparties?active_only=false", headers=hdr("acct-a"))).json()
        assert "cp1" not in {x["id"] for x in listed["items"]}                    # hidden
        listed = (await c.get("/api/counterparties?active_only=false&include_archived=true",
                              headers=hdr("acct-a"))).json()
        assert "cp1" in {x["id"] for x in listed["items"]}
        r = await c.put("/api/counterparties/cp1", headers=hdr("admin-a"), json={"name": "x"})
        assert r.status_code == 409 and r.json()["detail"]["error_code"] == "COUNTERPARTY_ARCHIVED"
        r = await c.post("/api/counterparties/cp1/reactivate", headers=hdr("acct-a"), json={"reason": "y"})
        assert r.status_code == 403
        r = await c.post("/api/counterparties/cp1/reactivate", headers=hdr("owner-a"), json={"reason": "y"})
        assert r.status_code == 200
        acts = [e["action"] for e in await rows(op, "audit_events", {"entity_id": "cp1"})]
        assert acts == ["counterparty.deactivated", "counterparty.reactivated", "counterparty.archived",
                        "counterparty.reactivated"]
        assert len(await rows(op, "counterparties")) == 3  # never deleted
        # persons / companies / clients the same, and an inactive client is not chosen for a project
        r = await c.post("/api/companies/co1/deactivate", headers=hdr("acct-a"), json={"reason": "z"})
        assert r.status_code == 200
        r = await c.patch("/api/projects/prj-1/client-link", headers=hdr("acct-a"),
                          json={"client_id": "co1", "client_type": "company"})
        assert r.status_code == 422
        r = await c.post("/api/clients/cl1/archive", headers=hdr("owner-a"), json={"reason": "z"})
        assert r.status_code == 200
        r = await c.post("/api/persons/pe1/deactivate", headers=hdr("acct-a"), json={"reason": "z"})
        assert r.status_code == 200
    run(monkeypatch, backend, mode, scenario)


def test_r22_project_client_change_by_office_only(monkeypatch, backend, mode):
    async def scenario(c, op):
        r = await c.patch("/api/projects/prj-1/client-link", headers=hdr("acct-a"),
                          json={"client_id": "co1", "client_type": "company"})
        assert r.status_code == 200, r.text
        prj = (await rows(op, "projects", {"id": "prj-1"}))[0]
        assert prj["owner_type"] == "company" and prj["owner_id"] == "co1"
        ev = await rows(op, "audit_events", {"action": "project.client_link_changed"})
        assert len(ev) == 1 and ev[0]["structured_diff"]["owner_id"]["before"] == "pe1"
    run(monkeypatch, backend, mode, scenario)


def test_another_tenant_cannot_touch_the_register(monkeypatch, backend, mode):
    async def scenario(c, op):
        acc = (await register(c, IBAN_OLD, who="acct-a")).json()
        r = await verify(c, acc, who="owner-b")
        assert r.status_code == 404
        r = await c.get("/api/counterparties/cp1/bank-accounts", headers=hdr("admin-b"))
        assert r.status_code == 404
        r = await c.post("/api/counterparties/cp1/bank-accounts", headers=hdr("admin-b"),
                         json={"iban": IBAN_NEW})
        assert r.status_code == 404
        assert len(await rows(op, "verified_bank_accounts")) == 1
    run(monkeypatch, backend, mode, scenario)


def test_iban_is_masked_for_roles_that_do_not_verify(monkeypatch, backend, mode):
    async def scenario(c, op):
        await register(c, IBAN_OLD, who="acct-a")
        full = (await c.get("/api/counterparties/cp1/bank-accounts", headers=hdr("acct-a"))).json()
        assert full[0]["iban"] == IBAN_OLD
        masked = (await c.get("/api/counterparties/cp1/bank-accounts", headers=hdr("admin-a"))).json()
        assert no_full(masked, IBAN_OLD)
        assert (await c.get("/api/counterparties/cp1/bank-accounts", headers=hdr("site-a"))).status_code == 403
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════ concurrency (real Mongo transactions)
def test_two_concurrent_approvals_of_one_version(monkeypatch, backend, mode):
    async def scenario(c, op):
        old = (await register(c, IBAN_OLD, who="acct-a")).json()
        await verify(c, old, who="owner-a")
        new = (await register(c, IBAN_NEW, who="admin-a")).json()
        new = (await verify(c, new, who="acct-a")).json()
        a, b = await asyncio.gather(*[
            c.post("/api/bank-accounts/%s/approve-change" % new["id"], headers=hdr(who),
                   json={"version": new["version"]}) for who in ("owner-a", "acct2-a")])
        codes = sorted([a.status_code, b.status_code])
        assert codes == [200, 409], (a.text, b.text)
        stored = [x for x in await rows(op, "verified_bank_accounts") if x["id"] == new["id"]][0]
        assert len(stored["approvals"]) == 1 and stored["status"] == "pending_verification"
        loser = "owner-a" if a.status_code == 409 else "acct2-a"
        r = await c.post("/api/bank-accounts/%s/approve-change" % new["id"], headers=hdr(loser),
                         json={"version": stored["version"]})
        assert r.status_code == 200 and r.json()["status"] == "verified"
        statuses = sorted(x["status"] for x in await rows(op, "verified_bank_accounts"))
        assert statuses == ["replaced", "verified"]
    run(monkeypatch, backend, mode, scenario)


def test_concurrent_creates_of_the_same_eik(monkeypatch, backend, mode):
    if backend != "real":
        pytest.skip("concurrency of transactions needs the real replica set")

    async def scenario(c, op):
        rs = await asyncio.gather(*[
            c.post("/api/counterparties", headers=hdr("acct-a"), json={"name": "N%d" % i, "eik": "121212121"})
            for i in range(4)])
        assert sorted(r.status_code for r in rs).count(201) == 1, [r.text for r in rs]
        assert len(await rows(op, "counterparties", {"eik": "121212121"})) == 1
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════ migration: existing IBANs → „за проверка“
def test_migration_dry_run_then_apply_is_pending_and_idempotent(backend):
    async def go():
        async with _Dbs(backend) as (op, _sys):
            from scripts import cp_01_migrate_bank_accounts as mig
            await op.counterparties.insert_one({"id": "cpm", "org_id": ORG_A, "name": "M", "iban": IBAN_OLD})
            await op.subcontractors.insert_one({"id": "sbm", "org_id": ORG_A, "name": "S",
                                                "bank_account": IBAN_NEW.lower()})
            await op.counterparties.insert_one({"id": "cpx", "org_id": ORG_A, "name": "X", "iban": "BG00XXXX"})
            await op.projects.insert_one({"id": "pm", "org_id": ORG_A, "owner_type": "person",
                                          "invoice_details": {"eik": EGN}})
            report = await mig.plan(op)
            assert len(report["to_create"]) == 2 and len(report["invalid"]) == 1
            assert report["projects_with_full_egn"] == 1
            assert no_full(mig.printable(report), IBAN_OLD) and no_full(mig.printable(report), IBAN_NEW)
            assert await rows(op, "verified_bank_accounts") == []          # dry run writes nothing
            assert await mig.apply(op, report) == 2
            accs = await rows(op, "verified_bank_accounts")
            assert {a["status"] for a in accs} == {"pending_verification"}  # never verified
            assert await mig.apply(op, await mig.plan(op)) == 0             # idempotent
            assert len(await rows(op, "verified_bank_accounts")) == 2
    asyncio.run(go())
