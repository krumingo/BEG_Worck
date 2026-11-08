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
            try:                                   # the invoice-number index server.py builds
                from app.services.invoice_corrections import INVOICE_NO_INDEX, SUPPLIER_NO_INDEX
                await op.invoices.create_index(INVOICE_NO_INDEX[1], **INVOICE_NO_INDEX[2])
                await op.invoices.create_index(SUPPLIER_NO_INDEX[1], **SUPPLIER_NO_INDEX[2])
            except ImportError:                    # main cd03324: the legacy startup index
                await op.invoices.create_index([("org_id", 1), ("invoice_no", 1)], unique=True,
                                               sparse=True)
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


async def cancel_flow(c, inv_id, who="acct-a", approver="owner-a", reason="грешен клиент"):
    """Р51(1): the Accountant proposes, the Owner (another person) approves."""
    r = await c.post("/api/finance/invoices/%s/cancel" % inv_id, headers=hdr(who), json={"reason": reason})
    assert r.status_code == 200, r.text
    req = r.json()["cancellation_request"]
    return await c.post("/api/finance/invoices/%s/cancel/approve" % inv_id, headers=hdr(approver),
                        json={"version": req["version"]})


async def offset(c, a, b, amount, n_id, who="acct-a", **extra):
    body = {"source_invoice_id": a["id"], "target_invoice_id": b["id"], "amount": amount,
            "reason": "прихващане", "legal_basis": "споразумение за прихващане от 08.11.2026",
            "file_id": "file-offset-1", "source_credit_note_id": n_id, **extra}
    return await c.post("/api/finance/offsets", headers=hdr(who), json=body)


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
    """Р49.2 + Р51(1): reason + key; the Accountant proposes, the Owner approves."""
    async def scenario(c, op):
        inv = await issued(c)
        url = "/api/finance/invoices/%s/cancel" % inv["id"]
        assert (await c.post(url, headers=hdr("acct-a"), json={})).status_code == 400   # no reason
        assert (await c.post(url, headers=hdr("acct-a", False), json={"reason": "x"})).status_code == 428
        r = await c.post(url, headers=hdr("acct-a"), json={"reason": "грешен клиент"})
        assert r.status_code == 200, r.text
        prop = r.json()
        assert prop["status"] == "Issued"                                # only a proposal
        req = prop["cancellation_request"]
        assert (req["status"], req["requested_by"], req["version"]) == ("pending_approval", "acct-a", 1)
        r = await c.post(url, headers=hdr("acct-a"), json={"reason": "пак"})
        assert r.status_code == 409 and code(r) == "CANCELLATION_PENDING"
        appr = url + "/approve"
        assert (await c.post(appr, headers=hdr("acct-a"), json={"version": 1})).status_code == 403
        assert (await c.post(appr, headers=hdr("admin-a"), json={"version": 1})).status_code == 403
        r = await c.post(appr, headers=hdr("owner-a"), json={"version": 2})
        assert r.status_code == 409 and code(r) == "VERSION_MISMATCH"
        r = await c.post(appr, headers=hdr("owner-a"), json={"version": 1})
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["status"] == "Cancelled" and out["invoice_no"] == inv["invoice_no"]
        assert out["cancel_reason"] == "грешен клиент" and out["cancellation_request"]["approved_by"] == "owner-a"
        acts = await audit_actions(op)
        assert "finance.invoice.cancellation_requested" in acts and "finance.invoice.cancelled" in acts
        r = await c.delete("/api/finance/invoices/" + inv["id"], headers=hdr("acct-a"))
        assert r.status_code == 409
        assert await op.invoices.count_documents({"id": inv["id"]}) == 1
        # the next invoice continues the sequence — the cancelled number is never reused
        nxt = await issued(c)
        assert nxt["invoice_no"] == "INV-0002"
    run(monkeypatch, mode, scenario)


