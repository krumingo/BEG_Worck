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


RECEIPTS_A = ("file_rcpt_1", "file_r", "file_r1", "file_r2", "file_bon", "file_x", "f")


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
    # FG-290: the receipts the tests use are file records of tenant A (legacy media_files
    # until W0-06 — the File Registry — lands); "file_b" belongs to tenant B
    for fid in RECEIPTS_A:
        await op.media_files.insert_one({"id": fid, "org_id": ORG_A, "filename": fid + ".jpg",
                                         "context_type": "finance_payment"})
    await op.media_files.insert_one({"id": "file_b", "org_id": ORG_B, "filename": "b.jpg"})
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
                                  "status": "Active", "owner_type": "person", "owner_id": "pe1",
                                  "invoice_details": {"company_name": "Мария П", "eik": EGN}})
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
    for name in ("app.permissions.money_write", "app.permissions.money_input"):   # #69 SEC-01
        try:
            mods.append(__import__(name, fromlist=["db"]))
        except ImportError:
            pass
    try:
        from app.routes import bank_accounts as r_bank
        mods.append(r_bank)
    except ImportError:                     # main: the register does not exist
        r_bank = None

    monkeypatch.setenv(ENV_MODE, "off")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    monkeypatch.setenv("BANK_ACCOUNT_GUARD_MODE", mode)
    monkeypatch.setenv("ENV", "test")        # D1: only a non-production ENV may relax the guard
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
        # R50.1: cash does not bypass it — while the IBAN is unverified, cash is blocked too
        r = await manual_pay(c, counterparty_id="cp1", method="Cash", account_id=CASH_A,
                             cash_receipt_file_id="file_rcpt_1", cash_recipient_name="Иван")
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error_code"] == "PAYEE_BLOCKED_PENDING_IBAN"
        assert await rows(op, "finance_payments") == before
        # an incoming payment is never checked
        r = await manual_pay(c, counterparty_id="cp1", direction="Inflow")
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
           "/api/projects/prj-1/client-info", "/api/projects/prj-1/invoice-context",
           "/api/projects/prj-1/invoice-details", "/api/projects", "/api/projects/prj-1"]   # FG-226


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
        if r.status_code == 200:
            prj = (await rows(op, "projects", {"id": "prj-1"}))[0]
            assert no_full(prj["invoice_details"], EGN), prj
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
        assert r.status_code == 409 and r.json()["detail"]["error_code"] == "SAME_PERSON_APPROVAL"
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
        assert no_full(masked, IBAN_OLD) and masked[0]["iban"] == "****" + IBAN_OLD[-4:]
        # D5: an Admin sees it only with the explicit sensitive right on their own assignment
        from app.tenancy import registry
        await registry.tenant_role_assignments.update_one(
            {"id": "ra_admin-a"}, {"$set": {"permissions": ["sensitive.iban.read"]}})
        full = (await c.get("/api/counterparties/cp1/bank-accounts", headers=hdr("admin-a"))).json()
        assert full[0]["iban"] == IBAN_OLD
        await registry.tenant_role_assignments.update_one(
            {"id": "ra_admin-b"}, {"$set": {"permissions": ["sensitive.iban.read"]}})
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
            from scripts.w0_04_bootstrap_audit_indexes import PLANNED_INDEXES
            for coll, keys, opts in PLANNED_INDEXES:
                await op[coll].create_index(keys, **opts)
            await op.counterparties.insert_one({"id": "cpm", "org_id": ORG_A, "name": "M", "iban": IBAN_OLD})
            await op.subcontractors.insert_one({"id": "sbm", "org_id": ORG_A, "name": "S",
                                                "bank_account": IBAN_NEW.lower()})
            await op.counterparties.insert_one({"id": "cpx", "org_id": ORG_A, "name": "X", "iban": "BG00XXXX"})
            await op.persons.insert_one({"id": "pe-m", "org_id": ORG_A, "first_name": "M", "egn": EGN})
            # 1. a redundant copy: the canonical person holds the same ЕГН → masked + AuditEvent
            await op.projects.insert_one({"id": "pm", "org_id": ORG_A, "owner_type": "person",
                                          "owner_id": "pe-m", "invoice_details": {"eik": EGN}})
            # 2. a copy with no canonical record → kept as it is, DQ issue for the Accountant
            await op.projects.insert_one({"id": "pn", "org_id": ORG_A, "owner_type": "person",
                                          "owner_id": "pe-none", "invoice_details": {"eik": "7501011111"}})
            # 3. a confirmed company's 10-digit foreign VAT id is never an ЕГН → untouched
            await op.companies.insert_one({"id": "co-x", "org_id": ORG_A, "name": "Foreign GmbH"})
            await op.projects.insert_one({"id": "pc", "org_id": ORG_A, "owner_type": "company",
                                          "owner_id": "co-x", "invoice_details": {"eik": "1234567890"}})
            # 3b. FG-267 (pass 28): owner_type=company with no company record → a possible ЕГН
            await op.projects.insert_one({"id": "pu", "org_id": ORG_A, "owner_type": "company",
                                          "owner_id": "co-gone", "invoice_details": {"eik": "5503031313"}})
            # 4. FG-267: a 10-digit value with no owner is a possible ЕГН → kept + DQ, not masked
            await op.projects.insert_one({"id": "po", "org_id": ORG_A,
                                          "invoice_details": {"eik": "6602021212"}})
            report = await mig.plan(op)
            assert len(report["to_create"]) == 2 and len(report["invalid"]) == 1
            assert report["projects_with_full_egn"] == 4
            assert [p["id"] for p in report["projects_to_mask"]] == ["pm"]
            assert sorted(p["id"] for p in report["egn_copies_without_canonical"]) == ["pn", "po", "pu"]
            shown = mig.printable(report)
            for secret in (IBAN_OLD, IBAN_NEW, EGN, "7501011111", "6602021212"):
                assert no_full(shown, secret)
            assert await rows(op, "verified_bank_accounts") == []          # dry run writes nothing
            # --apply without the dry run's token is refused, nothing written
            url = "mongodb://unused"
            refused = await _main_with(mig, op, ["--apply"])
            assert refused["refused"] is True and await rows(op, "verified_bank_accounts") == []
            ok = await _main_with(mig, op, ["--apply", "--plan-token", mig.plan_token(report)])
            assert ok["written"] == 3                                      # 2 accounts + 1 project
            prj = {p["id"]: p for p in await rows(op, "projects")}
            assert prj["pm"]["invoice_details"]["eik"] == EGN_MASKED
            assert prj["pn"]["invoice_details"]["eik"] == "7501011111"      # not destroyed
            assert prj["pc"]["invoice_details"]["eik"] == "1234567890"
            assert prj["po"]["invoice_details"]["eik"] == "6602021212"      # kept, masked on read
            assert prj["pu"]["invoice_details"]["eik"] == "5503031313"      # kept, masked on read
            ev = await rows(op, "audit_events", {"action": "project.invoice_details.egn_copy_masked"})
            assert [e["entity_id"] for e in ev] == ["pm"] and no_full(ev, EGN)
            dq = await rows(op, "dq_issues", {"type": "EGN_COPY_WITHOUT_CANONICAL"})
            assert sorted(d["entity_id"] for d in dq) == ["pn", "po", "pu"]
            assert all(d["owner_role"] == "accountant" and d["title"] == "ЕГН копие без каноничен запис"
                       for d in dq)
            accs = await rows(op, "verified_bank_accounts")
            assert {a["status"] for a in accs} == {"pending_verification"}  # never verified
            again = await mig.plan(op)
            assert await mig.apply(op, again) == 0                          # idempotent
            assert len(await rows(op, "verified_bank_accounts")) == 2
    asyncio.run(go())


