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
    "owner-a": (ORG_A, "Owner"), "owner2-a": (ORG_A, "Owner"), "admin-a": (ORG_A, "Admin"), "acct-a": (ORG_A, "Accountant"),
    "viewer-a": (ORG_A, "Viewer"), "site-a": (ORG_A, "SiteManager"), "admin-b": (ORG_B, "Admin"),
    "owner-b": (ORG_B, "Owner"),
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
    from app.routes import project_pnl as r_pnl           # /org/pnl-attribution (Q007)
    monkeypatch.setattr(r_pnl, "db", op)
    app.include_router(r_pnl.router, prefix="/api")
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
                from app.services.invoice_corrections import INVOICE_NO_INDEX
                await op.invoices.create_index(INVOICE_NO_INDEX[1], **INVOICE_NO_INDEX[2])
                # (the per-supplier index is built by the migration only — FG-248)
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
             "created_at": old}])
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
        assert ecn["status"] == "open" and "dq_mismatch" not in ecn
        mism = await op.dq_issues.find_one({"id": "dq-credit-note-difference-" + r.json()["id"]})
        assert (mism["type"], mism["title"], mism["status"], mism["owner_role"]) == (
            "CREDIT_NOTE_DIFFERENCE", "разлика в кредитно известие", "open", "accountant")
        cn77_id = r.json()["id"]
        assert (await get_inv(c, bill["id"]))["remaining_amount"] == 240.0
        # a duplicate (same supplier, same number) → 409
        r = await note(c, bill, number="CN-77", expected_credit_note_ids=["ecn_1"])
        assert r.status_code == 409 and code(r) == "DUPLICATE_CREDIT_NOTE"
        # exactly to the cent → fulfilled, DQ closed, payable recomputed
        r = await note(c, bill, number="CN-78", expected_credit_note_ids=["ecn_1"])   # qty 3 → 36.00
        assert r.status_code == 201 and r.json()["applied"] is True, r.text
        ecn = await op.expected_credit_notes.find_one({"id": "ecn_1"})
        assert ecn["status"] == "fulfilled" and "dq_task" not in ecn
        # Р52(2a): the corrected note resolved the mismatch DQ issue + alarm; superseded note
        mism = await op.dq_issues.find_one({"id": "dq-credit-note-difference-" + cn77_id})
        assert mism["status"] == "resolved" and mism["resolution"]["corrected_by_credit_note_id"] == r.json()["id"]
        assert (await op.alarm_events.find_one({"id": "alarm-credit-note-difference-" + cn77_id}))["status"] == "resolved"
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


def test_r74_fg453_an_offset_of_a_supplier_invoice_follows_the_payment_rules(monkeypatch, mode):
    """Р74 (FG-453): an offset is a payment — Р44 allocation, the Р47 cap, Р51(4) 2nd person."""
    async def scenario(c, op):
        a = await sent(c, direction="Received")                          # supplier invoice, 240
        assert (await quick_pay(c, a["id"], 240.0)).status_code == 201
        n = await note(c, a, number="CN-74")                              # registered, applied
        assert n.status_code == 201 and n.json()["applied"] is True, n.text
        n = n.json()                                                      # A: credit balance 36
        b = await sent(c, direction="Received")                           # B: open 240, same contract
        # Р44: a line of B without final allocation → no offset (as no payment), nothing written
        line = b["lines"][0]
        await op.invoices.update_one({"id": b["id"]}, {"$set": {
            "lines.0.allocations": [{"type": "project", "ref_id": "prj-1", "qty": line["qty"] - 1}]}})
        r = await offset(c, a, b, 10, n["id"])
        assert r.status_code == 409 and code(r) == "INVOICE_NOT_FULLY_ALLOCATED", r.text
        assert await op.invoice_offsets.count_documents({}) == 0
        await op.invoices.update_one({"id": b["id"]}, {"$set": {
            "lines.0.allocations": [{"type": "project", "ref_id": "prj-1", "qty": line["qty"]}]}})
        # Р47: B awaits a credit of 220 after a reversal → payable until the note 20 → 36 refused
        await op.expected_credit_notes.insert_one({
            "id": "ecn_74", "org_id": ORG_A, "invoice_id": b["id"], "amount": 220.0, "status": "open",
            "created_at": datetime.now(timezone.utc).isoformat()})
        r = await offset(c, a, b, 36, n["id"])
        assert r.status_code == 409 and code(r) == "INVOICE_AWAITS_CREDIT_NOTE", r.text
        assert r.json()["detail"]["payable_until_credit_note"] == 20.0
        assert (await offset(c, a, b, 20, n["id"])).status_code == 201   # within the cap: requested
        await op.invoice_offsets.update_many({}, {"$set": {"status": "rejected"}})   # (clean slate)
        await op.expected_credit_notes.update_one({"id": "ecn_74"}, {"$set": {"status": "fulfilled"}})
        # positive: requested by the Accountant, approved by the Owner (Р51(4): two people)
        off = (await offset(c, a, b, 36, n["id"])).json()
        assert off["status"] == "pending_approval", off
        assert (await c.post("/api/finance/offsets/%s/approve" % off["id"], headers=hdr("acct-a"),
                             json={"version": 1})).status_code == 403       # not the Owner
        # the cap is re-checked AT THE APPROVAL (a reversal arrived meanwhile) → 409, nothing applied
        await op.expected_credit_notes.update_one({"id": "ecn_74"}, {"$set": {"status": "open"}})
        r = await c.post("/api/finance/offsets/%s/approve" % off["id"], headers=hdr("owner-a"),
                         json={"version": 1})
        assert r.status_code == 409 and code(r) == "INVOICE_AWAITS_CREDIT_NOTE", r.text
        assert (await get_inv(c, b["id"]))["remaining_amount"] == 240.0
        await op.expected_credit_notes.update_one({"id": "ecn_74"}, {"$set": {"status": "fulfilled"}})
        r = await c.post("/api/finance/offsets/%s/approve" % off["id"], headers=hdr("owner-a"),
                         json={"version": 1})
        assert r.status_code == 200, r.text
        assert (await get_inv(c, b["id"]))["remaining_amount"] == 204.0
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
        # FG-599: the Owner can no longer author an outgoing note; the author ≠ approver guard
        # stays as defence in depth — a (legacy) note authored by the Owner → 409
        own = (await note(c, inv)).json()
        await op.credit_debit_notes.update_one({"id": own["id"]}, {"$set": {"created_by": "owner-a"}})
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


def test_fg599_r49_4_outgoing_note_issued_by_accountant_approved_by_owner(monkeypatch, mode):
    """FG-599, Р49(4): "известие към клиент: Счетоводител издава, Собственик одобрява (двама
    различни)" — for a credit AND a debit note to a client. In every mode (the catalog grants
    finance.credit_note.create to Owner / Admin / Accountant, so the narrower rule lives in the
    route, like REGISTRAR_ROLE_REQUIRED): Owner / Admin → 403 ISSUER_ROLE_REQUIRED and nothing
    written; Viewer / Site → 403; Accountant → 201. Only an Owner approves; the Accountant and
    the Admin cannot. A supplier (incoming) note keeps its rule: the Accountant registers it."""
    async def scenario(c, op):
        inv = await sent(c)
        line = inv["lines"][0]["id"]
        debit = {"kind": "debit", "basis": {"type": "act", "id": "act-1"}}
        counters = await op.org_counters.find({}, {"_id": 0}).to_list(None)
        for extra in ({"kind": "credit"}, debit):
            for who in ("owner-a", "owner2-a", "admin-a"):
                r = await note(c, inv, who=who, lines=[{"original_line_id": line, "qty": 1}], **extra)
                assert r.status_code == 403 and code(r) == "ISSUER_ROLE_REQUIRED", (who, extra, r.text)
            for who in ("viewer-a", "site-a"):
                r = await note(c, inv, who=who, lines=[{"original_line_id": line, "qty": 1}], **extra)
                assert r.status_code == 403, (who, extra, r.text)
        assert await op.credit_debit_notes.count_documents({}) == 0      # nothing written
        assert await op.org_counters.find({}, {"_id": 0}).to_list(None) == counters   # no number taken
        made = {}
        for extra in ({"kind": "credit"}, debit):
            r = await note(c, inv, lines=[{"original_line_id": line, "qty": 1}], **extra)   # acct-a
            assert r.status_code == 201, (extra, r.text)
            assert r.json()["created_by"] == "acct-a" and r.json()["status"] == "pending_approval"
            made[extra["kind"]] = r.json()["id"]
        for nid in made.values():
            for who in ("acct-a", "admin-a", "viewer-a"):
                assert (await approve(c, nid, who=who)).status_code == 403, who
        assert (await approve(c, made["credit"], who="owner-a")).status_code == 200
        assert (await approve(c, made["debit"], who="owner2-a")).status_code == 200
        for nid in made.values():
            doc = await op.credit_debit_notes.find_one({"id": nid})
            assert doc["status"] == "approved" and doc["created_by"] == "acct-a"
            assert doc["approved_by"] in ("owner-a", "owner2-a") and doc["approved_by"] != doc["created_by"]
        # incoming (supplier) notes are unchanged: the Accountant registers, Owner / Admin cannot
        bill = await sent(c, direction="Received")
        for who in ("owner-a", "admin-a"):
            r = await note(c, bill, who=who, number="CN-%s" % who,
                           lines=[{"original_line_id": bill["lines"][0]["id"], "qty": 1}])
            assert r.status_code == 403 and code(r) == "REGISTRAR_ROLE_REQUIRED", (who, r.text)
        r = await note(c, bill, number="CN-ACCT", lines=[{"original_line_id": bill["lines"][0]["id"], "qty": 1}])
        assert r.status_code == 201, r.text
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
            "created_at": datetime.now(timezone.utc).isoformat(), "created_by": "acct-a"})
        # FG-465: the Р47 issue „очаква кредитно известие“ + alarm, opened by #82's own path
        from app.services.invoice_allocation import sync_credit_note_issue
        from app.tenancy.data_access import TenantData
        await sync_credit_note_issue(TenantData.for_resolved_org(op, ORG_A), bill["id"])
        r47 = await op.dq_issues.find_one({"id": "dq-credit-note-" + bill["id"]})
        assert (r47["type"], r47["status"], r47["awaited_credit"]) == ("INVOICE_AWAITS_CREDIT_NOTE", "open", 36.0)
        if pr82:
            r = await quick_pay(c, bill["id"], 205.0)
            assert r.status_code == 409 and code(r) == "INVOICE_AWAITS_CREDIT_NOTE", r.text
        r = await note(c, bill, number="CN-R47", expected_credit_note_ids=["ecn_mv-1"])   # 36.00
        assert r.status_code == 201 and r.json()["applied"] is True, r.text
        ecn = await op.expected_credit_notes.find_one({"id": "ecn_mv-1"})
        assert (ecn["status"], ecn["credit_note_id"]) == ("fulfilled", r.json()["id"])
        # FG-465: the registration resolved the Р47 issue + its alarm (same transaction), AuditEvent
        r47 = await op.dq_issues.find_one({"id": "dq-credit-note-" + bill["id"]})
        assert r47["status"] == "resolved" and r47["resolved_at"]
        assert (await op.alarm_events.find_one({"id": "alarm-credit-note-" + bill["id"]}))["status"] == "resolved"
        assert await op.audit_events.find_one({"action": "dq.credit_note.resolved"})
        assert await op.dq_issues.count_documents({"kind": {"$exists": True}}) == 0       # ONE schema
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
            "created_at": datetime.now(timezone.utc).isoformat()})
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
        assert ecn["status"] == "fulfilled_with_difference" and "dq_mismatch" not in ecn
        mism = await op.dq_issues.find_one({"id": "dq-credit-note-difference-" + n["id"]})
        assert (mism["status"], mism["resolution"]["accepted_by"]) == ("resolved", "owner-a")
        inv = await get_inv(c, bill["id"])
        assert (inv["remaining_amount"], inv["awaiting_credit_note"]) == (210.0, False)   # 240 − 30.00
        assert "finance.credit_note.difference_accepted" in await audit_actions(op)
        r = await c.post(url, headers=hdr("owner-a"), json={"reason": "пак"})
        assert r.status_code == 409
    run(monkeypatch, mode, scenario)


