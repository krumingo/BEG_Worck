"""
W0-03E-A1 / C01 — A/B duplicate-ID collision matrix over the actual HTTP routes.

R1 was blocked by a leak its own audit had missed: ``GET /finance/invoices``
and ``GET /finance/invoices/{id}`` enriched A's invoice with
``db.projects.find_one({"id": ...})`` and returned tenant B's project code and
name. A1 replaced the pattern with one tenant-safe access layer
(``app.tenancy.data_access``) and a static guard. This module is the runtime
half of that proof.

The world is ONE shared legacy database holding tenants A and B (the hardest
case: database-per-tenant separates them physically). For every entity the A1
assignment names — project, client, company, user, warehouse, invoice,
counterparty, person, payment and allocation — B holds a record with the SAME
id as A's, inserted BEFORE A's, so any global lookup returns B's. B also holds
records that exist ONLY in B and that A's own documents reference (a foreign
relation; A must see "absent", never B's document). Every value that exists
only in B carries a ``B-SECRET-*`` marker or the amount 999999.

``_matrix`` drives the real FastAPI routes over HTTP (httpx ASGI transport, the
same event loop as the database client) for finance invoice list/detail,
invoice/payment/allocation projections, invoice PDF, subcontractor documents,
accounts, stats, aging, offers list/detail/XLSX/PDF/public review/events,
/prices, turnover and drill-downs, company-finance summary/compare/export,
finance-details reports, dashboard projections, advances and the client-invoice
import. For each it asserts: (1) zero B markers, B amounts or B canonical ids in
the body; (2) A's own same-tenant data IS present; (3) a B-only relation
resolves to empty/"Unknown". Then A performs writes on shared ids and the whole
B dataset must be byte-for-byte unchanged, and A's invoice status must be
computed from A's allocations only. ``off``, ``shadow`` and ``enforce``.

The same coroutine runs on a disposable real MongoDB in
``tests/test_w0_03e_a1_real_mongo.py``.

Run:  pytest tests/test_w0_03e_a1_collision_matrix.py -v --noconftest
"""
import io
import json

import pytest

from app.master_data import legacy_adapter as la
from app.master_data.deps import ENV_MODE

from tests.test_w0_03e_c03_isolation import MODES, b_canonical_ids_async
from tests.test_w0_03e_legacy_migration import ORG_A, ORG_B, run
from tests.test_w0_03e_legacy_routes import ADMIN, RouteCtx
from tests.test_w0_03e_r1_exports import R1_MARKERS, _r1_world, pdf_text, xlsx_text

#: Every B-only value this module adds on top of the C03/R1 worlds.
A1_MARKERS = R1_MARKERS + (
    "B-SECRET-PERSON", "B-SECRET-ACCOUNT", "B-SECRET-PAYREF", "B-SECRET-SUB", "B-SECRET-CLIENT2",
    "B-SECRET-ROSTER", "B-SECRET-CASH", "B-SECRET-ORG", "B-SECRET-ALLOC", "B-SECRET-PAYNOTE",
    "B-SECRET-INV3", "B-ONLY-EGN-555")
SITE = {"id": "site-1", "org_id": ORG_A, "role": "SiteManager", "email": "s@x", "name": "Site A"}
PERIOD = "date_from=2026-01-01&date_to=2026-12-31"

#: Entities of the A1 assignment → (collection, shared id) present in BOTH tenants.
SHARED_IDS = {
    "project": ("projects", "pr-x"), "client": ("clients", "cl-x"),
    "company": ("companies", "c1"), "user": ("users", "u1"),
    "warehouse": ("warehouses", "wh1"), "invoice": ("invoices", "inv-shared"),
    "counterparty": ("counterparties", "cp1"), "person": ("persons", "pe-x"),
    "payment": ("finance_payments", "pay-1"), "allocation": ("payment_allocations", "al-1"),
}
B_COLLECTIONS = sorted({c for c, _ in SHARED_IDS.values()} | {
    "offers", "offer_events", "financial_accounts", "subcontractors", "subcontractor_payments",
    "invoice_lines", "cash_transactions", "organizations", "project_team", "site_daily_rosters",
    "invoice_versions", "advances"})