def test_r51_1_the_proposer_cannot_approve_and_a_proposal_can_be_rejected(monkeypatch, mode):
    async def scenario(c, op):
        inv = await issued(c)
        url = "/api/finance/invoices/%s/cancel" % inv["id"]
        # Р53(2) / FG-234: the Owner approves, never proposes
        r = await c.post(url, headers=hdr("owner-a"), json={"reason": "грешка"})
        assert r.status_code == 403 and code(r) == "CANCEL_ROLE_REQUIRED"
        assert (await c.post(url, headers=hdr("admin-a"), json={"reason": "грешка"})).status_code == 200
        r = await c.post(url + "/approve", headers=hdr("admin-a"), json={"version": 1})
        assert r.status_code == 403                                      # the Admin proposed; Owner approves
        r = await c.post(url + "/reject", headers=hdr("acct-a"), json={"reason": "не"})
        assert r.status_code == 403                                      # neither Owner nor proposer
        r = await c.post(url + "/reject", headers=hdr("owner-a"), json={"reason": "оттеглям"})
        assert r.status_code == 200 and r.json()["cancellation_request"]["status"] == "rejected"
        assert r.json()["status"] == "Issued"
        # a new proposal (version 2) by the Accountant, approved by the Owner
        assert (await c.post(url, headers=hdr("acct-a"), json={"reason": "грешка"})).status_code == 200
        r = await c.post(url + "/approve", headers=hdr("owner-a"), json={"version": 2})
        assert r.status_code == 200 and r.json()["status"] == "Cancelled", r.text
        # FG-234: a pending proposal is superseded when the invoice is sent (AuditEvent)…
        inv2 = await issued(c)
        assert (await c.post("/api/finance/invoices/%s/cancel" % inv2["id"], headers=hdr("acct-a"),
                             json={"reason": "x"})).status_code == 200
        assert (await c.post("/api/finance/invoices/%s/send" % inv2["id"], headers=hdr("acct-a"))).status_code == 200
        assert (await get_inv(c, inv2["id"]))["cancellation_request"]["status"] == "superseded"
        r = await c.post("/api/finance/invoices/%s/cancel/approve" % inv2["id"], headers=hdr("owner-a"),
                         json={"version": 1})
        assert r.status_code == 409 and code(r) == "NOT_PENDING_APPROVAL"
        assert "finance.invoice.cancellation_superseded" in await audit_actions(op)
        # … or paid (a legacy numbered draft, cancellable while unsent, paid in between)
        await op.invoices.insert_one({
            "id": "legacy-p", "org_id": ORG_A, "invoice_no": "INV-0090", "direction": "Issued",
            "kind": "Invoice", "status": "Issued", "issued_at": "2026-11-01T00:00:00+00:00",
            "issue_date": "2026-11-01", "due_date": "2099-12-31", "currency": "EUR", "lines": [],
            "subtotal": 100.0, "vat_percent": 0, "vat_amount": 0, "total": 100.0, "paid_amount": 0,
            "remaining_amount": 100.0})
        assert (await c.post("/api/finance/invoices/legacy-p/cancel", headers=hdr("acct-a"),
                             json={"reason": "x"})).status_code == 200
        assert (await quick_pay(c, "legacy-p", 10.0)).status_code == 201
        assert (await get_inv(c, "legacy-p"))["cancellation_request"]["status"] == "superseded"
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
    """Р47 + Р49.8, FG-219 (exact to the cent), FG-220 (explicit link by the Accountant)."""
    async def scenario(c, op):
        bill = await sent(c, direction="Received")                    # supplier invoice, 240
        old = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()
        await op.expected_credit_notes.insert_many([            # the PR #82 (WH-REV-01) record
            {"id": "ecn_1", "org_id": ORG_A, "invoice_id": bill["id"], "amount": 36.0, "status": "open",
             "created_at": old, "dq_task": {"title": "очаква кредитно известие", "status": "open"}}])
        corr = (await c.get("/api/finance/invoices/%s/corrections" % bill["id"], headers=hdr("acct-a"))).json()
        assert corr["expected_credit_notes"][0]["escalate_to_owner"] is True   # 14 days passed
        assert await op.expected_credit_notes.count_documents({"escalate_to_owner": {"$exists": True}}) == 0
        # FG-220: no link to the awaited credit → 422; a wrong id → 422 (never linked by amount)
        r = await note(c, bill, number="CN-76")
        assert r.status_code == 422 and code(r) == "EXPECTED_CREDIT_LINK_REQUIRED", r.text
        r = await note(c, bill, number="CN-76", expected_credit_note_ids=["ecn_other"])
        assert r.status_code == 422 and code(r) == "EXPECTED_CREDIT_LINK_INVALID"
        # FG-219: one cent off (35.99 vs 36.00) → registered, NOT applied, the limit stays, DQ
        r = await note(c, bill, number="CN-77", expected_credit_note_ids=["ecn_1"],
                       lines=[{"original_line_id": bill["lines"][0]["id"], "amount": 29.99}])
        assert r.status_code == 201, r.text
        assert (r.json()["gross"], r.json()["status"], r.json()["applied"]) == (35.99, "registered", False)
        ecn = await op.expected_credit_notes.find_one({"id": "ecn_1"})
        assert ecn["status"] == "open" and ecn["dq_mismatch"]["title"] == "разлика в кредитно известие"
        assert (await get_inv(c, bill["id"]))["remaining_amount"] == 240.0
        # a duplicate (same supplier, same number) → 409
        r = await note(c, bill, number="CN-77", expected_credit_note_ids=["ecn_1"])
        assert r.status_code == 409 and code(r) == "DUPLICATE_CREDIT_NOTE"
        # exactly to the cent → fulfilled, DQ closed, payable recomputed
        r = await note(c, bill, number="CN-78", expected_credit_note_ids=["ecn_1"])   # qty 3 → 36.00
        assert r.status_code == 201 and r.json()["applied"] is True, r.text
        ecn = await op.expected_credit_notes.find_one({"id": "ecn_1"})
        assert ecn["status"] == "fulfilled" and ecn["dq_task"]["status"] == "closed"
        # Р52(2a): the corrected note closed the mismatch DQ; the mismatched note is superseded
        assert ecn["dq_mismatch"]["status"] == "closed"
        cn77 = await op.credit_debit_notes.find_one({"number": "CN-77"})
        assert (cn77["applied"], cn77["superseded_by"]) == (False, r.json()["id"])
        after = await get_inv(c, bill["id"])
        assert after["remaining_amount"] == 204.0
        assert (await quick_pay(c, bill["id"], 204.0)).status_code == 201
        # nothing awaited any more → a later supplier credit note needs no link
        bill2 = await sent(c, direction="Received")
        r = await note(c, bill2, number="CN-90")
        assert r.status_code == 201 and r.json()["applied"] is True
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
    """Р49.6(б), Р51(4) (every offset: a second person), FG-222 (basis + document + sources)."""
    async def scenario(c, op):
        a = await sent(c)
        assert (await quick_pay(c, a["id"], 240.0)).status_code == 201
        n = (await note(c, a)).json()
        assert (await approve(c, n["id"])).status_code == 200            # A: credit balance 36
        b = await sent(c)                                                 # B: open 240, same contract
        other = await sent(c, project="prj-2")                            # another project
        # FG-222: free text alone is not enough
        for missing in ("legal_basis", "file_id", "source_credit_note_id"):
            r = await offset(c, a, b, 10, n["id"], **{missing: ""})
            assert r.status_code == 422 and code(r) == "OFFSET_BASIS_REQUIRED", (missing, r.text)
        r = await offset(c, a, b, 10, "not-a-note")
        assert r.status_code == 422 and code(r) == "OFFSET_BASIS_REQUIRED"
        r = await offset(c, a, other, 10, n["id"])
        assert r.status_code == 409 and code(r) == "OFFSET_ACROSS_CONTRACTS"
        r = await offset(c, a, b, 36.5, n["id"])
        assert r.status_code == 409 and code(r) == "OFFSET_EXCEEDS_BALANCE"
        r = await offset(c, a, b, 36, n["id"], who="owner-a")
        assert r.status_code == 201 and r.json()["status"] == "pending_approval", r.text
        off = r.json()
        assert (off["legal_basis"], off["file_id"], off["source_credit_note_id"]) == (
            "споразумение за прихващане от 08.11.2026", "file-offset-1", n["id"])
        assert (await get_inv(c, b["id"]))["remaining_amount"] == 240.0     # nothing applied yet
        r = await c.post("/api/finance/offsets/%s/approve" % off["id"], headers=hdr("owner-a"),
                         json={"version": 1})
        assert r.status_code == 409 and code(r) == "SAME_PERSON_APPROVAL"
        # D10: the author withdraws it; then the Accountant's offset, approved by the Owner
        r = await c.post("/api/finance/offsets/%s/reject" % off["id"], headers=hdr("owner-a"),
                         json={"reason": "оттеглям"})
        assert r.status_code == 200 and r.json()["status"] == "rejected"
        off2 = (await offset(c, a, b, 36, n["id"])).json()
        assert off2["status"] == "pending_approval", off2
        r = await c.post("/api/finance/offsets/%s/approve" % off2["id"], headers=hdr("owner-a"),
                         json={"version": 1})
        assert r.status_code == 200, r.text
        assert (await get_inv(c, b["id"]))["remaining_amount"] == 204.0
        assert (await get_inv(c, a["id"]))["credit_balance"] == 0
        # the credit note is used up: no further offset from it
        r = await offset(c, a, b, 1, n["id"])
        assert r.status_code == 409 and code(r) == "OFFSET_EXCEEDS_BALANCE"
        assert "finance.offset.approved" in await audit_actions(op)
    run(monkeypatch, mode, scenario)


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