def test_r52_d8_unlinked_supplier_credit_reduces_project_cost_once_linked_does_not(monkeypatch, mode):
    """Р52(1) + FG-247: the effect is in THE cost source (project_material_cost) — so the
    P&L, the financial results, input VAT and the per-period split all agree; only a line
    that IS in the project's cost base (Path B) changes it; dated by the note."""
    async def scenario(c, op):
        from app.services import project_financial_results as pfr
        from app.services.canonical_material_cost import cost_by_period, project_input_vat, project_material_cost
        from app.services.project_pnl import compute_project_pnl
        from app.tenancy.data_access import TenantData
        import importlib
        from tests.test_warehouse_canonical_c22_all_reports_cutover import _DB_MODULES
        for name in _DB_MODULES + ("app.services.project_financial_results",):
            module = importlib.import_module(name)
            if hasattr(module, "db"):
                monkeypatch.setattr(module, "db", op)
        tenant = TenantData.for_resolved_org(op, ORG_A)

        async def readers(prj="prj-1"):
            mat = await project_material_cost(tenant, ORG_A, prj)
            pnl = await compute_project_pnl(ORG_A, prj)
            fin = await pfr.compute_financial_results(ORG_A, prj)
            return {"helper": mat["total_cost"], "pnl": pnl["expense"]["material_cost"],
                    "results": fin["cash"]["breakdown"]["paid_materials"],
                    "vat": await project_input_vat(tenant, ORG_A, prj),
                    "periods": cost_by_period(mat), "note_cost": mat["supplier_note_cost"]}

        # (a) an invoice with embedded lines only is no Path B cost → a credit changes nothing
        bill = await sent(c, direction="Received", project="prj-1")
        base = await readers()
        r = await note(c, bill, number="CN-EMB")
        assert r.status_code == 201 and r.json()["applied"] is True
        same = await readers()
        assert (same["helper"], same["pnl"], same["note_cost"]) == (base["helper"], base["pnl"], 0.0)

        # (b) a Path B line (10 × 10 = 100, VAT 20) allocated to prj-1
        pb = await sent(c, direction="Received", project="prj-1")
        await op.invoice_lines.insert_one({
            "id": "il-pb", "org_id": ORG_A, "invoice_id": pb["id"], "description": "Лепило",
            "qty": 10, "unit": "bag", "unit_price": 10, "line_total_ex_vat": 100.0, "vat_percent": 20,
            "vat_amount": 20.0, "line_total_inc_vat": 120.0, "created_at": "2026-11-02T08:00:00+00:00",
            "allocations": [{"type": "project", "ref_id": "prj-1", "qty": 10}]})
        before = await readers()
        assert before["helper"] - base["helper"] == 100.0
        r = await note(c, pb, number="CN-PB", issue_date="2026-12-15",
                       lines=[{"original_line_id": "il-pb", "amount": 50}])
        assert r.status_code == 201, r.text
        after = await readers()
        for k in ("helper", "pnl", "results"):
            assert round(before[k] - after[k], 2) == 50.0, (k, before[k], after[k])
        assert round(before["vat"] - after["vat"], 2) == 10.0                      # (c) 20 → 10
        assert after["periods"]["2026-12"]["total"] == -50.0                       # (d) note's period
        assert after["periods"]["2026-11"] == before["periods"]["2026-11"]
        again = await readers()
        assert again["helper"] == after["helper"]                                  # exactly once

        # a credit linked to a receipt reversal → payable only, no cost effect
        pb2 = await sent(c, direction="Received", project="prj-1")
        await op.invoice_lines.insert_one({
            "id": "il-pb2", "org_id": ORG_A, "invoice_id": pb2["id"], "description": "Лепило",
            "qty": 10, "unit_price": 10, "line_total_ex_vat": 100.0, "vat_amount": 20.0,
            "allocations": [{"type": "project", "ref_id": "prj-1", "qty": 10}]})
        await op.expected_credit_notes.insert_one({
            "id": "ecn_pb2", "org_id": ORG_A, "invoice_id": pb2["id"], "amount": 60.0, "status": "open",
            "created_at": datetime.now(timezone.utc).isoformat()})
        pre = await readers()
        r = await note(c, pb2, number="CN-LNK", expected_credit_note_ids=["ecn_pb2"],
                       lines=[{"original_line_id": "il-pb2", "amount": 50}])
        assert r.status_code == 201 and r.json()["applied"] is True, r.text
        linked = await readers()
        assert (linked["helper"], linked["pnl"]) == (pre["helper"], pre["pnl"])

        # a line allocated to two projects: only this project's share, never below its value
        two = await sent(c, direction="Received", project="prj-2")
        await op.invoice_lines.insert_one({
            "id": "il-2p", "org_id": ORG_A, "invoice_id": two["id"], "qty": 10, "unit_price": 10,
            "line_total_ex_vat": 100.0, "vat_amount": 20.0,
            "allocations": [{"type": "project", "ref_id": "prj-1", "qty": 4},
                            {"type": "project", "ref_id": "prj-2", "qty": 6}]})
        p1, p2 = await readers("prj-1"), await readers("prj-2")
        r = await note(c, two, number="CN-2P", lines=[{"original_line_id": "il-2p", "amount": 50}])
        assert r.status_code == 201, r.text
        q1, q2 = await readers("prj-1"), await readers("prj-2")
        assert (round(p1["helper"] - q1["helper"], 2), round(p2["helper"] - q2["helper"], 2)) == (20.0, 30.0)
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
        # after the migration, the index enforces it too (a write that skips the check)
        from app.services import invoice_corrections_migration as mig
        await mig.apply(op, actor_id="owner-a")
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


def test_fg248_before_the_migration_a_legacy_supplier_number_still_blocks_a_duplicate(monkeypatch, mode):
    async def scenario(c, op):
        from app.services import invoice_corrections_migration as mig
        await op.invoices.insert_one({"id": "leg-eik", "org_id": ORG_A, "direction": "Received",
                                      "status": "Sent", "invoice_no": "F-7", "counterparty_eik": EIK})
        await op.invoices.insert_one({"id": "leg-cp", "org_id": ORG_A, "direction": "Received",
                                      "status": "Sent", "invoice_no": "F-8", "supplier_counterparty_id": "cp-1"})
        body = {"direction": "Received", "issue_date": "2026-11-08", "due_date": "2099-12-31", "lines": LINES}
        r = await c.post("/api/finance/invoices", headers=hdr("acct-a"),
                         json={**body, "invoice_no": "F-7", "counterparty_eik": EIK})
        assert r.status_code == 409 and code(r) == "DUPLICATE_SUPPLIER_INVOICE", r.text
        # Р55(1): a new supplier invoice must name the ЕИК / foreign tax number at all
        r = await c.post("/api/finance/invoices", headers=hdr("acct-a"),
                         json={**body, "invoice_no": "F-8", "supplier_counterparty_id": "cp-1"})
        assert r.status_code == 422 and code(r) == "SUPPLIER_TAX_ID_REQUIRED", r.text
        r = await c.post("/api/finance/invoices", headers=hdr("acct-a"),
                         json={**body, "invoice_no": "F-7", "counterparty_eik": "831826092"})
        assert r.status_code == 201, r.text                         # another supplier
        assert (await mig.plan(op))["supplier_conflicts"] == 0
        await mig.apply(op, actor_id="owner-a")                      # backfill, then the index
        assert "inv_cn_02_supplier_invoice_no" in await op.invoices.index_information()
    run(monkeypatch, mode, scenario)


def test_fg246_an_invoice_in_an_offset_is_not_cancelled_and_the_offset_supersedes_a_proposal(monkeypatch, mode):
    async def scenario(c, op):
        a = await sent(c)
        assert (await quick_pay(c, a["id"], 240.0)).status_code == 201
        n = (await note(c, a)).json()
        assert (await approve(c, n["id"])).status_code == 200            # A: credit balance 36
        b = await issued(c)                                               # B: issued, not sent
        url = "/api/finance/invoices/%s/cancel" % b["id"]
        assert (await c.post(url, headers=hdr("acct-a"), json={"reason": "грешка"})).status_code == 200
        off = (await offset(c, a, b, 36, n["id"])).json()
        r = await c.post("/api/finance/offsets/%s/approve" % off["id"], headers=hdr("owner-a"), json={"version": 1})
        assert r.status_code == 200, r.text
        inv_b = await get_inv(c, b["id"])
        assert inv_b["cancellation_request"]["status"] == "superseded"
        assert inv_b["cancellation_request"]["superseded_by"] == "offset"
        assert "finance.invoice.cancellation_superseded" in await audit_actions(op)
        r = await c.post(url, headers=hdr("acct-a"), json={"reason": "пак"})
        assert r.status_code == 409 and code(r) == "USE_CREDIT_NOTE", r.text
        assert (await get_inv(c, b["id"]))["status"] == "Issued"
        # a pending (not yet approved) offset blocks the cancel too
        c2 = await issued(c)
        a2 = await sent(c)
        assert (await quick_pay(c, a2["id"], 240.0)).status_code == 201
        n2 = (await note(c, a2)).json()
        assert (await approve(c, n2["id"])).status_code == 200
        assert (await offset(c, a2, c2, 10, n2["id"])).status_code == 201
        r = await c.post("/api/finance/invoices/%s/cancel" % c2["id"], headers=hdr("acct-a"), json={"reason": "x"})
        assert r.status_code == 409 and code(r) == "USE_CREDIT_NOTE"
    run(monkeypatch, mode, scenario)



# ═══════════════════════════════════════════════════ Addendum D (Р55)
def test_fg249_supplier_tax_id_is_mandatory_duplicates_by_put_are_409_legacy_gets_dq(monkeypatch, mode):
    async def scenario(c, op):
        body = {"direction": "Received", "invoice_no": "S-1", "issue_date": "2026-11-08",
                "due_date": "2099-12-31", "counterparty_name": "Доставчик", "lines": LINES}
        r = await c.post("/api/finance/invoices", headers=hdr("acct-a"), json=body)
        assert r.status_code == 422 and code(r) == "SUPPLIER_TAX_ID_REQUIRED", r.text
        assert await op.invoices.count_documents({"invoice_no": "S-1"}) == 0
        r = await c.post("/api/finance/invoices", headers=hdr("acct-a"),
                         json={**body, "counterparty_foreign_tax_no": "DE123456789"})       # foreign
        assert r.status_code == 201 and r.json()["supplier_key"] == "tax:DE123456789", r.text
        a = await c.post("/api/finance/invoices", headers=hdr("acct-a"), json={**body, "invoice_no": "S-2",
                                                                              "counterparty_eik": EIK})
        b = await c.post("/api/finance/invoices", headers=hdr("acct-a"), json={**body, "invoice_no": "S-2",
                                                                              "counterparty_eik": "831826092"})
        assert (a.status_code, b.status_code) == (201, 201)
        # a PUT that would make b a duplicate of a (same supplier + number) → 409, never 500
        r = await c.put("/api/finance/invoices/" + b.json()["id"], headers=hdr("acct-a"),
                        json={"counterparty_eik": EIK})
        assert r.status_code == 409 and code(r) == "DUPLICATE_SUPPLIER_INVOICE", r.text
        r = await c.put("/api/finance/invoices/" + b.json()["id"], headers=hdr("acct-a"),
                        json={"counterparty_eik": ""})
        assert r.status_code == 422 and code(r) == "SUPPLIER_TAX_ID_REQUIRED", r.text
        # a legacy supplier invoice without ЕИК / tax number → a DQ task for the Accountant
        await op.invoices.insert_one({"id": "leg-noeik", "org_id": ORG_A, "direction": "Received",
                                      "status": "Sent", "invoice_no": "OLD-1", "counterparty_name": "Стар"})
        from app.services import invoice_corrections_migration as mig
        plan = await mig.plan(op)
        assert [i for t in plan["tenants"] for i in t["supplier_tax_id_missing"]] == ["leg-noeik"]
        await mig.apply(op, actor_id="owner-a")
        dq = await op.dq_issues.find({"entity_id": "leg-noeik"}, {"_id": 0}).to_list(None)
        assert [(d["type"], d["owner_role"], d["status"], d["entity_type"]) for d in dq] == [
            ("SUPPLIER_TAX_ID_MISSING", "accountant", "open", "invoice")]
        assert (await op.alarm_events.find_one({"id": "alarm-supplier-tax-id-missing-leg-noeik"}))["status"] == "active"
        assert (await mig.plan(op))["changes"] == 0
        await mig.apply(op, actor_id="owner-a")                                  # idempotent
        assert await op.dq_issues.count_documents({"entity_id": "leg-noeik"}) == 1
    run(monkeypatch, mode, scenario)


def test_fg250_accountant_registers_owner_accepts_never_the_same_person(monkeypatch, mode):
    async def scenario(c, op):
        bill = await sent(c, direction="Received")
        for who in ("owner-a", "admin-a"):
            r = await note(c, bill, number="CN-X", who=who)
            assert r.status_code == 403 and code(r) == "REGISTRAR_ROLE_REQUIRED", (who, r.text)
        await op.expected_credit_notes.insert_one({
            "id": "ecn_250", "org_id": ORG_A, "invoice_id": bill["id"], "amount": 36.0, "status": "open",
            "created_at": datetime.now(timezone.utc).isoformat()})
        n = (await note(c, bill, number="CN-250", expected_credit_note_ids=["ecn_250"],
                        lines=[{"original_line_id": bill["lines"][0]["id"], "amount": 25.0}])).json()
        # a registrant who is (also) the acceptor → 409 (two different people, Р55(2))
        await op.credit_debit_notes.update_one({"id": n["id"]}, {"$set": {"created_by": "owner-a"}})
        r = await c.post("/api/finance/credit-notes/%s/accept-difference" % n["id"], headers=hdr("owner-a"),
                         json={"reason": "приемам"})
        assert r.status_code == 409 and code(r) == "SAME_PERSON_APPROVAL", r.text
        assert (await op.credit_debit_notes.find_one({"id": n["id"]}))["applied"] is False
    run(monkeypatch, mode, scenario)