async def _a1_world(db=None):
    """C03 + R1 world plus the remaining A1 entities, B inserted first everywhere."""
    db = await _r1_world(db)
    b_first = [
        ("persons", {"id": "pe-x", "org_id": ORG_B, "first_name": "B-SECRET-PERSON", "last_name": "X",
                     "egn": "B-ONLY-EGN-555"}),
        ("persons", {"id": "pe-only-b", "org_id": ORG_B, "first_name": "B-SECRET-PERSON"}),
        ("clients", {"id": "cl-x", "org_id": ORG_B, "companyName": "B-SECRET-CLIENT2",
                     "eik": "B-ONLY-EIK-777"}),
        ("financial_accounts", {"id": "acc-1", "org_id": ORG_B, "name": "B-SECRET-ACCOUNT",
                                "type": "Bank", "currency": "EUR", "opening_balance": 999999}),
        ("financial_accounts", {"id": "acc-only-b", "org_id": ORG_B, "name": "B-SECRET-ACCOUNT",
                                "type": "Cash", "currency": "EUR", "opening_balance": 999999}),
        ("finance_payments", {"id": "pay-1", "org_id": ORG_B, "direction": "Outflow", "amount": 999999,
                              "date": "2026-09-03", "method": "B-SECRET-PAYNOTE", "account_id": "acc-1",
                              "reference": "B-SECRET-PAYREF", "note": "B-SECRET-PAYNOTE",
                              "counterparty_name": "B-SECRET-SUPPLIER", "currency": "EUR"}),
        ("finance_payments", {"id": "pay-only-b", "org_id": ORG_B, "direction": "Outflow",
                              "amount": 999999, "date": "2026-09-03", "method": "B-SECRET-PAYNOTE",
                              "account_id": "acc-only-b", "reference": "B-SECRET-PAYREF",
                              "note": "B-SECRET-PAYNOTE", "currency": "EUR"}),
        # B allocations on the SHARED invoice and payment ids, and on B-only ones
        ("payment_allocations", {"id": "al-1", "org_id": ORG_B, "invoice_id": "inv-shared",
                                 "payment_id": "pay-1", "amount_allocated": 999999,
                                 "allocated_at": "2026-09-03", "note": "B-SECRET-ALLOC"}),
        ("payment_allocations", {"id": "al-b-only", "org_id": ORG_B, "invoice_id": "inv-shared",
                                 "payment_id": "pay-only-b", "amount_allocated": 999999,
                                 "allocated_at": "2026-09-03", "note": "B-SECRET-ALLOC"}),
        ("invoices", {"id": "inv-3", "org_id": ORG_B, "invoice_no": "B-SECRET-INV3", "status": "Sent",
                      "direction": "Issued", "total": 999999, "subtotal": 999999, "vat_amount": 0,
                      "paid_amount": 0, "remaining_amount": 999999, "issue_date": "2026-09-03",
                      "due_date": "2026-09-04", "counterparty_name": "B-SECRET-SUPPLIER",
                      "project_id": "pr-x", "created_at": "2026-09-03"}),
        ("invoice_versions", {"id": "iv-b", "org_id": ORG_B, "invoice_id": "inv-shared",
                              "version_no": 1, "snapshot": {"invoice_no": "B-SECRET-INVOICE"}}),
        ("subcontractors", {"id": "sub-1", "org_id": ORG_B, "name": "B-SECRET-SUB"}),
        ("subcontractors", {"id": "sub-only-b", "org_id": ORG_B, "name": "B-SECRET-SUB"}),
        ("subcontractor_payments", {"id": "sp-b", "org_id": ORG_B, "status": "completed",
                                    "subcontractor_id": "sub-1", "project_id": "pr-x",
                                    "amount": 999999, "payment_no": "B-SECRET-SUB",
                                    "payment_date": "2026-09-03", "created_at": "2026-09-03"}),
        ("cash_transactions", {"id": "cash-b", "org_id": ORG_B, "type": "income", "amount": 999999,
                               "date": "2026-09-03", "note": "B-SECRET-CASH",
                               "description": "B-SECRET-CASH"}),
        ("organizations", {"id": ORG_B, "name": "B-SECRET-ORG"}),
        # a team row that only B's data can explain: site-1 on B's B-only project
        ("project_team", {"id": "pt-b", "project_id": "pr-only-b", "user_id": "site-1",
                          "role_in_project": "SiteManager", "active": True}),
        ("site_daily_rosters", {"id": "ros-b", "org_id": ORG_B, "date": "2099-01-01",
                                "project_id": "pr-x", "workers": [{"worker_id": "u1"}],
                                "note": "B-SECRET-ROSTER"}),
        ("advances", {"id": "adv-b", "org_id": ORG_B, "user_id": "u1", "amount": 999999,
                      "issued_date": "2026-09-03", "recipient_name": "B-SECRET-USER"}),
    ]
    for name, doc in b_first:
        await db[name].insert_one(doc)
    a_after = [
        ("persons", {"id": "pe-x", "org_id": ORG_A, "first_name": "Мария", "last_name": "Иванова",
                     "egn": "8001010000"}),
        ("clients", {"id": "cl-x", "org_id": ORG_A, "companyName": "А Клиент 2 ООД", "eik": "131313131"}),
        ("financial_accounts", {"id": "acc-1", "org_id": ORG_A, "name": "A Основна", "type": "Bank",
                                "currency": "EUR", "opening_balance": 100}),
        ("finance_payments", {"id": "pay-1", "org_id": ORG_A, "direction": "Outflow", "amount": 10,
                              "date": "2026-09-02", "method": "BankTransfer", "account_id": "acc-1",
                              "reference": "A-PAYREF", "note": "A note", "currency": "EUR",
                              "counterparty_name": "Baumit Bulgaria"}),
        ("finance_payments", {"id": "pay-a-foreign", "org_id": ORG_A, "direction": "Outflow",
                              "amount": 7, "date": "2026-09-02", "method": "Cash",
                              "account_id": "acc-only-b", "reference": "A-PAYREF-2", "currency": "EUR"}),
        ("payment_allocations", {"id": "al-1", "org_id": ORG_A, "invoice_id": "inv-shared",
                                 "payment_id": "pay-1", "amount_allocated": 3,
                                 "allocated_at": "2026-09-02"}),
        # A allocations that point at a payment / an invoice that exist ONLY in B
        ("payment_allocations", {"id": "al-a-foreign-pay", "org_id": ORG_A, "invoice_id": "inv-shared",
                                 "payment_id": "pay-only-b", "amount_allocated": 1,
                                 "allocated_at": "2026-09-02"}),
        ("payment_allocations", {"id": "al-a-foreign-inv", "org_id": ORG_A, "invoice_id": "inv-only-b",
                                 "payment_id": "pay-1", "amount_allocated": 2,
                                 "allocated_at": "2026-09-02"}),
        ("subcontractors", {"id": "sub-1", "org_id": ORG_A, "name": "А Бригада"}),
        ("subcontractor_payments", {"id": "sp-a", "org_id": ORG_A, "status": "completed",
                                    "subcontractor_id": "sub-1", "project_id": "pr-x", "amount": 5,
                                    "payment_no": "SP-A-1", "payment_date": "2026-09-02",
                                    "created_at": "2026-09-02"}),
        ("subcontractor_payments", {"id": "sp-a-foreign", "org_id": ORG_A, "status": "completed",
                                    "subcontractor_id": "sub-only-b", "project_id": "pr-only-b",
                                    "amount": 6, "payment_no": "SP-A-2", "payment_date": "2026-09-02",
                                    "created_at": "2026-09-02"}),
        ("organizations", {"id": ORG_A, "name": "A Org"}),
        ("site_daily_rosters", {"id": "ros-a", "org_id": ORG_A, "date": "2099-01-01",
                                "project_id": "pr-only-b", "workers": [{"worker_id": "u1"}]}),
        ("projects", {"id": "pr-person", "org_id": ORG_A, "code": "A-PP", "name": "A Person Project",
                      "owner_type": "person", "owner_id": "pe-x"}),
        ("projects", {"id": "pr-person-foreign", "org_id": ORG_A, "code": "A-PF", "name": "A PF",
                      "owner_type": "person", "owner_id": "pe-only-b"}),
    ]
    for name, doc in a_after:
        await db[name].insert_one(doc)
    # A's invoices: workflow fields the finance routes need; inv-shared points at A's pr-x
    await db["invoices"].update_one({"id": "inv-shared", "org_id": ORG_A}, {"$set": {
        "status": "Sent", "due_date": "2026-12-01", "created_at": "2026-09-01",
        "counterparty_name": "Baumit Bulgaria", "currency": "EUR", "vat_percent": 25, "lines": [],
        "paid_amount": 3, "remaining_amount": 7}})
    await db["invoices"].update_one({"id": "inv-a-foreign", "org_id": ORG_A}, {"$set": {
        "status": "Sent", "due_date": "2026-12-01", "created_at": "2026-09-01",
        "counterparty_name": "А купувач", "currency": "EUR", "lines": []}})
    # B first in storage order for EVERY shared id: re-insert A's copy after B's,
    # so a global find_one({"id": ...}) returns B's document (checked below).
    for coll, rid in SHARED_IDS.values():
        doc = await db[coll].find_one({"id": rid, "org_id": ORG_A}, {"_id": 0})
        await db[coll].delete_one({"id": rid, "org_id": ORG_A})
        await db[coll].insert_one(doc)
    await db["invoices"].update_many({"org_id": ORG_A, "status": {"$exists": False}}, {"$set": {
        "status": "Draft", "created_at": "2026-08-01"}})
    # A's u1 is an active employee with a roster entry on a B-only project
    await db["users"].update_one({"id": "u1", "org_id": ORG_A}, {"$set": {
        "is_active": True, "email": "u1@a", "name": "Иван Петров"}})
    return db


