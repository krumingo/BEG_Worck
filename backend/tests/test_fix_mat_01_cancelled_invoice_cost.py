"""
FIX-MAT-01 — a Cancelled supplier invoice is not project material cost nor
project input VAT (CLAUDE.md §7: material cost is recognised once, from valid
documents).

de720f94: a supplier invoice line allocated to the project (``invoice_lines``
with ``allocations`` type=project) raised the project P&L material cost by the
line (+110) and the input VAT (+22); cancelling the invoice
(``POST /finance/invoices/{id}/cancel``, which does not touch the lines) left
both in the P&L. Fix: the readers (``canonical_material_cost.
project_allocated_invoice_lines`` — Path B and ``project_input_vat``) skip the
lines of an invoice whose status is ``Cancelled``. The lines themselves are not
changed (no hard delete, no migration). Draft was NOT decided by FIX-MAT-01;
Р99 (Крум 16.11.2026, FIX-MAT-02) then decided it: a Draft is not officially
entered and does not count either (``app.services.official_invoice``).

Cases:
  1. allocated line of a Sent invoice counts: material +110, VAT +22;
  2. after the real cancel endpoint → 0 and 0; the line is unchanged;
  3. another, non-cancelled invoice on the same project still counts;
  4. tenant isolation: another org's Cancelled invoice (same invoice id, its
     own line on the project) changes nothing in this org;
  5. Draft: Р99 (FIX-MAT-02) — not officially entered, so 0 / 0 (FIX-MAT-01
     itself had left Draft counting; that expectation is replaced).

PAY-01 harness (HTTP finance router, PERMISSION_SERVICE_MODE off / shadow /
enforce) on mongomock and, with W0_03_REAL_MONGO_URL (a disposable LOCAL
MongoDB), on a real replica set. Databases are named ``fixtest_mat_*`` and
dropped afterwards.

    W0_03_REAL_MONGO_URL=... PYTHONPATH=. pytest \
        tests/test_fix_mat_01_cancelled_invoice_cost.py -q --noconftest -p no:cacheprovider
"""
import asyncio
import uuid

import pytest

from tests.test_pay_01_payment_reversal import (  # noqa: F401  (fixtures)
    ORG_A, ORG_B, backend, hdr, mode,
)
import tests.test_pay_01_payment_reversal as h

PRJ = "prj-1"
DAY = "2026-11-10"


class _FixDbs(h._Dbs):
    """The PAY-01 databases, named ``fixtest_mat_*``."""

    def __init__(self, backend):
        super().__init__(backend)
        tag = uuid.uuid4().hex[:10]
        self.names = ("fixtest_mat_op_" + tag, "fixtest_mat_sys_" + tag)
        assert all(n.startswith("fixtest_mat_") for n in self.names)


def run(monkeypatch, backend, mode, scenario):
    import httpx

    async def go():
        async with _FixDbs(backend) as (op, sysdb):
            await h._bootstrap_indexes(op)
            await h._seed(op, sysdb)
            app = h._app(monkeypatch, op, sysdb, mode)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://fixmat01") as c:
                return await scenario(c, op)
    return asyncio.run(go())


async def _supplier_invoice(op, inv_id, *, org=ORG_A, status="Sent", value=110.0,
                            project=PRJ, line_id=None):
    """A supplier invoice + one ``invoice_lines`` line (qty 1, VAT 20 %)
    allocated wholly to ``project``, as routes/invoice_lines stores it."""
    vat = round(value * 0.2, 2)
    await op.invoices.insert_one({
        "id": inv_id, "org_id": org, "invoice_no": "R-" + inv_id, "direction": "Received",
        "kind": "Invoice", "status": status, "issue_date": DAY, "due_date": "2099-12-31",
        "currency": "EUR", "lines": [], "subtotal": value, "vat_percent": 20,
        "vat_amount": vat, "total": value + vat, "paid_amount": 0,
        "remaining_amount": value + vat, "counterparty_name": "Доставчик",
        "created_at": DAY + "T10:00:00+00:00"})
    line = {
        "id": line_id or ("line-" + inv_id + "-" + org), "org_id": org, "invoice_id": inv_id,
        "line_no": 1, "description": "Лепило", "unit": "бр", "qty": 1, "unit_price": value,
        "vat_percent": 20, "line_total_ex_vat": value, "vat_amount": vat,
        "line_total_inc_vat": value + vat, "created_at": DAY + "T10:00:00+00:00",
        "allocations": [{"type": "project", "ref_id": project, "qty": 1}]}
    await op.invoice_lines.insert_one(line)
    return line["id"]