def test_r47_registration_releases_the_pr82_cap(monkeypatch, mode):
    """FG-196 coupling with PR #82 (WH-REV-01): a receipt reversal leaves an open
    ``expected_credit_notes`` row (exactly #82's shape) and blocks paying above the net
    received (409 INVOICE_AWAITS_CREDIT_NOTE). Registering the supplier's credit note
    that matches to the cent closes the row, so the block is lifted and the net payable
    is what can be paid. The cap itself exists only once #82 is merged: the "refused
    before" part runs only where ``finance._awaited_credit`` exists."""
    from app.routes import finance as r_finance
    pr82 = hasattr(r_finance, "_awaited_credit")

    async def scenario(c, op):
        bill = await sent(c, direction="Received")                    # 240 gross
        await op.invoices.update_one({"id": bill["id"]}, {"$set": {"awaiting_credit_note": True}})
        await op.expected_credit_notes.insert_one({                 # as #82 _expect_credit_note writes it
            "id": "ecn_mv-1", "org_id": ORG_A, "invoice_id": bill["id"],
            "invoice_line_id": bill["lines"][0]["id"], "reversal_movement_id": "mv-1",
            "receipt_movement_id": "mv-0", "quantity": "3", "unit": "m2", "amount": 36.0,
            "currency": "EUR", "status": "open", "reason": "сторно",
            "created_at": datetime.now(timezone.utc).isoformat(), "created_by": "acct-a",
            "dq_task": {"assignee_role": "accountant", "title": "очаква кредитно известие",
                        "status": "open"}})
        if pr82:
            r = await quick_pay(c, bill["id"], 205.0)
            assert r.status_code == 409 and code(r) == "INVOICE_AWAITS_CREDIT_NOTE", r.text
        r = await note(c, bill, number="CN-R47", expected_credit_note_ids=["ecn_mv-1"])   # 36.00
        assert r.status_code == 201 and r.json()["applied"] is True, r.text
        ecn = await op.expected_credit_notes.find_one({"id": "ecn_mv-1"})
        assert (ecn["status"], ecn["dq_task"]["status"], ecn["credit_note_id"]) == (
            "fulfilled", "closed", r.json()["id"])
        inv = await get_inv(c, bill["id"])
        assert (inv["remaining_amount"], inv["awaiting_credit_note"]) == (204.0, False)
        assert (await quick_pay(c, bill["id"], 204.0)).status_code == 201
        assert (await get_inv(c, bill["id"]))["status"] == "Paid"
    run(monkeypatch, mode, scenario)