def test_fg251_an_accepted_difference_after_a_reversal_is_project_cost_in_the_acceptance_period(monkeypatch, mode):
    async def scenario(c, op):
        import importlib
        from app.services.canonical_material_cost import cost_by_period, project_material_cost
        from app.services.project_pnl import compute_project_pnl
        from app.tenancy.data_access import TenantData
        from tests.test_warehouse_canonical_c22_all_reports_cutover import _DB_MODULES
        for name in _DB_MODULES:
            module = importlib.import_module(name)
            if hasattr(module, "db"):
                monkeypatch.setattr(module, "db", op)
        tenant = TenantData.for_resolved_org(op, ORG_A)
        bill = await sent(c, direction="Received", project="prj-1")
        await op.invoice_lines.insert_one({
            "id": "il-251", "org_id": ORG_A, "invoice_id": bill["id"], "description": "Лепило",
            "qty": 10, "unit_price": 10, "line_total_ex_vat": 100.0, "vat_amount": 20.0,
            "created_at": "2026-10-02T08:00:00+00:00",
            "allocations": [{"type": "project", "ref_id": "prj-1", "qty": 10}]})
        # the reversal (#82) awaits 36.00 (3 × 10 + VAT); the supplier credits only 30.00
        await op.expected_credit_notes.insert_one({
            "id": "ecn_251", "org_id": ORG_A, "invoice_id": bill["id"], "invoice_line_id": "il-251",
            "amount": 36.0, "status": "open", "created_at": "2026-10-05T08:00:00+00:00"})
        n = (await note(c, bill, number="CN-251", expected_credit_note_ids=["ecn_251"],
                        lines=[{"original_line_id": "il-251", "amount": 25.0}])).json()
        assert (n["gross"], n["applied"]) == (30.0, False)
        before = await project_material_cost(tenant, ORG_A, "prj-1")
        pnl_before = await compute_project_pnl(ORG_A, "prj-1")
        r = await c.post("/api/finance/credit-notes/%s/accept-difference" % n["id"], headers=hdr("owner-a"),
                         json={"reason": "доставчикът не коригира"})
        assert r.status_code == 200, r.text
        accepted_at = r.json()["difference_accepted"]["at"]
        after = await project_material_cost(tenant, ORG_A, "prj-1")
        pnl_after = await compute_project_pnl(ORG_A, "prj-1")
        assert round(after["total_cost"] - before["total_cost"], 2) == 5.0           # 6.00 gross → 5.00 net
        assert round(pnl_after["expense"]["material_cost"] - pnl_before["expense"]["material_cost"], 2) == 5.0
        period = accepted_at[:7]
        diff_lines = [ln for ln in after["lines"] if ln.get("kind") == "accepted_difference"]
        assert [(ln["value"], ln["period"]) for ln in diff_lines] == [(5.0, period)]
        assert cost_by_period(after)[period]["total"] - cost_by_period(before).get(period, {}).get("total", 0) == 5.0
        ev = await op.audit_events.find_one({"action": "finance.credit_note.difference_accepted"})
        assert ev["structured_diff"]["difference_gross"] == 6.0 and ev["structured_diff"]["cost_period"] == period
    run(monkeypatch, mode, scenario)



def test_r58_an_accepted_difference_on_a_warehouse_line_is_a_company_cost_fifo_unchanged(monkeypatch, mode):
    async def scenario(c, op):
        from app.services.canonical_material_cost import project_material_cost
        from app.tenancy.data_access import TenantData
        tenant = TenantData.for_resolved_org(op, ORG_A)
        bill = await sent(c, direction="Received", project="prj-1")
        for lid, desc in (("il-58w", "Плочки"), ("il-58p", "Лепило")):
            row = {"id": lid, "org_id": ORG_A, "invoice_id": bill["id"], "description": desc,
                   "qty": 10, "unit_price": 10, "line_total_ex_vat": 100.0, "vat_amount": 20.0,
                   "created_at": "2026-10-02T08:00:00+00:00"}
            if lid == "il-58p":
                row["allocations"] = [{"type": "project", "ref_id": "prj-1", "qty": 10}]
            await op.invoice_lines.insert_one(row)
        # il-58w was received INTO THE WAREHOUSE (a canonical ledger movement + its FIFO layer)
        await op.warehouse_transactions.insert_one({
            "id": "wt-58", "org_id": ORG_A, "action": "receive_from_supplier", "movement_id": "mv-58",
            "invoice_id": bill["id"], "invoice_line_id": "il-58w", "qty": 10, "unit_cost": 10.0,
            "destination": {"location_type": "central_warehouse", "location_id": "wh-1"}})
        await op.warehouse_transactions.insert_one({
            "id": "wt-58r", "org_id": ORG_A, "action": "receipt_reversal", "movement_id": "mv-58r",
            "invoice_id": bill["id"], "invoice_line_id": "il-58w", "qty": -3, "unit_cost": 10.0})
        fifo_before = await op.warehouse_transactions.find({}, {"_id": 0}).sort("id", 1).to_list(50)
        # the awaited credit 72.00 (3 × 10 + VAT on each line); the supplier credits 60.00
        await op.expected_credit_notes.insert_one({
            "id": "ecn_58", "org_id": ORG_A, "invoice_id": bill["id"], "invoice_line_id": "il-58w",
            "amount": 72.0, "status": "open", "created_at": "2026-10-05T08:00:00+00:00"})
        n = (await note(c, bill, number="CN-58", expected_credit_note_ids=["ecn_58"],
                        lines=[{"original_line_id": "il-58w", "amount": 25.0},
                               {"original_line_id": "il-58p", "amount": 25.0}])).json()
        assert (n["gross"], n["applied"]) == (60.0, False)
        before = await project_material_cost(tenant, ORG_A, "prj-1")
        r = await c.post("/api/finance/credit-notes/%s/accept-difference" % n["id"], headers=hdr("owner-a"),
                         json={"reason": "доставчикът не коригира"})
        assert r.status_code == 200, r.text
        acc = r.json()["difference_accepted"]
        period = acc["at"][:7]
        # 12.00 gross → 10.00 net, split by the note's lines: 5.00 warehouse + 5.00 project
        assert sorted((s["original_line_id"], s["net"], s["target"], s["basis"]) for s in acc["split"]) == [
            ("il-58p", 5.0, "project", "allocation"), ("il-58w", 5.0, "company", "warehouse_receipt")]
        assert acc["company_cost"] == 5.0
        # the warehouse part is a COMPANY cost (loss on the return) in the acceptance period
        r = await c.get("/api/finance/company-costs/accepted-differences?period=%s" % period,
                        headers=hdr("owner-a"))
        assert r.status_code == 200, r.text
        assert r.json()["total"] == 5.0
        assert [(l["invoice_line_id"], l["value"], l["period"]) for l in r.json()["lines"]] == [
            ("il-58w", 5.0, period)]
        r = await c.get("/api/finance/company-costs/accepted-differences?period=1999-01", headers=hdr("owner-a"))
        assert r.json()["total"] == 0.0
        # ...it is NOT a project cost; only the project line's part is (FG-251)
        after = await project_material_cost(tenant, ORG_A, "prj-1")
        assert round(after["total_cost"] - before["total_cost"], 2) == 5.0
        assert [ln["invoice_line_id"] for ln in after["lines"] if ln.get("kind") == "accepted_difference"] == [
            "il-58p"]
        # FIFO prices / ledger unchanged
        assert await op.warehouse_transactions.find({}, {"_id": 0}).sort("id", 1).to_list(50) == fifo_before
        # AuditEvent carries the split, the company cost and the period
        ev = await op.audit_events.find_one({"action": "finance.credit_note.difference_accepted"})
        diff = ev["structured_diff"]
        assert (diff["company_cost"], diff["cost_period"], diff["difference_gross"]) == (5.0, period, 12.0)
        # Q007 / FLOW-024: a separate line of the FINAL company result, with drill-down and a
        # label; never in project P&L, never in the overhead allocation base
        import importlib
        from tests.test_warehouse_canonical_c22_all_reports_cutover import _DB_MODULES
        for name in set(_DB_MODULES) | {"app.services.pnl_aggregator", "app.services.project_pnl",
                                        "app.permissions.money_write", "app.routes.project_pnl"}:
            module = importlib.import_module(name)
            if hasattr(module, "db"):
                monkeypatch.setattr(module, "db", op)
        r = await c.get("/api/org/pnl-attribution", headers=hdr("owner-a"))
        assert r.status_code == 200, r.text
        res = r.json()
        assert res["company_losses"]["label"] == "Фирмени загуби (не се разпределят)"
        assert "склада" in res["company_losses"]["includes"]
        assert res["company_losses"]["amount"] == res["totals"]["company_losses"] == 5.0
        assert res["totals"]["final_profit"] == round(res["totals"]["profit"] - 5.0, 2)
        assert [(l["ref"], l["invoice_line_id"], l["value"]) for l in res["company_losses"]["lines"]] == [
            (n["id"], "il-58w", 5.0)]
        # FG-271: the SAME line in every company-result reader
        r = await c.get("/api/org/pnl-overview", headers=hdr("owner-a"))
        assert r.status_code == 200, r.text
        ov = r.json()
        assert ov["company_losses"] == res["company_losses"]
        assert ov["totals"]["company_losses"] == 5.0
        assert ov["totals"]["final_profit"] == round(ov["totals"]["profit"] - 5.0, 2)
        assert all(p.get("company_losses") is None for p in ov["projects"])
        r = await c.get("/api/finance/stats", headers=hdr("owner-a"))
        assert r.status_code == 200, r.text
        assert r.json()["company_losses"] == res["company_losses"]
        assert await op.overhead_transactions.count_documents({}) == 0
        assert await op.overhead_snapshots.count_documents({}) == 0
        assert await op.overhead_costs.count_documents({}) == 0
        # tenant isolation: another org sees nothing
        r = await c.get("/api/finance/company-costs/accepted-differences", headers=hdr("admin-b"))
        assert r.status_code == 200 and r.json()["lines"] == [], r.text
        r = await c.get("/api/org/pnl-attribution", headers=hdr("admin-b"))
        assert r.status_code == 200 and r.json()["company_losses"]["amount"] == 0, r.text
    run(monkeypatch, mode, scenario)


def test_fg269_fg270_the_difference_follows_each_line_s_own_receipt_destination(monkeypatch, mode):
    async def scenario(c, op):
        from app.services.canonical_material_cost import project_material_cost
        from app.services import invoice_corrections as ic
        from app.tenancy.data_access import TenantData
        tenant = TenantData.for_resolved_org(op, ORG_A)

        async def accepted(bill, number, lines, expected):
            await op.expected_credit_notes.insert_one({
                "id": "ecn_" + number, "org_id": ORG_A, "invoice_id": bill["id"], "amount": expected,
                "status": "open", "created_at": "2026-10-05T08:00:00+00:00"})
            n = (await note(c, bill, number=number, expected_credit_note_ids=["ecn_" + number],
                            lines=lines)).json()
            r = await c.post("/api/finance/credit-notes/%s/accept-difference" % n["id"],
                             headers=hdr("owner-a"), json={"reason": "доставчикът не коригира"})
            assert r.status_code == 200, r.text
            return n, {s["original_line_id"]: s for s in r.json()["difference_accepted"]["split"]}

        # FG-269: a DIRECT delivery to a project (no allocation on the line) → the project's
        # cost (Р55(3)), never a company cost
        bill = await sent(c, direction="Received", project="prj-1")
        await op.invoice_lines.insert_one({
            "id": "il-269", "org_id": ORG_A, "invoice_id": bill["id"], "description": "Лепило",
            "qty": 10, "unit_price": 10, "line_total_ex_vat": 100.0, "vat_amount": 20.0,
            "created_at": "2026-10-02T08:00:00+00:00"})
        await op.warehouse_transactions.insert_one({
            "id": "wt-269", "org_id": ORG_A, "action": "receive_from_supplier_to_project",
            "movement_id": "mv-269", "invoice_id": bill["id"], "invoice_line_id": "il-269", "qty": 10,
            "project_id": "prj-1", "destination": {"location_type": "project", "location_id": "prj-1"}})
        before = await project_material_cost(tenant, ORG_A, "prj-1")
        n, split = await accepted(bill, "CN-269", [{"original_line_id": "il-269", "amount": 25.0}], 36.0)
        assert (split["il-269"]["target"], split["il-269"]["basis"], split["il-269"]["project_id"],
                split["il-269"]["net"]) == ("project", "direct_delivery", "prj-1", 5.0)
        after = await project_material_cost(tenant, ORG_A, "prj-1")
        assert [(ln["invoice_line_id"], ln["value"]) for ln in after["lines"]
                if ln.get("kind") == "accepted_difference"] == [("il-269", 5.0)]
        assert round(after["total_cost"] - before["total_cost"], 2) == 5.0
        assert (await ic.company_losses_block(tenant))["amount"] == 0.0

        # FG-270: a receipt linked ONLY by invoice_id reclassifies no line: the allocated line
        # stays the project's; the other line cannot be determined → DQ, no company cost
        bill2 = await sent(c, direction="Received", project="prj-1")
        for lid in ("il-270p", "il-270x"):
            row = {"id": lid, "org_id": ORG_A, "invoice_id": bill2["id"], "description": lid,
                   "qty": 10, "unit_price": 10, "line_total_ex_vat": 100.0, "vat_amount": 20.0,
                   "created_at": "2026-10-02T08:00:00+00:00"}
            if lid == "il-270p":
                row["allocations"] = [{"type": "project", "ref_id": "prj-1", "qty": 10}]
            await op.invoice_lines.insert_one(row)
        await op.warehouse_transactions.insert_one({
            "id": "wt-270", "org_id": ORG_A, "action": "receive_from_supplier", "movement_id": "mv-270",
            "invoice_id": bill2["id"], "qty": 10,
            "destination": {"location_type": "central_warehouse", "location_id": "wh-1"}})
        before = await project_material_cost(tenant, ORG_A, "prj-1")
        n2, split = await accepted(bill2, "CN-270", [{"original_line_id": "il-270p", "amount": 25.0},
                                                     {"original_line_id": "il-270x", "amount": 25.0}], 72.0)
        assert (split["il-270p"]["target"], split["il-270p"]["basis"]) == ("project", "allocation")
        assert (split["il-270x"]["target"], split["il-270x"]["basis"]) == ("undetermined", "invoice_level_receipt")
        assert (await ic.company_losses_block(tenant))["amount"] == 0.0          # no automatic company cost
        after = await project_material_cost(tenant, ORG_A, "prj-1")
        assert round(after["total_cost"] - before["total_cost"], 2) == 5.0       # only the allocated line
        dq = await op.dq_issues.find_one({"type": "ACCEPTED_DIFFERENCE_LINE_UNDETERMINED"}, {"_id": 0})
        assert dq and (dq["entity_id"], dq["owner_role"], dq["status"]) == (
            "%s:il-270x" % n2["id"], "accountant", "open")
    run(monkeypatch, mode, scenario)


