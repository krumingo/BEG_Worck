"""
INV-CN-01 — invoices locked at issue, cancellation, credit / debit notes (FLOW-006).

Package ``docs/architecture/tasks/INV-CN-01_CREDIT_DEBIT_NOTES.md`` (branch
claude/happy-meitner-bmcnel @ 344c197); decisions Р49 (+ Р47); oracle Q004.

Real MongoDB only (``W0_03_REAL_MONGO_URL``, a disposable LOCAL replica set): every
write here is a multi-document transaction, and the concurrency cases are only
meaningful on a real server. Every scenario runs in PERMISSION_SERVICE_MODE off /
shadow / enforce.

The ``test_main_*`` cases are the proof on main cd03324: there an issued / paid
invoice is edited, cancelled after sending, and a numbered invoice is deleted.

    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27017/?replicaSet=rs0' \\
        PYTHONPATH=. pytest tests/test_inv_cn_01_credit_notes.py -q --noconftest -p no:cacheprovider
"""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests.test_r0_05_pay_run_selected_only import _real_refusal, _token

pytestmark = pytest.mark.skipif(bool(_real_refusal()) or not os.environ.get("W0_03_REAL_MONGO_URL"),
                                reason="INV-CN-01 needs a disposable local replica-set MongoDB")

ORG_A, ORG_B = "ORG-INVCN-A", "ORG-INVCN-B"
USERS = {
    "owner-a": (ORG_A, "Owner"), "admin-a": (ORG_A, "Admin"), "acct-a": (ORG_A, "Accountant"),
    "viewer-a": (ORG_A, "Viewer"), "site-a": (ORG_A, "SiteManager"), "admin-b": (ORG_B, "Admin"),
}
MODES = ["off", "shadow", "enforce"]
BANK_A = "acc-bank-a"
EIK = "175074752"          # a valid ЕИК (checksum) for the client / supplier


@pytest.fixture(params=MODES)
def mode(request):
    return request.param


def hdr(uid, key=None):
    org, role = USERS[uid]
    h = _token(uid, org, role)
    if key is None:
        key = "auto-" + uuid.uuid4().hex
    if key:
        h["Idempotency-Key"] = key
    return h


# ═══════════════════════════════════════════════════════════════════ harness
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
                                   "email": uid + "@invcn.example", "first_name": uid, "last_name": "T"})
        await sysdb.tenant_memberships.insert_one({"id": "tm_" + uid, "user_id": uid, "tenant_id": org,
                                                   "status": "active"})
        await sysdb.tenant_role_assignments.insert_one({
            "id": "ra_" + uid, "user_id": uid, "tenant_id": org, "role_id": LEGACY_ROLE_MAP[role],
            "scope_type": "company", "scope_id": None, "module": None, "permissions": [],
            "status": "active", "sync_source": "users.role"})
    for prj, org in (("prj-1", ORG_A), ("prj-2", ORG_A), ("prj-b", ORG_B)):
        await op.projects.insert_one({"id": prj, "org_id": org, "code": prj, "name": prj, "status": "Active"})
    await op.financial_accounts.insert_one({
        "id": BANK_A, "org_id": ORG_A, "name": "bank", "type": "Bank", "currency": "EUR",
        "opening_balance": 10000.0, "active": True, "is_default": True})
    for act_id, prj, status in (("act-1", "prj-1", "Accepted"), ("act-draft", "prj-1", "Draft"),
                                ("act-2", "prj-2", "Accepted")):
        await op.client_acts.insert_one({
            "id": act_id, "org_id": ORG_A, "project_id": prj, "act_number": act_id, "status": status,
            "lines": [{"id": "al-1", "activity_name": "СМР", "executed_qty": 10, "unit_price": 100,
                       "line_total": 1000}], "subtotal": 1000.0, "vat_percent": 20,
            "vat_amount": 200.0, "total": 1200.0})


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
    for module in (appdb, deps_auth, deps_modules, r_finance, project_pnl, u_audit):
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
    try:                                   # absent on main cd03324 (the proof run)
        from app.routes import invoice_corrections as r_corr
        app.include_router(r_corr.router, prefix="/api")
    except ImportError:
        pass
    return app