# ═══════════════════════════════════════════════════ Addendum A (FLOW Guard pass + Р51)
def test_fg217_many_drafts_and_supplier_numbers_never_block_our_series(monkeypatch, mode):
    """FG-217: a draft has NO invoice_no field; any number of drafts per tenant; a
    supplier's number never blocks our own issue; the legacy index → 409 (never 500) until
    the migration replaces it."""
    async def scenario(c, op):
        d1, d2, d3 = await draft(c), await draft(c), await draft(c)
        saved = await op.invoices.find_one({"id": d2["id"]})
        assert "invoice_no" not in saved
        bill = await draft(c, direction="Received")
        await op.invoices.update_one({"id": bill["id"]}, {"$set": {"invoice_no": "INV-0001"}})
        r = await c.post("/api/finance/invoices/%s/issue" % d1["id"], headers=hdr("acct-a"))
        assert r.status_code == 200 and r.json()["invoice_no"] == "INV-0001", r.text
        # a tenant still on the LEGACY unique+sparse (org_id, invoice_no) index
        # (on a legacy tenant the supplier INV-0001 and our INV-0001 could not even coexist)
        await op.invoices.delete_many({"id": {"$in": [d2["id"], d3["id"], bill["id"]]}})
        await op.invoices.create_index([("org_id", 1), ("invoice_no", 1)], unique=True, sparse=True,
                                       name="org_id_1_invoice_no_1")
        await draft(c)
        r = await c.post("/api/finance/invoices", headers=hdr("acct-a"), json={
            "direction": "Issued", "issue_date": "2026-11-08", "due_date": "2099-12-31",
            "counterparty_eik": EIK, "lines": LINES})
        assert r.status_code == 409 and code(r) == "INVOICE_NUMBER_TAKEN", r.text      # not a 500
        from app.services import invoice_corrections_migration as mig
        plan = await mig.plan(op)
        assert plan["legacy_index"] == ["org_id_1_invoice_no_1"]
        await mig.apply(op, actor_id="owner-a")
        assert "org_id_1_invoice_no_1" not in await op.invoices.index_information()
        assert (await mig.plan(op))["changes"] == 0                              # idempotent
        await draft(c)
        await draft(c)
    run(monkeypatch, mode, scenario)


def test_fg218_a_manual_number_inside_the_series_is_skipped_never_blocks(monkeypatch, mode):
    async def scenario(c, op):
        first = await issued(c)
        assert first["invoice_no"] == "INV-0001"
        settings = "/api/finance/invoice-settings"
        assert (await c.put(settings, headers=hdr("owner-a"), json={"issued_auto_numbering": False})).status_code == 200
        manual = await draft(c)                     # typed number kept for the issue step
        await op.invoices.update_one({"id": manual["id"]}, {"$set": {"manual_number": "INV-0002"}})
        r = await c.post("/api/finance/invoices/%s/issue" % manual["id"], headers=hdr("acct-a"))
        assert r.status_code == 200 and r.json()["invoice_no"] == "INV-0002", r.text
        assert (await c.put(settings, headers=hdr("owner-a"), json={"issued_auto_numbering": True})).status_code == 200
        nxt = await issued(c)
        assert nxt["invoice_no"] == "INV-0003"                         # 0002 skipped, not blocked
        assert (await issued(c))["invoice_no"] == "INV-0004"
    run(monkeypatch, mode, scenario)