def a1_world():
    return run(_a1_world())


async def b_snapshot(db):
    return {n: await db[n].find({"$or": [{"org_id": ORG_B}, {"id": {"$in": ["pt-b"]}}]},
                                {"_id": 0}).sort("id", 1).to_list(None)
            for n in B_COLLECTIONS}


def no_b(text, b_ids, where, echoed=()):
    """``echoed``: a value tenant A itself sent in the request (a path id) and the
    route may repeat — A's input, not data read from B."""
    text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False, default=str)
    for marker in A1_MARKERS:
        if marker in echoed:
            continue
        assert marker not in text, "%s: tenant B value %r reached tenant A" % (where, marker)
    leaked = [i for i in b_ids if i in text]
    assert not leaked, "%s: tenant B canonical ids reached tenant A: %s" % (where, leaked[:3])


def make_app(monkeypatch, db, user):
    """The real routers, with the module database handles pointed at ``db``."""
    from fastapi import FastAPI

    from app.deps.auth import get_current_user, require_admin
    from app.deps.modules import require_m2, require_m4, require_m5
    from app.routes import dashboard, finance, hr, offers, projects, reports
    from app.services import paid_labor

    async def _noop(*a, **kw):
        return None

    async def _user():
        return dict(user)
    app = FastAPI()
    monkeypatch.setattr(paid_labor, "db", db)
    for module in (finance, offers, reports, dashboard, hr, projects):
        monkeypatch.setattr(module, "db", db)
        if hasattr(module, "log_audit"):
            monkeypatch.setattr(module, "log_audit", _noop)
        app.include_router(module.router, prefix="/api")
    for dep in (get_current_user, require_admin, require_m2, require_m4, require_m5):
        app.dependency_overrides[dep] = _user
    return app


