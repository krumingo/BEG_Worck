"""
FIX-MAT-03 — finding F1-3: a supplier invoice made in the FINANCE UI
(``POST /finance/invoices`` with ``lines[]``) keeps its lines EMBEDDED in
``invoices.lines[]`` (FG-200); Path B (project material cost) and the project
input VAT read only the ``invoice_lines`` collection, so an 85 € line
allocated to a project gave the project P&L material cost +0 while the
dashboards / company reports (``received_line_allocations``) already showed it.

Rule (CLAUDE.md §2.12 / §7, FLOW-043 D-04, Р99): a supplier invoice line
allocated to a project is project material cost ONCE, when its invoice is
officially entered. ONE precedence per invoice (FG-200,
``invoice_allocation.invoices_with_line_docs``): an invoice with
``invoice_lines`` documents is read from them only; without them, from its
embedded lines. The one Path B selection
(``canonical_material_cost.project_allocated_invoice_lines``) now applies it.

Cases (all through the real finance endpoints):
  1. finance-UI invoice, inline 85 € line → project: Draft 0 (Р99); after the
     real send +85 / VAT 17 once on every project screen and dashboard;
  2. the line amount is updated (``PUT /finance/invoices/{id}/lines``) → the
     cost follows, once;
  3. the line is removed (another line to another project stays) → 0 here,
     the other project keeps its own;
  4. cancel → 0;
  5. an invoice whose lines were written through the ``invoice_lines`` API
     (embedded copy for send, also allocated to the project) → once;
     a later ``invoice_lines`` document for a finance-UI invoice (e.g. a
     backfill) → still once;
  6. an Issued (client) invoice with ``lines[].project_id`` is no cost;
  7. tenant isolation (same project / invoice ids in ORG_B);
  8. revenue_expense: the line is material, not also the subcontract fallback.

    W0_03_REAL_MONGO_URL=... PYTHONPATH=. pytest \
        tests/test_fix_mat_03_one_invoice_lines.py -q --noconftest -p no:cacheprovider
"""
import asyncio
import sys
import uuid
from datetime import datetime, timezone

import pytest

from tests.test_pay_01_payment_reversal import (  # noqa: F401  (fixtures)
    ORG_A, ORG_B, backend, hdr, mode,
)
import tests.test_pay_01_payment_reversal as h
from tests.test_fix_mat_02_official_invoices_only import _dashboards, _project_screens

PRJ = "prj-1"
OTHER = "prj-a"
TODAY = datetime.now(timezone.utc)
DAY = TODAY.strftime("%Y-%m-%d")
EX, VAT = 85.0, 17.0
INC = EX + VAT


class _Dbs(h._Dbs):
    def __init__(self, backend):
        super().__init__(backend)
        tag = uuid.uuid4().hex[:10]
        self.names = ("fixtest_mat3_op_" + tag, "fixtest_mat3_sys_" + tag)


def run(monkeypatch, backend, mode, scenario):
    import httpx

    async def go():
        async with _Dbs(backend) as (op, sysdb):
            await h._bootstrap_indexes(op)
            await h._seed(op, sysdb)
            app = h._app(monkeypatch, op, sysdb, mode)
            from app.routes import (dashboard, reports, revenue_expense, full_cost,
                                    financial_results, project_pnl as r_pnl, invoice_lines)
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
                                         base_url="http://fixmat03") as c:
                return await scenario(c, op)
    return asyncio.run(go())


def _line(price=EX, project=PRJ, desc="Лепило"):
    out = {"description": desc, "unit": "бр", "qty": 1, "unit_price": price}
    if project:
        out["project_id"] = project
    return out


async def _create(c, lines, who="acct-a", direction="Received"):
    r = await c.post("/api/finance/invoices", headers=hdr(who), json={
        "direction": direction, "kind": "Invoice", "invoice_no": "F3-" + uuid.uuid4().hex[:8],
        "counterparty_name": "Доставчик", "issue_date": DAY, "due_date": "2099-12-31",
        "currency": "EUR", "vat_percent": 20, "lines": lines})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "Draft"
    return r.json()["id"]


async def _send(c, inv_id, who="acct-a"):
    r = await c.post(f"/api/finance/invoices/{inv_id}/send", headers=hdr(who))
    assert r.status_code == 200, r.text
    assert r.json()["status"] in ("Sent", "Overdue")


async def _put_lines(c, inv_id, lines):
    r = await c.put(f"/api/finance/invoices/{inv_id}/lines", headers=hdr("acct-a"),
                    json={"lines": lines})
    assert r.status_code == 200, r.text
    return r.json()


async def _cancel(c, inv_id):
    r = await c.post(f"/api/finance/invoices/{inv_id}/cancel", headers=hdr("acct-a"))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "Cancelled"


def _project(ex, vat):
    return {"helper_path_b": ex, "helper_vat": vat, "pnl_material": ex, "pnl_input_vat": vat,
            "financial_results_materials": ex, "full_cost_material": ex,
            "project_profit_material": ex}