def test_r49_1_legacy_numbered_draft_is_locked_and_migrated_to_issued(monkeypatch, mode):
    async def scenario(c, op):
        await op.invoices.insert_one({
            "id": "legacy-1", "org_id": ORG_A, "invoice_no": "INV-0007", "direction": "Issued",
            "kind": "Invoice", "status": "Draft", "issue_date": "2026-10-01", "due_date": "2099-12-31",
            "currency": "EUR", "lines": [{"id": "l1", "description": "x", "qty": 1, "unit_price": 100,
                                          "line_total": 100}], "subtotal": 100, "vat_percent": 20,
            "vat_amount": 20, "total": 120, "paid_amount": 0, "remaining_amount": 120,
            "created_at": "2026-10-01T08:00:00+00:00"})
        r = await c.put("/api/finance/invoices/legacy-1/lines", headers=hdr("acct-a"),
                        json={"lines": [{"description": "y", "qty": 1, "unit_price": 1}]})
        assert r.status_code == 409 and code(r) == "INVOICE_LOCKED"
        from app.services import invoice_corrections_migration as mig
        plan = await mig.plan(op)
        assert [d["id"] for t in plan["tenants"] for d in t["legacy_numbered_drafts_to_issue"]] == ["legacy-1"]
        assert (await op.invoices.find_one({"id": "legacy-1"}))["status"] == "Draft"   # dry run wrote nothing
        await mig.apply(op, actor_id="owner-a")
        inv = await op.invoices.find_one({"id": "legacy-1"})
        assert (inv["status"], inv["issued_number"], inv["issued_by_migration"]) == ("Issued", "INV-0007", True)
        assert "finance.invoice.issued_by_migration" in await audit_actions(op)
        await mig.apply(op, actor_id="owner-a")                                    # idempotent
        assert await op.audit_events.count_documents({"action": "finance.invoice.issued_by_migration"}) == 1
        # the auto series continues above it
        assert (await issued(c))["invoice_no"] == "INV-0008"
    run(monkeypatch, mode, scenario)


def test_r49_1_due_date_after_issue_needs_a_reason_and_an_audit_event(monkeypatch, mode):
    async def scenario(c, op):
        inv = await sent(c)
        url = "/api/finance/invoices/" + inv["id"]
        r = await c.put(url, headers=hdr("acct-a"), json={"due_date": "2099-06-30"})
        assert r.status_code == 400 and code(r) == "DUE_DATE_REASON_REQUIRED"
        assert (await get_inv(c, inv["id"]))["due_date"] == "2099-12-31"
        r = await c.put(url, headers=hdr("acct-a"), json={"due_date": "2099-06-30", "reason": "разсрочване"})
        assert r.status_code == 200 and r.json()["due_date"] == "2099-06-30", r.text
        ev = await op.audit_events.find_one({"action": "finance.invoice.due_date_changed"})
        assert ev and ev["reason"] == "разсрочване"
    run(monkeypatch, mode, scenario)


def test_r51_2_supplier_debit_note_needs_basis_file_and_owner_before_it_is_payable(monkeypatch, mode):
    async def scenario(c, op):
        bill = await sent(c, direction="Received")                              # 240
        r = await note(c, bill, kind="debit", number="DN-1")
        assert r.status_code == 422 and code(r) == "DEBIT_NOTE_BASIS_REQUIRED"
        r = await note(c, bill, kind="debit", number="DN-1", basis={"type": "order", "ref": "PO-12"})
        assert r.status_code == 422 and code(r) == "DEBIT_NOTE_BASIS_REQUIRED"   # no file_id
        r = await note(c, bill, kind="debit", number="DN-1", basis={"type": "additional_delivery",
                                                                    "ref": "доставка 12.11"},
                       file_id="file-dn-1")
        assert r.status_code == 201, r.text
        dn = r.json()
        assert (dn["status"], dn["applied"], dn["gross"]) == ("pending_approval", False, 36.0)
        assert (await get_inv(c, bill["id"]))["remaining_amount"] == 240.0
        r = await quick_pay(c, bill["id"], 276.0)
        assert r.status_code == 409 and code(r) == "DEBIT_NOTE_NOT_APPROVED", r.text
        assert (await approve(c, dn["id"], who="acct-a")).status_code == 403
        r = await approve(c, dn["id"])
        assert r.status_code == 200 and r.json()["number"] == "DN-1", r.text      # supplier's number
        assert (await get_inv(c, bill["id"]))["remaining_amount"] == 276.0
        assert (await quick_pay(c, bill["id"], 276.0)).status_code == 201
    run(monkeypatch, mode, scenario)