async def _project(org=ORG_A, project=PRJ):
    """(P&L material cost, P&L input VAT, helper Path B cost, helper VAT)."""
    from app.services.project_pnl import compute_project_pnl
    from app.services.canonical_material_cost import project_input_vat, project_material_cost
    from app.tenancy.data_access import TenantData
    import app.services.project_pnl as pnl_mod
    pnl = await compute_project_pnl(org, project)
    tenant = TenantData.for_resolved_org(pnl_mod.db, org)
    cost = await project_material_cost(tenant, org, project)
    vat = await project_input_vat(tenant, org, project)
    return (pnl["expense"]["material_cost"], pnl["vat"]["input_vat"],
            cost["invoice_cost"], vat)


async def _cancel(c, inv_id, who="acct-a"):
    r = await c.post(f"/api/finance/invoices/{inv_id}/cancel", headers=hdr(who))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "Cancelled"


def test_01_allocated_line_counts_then_cancel_removes_it(monkeypatch, backend, mode):
    async def scenario(c, op):
        line_id = await _supplier_invoice(op, "inv-mat-1")
        assert await _project() == (110.0, 22.0, 110.0, 22.0)
        before = await op.invoice_lines.find_one({"id": line_id}, {"_id": 0})
        await _cancel(c, "inv-mat-1")
        # de720f94: (110.0, 22.0, 110.0, 22.0) — the cancelled invoice stayed.
        assert await _project() == (0, 0, 0, 0)
        # the line itself is untouched (no hard delete, no mutation)
        assert await op.invoice_lines.find_one({"id": line_id}, {"_id": 0}) == before
    run(monkeypatch, backend, mode, scenario)


def test_02_other_non_cancelled_invoice_still_counts(monkeypatch, backend, mode):
    async def scenario(c, op):
        await _supplier_invoice(op, "inv-mat-1")
        await _supplier_invoice(op, "inv-mat-2", value=55.0)
        assert await _project() == (165.0, 33.0, 165.0, 33.0)
        await _cancel(c, "inv-mat-1")
        # de720f94: (165.0, 33.0, 165.0, 33.0)
        assert await _project() == (55.0, 11.0, 55.0, 11.0)
    run(monkeypatch, backend, mode, scenario)


def test_03_other_tenant_cancelled_invoice_does_not_affect(monkeypatch, backend, mode):
    async def scenario(c, op):
        # same invoice id in both orgs: ORG_A Sent, ORG_B Cancelled — the
        # status of ORG_B's invoice must not reach ORG_A's line.
        await _supplier_invoice(op, "inv-shared", org=ORG_A)
        await _supplier_invoice(op, "inv-shared", org=ORG_B, status="Cancelled",
                                value=999.0, project=PRJ)
        await _supplier_invoice(op, "inv-b-own", org=ORG_B, status="Cancelled",
                                value=777.0, project=PRJ)
        assert await _project(ORG_A) == (110.0, 22.0, 110.0, 22.0)
        # ORG_B's own cancelled lines count nowhere (its P&L too)
        assert await _project(ORG_B) == (0, 0, 0, 0)
        # ORG_B cannot cancel ORG_A's invoice
        r = await c.post("/api/finance/invoices/inv-shared/cancel", headers=hdr("admin-b"))
        assert r.status_code in (400, 403, 404, 409), r.text  # 409: it hit ORG_B's own (already Cancelled) invoice
        assert await _project(ORG_A) == (110.0, 22.0, 110.0, 22.0)
    run(monkeypatch, backend, mode, scenario)


def test_04_draft_is_not_cost_r99(monkeypatch, backend, mode):
    """Р99 (Крум 16.11.2026, FIX-MAT-02) replaces FIX-MAT-01's "Draft
    unchanged": a Draft invoice is not officially entered, so its allocated
    line is neither material cost nor input VAT (c0ee4613 asserted
    (110, 22, 110, 22) here). Cancelling it keeps it at 0."""
    async def scenario(c, op):
        await _supplier_invoice(op, "inv-mat-draft", status="Draft")
        assert await _project() == (0, 0, 0, 0)
        await _cancel(c, "inv-mat-draft")
        assert await _project() == (0, 0, 0, 0)
    run(monkeypatch, backend, mode, scenario)


def test_05_one_selection_for_cost_and_vat():
    """Both readers go through the one selection helper (cannot diverge)."""
    import inspect
    from app.services import canonical_material_cost as m
    # Р99 (FIX-MAT-02): the selection keeps officially entered invoices only
    assert m.OFFICIAL_INVOICE_STATUSES == ("Sent", "PartiallyPaid", "Paid", "Overdue")
    for fn in (m.project_invoice_lines, m.project_input_vat):
        src = inspect.getsource(fn)
        assert "project_allocated_invoice_lines(" in src
        assert "invoice_lines.find(" not in src