# Dashboards / company reports (already read embedded lines before the fix —
# they must stay ONE count). The invoice-lines listing is an `invoice_lines`
# API listing (not a cost reader) and is not compared for embedded lines.
DASH_KEYS = ("by_project_row_inc", "summary_company_ex", "summary_project_ex", "series_ex",
             "weekly_ex", "month_totals_inc")


def _dash(ex):
    inc = round(ex * 1.2, 2)
    return {"by_project_row_inc": inc, "summary_company_ex": ex, "summary_project_ex": ex,
            "series_ex": ex, "weekly_ex": ex, "month_totals_inc": inc}


async def _dash_now(c, who="acct-a"):
    d = await _dashboards(c, who)
    return {k: round(d[k], 2) for k in DASH_KEYS}


async def _profit(c, project=PRJ):
    r = await c.get(f"/api/project-profit/{project}", headers=hdr("acct-a"))
    assert r.status_code == 200, r.text
    e = r.json()["expenses"]
    return {"material": e["material"], "subcontract": e["subcontract"], "total": e["total"]}


def test_01_finance_ui_line_draft_zero_then_sent_counts_once(monkeypatch, backend, mode):
    async def scenario(c, op):
        inv = await _create(c, [_line()])
        assert await op.invoice_lines.count_documents({}) == 0      # embedded only
        assert await _project_screens(c) == _project(0, 0)           # Draft (Р99)
        assert await _dash_now(c) == _dash(0)
        await _send(c, inv)
        # a6f2518f: helper / P&L / results / full cost / profit material = 0, VAT 0
        assert await _project_screens(c) == _project(EX, VAT)
        assert await _dash_now(c) == _dash(EX)
        from app.services.canonical_material_cost import project_material_cost
        from app.tenancy.data_access import TenantData
        import app.services.project_pnl as pnl_mod
        cost = await project_material_cost(TenantData.for_resolved_org(pnl_mod.db, ORG_A),
                                           ORG_A, PRJ)
        inv_lines = [ln for ln in cost["lines"] if ln["source"] == "invoice"]
        assert len(inv_lines) == 1 and inv_lines[0]["value"] == EX     # one lot, once
    run(monkeypatch, backend, mode, scenario)


def test_02_update_line_amount_cost_follows_once(monkeypatch, backend, mode):
    async def scenario(c, op):
        inv = await _create(c, [_line()])
        await _send(c, inv)
        assert await _project_screens(c) == _project(EX, VAT)
        await _put_lines(c, inv, [_line(price=120.0)])
        assert await _project_screens(c) == _project(120.0, 24.0)
        assert await _dash_now(c) == _dash(120.0)
        await _put_lines(c, inv, [_line(price=EX)])
        assert await _project_screens(c) == _project(EX, VAT)
    run(monkeypatch, backend, mode, scenario)


def test_03_remove_line_is_zero_other_project_keeps_its_own(monkeypatch, backend, mode):
    async def scenario(c, op):
        inv = await _create(c, [_line(), _line(price=40.0, project=OTHER, desc="Шпакловка")])
        await _send(c, inv)
        assert await _project_screens(c) == _project(EX, VAT)
        await _put_lines(c, inv, [_line(price=40.0, project=OTHER, desc="Шпакловка")])
        assert await _project_screens(c) == _project(0, 0)
        from app.services.canonical_material_cost import project_input_vat, project_material_cost
        from app.tenancy.data_access import TenantData
        import app.services.project_pnl as pnl_mod
        t = TenantData.for_resolved_org(pnl_mod.db, ORG_A)
        assert (await project_material_cost(t, ORG_A, OTHER))["invoice_cost"] == 40.0
        assert await project_input_vat(t, ORG_A, OTHER) == 8.0
    run(monkeypatch, backend, mode, scenario)


def test_04_cancel_is_zero(monkeypatch, backend, mode):
    async def scenario(c, op):
        inv = await _create(c, [_line()])
        await _send(c, inv)
        assert await _project_screens(c) == _project(EX, VAT)
        await _cancel(c, inv)
        assert await _project_screens(c) == _project(0, 0)
        assert await _dash_now(c) == _dash(0)
    run(monkeypatch, backend, mode, scenario)


def test_05_invoice_lines_api_path_counts_once(monkeypatch, backend, mode):
    """Both representations exist (embedded copy so the send endpoint accepts
    it, also allocated to the project): the invoice_lines documents win."""
    async def scenario(c, op):
        inv = await _create(c, [_line()])
        r = await c.post("/api/invoice-lines", headers=hdr("acct-a"), json={
            "invoice_id": inv, "line_no": 1, "description": "Лепило", "unit": "бр",
            "qty": 1, "unit_price": EX, "vat_percent": 20,
            "allocations": [{"type": "project", "ref_id": PRJ, "qty": 1}]})
        assert r.status_code == 201, r.text
        assert await _project_screens(c) == _project(0, 0)           # still Draft
        await _send(c, inv)
        assert await _project_screens(c) == _project(EX, VAT)        # not 170 / 34
        assert await _dash_now(c) == _dash(EX)
    run(monkeypatch, backend, mode, scenario)