def set_mode(monkeypatch, db, mode):
    monkeypatch.setenv(ENV_MODE, mode)
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")
    if mode == "enforce":
        ctx = RouteCtx(db)

        async def _ctx(user):
            return ctx
        monkeypatch.setattr(la, "context_for", _ctx)


async def _matrix(monkeypatch, db, mode):
    """Every protected HTTP projection as tenant A. Returns {path: checked}."""
    import httpx

    set_mode(monkeypatch, db, mode)
    b_ids = await b_canonical_ids_async(db)
    before = await b_snapshot(db)
    checked = {}

    async def get(c, url, where=None, echoed=()):
        r = await c.get(url)
        assert r.status_code == 200, (url, r.status_code, r.text[:300])
        ctype = r.headers.get("content-type", "")
        if "spreadsheet" in ctype:
            body = " ".join(map(str, xlsx_text(r.content).values()))
        elif "pdf" in ctype:
            body = pdf_text(r.content)
        else:
            body = r.json()
        no_b(body, b_ids, where or url, echoed)
        checked[(where or url).split("?")[0]] = True
        return body

    transport = httpx.ASGITransport(app=make_app(monkeypatch, db, ADMIN))
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        # ---------------------------------------------------- finance: invoices
        listed = {i["id"]: i for i in await get(c, "/api/finance/invoices")}
        assert listed["inv-shared"]["project_code"] == "A-CODE-PRX"            # the R1 leak
        assert listed["inv-shared"]["project_name"] == "A-OWN-PROJECT"
        assert listed["inv-a-foreign"]["project_code"] == ""                    # B-only project
        assert listed["inv-a-foreign"]["project_name"] == ""
        assert "inv-3" not in listed                                            # B-only invoice
        detail = await get(c, "/api/finance/invoices/inv-shared")
        assert detail["invoice_no"] == "A-INV-1" and detail["project_name"] == "A-OWN-PROJECT"
        allocs = {a["id"]: a for a in detail["allocations"]}
        assert set(allocs) == {"al-1", "al-a-foreign-pay"}                      # A's rows only
        assert allocs["al-1"]["amount_allocated"] == 3
        assert allocs["al-1"]["payment_reference"] == "A-PAYREF"               # A's pay-1
        assert "payment_reference" not in allocs["al-a-foreign-pay"]            # payment only in B
        assert (await c.get("/api/finance/invoices/inv-3")).status_code == 404  # B-only: not found
        assert (await c.get("/api/finance/invoices/inv-only-b")).status_code == 404
        pays = await get(c, "/api/finance/invoices/inv-shared/payments")
        assert [p["payment_id"] for p in pays] == ["pay-1"]
        assert pays[0]["account_name"] == "A Основна" and pays[0]["amount"] == 3
        await get(c, "/api/finance/invoices/inv-shared/versions")
        await get(c, "/api/finance/invoices/inv-shared/pdf")
        foreign_pdf = await get(c, "/api/finance/invoices/inv-a-foreign/pdf")
        assert "A-OWN-PROJECT" not in foreign_pdf
        # ---------------------------------------------- finance: payments/allocations
        payments = {p["id"]: p for p in await get(c, "/api/finance/payments")}
        assert set(payments) == {"pay-1", "pay-a-foreign"}
        assert payments["pay-1"]["account_name"] == "A Основна"
        assert payments["pay-1"]["allocated_amount"] == 5                       # 3 + 2, A rows only
        assert [x["invoice_no"] for x in payments["pay-1"]["linked_invoices"]] == ["A-INV-1"]
        assert payments["pay-a-foreign"]["account_name"] == "Unknown"           # account only in B
        pay = await get(c, "/api/finance/payments/pay-1")
        pallocs = {a["id"]: a for a in pay["allocations"]}
        assert set(pallocs) == {"al-1", "al-a-foreign-inv"}
        assert pallocs["al-1"]["invoice_no"] == "A-INV-1"
        assert "invoice_no" not in pallocs["al-a-foreign-inv"]                  # invoice only in B
        assert (await c.get("/api/finance/payments/pay-only-b")).status_code == 404
        accounts = {a["id"]: a for a in await get(c, "/api/finance/accounts")}
        assert set(accounts) == {"acc-1"} and accounts["acc-1"]["current_balance"] == 90
        await get(c, "/api/finance/stats")
        await get(c, "/api/finance/aging-report")
        await get(c, "/api/finance/upcoming-payments?days=400")
        docs = {d["id"]: d for d in await get(c, "/api/finance/subcontractor-documents")}
        assert docs["sp-a"]["counterparty_name"] == "А Бригада"
        assert docs["sp-a"]["project_name"] == "A-OWN-PROJECT"
        assert docs["sp-a-foreign"]["project_name"] == ""
        assert docs["sp-a-foreign"]["counterparty_name"] == "Подизпълнител/бригада"
        # ------------------------------------------------------------- offers
        await get(c, "/api/offers")
        offer = await get(c, "/api/offers/offer-a")
        assert offer["project_name"] == "A-OWN-PROJECT"
        assert (await get(c, "/api/offers/offer-a-foreign"))["project_name"] == ""
        await get(c, "/api/offers/offer-a/xlsx")
        await get(c, "/api/offers/offer-a/pdf")
        await get(c, "/api/offers/offer-a-foreign/xlsx")
        review = await get(c, "/api/offers/review/tok-a")
        assert review["project_name"] == "A-OWN-PROJECT" and review["company_name"] == "A Org"
        assert (await get(c, "/api/offers/review/tok-af"))["project_name"] == ""
        await get(c, "/api/offers/offer-a/events")
        # ------------------------------------------------------------ reports
        prices = await get(c, "/api/prices")
        assert {r["line_id"] for r in prices["items"]} == {"line-a", "line-a2"}
        await get(c, "/api/reports/turnover-by-counterparty?type=purchases")
        await get(c, "/api/reports/turnover-by-counterparty?type=sales")
        await get(c, "/api/reports/turnover-by-counterparty/cp1/invoices")
        drill_b = await get(c, "/api/reports/turnover-by-counterparty/cp-b-hidden-supplier/invoices",
                            where="/api/reports/turnover-by-counterparty/{foreign}/invoices",
                            echoed=("cp-b-hidden-supplier",))
        assert drill_b["items"] == [] and drill_b["counterparty_name"] == "(Неизвестен)"
        await get(c, "/api/reports/turnover-by-client")
        summary = await get(c, "/api/reports/company-finance-summary?year=2026&month=9")
        assert "999999" not in json.dumps(summary)
        await get(c, "/api/reports/company-finance-compare?year=2026&months=08,09")
        await get(c, "/api/reports/company-finance-export?year=2026&month=9&format=xlsx")
        await get(c, "/api/finance/cash-transactions")
        await get(c, "/api/reports/company-finance-series?" + PERIOD)
        await get(c, "/api/reports/finance-details/summary?" + PERIOD)
        by_cp = await get(c, "/api/reports/finance-details/by-counterparty?" + PERIOD)
        assert {r["counterparty_id"]: r["counterparty_name"] for r in by_cp["items"]}["cp-only-b"] \
            == "Unknown"
        by_pr = await get(c, "/api/reports/finance-details/by-project?" + PERIOD)
        assert {r["project_id"]: r["project_name"] for r in by_pr["items"]} == {
            "pr-x": "A-OWN-PROJECT", "pr-only-b": "Unknown"}
        await get(c, "/api/reports/finance-details/transactions?" + PERIOD)
        await get(c, "/api/reports/finance-details/top-counterparties?direction=income&" + PERIOD)
        await get(c, "/api/reports/finance-details/top-counterparties?direction=expense&" + PERIOD)
        # ---------------------------------------------------------- dashboard
        await get(c, "/api/dashboard/pending-payments")
        await get(c, "/api/dashboard/activity")
        # ---------------------------------------------------- advances, import
        advances = {a["id"]: a for a in await get(c, "/api/advances")}
        assert "adv-b" not in advances
        assert advances["adv-foreign-user"]["user_name"] == "Unknown"
        r = await c.post("/api/projects/pr-x/import-client-invoice")
        assert r.status_code == 200, r.text
        no_b(r.json(), b_ids, "import-client-invoice (company)")
        assert r.json()["invoice_details"]["company_name"] == "А Клиент ООД"
        r = await c.post("/api/projects/pr-person/import-client-invoice")
        assert r.status_code == 200, r.text
        no_b(r.json(), b_ids, "import-client-invoice (person)")
        assert r.json()["invoice_details"]["company_name"] == "Мария Иванова"
        r = await c.post("/api/projects/pr-person-foreign/import-client-invoice")
        assert r.status_code == 404                     # owner exists only in B: no data
        checked["/api/projects/{id}/import-client-invoice"] = True

        # -------------------------------------- A writes on SHARED ids (B untouched)
        r = await c.put("/api/finance/invoices/inv-shared", json={"notes": "A edit"})
        assert r.status_code == 200, r.text
        no_b(r.json(), b_ids, "PUT invoice")
        assert r.json()["notes"] == "A edit"
        r = await c.post("/api/finance/invoices/inv-shared/payments",
                         json={"amount": 1, "method": "BankTransfer", "account_id": "acc-1"})
        assert r.status_code == 201, r.text
        inv = r.json()["invoice"]
        no_b(inv, b_ids, "POST invoice payment")
        # paid = A's allocations only (3 + 1 + 1); B's 999999 allocations never count
        assert inv["paid_amount"] == 5 and inv["status"] == "PartiallyPaid"
        r = await c.delete("/api/finance/invoices/inv-shared/payments/al-1")
        assert r.status_code == 200, r.text
        r = await c.put("/api/finance/accounts/acc-1", json={"name": "A Основна 2"})
        assert r.status_code == 200 and r.json()["name"] == "A Основна 2", r.text
        no_b(r.json(), b_ids, "PUT account")
        r = await c.put("/api/offers/offer-a", json={"title": "A title"})
        assert r.status_code in (200, 403), r.text      # Sent offer: refused, no write either way
        checked["writes"] = True

    # SiteManager scope: a team row that resolves only through B's project
    transport = httpx.ASGITransport(app=make_app(monkeypatch, db, SITE))
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/api/finance/invoices")
        assert r.status_code == 200 and r.json() == [], r.text
        r = await c.get("/api/finance/invoices/inv-a-foreign")
        assert r.status_code == 403, r.text
        r = await c.get("/api/offers")
        assert r.status_code == 200 and r.json() == [], r.text
        checked["sitemanager-scope"] = True

    # nothing of tenant B changed, whatever A read or wrote
    assert await b_snapshot(db) == before
    return checked