async def _main_with(mig, op, extra):
    """Run the script's main() against the test database (its client is replaced)."""
    import motor.motor_asyncio as mm
    real = mm.AsyncIOMotorClient

    class _Client:
        def __init__(self, *a, **kw):
            pass

        def __getitem__(self, name):
            return op

        def close(self):
            pass
    mm.AsyncIOMotorClient = _Client
    try:
        return await mig.main(["--mongo-url", "mongodb://127.0.0.1:1/", "--db", "x"] + extra)
    finally:
        mm.AsyncIOMotorClient = real


# ═══════════════════════════════════════════════ Addendum A (R50, Q005)
@pytest.mark.parametrize("env,var,expected", [
    ("production", "shadow", "enforce"), ("production", "off", "enforce"), (None, "shadow", "enforce"),
    ("prod", "off", "enforce"), ("staging", "shadow", "shadow"), ("staging", None, "enforce"),
    ("test", "off", "off"), ("development", "nonsense", "enforce")])
def test_a1_production_is_always_enforce(monkeypatch, env, var, expected):
    from app.services import counterparty_rules as cr
    for k, v in (("ENV", env), ("BANK_ACCOUNT_GUARD_MODE", var)):
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    assert cr.bank_guard_mode() == expected


def test_a1_production_refuses_a_legacy_payment_even_with_shadow_set(monkeypatch, backend, mode):
    async def scenario(c, op):
        import os
        os.environ["ENV"] = "production"
        try:
            r = await manual_pay(c)
        finally:
            os.environ["ENV"] = "test"
        assert r.status_code == 409 and r.json()["detail"]["reason"] == "NO_VERIFIED_BANK_ACCOUNT"
        assert await rows(op, "finance_payments") == []
    run(monkeypatch, backend, mode, scenario)


def test_a2_other_roles_are_pointed_to_the_pending_proposal(monkeypatch, backend, mode):
    def app_with_master_data(mp, op, sysdb, m):
        app = _app(mp, op, sysdb, m)
        from app.master_data.deps import ENV_MODE
        from app.routes import master_data as md
        mp.setenv(ENV_MODE, "enforce")
        app.include_router(md.router, prefix="/api")
        return app

    async def scenario(c, op):
        before = await rows(op, "counterparties")
        r = await c.post("/api/counterparties", headers=hdr("site-a"), json={"name": "Нов ООД"})
        assert r.status_code == 403
        assert r.json()["detail"]["propose"]["path"] == "/api/master-data/pending"
        r = await c.post("/api/master-data/pending", headers=hdr("site-a"), json={
            "entity_type": "organization", "raw_value": "Нов ООД", "source_channel": "ocr",
            "source_ref": "scan-17"})
        assert r.status_code == 201 and r.json()["performed"] is True, r.text
        assert r.json()["pending"]["status"] == "pending"
        assert await rows(op, "counterparties") == before           # a proposal, not a record
        for who in ("viewer-a", "tech-a"):                          # the catalog is not widened
            r = await c.post("/api/master-data/pending", headers=hdr(who), json={
                "entity_type": "organization", "raw_value": "X", "source_channel": "ocr"})
            assert r.status_code == 403
    import httpx

    async def go():
        async with _Dbs(backend) as (op, sysdb):
            await _bootstrap_indexes(op)
            await _seed(op, sysdb)
            app = app_with_master_data(monkeypatch, op, sysdb, mode)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://cp01") as c:
                return await scenario(c, op)
    asyncio.run(go())


def test_a6_cash_to_a_counterparty_needs_a_receipt(monkeypatch, backend, mode):
    async def scenario(c, op):
        await seed_account(op, "ba-ok", IBAN_OLD, "verified")
        cash = dict(counterparty_id="cp1", method="Cash", account_id=CASH_A)
        for extra in ({}, {"cash_receipt_file_id": "file_r"}, {"cash_recipient_name": "Иван"},
                      {"cash_receipt_file_id": "https://x/r.pdf", "cash_recipient_name": "Иван"}):
            r = await manual_pay(c, **cash, **extra)
            assert r.status_code == 422 and r.json()["detail"]["error_code"] == "CASH_RECEIPT_REQUIRED"
        assert await rows(op, "finance_payments") == []
        r = await manual_pay(c, **cash, cash_receipt_file_id="file_r1", cash_recipient_name="Иван Петров")
        assert r.status_code == 201, r.text
        assert r.json()["cash_receipt_file_id"] == "file_r1" and r.json()["cash_recipient_name"] == "Иван Петров"
        # R59: a small expense with no payee only with a till receipt
        r = await manual_pay(c, method="Cash", account_id=CASH_A, counterparty_name=None)
        assert r.status_code == 422 and r.json()["detail"]["error_code"] == "CASH_RECEIPT_REQUIRED"
        r = await manual_pay(c, method="Cash", account_id=CASH_A, counterparty_name=None,
                             cash_receipt_file_id="file_bon")
        assert r.status_code == 201 and r.json()["cash_expense_without_payee"] is True
        if backend != "real":       # #69's cap reservation uses $round: real Mongo only
            return
        # a subcontractor in cash: the same rule, and blocked while its IBAN is unverified
        body = {"package_id": "pkg1", "amount": 50.0, "payment_method": "cash", "account_id": CASH_A}
        r = await c.post("/api/subcontractor-payments", headers=hdr("acct-a"), json=body)
        assert r.status_code == 422, r.text
        body.update(cash_receipt_file_id="file_r2", cash_recipient_name="Бригадир")
        r = await c.post("/api/subcontractor-payments", headers=hdr("acct-a"), json=body)
        assert r.status_code == 201, r.text
        await seed_account(op, "ba-sub-new", IBAN_NEW, "pending_verification", party="sub1",
                           party_type="subcontractor")
        r = await c.post("/api/subcontractor-payments", headers=hdr("acct-a"), json=body)
        assert r.status_code == 409 and r.json()["detail"]["error_code"] == "PAYEE_BLOCKED_PENDING_IBAN"
    run(monkeypatch, backend, mode, scenario)


def test_a7_entrant_verifier_approvers_are_three_people(monkeypatch, backend, mode):
    async def scenario(c, op):
        old = (await register(c, IBAN_OLD, who="admin-a")).json()
        assert (await verify(c, old, who="owner-a")).status_code == 200
        new = (await register(c, IBAN_NEW, who="acct-a")).json()          # entrant: acct-a
        new = (await verify(c, new, who="owner-a")).json()                # verifier: owner-a
        url = "/api/bank-accounts/%s/approve-change" % new["id"]
        r = await c.post(url, headers=hdr("acct-a"), json={"version": new["version"]})
        assert r.status_code == 409 and r.json()["detail"]["error_code"] == "SAME_PERSON_APPROVAL"
        r = await c.post(url, headers=hdr("owner-a"), json={"version": new["version"]})
        assert r.status_code == 200, r.text                               # verifier = approver 1
        v = r.json()["version"]
        r = await c.post(url, headers=hdr("owner-a"), json={"version": v})
        assert r.status_code == 409 and r.json()["detail"]["error_code"] == "SAME_PERSON_APPROVAL"
        r = await c.post(url, headers=hdr("acct-a"), json={"version": v})
        assert r.status_code == 409 and r.json()["detail"]["error_code"] == "SAME_PERSON_APPROVAL"
        stored = [a for a in await rows(op, "verified_bank_accounts") if a["id"] == new["id"]][0]
        assert stored["status"] == "pending_verification" and len(stored["approvals"]) == 1
        r = await c.post(url, headers=hdr("acct2-a"), json={"version": v})
        assert r.status_code == 200 and r.json()["status"] == "verified"
        assert {a["approver_id"] for a in r.json()["approvals"]} == {"owner-a", "acct2-a"}
    run(monkeypatch, backend, mode, scenario)


