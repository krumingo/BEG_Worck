"""
5C-C26j — Р35 (Крум 07.11.2026, FG-71): per project and article, the purchase
price history — every purchase with its unit price, supplier and date — and a
FLAG when the same article was bought from the same supplier at different
unit prices, plus a "best price" summary.

Read-only, computed at read time from the existing sources (no new registry):
  * canonical supplier receipts of the project's lots —
      - ``receive_from_supplier_to_project`` into the project or one of its
        subprojects (direct delivery);
      - ``receive_from_supplier`` into a warehouse whose FIFO layers were
        accepted on the project / its subprojects (the acceptance rows'
        ``layer_allocations[*].source_movement_id`` name the receipt);
  * Path B supplier invoice lines with a quantity allocated to the project
    (``canonical_material_cost.effective_allocations``) that no canonical
    receipt carries (``invoice_line_id``) — one lot, counted once (FG-17).
Articles are keyed by the master ``item_id`` (canonical) and by the
normalized description for an unlinked invoice line.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

SUPPLIER_TYPE = "supplier"
PROJECT_TYPES = ("project", "subproject")


def _dec(value: Any) -> Optional[Decimal]:
    try:
        return Decimal(str(value)) if value is not None and value != "" else None
    except (InvalidOperation, ValueError):
        return None


async def _project_buckets(tenant, project_id: str) -> List[str]:
    subs = [p["id"] async for p in tenant.projects.find(
        {"parent_project_id": project_id}, {"_id": 0, "id": 1})]
    # PRJ-01 / FG-280 (R60): a legacy warranty project one level below a sub-project (the
    # only second level allowed) belongs to the same project's purchases.
    warranty = [p["id"] async for p in tenant.projects.find(
        {"parent_project_id": {"$in": subs}, "type": "Warranty"}, {"_id": 0, "id": 1})] if subs else []
    return [project_id] + subs + warranty


async def project_purchases(tenant, org_id: str, project_id: str) -> List[dict]:
    """Every purchase that reached the project (see module doc)."""
    buckets = await _project_buckets(tenant, project_id)
    ledger = tenant.warehouse_transactions
    purchases: List[dict] = []
    seen_receipts = set()

    def _canon(row, via):
        return {
            "article": row.get("item_id"), "item_id": row.get("item_id"),
            "description": None, "unit": row.get("unit"),
            "unit_price": str(_dec(row.get("unit_value")) or Decimal("0")),
            "quantity": str(row.get("quantity")),
            "supplier": (row.get("source") or {}).get("location_id"),
            "date": row.get("occurred_at") or row.get("recorded_at"),
            "source": via, "movement_id": row.get("movement_id"),
            "invoice_line_id": row.get("invoice_line_id"),
        }

    async for row in ledger.find(
            {"action": "receive_from_supplier_to_project",
             "destination.location_id": {"$in": buckets},
             "destination.location_type": {"$in": list(PROJECT_TYPES)}},
            {"_id": 0}):
        seen_receipts.add(row.get("movement_id"))
        purchases.append(_canon(row, "direct_delivery"))

    lot_ids = set()
    async for row in ledger.find(
            {"action": "accept_project_delivery",
             "destination.location_id": {"$in": buckets},
             "destination.location_type": {"$in": list(PROJECT_TYPES)}},
            {"_id": 0, "layer_allocations": 1}):
        for layer in row.get("layer_allocations") or []:
            if layer.get("source_movement_id"):
                lot_ids.add(layer["source_movement_id"])
    if lot_ids:
        async for row in ledger.find(
                {"action": "receive_from_supplier",
                 "movement_id": {"$in": sorted(lot_ids - seen_receipts)}},
                {"_id": 0}):
            seen_receipts.add(row.get("movement_id"))
            purchases.append(_canon(row, "warehouse_receipt"))

    # Path B invoice lines not carried by a canonical receipt (one lot once).
    from app.services.canonical_material_cost import (
        effective_allocations, ledger_invoice_line_links, project_invoice_lines,
        _norm_name,
    )
    lines = await project_invoice_lines(tenant, org_id, project_id)
    links = await ledger_invoice_line_links(
        tenant, org_id, [ln.get("id") for ln in lines if ln.get("id")])
    invoice_ids = {ln.get("invoice_id") for ln in lines if ln.get("invoice_id")}
    invoices = {}
    if invoice_ids:
        async for inv in tenant.invoices.find(
                {"id": {"$in": sorted(invoice_ids)}},
                {"_id": 0, "id": 1, "counterparty_name": 1,
                 "supplier_counterparty_id": 1, "issue_date": 1}):
            invoices[inv["id"]] = inv
    for ln in lines:
        if links.get(ln.get("id")):
            continue
        mine = [a for a in effective_allocations(ln)
                if a["type"] == "project" and a["ref_id"] == project_id]
        if not mine:
            continue
        qty = _dec(ln.get("qty"))
        price = _dec(ln.get("unit_price"))
        if price is None and qty:
            total = _dec(ln.get("line_total_ex_vat"))
            price = (total / qty) if total is not None else None
        inv = invoices.get(ln.get("invoice_id")) or {}
        purchases.append({
            "article": "desc:" + _norm_name(ln.get("description")),
            "item_id": None, "description": ln.get("description"),
            "unit": ln.get("unit"),
            "unit_price": str(price if price is not None else Decimal("0")),
            "quantity": str(qty) if qty is not None else None,
            "supplier": inv.get("supplier_counterparty_id") or inv.get("counterparty_name"),
            "date": inv.get("issue_date") or ln.get("created_at"),
            "source": "invoice_line", "movement_id": None,
            "invoice_line_id": ln.get("id"),
        })
    return purchases


def price_history(purchases: List[dict]) -> List[dict]:
    """Per article bought 2+ times: purchases (by date), the FLAG for the same
    supplier at different unit prices, and the best price."""
    by_article: Dict[str, List[dict]] = {}
    for p in purchases:
        if p.get("article"):
            by_article.setdefault(p["article"], []).append(p)
    out = []
    for article, rows in sorted(by_article.items()):
        if len(rows) < 2:
            continue
        rows = sorted(rows, key=lambda r: (str(r.get("date") or ""), r.get("movement_id") or ""))
        flags = []
        by_supplier: Dict[Any, List[dict]] = {}
        for r in rows:
            by_supplier.setdefault(r.get("supplier"), []).append(r)
        for supplier, srows in sorted(by_supplier.items(), key=lambda kv: str(kv[0])):
            prices = sorted({Decimal(r["unit_price"]) for r in srows})
            if len(prices) > 1:
                flags.append({"code": "SAME_SUPPLIER_DIFFERENT_PRICE",
                              "supplier": supplier,
                              "prices": [str(x) for x in prices],
                              "min_price": str(prices[0]), "max_price": str(prices[-1])})
        best = min(rows, key=lambda r: (Decimal(r["unit_price"]), str(r.get("date") or "")))
        out.append({
            "article": article, "item_id": rows[0].get("item_id"),
            "description": rows[0].get("description"), "unit": rows[0].get("unit"),
            "purchases": rows, "purchase_count": len(rows),
            "flagged": bool(flags), "flags": flags,
            "best_price": {"unit_price": best["unit_price"], "supplier": best.get("supplier"),
                           "date": best.get("date")},
        })
    return out
