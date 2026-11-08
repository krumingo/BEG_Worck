"""
WH-FIX-01 Addendum A2 (FG-155 per canon, oracle Q001) + A3 (Р44, Крум 08.11.2026).

A supplier invoice line of 100, 60 allocated to project P:
  * the line is in the interim state „чака разпределение" (final only at 100 %);
  * P&L(P) counts 60 — the remainder 40 is in no project result;
  * every payment path (quick-pay, allocate, partial) → 409
    INVOICE_NOT_FULLY_ALLOCATED, nothing written (Р44);
  * „фактури за разпределяне" lists it (drill-down to the line) with ONE DQ issue
    (owner Accountant, deadline 3 days per tenant, then escalation to Owner) and
    ONE alarm; allocating the 40 resolves both and the payment goes through;
  * the allocation change writes a canonical AuditEvent.

PERMISSION_SERVICE_MODE off / shadow / enforce; mongomock and, with
W0_03_REAL_MONGO_URL, a real local MongoDB (PAY-01 harness).
"""
from datetime import datetime, timedelta, timezone

import pytest

from tests.test_pay_01_payment_reversal import (  # noqa: F401  (fixtures)
    ORG_A, backend, hdr, mode, pay, snap,
)
import tests.test_pay_01_payment_reversal as h

INV, LINE = "inv-r44", "line-r44"


async def _seed_supplier_invoice(op, allocated=60):
    await op.invoices.insert_one({
        "id": INV, "org_id": ORG_A, "invoice_no": "R-44", "direction": "Received",
        "kind": "Invoice", "status": "Sent", "issue_date": "2026-11-01", "due_date": "2099-12-31",
        "currency": "EUR", "subtotal": 1000.0, "vat_percent": 20, "vat_amount": 200.0,
        "total": 1200.0, "paid_amount": 0, "remaining_amount": 1200.0,
        "counterparty_name": "Доставчик", "created_at": "2026-11-08T09:00:00+00:00"})
    await op.invoice_lines.insert_one({
        "id": LINE, "org_id": ORG_A, "invoice_id": INV, "line_no": 1, "description": "Лепило",
        "unit": "bag", "qty": 100, "unit_price": 10, "vat_percent": 20,
        "line_total_ex_vat": 1000.0, "vat_amount": 200.0, "line_total_inc_vat": 1200.0,
        "allocations": [{"type": "project", "ref_id": "prj-1", "qty": allocated, "note": None}]})


def run(monkeypatch, backend, mode, scenario, allocated=60):
    """PAY-01 harness + the invoice-lines router and the supplier invoice."""
    import asyncio
    import httpx

    async def go():
        async with h._Dbs(backend) as (op, sysdb):
            await h._bootstrap_indexes(op)
            await h._seed(op, sysdb)
            await _seed_supplier_invoice(op, allocated)
            app = h._app(monkeypatch, op, sysdb, mode)
            from app.routes import invoice_lines as r_lines
            monkeypatch.setattr(r_lines, "db", op)
            app.include_router(r_lines.router, prefix="/api")
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://r44") as c:
                return await scenario(c, op)
    return asyncio.run(go())


def _tenant(op):
    from app.tenancy.data_access import TenantData
    return TenantData.for_resolved_org(op, ORG_A)


# ───────────────────────────── Р44 — payment refused ─────────────────────────────

def test_r44_quick_pay_of_a_partly_allocated_supplier_invoice_is_409(monkeypatch, backend, mode):
    async def scenario(c, op):
        before = await snap(op)
        for amount in (1200.0, 100.0):                     # full and partial
            r = await c.post(f"/api/finance/invoices/{INV}/payments", headers=hdr("acct-a"),
                             json={"amount": amount, "method": "BankTransfer",
                                   "account_id": h.BANK_A})
            assert r.status_code == 409, r.text
            assert r.json()["detail"]["error_code"] == "INVOICE_NOT_FULLY_ALLOCATED"
            assert r.json()["detail"]["pending_lines"] == [{"line_id": LINE, "unallocated_qty": 40.0}]
        after = await snap(op)
        for coll in ("finance_payments", "payment_allocations", "invoices", "audit_events"):
            assert after[coll] == before[coll], coll        # nothing written
    run(monkeypatch, backend, mode, scenario)