def test_a8_unarchive_sends_the_iban_back_to_verification(monkeypatch, backend, mode):
    async def scenario(c, op):
        acc = (await register(c, IBAN_OLD, who="acct-a")).json()
        assert (await verify(c, acc, who="owner-a")).status_code == 200
        assert (await c.post("/api/counterparties/cp1/archive", headers=hdr("admin-a"),
                             json={"reason": "закрит"})).status_code == 200
        r = await c.post("/api/counterparties/cp1/reactivate", headers=hdr("acct-a"), json={"reason": "x"})
        assert r.status_code == 403                                       # Admin / Owner only
        r = await c.post("/api/counterparties/cp1/reactivate", headers=hdr("admin-a"), json={})
        assert r.status_code == 400                                       # a reason is required
        r = await c.post("/api/counterparties/cp1/reactivate", headers=hdr("admin-a"),
                         json={"reason": "отново работим"})
        assert r.status_code == 200 and r.json()["lifecycle_status"] == "active"
        stored = (await rows(op, "verified_bank_accounts"))[0]
        assert stored["status"] == "pending_verification" and stored["verification"] is None
        assert stored["reverification_reason"] == "unarchived"
        r = await manual_pay(c, counterparty_id="cp1")
        assert r.status_code == 409                                       # the old IBAN is not valid
        ev = [e["action"] for e in await rows(op, "audit_events")]
        assert "bank_account.reverification_required" in ev and "counterparty.reactivated" in ev
        assert (await verify(c, stored, who="owner-a")).json()["status"] == "verified"
        assert (await manual_pay(c, counterparty_id="cp1")).status_code == 201
    run(monkeypatch, backend, mode, scenario)



# ═══════════════════════════════════════════════ FLOW Guard pass 23 / audit (#83 @ ea51030)
async def _verified(op, acc_id, iban, party="cp1", party_type="counterparty"):
    await seed_account(op, acc_id, iban, "verified", party=party, party_type=party_type)


def test_fg225a_allocate_checks_the_payee_and_its_account(monkeypatch, backend, mode):
    async def scenario(c, op):
        await _verified(op, "ba-cp1", IBAN_OLD)
        await _verified(op, "ba-cp2", IBAN_NEW, party="cp2")
        await op.invoices.update_one({"id": "inv-r1"}, {"$set": {"counterparty_iban": IBAN_OLD}})
        url = "/api/finance/payments/%s/allocate"
        alloc = {"allocations": [{"invoice_id": "inv-r1", "amount": 50.0}]}
        # a payment to cp2 (its own verified account) is never allocated to cp1's invoice
        p2 = (await manual_pay(c, counterparty_id="cp2")).json()
        assert p2["bank_account_id"] == "ba-cp2"
        r = await c.post(url % p2["id"], headers=hdr("acct-a"), json=alloc)
        assert r.status_code == 409 and r.json()["detail"]["reason"] == "PAYEE_MISMATCH", r.text
        # a payment of no counterparty that went to cp2's account → not this payee
        await op.finance_payments.update_one({"id": p2["id"]}, {"$unset": {"counterparty_id": ""}})
        r = await c.post(url % p2["id"], headers=hdr("acct-a"), json=alloc)
        assert r.status_code == 409 and r.json()["detail"]["error_code"] == "BANK_ACCOUNT_NOT_VERIFIED"
        assert await rows(op, "payment_allocations") == []
        # an invoice IBAN that differs from the account the payment went to → DQ + 409
        p1 = (await manual_pay(c, counterparty_id="cp1")).json()
        await op.invoices.update_one({"id": "inv-r1"}, {"$set": {"counterparty_iban": IBAN_OTHER}})
        r = await c.post(url % p1["id"], headers=hdr("acct-a"), json=alloc)
        assert r.status_code == 409 and r.json()["detail"]["reason"] == "INVOICE_IBAN_MISMATCH"
        assert await rows(op, "payment_allocations") == []
        # the right payee, its verified account, the invoice IBAN equal → allocated
        await op.invoices.update_one({"id": "inv-r1"}, {"$set": {"counterparty_iban": IBAN_OLD}})
        r = await c.post(url % p1["id"], headers=hdr("acct-a"), json=alloc)
        assert r.status_code == 200, r.text
        # a legacy payment that recorded no account → by mode (enforce refuses)
        await op.finance_payments.insert_one({
            "id": "pay-legacy", "org_id": ORG_A, "direction": "Outflow", "amount": 10.0,
            "currency": "EUR", "date": "2026-11-01", "method": "BankTransfer", "account_id": BANK_A})
        await op.invoices.update_one({"id": "inv-r1"}, {"$unset": {"counterparty_iban": ""}})
        r = await c.post(url % "pay-legacy", headers=hdr("acct-a"),
                         json={"allocations": [{"invoice_id": "inv-r1", "amount": 10.0}]})
        assert r.status_code == (409 if mode == "enforce" else 200), r.text
        # a cash payment without a receipt is not allocated to a counterparty's invoice
        await op.finance_payments.insert_one({
            "id": "pay-cash", "org_id": ORG_A, "direction": "Outflow", "amount": 10.0,
            "currency": "EUR", "date": "2026-11-01", "method": "Cash", "account_id": CASH_A})
        r = await c.post(url % "pay-cash", headers=hdr("acct-a"),
                         json={"allocations": [{"invoice_id": "inv-r1", "amount": 10.0}]})
        assert r.status_code == 422 and r.json()["detail"]["error_code"] == "CASH_RECEIPT_REQUIRED"
    run(monkeypatch, backend, mode, scenario)


def test_fg225b_the_account_decides_the_method(monkeypatch, backend, mode):
    async def scenario(c, op):
        # manual payment: "Cash" requested is routed to the Cash account → cash rules
        r = await manual_pay(c, counterparty_id="cp1", method="Cash", account_id=BANK_A)
        assert r.status_code == 422 and r.json()["detail"]["error_code"] == "CASH_RECEIPT_REQUIRED"
        # "BankTransfer" on the Cash account is cash too (the account decides)
        r = await manual_pay(c, counterparty_id="cp1", method="BankTransfer", account_id=CASH_A)
        assert r.status_code == 422 and r.json()["detail"]["error_code"] == "CASH_RECEIPT_REQUIRED"
        if backend != "real":       # #69's subcontractor cap reservation uses $round: real only
            return
        # subcontractor: payment_method "cash" on a BANK account is a bank transfer
        body = {"package_id": "pkg1", "amount": 30.0, "payment_method": "cash", "account_id": BANK_A,
                "cash_receipt_file_id": "file_r", "cash_recipient_name": "X"}
        r = await c.post("/api/subcontractor-payments", headers=hdr("acct-a"), json=body)
        assert r.status_code == (409 if mode == "enforce" else 201), r.text
        await seed_account(op, "ba-sub-p", IBAN_NEW, "pending_verification", party="sub1",
                           party_type="subcontractor")
        r = await c.post("/api/subcontractor-payments", headers=hdr("acct-a"), json=body)
        assert r.status_code == 409 and r.json()["detail"]["reason"] == "BANK_ACCOUNT_PENDING", r.text
    run(monkeypatch, backend, mode, scenario)


