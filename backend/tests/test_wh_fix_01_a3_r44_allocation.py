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
        "counterparty_name": "Доставчик"})
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
        r = await c.get("/api/invoice-lines/invoices-to-allocate", headers=hdr("acct-a"))
        assert r.status_code == 200, r.text
        [inv] = r.json()["invoices"]
        assert inv["id"] == INV and inv["allocation_status"] == "pending_allocation"
        [line] = inv["pending_lines"]
        assert (line["line_id"], line["allocated_qty"], line["unallocated_qty"]) == (LINE, 60.0, 40.0)
        issue = inv["dq_issue"]
        assert issue["owner_role"] == "accountant" and issue["deadline_days"] == 3
        assert issue["escalated"] is False and issue["status"] == "open"
        # read again → still ONE issue and ONE alarm (deduplicated)
        await c.get("/api/invoice-lines/invoices-to-allocate", headers=hdr("acct-a"))
        assert await op.dq_issues.count_documents({"entity_id": INV}) == 1
        [alarm] = await op.alarm_events.find({"context.entity_id": INV}).to_list(None)
        assert alarm["status"] == "active" and alarm["rule_id"] == "INVOICE_NOT_FULLY_ALLOCATED"
        # P&L(P): only the allocated 60 × 10
        from app.services.canonical_material_cost import project_material_cost
        cost = await project_material_cost(_tenant(op), ORG_A, "prj-1")
        assert cost["invoice_cost"] == 600.0
        # allocate the remaining 40 (a correction with a canonical AuditEvent)
        r = await c.post(f"/api/invoice-lines/{LINE}/allocate", headers=hdr("acct-a"), json={
            "allocations": [{"type": "project", "ref_id": "prj-1", "qty": 60},
                            {"type": "project", "ref_id": "prj-a", "qty": 40}]})
        assert r.status_code == 200, r.text
        assert r.json()["allocation_status"] == "allocated"
        assert await op.audit_events.count_documents(
            {"action": "finance.invoice_line.allocation_corrected", "entity_id": LINE}) == 1
        r = await c.get("/api/invoice-lines/invoices-to-allocate", headers=hdr("acct-a"))
        assert r.json()["count"] == 0
        assert (await op.dq_issues.find_one({"entity_id": INV}))["status"] == "resolved"
        assert (await op.alarm_events.find_one({"context.entity_id": INV}))["status"] == "resolved"
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
    async def scenario(c, op):
        from app.services.invoice_allocation import invoices_to_allocate
        if setting is not None:
            await op.organizations.update_one({"id": ORG_A},
                                              {"$set": {"allocation_dq_deadline_days": setting}})
        t0 = datetime(2026, 11, 8, 9, 0, tzinfo=timezone.utc)
        [inv] = await invoices_to_allocate(_tenant(op), ORG_A, now=t0)
        issue = inv["dq_issue"]
        assert issue["due_at"] == (t0 + timedelta(days=days)).isoformat()
        assert issue["escalated"] is False and issue["escalated_to_role"] is None
        [inv] = await invoices_to_allocate(_tenant(op), ORG_A, now=t0 + timedelta(days=days, hours=1))
        issue = inv["dq_issue"]
        assert issue["escalated"] is True and issue["escalated_to_role"] == "owner"
        assert issue["severity"] == "high" and issue["opened_at"] == t0.isoformat()
        alarm = await op.alarm_events.find_one({"context.entity_id": INV})
        assert alarm["severity"] == "critical" and alarm["context"]["escalated_to_role"] == "owner"
    run(monkeypatch, backend, mode, scenario)