def test_r51_3_supplier_invoice_entered_by_mistake_is_cancelled_not_deleted(monkeypatch, mode):
    async def scenario(c, op):
        # a draft with the supplier's number → never deleted, cancelled in one step
        d = await draft(c, direction="Received")
        r = await c.delete("/api/finance/invoices/" + d["id"], headers=hdr("acct-a"))
        assert r.status_code == 409 and code(r) == "INVOICE_NUMBERED"
        for who in ("admin-a", "owner-a"):                  # FG-235 / Р51(3): the Accountant only
            r = await c.post("/api/finance/invoices/%s/cancel" % d["id"], headers=hdr(who),
                             json={"reason": "въведена по грешка"})
            assert r.status_code == 403, (who, r.text)
        r = await c.post("/api/finance/invoices/%s/cancel" % d["id"], headers=hdr("acct-a"),
                         json={"reason": "въведена по грешка"})
        assert r.status_code == 200 and r.json()["status"] == "Cancelled", r.text
        assert await op.invoices.count_documents({"id": d["id"]}) == 1
        # paid → 409 USE_CORRECTION
        paid = await sent(c, direction="Received")
        assert (await quick_pay(c, paid["id"], 10.0)).status_code == 201
        r = await c.post("/api/finance/invoices/%s/cancel" % paid["id"], headers=hdr("acct-a"),
                         json={"reason": "грешка"})
        assert r.status_code == 409 and code(r) == "USE_CORRECTION", r.text
        # linked to a warehouse receipt → 409 USE_CORRECTION
        linked = await sent(c, direction="Received")
        await op.invoice_lines.insert_one({"id": "il-1", "org_id": ORG_A, "invoice_id": linked["id"],
                                           "qty": 1, "unit_price": 10})
        await op.warehouse_transactions.insert_one({"id": "wt-1", "org_id": ORG_A, "action": "receive_from_supplier",
                                                    "invoice_line_id": "il-1", "movement_id": "mv-1"})
        r = await c.post("/api/finance/invoices/%s/cancel" % linked["id"], headers=hdr("acct-a"),
                         json={"reason": "грешка"})
        assert r.status_code == 409 and code(r) == "USE_CORRECTION", r.text
        assert (await get_inv(c, linked["id"]))["status"] == "Sent"
        # FG-233: a receipt linked to the invoice ONLY by invoice_id (no line) counts too
        by_id = await sent(c, direction="Received")
        await op.warehouse_transactions.insert_one({"id": "wt-2", "org_id": ORG_A, "action": "receive_from_supplier",
                                                    "invoice_id": by_id["id"], "movement_id": "mv-2"})
        r = await c.post("/api/finance/invoices/%s/cancel" % by_id["id"], headers=hdr("acct-a"),
                         json={"reason": "грешка"})
        assert r.status_code == 409 and code(r) == "USE_CORRECTION", r.text
    run(monkeypatch, mode, scenario)


def test_d9_reversing_a_refund_gives_the_credit_balance_back(monkeypatch, mode):
    async def scenario(c, op):
        inv = await sent(c)
        assert (await quick_pay(c, inv["id"], 240.0)).status_code == 201
        n = (await note(c, inv)).json()
        assert (await approve(c, n["id"])).status_code == 200
        r = await c.post("/api/finance/invoices/%s/refund" % inv["id"], headers=hdr("acct-a"), json={
            "amount": 36.0, "reason": "връщане", "account_id": BANK_A, "method": "BankTransfer"})
        assert r.status_code == 201, r.text
        assert (await get_inv(c, inv["id"]))["credit_balance"] == 0
        r = await c.request("DELETE", "/api/finance/payments/" + r.json()["payment_id"], headers=hdr("acct-a"),
                            json={"reason": "грешна сметка"})
        assert r.status_code == 200, r.text
        assert (await get_inv(c, inv["id"]))["credit_balance"] == 36.0
    run(monkeypatch, mode, scenario)


def test_d10_a_pending_note_is_rejected_or_withdrawn(monkeypatch, mode):
    async def scenario(c, op):
        inv = await sent(c)
        n1 = (await note(c, inv)).json()
        n2 = (await note(c, inv)).json()
        url = "/api/finance/credit-notes/%s/reject"
        assert (await c.post(url % n1["id"], headers=hdr("admin-a"), json={"reason": "x"})).status_code == 403
        assert (await c.post(url % n1["id"], headers=hdr("acct-a"), json={})).status_code == 400
        r = await c.post(url % n1["id"], headers=hdr("acct-a"), json={"reason": "оттеглям"})   # author
        assert r.status_code == 200 and r.json()["status"] == "rejected"
        r = await c.post(url % n2["id"], headers=hdr("owner-a"), json={"reason": "не"})        # Owner
        assert r.status_code == 200 and r.json()["status"] == "rejected"
        r = await approve(c, n1["id"])
        assert r.status_code == 409 and code(r) == "NOT_PENDING_APPROVAL"
        assert (await get_inv(c, inv["id"]))["remaining_amount"] == 240.0
        assert "finance.credit_debit_note.rejected" in await audit_actions(op)
    run(monkeypatch, mode, scenario)


def test_d15_paid_invoice_with_every_payment_cancelled_is_open_again(monkeypatch, mode):
    async def scenario(c, op):
        inv = await sent(c)
        r = await quick_pay(c, inv["id"], 240.0)
        assert (await get_inv(c, inv["id"]))["status"] == "Paid"
        r = await c.request("DELETE", "/api/finance/invoices/%s/payments/%s" % (inv["id"], r.json()["allocation_id"]),
                            headers=hdr("acct-a"), json={"reason": "върнато"})
        assert r.status_code == 200, r.text
        after = await get_inv(c, inv["id"])
        assert (after["status"], after["remaining_amount"]) == ("Sent", 240.0)
    run(monkeypatch, mode, scenario)