def test_r44_allocate_payment_to_it_is_409(monkeypatch, backend, mode):
    async def scenario(c, op):
        pid = await pay(c, 500.0, direction="Outflow")
        before = await snap(op)
        r = await c.post(f"/api/finance/payments/{pid}/allocate", headers=hdr("acct-a"),
                         json={"allocations": [{"invoice_id": INV, "amount": 50}]})
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error_code"] == "INVOICE_NOT_FULLY_ALLOCATED"
        assert (await snap(op))["payment_allocations"] == before["payment_allocations"]
    run(monkeypatch, backend, mode, scenario)


def test_r44_issued_invoices_are_not_affected(monkeypatch, backend, mode):
    async def scenario(c, op):
        r = await c.post("/api/finance/invoices/inv-a1/payments", headers=hdr("acct-a"),
                         json={"amount": 10, "method": "BankTransfer", "account_id": h.BANK_A})
        assert r.status_code == 201, r.text
    run(monkeypatch, backend, mode, scenario)


# ──────────────────── A2 — pending list, DQ, alarm, AuditEvent, payment after ────────────────────

def test_a2_pending_dq_alarm_then_allocation_resolves_and_payment_passes(monkeypatch, backend, mode):
    async def scenario(c, op):
        # FG-201: the DQ issue / alarm are opened by a WRITE (with an AuditEvent)
        r = await c.post(f"/api/invoice-lines/{LINE}/allocate", headers=hdr("acct-a"), json={
            "allocations": [{"type": "project", "ref_id": "prj-1", "qty": 60}]})
        assert r.status_code == 200, r.text
        assert r.json()["allocation_status"] == "pending_allocation"
        assert await op.dq_issues.count_documents({"entity_id": INV, "status": "open"}) == 1
        assert await op.audit_events.count_documents(
            {"action": "dq.invoice_allocation.opened"}) == 1
        [alarm] = await op.alarm_events.find({"context.entity_id": INV}).to_list(None)
        assert alarm["status"] == "active" and alarm["rule_id"] == "INVOICE_NOT_FULLY_ALLOCATED"
        # … and the list GET writes NOTHING (FG-201)
        before = await snap(op, ("dq_issues", "alarm_events", "audit_events", "invoices",
                                 "invoice_lines"))
        r = await c.get("/api/invoice-lines/invoices-to-allocate", headers=hdr("acct-a"))
        assert r.status_code == 200, r.text
        await c.get("/api/invoice-lines/invoices-to-allocate", headers=hdr("acct-a"))
        assert await snap(op, ("dq_issues", "alarm_events", "audit_events", "invoices",
                               "invoice_lines")) == before
        [inv] = r.json()["invoices"]
        assert inv["id"] == INV and inv["allocation_status"] == "pending_allocation"
        [line] = inv["pending_lines"]
        assert (line["line_id"], line["allocated_qty"], line["unallocated_qty"]) == (LINE, 60.0, 40.0)
        issue = inv["dq_issue"]
        assert issue["owner_role"] == "accountant" and issue["deadline_days"] == 3
        assert issue["escalated"] is False and issue["status"] == "open"
        # P&L(P): only the allocated 60 × 10
        from app.services.canonical_material_cost import project_material_cost
        cost = await project_material_cost(_tenant(op), ORG_A, "prj-1")
        assert cost["invoice_cost"] == 600.0
        # allocate the remaining 40 → the write resolves issue + alarm (AuditEvent)
        r = await c.post(f"/api/invoice-lines/{LINE}/allocate", headers=hdr("acct-a"), json={
            "allocations": [{"type": "project", "ref_id": "prj-1", "qty": 60},
                            {"type": "project", "ref_id": "prj-a", "qty": 40}]})
        assert r.status_code == 200, r.text
        assert r.json()["allocation_status"] == "allocated"
        assert await op.audit_events.count_documents(
            {"action": "finance.invoice_line.allocation_corrected", "entity_id": LINE}) == 2
        assert (await op.dq_issues.find_one({"entity_id": INV}))["status"] == "resolved"
        assert (await op.alarm_events.find_one({"context.entity_id": INV}))["status"] == "resolved"
        assert await op.audit_events.count_documents(
            {"action": "dq.invoice_allocation.resolved"}) == 1
        r = await c.get("/api/invoice-lines/invoices-to-allocate", headers=hdr("acct-a"))
        assert r.json()["count"] == 0
        r = await c.post(f"/api/finance/invoices/{INV}/payments", headers=hdr("acct-a"),
                         json={"amount": 100.0, "method": "BankTransfer", "account_id": h.BANK_A})
        assert r.status_code == 201, r.text
    run(monkeypatch, backend, mode, scenario)