def test_fg277_fg276_fg278_resolve_reverse_and_scope_of_an_accepted_difference(monkeypatch, mode):
    async def scenario(c, op):
        from app.services.canonical_material_cost import project_material_cost
        from app.services import invoice_corrections as ic
        from app.tenancy.data_access import TenantData
        tenant = TenantData.for_resolved_org(op, ORG_A)
        bill = await sent(c, direction="Received", project="prj-1")
        for lid in ("il-27p", "il-27x"):
            row = {"id": lid, "org_id": ORG_A, "invoice_id": bill["id"], "description": lid,
                   "qty": 10, "unit_price": 10, "line_total_ex_vat": 100.0, "vat_amount": 20.0,
                   "created_at": "2026-10-02T08:00:00+00:00"}
            if lid == "il-27p":
                row["allocations"] = [{"type": "project", "ref_id": "prj-1", "qty": 10}]
            await op.invoice_lines.insert_one(row)
        await op.warehouse_transactions.insert_one({        # invoice-level only → il-27x undetermined
            "id": "wt-27", "org_id": ORG_A, "action": "receive_from_supplier", "movement_id": "mv-27",
            "invoice_id": bill["id"], "qty": 10, "destination": {"location_type": "central_warehouse"}})
        await op.expected_credit_notes.insert_one({
            "id": "ecn_27", "org_id": ORG_A, "invoice_id": bill["id"], "amount": 72.0, "status": "open",
            "created_at": "2026-10-05T08:00:00+00:00"})
        n = (await note(c, bill, number="CN-27", expected_credit_note_ids=["ecn_27"],
                        lines=[{"original_line_id": "il-27p", "amount": 25.0},
                               {"original_line_id": "il-27x", "amount": 25.0}])).json()
        r = await c.post("/api/finance/credit-notes/%s/accept-difference" % n["id"], headers=hdr("owner-a"),
                         json={"reason": "доставчикът не коригира"})
        assert r.status_code == 200, r.text
        accepted_at = r.json()["difference_accepted"]["at"]
        base = await project_material_cost(tenant, ORG_A, "prj-1")
        url = "/api/finance/credit-notes/%s/difference-lines/il-27x/resolve" % n["id"]
        body = {"target": "project", "project_id": "prj-1", "reason": "стоката е за обекта"}

        # FG-277: rights (Р14), Idempotency-Key, validation
        r = await c.post(url, headers={k: v for k, v in hdr("acct-a").items() if k != "Idempotency-Key"}, json=body)
        assert r.status_code == 428, r.text
        assert (await c.post(url, headers=hdr("viewer-a"), json=body)).status_code == 403
        assert (await c.post(url, headers=hdr("site-a"), json=body)).status_code == 403
        assert (await c.post(url, headers=hdr("admin-b"), json=body)).status_code == 404     # other tenant
        r = await c.post(url, headers=hdr("acct-a"), json={**body, "project_id": "nope"})
        assert code(r) == "PROJECT_NOT_FOUND", r.text
        r = await c.post(url, headers=hdr("acct-a"), json={"target": "x", "reason": "r"})
        assert code(r) == "TARGET_REQUIRED", r.text
        # the Accountant books the open line on the project, in the ACCEPTANCE period
        key = hdr("acct-a")
        r = await c.post(url, headers=key, json=body)
        assert r.status_code == 200, r.text
        again = await c.post(url, headers=key, json=body)                        # replay: same result
        assert again.status_code == 200 and again.json()["difference_accepted"]["postings"] == \
            r.json()["difference_accepted"]["postings"]
        assert (await c.post(url, headers=hdr("acct-a"), json=body)).status_code == 409   # nothing open now
        after = await project_material_cost(tenant, ORG_A, "prj-1")
        res_lines = [ln for ln in after["lines"] if ln.get("posting") == "resolution"]
        assert [(ln["invoice_line_id"], ln["value"], ln["period"]) for ln in res_lines] == [
            ("il-27x", 5.0, accepted_at[:7])]
        assert round(after["total_cost"] - base["total_cost"], 2) == 5.0
        dq = await op.dq_issues.find_one({"type": "ACCEPTED_DIFFERENCE_LINE_UNDETERMINED"}, {"_id": 0})
        assert dq["status"] == "resolved" and dq["resolution"]["target"] == "project"
        ev = await op.audit_events.find_one({"action": "finance.credit_note.difference_line_resolved"})
        assert ev and ev["structured_diff"]["cost_period"] == accepted_at[:7]

        # FG-276: only the Owner reverses, with a reason; append-only reversal postings
        rev = "/api/finance/credit-notes/%s/reverse-difference" % n["id"]
        assert (await c.post(rev, headers=hdr("acct-a"), json={"reason": "грешка"})).status_code == 403
        assert (await c.post(rev, headers=hdr("owner-a"), json={})).status_code == 400
        before_rev = (await op.credit_debit_notes.find_one({"id": n["id"]}))["difference_accepted"]["postings"]
        r = await c.post(rev, headers=hdr("owner-a"), json={"reason": "грешно приета разлика"})
        assert r.status_code == 200, r.text
        postings = r.json()["difference_accepted"]["postings"]
        assert postings[:len(before_rev)] == [{k: v for k, v in p.items() if k != "_id"} for p in before_rev]
        reversals = [p for p in postings if p["kind"] == "reversal"]
        assert sorted((p["original_line_id"], p["net"]) for p in reversals) == [("il-27p", -5.0), ("il-27x", -5.0)]
        assert ic.booked_by_line(postings) == {"il-27p": 0, "il-27x": 0}
        reversed_cost = await project_material_cost(tenant, ORG_A, "prj-1")
        assert round(reversed_cost["total_cost"] - base["total_cost"], 2) == -5.0  # both lines out
        assert await op.dq_issues.count_documents({"type": "ACCEPTED_DIFFERENCE_LINE_REVERSED",
                                                   "status": "open"}) == 2
        assert await op.audit_events.find_one({"action": "finance.credit_note.difference_reversed"})
        assert (await c.post(rev, headers=hdr("owner-a"), json={"reason": "пак"})).status_code == 409
        # the correction: re-book il-27x as a company loss, in the CURRENT period — another
        # destination than the reversed booking, so the Owner approves it (Р63)
        r = await c.post(url, headers=hdr("acct-a"), json={"target": "company", "reason": "загуба от връщане"})
        assert r.status_code == 200, r.text
        prop = r.json()["difference_accepted"]["proposals"][-1]
        r = await c.post("/api/finance/credit-notes/%s/difference-proposals/%s/approve" % (n["id"], prop["id"]),
                         headers=hdr("owner-a"), json={})
        assert r.status_code == 200, r.text
        block = await ic.company_losses_block(tenant)
        assert block["amount"] == 5.0
        assert await op.dq_issues.count_documents({"type": "ACCEPTED_DIFFERENCE_LINE_REVERSED",
                                                   "entity_id": {"$regex": ":il-27x:"}, "status": "open"}) == 0

        # FG-278: every company-result reader uses the same (cumulative) scope as its
        # project sums; a period filter gives only that period's postings
        import importlib
        from tests.test_warehouse_canonical_c22_all_reports_cutover import _DB_MODULES
        for name in set(_DB_MODULES) | {"app.services.pnl_aggregator", "app.services.project_pnl",
                                        "app.permissions.money_write", "app.routes.project_pnl"}:
            module = importlib.import_module(name)
            if hasattr(module, "db"):
                monkeypatch.setattr(module, "db", op)
        for path in ("/api/org/pnl-attribution", "/api/org/pnl-overview", "/api/finance/stats"):
            r = await c.get(path, headers=hdr("owner-a"))
            assert r.status_code == 200, r.text
            assert r.json()["company_losses"]["scope"] == {"period": None, "basis": "cumulative"}, path
            assert r.json()["company_losses"]["amount"] == block["amount"], path
        await op.credit_debit_notes.update_one(                 # an older posting in another period
            {"id": n["id"]}, {"$push": {"difference_accepted.postings": {
                "id": "dp_old", "kind": "booking", "original_line_id": "il-27x", "net": 7.0,
                "target": "company", "at": "2025-01-10T00:00:00+00:00", "period": "2025-01"}}})
        assert (await ic.company_losses_block(tenant))["amount"] == 12.0          # cumulative: all
        assert (await ic.company_losses_block(tenant, "2025-01"))["amount"] == 7.0
        r = await c.get("/api/finance/company-costs/accepted-differences?period=2025-01", headers=hdr("owner-a"))
        assert r.json()["total"] == 7.0
        ov = (await c.get("/api/org/pnl-overview", headers=hdr("owner-a"))).json()
        assert ov["totals"]["final_profit"] == round(ov["totals"]["profit"] - 12.0, 2)
    run(monkeypatch, mode, scenario)


