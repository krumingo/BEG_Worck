"""CLAUDE AUDIT probe — #81 WH-FIX-01 @ 20b1663 (F-81-01 reader sweep). Copy into backend/tests/.
  X8  a SUPPLIER (Received) invoice with header project_id = prj-1 and its only line allocated
      0 / to another project: the project readers that are not in the F-81 fix
      (project_pnl.compute_project_pnl + compute_pnl_trend, centralized_reports
      .build_centralized_reports, project_financial_results.compute_financial_results)
      must not count it as project REVENUE / invoiced (Р45: a supplier invoice reaches a result
      only by its lines' allocation, and never as income).
"""
import pytest

from tests.test_wh_fix_01_f81_readers import (  # noqa: F401
    INV, ORG_A, _supplier_invoice, backend, mode, run)


@pytest.mark.parametrize("where", ["unallocated", "other-project"])
def test_x8_supplier_invoice_is_not_project_revenue(monkeypatch, backend, mode, where):
    async def scenario(c, op):
        from app.services import project_pnl, centralized_reports, project_financial_results
        for mod in (project_pnl, centralized_reports, project_financial_results):
            monkeypatch.setattr(mod, "db", op, raising=False)
        await _supplier_invoice(op, 0 if where == "unallocated" else 100,
                                project="prj-1" if where == "unallocated" else "prj-x")
        await op.invoices.update_one({"id": INV}, {"$set": {"project_id": "prj-1"}})   # header project
        out = {}
        try:
            p = await project_pnl.compute_project_pnl(ORG_A, "prj-1")
            out["pnl.revenue"] = p.get("revenue", p).get("total_revenue") if isinstance(p.get("revenue"), dict) else p.get("total_revenue")
            out["pnl.invoiced"] = (p.get("revenue") or {}).get("invoiced_total") if isinstance(p.get("revenue"), dict) else p.get("invoiced_total")
        except Exception as e:                       # noqa: BLE001
            out["pnl"] = "ERR %r" % e
        try:
            t = await project_pnl.compute_pnl_trend(ORG_A, "prj-1", months=2)
            out["trend.revenue"] = sum(m["revenue"] for m in t)
        except Exception as e:                       # noqa: BLE001
            out["trend"] = "ERR %r" % e
        try:
            cr = await centralized_reports.build_centralized_reports(ORG_A, "prj-1")
            out["central.revenue"] = (cr.get("finance") or {}).get("total_revenue")
        except Exception as e:                       # noqa: BLE001
            out["central"] = "ERR %r" % e
        try:
            fr = await project_financial_results.compute_financial_results(ORG_A, "prj-1")
            out["finres.invoiced"] = (fr.get("cash") or fr.get("cash_result") or {}).get("total_invoiced", fr.get("total_invoiced"))
        except Exception as e:                       # noqa: BLE001
            out["finres"] = "ERR %r" % e
        print("X8 %s/%s/%s: %s" % (backend, mode, where, out))
        bad = {k: v for k, v in out.items() if isinstance(v, (int, float)) and v}
        assert not bad, "supplier invoice counted as project revenue/invoiced: %s" % bad
    run(monkeypatch, backend, mode, scenario)
