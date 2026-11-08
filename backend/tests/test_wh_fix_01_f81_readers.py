"""
WH-FIX-01 — Codex review on #81 @ 625ece1 (comment 6722712113).

F-81-01 — every official aggregate of SUPPLIER (Received) invoices reads the
per-line final allocation (Р45, FG-155 #2): the part of a line allocated
(allocated qty / line qty × the line amount) is in the result; the
unallocated remainder is in no result — it stays visible separately
(„фактури за разпределяне"). No header / whole-subtotal fallback.
  Invoice subtotal 1000 / total 1200, one line 100 × 10, allocated to prj-1
  0 / 60 / 100 → company 0 / 600 / 1000 (ex VAT), project filter the same,
  another project 0. The invoice document itself is unchanged.

F-81-02 — an ISSUED (income) invoice keeps main's semantics (FG-215): its
header project gets the whole total, whatever its lines' allocations say.
  Issued total 500, header prj-1, a line 100 × 5 with 60 to prj-1 → 500
  (625ece1: 300); a line allocated to another project → still 500 on prj-1,
  nothing on the other; the same with embedded lines.

HTTP, PERMISSION_SERVICE_MODE off / shadow / enforce × mongomock and (with
W0_03_REAL_MONGO_URL) a real MongoDB replica set — the PAY-01 harness. The
unrelated payroll source is isolated to an empty result; the invoice queries
and aggregation are the real ones.
"""
from datetime import datetime, timezone

import pytest

from tests.test_pay_01_payment_reversal import (  # noqa: F401  (fixtures)
    ORG_A, backend, hdr, mode,
)
import tests.test_pay_01_payment_reversal as h

TODAY = datetime.now(timezone.utc)
DAY = TODAY.strftime("%Y-%m-%d")
FROM = TODAY.strftime("%Y-%m-01")
INV = "inv-f81"


def run(monkeypatch, backend, mode, scenario):
    import asyncio
    import httpx

    async def go():
        async with h._Dbs(backend) as (op, sysdb):
            await h._bootstrap_indexes(op)
            await h._seed(op, sysdb)
            app = h._app(monkeypatch, op, sysdb, mode)
            from app.routes import (dashboard, reports, revenue_expense, material_smr,
                                    subcontractors, labor_smr)
            for mod in (dashboard, reports, revenue_expense, material_smr, subcontractors, labor_smr):
                monkeypatch.setattr(mod, "db", op)

            async def _no_payroll(*a, **k):
                return []
            monkeypatch.setattr(dashboard, "paid_labor_v3", _no_payroll)
            monkeypatch.setattr(reports, "paid_labor_v3", _no_payroll)
            app.include_router(dashboard.router, prefix="/api")
            app.include_router(reports.router, prefix="/api")
            app.include_router(revenue_expense.router, prefix="/api")
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://f81") as c:
                return await scenario(c, op)
    return asyncio.run(go())


async def _supplier_invoice(op, allocated, *, project="prj-1"):
    await op.invoices.insert_one({
        "id": INV, "org_id": ORG_A, "invoice_no": "R-81", "direction": "Received",
        "kind": "Invoice", "status": "Sent", "issue_date": DAY, "due_date": "2099-12-31",
        "currency": "EUR", "subtotal": 1000.0, "vat_percent": 20, "vat_amount": 200.0,
        "total": 1200.0, "paid_amount": 0, "remaining_amount": 1200.0,
        "supplier_counterparty_id": "cp-81", "counterparty_name": "Доставчик",
        "created_at": TODAY.isoformat()})
    allocs = [{"type": "project", "ref_id": project, "qty": allocated}] if allocated else []
    await op.invoice_lines.insert_one({
        "id": "line-f81", "org_id": ORG_A, "invoice_id": INV, "line_no": 1,
        "description": "Лепило", "unit": "bag", "qty": 100, "unit_price": 10,
        "vat_percent": 20, "line_total_ex_vat": 1000.0, "vat_amount": 200.0,
        "line_total_inc_vat": 1200.0, "allocations": allocs})


EXPECTED = {0: 0.0, 60: 600.0, 100: 1000.0}


# ═══════════════ F-81-01 — finance summary (company + project filter) ═══════════════