def test_r63_rebooking_after_a_reversal_same_place_at_once_else_another_owner(monkeypatch, mode):
    async def scenario(c, op):
        from app.services import invoice_corrections as ic
        from app.tenancy.data_access import TenantData
        tenant = TenantData.for_resolved_org(op, ORG_A)
        bill = await sent(c, direction="Received", project="prj-1")
        for lid in ("il-63p", "il-63d"):
            row = {"id": lid, "org_id": ORG_A, "invoice_id": bill["id"], "description": lid,
                   "qty": 10, "unit_price": 10, "line_total_ex_vat": 100.0, "vat_amount": 20.0,
                   "created_at": "2026-10-02T08:00:00+00:00"}
            if lid == "il-63p":
                row["allocations"] = [{"type": "project", "ref_id": "prj-1", "qty": 10}]
            await op.invoice_lines.insert_one(row)
        await op.warehouse_transactions.insert_one({                # il-63d: direct delivery to prj-2
            "id": "wt-63", "org_id": ORG_A, "action": "receive_from_supplier_to_project", "movement_id": "mv-63",
            "invoice_id": bill["id"], "invoice_line_id": "il-63d", "qty": 10, "project_id": "prj-2",
            "destination": {"location_type": "project", "location_id": "prj-2"}})
        await op.expected_credit_notes.insert_one({
            "id": "ecn_63", "org_id": ORG_A, "invoice_id": bill["id"], "amount": 72.0, "status": "open",
            "created_at": "2026-10-05T08:00:00+00:00"})
        n = (await note(c, bill, number="CN-63", expected_credit_note_ids=["ecn_63"],
                        lines=[{"original_line_id": "il-63p", "amount": 25.0},
                               {"original_line_id": "il-63d", "amount": 25.0}])).json()
        base = "/api/finance/credit-notes/%s" % n["id"]
        assert (await c.post(base + "/accept-difference", headers=hdr("owner-a"),
                             json={"reason": "доставчикът не коригира"})).status_code == 200
        assert (await c.post(base + "/reverse-difference", headers=hdr("owner-a"),
                             json={"reason": "грешно разнесено"})).status_code == 200

        async def postings():
            return (await op.credit_debit_notes.find_one({"id": n["id"]}))["difference_accepted"]["postings"]

        # SAME destination as the reversed booking → applied at once (allocation line: back to
        # its own allocation; direct delivery: the same project)
        r = await c.post(base + "/difference-lines/il-63p/resolve", headers=hdr("acct-a"),
                         json={"target": "project", "reason": "обратно на обекта"})
        assert r.status_code == 200, r.text
        assert ic.booked_by_line(await postings())["il-63p"] == ic.cents(5)
        # ANOTHER destination (company) → a proposal only; nothing booked; the line is locked
        before = await postings()
        r = await c.post(base + "/difference-lines/il-63d/resolve", headers=hdr("acct-a"),
                         json={"target": "company", "reason": "загуба от връщане"})
        assert r.status_code == 200, r.text
        prop = r.json()["difference_accepted"]["proposals"][-1]
        assert (prop["target"], prop["by"], prop["why_approval"]) == ("company", "acct-a", "other_destination")
        assert await postings() == before
        assert (await c.post(base + "/difference-lines/il-63d/resolve", headers=hdr("acct-a"),
                             json={"target": "project", "project_id": "prj-2", "reason": "r"})).status_code == 409
        approve = base + "/difference-proposals/%s/approve" % prop["id"]
        nokey = {k: v for k, v in hdr("owner-a").items() if k != "Idempotency-Key"}
        assert (await c.post(approve, headers=nokey, json={})).status_code == 428
        assert (await c.post(approve, headers=hdr("acct-a"), json={})).status_code == 403     # not an Owner
        assert (await c.post(approve, headers=hdr("admin-a"), json={})).status_code == 403
        assert (await c.post(approve, headers=hdr("owner-b"), json={})).status_code == 404    # other tenant
        # the proposer withdraws; the OWNER proposes himself → he cannot approve (two people)
        r = await c.post(base + "/difference-proposals/%s/reject" % prop["id"], headers=hdr("acct-a"),
                         json={"reason": "оттеглям"})
        assert r.status_code == 200, r.text
        r = await c.post(base + "/difference-lines/il-63d/resolve", headers=hdr("owner-a"),
                         json={"target": "company", "reason": "загуба от връщане"})
        prop2 = r.json()["difference_accepted"]["proposals"][-1]
        approve2 = base + "/difference-proposals/%s/approve" % prop2["id"]
        r = await c.post(approve2, headers=hdr("owner-a"), json={})
        assert r.status_code == 403 and code(r) == "SAME_PERSON_APPROVAL", r.text
        r = await c.post(approve2, headers=hdr("owner2-a", key="k-416"), json={"reason": "одобрявам"})
        assert r.status_code == 200, r.text
        # FG-416: the same key with another body (another comment) → 409; the same body → replay
        r = await c.post(approve2, headers=hdr("owner2-a", key="k-416"), json={"reason": "друго"})
        assert r.status_code == 409 and code(r) == "IDEMPOTENCY_KEY_REUSED", r.text
        assert (await c.post(approve2, headers=hdr("owner2-a", key="k-416"),
                             json={"reason": "одобрявам"})).status_code == 200
        assert (await c.post(approve2, headers=hdr("owner2-a"), json={})).status_code == 409   # decided
        assert (await ic.company_losses_block(tenant))["amount"] == 5.0
        last = (await postings())[-1]
        assert (last["original_line_id"], last["target"], last["basis"]) == (
            "il-63d", "company", "rebooking_approved_by_owner")
        assert await op.dq_issues.count_documents({"type": "ACCEPTED_DIFFERENCE_LINE_REVERSED",
                                                   "status": "open"}) == 0
        for action in ("proposed", "approved", "rejected"):
            assert await op.audit_events.find_one(
                {"action": "finance.credit_note.difference_rebooking_" + action}), action
        # Р64 / FG-415: the SAME place, but the project is not Active / Paused (here Archived)
        # → a proposal, never booked at once; the status is re-read at the approval
        assert (await c.post(base + "/reverse-difference", headers=hdr("owner-a"),
                             json={"reason": "пак грешно"})).status_code == 200
        await op.projects.update_one({"id": "prj-1"}, {"$set": {"status": "Archived"}})
        before = await postings()
        r = await c.post(base + "/difference-lines/il-63p/resolve", headers=hdr("acct-a"),
                         json={"target": "project", "reason": "обратно на обекта"})
        assert r.status_code == 200, r.text
        prop3 = r.json()["difference_accepted"]["proposals"][-1]
        assert (prop3["why_approval"], prop3["project_statuses"]) == ("closed_project", {"prj-1": "Archived"})
        assert await postings() == before                                   # nothing booked
        # the same place, no project involved (company → company) → at once
        r = await c.post(base + "/difference-lines/il-63d/resolve", headers=hdr("acct-a"),
                         json={"target": "company", "reason": "пак загуба"})
        assert r.status_code == 200 and len(await postings()) == len(before) + 1, r.text
        # the proposer is never the approver; another Owner approves; status re-read (Completed now)
        await op.projects.update_one({"id": "prj-1"}, {"$set": {"status": "Completed"}})
        approve3 = base + "/difference-proposals/%s/approve" % prop3["id"]
        assert (await c.post(approve3, headers=hdr("acct-a"), json={})).status_code == 403
        r = await c.post(approve3, headers=hdr("owner-a"), json={})
        assert r.status_code == 200, r.text
        dec = r.json()["difference_accepted"]["decisions"][-1]
        assert (dec["decision"], dec["project_statuses"]) == ("approved", {"prj-1": "Completed"})
        # a Completed project, ANOTHER line re-booked to it explicitly → a proposal as well
        await op.projects.update_one({"id": "prj-2"}, {"$set": {"status": "Finished"}})
        assert (await c.post(base + "/reverse-difference", headers=hdr("owner-a"),
                             json={"reason": "трети път"})).status_code == 200
        r = await c.post(base + "/difference-lines/il-63d/resolve", headers=hdr("acct-a"),
                         json={"target": "project", "project_id": "prj-2", "reason": "към обекта"})
        assert r.json()["difference_accepted"]["proposals"][-1]["why_approval"] == "other_destination"
    run(monkeypatch, mode, scenario)


def test_fg278_every_company_result_reader_uses_one_project_status_scope(monkeypatch, mode):
    async def scenario(c, op):
        import importlib
        from tests.test_warehouse_canonical_c22_all_reports_cutover import _DB_MODULES
        for name in set(_DB_MODULES) | {"app.services.pnl_aggregator", "app.services.project_pnl",
                                        "app.permissions.money_write", "app.routes.project_pnl"}:
            module = importlib.import_module(name)
            if hasattr(module, "db"):
                monkeypatch.setattr(module, "db", op)
        # a Completed project with a cost of its own → a −100.00 result
        await op.projects.insert_one({"id": "prj-done", "org_id": ORG_A, "code": "DONE", "name": "Done",
                                      "status": "Completed"})
        bill = await sent(c, direction="Received", project="prj-done")
        await op.invoice_lines.insert_one({
            "id": "il-done", "org_id": ORG_A, "invoice_id": bill["id"], "description": "Лепило",
            "qty": 10, "unit_price": 10, "line_total_ex_vat": 100.0, "vat_amount": 20.0,
            "created_at": "2026-10-02T08:00:00+00:00",
            "allocations": [{"type": "project", "ref_id": "prj-done", "qty": 10}]})
        att = (await c.get("/api/org/pnl-attribution", headers=hdr("owner-a"))).json()
        ov = (await c.get("/api/org/pnl-overview", headers=hdr("owner-a"))).json()
        assert "prj-done" in [p["id"] for p in ov["projects"]]
        assert att["scope"] == ov["scope"] == {"projects": "all", "project_statuses": "all"}
        for k in ("revenue", "expense", "profit", "company_losses", "final_profit"):
            assert att["totals"][k] == ov["totals"][k], k
        assert att["company_losses"] == ov["company_losses"]
        # FG-282 (closed by #81 WH81-03, pinned here): a Received invoice with a project_id is
        # a cost, never revenue
        from app.services.project_pnl import compute_project_pnl
        assert (await compute_project_pnl(ORG_A, "prj-done"))["revenue"]["total_revenue"] == 0
        done = [p for p in ov["projects"] if p["id"] == "prj-done"][0]
        assert done["revenue"] == 0 and done["expense"] > 0
    run(monkeypatch, mode, scenario)


def test_wh_fix_01_merge_a_locked_supplier_invoice_changes_only_its_line_destination(monkeypatch, mode):
    async def scenario(c, op):
        bill = await sent(c, direction="Received")
        assert bill["status"] not in ("Draft",)
        url = "/api/finance/invoices/%s/lines" % bill["id"]
        cur = bill["lines"]
        same = [{k: l.get(k) for k in ("description", "unit", "qty", "unit_price", "cost_category")}
                for l in cur]
        # a money change on a locked invoice → 409 INVOICE_LOCKED, nothing written
        more = [dict(same[0], qty=same[0]["qty"] + 1)] + same[1:]
        r = await c.put(url, headers=hdr("acct-a"), json={"lines": more})
        assert r.status_code == 409 and code(r) == "INVOICE_LOCKED", r.text
        # the destination only (Р45) → allowed; the line ids and every amount are kept
        moved = [dict(same[0], project_id="prj-2")] + same[1:]
        r = await c.put(url, headers=hdr("acct-a"), json={"lines": moved})
        assert r.status_code == 200, r.text
        after = r.json()
        assert [l["id"] for l in after["lines"]] == [l["id"] for l in cur]
        assert after["lines"][0]["project_id"] == "prj-2"
        assert (after["total"], after["subtotal"]) == (bill["total"], bill["subtotal"])
        # our own (outgoing) issued invoice stays fully locked, even for a destination
        ours = await sent(c)
        r = await c.put("/api/finance/invoices/%s/lines" % ours["id"], headers=hdr("acct-a"), json={
            "lines": [dict({k: l.get(k) for k in ("description", "unit", "qty", "unit_price")},
                           project_id="prj-2") for l in ours["lines"]]})
        assert r.status_code == 409 and code(r) == "INVOICE_LOCKED", r.text
    run(monkeypatch, mode, scenario)


R64_SHAPES = {   # INV84-R64-1 (AUDIT-2 probe): every shape of the SAME line allocation to prj-1
    "new": {"allocations": [{"type": "project", "ref_id": "prj-1", "qty": 10}]},
    "legacy": {"allocation_type": "project", "allocation_ref_id": "prj-1"},
    "camel": {"allocations": [{"type": "project", "refId": "prj-1", "qty": 10}]},
    "none": {},          # no readable allocation → fail closed
}


@pytest.mark.parametrize("shape", sorted(R64_SHAPES))
def test_inv84_r64_1_back_to_own_allocation_on_a_closed_project_is_a_proposal(monkeypatch, mode, shape):
    async def scenario(c, op):
        bill = await sent(c, direction="Received", project="prj-1")
        await op.invoice_lines.insert_one({
            "id": "il-p", "org_id": ORG_A, "invoice_id": bill["id"], "description": "il-p",
            "qty": 10, "unit_price": 10, "line_total_ex_vat": 100.0, "vat_amount": 20.0,
            "created_at": "2026-10-02T08:00:00+00:00", **R64_SHAPES[shape]})
        await op.expected_credit_notes.insert_one({
            "id": "ecn_p", "org_id": ORG_A, "invoice_id": bill["id"], "amount": 36.0, "status": "open",
            "created_at": "2026-10-05T08:00:00+00:00"})
        n = (await note(c, bill, number="CN-P", expected_credit_note_ids=["ecn_p"],
                        lines=[{"original_line_id": "il-p", "amount": 25.0}])).json()
        base = "/api/finance/credit-notes/%s" % n["id"]
        r = await c.post(base + "/accept-difference", headers=hdr("owner-a"), json={"reason": "не коригира"})
        assert r.status_code == 200, r.text
        split = r.json()["difference_accepted"]["split"][0]
        assert (split["target"], split["basis"]) == (
            "project", "no_receipt" if shape == "none" else "allocation")
        assert (await c.post(base + "/reverse-difference", headers=hdr("owner-a"),
                             json={"reason": "грешно"})).status_code == 200
        await op.projects.update_one({"id": "prj-1"}, {"$set": {"status": "Archived"}})
        before = (await op.credit_debit_notes.find_one({"id": n["id"]}))["difference_accepted"]["postings"]
        r = await c.post(base + "/difference-lines/il-p/resolve", headers=hdr("acct-a"),
                         json={"target": "project", "reason": "обратно на обекта"})
        assert r.status_code == 200, r.text
        acc = (await op.credit_debit_notes.find_one({"id": n["id"]}))["difference_accepted"]
        assert acc["postings"] == before                                     # nothing booked at once
        prop = acc["proposals"][-1]
        assert prop["why_approval"] == "closed_project"
        assert prop["project_statuses"] == ({} if shape == "none" else {"prj-1": "Archived"})
    run(monkeypatch, mode, scenario)


def test_inv84_n2_every_invariant_holds_without_its_unique_index_and_a_missing_index_is_a_dq_issue(
        monkeypatch, mode):
    async def scenario(c, op):
        from app.services import invoice_corrections as ic
        # no unique index can be relied on here: drop every planned unique one (a legacy
        # database whose data refused the build) and forget the per-process cache
        for coll in ("invoices", "credit_debit_notes", "org_counters"):
            for name in list(await op[coll].index_information()):
                if name.startswith("inv_cn_0"):
                    await op[coll].drop_index(name)
        ic._ensured.clear(); ic._retry_at.clear(); ic._index_failures.clear(); ic._recorded.clear()
        # a legacy collision that makes the incoming-number index unbuildable
        for i in (1, 2):
            await op.credit_debit_notes.insert_one({"id": "legacy-n%d" % i, "org_id": ORG_A,
                                                    "direction": "incoming", "supplier_key": "x",
                                                    "number": "OLD-1"})
        # (1) the shared counter: 6 parallel FIRST issues → ONE counter document, 6 numbers
        drafts = [await draft(c) for _ in range(6)]
        results = await asyncio.gather(*(
            c.post("/api/finance/invoices/%s/issue" % d["id"], headers=hdr("acct-a")) for d in drafts))
        assert all(r.status_code == 200 for r in results), [r.text for r in results]
        assert sorted(r.json()["invoice_no"] for r in results) == ["INV-%04d" % i for i in range(1, 7)]
        assert await op.org_counters.count_documents({"counter_type": ic.NUMBER_COUNTER}) == 1
        # (2) the missing index is a canonical DQ issue + alarm naming its invariant + other guard
        dq = await op.dq_issues.find_one({"id": "dq-index-not-built-inv_cn_01_incoming_number_unique"})
        assert dq and (dq["type"], dq["status"], dq["owner_role"]) == ("INDEX_NOT_BUILT", "open", "accountant")
        assert dq["details"]["invariant"] == "one supplier note per (supplier, number)"
        assert "lock" in dq["details"]["other_guard"]
        assert (await op.alarm_events.find_one(
            {"id": "alarm-index-not-built-inv_cn_01_incoming_number_unique"}))["status"] == "active"
        # (3) one supplier note per (supplier, number) ACROSS two invoices of the supplier,
        # 6 in parallel, with no index → 1 × 201 + 5 × 409
        b1 = await sent(c, direction="Received")
        b2 = await sent(c, direction="Received")
        rs = await asyncio.gather(*(
            note(c, b, number="CN-SAME", lines=[{"original_line_id": b["lines"][0]["id"], "qty": 1}])
            for b in (b1, b2, b1, b2, b1, b2)))
        assert sorted(r.status_code for r in rs) == [201, 409, 409, 409, 409, 409], [r.text for r in rs]
        assert {code(r) for r in rs if r.status_code == 409} == {"DUPLICATE_CREDIT_NOTE"}
        # (4) two manual numbers decided concurrently, no index → one issued, the other 409
        settings = "/api/finance/invoice-settings"
        assert (await c.put(settings, headers=hdr("owner-a"), json={"issued_auto_numbering": False})).status_code == 200
        m = [await draft(c) for _ in range(2)]
        for d in m:
            await op.invoices.update_one({"id": d["id"]}, {"$set": {"manual_number": "MAN-1"}})
        rs = await asyncio.gather(*(c.post("/api/finance/invoices/%s/issue" % d["id"], headers=hdr("acct-a"))
                                    for d in m))
        assert sorted(r.status_code for r in rs) == [200, 409], [r.text for r in rs]
        assert await op.invoices.count_documents({"direction": "Issued", "invoice_no": "MAN-1"}) == 1
        # (5) the legacy collision cleaned + the index built → the DQ issue resolves
        await op.credit_debit_notes.delete_one({"id": "legacy-n2"})
        ic._retry_at.clear()
        await note(c, b1, number="CN-NEXT", lines=[{"original_line_id": b1["lines"][0]["id"], "qty": 1}])
        assert (await op.dq_issues.find_one(
            {"id": "dq-index-not-built-inv_cn_01_incoming_number_unique"}))["status"] == "resolved"
    run(monkeypatch, mode, scenario)