@pytest.mark.parametrize("who", ["viewer-a", "site-a", "tech-a"])
def test_a2_pending_list_is_for_finance_roles_only(monkeypatch, backend, mode, who):
    async def scenario(c, op):
        r = await c.get("/api/invoice-lines/invoices-to-allocate", headers=hdr(who))
        assert r.status_code == 403, r.text
    run(monkeypatch, backend, mode, scenario)


# ───────────────────── A3 — owner Accountant, 3 days, escalation to Owner ─────────────────────

@pytest.mark.parametrize("setting,days", [(None, 3), (5, 5)])
def test_a3_deadline_per_tenant_and_escalation_to_owner(monkeypatch, backend, mode, setting, days):
    """A3 #7 + FG-201: the escalation is COMPUTED when read (opened + deadline
    < now → Owner); the read writes nothing."""
    async def scenario(c, op):
        from app.services.invoice_allocation import invoices_to_allocate
        if setting is not None:
            await op.organizations.update_one({"id": ORG_A},
                                              {"$set": {"allocation_dq_deadline_days": setting}})
        t0 = datetime(2026, 11, 8, 9, 0, tzinfo=timezone.utc)      # the invoice's created_at
        before = await snap(op, ("dq_issues", "alarm_events", "audit_events"))
        [inv] = await invoices_to_allocate(_tenant(op), ORG_A, now=t0)
        issue = inv["dq_issue"]
        assert issue["due_at"] == (t0 + timedelta(days=days)).isoformat()
        assert issue["escalated"] is False and issue["escalated_to_role"] is None
        [inv] = await invoices_to_allocate(_tenant(op), ORG_A, now=t0 + timedelta(days=days, hours=1))
        issue = inv["dq_issue"]
        assert issue["escalated"] is True and issue["escalated_to_role"] == "owner"
        assert issue["severity"] == "high" and issue["owner_role"] == "accountant"
        assert await snap(op, ("dq_issues", "alarm_events", "audit_events")) == before
    run(monkeypatch, backend, mode, scenario)


# ───────────────── FG-200 — finance UI invoices (embedded lines) ─────────────────

def _ui_invoice(project_id=None):
    body = {"direction": "Received", "invoice_no": "UI-1", "issue_date": "2026-11-05",
            "due_date": "2099-12-31", "counterparty_name": "Доставчик", "currency": "EUR",
            "vat_percent": 20, "lines": [{"description": "Пясък", "unit": "t", "qty": 4,
                                          "unit_price": 25}]}
    if project_id:
        body["project_id"] = project_id
    return body