def test_fg225c_other_expense_by_bank_is_guarded(monkeypatch, backend, mode):
    async def scenario(c, op):
        base = {"amount": 40.0, "project_id": "prj-1", "method": "BankTransfer", "account_id": BANK_A}
        r = await c.post("/api/finance/other-expense", headers=hdr("acct-a"), json=base)
        assert r.status_code == (409 if mode == "enforce" else 201), r.text
        await seed_account(op, "ba-p", IBAN_NEW, "pending_verification")
        r = await c.post("/api/finance/other-expense", headers=hdr("acct-a"), json=dict(base, counterparty_id="cp1"))
        assert r.status_code == 409 and r.json()["detail"]["reason"] == "BANK_ACCOUNT_PENDING"
        await _verified(op, "ba-v", IBAN_OLD, party="cp2")
        r = await c.post("/api/finance/other-expense", headers=hdr("acct-a"), json=dict(base, counterparty_id="cp2"))
        assert r.status_code == 201, r.text
        row = [p for p in await rows(op, "finance_payments") if p["id"] == r.json()["id"]][0]
        assert row["bank_account_id"] == "ba-v" and row["counterparty_id"] == "cp2"
        # in cash to a named counterparty: the receipt (R50.1)
        cash = {"amount": 5.0, "project_id": "prj-1", "method": "Cash", "counterparty_id": "cp2"}
        r = await c.post("/api/finance/other-expense", headers=hdr("acct-a"), json=cash)
        assert r.status_code == 422
        r = await c.post("/api/finance/other-expense", headers=hdr("acct-a"),
                         json=dict(cash, cash_receipt_file_id="file_x", cash_recipient_name="Y"))
        assert r.status_code == 201
    run(monkeypatch, backend, mode, scenario)


def test_fg226_a_stored_project_never_holds_a_full_egn(monkeypatch, backend, mode):
    async def scenario(c, op):
        # the canonical person pe1 holds this ЕГН → the copy is redundant and stored masked
        r = await c.put("/api/projects/prj-1", headers=hdr("admin-a"),
                        json={"invoice_details": {"company_name": "Мария П", "eik": EGN}})
        assert r.status_code == 200, r.text
        assert no_full(r.json(), EGN)
        prj = (await rows(op, "projects", {"id": "prj-1"}))[0]
        assert prj["invoice_details"]["eik"] == EGN_MASKED
        # CP83-03: a typed ЕГН with no canonical record is NOT destroyed — kept, masked on read,
        # DQ issue „ЕГН копие без каноничен запис“ for the Accountant
        other = "7501011111"
        r = await c.put("/api/projects/prj-1", headers=hdr("admin-a"),
                        json={"invoice_details": {"company_name": "Мария П", "eik": other}})
        assert r.status_code == 200 and no_full(r.json(), other)
        prj = (await rows(op, "projects", {"id": "prj-1"}))[0]
        assert prj["invoice_details"]["eik"] == other
        for who in ("viewer-a", "site-a", "admin-a"):
            for url in ("/api/projects/prj-1/invoice-details", "/api/projects", "/api/projects/prj-1"):
                got = await c.get(url, headers=hdr(who))
                if got.status_code == 200:
                    assert no_full(got.json(), other), (who, url)
        dq = await rows(op, "dq_issues", {"type": "EGN_COPY_WITHOUT_CANONICAL"})
        assert len(dq) == 1 and dq[0]["title"] == "ЕГН копие без каноничен запис"
        # a company's 10-digit tax id (e.g. a foreign VAT number) is never masked as an ЕГН
        await op.projects.update_one({"id": "prj-1"}, {"$set": {"owner_type": "company", "owner_id": "co1"}})
        r = await c.put("/api/projects/prj-1", headers=hdr("admin-a"),
                        json={"invoice_details": {"company_name": "Foreign GmbH", "eik": "1234567890"}})
        assert r.status_code == 200 and r.json()["invoice_details"]["eik"] == "1234567890"
        got = await c.get("/api/projects/prj-1/invoice-details", headers=hdr("admin-a"))
        assert got.json()["invoice_details"]["eik"] == "1234567890"
    run(monkeypatch, backend, mode, scenario)


def test_cp83_02_other_income_is_never_blocked(monkeypatch, backend, mode):
    """CP83-02: income is not a payment to a payee — no IBAN / receipt guard, in every mode."""
    async def scenario(c, op):
        await seed_account(op, "ba-pend", IBAN_NEW, "pending_verification")   # even a blocked payee
        for body in ({"method": "BankTransfer", "account_id": BANK_A},
                     {"method": "Cash", "account_id": BANK_A},               # PaymentsPage default
                     {"method": "Cash", "account_id": CASH_A},
                     {"method": "BankTransfer", "account_id": BANK_A, "counterparty_id": "cp1"},
                     {"method": "Cash", "account_id": CASH_A, "counterparty_id": "cp1"}):
            r = await c.post("/api/finance/other-income", headers=hdr("acct-a"),
                             json=dict(body, amount=25.0, project_id="prj-1"))
            assert r.status_code == 201, (body, r.text)
        assert len(await rows(op, "finance_payments", {"direction": "Inflow"})) == 5
    run(monkeypatch, backend, mode, scenario)


def test_fg227_search_by_full_egn_only_for_owner_and_accountant(monkeypatch, backend, mode):
    async def scenario(c, op):
        url = "/api/clients/search/unified?type=person&query=" + EGN
        for who in ("viewer-a", "site-a", "tech-a", "admin-a"):
            r = await c.get(url, headers=hdr(who))
            assert r.status_code == 200 and r.json()["total"] == 0, (who, r.text)
        for who in ("owner-a", "acct-a"):
            r = await c.get(url, headers=hdr(who))
            assert r.json()["total"] == 1 and r.json()["items"][0]["identifier"] == EGN_MASKED
    run(monkeypatch, backend, mode, scenario)


def test_fg227_master_data_report_uses_the_one_egn_mask():
    from app.master_data.uniqueness import mask_value
    assert mask_value("egn", "egn:8001011234") == "egn:******1234"
    assert mask_value("egn", "8001011234") == "******1234"


def test_fg229_subcontractor_eik_is_one_per_organisation(monkeypatch, backend, mode):
    async def scenario(c, op):
        before = await rows(op, "subcontractors")
        r = await c.post("/api/subcontractors", headers=hdr("acct-a"), json={"name": "S", "eik": "111111111"})
        assert r.status_code == 409 and r.json()["detail"]["error_code"] == "EIK_ALREADY_EXISTS", r.text
        assert await rows(op, "subcontractors") == before        # the ЕИК of counterparty cp1
        dq = await rows(op, "dq_issues", {"type": "DUPLICATE_EIK"})
        assert len(dq) == 1 and dq[0]["entity_id"] == "cp1"
        r = await c.post("/api/subcontractors", headers=hdr("acct-a"), json={"name": "S2", "eik": "565656565"})
        assert r.status_code == 201, r.text
        r = await c.post("/api/subcontractors", headers=hdr("acct-a"), json={"name": "S3", "eik": "565 656 565"})
        assert r.status_code == 409
        r = await c.post("/api/counterparties", headers=hdr("acct-a"), json={"name": "C", "eik": "565656565"})
        assert r.status_code == 409 and r.json()["detail"]["error_code"] == "EIK_ALREADY_EXISTS"
    run(monkeypatch, backend, mode, scenario)