F8401_WRITES = [
    "/api/finance/credit-notes", "/api/finance/credit-notes/{n}/approve",
    "/api/finance/credit-notes/{n}/reject", "/api/finance/credit-notes/{n}/accept-difference",
    "/api/finance/credit-notes/{n}/difference-lines/x/resolve",
    "/api/finance/credit-notes/{n}/difference-proposals/x/approve",
    "/api/finance/credit-notes/{n}/difference-proposals/x/reject",
    "/api/finance/credit-notes/{n}/reverse-difference", "/api/finance/invoices/{i}/refund",
    "/api/finance/offsets", "/api/finance/offsets/{o}/approve", "/api/finance/offsets/{o}/reject"]
F8401_READS = ["/api/finance/credit-notes", "/api/finance/credit-notes/{n}",
               "/api/finance/invoices/{i}/corrections", "/api/finance/company-costs/accepted-differences",
               "/api/finance/offsets"]
F8401_BUSINESS = ("invoices", "credit_debit_notes", "invoice_offsets", "finance_payments",
                  "payment_allocations", "expected_credit_notes", "dq_issues", "alarm_events",
                  "org_counters", "idempotency_keys")


@pytest.mark.parametrize("assignment", ["revoked", "expired", "missing"])
def test_f84_01_every_correction_route_goes_through_the_permission_service(monkeypatch, mode, assignment):
    """Codex F-84-01: a tenant Admin whose RoleAssignment is revoked / expired / missing
    (login valid, legacy users.role still Admin). enforce: EVERY read and write of the
    corrections router answers 403 with the Permission Service reason and writes NO business
    row (only the denial AuditEvent). off / shadow keep the legacy role rule (as every money
    write of SEC-01): the same Admin is still served."""
    async def scenario(c, op):
        sysdb = op.client["invcn_sys_" + op.name.split("invcn_op_", 1)[1]]
        inv = await sent(c)
        assert (await quick_pay(c, inv["id"], 240.0)).status_code == 201
        n = (await note(c, inv)).json()
        assert (await approve(c, n["id"])).status_code == 200
        b = await sent(c)
        off = (await offset(c, inv, b, 10, n["id"])).json()
        ids = {"n": n["id"], "i": inv["id"], "o": off["id"]}
        flt = {"user_id": "admin-a", "tenant_id": ORG_A}
        if assignment == "revoked":
            await sysdb.tenant_role_assignments.update_one(flt, {"$set": {"status": "revoked"}})
        elif assignment == "expired":
            await sysdb.tenant_role_assignments.update_one(
                flt, {"$set": {"valid_to": "2020-01-01T00:00:00+00:00"}})
        else:
            await sysdb.tenant_role_assignments.delete_one(flt)

        async def business():
            out = {}
            for coll in F8401_BUSINESS:
                out[coll] = sorted((await op[coll].find({}, {"_id": 0}).to_list(None)), key=repr)
            return out

        reason = {"revoked": "ASSIGNMENT_REVOKED", "expired": "ASSIGNMENT_EXPIRED",
                  "missing": "NO_ASSIGNMENT"}[assignment]
        if mode == "enforce":
            before = await business()
            for path in F8401_WRITES:
                r = await c.post(path.format(**ids), headers=hdr("admin-a"),
                                 json={"reason": "r", "version": 1, "kind": "credit"})
                assert r.status_code == 403, (path, r.text)
                assert reason in r.text, (path, r.text)
            for path in F8401_READS:
                r = await c.get(path.format(**ids), headers=hdr("admin-a"))
                assert r.status_code == 403, (path, r.text)
            assert await business() == before                    # no business write at all
            # the control: the same routes still serve an Admin WITH an active assignment
            assert (await c.get("/api/finance/credit-notes/%s" % n["id"], headers=hdr("owner-a"))).status_code == 200
        else:
            # off / shadow: the legacy users.role rule (SEC-01) — the Admin is still served
            assert (await c.get("/api/finance/credit-notes/%s" % n["id"], headers=hdr("admin-a"))).status_code == 200
            # … through the Permission Service up to the route's own Р49(4) rule (FG-599):
            # an Admin never issues an outgoing note
            r = await note(c, inv, who="admin-a", lines=[{"original_line_id": inv["lines"][0]["id"], "qty": 1}])
            assert r.status_code == 403 and code(r) == "ISSUER_ROLE_REQUIRED", r.text
        # a Viewer is refused in every mode, nothing written
        before = await business()
        r = await c.post("/api/finance/credit-notes", headers=hdr("viewer-a"),
                         json={"kind": "credit", "original_invoice_id": inv["id"], "reason": "r",
                               "lines": [{"original_line_id": inv["lines"][0]["id"], "qty": 1}]})
        assert r.status_code == 403, r.text
        assert (await c.get("/api/finance/offsets", headers=hdr("viewer-a"))).status_code == 403
        assert await business() == before
    run(monkeypatch, mode, scenario)


@pytest.mark.parametrize("assignment", ["revoked", "expired", "missing"])
def test_fg572_cancellation_and_due_date_go_through_the_permission_service(monkeypatch, mode, assignment):
    """FG-572 (CLAUDE.md §14): the cancellation proposal / approval / rejection and the
    invoice edit (the due date after issue) take the Permission Service first. enforce:
    Admin / Accountant / Owner whose assignment is revoked / expired / missing → 403 with
    the reason, nothing written; off / shadow keep the legacy role rule."""
    async def scenario(c, op):
        sysdb = op.client["invcn_sys_" + op.name.split("invcn_op_", 1)[1]]
        inv = await issued(c)                                    # issued, not sent
        inv2 = await issued(c)
        r = await c.post("/api/finance/invoices/%s/cancel" % inv2["id"], headers=hdr("acct-a"),
                         json={"reason": "грешка"})              # a pending proposal to decide
        assert r.status_code == 200, r.text
        for uid in ("admin-a", "acct-a", "owner-a"):
            flt = {"user_id": uid, "tenant_id": ORG_A}
            if assignment == "revoked":
                await sysdb.tenant_role_assignments.update_one(flt, {"$set": {"status": "revoked"}})
            elif assignment == "expired":
                await sysdb.tenant_role_assignments.update_one(
                    flt, {"$set": {"valid_to": "2020-01-01T00:00:00+00:00"}})
            else:
                await sysdb.tenant_role_assignments.delete_one(flt)

        async def business():
            return {coll: sorted((await op[coll].find({}, {"_id": 0}).to_list(None)), key=repr)
                    for coll in F8401_BUSINESS}

        reason = {"revoked": "ASSIGNMENT_REVOKED", "expired": "ASSIGNMENT_EXPIRED",
                  "missing": "NO_ASSIGNMENT"}[assignment]
        calls = [
            ("admin-a", "post", "/api/finance/invoices/%s/cancel" % inv["id"], {"reason": "грешка"}),
            ("acct-a", "put", "/api/finance/invoices/%s" % inv["id"],
             {"due_date": "2099-06-30", "reason": "разсрочване"}),
            ("owner-a", "post", "/api/finance/invoices/%s/cancel/approve" % inv2["id"], {"version": 1}),
            ("owner-a", "post", "/api/finance/invoices/%s/cancel/reject" % inv2["id"], {"reason": "не"}),
        ]
        if mode == "enforce":
            before = await business()
            for who, method, url, body in calls:
                r = await getattr(c, method)(url, headers=hdr(who), json=body)
                assert r.status_code == 403 and reason in r.text, (who, url, r.text)
            assert await business() == before                     # nothing written
        else:
            # off / shadow: the legacy role rule — the same callers are served
            r = await c.put("/api/finance/invoices/%s" % inv["id"], headers=hdr("acct-a"),
                            json={"due_date": "2099-06-30", "reason": "разсрочване"})
            assert r.status_code == 200, r.text
            r = await c.post("/api/finance/invoices/%s/cancel" % inv["id"], headers=hdr("admin-a"),
                             json={"reason": "грешка"})
            assert r.status_code == 200, r.text
        # a Viewer is refused in every mode
        r = await c.put("/api/finance/invoices/%s" % inv["id"], headers=hdr("viewer-a"),
                        json={"due_date": "2099-01-01", "reason": "x"})
        assert r.status_code == 403
    run(monkeypatch, mode, scenario)


def test_fg571_one_payable_net_after_credit_and_debit_notes(monkeypatch, mode):
    """FG-571 (#82 × #84): ONE function for what is owed on an invoice — the payable net
    after the approved credit / debit notes (``payable_net``) and, for Р47, what may still
    be paid while a credit is awaited (``payable_until_credit_note``). The raw invoice.total
    would let a second reversal through (120 − 72 = 48 ≥ 48) and refuse a payment an
    approved debit note made due."""
    async def scenario(c, op):
        from app.services import invoice_corrections as ic
        from app.tenancy.data_access import TenantData
        tenant = TenantData.for_resolved_org(op, ORG_A)
        one = [{"description": "Плочки", "unit": "бр", "qty": 1, "unit_price": 100}]
        # total 120, paid 72, credited 48 → payable net 72, open 0; a second reversal awaits 48
        a = await sent(c, direction="Received", lines=one)
        assert a["total"] == 120.0
        assert (await quick_pay(c, a["id"], 72.0)).status_code == 201
        r = await note(c, a, number="CN-571", lines=[{"original_line_id": a["lines"][0]["id"], "amount": 40.0}])
        assert r.status_code == 201 and r.json()["gross"] == 48.0 and r.json()["applied"], r.text
        await op.expected_credit_notes.insert_one({
            "id": "ecn_571", "org_id": ORG_A, "invoice_id": a["id"], "amount": 48.0, "status": "open",
            "created_at": datetime.now(timezone.utc).isoformat()})
        doc = await op.invoices.find_one({"id": a["id"]}, {"_id": 0})
        assert ic.cents(doc["total"]) - ic.cents(doc["paid_amount"]) == ic.cents(48)   # the raw view: "48 left"
        assert await ic.payable_net(tenant, doc) == ic.cents(72)
        assert await ic.current_open(tenant, doc) == ic.cents(0)
        assert await ic.payable_until_credit_note(tenant, doc) == ic.cents(-48)        # nothing payable
        # an approved supplier debit note: total 120 + 24 → payable net 144; paid 72, awaiting 48
        b = await sent(c, direction="Received", lines=one)
        dn = (await note(c, b, kind="debit", number="DN-571",
                         lines=[{"original_line_id": b["lines"][0]["id"], "amount": 20.0}],
                         basis={"type": "additional_delivery", "ref": "доставка"}, file_id="file-571")).json()
        assert (await approve(c, dn["id"])).status_code == 200
        assert (await quick_pay(c, b["id"], 72.0)).status_code == 201
        await op.expected_credit_notes.insert_one({
            "id": "ecn_571b", "org_id": ORG_A, "invoice_id": b["id"], "amount": 48.0, "status": "open",
            "created_at": datetime.now(timezone.utc).isoformat()})
        docb = await op.invoices.find_one({"id": b["id"]}, {"_id": 0})
        assert ic.cents(docb["total"]) - ic.cents(docb["paid_amount"]) - ic.cents(48) == ic.cents(0)  # raw: refuse
        assert await ic.payable_net(tenant, docb) == ic.cents(144)
        assert await ic.payable_until_credit_note(tenant, docb) == ic.cents(24)      # 24 still payable
    run(monkeypatch, mode, scenario)