# ═══════════════════════════════════════════════════ Addendum B (Р52) + Addendum C (Р53)
def test_r52_d7_owner_accepts_the_difference_limit_uses_the_real_amount(monkeypatch, mode):
    async def scenario(c, op):
        bill = await sent(c, direction="Received")                                     # 240
        await op.expected_credit_notes.insert_one({
            "id": "ecn_d7", "org_id": ORG_A, "invoice_id": bill["id"], "amount": 36.0, "status": "open",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "dq_task": {"title": "очаква кредитно известие", "status": "open"}})
        r = await note(c, bill, number="CN-D7", expected_credit_note_ids=["ecn_d7"],
                       lines=[{"original_line_id": bill["lines"][0]["id"], "amount": 25.0}])   # 30.00
        assert r.status_code == 201 and r.json()["applied"] is False, r.text
        n = r.json()
        url = "/api/finance/credit-notes/%s/accept-difference" % n["id"]
        assert (await c.post(url, headers=hdr("acct-a"), json={"reason": "приемам"})).status_code == 403
        assert (await c.post(url, headers=hdr("owner-a"), json={})).status_code == 400
        r = await c.post(url, headers=hdr("owner-a"), json={"reason": "доставчикът не коригира"})
        assert r.status_code == 200, r.text
        assert r.json()["applied"] is True and r.json()["difference_accepted"]["by"] == "owner-a"
        ecn = await op.expected_credit_notes.find_one({"id": "ecn_d7"})
        assert (ecn["status"], ecn["dq_mismatch"]["status"]) == ("fulfilled_with_difference", "accepted_by_owner")
        inv = await get_inv(c, bill["id"])
        assert (inv["remaining_amount"], inv["awaiting_credit_note"]) == (210.0, False)   # 240 − 30.00
        assert "finance.credit_note.difference_accepted" in await audit_actions(op)
        r = await c.post(url, headers=hdr("owner-a"), json={"reason": "пак"})
        assert r.status_code == 409
    run(monkeypatch, mode, scenario)


def test_r52_d8_unlinked_supplier_credit_reduces_project_cost_once_linked_does_not(monkeypatch, mode):
    async def scenario(c, op):
        from app.services.project_pnl import compute_project_pnl
        cost = lambda p: p["expense"]["material_cost"]
        reduction = lambda p: p["expense"]["supplier_notes_cost_reduction"]
        bill = await sent(c, direction="Received", project="prj-1")
        base = await compute_project_pnl(ORG_A, "prj-1")
        # a discount / defect credit (no reversal) → the original line's project, once
        r = await note(c, bill, number="CN-D8a")                                         # net 30
        assert r.status_code == 201 and r.json()["applied"] is True
        after = await compute_project_pnl(ORG_A, "prj-1")
        assert (round(cost(base) - cost(after), 2), reduction(after)) == (30.0, 30.0)
        again = await compute_project_pnl(ORG_A, "prj-1")
        assert cost(again) == cost(after)                                               # exactly once
        # a credit linked to a receipt reversal → payable only, no second P&L effect
        bill2 = await sent(c, direction="Received", project="prj-1")
        await op.expected_credit_notes.insert_one({
            "id": "ecn_d8", "org_id": ORG_A, "invoice_id": bill2["id"], "amount": 36.0, "status": "open",
            "created_at": datetime.now(timezone.utc).isoformat(), "dq_task": {"status": "open"}})
        r = await note(c, bill2, number="CN-D8b", expected_credit_note_ids=["ecn_d8"])
        assert r.status_code == 201 and r.json()["applied"] is True
        linked = await compute_project_pnl(ORG_A, "prj-1")
        assert cost(linked) == cost(after) and reduction(linked) == 30.0
        assert (await get_inv(c, bill2["id"]))["remaining_amount"] == 204.0               # payable reduced
        # a line allocated to two projects: only this project's share
        bill3 = await sent(c, direction="Received", project="prj-2")
        await op.invoice_lines.insert_one({
            "id": "il-d8", "org_id": ORG_A, "invoice_id": bill3["id"], "qty": 10, "unit_price": 10,
            "vat_percent": 20, "allocations": [{"type": "project", "ref_id": "prj-1", "qty": 4},
                                               {"type": "project", "ref_id": "prj-2", "qty": 6}]})
        r = await note(c, bill3, number="CN-D8c", lines=[{"original_line_id": "il-d8", "amount": 50}])
        assert r.status_code == 201, r.text
        shared = await compute_project_pnl(ORG_A, "prj-1")
        assert round(cost(after) - cost(shared), 2) == 20.0                              # 4/10 × 50
    run(monkeypatch, mode, scenario)


def test_r52_d12_prefix_change_does_not_reset_the_counter(monkeypatch, mode):
    async def scenario(c, op):
        assert (await issued(c))["invoice_no"] == "INV-0001"
        assert (await issued(c))["invoice_no"] == "INV-0002"
        r = await c.put("/api/finance/invoice-settings", headers=hdr("owner-a"), json={"issued_prefix": "BG"})
        assert r.status_code == 200
        assert (await issued(c))["invoice_no"] == "BG-0003"
    run(monkeypatch, mode, scenario)


