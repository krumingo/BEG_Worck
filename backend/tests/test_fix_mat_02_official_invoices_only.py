"""
FIX-MAT-02 — Р99 (Крум, 16.11.2026): a supplier invoice becomes project cost
when it is OFFICIALLY ENTERED. A Draft and a Cancelled invoice are not
material cost and not project VAT. Every screen (P&L, financial result, full
cost, dashboards, company reports) uses the same rule, so they show one number.

The rule lives in ``app.services.official_invoice`` (OFFICIAL_INVOICE_STATUSES
= INVOICE_STATUSES minus Draft / Cancelled = Sent, PartiallyPaid, Paid,
Overdue). c0ee4613 (FIX-MAT-01) excluded Cancelled only in the project Path B /
input VAT; Draft counted there, and every company report / dashboard read
Draft AND Cancelled supplier invoices.

Fixture: one supplier invoice 110 + 22 VAT (= 132), one embedded line (so the
real send endpoint accepts it) and one ``invoice_lines`` line allocated wholly
to prj-1, supplier cp-99, issued today.

Cases:
  1. Draft → 0 everywhere (project P&L material / input VAT, helper Path B,
     financial result, full cost, project profit, dashboard by-project row,
     finance-details, company summary / series / month totals, by-counterparty,
     top counterparties, turnover, invoice-lines by-project total); the real
     ``POST /finance/invoices/{id}/send`` → Sent → counted ONCE, the same
     number on every screen;
  2. the real cancel endpoint → 0 everywhere again; the line is unchanged;
  3. a Cancelled invoice inserted as such → 0 everywhere;
  4. a line whose invoice is missing (e.g. left by a deleted Draft) → 0;
  5. tenant isolation: ORG_B's officially entered invoice with the SAME id
     does not make ORG_A's Draft line count; ORG_B sees its own;
  6. the invoice-lines by-project listing keeps the Draft row visible (with
     its status) but out of the totals;
  7. static: one rule, used by the readers.

PAY-01 / F-81 harness (HTTP, PERMISSION_SERVICE_MODE off / shadow / enforce)
on mongomock and, with W0_03_REAL_MONGO_URL (a disposable LOCAL MongoDB), on a
real replica set.

    W0_03_REAL_MONGO_URL=... PYTHONPATH=. pytest \
        tests/test_fix_mat_02_official_invoices_only.py -q --noconftest -p no:cacheprovider
"""
import asyncio
import sys
from datetime import datetime, timezone

import pytest

from tests.test_pay_01_payment_reversal import (  # noqa: F401  (fixtures)
    ORG_A, ORG_B, backend, hdr, mode,
)
import tests.test_pay_01_payment_reversal as h

PRJ = "prj-1"
TODAY = datetime.now(timezone.utc)
DAY = TODAY.strftime("%Y-%m-%d")
FROM = TODAY.strftime("%Y-%m-01")
CP = "cp-99"
INV = "inv-mat2"
EX, VAT = 110.0, 22.0
INC = EX + VAT


def run(monkeypatch, backend, mode, scenario):
    import httpx

    async def go():
        async with h._Dbs(backend) as (op, sysdb):
            await h._bootstrap_indexes(op)
            await h._seed(op, sysdb)
            app = h._app(monkeypatch, op, sysdb, mode)
            from app.routes import (dashboard, reports, revenue_expense, material_smr,
                                    subcontractors, labor_smr, full_cost, financial_results,
                                    project_pnl as r_pnl, invoice_lines)
            for name, mod in list(sys.modules.items()):
                if name.startswith("app.") and getattr(mod, "db", None) not in (None, op):
                    monkeypatch.setattr(mod, "db", op)

            async def _no_payroll(*a, **k):
                return []
            monkeypatch.setattr(dashboard, "paid_labor_v3", _no_payroll)
            monkeypatch.setattr(reports, "paid_labor_v3", _no_payroll)
            for r in (dashboard, reports, revenue_expense, full_cost, financial_results,
                      r_pnl, invoice_lines):
                app.include_router(r.router, prefix="/api")
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://fixmat02") as c:
                return await scenario(c, op)
    return asyncio.run(go())