def test_fg264_parallel_creates_of_one_supplier_number_one_wins_with_or_without_the_index(monkeypatch, mode):
    async def scenario(c, op):
        body = {"direction": "Received", "issue_date": "2026-11-08", "due_date": "2099-12-31",
                "counterparty_eik": EIK, "counterparty_name": "Доставчик", "lines": LINES}

        async def burst(number):
            results = await asyncio.gather(*(
                c.post("/api/finance/invoices", headers=hdr("acct-a"), json={**body, "invoice_no": number})
                for _ in range(6)))
            return sorted(r.status_code for r in results), results

        # (a) a fresh tenant, no migration run: the index is built on first use + the lock
        codes, results = await burst("P-1")
        assert codes == [201, 409, 409, 409, 409, 409], [r.text for r in results]
        assert {code(r) for r in results if r.status_code == 409} == {"DUPLICATE_SUPPLIER_INVOICE"}
        assert await op.invoices.count_documents({"invoice_no": "P-1"}) == 1
        # (b) a legacy database whose rows collide: the unique index CANNOT be built, so the
        # (supplier, number) lock alone serialises the decision
        await op.invoices.drop_index("inv_cn_02_supplier_invoice_no")
        for i, eik in enumerate(("111111111", "222222222")):
            await op.invoices.insert_one({"id": "legacy-%d" % i, "org_id": ORG_A, "direction": "Received",
                                          "status": "Sent", "invoice_no": "L-1", "counterparty_eik": eik})
        from app.services import invoice_corrections as ic
        ic._ensured.clear()                                          # a fresh process on that database
        codes, results = await burst("P-2")
        assert codes == [201, 409, 409, 409, 409, 409], [r.text for r in results]
        assert "inv_cn_02_supplier_invoice_no" not in await op.invoices.index_information()
        assert await op.invoices.count_documents({"invoice_no": "P-2"}) == 1
    run(monkeypatch, mode, scenario)


# ═════════════════════════ R84 — a supplier refund received BEFORE the credit note
from decimal import Decimal                                             # noqa: E402
from app.services import invoice_corrections as ic                     # noqa: E402
from app.tenancy.data_access import TenantData                         # noqa: E402


async def r84_setup(c, op, *, pay=240.0, amount=36.0, row="ecn-r84"):
    bill = await sent(c, direction="Received")                         # 240 gross
    if pay:
        assert (await quick_pay(c, bill["id"], pay)).status_code == 201
    await op.invoices.update_one({"id": bill["id"]}, {"$set": {"awaiting_credit_note": True}})
    await op.expected_credit_notes.insert_one({                       # as #82 _expect_credit_note writes it
        "id": row, "org_id": ORG_A, "invoice_id": bill["id"], "invoice_line_id": bill["lines"][0]["id"],
        "reversal_movement_id": "mv-" + row, "receipt_movement_id": "mv-0", "quantity": "3", "unit": "m2",
        "amount": amount, "currency": "EUR", "status": "open", "reason": "връщане на стока",
        "created_at": datetime.now(timezone.utc).isoformat(), "created_by": "acct-a"})
    return bill


async def r84_refund(c, bill, rows, amount, who="acct-a", key=None):
    return await c.post("/api/finance/invoices/%s/refund" % bill["id"], headers=hdr(who, key), json={
        "amount": amount, "reason": "върнати пари от доставчика", "account_id": BANK_A,
        "method": "BankTransfer", "expected_credit_rows": rows})


async def r84_cov(c, bill, row="ecn-r84"):
    r = await c.get("/api/finance/invoices/%s/corrections" % bill["id"], headers=hdr("acct-a"))
    assert r.status_code == 200, r.text
    return r.json(), next(e for e in r.json()["expected_credit_notes"] if e["id"] == row)


def r84_line(bill, qty):
    return [{"original_line_id": bill["lines"][0]["id"], "qty": qty}]


def test_r84_refund_before_the_note_closes_the_expectation_and_the_note_makes_no_second_balance(monkeypatch, mode):
    """R84 / FLOW Guard: paid 240, a return awaits a credit of 36. The supplier refunds 36
    BEFORE its note: one FLOW-006 Inflow, the expectation drops to 0 (Р47 cap), NO credit
    balance, the document is still awaited. The note of 36 then closes the row and makes no
    second credit balance; an ordinary refund of a "balance" is refused."""
    async def scenario(c, op):
        bill = await r84_setup(c, op)
        tenant = TenantData.for_resolved_org(op, ORG_A)
        assert await ic.awaited_credit(tenant, bill["id"]) == Decimal("36.00")
        r = await r84_refund(c, bill, [{"id": "ecn-r84", "amount": 36.0}], 36.0)
        assert r.status_code == 201, r.text
        pay = await op.finance_payments.find_one({"id": r.json()["payment_id"]}, {"_id": 0})
        assert (pay["direction"], pay["amount"], pay["refund_invoice_id"]) == ("Inflow", 36.0, bill["id"])
        assert pay["expected_credit_rows"] == [{"id": "ecn-r84", "amount": 36.0}]
        view, row = await r84_cov(c, bill)
        assert row["status"] == "open"                                 # the document is still awaited
        assert row["coverage"] == {"refunded": 36.0, "noted": 0.0, "uncovered": 36.0, "open": 0.0}
        assert [s["type"] for s in row["settlements"]] == ["refund"]
        assert (view["remaining_amount"], view["credit_balance"]) == (0.0, 0.0)
        assert await ic.awaited_credit(tenant, bill["id"]) == Decimal("0.00")
        inv = await get_inv(c, bill["id"])
        assert (inv["refunded_amount"], inv["credit_balance"]) == (0.0, 0.0)
        ev = await op.audit_events.find_one({"action": "finance.invoice.expected_credit_refund_registered"})
        assert ev and ev["entity_id"] == pay["id"]
        r = await r84_refund(c, bill, [{"id": "ecn-r84", "amount": 0.01}], 0.01)
        assert r.status_code == 409 and code(r) == "REFUND_EXCEEDS_EXPECTED_CREDIT", r.text
        # the note of 36 (D22: = the refunded money) closes the row, no second balance
        r = await note(c, bill, number="CN-R84", expected_credit_note_ids=["ecn-r84"])
        assert r.status_code == 201 and r.json()["applied"] is True, r.text
        assert r.json()["expected_link"]["covered"] == [{"id": "ecn-r84", "amount": 36.0}]
        view, row = await r84_cov(c, bill)
        assert row["status"] == "fulfilled" and [s["type"] for s in row["settlements"]] == ["refund", "credit_note"]
        assert (view["remaining_amount"], view["credit_balance"]) == (0.0, 0.0)
        inv = await get_inv(c, bill["id"])
        assert (inv["credited_amount"], inv["refunded_amount"], inv["credit_balance"]) == (36.0, 36.0, 0.0)
        assert inv["awaiting_credit_note"] is False
        r = await c.post("/api/finance/invoices/%s/refund" % bill["id"], headers=hdr("acct-a"), json={
            "amount": 36.0, "reason": "втори път", "account_id": BANK_A, "method": "BankTransfer"})
        assert r.status_code == 409 and code(r) == "REFUND_EXCEEDS_BALANCE", r.text
        assert await op.finance_payments.count_documents({"refund_invoice_id": bill["id"]}) == 1
    run(monkeypatch, mode, scenario)


def test_r84_partial_refund_settles_40_and_leaves_8_open_d21_d22(monkeypatch, mode):
    """D21: a partial refund = settled part + open rest. D22: the note after it must equal
    the refunded money, else DQ (no tolerance); a corrected note resolves it (Р52(2a)); the
    rest closes with its own note (FG-219), and what the supplier still owes is a real
    credit balance, refunded the ordinary way."""
    async def scenario(c, op):
        bill = await r84_setup(c, op)                                  # awaits 36
        assert (await r84_refund(c, bill, [{"id": "ecn-r84", "amount": 24.0}], 24.0)).status_code == 201
        _, row = await r84_cov(c, bill)
        assert row["coverage"] == {"refunded": 24.0, "noted": 0.0, "uncovered": 24.0, "open": 12.0}
        r = await note(c, bill, number="CN-FULL", expected_credit_note_ids=["ecn-r84"])   # 36 ≠ 24
        assert r.status_code == 201 and r.json()["applied"] is False, r.text
        assert r.json()["expected_link"]["expected"] == 24.0
        mismatch = r.json()["id"]
        dq = await op.dq_issues.find_one({"type": "CREDIT_NOTE_DIFFERENCE", "entity_id": mismatch})
        assert dq["status"] == "open" and dq["details"]["refunded_before"] == 24.0
        assert dq["owner_role"] == "accountant"             # the Accountant asks for a corrected note
        r = await note(c, bill, number="CN-24", lines=r84_line(bill, 2), expected_credit_note_ids=["ecn-r84"])
        assert r.status_code == 201 and r.json()["applied"] is True, r.text            # 24 = refunded
        assert (await op.dq_issues.find_one({"id": dq["id"]}))["status"] == "resolved"
        assert (await op.credit_debit_notes.find_one({"id": mismatch}))["superseded_by"] == r.json()["id"]
        view, row = await r84_cov(c, bill)
        assert row["status"] == "open" and row["coverage"]["open"] == 12.0
        assert (view["remaining_amount"], view["credit_balance"]) == (0.0, 0.0)
        r = await note(c, bill, number="CN-12", lines=r84_line(bill, 1), expected_credit_note_ids=["ecn-r84"])
        assert r.status_code == 201 and r.json()["applied"] is True, r.text            # the rest, 12
        view, row = await r84_cov(c, bill)
        assert row["status"] == "fulfilled"
        inv = await get_inv(c, bill["id"])
        assert (inv["credited_amount"], inv["refunded_amount"], inv["credit_balance"]) == (36.0, 24.0, 12.0)
        r = await c.post("/api/finance/invoices/%s/refund" % bill["id"], headers=hdr("acct-a"), json={
            "amount": 12.0, "reason": "остатък", "account_id": BANK_A, "method": "BankTransfer"})
        assert r.status_code == 201, r.text
        assert (await get_inv(c, bill["id"]))["credit_balance"] == 0.0
    run(monkeypatch, mode, scenario)


def test_r84_forbidden_and_invalid_write_nothing(monkeypatch, mode):
    """D20: only the Accountant registers a received refund; a bad link, an outgoing
    invoice, an unpaid invoice, a missing key → refused, nothing written."""
    async def scenario(c, op):
        bill = await r84_setup(c, op)
        unpaid = await r84_setup(c, op, pay=0, row="ecn-unpaid")
        out = await sent(c)
        ok = [{"id": "ecn-r84", "amount": 10.0}]

        async def snapshot():
            return (await op.finance_payments.count_documents({}),
                    await op.expected_credit_notes.count_documents({"settlements": {"$exists": True}}))
        before = await snapshot()
        for who in ("owner-a", "admin-a"):
            r = await r84_refund(c, bill, ok, 10.0, who=who)
            assert r.status_code == 403 and code(r) == "REGISTRAR_ROLE_REQUIRED", (who, r.text)
        for who in ("viewer-a", "site-a"):
            assert (await r84_refund(c, bill, ok, 10.0, who=who)).status_code == 403, who
        assert (await r84_refund(c, bill, ok, 10.0, key=False)).status_code == 428
        assert (await r84_refund(c, bill, ok, 10.0, who="admin-b")).status_code == 403   # other tenant
        for rows, amount in (([{"id": "ecn-r84", "amount": 10.0}], 9.99),
                             ([{"id": "ecn-r84", "amount": 5.0}, {"id": "ecn-r84", "amount": 5.0}], 10.0),
                             ([], 10.0), ("ecn-r84", 10.0),
                             ([{"id": "no-such-row", "amount": 10.0}], 10.0),
                             ([{"id": "ecn-unpaid", "amount": 10.0}], 10.0)):     # another invoice's row
            r = await r84_refund(c, bill, rows, amount)
            assert r.status_code == 422 and code(r) == "EXPECTED_CREDIT_LINK_INVALID", (rows, r.text)
        r = await r84_refund(c, out, ok, 10.0)
        assert r.status_code == 422 and code(r) == "EXPECTED_CREDIT_LINK_INVALID", r.text
        r = await r84_refund(c, unpaid, [{"id": "ecn-unpaid", "amount": 10.0}], 10.0)
        assert r.status_code == 409 and code(r) == "REFUND_EXCEEDS_PAID", r.text
        assert await snapshot() == before
        assert (await r84_refund(c, bill, ok, 10.0)).status_code == 201
    run(monkeypatch, mode, scenario)


def test_r84_concurrent_refunds_never_exceed_the_expectation_and_replay_is_idempotent(monkeypatch, mode):
    async def scenario(c, op):
        bill = await r84_setup(c, op)                                  # awaits 36
        rs = await asyncio.gather(*(r84_refund(c, bill, [{"id": "ecn-r84", "amount": 10.0}], 10.0)
                                    for _ in range(6)))
        assert sorted(r.status_code for r in rs) == [201, 201, 201, 409, 409, 409], [r.text for r in rs]
        assert {code(r) for r in rs if r.status_code == 409} == {"REFUND_EXCEEDS_EXPECTED_CREDIT"}
        _, row = await r84_cov(c, bill)
        assert row["coverage"]["refunded"] == 30.0 and len(row["settlements"]) == 3
        a = await r84_refund(c, bill, [{"id": "ecn-r84", "amount": 6.0}], 6.0, key="r84-same")
        b = await r84_refund(c, bill, [{"id": "ecn-r84", "amount": 6.0}], 6.0, key="r84-same")
        assert a.status_code == 201 and b.json()["payment_id"] == a.json()["payment_id"], b.text
        _, row = await r84_cov(c, bill)
        assert row["coverage"] == {"refunded": 36.0, "noted": 0.0, "uncovered": 36.0, "open": 0.0}
        assert len(row["settlements"]) == 4
        r = await r84_refund(c, bill, [{"id": "ecn-r84", "amount": 7.0}], 7.0, key="r84-same")
        assert r.status_code == 409 and code(r) == "IDEMPOTENCY_KEY_REUSED", r.text
    run(monkeypatch, mode, scenario)