#: The protected HTTP projections the matrix must have exercised.
EXPECTED_PATHS = {
    "/api/finance/invoices", "/api/finance/invoices/inv-shared",
    "/api/finance/invoices/inv-shared/payments", "/api/finance/invoices/inv-shared/versions",
    "/api/finance/invoices/inv-shared/pdf", "/api/finance/invoices/inv-a-foreign/pdf",
    "/api/finance/payments", "/api/finance/payments/pay-1", "/api/finance/accounts",
    "/api/finance/stats", "/api/finance/aging-report", "/api/finance/upcoming-payments",
    "/api/finance/subcontractor-documents", "/api/offers", "/api/offers/offer-a",
    "/api/offers/offer-a-foreign", "/api/offers/offer-a/xlsx", "/api/offers/offer-a/pdf",
    "/api/offers/offer-a-foreign/xlsx", "/api/offers/review/tok-a", "/api/offers/review/tok-af",
    "/api/offers/offer-a/events", "/api/prices", "/api/reports/turnover-by-counterparty",
    "/api/reports/turnover-by-counterparty/cp1/invoices",
    "/api/reports/turnover-by-counterparty/{foreign}/invoices", "/api/reports/turnover-by-client",
    "/api/reports/company-finance-summary", "/api/reports/company-finance-compare",
    "/api/reports/company-finance-export", "/api/finance/cash-transactions",
    "/api/reports/company-finance-series", "/api/reports/finance-details/summary",
    "/api/reports/finance-details/by-counterparty", "/api/reports/finance-details/by-project",
    "/api/reports/finance-details/transactions", "/api/reports/finance-details/top-counterparties",
    "/api/dashboard/pending-payments", "/api/dashboard/activity", "/api/advances",
    "/api/projects/{id}/import-client-invoice", "writes", "sitemanager-scope",
}