@pytest.mark.parametrize("allocated", [0, 60, 100])
def test_f81_01_summary_counts_only_the_allocated_part(monkeypatch, backend, mode, allocated):
    async def scenario(c, op):
        await _supplier_invoice(op, allocated)
        q = f"date_from={FROM}&date_to={DAY}&counterparty_id=cp-81"
        company = (await c.get(f"/api/reports/finance-details/summary?{q}",
                               headers=hdr("acct-a"))).json()
        project = (await c.get(f"/api/reports/finance-details/summary?{q}&project_id=prj-1",
                               headers=hdr("acct-a"))).json()
        other = (await c.get(f"/api/reports/finance-details/summary?{q}&project_id=prj-x",
                             headers=hdr("acct-a"))).json()
        assert company["breakdown"]["expenses_invoices"] == EXPECTED[allocated]
        assert company["totals"]["expenses"] == EXPECTED[allocated]
        assert company["totals"]["net"] == -EXPECTED[allocated]
        assert project["breakdown"]["expenses_invoices"] == EXPECTED[allocated]
        assert other["breakdown"]["expenses_invoices"] == 0.0
        # the remainder is visible separately, never in the result
        assert company["breakdown"]["expenses_invoices_to_allocate"] == 1000.0 - EXPECTED[allocated]
        assert company["counts"]["expenses_invoices_to_allocate_count"] == (0 if allocated == 100 else 1)
        inv = await op.invoices.find_one({"id": INV})
        assert (inv["subtotal"], inv["total"]) == (1000.0, 1200.0)     # the invoice is unchanged
    run(monkeypatch, backend, mode, scenario)


@pytest.mark.parametrize("allocated", [0, 60, 100])
def test_f81_01_company_finance_series_counts_only_the_allocated_part(
        monkeypatch, backend, mode, allocated):
    async def scenario(c, op):
        await _supplier_invoice(op, allocated)
        r = await c.get("/api/reports/company-finance-series?months=1", headers=hdr("acct-a"))
        assert r.status_code == 200, r.text
        [month] = r.json()["months"]
        assert month["breakdown"]["expenses_invoices"] == EXPECTED[allocated]
    run(monkeypatch, backend, mode, scenario)


@pytest.mark.parametrize("allocated", [0, 60, 100])
def test_f81_01_company_finance_summary_and_compare_count_only_the_allocated_part(
        monkeypatch, backend, mode, allocated):
    async def scenario(c, op):
        await _supplier_invoice(op, allocated)
        r = await c.get(f"/api/reports/company-finance-summary?year={TODAY.year}&month={TODAY.month}",
                        headers=hdr("acct-a"))
        assert r.status_code == 200, r.text
        weeks = r.json()["weeks"]
        assert round(sum(w["expenses_invoices"] for w in weeks), 2) == EXPECTED[allocated]
        # the month totals (compare view) read incl. VAT — 60 % of 1200 = 720
        from app.routes import reports
        from app.tenancy.data_access import TenantData
        tot = await reports.get_month_finance_totals(
            TenantData.for_resolved_org(op, ORG_A), TODAY.year, TODAY.month)
        assert tot["expense_breakdown"]["invoices"] == round(EXPECTED[allocated] * 1.2, 2)
    run(monkeypatch, backend, mode, scenario)


@pytest.mark.parametrize("allocated", [0, 60, 100])
def test_f81_01_project_pnl_fallback_reads_the_line_share(monkeypatch, backend, mode, allocated):
    """revenue_expense subcontract fallback: a supplier invoice with EMBEDDED
    lines (finance UI) reaches the project only by its line share — not by its
    header project_id (main: the whole subtotal 1000)."""
    async def scenario(c, op):
        allocs = [{"type": "project", "ref_id": "prj-1", "qty": allocated}] if allocated else []
        await op.invoices.insert_one({
            "id": "inv-f81-emb", "org_id": ORG_A, "invoice_no": "R-81E", "direction": "Received",
            "kind": "Invoice", "status": "Sent", "issue_date": DAY, "due_date": "2099-12-31",
            "subtotal": 1000.0, "vat_percent": 20, "total": 1200.0, "project_id": "prj-1",
            "lines": [{"id": "e1", "description": "Услуга", "qty": 100, "unit_price": 10,
                       "line_total": 1000.0, "allocations": allocs}]})
        r = await c.get("/api/project-profit/prj-1", headers=hdr("owner-a"))
        assert r.status_code == 200, r.text
        assert r.json()["expenses"]["subcontract"] == EXPECTED[allocated]
    run(monkeypatch, backend, mode, scenario)


# ═══════════════ F-81-02 — Issued income keeps main's header semantics ═══════════════

async def _issued(op, *, header="prj-1", line_alloc=None, embedded=False):
    doc = {"id": "iss-f81", "org_id": ORG_A, "invoice_no": "I-81", "direction": "Issued",
           "kind": "Invoice", "status": "Sent", "issue_date": DAY, "due_date": "2099-12-31",
           "subtotal": 500.0, "vat_percent": 0, "total": 500.0, "project_id": header,
           "allocations": [{"type": "project", "ref_id": header}]}
    if embedded:
        doc["lines"] = [{"id": "e1", "description": "СМР", "qty": 100, "unit_price": 5,
                         "line_total": 500.0, "allocations": line_alloc or []}]
    await op.invoices.insert_one(doc)
    if not embedded:
        await op.invoice_lines.insert_one({
            "id": "l-iss-f81", "org_id": ORG_A, "invoice_id": "iss-f81", "qty": 100,
            "unit_price": 5, "line_total_inc_vat": 500.0, "allocations": line_alloc or []})