async def _supplier_invoice(op, *, org=ORG_A, status="Draft", inv_id=INV, project=PRJ,
                            with_invoice=True):
    if with_invoice:
        await op.invoices.insert_one({
            "id": inv_id, "org_id": org, "invoice_no": "R-" + inv_id, "direction": "Received",
            "kind": "Invoice", "status": status, "issue_date": DAY, "due_date": "2099-12-31",
            "currency": "EUR", "subtotal": EX, "vat_percent": 20, "vat_amount": VAT,
            "total": INC, "paid_amount": 0, "remaining_amount": INC,
            "supplier_counterparty_id": CP, "counterparty_name": "Доставчик",
            "lines": [{"id": "emb-" + inv_id, "description": "Лепило", "unit": "бр", "qty": 1,
                       "unit_price": EX, "line_total": EX}],
            "created_at": TODAY.isoformat()})
    line = {
        "id": "line-" + inv_id + "-" + org, "org_id": org, "invoice_id": inv_id,
        "line_no": 1, "description": "Лепило", "unit": "бр", "qty": 1, "unit_price": EX,
        "vat_percent": 20, "line_total_ex_vat": EX, "vat_amount": VAT,
        "line_total_inc_vat": INC, "created_at": TODAY.isoformat(),
        "allocations": [{"type": "project", "ref_id": project, "qty": 1}]}
    await op.invoice_lines.insert_one(line)
    return line["id"]


async def _get(c, url, who="acct-a"):
    r = await c.get(url, headers=hdr(who))
    assert r.status_code == 200, (url, r.status_code, r.text)
    return r.json()


async def _project_screens(c, org=ORG_A, who="acct-a"):
    """Project material cost (ex VAT) and input VAT on every project screen."""
    from app.services.canonical_material_cost import project_input_vat, project_material_cost
    from app.tenancy.data_access import TenantData
    import app.services.project_pnl as pnl_mod
    tenant = TenantData.for_resolved_org(pnl_mod.db, org)
    helper = await project_material_cost(tenant, org, PRJ)
    pnl = await _get(c, f"/api/projects/{PRJ}/pnl", who)
    fin = await _get(c, f"/api/projects/{PRJ}/financial-results", who)
    full = await _get(c, f"/api/project-net-profit/{PRJ}", who)
    profit = await _get(c, f"/api/project-profit/{PRJ}", who)
    return {
        "helper_path_b": helper["invoice_cost"],
        "helper_vat": await project_input_vat(tenant, org, PRJ),
        "pnl_material": pnl["expense"]["material_cost"],
        "pnl_input_vat": pnl["vat"]["input_vat"],
        "financial_results_materials": fin["operating"]["materials"],
        "full_cost_material": round(full["costs"]["material"] + full["costs"]["waste"], 2),
        "project_profit_material": profit["expenses"]["material"],
    }


async def _dashboards(c, who="acct-a"):
    """Supplier-invoice expense on every dashboard / company report."""
    from app.routes import reports
    from app.tenancy.data_access import TenantData
    import app.services.project_pnl as pnl_mod
    q = f"date_from={FROM}&date_to={DAY}"
    by_project = await _get(c, f"/api/reports/finance-details/by-project?{q}", who)
    company = await _get(c, f"/api/reports/finance-details/summary?{q}", who)
    proj_f = await _get(c, f"/api/reports/finance-details/summary?{q}&project_id={PRJ}", who)
    series = await _get(c, "/api/reports/company-finance-series?months=1", who)
    weeks = await _get(c, f"/api/reports/company-finance-summary?year={TODAY.year}"
                          f"&month={TODAY.month}", who)
    org = h.USERS[who][0]
    month = await reports.get_month_finance_totals(
        TenantData.for_resolved_org(pnl_mod.db, org), TODAY.year, TODAY.month)
    by_cp = await _get(c, f"/api/reports/finance-details/by-counterparty?{q}", who)
    top = await _get(c, f"/api/reports/finance-details/top-counterparties?{q}&direction=expense",
                     who)
    turnover = await _get(c, f"/api/reports/turnover-by-counterparty?{q}&type=purchases", who)
    turnover_all = await _get(c, f"/api/reports/turnover-by-counterparty?{q}&type=all", who)
    turnover_sales = await _get(c, f"/api/reports/turnover-by-counterparty?{q}&type=sales", who)
    lines = await _get(c, f"/api/invoice-lines/by-project/{PRJ}", who)
    return {
        "by_project_row_inc": {r["project_id"]: r["total_expenses"]
                               for r in by_project["items"]}.get(PRJ, 0.0),
        "summary_company_ex": company["breakdown"]["expenses_invoices"],
        "summary_project_ex": proj_f["breakdown"]["expenses_invoices"],
        "series_ex": series["months"][0]["breakdown"]["expenses_invoices"],
        "weekly_ex": round(sum(w["expenses_invoices"] for w in weeks["weeks"]), 2),
        "month_totals_inc": round(month["expense_breakdown"]["invoices"], 2),
        "by_counterparty_inc": sum(r["total_expenses"] for r in by_cp["items"]
                                   if r["counterparty_id"] == CP),
        "top_counterparty_inc": sum(r["total"] for r in top["items"]
                                    if r["counterparty_id"] == CP),
        "turnover_purchases_ex": turnover["grand_totals"]["total_subtotal"],
        # type=all minus the (unchanged) Issued side = the supplier side
        "turnover_all_ex": round(turnover_all["grand_totals"]["total_subtotal"]
                                 - turnover_sales["grand_totals"]["total_subtotal"], 2),
        "invoice_lines_by_project_ex": lines["total_ex_vat"],
        "_lines": lines["allocations"],
    }