def run(monkeypatch, mode, scenario):
    import httpx
    from motor.motor_asyncio import AsyncIOMotorClient
    from tests.test_w0_03c_real_mongo import REAL_URL

    async def go():
        tag = uuid.uuid4().hex[:10]
        client = AsyncIOMotorClient(REAL_URL, serverSelectionTimeoutMS=5000)
        op, sysdb = client["invcn_op_" + tag], client["invcn_sys_" + tag]
        try:
            from app.audit.indexes import PLANNED_INDEXES
            for coll, keys, opts in PLANNED_INDEXES:
                await op[coll].create_index(keys, **opts)
            await _seed(op, sysdb)
            app = _app(monkeypatch, op, sysdb, mode)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://invcn", timeout=120) as c:
                return await scenario(c, op)
        finally:
            await client.drop_database(op.name)
            await client.drop_database(sysdb.name)
            client.close()
    return asyncio.run(go())


LINES = [{"description": "Кофраж", "unit": "m2", "qty": 10, "unit_price": 10},
         {"description": "Бетон", "unit": "m3", "qty": 5, "unit_price": 20}]


async def draft(c, *, direction="Issued", lines=LINES, project="prj-1", act_id=None, who="acct-a",
                vat=20.0):
    body = {"direction": direction, "invoice_no": "TYPED-1" if direction == "Issued" else
            "SUP-" + uuid.uuid4().hex[:6], "project_id": project, "counterparty_name": "Клиент ООД",
            "counterparty_eik": EIK, "issue_date": "2026-11-08", "due_date": "2099-12-31",
            "vat_percent": vat, "lines": lines}
    if act_id:
        body["act_id"] = act_id
    r = await c.post("/api/finance/invoices", headers=hdr(who), json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def issued(c, **kw):
    inv = await draft(c, **kw)
    r = await c.post("/api/finance/invoices/%s/issue" % inv["id"], headers=hdr("acct-a"))
    assert r.status_code == 200, r.text
    return r.json()


async def sent(c, **kw):
    inv = await draft(c, **kw)
    r = await c.post("/api/finance/invoices/%s/send" % inv["id"], headers=hdr("acct-a"))
    assert r.status_code == 200, r.text
    return r.json()


async def get_inv(c, inv_id):
    r = await c.get("/api/finance/invoices/" + inv_id, headers=hdr("acct-a"))
    assert r.status_code == 200, r.text
    return r.json()


async def quick_pay(c, inv_id, amount):
    return await c.post("/api/finance/invoices/%s/payments" % inv_id, headers=hdr("acct-a"), json={
        "amount": amount, "method": "BankTransfer", "account_id": BANK_A, "date": "2026-11-08"})


async def note(c, inv, kind="credit", lines=None, who="acct-a", key=None, **extra):
    lines = lines if lines is not None else [{"original_line_id": inv["lines"][0]["id"], "qty": 3}]
    body = {"kind": kind, "original_invoice_id": inv["id"], "lines": lines, "reason": "грешка в количеството",
            **extra}
    return await c.post("/api/finance/credit-notes", headers=hdr(who, key), json=body)


async def approve(c, note_id, version=1, who="owner-a", key=None):
    return await c.post("/api/finance/credit-notes/%s/approve" % note_id, headers=hdr(who, key),
                        json={"version": version})


async def audit_actions(op):
    return [e["action"] for e in await op.audit_events.find({}, {"_id": 0, "action": 1}).to_list(None)]


def code(r):
    d = r.json().get("detail")
    return d.get("error_code") if isinstance(d, dict) else d


# ═══════════════════════════════════════════════════════ proof on main (red on cd03324)
def test_main_sent_invoice_lines_are_locked(monkeypatch, mode):
    async def scenario(c, op):
        inv = await sent(c)
        r = await c.put("/api/finance/invoices/%s/lines" % inv["id"], headers=hdr("acct-a"),
                        json={"lines": [{"description": "x", "qty": 1, "unit_price": 1}]})
        assert r.status_code == 409, r.text
        assert code(r) == "INVOICE_LOCKED"
        assert (await get_inv(c, inv["id"]))["total"] == 240.0
    run(monkeypatch, mode, scenario)


def test_main_partially_paid_and_paid_invoice_header_locked(monkeypatch, mode):
    async def scenario(c, op):
        inv = await sent(c)
        assert (await quick_pay(c, inv["id"], 100.0)).status_code == 201
        r = await c.put("/api/finance/invoices/" + inv["id"], headers=hdr("acct-a"), json={"vat_percent": 0})
        assert r.status_code == 409 and code(r) == "INVOICE_LOCKED", r.text
        r = await c.put("/api/finance/invoices/" + inv["id"], headers=hdr("acct-a"),
                        json={"counterparty_name": "Друг"})
        assert r.status_code == 409 and code(r) == "INVOICE_LOCKED", r.text
        assert (await quick_pay(c, inv["id"], 140.0)).status_code == 201
        r = await c.put("/api/finance/invoices/" + inv["id"], headers=hdr("acct-a"), json={"vat_percent": 0})
        assert r.status_code == 409 and code(r) == "INVOICE_LOCKED", r.text
        after = await get_inv(c, inv["id"])
        assert (after["total"], after["vat_percent"], after["counterparty_name"]) == (240.0, 20.0, "Клиент ООД")
        # notes / due date stay editable on an issued invoice
        r = await c.put("/api/finance/invoices/" + inv["id"], headers=hdr("acct-a"), json={"notes": "бележка"})
        assert r.status_code == 200, r.text
    run(monkeypatch, mode, scenario)


def test_main_numbered_invoice_is_never_deleted(monkeypatch, mode):
    async def scenario(c, op):
        await op.invoices.insert_one({
            "id": "legacy-draft", "org_id": ORG_A, "invoice_no": "INV-0042", "direction": "Issued",
            "kind": "Invoice", "status": "Draft", "issue_date": "2026-11-01", "due_date": "2099-12-31",
            "currency": "EUR", "lines": [], "subtotal": 0, "vat_percent": 20, "vat_amount": 0, "total": 0,
            "paid_amount": 0, "remaining_amount": 0})
        r = await c.delete("/api/finance/invoices/legacy-draft", headers=hdr("acct-a"))
        assert r.status_code == 409 and code(r) == "INVOICE_NUMBERED", r.text
        assert await op.invoices.count_documents({"id": "legacy-draft"}) == 1
    run(monkeypatch, mode, scenario)


def test_main_sent_invoice_is_not_cancelled_use_credit_note(monkeypatch, mode):
    async def scenario(c, op):
        inv = await sent(c)
        r = await c.post("/api/finance/invoices/%s/cancel" % inv["id"], headers=hdr("acct-a"),
                         json={"reason": "грешка"})
        assert r.status_code == 409 and code(r) == "USE_CREDIT_NOTE", r.text
        assert (await get_inv(c, inv["id"]))["status"] == "Sent"
    run(monkeypatch, mode, scenario)


def test_main_draft_has_no_number_until_issued(monkeypatch, mode):
    async def scenario(c, op):
        d = await draft(c)
        assert not d.get("invoice_no"), d
        r = await c.post("/api/finance/invoices/%s/issue" % d["id"], headers=hdr("acct-a", False))
        assert r.status_code == 428
        r = await c.post("/api/finance/invoices/%s/issue" % d["id"], headers=hdr("acct-a"))
        assert r.status_code == 200, r.text
        inv = r.json()
        assert inv["status"] == "Issued" and inv["invoice_no"] == "INV-0001"
        assert "finance.invoice.issued" in await audit_actions(op)
        # a draft without a number can still be deleted (it is not an official document)
        d2 = await draft(c)
        assert (await c.delete("/api/finance/invoices/" + d2["id"], headers=hdr("acct-a"))).status_code == 200
    run(monkeypatch, mode, scenario)


# ═══════════════════════════════════════════════════════════════════ positive
def test_cancel_issued_unsent_invoice_keeps_its_number(monkeypatch, mode):
    async def scenario(c, op):
        inv = await issued(c)
        url = "/api/finance/invoices/%s/cancel" % inv["id"]
        assert (await c.post(url, headers=hdr("acct-a"), json={})).status_code == 400   # no reason
        assert (await c.post(url, headers=hdr("acct-a", False), json={"reason": "x"})).status_code == 428
        r = await c.post(url, headers=hdr("acct-a"), json={"reason": "грешен клиент"})
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["status"] == "Cancelled" and out["invoice_no"] == inv["invoice_no"]
        assert out["cancel_reason"] == "грешен клиент"
        assert "finance.invoice.cancelled" in await audit_actions(op)
        r = await c.delete("/api/finance/invoices/" + inv["id"], headers=hdr("acct-a"))
        assert r.status_code == 409
        assert await op.invoices.count_documents({"id": inv["id"]}) == 1
        # the next invoice continues the sequence — the cancelled number is never reused
        nxt = await issued(c)
        assert nxt["invoice_no"] == "INV-0002"
    run(monkeypatch, mode, scenario)


def test_partial_credit_by_line_owner_approves_shared_number(monkeypatch, mode):
    async def scenario(c, op):
        inv = await sent(c)                               # INV-0001, 100 + 100 net, 20 % VAT
        r = await note(c, inv)                            # line 1, qty 3 → net 30, VAT 6, gross 36
        assert r.status_code == 201, r.text
        n = r.json()
        assert (n["status"], n["number"], n["applied"]) == ("pending_approval", None, False)
        assert (n["net"], n["vat"], n["gross"]) == (30.0, 6.0, 36.0)
        assert (await get_inv(c, inv["id"]))["remaining_amount"] == 240.0   # a draft changes nothing
        r = await approve(c, n["id"])
        assert r.status_code == 200, r.text
        n = r.json()
        assert (n["status"], n["number"], n["approval"]["version"]) == ("approved", "INV-0002", 1)
        after = await get_inv(c, inv["id"])
        assert (after["total"], after["remaining_amount"], after["credited_amount"]) == (240.0, 204.0, 36.0)
        assert after["lines"] == inv["lines"]             # the original is never rewritten
        acts = await audit_actions(op)
        assert "finance.credit_note.drafted" in acts and "finance.credit_note.approved" in acts
        # the open amount is what can be paid
        assert (await quick_pay(c, inv["id"], 204.5)).status_code == 400
        assert (await quick_pay(c, inv["id"], 204.0)).status_code == 201
        assert (await get_inv(c, inv["id"]))["status"] == "Paid"
    run(monkeypatch, mode, scenario)


def test_full_credit_then_new_invoice(monkeypatch, mode):
    async def scenario(c, op):
        inv = await sent(c)
        lines = [{"original_line_id": l["id"], "amount": l["line_total"]} for l in inv["lines"]]
        n = (await note(c, inv, lines=lines)).json()
        assert n["gross"] == 240.0
        assert (await approve(c, n["id"])).status_code == 200
        after = await get_inv(c, inv["id"])
        assert after["remaining_amount"] == 0 and after["status"] == "Sent"   # credited, not "paid"
        assert (await quick_pay(c, inv["id"], 1.0)).status_code == 400
        nxt = await issued(c)
        assert nxt["invoice_no"] == "INV-0003"            # 0001 invoice, 0002 note, 0003 new invoice
    run(monkeypatch, mode, scenario)


def test_credit_on_act_invoice_frees_the_act_hard_cap(monkeypatch, mode):
    async def scenario(c, op):
        line600 = [{"description": "СМР", "qty": 6, "unit_price": 100}]
        line500 = [{"description": "СМР", "qty": 5, "unit_price": 100}]
        inv1 = await issued(c, lines=line600, act_id="act-1")
        d2 = await draft(c, lines=line500, act_id="act-1")
        r = await c.post("/api/finance/invoices/%s/issue" % d2["id"], headers=hdr("acct-a"))
        assert r.status_code == 409 and code(r) == "ACT_OVER_INVOICED", r.text
        assert (await get_inv(c, d2["id"]))["status"] == "Draft"
        n = (await note(c, inv1, lines=[{"original_line_id": inv1["lines"][0]["id"], "qty": 2}])).json()
        assert (await approve(c, n["id"])).status_code == 200            # 600 − 200 = 400 invoiced
        r = await c.post("/api/finance/invoices/%s/issue" % d2["id"], headers=hdr("acct-a"))
        assert r.status_code == 200, r.text                              # 400 + 500 ≤ 1000
        act = await op.client_acts.find_one({"id": "act-1"})
        assert act["lines"][0]["executed_qty"] == 10                    # the act is never touched
        # an act that is not approved cannot be invoiced
        r = await c.post("/api/finance/invoices", headers=hdr("acct-a"), json={
            "direction": "Issued", "project_id": "prj-1", "act_id": "act-draft", "issue_date": "2026-11-08",
            "due_date": "2099-12-31", "counterparty_eik": EIK, "lines": line500})
        assert r.status_code == 422 and code(r) == "ACT_NOT_APPROVED"
    run(monkeypatch, mode, scenario)


def test_incoming_credit_note_matches_awaited_credit_and_lifts_the_limit(monkeypatch, mode):
    async def scenario(c, op):
        bill = await sent(c, direction="Received")                    # supplier invoice, 240
        old = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()
        await op.expected_credit_notes.insert_many([            # the PR #82 (WH-REV-01) record
            {"id": "ecn_1", "org_id": ORG_A, "invoice_id": bill["id"], "amount": 36.0, "status": "open",
             "created_at": old, "dq_task": {"title": "очаква кредитно известие", "status": "open"}}])
        corr = (await c.get("/api/finance/invoices/%s/corrections" % bill["id"], headers=hdr("acct-a"))).json()
        assert corr["expected_credit_notes"][0]["escalate_to_owner"] is True   # 14 days passed
        assert await op.expected_credit_notes.count_documents({"escalate_to_owner": {"$exists": True}}) == 0
        # a difference → registered, NOT applied, the limit stays, DQ „разлика“
        r = await note(c, bill, number="CN-77", lines=[{"original_line_id": bill["lines"][0]["id"], "qty": 4}])
        assert r.status_code == 201, r.text
        assert (r.json()["status"], r.json()["applied"]) == ("registered", False)
        ecn = await op.expected_credit_notes.find_one({"id": "ecn_1"})
        assert ecn["status"] == "open" and ecn["dq_mismatch"]["title"] == "разлика в кредитно известие"
        assert (await get_inv(c, bill["id"]))["remaining_amount"] == 240.0
        # a duplicate (same supplier, same number) → 409
        r = await note(c, bill, number="CN-77")
        assert r.status_code == 409 and code(r) == "DUPLICATE_CREDIT_NOTE"
        # to the cent → fulfilled, DQ closed, payable recomputed
        r = await note(c, bill, number="CN-78")                         # qty 3 → 36.00
        assert r.status_code == 201 and r.json()["applied"] is True, r.text
        ecn = await op.expected_credit_notes.find_one({"id": "ecn_1"})
        assert ecn["status"] == "fulfilled" and ecn["dq_task"]["status"] == "closed"
        after = await get_inv(c, bill["id"])
        assert after["remaining_amount"] == 204.0
        assert (await quick_pay(c, bill["id"], 204.0)).status_code == 201
    run(monkeypatch, mode, scenario)


def test_credit_on_paid_invoice_is_a_balance_refund_through_the_ledger(monkeypatch, mode):
    async def scenario(c, op):
        inv = await sent(c)
        assert (await quick_pay(c, inv["id"], 240.0)).status_code == 201
        n = (await note(c, inv)).json()
        assert (await approve(c, n["id"])).status_code == 200
        after = await get_inv(c, inv["id"])
        assert (after["status"], after["remaining_amount"], after["credit_balance"]) == ("Paid", 0, 36.0)
        url = "/api/finance/invoices/%s/refund" % inv["id"]
        body = {"amount": 36.01, "reason": "връщане", "account_id": BANK_A, "method": "BankTransfer"}
        r = await c.post(url, headers=hdr("acct-a"), json=body)
        assert r.status_code == 409 and code(r) == "REFUND_EXCEEDS_BALANCE"
        assert (await c.post(url, headers=hdr("acct-a", False), json=body)).status_code == 428
        key = "refund-" + uuid.uuid4().hex
        r = await c.post(url, headers=hdr("acct-a", key), json={**body, "amount": 36.0})
        assert r.status_code == 201, r.text
        again = await c.post(url, headers=hdr("acct-a", key), json={**body, "amount": 36.0})
        assert again.json()["payment_id"] == r.json()["payment_id"]
        pays = await op.finance_payments.find({"refund_invoice_id": inv["id"]}).to_list(None)
        assert len(pays) == 1 and (pays[0]["direction"], pays[0]["amount"]) == ("Outflow", 36.0)
        assert (await get_inv(c, inv["id"]))["credit_balance"] == 0
    run(monkeypatch, mode, scenario)


def test_offset_same_contract_needs_a_second_person(monkeypatch, mode):
    async def scenario(c, op):
        a = await sent(c)
        assert (await quick_pay(c, a["id"], 240.0)).status_code == 201
        n = (await note(c, a)).json()
        assert (await approve(c, n["id"])).status_code == 200            # A: credit balance 36
        b = await sent(c)                                                 # B: open 240, same contract
        other = await sent(c, project="prj-2")                            # another project
        r = await c.post("/api/finance/offsets", headers=hdr("acct-a"), json={
            "source_invoice_id": a["id"], "target_invoice_id": other["id"], "amount": 10, "reason": "x"})
        assert r.status_code == 409 and code(r) == "OFFSET_ACROSS_CONTRACTS"
        r = await c.post("/api/finance/offsets", headers=hdr("acct-a"), json={
            "source_invoice_id": a["id"], "target_invoice_id": b["id"], "amount": 36.5, "reason": "x"})
        assert r.status_code == 409 and code(r) == "OFFSET_EXCEEDS_BALANCE"
        r = await c.post("/api/finance/offsets", headers=hdr("owner-a"), json={
            "source_invoice_id": a["id"], "target_invoice_id": b["id"], "amount": 36, "reason": "прихващане"})
        assert r.status_code == 201 and r.json()["status"] == "pending_approval", r.text
        off = r.json()
        assert (await get_inv(c, b["id"]))["remaining_amount"] == 240.0     # nothing applied yet
        r = await c.post("/api/finance/offsets/%s/approve" % off["id"], headers=hdr("owner-a"),
                         json={"version": 1})
        assert r.status_code == 409 and code(r) == "SAME_PERSON_APPROVAL"
        # a second offset by the Accountant, approved by the Owner
        r = await c.post("/api/finance/offsets", headers=hdr("acct-a"), json={
            "source_invoice_id": a["id"], "target_invoice_id": b["id"], "amount": 36, "reason": "прихващане"})
        off2 = r.json()
        r = await c.post("/api/finance/offsets/%s/approve" % off2["id"], headers=hdr("owner-a"),
                         json={"version": 1})
        assert r.status_code == 200, r.text
        assert (await get_inv(c, b["id"]))["remaining_amount"] == 204.0
        assert (await get_inv(c, a["id"]))["credit_balance"] == 0
        # the first (pending) one can no longer be approved: the balance is used up
        r = await c.post("/api/finance/offsets/%s/approve" % off["id"], headers=hdr("admin-a"),
                         json={"version": 1})
        assert r.status_code == 403
        assert "finance.offset.approved" in await audit_actions(op)
    run(monkeypatch, mode, scenario)


# ═══════════════════════════════════════════════════════════════════ forbidden
def test_credit_above_invoiced_including_six_concurrent(monkeypatch, mode):
    async def scenario(c, op):
        inv = await sent(c)
        line = inv["lines"][0]["id"]                                       # qty 10 × 10 = net 100
        r = await note(c, inv, lines=[{"original_line_id": line, "qty": 11}])
        assert r.status_code == 409 and code(r) == "CREDIT_EXCEEDS_INVOICED"
        r = await note(c, inv, lines=[{"original_line_id": "not-a-line", "qty": 1}])
        assert r.status_code == 422
        drafts = []
        for _ in range(6):
            r = await note(c, inv, lines=[{"original_line_id": line, "qty": 4}])   # 40 each
            assert r.status_code == 201, r.text
            drafts.append(r.json()["id"])
        results = await asyncio.gather(*(approve(c, d) for d in drafts))
        ok = [r for r in results if r.status_code == 200]
        refused = [r for r in results if r.status_code == 409]
        assert len(ok) == 2 and len(refused) == 4, [r.text for r in results]
        assert {code(r) for r in refused} == {"CREDIT_EXCEEDS_INVOICED"}
        after = await get_inv(c, inv["id"])
        assert after["credited_amount"] == 96.0                            # 2 × 48 gross
        assert sorted(r.json()["number"] for r in ok) == ["INV-0002", "INV-0003"]
    run(monkeypatch, mode, scenario)


def test_debit_note_requires_an_approved_act(monkeypatch, mode):
    async def scenario(c, op):
        inv = await sent(c)
        r = await note(c, inv, kind="debit")
        assert r.status_code == 422 and code(r) == "DEBIT_NOTE_BASIS_REQUIRED"
        r = await note(c, inv, kind="debit", basis={"type": "act", "id": "act-draft"})
        assert r.status_code == 422 and code(r) == "DEBIT_NOTE_BASIS_REQUIRED"
        r = await note(c, inv, kind="debit", basis={"type": "act", "id": "act-2"})    # other project
        assert r.status_code == 422 and code(r) == "DEBIT_NOTE_BASIS_REQUIRED"
        r = await note(c, inv, kind="debit", basis={"type": "act", "id": "act-1"})
        assert r.status_code == 201, r.text
        assert (await approve(c, r.json()["id"])).status_code == 200
        after = await get_inv(c, inv["id"])
        assert (after["total"], after["remaining_amount"]) == (240.0, 276.0)
    run(monkeypatch, mode, scenario)


def test_author_cannot_approve_only_owner_exact_version(monkeypatch, mode):
    async def scenario(c, op):
        inv = await sent(c)
        own = (await note(c, inv, who="owner-a")).json()
        r = await approve(c, own["id"], who="owner-a")
        assert r.status_code == 409 and code(r) == "SAME_PERSON_APPROVAL"
        n = (await note(c, inv)).json()
        assert (await approve(c, n["id"], who="acct-a")).status_code == 403
        assert (await approve(c, n["id"], who="admin-a")).status_code == 403
        r = await approve(c, n["id"], version=2)
        assert r.status_code == 409 and code(r) == "VERSION_MISMATCH"
        assert (await approve(c, n["id"], who="owner-a", key=False)).status_code == 428
        assert (await op.credit_debit_notes.find_one({"id": n["id"]}))["status"] == "pending_approval"
        assert (await approve(c, n["id"])).status_code == 200
        r = await approve(c, n["id"])
        assert r.status_code == 409 and code(r) == "NOT_PENDING_APPROVAL"
    run(monkeypatch, mode, scenario)


def test_roles_and_tenants_and_missing_key(monkeypatch, mode):
    async def scenario(c, op):
        inv = await sent(c)
        for who in ("viewer-a", "site-a"):
            r = await note(c, inv, who=who)
            assert r.status_code == 403, (who, r.text)
        assert (await note(c, inv, key=False)).status_code == 428
        r = await note(c, inv, who="admin-b")
        assert r.status_code == 404
        assert await op.credit_debit_notes.count_documents({}) == 0
        n = (await note(c, inv)).json()
        r = await c.get("/api/finance/credit-notes/" + n["id"], headers=hdr("admin-b"))
        assert r.status_code == 404
        # draft / cancelled invoices are not corrected by a note
        d = await draft(c)
        r = await c.post("/api/finance/credit-notes", headers=hdr("acct-a"), json={
            "kind": "credit", "original_invoice_id": d["id"], "reason": "x",
            "lines": [{"original_line_id": d["lines"][0]["id"], "qty": 1}]})
        assert r.status_code == 409 and code(r) == "INVOICE_NOT_CORRECTABLE"
    run(monkeypatch, mode, scenario)


def test_act_cannot_be_over_invoiced_concurrently(monkeypatch, mode):
    async def scenario(c, op):
        line300 = [{"description": "СМР", "qty": 3, "unit_price": 100}]
        drafts = [await draft(c, lines=line300, act_id="act-1") for _ in range(6)]
        results = await asyncio.gather(*(
            c.post("/api/finance/invoices/%s/issue" % d["id"], headers=hdr("acct-a")) for d in drafts))
        ok = [r for r in results if r.status_code == 200]
        assert len(ok) == 3, [r.text for r in results]                     # 3 × 300 ≤ 1000
        assert {code(r) for r in results if r.status_code != 200} == {"ACT_OVER_INVOICED"}
    run(monkeypatch, mode, scenario)


def test_six_concurrent_numbers_are_unique_one_sequence(monkeypatch, mode):
    async def scenario(c, op):
        drafts = [await draft(c) for _ in range(6)]
        results = await asyncio.gather(*(
            c.post("/api/finance/invoices/%s/issue" % d["id"], headers=hdr("acct-a")) for d in drafts))
        assert all(r.status_code == 200 for r in results), [r.text for r in results]
        numbers = sorted(r.json()["invoice_no"] for r in results)
        assert numbers == ["INV-%04d" % i for i in range(1, 7)]
        inv = results[0].json()
        notes = [(await note(c, inv, lines=[{"original_line_id": inv["lines"][0]["id"], "qty": 1}])).json()["id"]
                 for _ in range(3)]
        more = [await draft(c) for _ in range(3)]
        mixed = await asyncio.gather(
            *(approve(c, n) for n in notes),
            *(c.post("/api/finance/invoices/%s/issue" % d["id"], headers=hdr("acct-a")) for d in more))
        assert all(r.status_code == 200 for r in mixed), [r.text for r in mixed]
        got = sorted([r.json().get("number") or r.json().get("invoice_no") for r in mixed])
        assert got == ["INV-%04d" % i for i in range(7, 13)]
    run(monkeypatch, mode, scenario)


def test_pnl_takes_the_note_in_its_own_period_on_the_original_project(monkeypatch, mode):
    async def scenario(c, op):
        from app.services.project_pnl import compute_project_pnl
        inv = await sent(c)
        before = await compute_project_pnl(ORG_A, "prj-1")
        n = (await note(c, inv)).json()
        assert (await approve(c, n["id"])).status_code == 200
        after = await compute_project_pnl(ORG_A, "prj-1")
        rev = lambda p: p["revenue"]["total_revenue"] if isinstance(p.get("revenue"), dict) else p["total_revenue"]
        assert round(rev(before) - rev(after), 2) == 30.0
        saved = await op.credit_debit_notes.find_one({"id": n["id"]})
        assert saved["issue_date"] == datetime.now(timezone.utc).date().isoformat()
        assert saved["project_id"] == "prj-1"
    run(monkeypatch, mode, scenario)