def test_fg200_ui_invoice_with_one_header_project_is_stamped_and_payable(monkeypatch, backend, mode):
    async def scenario(c, op):
        r = await c.post("/api/finance/invoices", headers=hdr("acct-a"), json=_ui_invoice("prj-1"))
        assert r.status_code == 201, r.text
        inv_id = r.json()["id"]
        doc = await op.invoices.find_one({"id": inv_id})
        [line] = doc["lines"]
        assert [(a["type"], a["ref_id"], a["qty"]) for a in line["allocations"]] == [("project", "prj-1", 4)]
        assert await op.audit_events.count_documents(
            {"action": "finance.invoice_line.allocation_corrected", "entity_id": line["id"]}) == 1
        assert await op.dq_issues.count_documents({"entity_id": inv_id}) == 0
        assert (await c.post(f"/api/finance/invoices/{inv_id}/send", headers=hdr("acct-a"))).status_code == 200
        r = await c.post(f"/api/finance/invoices/{inv_id}/payments", headers=hdr("acct-a"),
                         json={"amount": 10.0, "method": "BankTransfer", "account_id": h.BANK_A})
        assert r.status_code == 201, r.text
    run(monkeypatch, backend, mode, scenario)


def test_fg200_ui_invoice_without_destination_is_pending_and_not_payable(monkeypatch, backend, mode):
    async def scenario(c, op):
        r = await c.post("/api/finance/invoices", headers=hdr("acct-a"), json=_ui_invoice())
        assert r.status_code == 201, r.text
        inv_id = r.json()["id"]
        assert await op.dq_issues.count_documents({"entity_id": inv_id, "status": "open"}) == 1
        assert await op.audit_events.count_documents({"action": "dq.invoice_allocation.opened"}) == 1
        assert (await c.post(f"/api/finance/invoices/{inv_id}/send", headers=hdr("acct-a"))).status_code == 200
        r = await c.post(f"/api/finance/invoices/{inv_id}/payments", headers=hdr("acct-a"),
                         json={"amount": 10.0, "method": "BankTransfer", "account_id": h.BANK_A})
        assert r.status_code == 409 and r.json()["detail"]["error_code"] == "INVOICE_NOT_FULLY_ALLOCATED"
        listed = (await c.get("/api/invoice-lines/invoices-to-allocate", headers=hdr("acct-a"))).json()
        assert inv_id in {i["id"] for i in listed["invoices"]}
        # a line destination given in the UI makes it final
        r = await c.put(f"/api/finance/invoices/{inv_id}/lines", headers=hdr("acct-a"), json={
            "lines": [{"description": "Пясък", "unit": "t", "qty": 4, "unit_price": 25,
                       "project_id": "prj-1"}]})
        assert r.status_code == 200, r.text
        assert (await op.dq_issues.find_one({"entity_id": inv_id}))["status"] == "resolved"
        r = await c.post(f"/api/finance/invoices/{inv_id}/payments", headers=hdr("acct-a"),
                         json={"amount": 10.0, "method": "BankTransfer", "account_id": h.BANK_A})
        assert r.status_code == 201, r.text
    run(monkeypatch, backend, mode, scenario)


def test_a4_header_only_supplier_invoice_is_not_payable_until_written_on_lines(
        monkeypatch, backend, mode):
    """A4 #9 (Р45): a header flag is not final — 409 until the destination is
    written on every line (here by the A4 #11 migration); then payable."""
    async def scenario(c, op):
        await op.invoices.update_one({"id": INV}, {"$set": {
            "allocations": [{"type": "project", "ref_id": "prj-1"}]}})
        await op.invoice_lines.update_one({"id": LINE}, {"$set": {"allocations": []}})
        pay_body = {"amount": 100.0, "method": "BankTransfer", "account_id": h.BANK_A}
        r = await c.post(f"/api/finance/invoices/{INV}/payments", headers=hdr("acct-a"), json=pay_body)
        assert r.status_code == 409, r.text
        from app.services.invoice_allocation import migrate_header_allocations
        rep = await migrate_header_allocations(_tenant(op), ORG_A, {"id": "acct-a", "org_id": ORG_A,
                                                                    "role": "Accountant"},
                                               dry_run=False)
        assert rep["written"] == [{"invoice_id": INV, "lines_written": 1}]
        r = await c.post(f"/api/finance/invoices/{INV}/payments", headers=hdr("acct-a"), json=pay_body)
        assert r.status_code == 201, r.text
    run(monkeypatch, backend, mode, scenario)