def test_06_later_invoice_lines_document_does_not_double_count(monkeypatch, backend, mode):
    """A later backfill that writes the finance-UI line as an invoice_lines
    document: the embedded copy drops out, the line counts once."""
    async def scenario(c, op):
        inv = await _create(c, [_line()])
        await _send(c, inv)
        emb = (await op.invoices.find_one({"id": inv}))["lines"][0]
        await op.invoice_lines.insert_one({
            "id": emb["id"], "org_id": ORG_A, "invoice_id": inv, "line_no": 0,
            "description": "Лепило", "unit": "бр", "qty": 1, "unit_price": EX,
            "vat_percent": 20, "line_total_ex_vat": EX, "vat_amount": VAT,
            "line_total_inc_vat": INC, "created_at": TODAY.isoformat(),
            "allocations": [{"type": "project", "ref_id": PRJ, "qty": 1}]})
        assert await _project_screens(c) == _project(EX, VAT)
        assert await _dash_now(c) == _dash(EX)
    run(monkeypatch, backend, mode, scenario)


def test_07_issued_invoice_line_is_no_cost(monkeypatch, backend, mode):
    async def scenario(c, op):
        inv = await _create(c, [_line()], direction="Issued")
        await _send(c, inv)
        p = await _project_screens(c)
        assert (p["helper_path_b"], p["helper_vat"], p["pnl_material"],
                p["pnl_input_vat"]) == (0, 0, 0, 0)
    run(monkeypatch, backend, mode, scenario)


def test_08_tenant_isolation(monkeypatch, backend, mode):
    async def scenario(c, op):
        # ORG_B: an officially entered supplier invoice whose embedded line names
        # the id string "prj-1" (ORG_A's project) — ORG_A must not see it.
        await op.invoices.insert_one({
            "id": "inv-b-emb", "org_id": ORG_B, "invoice_no": "B-1", "direction": "Received",
            "kind": "Invoice", "status": "Sent", "issue_date": DAY, "due_date": "2099-12-31",
            "currency": "EUR", "vat_percent": 20, "subtotal": EX, "vat_amount": VAT,
            "total": INC, "paid_amount": 0, "remaining_amount": INC,
            "lines": [{"id": "emb-b", "description": "Лепило", "unit": "бр", "qty": 1,
                       "unit_price": EX, "line_total": EX, "project_id": PRJ}],
            "created_at": TODAY.isoformat()})
        assert await _project_screens(c) == _project(0, 0)
        inv = await _create(c, [_line()])
        await _send(c, inv)
        # ORG_B's invoice_lines document with ORG_A's invoice id does not hide
        # ORG_A's embedded line (the precedence is per tenant)
        await op.invoice_lines.insert_one({
            "id": "line-b-x", "org_id": ORG_B, "invoice_id": inv, "qty": 1,
            "line_total_ex_vat": 999.0, "vat_amount": 1.0,
            "allocations": [{"type": "warehouse", "ref_id": "wh-b", "qty": 1}]})
        assert await _project_screens(c) == _project(EX, VAT)
        from app.services.canonical_material_cost import project_input_vat, project_material_cost
        from app.tenancy.data_access import TenantData
        import app.services.project_pnl as pnl_mod
        tb = TenantData.for_resolved_org(pnl_mod.db, ORG_B)
        assert (await project_material_cost(tb, ORG_B, PRJ))["invoice_cost"] == EX
        assert await project_input_vat(tb, ORG_B, PRJ) == VAT
    run(monkeypatch, backend, mode, scenario)


def test_09_revenue_expense_counts_the_line_once(monkeypatch, backend, mode):
    """The project-profit screen: the line is material cost and is not also
    read by the received-invoice subcontract fallback."""
    async def scenario(c, op):
        inv = await _create(c, [_line()])
        await _send(c, inv)
        p = await _profit(c)
        assert (p["material"], p["subcontract"]) == (EX, 0)
        assert p["total"] == EX
    run(monkeypatch, backend, mode, scenario)


def test_10_one_precedence_rule():
    import inspect
    from app.services import canonical_material_cost as m
    src = inspect.getsource(m.project_allocated_invoice_lines)
    assert "project_embedded_invoice_lines(" in src
    assert "invoices_with_line_docs(" in inspect.getsource(m.project_embedded_invoice_lines)
    assert '"direction": "Received"' in inspect.getsource(m.project_embedded_invoice_lines)
    from app.routes import revenue_expense
    assert "project_invoice_lines(" in inspect.getsource(revenue_expense)