async def _by_project(c):
    r = await c.get(f"/api/reports/finance-details/by-project?date_from={FROM}&date_to={DAY}",
                    headers=hdr("acct-a"))
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("embedded", [False, True])
@pytest.mark.parametrize("line_project", ["prj-1", "prj-x"])
def test_f81_02_issued_income_is_the_header_total_like_main(monkeypatch, backend, mode,
                                                           embedded, line_project):
    async def scenario(c, op):
        await _issued(op, line_alloc=[{"type": "project", "ref_id": line_project, "qty": 60}],
                      embedded=embedded)
        out = await _by_project(c)
        assert {r["project_id"]: r["total_income"] for r in out["items"]} == {"prj-1": 500.0}
        assert out["to_allocate"] == []
        assert await op.dq_issues.count_documents({}) == 0
    run(monkeypatch, backend, mode, scenario)


def test_f81_02_received_by_project_still_reads_the_line_share(monkeypatch, backend, mode):
    """Control: the supplier side of the same report is unchanged (FG-154 / Р45)."""
    async def scenario(c, op):
        await _supplier_invoice(op, 60)
        out = await _by_project(c)
        assert {r["project_id"]: r["total_expenses"] for r in out["items"]} == {"prj-1": 720.0}
        assert [u["invoice_id"] for u in out["to_allocate"]] == [INV]
    run(monkeypatch, backend, mode, scenario)


# ═══════════ WH81-03 — a SUPPLIER invoice is never project REVENUE ═══════════
# Probe X8 (orchestrator audit): a Received invoice 1000 + VAT with header
# prj-1 was read as revenue 1000 / invoiced 1200 by the project P&L readers
# (no direction filter). Revenue / "invoiced" come from Issued invoices only;
# the supplier cost stays in these readers through materials / subcontracts.

OWNER = {"id": "owner-a", "org_id": ORG_A, "role": "Owner", "email": "o@a"}


@pytest.mark.parametrize("with_sale", [False, True])
def test_wh81_03_supplier_invoice_is_not_project_revenue(monkeypatch, backend, mode, with_sale):
    async def scenario(c, op):
        from app.services import (project_pnl, centralized_reports, project_financial_results,
                                  cashflow_forecast)
        from app.routes import clients, projects
        for mod in (project_pnl, centralized_reports, project_financial_results,
                    cashflow_forecast, clients, projects):
            monkeypatch.setattr(mod, "db", op)
        now = TODAY.isoformat()
        await op.invoices.insert_one({
            "id": "inv-x8", "org_id": ORG_A, "invoice_no": "R-X8", "direction": "Received",
            "kind": "Invoice", "status": "Sent", "issue_date": DAY, "due_date": "2099-12-31",
            "subtotal": 1000.0, "vat_amount": 200.0, "total": 1200.0, "paid_amount": 0,
            "remaining_amount": 1200.0, "project_id": "prj-1", "created_at": now})
        sale = 0.0
        if with_sale:                       # control: a sale on the same project is revenue
            sale = 500.0
            await op.invoices.insert_one({
                "id": "iss-x8", "org_id": ORG_A, "invoice_no": "I-X8", "direction": "Issued",
                "kind": "Invoice", "status": "Sent", "issue_date": DAY, "due_date": "2099-12-31",
                "subtotal": 500.0, "vat_amount": 100.0, "total": 600.0, "paid_amount": 0,
                "remaining_amount": 600.0, "project_id": "prj-1", "created_at": now})
        await op.projects.update_one({"id": "prj-1"}, {"$set": {"owner_id": "cl-x8"}})
        await op.clients.insert_one({"id": "cl-x8", "org_id": ORG_A, "name": "Клиент"})

        pnl = await project_pnl.compute_project_pnl(ORG_A, "prj-1")
        assert pnl["revenue"]["invoiced_net"] == sale
        assert pnl["revenue"]["invoiced_total"] == sale * 1.2
        trend = await project_pnl.compute_pnl_trend(ORG_A, "prj-1", 1)
        assert sum(m["revenue"] for m in trend) == sale
        cent = await centralized_reports.build_centralized_reports(ORG_A, "prj-1")
        assert cent["finance"]["total_revenue"] == sale
        fin = await project_financial_results.compute_financial_results(ORG_A, "prj-1")
        assert fin["cash"]["invoices"]["invoiced"] == sale * 1.2
        flow = await cashflow_forecast.build_cashflow_forecast(ORG_A, 30)
        ids = [i["source_id"] for i in flow["incoming"] + flow["overdue"]]
        assert "inv-x8" not in ids and ("iss-x8" in ids) == with_sale
        summ = await clients.get_client_summary("cl-x8", user=OWNER)
        assert summ["totals"]["total_revenue"] == sale * 1.2
        await op.projects.insert_one({"id": "prj-1-c", "org_id": ORG_A, "code": "C", "name": "C",
                                      "parent_project_id": "prj-1", "status": "Active"})
        agg = await projects.get_project_aggregate("prj-1", user=OWNER)
        assert agg["invoices"]["own"]["invoiced"] == sale * 1.2
    run(monkeypatch, backend, mode, scenario)