@pytest.fixture
def plain_pdf_fonts(monkeypatch):
    import reportlab.pdfbase.ttfonts as ttfonts

    def unavailable(*a, **kw):
        raise OSError("font unavailable in this test")
    monkeypatch.setattr(ttfonts, "TTFont", unavailable)


# ================================================================== the matrix
@pytest.mark.parametrize("mode", MODES)
def test_a1_collision_matrix_over_http(monkeypatch, plain_pdf_fonts, mode):
    async def body():
        db = await _a1_world()
        return await _matrix(monkeypatch, db, mode)
    checked = run(body())
    assert set(checked) == EXPECTED_PATHS


def test_every_a1_entity_really_collides_and_b_is_stored_first():
    """The fixture itself: each named entity id exists in BOTH tenants and a
    global ``find_one({"id": ...})`` returns B's copy — so a bare lookup WOULD leak."""
    db = a1_world()

    async def check():
        for entity, (coll, rid) in SHARED_IDS.items():
            owners = {d["org_id"] for d in await db[coll].find({"id": rid}).to_list(None)}
            assert owners == {ORG_A, ORG_B}, entity
            first = await db[coll].find_one({"id": rid})
            assert first["org_id"] == ORG_B, "%s: B's copy must be found first" % entity
    run(check())


def test_the_matrix_would_see_a_b_value():
    """Control: the marker check is real — B's project text on A's own row is caught."""
    db = a1_world()
    run(db["projects"].update_one({"id": "pr-x", "org_id": ORG_A}, {"$set": {"name": "B-SECRET-PROJECT"}}))
    with pytest.raises(AssertionError, match="B-SECRET-PROJECT"):
        run(_listing_only(db))


async def _listing_only(db):
    import httpx
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    try:
        set_mode(mp, db, "off")
        transport = httpx.ASGITransport(app=make_app(mp, db, ADMIN))
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            no_b((await c.get("/api/finance/invoices")).json(), set(), "control")
    finally:
        mp.undo()