def test_fg231_same_number_from_two_suppliers_is_fine_same_supplier_is_a_duplicate(monkeypatch, mode):
    async def scenario(c, op):
        body = {"direction": "Received", "invoice_no": "F-100", "issue_date": "2026-11-08",
                "due_date": "2099-12-31", "lines": LINES}
        r1 = await c.post("/api/finance/invoices", headers=hdr("acct-a"),
                          json={**body, "counterparty_eik": EIK, "counterparty_name": "Доставчик 1"})
        r2 = await c.post("/api/finance/invoices", headers=hdr("acct-a"),
                          json={**body, "counterparty_eik": "831826092", "counterparty_name": "Доставчик 2"})
        assert (r1.status_code, r2.status_code) == (201, 201), (r1.text, r2.text)
        r3 = await c.post("/api/finance/invoices", headers=hdr("acct-a"),
                          json={**body, "counterparty_eik": EIK, "counterparty_name": "Доставчик 1"})
        assert r3.status_code == 409 and code(r3) == "DUPLICATE_SUPPLIER_INVOICE", r3.text
        # the index enforces it too (a write that skips the check)
        from pymongo.errors import DuplicateKeyError
        dup = {**(await op.invoices.find_one({"id": r1.json()["id"]}, {"_id": 0})), "id": "dup-1"}
        with pytest.raises(DuplicateKeyError):
            await op.invoices.insert_one(dup)
        # our outgoing series is separate: our INV-0001 next to a supplier's INV-0001
        r4 = await c.post("/api/finance/invoices", headers=hdr("acct-a"),
                          json={**body, "invoice_no": "INV-0001", "counterparty_eik": EIK})
        assert r4.status_code == 201
        assert (await issued(c))["invoice_no"] == "INV-0001"
    run(monkeypatch, mode, scenario)


def test_fg231_migration_backfills_supplier_key_and_reports_conflicts(monkeypatch, mode):
    async def scenario(c, op):
        from app.services import invoice_corrections_migration as mig
        await op.invoices.drop_index("inv_cn_02_supplier_invoice_no")      # a legacy database
        for i, (eik, no) in enumerate((("111111111", "A-1"), ("222222222", "A-1"))):
            await op.invoices.insert_one({"id": "leg-%d" % i, "org_id": ORG_A, "direction": "Received",
                                          "status": "Sent", "invoice_no": no, "counterparty_eik": eik})
        plan = await mig.plan(op)
        keys = {k["id"]: k["supplier_key"] for t in plan["tenants"] for k in t["supplier_keys_to_set"]}
        assert keys == {"leg-0": "eik:111111111", "leg-1": "eik:222222222"} and plan["supplier_conflicts"] == 0
        await mig.apply(op, actor_id="owner-a")
        assert (await op.invoices.find_one({"id": "leg-1"}))["supplier_key"] == "eik:222222222"
        assert "inv_cn_02_supplier_invoice_no" in await op.invoices.index_information()
        # the same supplier + number twice → reported, apply refuses, nothing changed
        await op.invoices.drop_index("inv_cn_02_supplier_invoice_no")
        await op.invoices.insert_one({"id": "leg-2", "org_id": ORG_A, "direction": "Received",
                                      "status": "Sent", "invoice_no": "A-1", "counterparty_eik": "111111111"})
        plan = await mig.plan(op)
        assert plan["supplier_conflicts"] == 1
        with pytest.raises(RuntimeError):
            await mig.apply(op, actor_id="owner-a")
        assert "supplier_key" not in await op.invoices.find_one({"id": "leg-2"})
    run(monkeypatch, mode, scenario)


def test_fg232_editor_put_of_a_draft_with_a_typed_number_is_not_a_500(monkeypatch, mode):
    async def scenario(c, op):
        d = await draft(c)
        # exactly the InvoiceEditorPage PUT payload
        r = await c.put("/api/finance/invoices/" + d["id"], headers=hdr("acct-a"), json={
            "invoice_no": "INV-0042", "kind": "Invoice", "counterparty_name": "Клиент ООД",
            "counterparty_eik": EIK, "counterparty_vat_no": None, "counterparty_address": None,
            "counterparty_mol": None, "counterparty_email": None, "counterparty_phone": None,
            "project_id": "prj-1", "issue_date": "2026-11-08", "due_date": "2099-12-31",
            "vat_percent": 20, "notes": "бележка"})
        assert r.status_code == 200, r.text
        assert "invoice_no" not in await op.invoices.find_one({"id": d["id"]})   # still unnumbered
        bill = await draft(c, direction="Received")
        r = await c.put("/api/finance/invoices/" + bill["id"], headers=hdr("acct-a"),
                        json={"invoice_no": "SUP-NEW", "notes": "x"})
        assert r.status_code == 200 and r.json()["invoice_no"] == "SUP-NEW", r.text
    run(monkeypatch, mode, scenario)


def test_fg235_notes_change_on_a_sent_invoice_is_audited(monkeypatch, mode):
    async def scenario(c, op):
        inv = await sent(c)
        r = await c.put("/api/finance/invoices/" + inv["id"], headers=hdr("acct-a"), json={"notes": "нова бележка"})
        assert r.status_code == 200, r.text
        ev = await op.audit_events.find_one({"action": "finance.invoice.notes_changed"})
        assert ev and ev["structured_diff"]["notes"]["after"] == "нова бележка"
    run(monkeypatch, mode, scenario)