def test_fg230_dq_rows_have_the_one_schema_of_81(monkeypatch, backend, mode):
    async def scenario(c, op):
        await c.post("/api/counterparties", headers=hdr("acct-a"), json={"name": "Д", "eik": "111111111"})
        row = (await rows(op, "dq_issues"))[0]
        for field in ("id", "org_id", "type", "title", "entity_type", "entity_id", "status",
                      "owner_role", "opened_at", "updated_at"):
            assert row.get(field) is not None, (field, row)
        assert row["status"] == "open" and row["owner_role"] == "accountant" and row["org_id"] == ORG_A
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════ FLOW Guard pass 24 (#83 @ 7e0b914)
def test_fg242_r59_cash_to_a_named_payee_needs_a_counterparty_from_the_list(monkeypatch, backend, mode):
    """R59 (Krum, 08.11.2026, FG-242/FG-268): cash to a company or person only with a
    counterparty_id chosen from the list; a name or ЕИК alone → 422 COUNTERPARTY_REQUIRED;
    a small expense with no payee only with a till receipt; the R50.1 block always."""
    async def scenario(c, op):
        cash = dict(method="Cash", account_id=CASH_A, cash_receipt_file_id="file_r",
                    cash_recipient_name="Иван")
        before = await rows(op, "finance_payments")
        for extra in ({"counterparty_name": "Някой Друг"}, {"counterparty_name": "Доставчик cp1"},
                      {"counterparty_name": "DOSTAVCHIK  CP1 OOD"},
                      {"counterparty_name": "Доставчк cp1"},                    # FG-268: a typo
                      {"counterparty_name": "Dostavchik cp1"},                  # FG-268: Latin spelling
                      {"counterparty_name": None, "counterparty_eik": "999999999"},   # unknown ЕИК
                      {"counterparty_name": "Доставчик cp1", "counterparty_eik": "999999999"},
                      {"counterparty_name": None, "counterparty_eik": "111111111"}):
            r = await manual_pay(c, **dict(cash, **extra))
            assert r.status_code == 422 and r.json()["detail"]["error_code"] == "COUNTERPARTY_REQUIRED", (extra, r.text)
        r = await c.post("/api/finance/other-expense", headers=hdr("acct-a"), json=dict(
            cash, amount=5.0, project_id="prj-1", counterparty_name="Доставчик cp1"))
        assert r.status_code == 422 and r.json()["detail"]["error_code"] == "COUNTERPARTY_REQUIRED"
        await op.invoices.update_one({"id": "inv-r1"}, {"$unset": {"supplier_counterparty_id": "",
                                                                    "counterparty_eik": ""}})
        r = await c.post("/api/finance/invoices/inv-r1/payments", headers=hdr("acct-a"),
                         json=dict(cash, amount=5.0))          # an invoice linked to no counterparty
        assert r.status_code == 422 and r.json()["detail"]["error_code"] == "COUNTERPARTY_REQUIRED"
        assert await rows(op, "finance_payments") == before
        # every variant above with no receipt is refused too, and nothing is written
        for extra in ({"counterparty_name": "Доставчк cp1"}, {"counterparty_name": "Dostavchik cp1"},
                      {"counterparty_name": None, "counterparty_eik": "999999999"}):
            r = await manual_pay(c, method="Cash", account_id=CASH_A, **extra)
            assert r.status_code == 422, (extra, r.text)
        # the counterparty chosen from the list but no receipt → 422, nothing written
        r = await manual_pay(c, counterparty_id="cp1", method="Cash", account_id=CASH_A)
        assert r.status_code == 422 and r.json()["detail"]["error_code"] == "CASH_RECEIPT_REQUIRED", r.text
        assert await rows(op, "finance_payments") == before
        # the counterparty chosen from the list: receipt + recipient → paid
        r = await manual_pay(c, counterparty_id="cp1", **cash)
        assert r.status_code == 201, r.text
        # … and blocked while its IBAN is unverified (R50.1), whatever is in the name
        await seed_account(op, "ba-pend", IBAN_NEW, "pending_verification")
        r = await manual_pay(c, counterparty_id="cp1", counterparty_name="Друго име", **cash)
        assert r.status_code == 409 and r.json()["detail"]["error_code"] == "PAYEE_BLOCKED_PENDING_IBAN"
        # a small expense with no payee: only with a till receipt
        r = await c.post("/api/finance/other-expense", headers=hdr("acct-a"), json={
            "amount": 3.0, "project_id": "prj-1", "method": "Cash"})
        assert r.status_code == 422 and r.json()["detail"]["error_code"] == "CASH_RECEIPT_REQUIRED"
        r = await c.post("/api/finance/other-expense", headers=hdr("acct-a"), json={
            "amount": 3.0, "project_id": "prj-1", "method": "Cash", "cash_receipt_file_id": "file_bon"})
        assert r.status_code == 201, r.text
        row = [p for p in await rows(op, "finance_payments") if p["id"] == r.json()["id"]][0]
        assert row["cash_expense_without_payee"] is True and row["cash_receipt_file_id"] == "file_bon"
    run(monkeypatch, backend, mode, scenario)


def test_fg243_unarchive_resets_a_pending_change_too(monkeypatch, backend, mode):
    async def scenario(c, op):
        old = (await register(c, IBAN_OLD, who="admin-a")).json()
        assert (await verify(c, old, who="owner-a")).status_code == 200
        new = (await register(c, IBAN_NEW, who="admin-a")).json()
        new = (await verify(c, new, who="acct-a")).json()                 # verified, awaiting approvals
        r = await c.post("/api/bank-accounts/%s/approve-change" % new["id"], headers=hdr("owner-a"),
                         json={"version": new["version"]})
        assert r.status_code == 200 and len(r.json()["approvals"]) == 1
        v = r.json()["version"]
        assert (await c.post("/api/counterparties/cp1/archive", headers=hdr("admin-a"),
                             json={"reason": "закрит"})).status_code == 200
        assert (await c.post("/api/counterparties/cp1/reactivate", headers=hdr("owner-a"),
                             json={"reason": "отново"})).status_code == 200
        accs = {a["id"]: a for a in await rows(op, "verified_bank_accounts")}
        for acc in accs.values():
            assert acc["status"] == "pending_verification" and acc["verification"] is None, acc
            assert acc["approvals"] == [] and acc["reverification_reason"] == "unarchived"
        # the second approval of the pre-archive version no longer activates anything
        r = await c.post("/api/bank-accounts/%s/approve-change" % new["id"], headers=hdr("acct2-a"),
                         json={"version": v})
        assert r.status_code == 409, r.text
        assert accs[new["id"]]["status"] == "pending_verification"
        assert (await manual_pay(c, counterparty_id="cp1")).status_code == 409
        ev = await rows(op, "audit_events", {"action": "bank_account.reverification_required"})
        assert {e["entity_id"] for e in ev} == {old["id"], new["id"]}
    run(monkeypatch, backend, mode, scenario)


def test_fg244_subcontractor_deactivate_archive_reactivate(monkeypatch, backend, mode):
    async def scenario(c, op):
        url = "/api/subcontractors/sub1/%s"
        assert (await c.post(url % "deactivate", headers=hdr("site-a"), json={"reason": "x"})).status_code == 403
        assert (await c.post(url % "deactivate", headers=hdr("acct-a"), json={})).status_code == 400
        r = await c.post(url % "deactivate", headers=hdr("acct-a"), json={"reason": "пауза"})
        assert r.status_code == 200 and r.json()["lifecycle_status"] == "inactive"
        r = await c.post("/api/subcontractor-payments", headers=hdr("acct-a"), json={
            "package_id": "pkg1", "amount": 10.0, "payment_method": "cash", "account_id": CASH_A,
            "cash_receipt_file_id": "f", "cash_recipient_name": "n"})
        assert r.status_code == 422 and r.json()["detail"]["error_code"] == "COUNTERPARTY_NOT_SELECTABLE"
        assert (await c.post(url % "reactivate", headers=hdr("acct-a"), json={"reason": "ок"})).status_code == 200
        assert (await c.post(url % "archive", headers=hdr("acct-a"), json={"reason": "стар"})).status_code == 403
        assert (await c.post(url % "archive", headers=hdr("admin-a"), json={"reason": "стар"})).status_code == 200
        listed = (await c.get("/api/subcontractors", headers=hdr("acct-a"))).json()
        assert "sub1" not in {s["id"] for s in listed}
        listed = (await c.get("/api/subcontractors?include_archived=true", headers=hdr("acct-a"))).json()
        assert "sub1" in {s["id"] for s in listed}
        assert (await c.post(url % "reactivate", headers=hdr("acct-a"), json={"reason": "y"})).status_code == 403
        assert (await c.post(url % "reactivate", headers=hdr("owner-a"), json={"reason": "y"})).status_code == 200
        acts = [e["action"] for e in await rows(op, "audit_events", {"entity_id": "sub1"})]
        assert acts == ["subcontractor.deactivated", "subcontractor.reactivated",
                        "subcontractor.archived", "subcontractor.reactivated"]
        assert len(await rows(op, "subcontractors", {"id": "sub1"})) == 1    # never deleted
    run(monkeypatch, backend, mode, scenario)


@pytest.mark.parametrize("who,full", [("owner-a", True), ("acct-a", True), ("admin-a", False),
                                      ("viewer-a", False), ("site-a", False), ("tech-a", False)])
def test_fg245_legacy_iban_fields_masked_by_role(monkeypatch, backend, mode, who, full):
    async def scenario(c, op):
        await op.counterparties.update_one({"id": "cp1"}, {"$set": {"iban": IBAN_OLD}})
        await op.subcontractors.update_one({"id": "sub1"}, {"$set": {"bank_iban": IBAN_NEW}})
        await op.projects.update_one({"id": "prj-1"}, {"$set": {"invoice_details.iban": IBAN_OTHER}})
        await op.invoices.update_one({"id": "inv-r1"}, {"$set": {"counterparty_iban": IBAN_OLD}})
        readers = ["/api/counterparties?active_only=false", "/api/counterparties/cp1",
                   "/api/subcontractors", "/api/subcontractors/sub1", "/api/projects",
                   "/api/projects/prj-1", "/api/projects/prj-1/invoice-details",
                   "/api/finance/invoices", "/api/finance/invoices/inv-r1",
                   "/api/reports/turnover-by-counterparty/cp1/invoices"]
        seen = 0
        for url in readers:
            r = await c.get(url, headers=hdr(who))
            if r.status_code != 200:
                continue
            text = json.dumps(r.json(), ensure_ascii=False)
            for iban in (IBAN_OLD, IBAN_NEW, IBAN_OTHER):
                if full:
                    continue
                assert iban not in text, (who, url)
            seen += 1
        assert seen >= 3, (who, seen)
        if full:   # the full value is there for Owner / Accountant
            r = await c.get("/api/counterparties/cp1", headers=hdr(who))
            assert r.json()["iban"] == IBAN_OLD
        if who == "admin-a":     # an Admin with the explicit sensitive right sees it
            from app.tenancy import registry
            await registry.tenant_role_assignments.update_one(
                {"id": "ra_admin-a"}, {"$set": {"permissions": ["sensitive.iban.read"]}})
            r = await c.get("/api/counterparties/cp1", headers=hdr(who))
            assert r.json()["iban"] == IBAN_OLD
    run(monkeypatch, backend, mode, scenario)


def test_fg245_a_masked_form_value_never_overwrites_the_stored_iban(monkeypatch, backend, mode):
    async def scenario(c, op):
        await op.projects.update_one({"id": "prj-1"}, {"$set": {"invoice_details.iban": IBAN_OTHER}})
        shown = (await c.get("/api/projects/prj-1/invoice-details", headers=hdr("admin-a"))).json()
        assert shown["invoice_details"]["iban"] == "****" + IBAN_OTHER[-4:]
        r = await c.put("/api/projects/prj-1", headers=hdr("admin-a"),
                        json={"invoice_details": dict(shown["invoice_details"], company_name="Ново")})
        assert r.status_code == 200, r.text
        prj = (await rows(op, "projects", {"id": "prj-1"}))[0]
        assert prj["invoice_details"]["iban"] == IBAN_OTHER and prj["invoice_details"]["company_name"] == "Ново"
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════ FLOW Guard pass 26 (#83 @ bc0d1c7)
TYPED = "7501011111"        # a typed ЕГН with no canonical persons record


def test_fg266_a_typed_egn_never_reaches_logs_or_responses(monkeypatch, backend, mode):
    async def scenario(c, op):
        r = await c.put("/api/projects/prj-1", headers=hdr("admin-a"),
                        json={"invoice_details": {"company_name": "Мария П", "eik": TYPED,
                                                  "iban": IBAN_OTHER}})
        assert r.status_code == 200 and no_full(r.json(), TYPED) and no_full(r.json(), IBAN_OTHER)
        logs = await rows(op, "audit_logs")
        assert logs and no_full(logs, TYPED) and no_full(logs, IBAN_OTHER), logs
        assert no_full(await rows(op, "audit_events"), TYPED)
        # the stored copy is kept (CP83-03) and a DQ issue is open
        assert (await rows(op, "projects", {"id": "prj-1"}))[0]["invoice_details"]["eik"] == TYPED
        assert await rows(op, "dq_issues", {"type": "EGN_COPY_WITHOUT_CANONICAL"})
        # the create response is a reader too
        r = await c.post("/api/projects", headers=hdr("admin-a"), json={
            "code": "P-266", "name": "P-266", "owner_type": "person", "owner_id": "pe1",
            "invoice_details": {"company_name": "X", "eik": TYPED}})
        assert r.status_code == 201, r.text
        assert no_full(r.json(), TYPED)
        # /audit-logs (platform admin) masks rows written before CP-01 on read
        await op.audit_logs.insert_one({"id": "old-row", "org_id": ORG_A, "action": "updated",
                                        "timestamp": "2026-01-01", "changes": {
                                            "invoice_details": {"eik": TYPED, "iban": IBAN_OLD}}})
        from app.routes import auth as r_auth
        monkeypatch.setattr(r_auth, "db", op)
        got = await r_auth.list_audit_logs(user={"id": "admin-a", "org_id": ORG_A, "role": "Admin"},
                                           limit=50, skip=0)
        assert got["total"] >= 2 and no_full(got, TYPED) and no_full(got, IBAN_OLD)
    run(monkeypatch, backend, mode, scenario)


@pytest.mark.parametrize("who", ["owner-a", "acct-a", "admin-a", "viewer-a", "site-a", "tech-a"])
def test_fg267_a_possible_egn_without_a_company_owner_is_masked(monkeypatch, backend, mode, who):
    """FG-267 + FG-275 (pass 28): a possible ЕГН is masked in every ordinary read, for every
    role; a company's 10-digit tax id is shown only when the owner is an existing company of
    THIS tenant — not for an unknown id or another tenant's company."""
    async def scenario(c, op):
        await op.projects.insert_one({"id": "prj-none", "org_id": ORG_A, "code": "N", "name": "N",
                                      "status": "Active", "invoice_details": {"eik": TYPED}})
        await op.projects.insert_one({"id": "prj-co", "org_id": ORG_A, "code": "C", "name": "C",
                                      "status": "Active", "owner_type": "company", "owner_id": "co1",
                                      "invoice_details": {"eik": "1234567890"}})   # a foreign VAT id
        await op.project_team.insert_many([
            {"id": "pt-%s-%s" % (p, u), "org_id": ORG_A, "project_id": p, "user_id": u,
             "active": True, "role_in_project": "SiteManager"}
            for p in ("prj-none", "prj-co") for u in ("site-a", "tech-a", "viewer-a")])
        seen = 0
        for url in ("/api/projects/prj-none", "/api/projects/prj-none/invoice-details", "/api/projects"):
            r = await c.get(url, headers=hdr(who))
            if r.status_code != 200:
                continue
            seen += 1
            assert TYPED not in json.dumps(r.json()), (who, url)
        assert seen >= 1, who
        r = await c.get("/api/projects/prj-co/invoice-details", headers=hdr(who))
        if r.status_code == 200:      # a confirmed company's 10-digit tax id is never masked
            assert r.json()["invoice_details"]["eik"] == "1234567890"
        # FG-267 remaining: owner_type=company alone is not a company
        await op.companies.insert_one({"id": "co-b", "org_id": ORG_B, "name": "B", "eik": "777777777"})
        for owner_id in ("co-missing", "co-b", "pe1"):
            await op.projects.update_one({"id": "prj-co"}, {"$set": {"owner_id": owner_id}})
            for url in ("/api/projects/prj-co", "/api/projects/prj-co/invoice-details", "/api/projects"):
                r = await c.get(url, headers=hdr(who))
                if r.status_code == 200:
                    assert "1234567890" not in json.dumps(r.json()), (who, owner_id, url)
    run(monkeypatch, backend, mode, scenario)


def test_fg275_owner_and_accountant_see_the_full_egn_only_by_reveal(monkeypatch, backend, mode):
    """FG-275 (R48.3): ordinary reads and write responses are masked for Owner / Accountant
    too; the full ЕГН only via /reveal, which writes an AuditEvent first."""
    async def scenario(c, op):
        await op.projects.update_one({"id": "prj-1"}, {"$set": {
            "owner_type": "person", "owner_id": "pe1", "invoice_details": {"eik": EGN, "egn": TYPED}}})
        for who in ("owner-a", "acct-a"):
            seen = 0
            for url in ("/api/projects", "/api/projects/prj-1", "/api/projects/prj-1/invoice-details",
                        "/api/persons/pe1"):
                r = await c.get(url, headers=hdr(who))
                if r.status_code != 200:          # a reader this role may not use at all
                    continue
                seen += 1
                assert no_full(r.json(), EGN) and no_full(r.json(), TYPED), (who, url)
            assert seen >= 3, (who, seen)
        r = await c.put("/api/projects/prj-1", headers=hdr("owner-a"),
                        json={"invoice_details": {"company_name": "M", "eik": TYPED}})
        assert r.status_code == 200 and no_full(r.json(), TYPED), r.text
        r = await c.post("/api/projects", headers=hdr("owner-a"), json={
            "code": "P-275", "name": "P-275", "owner_type": "person", "owner_id": "pe1",
            "invoice_details": {"company_name": "X", "eik": TYPED}})
        assert r.status_code == 201 and no_full(r.json(), TYPED), r.text
        assert await rows(op, "audit_events", {"action": "person.egn.revealed"}) == []
        for who in ("owner-a", "acct-a"):
            r = await c.post("/api/persons/pe1/egn/reveal", headers=hdr(who))
            assert r.status_code == 200 and r.json()["egn"] == EGN, r.text
        ev = await rows(op, "audit_events", {"action": "person.egn.revealed"})
        assert len(ev) == 2 and no_full(ev, EGN)
        r = await c.post("/api/persons/pe1/egn/reveal", headers=hdr("admin-a"))
        assert r.status_code == 403
    run(monkeypatch, backend, mode, scenario)


def test_fg268_r59_the_eik_stays_a_defence(monkeypatch, backend, mode):
    """R59 keeps the ЕИК check: an ЕИК of another counterparty → 409; a bank transfer
    named only by ЕИК resolves the payee, so its unverified IBAN blocks it."""
    async def scenario(c, op):
        cash = dict(method="Cash", account_id=CASH_A, cash_receipt_file_id="file_r",
                    cash_recipient_name="Иван")
        r = await manual_pay(c, counterparty_id="cp2", counterparty_eik="111111111", **cash)
        assert r.status_code == 409 and r.json()["detail"]["reason"] == "PAYEE_MISMATCH"
        r = await manual_pay(c, counterparty_id="cp2", counterparty_eik="111111111")     # bank
        assert r.status_code == 409 and r.json()["detail"]["reason"] == "PAYEE_MISMATCH"
        await seed_account(op, "ba-pend", IBAN_NEW, "pending_verification")             # cp1
        r = await manual_pay(c, counterparty_name="X", counterparty_eik="111 111 111")   # bank
        assert r.status_code == 409 and r.json()["detail"]["reason"] == "BANK_ACCOUNT_PENDING"
        assert await rows(op, "finance_payments") == []
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════ FLOW Guard pass 30 (#83 @ 1e455e3)
def test_fg290_the_cash_receipt_is_a_file_of_this_tenant(monkeypatch, backend, mode):
    """FG-290: the till receipt / cash document ``file_id`` must be a file record of THIS
    tenant in an active state (legacy media_files until W0-06) — an invented id ("zzz"),
    another tenant's file or a deleted one → 422 CASH_RECEIPT_NOT_REGISTERED, nothing written."""
    async def scenario(c, op):
        await seed_account(op, "ba-ok", IBAN_OLD, "verified")
        await op.media_files.insert_one({"id": "file_gone", "org_id": ORG_A, "filename": "g.jpg",
                                         "status": "deleted"})
        before = await rows(op, "finance_payments")
        for fid in ("zzz", "file_b", "file_gone"):
            # a small expense with no payee
            r = await c.post("/api/finance/other-expense", headers=hdr("acct-a"), json={
                "amount": 3.0, "project_id": "prj-1", "method": "Cash", "cash_receipt_file_id": fid})
            assert r.status_code == 422 and \
                r.json()["detail"]["error_code"] == "CASH_RECEIPT_NOT_REGISTERED", (fid, r.text)
            r = await manual_pay(c, method="Cash", account_id=CASH_A, counterparty_name=None,
                                 cash_receipt_file_id=fid)
            assert r.status_code == 422, (fid, r.text)
            # a counterparty from the list
            r = await manual_pay(c, counterparty_id="cp1", method="Cash", account_id=CASH_A,
                                 cash_receipt_file_id=fid, cash_recipient_name="Иван")
            assert r.status_code == 422 and \
                r.json()["detail"]["error_code"] == "CASH_RECEIPT_NOT_REGISTERED", (fid, r.text)
        assert await rows(op, "finance_payments") == before
        # the tenant's own active file → paid
        r = await c.post("/api/finance/other-expense", headers=hdr("acct-a"), json={
            "amount": 3.0, "project_id": "prj-1", "method": "Cash", "cash_receipt_file_id": "file_bon"})
        assert r.status_code == 201, r.text
        if backend != "real":       # #69's cap reservation uses $round: real Mongo only
            return
        body = {"package_id": "pkg1", "amount": 5.0, "payment_method": "cash", "account_id": CASH_A,
                "cash_receipt_file_id": "zzz", "cash_recipient_name": "Бригадир"}
        r = await c.post("/api/subcontractor-payments", headers=hdr("acct-a"), json=body)
        assert r.status_code == 422 and \
            r.json()["detail"]["error_code"] == "CASH_RECEIPT_NOT_REGISTERED", r.text
        assert await rows(op, "subcontractor_payments") == []
    run(monkeypatch, backend, mode, scenario)


def test_fg294_an_invoice_egn_is_masked_for_every_role_and_revealed_with_an_audit(monkeypatch, backend, mode):
    """FG-294 (R48.3): an invoice to a natural person carries the ЕГН in ``counterparty_eik``.
    Every invoice read / write response masks it for EVERY role (Admin, Owner, Accountant);
    the full value only via POST /finance/invoices/{id}/egn/reveal (Owner / Accountant), which
    writes ``invoice.egn.revealed`` first. A masked value sent back by the form keeps it."""
    async def scenario(c, op):
        await op.invoices.insert_one({
            "id": "inv-p", "org_id": ORG_A, "invoice_no": "I-P", "direction": "Issued", "kind": "Invoice",
            "status": "Sent", "issue_date": "2026-11-01", "due_date": "2099-12-31", "currency": "EUR",
            "project_id": "prj-1", "counterparty_name": "Мария П", "counterparty_eik": TYPED,
            "lines": [], "subtotal": 10.0, "vat_percent": 0, "vat_amount": 0, "total": 10.0,
            "paid_amount": 0, "remaining_amount": 10.0})
        await op.invoice_versions.insert_one({"id": "iv-1", "org_id": ORG_A, "invoice_id": "inv-p",
                                              "version_no": 1, "snapshot": {"counterparty_eik": TYPED}})
        readers = ["/api/finance/invoices", "/api/finance/invoices/inv-p",
                   "/api/finance/invoices/inv-p/versions", "/api/clients/pe1/invoices"]
        for who in ("owner-a", "acct-a", "admin-a"):
            seen = 0
            for url in readers:
                r = await c.get(url, headers=hdr(who))
                if r.status_code != 200:
                    continue
                seen += 1
                assert no_full(r.json(), TYPED), (who, url)
            assert seen >= 3, (who, seen)
        # a write response (the API refuses a NEW 10-digit ЕИК — 9 or 13 digits — so an ЕГН
        # reaches an invoice only from legacy / imported data, as seeded here)
        shown = (await c.get("/api/finance/invoices/inv-p", headers=hdr("acct-a"))).json()
        r = await c.put("/api/finance/invoices/inv-p", headers=hdr("acct-a"), json={
            "counterparty_eik": shown["counterparty_eik"], "notes": "ново"})
        assert r.status_code == 200 and no_full(r.json(), TYPED), r.text
        stored = (await rows(op, "invoices", {"id": "inv-p"}))[0]
        assert stored["counterparty_eik"] == TYPED and stored["notes"] == "ново"   # not overwritten
        # no reveal yet → no AuditEvent; then the reveal: Owner / Accountant, audited
        assert await rows(op, "audit_events", {"action": "invoice.egn.revealed"}) == []
        for who in ("admin-a", "site-a", "viewer-a"):
            r = await c.post("/api/finance/invoices/inv-p/egn/reveal", headers=hdr(who))
            assert r.status_code == 403, (who, r.text)
        for who in ("owner-a", "acct-a"):
            r = await c.post("/api/finance/invoices/inv-p/egn/reveal", headers=hdr(who))
            assert r.status_code == 200 and r.json()["counterparty_eik"] == TYPED, r.text
        ev = await rows(op, "audit_events", {"action": "invoice.egn.revealed"})
        assert len(ev) == 2 and {e["entity_id"] for e in ev} == {"inv-p"} and no_full(ev, TYPED)
        r = await c.post("/api/finance/invoices/inv-missing/egn/reveal", headers=hdr("owner-a"))
        assert r.status_code == 404
        # a company's 9-digit ЕИК is not an ЕГН — shown as it is
        r = await c.get("/api/finance/invoices/inv-r1", headers=hdr("acct-a"))
        assert r.json().get("counterparty_eik") in (None, "111111111")
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════ R65 (Krum, 09.11.2026, CP-01 D11)
def test_r65_invoice_pdf_with_an_egn_only_owner_accountant_and_audited(monkeypatch, backend, mode):
    """R65: the PDF of an invoice to a natural person is the official document and carries
    the FULL ЕГН; only Owner / Accountant download it (Admin and the rest → 403, nothing
    written); every download writes ``invoice.pdf.downloaded`` (who, when, which invoice).
    A company invoice's PDF is unchanged (Admin may download it, no audit)."""
    async def scenario(c, op):
        await op.invoices.insert_one({
            "id": "inv-p", "org_id": ORG_A, "invoice_no": "I-P", "direction": "Issued", "kind": "Invoice",
            "status": "Sent", "issue_date": "2026-11-01", "due_date": "2099-12-31", "currency": "EUR",
            "counterparty_name": "Мария П", "counterparty_eik": TYPED,
            "lines": [{"description": "СМР", "qty": 1, "unit_price": 10.0, "line_total": 10.0}],
            "subtotal": 10.0, "vat_percent": 0, "vat_amount": 0, "total": 10.0,
            "paid_amount": 0, "remaining_amount": 10.0})
        url = "/api/finance/invoices/inv-p/pdf"
        for who in ("admin-a", "site-a", "viewer-a", "tech-a"):
            r = await c.get(url, headers=hdr(who))
            assert r.status_code == 403, (who, r.status_code)
        assert await rows(op, "audit_events", {"action": "invoice.pdf.downloaded"}) == []
        for who in ("owner-a", "acct-a"):
            r = await c.get(url, headers=hdr(who))
            assert r.status_code == 200 and r.headers["content-type"].startswith("application/pdf"), \
                (who, r.status_code, r.text[:200])
        ev = await rows(op, "audit_events", {"action": "invoice.pdf.downloaded"})
        assert len(ev) == 2 and {e["entity_id"] for e in ev} == {"inv-p"}
        assert {e["actor_id"] for e in ev} == {"owner-a", "acct-a"} and no_full(ev, TYPED)
        assert all(e.get("timestamp") or e.get("occurred_at") or e.get("created_at") for e in ev), ev
        # another tenant's invoice is not found; a company invoice is unchanged
        r = await c.get("/api/finance/invoices/inv-p/pdf", headers=hdr("owner-b"))
        assert r.status_code == 404
        r = await c.get("/api/finance/invoices/inv-r1/pdf", headers=hdr("admin-a"))
        assert r.status_code == 200, r.text[:200]
        assert len(await rows(op, "audit_events", {"action": "invoice.pdf.downloaded"})) == 2
    run(monkeypatch, backend, mode, scenario)