def test_r84_a_reversed_refund_reopens_the_expectation(monkeypatch, mode):
    """A refund reversed in the ONE ledger (FLOW-006) no longer settles the row: the
    expectation is back, and the note of the full amount then matches it (FG-219)."""
    async def scenario(c, op):
        bill = await r84_setup(c, op)
        r = await r84_refund(c, bill, [{"id": "ecn-r84", "amount": 36.0}], 36.0)
        assert r.status_code == 201, r.text
        r = await c.request("DELETE", "/api/finance/payments/" + r.json()["payment_id"], headers=hdr("acct-a"),
                            json={"reason": "грешно разнесено"})
        assert r.status_code == 200, r.text
        _, row = await r84_cov(c, bill)
        assert row["coverage"] == {"refunded": 0.0, "noted": 0.0, "uncovered": 0.0, "open": 36.0}
        r = await note(c, bill, number="CN-AFTER-REV", expected_credit_note_ids=["ecn-r84"])
        assert r.status_code == 201 and r.json()["applied"] is True, r.text
        inv = await get_inv(c, bill["id"])
        assert (inv["credited_amount"], inv["refunded_amount"], inv["credit_balance"]) == (36.0, 0.0, 36.0)
    run(monkeypatch, mode, scenario)


@pytest.mark.parametrize("note_qty, balance", [(3, 12.0), (1, 0.0)])
def test_r84_d22_owner_accepts_a_note_higher_or_lower_than_the_refund(monkeypatch, mode, note_qty, balance):
    """D22 + Р52(2) (FLOW Guard): refunded 24 of an awaited 36. A note of 36 (higher) or of
    12 (lower) ≠ 24 → DQ for the Accountant; the Owner (not the registrant) accepts the
    difference with a reason + AuditEvent. The row closes, the limit is recomputed with
    the note's REAL amount, the whole refund counts: higher → the supplier still owes the
    unrefunded 12 (a real balance, refunded the ordinary way); lower → we owe the supplier
    the 12 refunded beyond the note — never a second credit balance."""
    async def scenario(c, op):
        bill = await r84_setup(c, op)                                  # paid 240, awaits 36
        assert (await r84_refund(c, bill, [{"id": "ecn-r84", "amount": 24.0}], 24.0)).status_code == 201
        r = await note(c, bill, number="CN-D22", lines=r84_line(bill, note_qty), expected_credit_note_ids=["ecn-r84"])
        assert r.status_code == 201 and r.json()["applied"] is False, r.text
        nid = r.json()["id"]
        url = "/api/finance/credit-notes/%s/accept-difference" % nid
        assert (await c.post(url, headers=hdr("acct-a"), json={"reason": "приемам"})).status_code == 403
        assert (await c.post(url, headers=hdr("owner-a"), json={})).status_code == 400
        r = await c.post(url, headers=hdr("owner-a"), json={"reason": "доставчикът не коригира"})
        assert r.status_code == 200, r.text
        assert (await op.dq_issues.find_one({"type": "CREDIT_NOTE_DIFFERENCE", "entity_id": nid}))["status"] == "resolved"
        ev = await op.audit_events.find_one({"action": "finance.credit_note.difference_accepted", "entity_id": nid})
        assert ev and ev["reason"] == "доставчикът не коригира"
        view, row = await r84_cov(c, bill)
        assert row["status"] == "fulfilled_with_difference" and row["coverage"]["open"] == 0.0
        inv = await get_inv(c, bill["id"])
        gross = 12.0 * note_qty
        assert (inv["credited_amount"], inv["refunded_amount"]) == (gross, 24.0)
        assert (view["credit_balance"], view["remaining_amount"]) == (balance, 12.0 - balance)
        tenant = TenantData.for_resolved_org(op, ORG_A)
        assert await ic.awaited_credit(tenant, bill["id"]) == Decimal("0.00")
        if balance:
            r = await c.post("/api/finance/invoices/%s/refund" % bill["id"], headers=hdr("acct-a"), json={
                "amount": balance + 0.01, "reason": "повече", "account_id": BANK_A, "method": "BankTransfer"})
            assert r.status_code == 409 and code(r) == "REFUND_EXCEEDS_BALANCE", r.text
    run(monkeypatch, mode, scenario)


def test_r84_d20_the_refund_is_a_dated_bank_inflow_and_the_rest_stays_escalated(monkeypatch, mode):
    """D20 (a)-(d) + D21 (FLOW Guard): the refund is a real Inflow on a bank account with
    a date; the open rest stays visible and under the 14-day Р49(8) escalation."""
    async def scenario(c, op):
        bill = await r84_setup(c, op)
        await op.expected_credit_notes.update_one(
            {"id": "ecn-r84"}, {"$set": {"created_at": (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()}})
        r = await c.post("/api/finance/invoices/%s/refund" % bill["id"], headers=hdr("acct-a"), json={
            "amount": 20.0, "reason": "банка", "account_id": BANK_A, "method": "BankTransfer",
            "date": "2026-11-12", "expected_credit_rows": [{"id": "ecn-r84", "amount": 20.0}]})
        assert r.status_code == 201, r.text
        pay = await op.finance_payments.find_one({"id": r.json()["payment_id"]}, {"_id": 0})
        assert (pay["direction"], pay["account_id"], pay["date"], pay["method"]) == (
            "Inflow", BANK_A, "2026-11-12", "BankTransfer")
        _, row = await r84_cov(c, bill)
        assert row["coverage"]["open"] == 16.0 and row["status"] == "open" and row["escalate_to_owner"] is True
    run(monkeypatch, mode, scenario)


@pytest.mark.parametrize("path", ["expected", "balance"])
def test_fg708_refund_date_is_an_iso_date_not_in_the_future_not_before_the_invoice(monkeypatch, mode, path):
    """FG-708: on BOTH refund routes (against an expectation, R84; of a credit balance,
    Р49.6 а) the date is an ISO date, not after today in Europe/Sofia, not before the
    invoice's date → else 422 with a code and nothing written; absent → today (Sofia)."""
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("Europe/Sofia")).date()

    async def scenario(c, op):
        if path == "expected":
            bill = await r84_setup(c, op)
            extra = lambda amt: {"expected_credit_rows": [{"id": "ecn-r84", "amount": amt}]}   # noqa: E731
        else:
            bill = await sent(c)
            assert (await quick_pay(c, bill["id"], 240.0)).status_code == 201
            n = (await note(c, bill)).json()
            assert (await approve(c, n["id"])).status_code == 200                       # balance 36
            extra = lambda amt: {}                                                     # noqa: E731
        issued = (await op.invoices.find_one({"id": bill["id"]}))["issue_date"][:10]
        if path == "expected":            # the expectation arose on the invoice's day (F-84-02 apart)
            await op.expected_credit_notes.update_one({"id": "ecn-r84"},
                                                      {"$set": {"created_at": issued + "T09:00:00+00:00"}})

        async def refund(amount, **kw):
            return await c.post("/api/finance/invoices/%s/refund" % bill["id"], headers=hdr("acct-a"), json={
                "amount": amount, "reason": "връщане", "account_id": BANK_A, "method": "BankTransfer",
                **extra(amount), **kw})
        before = await op.finance_payments.count_documents({})
        day_before = (datetime.fromisoformat(issued) - timedelta(days=1)).date().isoformat()
        for value, err in (("14.11.2026", "REFUND_DATE_INVALID"), ("2026-13-01", "REFUND_DATE_INVALID"),
                           ("2026-11-14T10:00:00", "REFUND_DATE_INVALID"), (20261114, "REFUND_DATE_INVALID"),
                           ("", "REFUND_DATE_INVALID"),
                           ((today + timedelta(days=1)).isoformat(), "REFUND_DATE_IN_FUTURE"),
                           (day_before, "REFUND_DATE_BEFORE_INVOICE")):
            r = await refund(10.0, date=value)
            assert r.status_code == 422 and code(r) == err, (value, r.text)
        assert await op.finance_payments.count_documents({}) == before
        r = await refund(10.0, date=issued)                                            # the boundary
        assert r.status_code == 201, r.text
        r = await refund(10.0, date=today.isoformat())                                 # today, Sofia
        assert r.status_code == 201, r.text
        r = await refund(10.0)                                                         # absent → today
        assert r.status_code == 201, r.text
        pay = await op.finance_payments.find_one({"id": r.json()["payment_id"]})
        assert pay["date"] == today.isoformat()
    run(monkeypatch, mode, scenario)


def test_f84_02_a_refund_is_never_dated_before_its_expected_credit_row(monkeypatch, mode):
    """Codex F-84-02 / FG-708: a refund against an expectation is dated no earlier than
    max(invoice date, the day each NAMED row arose — Europe/Sofia). The day before → 422
    REFUND_DATE_BEFORE_EXPECTED_CREDIT with no payment, no settlement, no AuditEvent; the
    same day and a later day → 201. A row created 23:30 UTC belongs to the next Sofia day."""
    async def scenario(c, op):
        bill = await r84_setup(c, op)
        issued = datetime.fromisoformat((await op.invoices.find_one({"id": bill["id"]}))["issue_date"][:10])
        day = lambda n: (issued + timedelta(days=n)).date().isoformat()            # noqa: E731
        # the row arose on issued+2 in Sofia (23:30 UTC on issued+1)
        await op.expected_credit_notes.update_one({"id": "ecn-r84"},
                                                  {"$set": {"created_at": day(1) + "T23:30:00+00:00"}})

        async def snapshot():
            return (await op.finance_payments.count_documents({}),
                    (await op.expected_credit_notes.find_one({"id": "ecn-r84"})).get("settlements"),
                    await op.audit_events.count_documents(
                        {"action": "finance.invoice.expected_credit_refund_registered"}))
        before = await snapshot()
        for d in (day(0), day(1)):                                   # after the invoice, before the row
            r = await c.post("/api/finance/invoices/%s/refund" % bill["id"], headers=hdr("acct-a"), json={
                "amount": 10.0, "reason": "връщане", "account_id": BANK_A, "method": "BankTransfer",
                "date": d, "expected_credit_rows": [{"id": "ecn-r84", "amount": 10.0}]})
            assert r.status_code == 422 and code(r) == "REFUND_DATE_BEFORE_EXPECTED_CREDIT", (d, r.text)
            assert r.json()["detail"]["expected_since"] == day(2)
        assert await snapshot() == before
        for d in (day(2), day(3)):                                   # the same day, a later day
            r = await c.post("/api/finance/invoices/%s/refund" % bill["id"], headers=hdr("acct-a"), json={
                "amount": 10.0, "reason": "връщане", "account_id": BANK_A, "method": "BankTransfer",
                "date": d, "expected_credit_rows": [{"id": "ecn-r84", "amount": 10.0}]})
            assert r.status_code == 201, (d, r.text)
        # FG-708's other checks hold: the future and before-the-invoice still refused
        r = await c.post("/api/finance/invoices/%s/refund" % bill["id"], headers=hdr("acct-a"), json={
            "amount": 1.0, "reason": "в", "account_id": BANK_A, "method": "BankTransfer",
            "date": day(-1), "expected_credit_rows": [{"id": "ecn-r84", "amount": 1.0}]})
        assert r.status_code == 422 and code(r) == "REFUND_DATE_BEFORE_INVOICE", r.text
    run(monkeypatch, mode, scenario)


def test_f84_02_the_row_date_is_checked_again_inside_the_transaction(monkeypatch, mode):
    """F-84-02: the check runs again on the rows as the transaction reads them — a row
    whose date moves after the pre-check (simulated by failing the pre-check open) is
    still refused, and nothing is written."""
    from app.routes import invoice_corrections as routes
    real = routes._check_refund_after_expected
    calls = []

    async def first_open(tenant, invoice_id, links, refund_date, *, session=None):
        calls.append(session is not None)
        if session is None:
            return None                                                # the pre-check misses it
        return await real(tenant, invoice_id, links, refund_date, session=session)
    monkeypatch.setattr(routes, "_check_refund_after_expected", first_open)

    async def scenario(c, op):
        bill = await r84_setup(c, op)
        tomorrow_row = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        await op.expected_credit_notes.update_one({"id": "ecn-r84"}, {"$set": {"created_at": tomorrow_row}})
        before = await op.finance_payments.count_documents({})
        r = await r84_refund(c, bill, [{"id": "ecn-r84", "amount": 10.0}], 10.0)   # today < the row's day
        assert r.status_code == 422 and code(r) == "REFUND_DATE_BEFORE_EXPECTED_CREDIT", r.text
        assert await op.finance_payments.count_documents({}) == before
        assert (await op.expected_credit_notes.find_one({"id": "ecn-r84"})).get("settlements") is None
        assert calls[:1] == [False] and True in calls                    # pre-check, then in the transaction
    run(monkeypatch, mode, scenario)