def test_a4_percentage_header_is_pending_and_not_payable(monkeypatch, backend, mode):
    async def scenario(c, op):
        await op.invoices.update_one({"id": INV}, {"$set": {"allocations": [
            {"type": "project", "ref_id": "prj-1", "percent": 40},
            {"type": "project", "ref_id": "prj-a", "percent": 60}]}})
        await op.invoice_lines.update_one({"id": LINE}, {"$set": {"allocations": []}})
        r = await c.post(f"/api/finance/invoices/{INV}/payments", headers=hdr("acct-a"),
                         json={"amount": 10.0, "method": "BankTransfer", "account_id": h.BANK_A})
        assert r.status_code == 409 and r.json()["detail"]["error_code"] == "INVOICE_NOT_FULLY_ALLOCATED"
        listed = (await c.get("/api/invoice-lines/invoices-to-allocate", headers=hdr("acct-a"))).json()
        [inv] = listed["invoices"]
        assert inv["id"] == INV and len(inv["header_destinations"]) == 2
    run(monkeypatch, backend, mode, scenario)


def test_a4_line_percentage_becomes_exact_amounts(monkeypatch, backend, mode):
    """A4 #10: a percentage on the line is converted at once — cumulative
    rounding, Σ amount = the line value, Σ qty = the line qty; then payable."""
    async def scenario(c, op):
        r = await c.post(f"/api/invoice-lines/{LINE}/allocate", headers=hdr("acct-a"), json={
            "allocations": [{"type": "project", "ref_id": "prj-1", "percent": 33.33},
                            {"type": "project", "ref_id": "prj-a", "percent": 33.33},
                            {"type": "project", "ref_id": "prj-1", "percent": 33.34}]})
        assert r.status_code == 200, r.text
        allocs = (await op.invoice_lines.find_one({"id": LINE}))["allocations"]
        assert [a["amount"] for a in allocs] == [333.3, 333.3, 333.4]
        assert round(sum(a["amount"] for a in allocs), 2) == 1000.0
        assert round(sum(a["qty"] for a in allocs), 4) == 100.0
        assert all("percent" not in a for a in allocs)
        assert r.json()["allocation_status"] == "allocated"
        r = await c.post(f"/api/finance/invoices/{INV}/payments", headers=hdr("acct-a"),
                         json={"amount": 10.0, "method": "BankTransfer", "account_id": h.BANK_A})
        assert r.status_code == 201, r.text
    run(monkeypatch, backend, mode, scenario)


def test_a4_new_line_gets_the_single_header_destination(monkeypatch, backend, mode):
    """A4 #9: writing a line on a Draft invoice with ONE header destination
    writes it on the line, with an AuditEvent, in the same transaction."""
    async def scenario(c, op):
        await op.invoices.insert_one({
            "id": "inv-draft-r45", "org_id": ORG_A, "invoice_no": "D-45", "direction": "Received",
            "kind": "Invoice", "status": "Draft", "issue_date": "2026-11-01",
            "due_date": "2099-12-31", "currency": "EUR", "subtotal": 0, "total": 0,
            "allocations": [{"type": "project", "ref_id": "prj-1"}]})
        r = await c.post("/api/invoice-lines", headers=hdr("acct-a"), json={
            "invoice_id": "inv-draft-r45", "line_no": 1, "description": "Пясък", "unit": "t",
            "qty": 4, "unit_price": 25})
        assert r.status_code == 201, r.text
        line = await op.invoice_lines.find_one({"invoice_id": "inv-draft-r45"})
        assert [(a["type"], a["ref_id"], a["qty"]) for a in line["allocations"]] == [("project", "prj-1", 4)]
        assert await op.audit_events.count_documents(
            {"action": "finance.invoice_line.allocation_corrected", "entity_id": line["id"]}) == 1
    run(monkeypatch, backend, mode, scenario)