ZERO_PROJECT = {k: 0 for k in ("helper_path_b", "helper_vat", "pnl_material", "pnl_input_vat",
                               "financial_results_materials", "full_cost_material",
                               "project_profit_material")}
ONCE_PROJECT = {"helper_path_b": EX, "helper_vat": VAT, "pnl_material": EX, "pnl_input_vat": VAT,
                "financial_results_materials": EX, "full_cost_material": EX,
                "project_profit_material": EX}
ZERO_DASH = {k: 0 for k in ("by_project_row_inc", "summary_company_ex", "summary_project_ex",
                            "series_ex", "weekly_ex", "month_totals_inc", "by_counterparty_inc",
                            "top_counterparty_inc", "turnover_purchases_ex", "turnover_all_ex",
                            "invoice_lines_by_project_ex")}
# ex VAT readers show 110, incl.-VAT readers 132 (= the P&L material 110 + input VAT 22)
ONCE_DASH = {"by_project_row_inc": INC, "summary_company_ex": EX, "summary_project_ex": EX,
             "series_ex": EX, "weekly_ex": EX, "month_totals_inc": INC,
             "by_counterparty_inc": INC, "top_counterparty_inc": INC,
             "turnover_purchases_ex": EX, "turnover_all_ex": EX,
             "invoice_lines_by_project_ex": EX}


def _strip(d):
    return {k: v for k, v in d.items() if not k.startswith("_")}


async def _send(c, inv_id=INV):
    r = await c.post(f"/api/finance/invoices/{inv_id}/send", headers=hdr("acct-a"))
    assert r.status_code == 200, r.text
    assert r.json()["status"] in ("Sent", "Overdue")


async def _cancel(c, inv_id=INV):
    r = await c.post(f"/api/finance/invoices/{inv_id}/cancel", headers=hdr("acct-a"))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "Cancelled"


def test_01_draft_is_no_cost_then_send_counts_once_everywhere(monkeypatch, backend, mode):
    async def scenario(c, op):
        await _supplier_invoice(op, status="Draft")
        # c0ee4613: project 110 / 22 everywhere, dashboards 110 / 132 — Draft counted
        assert await _project_screens(c) == ZERO_PROJECT
        assert _strip(await _dashboards(c)) == ZERO_DASH
        await _send(c)                                   # the real Draft → Sent transition
        assert await _project_screens(c) == ONCE_PROJECT
        assert _strip(await _dashboards(c)) == ONCE_DASH
    run(monkeypatch, backend, mode, scenario)


def test_02_cancel_after_send_removes_it_everywhere(monkeypatch, backend, mode):
    async def scenario(c, op):
        line_id = await _supplier_invoice(op, status="Draft")
        await _send(c)
        assert await _project_screens(c) == ONCE_PROJECT
        before = await op.invoice_lines.find_one({"id": line_id}, {"_id": 0})
        await _cancel(c)
        assert await _project_screens(c) == ZERO_PROJECT
        # c0ee4613: the company reports / dashboards still counted it (110 / 132)
        assert _strip(await _dashboards(c)) == ZERO_DASH
        assert await op.invoice_lines.find_one({"id": line_id}, {"_id": 0}) == before
    run(monkeypatch, backend, mode, scenario)


