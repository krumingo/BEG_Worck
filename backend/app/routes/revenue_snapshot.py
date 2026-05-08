"""
Routes - Revenue Snapshot / Profit by Period / Procurement Risk.
Phase 1: Revenue snapshot at acceptance
Phase 2: Profit by period
Phase 3: Collected cash vs earned profit
Phase 4: Low stock / delayed procurement alerts
Phase 5: Procurement risk integration
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from datetime import datetime, timezone
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import require_m2

router = APIRouter(tags=["Revenue Snapshot / Profit Period / Procurement"])

DEFAULT_PROCUREMENT_LEAD_DAYS = 14


# ═══════════════════════════════════════════════════════════════════
# PHASE 1 — REVENUE SNAPSHOT AT ACCEPTANCE
# ═══════════════════════════════════════════════════════════════════

@router.post("/revenue-snapshots/from-offer/{offer_id}", status_code=201)
async def create_revenue_snapshot(offer_id: str, user: dict = Depends(require_m2)):
    """Create a frozen revenue snapshot from an accepted offer"""
    org_id = user["org_id"]
    offer = await db.offers.find_one({"id": offer_id, "org_id": org_id})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")

    # Prevent duplicate snapshots for same offer version
    existing = await db.revenue_snapshots.find_one(
        {"org_id": org_id, "offer_id": offer_id, "version": offer.get("version", 1)})
    if existing:
        raise HTTPException(status_code=400, detail="Snapshot already exists for this offer version")

    now = datetime.now(timezone.utc).isoformat()
    line_snapshot = []
    for ol in offer.get("lines", []):
        mat = ol.get("material_unit_cost", 0)
        lab = ol.get("labor_unit_cost", 0)
        qty = ol.get("qty", 0)
        line_snapshot.append({
            "offer_line_id": ol.get("id"),
            "activity_name": ol.get("activity_name", ""),
            "unit": ol.get("unit", ""),
            "qty": qty,
            "material_unit_cost": mat,
            "labor_unit_cost": lab,
            "sale_unit_price": round(mat + lab, 2),
            "line_total": round(qty * (mat + lab), 2),
        })

    snapshot = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "project_id": offer["project_id"],
        "offer_id": offer_id,
        "offer_no": offer.get("offer_no", ""),
        "offer_type": offer.get("offer_type", "main"),
        "version": offer.get("version", 1),
        "accepted_at": offer.get("accepted_at") or now,
        "currency": offer.get("currency", "EUR"),
        "subtotal": offer.get("subtotal", 0),
        "vat_amount": offer.get("vat_amount", 0),
        "total_contract_value": offer.get("total", 0),
        "lines": line_snapshot,
        "line_count": len(line_snapshot),
        "frozen_at": now,
        "frozen_by": user["id"],
    }
    await db.revenue_snapshots.insert_one(snapshot)
    return {k: v for k, v in snapshot.items() if k != "_id"}


@router.get("/revenue-snapshots")
async def list_revenue_snapshots(project_id: Optional[str] = None, user: dict = Depends(require_m2)):
    q = {"org_id": user["org_id"]}
    if project_id: q["project_id"] = project_id
    return await db.revenue_snapshots.find(q, {"_id": 0}).sort("frozen_at", -1).to_list(100)


@router.get("/revenue-snapshots/{snapshot_id}")
async def get_revenue_snapshot(snapshot_id: str, user: dict = Depends(require_m2)):
    s = await db.revenue_snapshots.find_one({"id": snapshot_id, "org_id": user["org_id"]}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return s


# ═══════════════════════════════════════════════════════════════════
# PHASE 2 — PROFIT BY PERIOD
# ═══════════════════════════════════════════════════════════════════

@router.get("/profit-by-period/{project_id}")
async def get_profit_by_period(project_id: str, user: dict = Depends(require_m2)):
    """Monthly profit breakdown for a project"""
    org_id = user["org_id"]

    # Earned revenue by month (from client acts)
    acts = await db.client_acts.find(
        {"org_id": org_id, "project_id": project_id, "status": "Accepted"},
        {"_id": 0, "act_date": 1, "subtotal": 1}
    ).to_list(200)

    # Billed by month (invoices)
    invoices = await db.invoices.find(
        {"org_id": org_id, "project_id": project_id, "direction": "Issued",
         "status": {"$nin": ["Draft", "Cancelled"]}},
        {"_id": 0, "issue_date": 1, "subtotal": 1, "total": 1, "paid_amount": 1}
    ).to_list(500)

    # Labor by month
    labor_entries = await db.labor_entries.find(
        {"org_id": org_id, "project_id": project_id},
        {"_id": 0, "date": 1, "labor_cost": 1, "hours": 1}
    ).to_list(5000)

    # Material by month (from material_entries issues + returns)
    mat_entries = await db.material_entries.find(
        {"org_id": org_id, "project_id": project_id, "movement_type": {"$in": ["issue", "return"]}},
        {"_id": 0, "date": 1, "total_cost": 1}
    ).to_list(5000)

    # Subcontract by month (from acts)
    sub_acts = await db.subcontractor_acts.find(
        {"org_id": org_id, "project_id": project_id, "status": "confirmed"},
        {"_id": 0, "act_date": 1, "certified_total": 1}
    ).to_list(200)

    # Overhead by month
    oh_allocs = await db.project_overhead_alloc.find(
        {"org_id": org_id, "project_id": project_id},
        {"_id": 0, "period": 1, "allocated_amount": 1}
    ).to_list(50)

    # Aggregate by period
    periods = {}

    def ensure_period(pk):
        if pk not in periods:
            periods[pk] = {"period": pk, "earned": 0, "billed": 0, "collected": 0,
                          "material": 0, "labor": 0, "labor_hours": 0,
                          "subcontract": 0, "overhead": 0,
                          "gross_profit": None, "net_profit": None}

    for a in acts:
        pk = (a.get("act_date") or "")[:7]
        if pk: ensure_period(pk); periods[pk]["earned"] += a.get("subtotal", 0)

    for inv in invoices:
        pk = (inv.get("issue_date") or "")[:7]
        if pk:
            ensure_period(pk)
            periods[pk]["billed"] += inv.get("subtotal", 0) or inv.get("total", 0)
            periods[pk]["collected"] += inv.get("paid_amount", 0)

    for le in labor_entries:
        pk = (le.get("date") or "")[:7]
        if pk:
            ensure_period(pk)
            if le.get("labor_cost") is not None:
                periods[pk]["labor"] += le["labor_cost"]
            periods[pk]["labor_hours"] += float(le.get("hours", 0))

    for me in mat_entries:
        pk = (me.get("date") or "")[:7]
        if pk and me.get("total_cost") is not None:
            ensure_period(pk)
            periods[pk]["material"] += me["total_cost"]

    for sa in sub_acts:
        pk = (sa.get("act_date") or "")[:7]
        if pk:
            ensure_period(pk)
            periods[pk]["subcontract"] += sa.get("certified_total", 0)

    for oh in oh_allocs:
        pk = oh.get("period", "")
        if pk:
            ensure_period(pk)
            periods[pk]["overhead"] += oh.get("allocated_amount", 0)

    # Calculate profits per period
    for pk, p in periods.items():
        for k in ["earned", "billed", "collected", "material", "labor", "subcontract", "overhead", "labor_hours"]:
            p[k] = round(p[k], 2) if k != "labor_hours" else round(p[k], 1)
        gross_cost = p["material"] + p["labor"] + p["subcontract"]
        p["gross_cost"] = round(gross_cost, 2)
        p["total_cost"] = round(gross_cost + p["overhead"], 2)
        rev = p["earned"] if p["earned"] > 0 else p["billed"]
        p["gross_profit"] = round(rev - gross_cost, 2) if rev > 0 else None
        p["net_profit"] = round(rev - p["total_cost"], 2) if rev > 0 else None

    result = sorted(periods.values(), key=lambda x: x["period"], reverse=True)
    return {"project_id": project_id, "currency": "EUR", "periods": result}


# ═══════════════════════════════════════════════════════════════════
# PHASE 3 — COLLECTED CASH VS EARNED PROFIT
# ═══════════════════════════════════════════════════════════════════

@router.get("/cash-vs-earned/{project_id}")
async def get_cash_vs_earned(project_id: str, user: dict = Depends(require_m2)):
    """Cash collected vs earned revenue + gap analysis"""
    org_id = user["org_id"]

    # Earned
    acts = await db.client_acts.find(
        {"org_id": org_id, "project_id": project_id, "status": "Accepted"},
        {"_id": 0, "subtotal": 1}
    ).to_list(200)
    earned = sum(a.get("subtotal", 0) for a in acts)

    # Billed
    invoices = await db.invoices.find(
        {"org_id": org_id, "project_id": project_id, "direction": "Issued",
         "status": {"$nin": ["Draft", "Cancelled"]}},
        {"_id": 0, "subtotal": 1, "total": 1, "paid_amount": 1, "remaining_amount": 1}
    ).to_list(500)
    billed = sum(i.get("subtotal", 0) or i.get("total", 0) for i in invoices)
    collected = sum(i.get("paid_amount", 0) for i in invoices)

    # Costs paid (outflows)
    sub_payments = await db.subcontractor_payments.find(
        {"org_id": org_id, "project_id": project_id, "status": "completed"},
        {"_id": 0, "amount": 1}
    ).to_list(200)
    costs_paid = sum(p.get("amount", 0) for p in sub_payments)

    collected_vs_earned = round(collected - earned, 2) if earned > 0 else None
    collected_vs_billed = round(collected - billed, 2) if billed > 0 else None
    cash_position = round(collected - costs_paid, 2)

    return {
        "project_id": project_id,
        "currency": "EUR",
        "earned_revenue": round(earned, 2),
        "billed_revenue": round(billed, 2),
        "collected_cash": round(collected, 2),
        "costs_paid_cash": round(costs_paid, 2),
        "cash_position": cash_position,
        "gaps": {
            "collected_vs_earned": collected_vs_earned,
            "collected_vs_billed": collected_vs_billed,
            "earned_vs_billed": round(earned - billed, 2) if earned > 0 else None,
        },
        "collection_percent": round(collected / billed * 100, 1) if billed > 0 else None,
        "basis_labels": {
            "earned": "client_acts_accepted",
            "billed": "invoices_issued",
            "collected": "invoice_payments",
            "costs_paid": "subcontractor_payments",
        },
    }


# ═══════════════════════════════════════════════════════════════════
# PHASE 4 — LOW STOCK / DELAYED PROCUREMENT ALERTS
# ═══════════════════════════════════════════════════════════════════

@router.get("/procurement-alerts/{project_id}")
async def get_procurement_alerts(project_id: str, user: dict = Depends(require_m2)):
    """Procurement risk alerts based on planned vs requested vs purchased vs issued"""
    org_id = user["org_id"]
    alerts = []

    # Load planned materials
    planned = await db.planned_materials.find(
        {"org_id": org_id, "project_id": project_id, "status": "active"},
        {"_id": 0}
    ).to_list(500)

    if not planned:
        return {"project_id": project_id, "alerts": [], "total": 0,
                "metrics_available": {"planned_materials": False}}

    # Load request coverage
    requests = await db.material_requests.find(
        {"org_id": org_id, "project_id": project_id, "status": {"$ne": "cancelled"}},
        {"_id": 0, "lines": 1}
    ).to_list(100)
    requested_by_name = {}
    for req in requests:
        for rl in req.get("lines", []):
            name = rl.get("material_name", "")
            requested_by_name[name] = requested_by_name.get(name, 0) + float(rl.get("qty_requested", 0))

    # Load purchases
    sinvs = await db.supplier_invoices.find(
        {"org_id": org_id, "project_id": project_id},
        {"_id": 0, "lines": 1, "status": 1}
    ).to_list(100)
    purchased_by_name = {}
    for si in sinvs:
        for sl in si.get("lines", []):
            name = sl.get("material_name", "")
            purchased_by_name[name] = purchased_by_name.get(name, 0) + float(sl.get("qty", 0))

    # Load warehouse issues
    issues = await db.warehouse_transactions.find(
        {"org_id": org_id, "project_id": project_id, "type": "issue"},
        {"_id": 0, "lines": 1}
    ).to_list(200)
    issued_by_name = {}
    for wt in issues:
        for wl in wt.get("lines", []):
            name = wl.get("material_name", "")
            issued_by_name[name] = issued_by_name.get(name, 0) + float(wl.get("qty_issued", 0))

    for pm in planned:
        name = pm.get("material_name", "")
        planned_qty = pm.get("planned_qty_with_waste", pm.get("planned_qty", 0))
        if planned_qty <= 0:
            continue

        req_qty = requested_by_name.get(name, 0)
        pur_qty = purchased_by_name.get(name, 0)
        iss_qty = issued_by_name.get(name, 0)

        # Not requested
        if req_qty == 0:
            alerts.append({
                "type": "not_requested",
                "severity": "warning",
                "material_name": name,
                "planned_qty": planned_qty,
                "message": f"{name}: планирано {planned_qty} {pm.get('unit','')}, не е заявено",
            })
        # Requested but not purchased
        elif pur_qty == 0 and req_qty > 0:
            alerts.append({
                "type": "requested_not_purchased",
                "severity": "warning",
                "material_name": name,
                "requested_qty": round(req_qty, 2),
                "message": f"{name}: заявено {round(req_qty, 2)}, не е закупено",
            })
        # Purchased but not issued
        elif iss_qty == 0 and pur_qty > 0:
            alerts.append({
                "type": "purchased_not_issued",
                "severity": "info",
                "material_name": name,
                "purchased_qty": round(pur_qty, 2),
                "message": f"{name}: закупено {round(pur_qty, 2)}, не е отпуснато към обект",
            })
        # Under-purchased
        elif req_qty > 0 and pur_qty < req_qty * 0.8:
            shortage = round(req_qty - pur_qty, 2)
            alerts.append({
                "type": "under_purchased",
                "severity": "warning",
                "material_name": name,
                "requested_qty": round(req_qty, 2),
                "purchased_qty": round(pur_qty, 2),
                "shortage": shortage,
                "message": f"{name}: заявено {round(req_qty, 2)}, закупено {round(pur_qty, 2)} (недостиг {shortage})",
            })

    alerts.sort(key=lambda a: {"critical": 0, "warning": 1, "info": 2}.get(a["severity"], 3))

    return {
        "project_id": project_id,
        "alerts": alerts,
        "total": len(alerts),
        "summary": {
            "not_requested": sum(1 for a in alerts if a["type"] == "not_requested"),
            "not_purchased": sum(1 for a in alerts if a["type"] == "requested_not_purchased"),
            "not_issued": sum(1 for a in alerts if a["type"] == "purchased_not_issued"),
            "under_purchased": sum(1 for a in alerts if a["type"] == "under_purchased"),
        },
        "metrics_available": {"planned_materials": True},
    }


# ═══════════════════════════════════════════════════════════════════
# PHASE 5 — PROCUREMENT RISK INTEGRATION
# ═══════════════════════════════════════════════════════════════════

async def get_procurement_risk(org_id: str, project_id: str) -> dict:
    """Get procurement risk flags for integration into project risk"""
    planned_count = await db.planned_materials.count_documents(
        {"org_id": org_id, "project_id": project_id, "status": "active"})

    if planned_count == 0:
        return {"available": False, "flags": [], "severity": "unknown"}

    # Count coverage gaps
    planned = await db.planned_materials.find(
        {"org_id": org_id, "project_id": project_id, "status": "active"},
        {"_id": 0, "material_name": 1, "planned_qty_with_waste": 1, "planned_qty": 1, "unit": 1}
    ).to_list(500)

    requests = await db.material_requests.find(
        {"org_id": org_id, "project_id": project_id, "status": {"$ne": "cancelled"}},
        {"_id": 0, "lines": 1}
    ).to_list(100)
    req_names = set()
    for r in requests:
        for l in r.get("lines", []):
            req_names.add(l.get("material_name", ""))

    not_requested = sum(1 for pm in planned if pm.get("material_name", "") not in req_names and (pm.get("planned_qty_with_waste", 0) or pm.get("planned_qty", 0)) > 0)

    flags = []
    if not_requested > planned_count * 0.5:
        flags.append("high_unrequested_materials")
    elif not_requested > 0:
        flags.append("some_unrequested_materials")

    severity = "warning" if "high_unrequested_materials" in flags else "info" if flags else "ok"

    return {
        "available": True,
        "planned_count": planned_count,
        "not_requested_count": not_requested,
        "flags": flags,
        "severity": severity,
    }