@pytest.mark.parametrize("status", ["Cancelled", "Draft"])
def test_03_not_official_status_is_zero_everywhere(monkeypatch, backend, mode, status):
    async def scenario(c, op):
        await _supplier_invoice(op, status=status)
        assert await _project_screens(c) == ZERO_PROJECT
        assert _strip(await _dashboards(c)) == ZERO_DASH
    run(monkeypatch, backend, mode, scenario)


@pytest.mark.parametrize("status", ["Sent", "PartiallyPaid", "Paid", "Overdue"])
def test_04_every_official_status_counts_once(monkeypatch, backend, mode, status):
    async def scenario(c, op):
        await _supplier_invoice(op, status=status)
        assert await _project_screens(c) == ONCE_PROJECT
        assert _strip(await _dashboards(c)) == ONCE_DASH
    run(monkeypatch, backend, mode, scenario)


def test_05_line_without_invoice_is_no_cost(monkeypatch, backend, mode):
    """A line whose invoice is missing in the tenant (e.g. a deleted Draft's
    leftover line) is not officially entered."""
    async def scenario(c, op):
        await _supplier_invoice(op, with_invoice=False)
        assert await _project_screens(c) == ZERO_PROJECT
    run(monkeypatch, backend, mode, scenario)


def test_06_tenant_isolation(monkeypatch, backend, mode):
    async def scenario(c, op):
        # same invoice id: ORG_A Draft, ORG_B Sent (its own line on its prj-1)
        await _supplier_invoice(op, org=ORG_A, status="Draft")
        await _supplier_invoice(op, org=ORG_B, status="Sent")
        assert await _project_screens(c) == ZERO_PROJECT          # ORG_A
        from app.services.canonical_material_cost import project_input_vat, project_material_cost
        from app.tenancy.data_access import TenantData
        import app.services.project_pnl as pnl_mod
        tb = TenantData.for_resolved_org(pnl_mod.db, ORG_B)
        assert (await project_material_cost(tb, ORG_B, PRJ))["invoice_cost"] == EX
        assert await project_input_vat(tb, ORG_B, PRJ) == VAT
        # ORG_B cannot send ORG_A's Draft (it hits its own Sent invoice or nothing)
        r = await c.post(f"/api/finance/invoices/{INV}/send", headers=hdr("admin-b"))
        assert r.status_code in (400, 403, 404, 409), r.text
        assert (await op.invoices.find_one({"id": INV, "org_id": ORG_A}))["status"] == "Draft"
        assert await _project_screens(c) == ZERO_PROJECT
    run(monkeypatch, backend, mode, scenario)


def test_07_invoice_lines_listing_keeps_draft_row_out_of_totals(monkeypatch, backend, mode):
    async def scenario(c, op):
        await _supplier_invoice(op, status="Draft")
        await _supplier_invoice(op, status="Sent", inv_id="inv-mat2-sent")
        d = await _dashboards(c)
        rows = {r["invoice_id"]: r for r in d["_lines"]}
        assert set(rows) == {INV, "inv-mat2-sent"}             # both rows stay visible
        assert (rows[INV]["invoice_status"], rows[INV]["in_result"]) == ("Draft", False)
        assert (rows["inv-mat2-sent"]["invoice_status"], rows["inv-mat2-sent"]["in_result"]) \
            == ("Sent", True)
        assert d["invoice_lines_by_project_ex"] == EX           # only the Sent one
        assert await _project_screens(c) == ONCE_PROJECT
    run(monkeypatch, backend, mode, scenario)


def test_08_one_rule_used_by_the_readers():
    import inspect
    from app.models.finance import INVOICE_STATUSES
    from app.services import official_invoice as r99
    assert r99.NOT_OFFICIAL_INVOICE_STATUSES == ("Draft", "Cancelled")
    assert r99.OFFICIAL_INVOICE_STATUSES == ("Sent", "PartiallyPaid", "Paid", "Overdue")
    assert set(r99.OFFICIAL_INVOICE_STATUSES) | set(r99.NOT_OFFICIAL_INVOICE_STATUSES) \
        == set(INVOICE_STATUSES)
    from app.services import canonical_material_cost as m, invoice_allocation as ia
    assert "official_invoice_ids(" in inspect.getsource(m.project_allocated_invoice_lines)
    assert "official_invoice_ids(" in inspect.getsource(ia.received_line_allocations)
    from app.routes import revenue_expense
    src = inspect.getsource(revenue_expense)
    assert '"direction": "Received", "status": official_status_query()' in src
