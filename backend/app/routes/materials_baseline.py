"""
Routes - Materials Baseline + Request Matching.
Phase 1: Planned Materials Snapshot
Phase 2: Request Linkage
Phase 3: Purchase / Warehouse Linkage
Phase 4: Comparison / Project Material Summary
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from datetime import datetime, timezone
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import require_m2

router = APIRouter(tags=["Materials Baseline"])


# ═══════════════════════════════════════════════════════════════════
# PHASE 1 — PLANNED MATERIALS SNAPSHOT
# ═══════════════════════════════════════════════════════════════════

@router.post("/planned-materials/from-offer/{offer_id}", status_code=201)
async def generate_planned_materials(offer_id: str, data: dict = {}, user: dict = Depends(require_m2)):
    """Generate planned materials snapshot from accepted offer + AI material suggestions"""
    org_id = user["org_id"]
    offer = await db.offers.find_one({"id": offer_id, "org_id": org_id})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")

    project_id = offer["project_id"]
    waste_percent = float(data.get("waste_percent", 10))

    # Duplicate protection
    existing = await db.planned_materials.count_documents({"org_id": org_id, "source_offer_id": offer_id})
    if existing > 0:
        raise HTTPException(status_code=400, detail="Planned materials already exist for this offer. Use regenerate endpoint.")

    # Load execution packages for linkage
    exec_pkgs = {}
    pkgs = await db.execution_packages.find({"org_id": org_id, "source_offer_id": offer_id}, {"_id": 0, "id": 1, "offer_line_id": 1}).to_list(200)
    for p in pkgs:
        if p.get("offer_line_id"):
            exec_pkgs[p["offer_line_id"]] = p["id"]

    # Load AI material suggestions from extra work drafts linked to this offer
    ai_materials = {}
    if offer.get("source_batch_id"):
        drafts = await db.extra_work_drafts.find(
            {"group_batch_id": offer["source_batch_id"]},
            {"_id": 0, "title": 1, "suggested_materials": 1}
        ).to_list(50)
        for draft in drafts:
            for mat in (draft.get("suggested_materials") or []):
                key = mat.get("name", "")
                if key and key not in ai_materials:
                    ai_materials[key] = mat

    now = datetime.now(timezone.utc).isoformat()
    rows = []

    for ol in offer.get("lines", []):
        line_id = ol.get("id")
        activity_name = ol.get("activity_name", "")
        qty = ol.get("qty", 0)
        mat_cost = ol.get("material_unit_cost", 0)
        pkg_id = exec_pkgs.get(line_id)

        # Primary: the offer line itself as a material cost line
        planned_qty = qty
        planned_with_waste = round(planned_qty * (1 + waste_percent / 100), 2)
        planned_unit_cost = mat_cost
        planned_total = round(planned_with_waste * planned_unit_cost, 2)

        rows.append({
            "id": str(uuid.uuid4()),
            "org_id": org_id,
            "project_id": project_id,
            "source_offer_id": offer_id,
            "offer_line_id": line_id,
            "execution_package_id": pkg_id,
            "activity_type": ol.get("activity_type", ""),
            "activity_subtype": ol.get("activity_subtype", ""),
            "activity_name": activity_name,
            "material_name": f"Материали за: {activity_name}",
            "category": "aggregate",
            "unit": ol.get("unit", "m2"),
            "planned_qty": planned_qty,
            "waste_percent": waste_percent,
            "planned_qty_with_waste": planned_with_waste,
            "planned_unit_cost": planned_unit_cost,
            "planned_total_cost": planned_total,
            "source_type": "offer_line",
            "status": "active",
            "created_at": now,
        })

    # Also add specific AI-suggested materials if available from drafts
    for mat_name, mat in ai_materials.items():
        est_qty = mat.get("estimated_qty") or 0
        if est_qty <= 0:
            continue
        planned_with_waste = round(est_qty * (1 + waste_percent / 100), 2)

        rows.append({
            "id": str(uuid.uuid4()),
            "org_id": org_id,
            "project_id": project_id,
            "source_offer_id": offer_id,
            "offer_line_id": None,
            "execution_package_id": None,
            "activity_type": "",
            "activity_subtype": "",
            "activity_name": "",
            "material_name": mat_name,
            "category": mat.get("category", "primary"),
            "unit": mat.get("unit", "бр"),
            "planned_qty": est_qty,
            "waste_percent": waste_percent,
            "planned_qty_with_waste": planned_with_waste,
            "planned_unit_cost": 0,
            "planned_total_cost": 0,
            "source_type": "ai_suggestion",
            "status": "active",
            "created_at": now,
        })

    if rows:
        await db.planned_materials.insert_many(rows)

    return {"ok": True, "count": len(rows), "offer_id": offer_id, "project_id": project_id}


@router.get("/planned-materials")
async def list_planned_materials(project_id: Optional[str] = None, offer_id: Optional[str] = None, user: dict = Depends(require_m2)):
    query = {"org_id": user["org_id"]}
    if project_id:
        query["project_id"] = project_id
    if offer_id:
        query["source_offer_id"] = offer_id
    rows = await db.planned_materials.find(query, {"_id": 0}).sort("created_at", 1).to_list(500)
    return rows


@router.delete("/planned-materials/by-offer/{offer_id}")
async def delete_planned_materials(offer_id: str, user: dict = Depends(require_m2)):
    """Delete planned materials for an offer (allows regeneration)"""
    result = await db.planned_materials.delete_many({"org_id": user["org_id"], "source_offer_id": offer_id})
    return {"ok": True, "deleted": result.deleted_count}


# ═══════════════════════════════════════════════════════════════════
# PHASE 2 — REQUEST LINKAGE + COVERAGE
# ═══════════════════════════════════════════════════════════════════

@router.get("/planned-materials/coverage/{project_id}")
async def get_material_coverage(project_id: str, user: dict = Depends(require_m2)):
    """Get planned materials with request/purchase/warehouse coverage"""
    org_id = user["org_id"]

    planned = await db.planned_materials.find(
        {"org_id": org_id, "project_id": project_id, "status": "active"},
        {"_id": 0}
    ).to_list(500)

    if not planned:
        return {"project_id": project_id, "rows": [], "summary": _empty_summary()}

    # Load all material requests for this project
    requests = await db.material_requests.find(
        {"org_id": org_id, "project_id": project_id, "status": {"$ne": "cancelled"}},
        {"_id": 0, "lines": 1, "source_offer_id": 1}
    ).to_list(100)

    requested_by_name = {}
    for req in requests:
        for rl in req.get("lines", []):
            name = rl.get("material_name", "")
            requested_by_name[name] = requested_by_name.get(name, 0) + float(rl.get("qty_requested", 0))

    # Load supplier invoices for this project
    sinvs = await db.supplier_invoices.find(
        {"org_id": org_id, "project_id": project_id, "status": {"$ne": "uploaded"}},
        {"_id": 0, "lines": 1}
    ).to_list(100)

    purchased_by_name = {}
    for si in sinvs:
        for sl in si.get("lines", []):
            name = sl.get("material_name", "")
            purchased_by_name[name] = purchased_by_name.get(name, 0) + float(sl.get("qty", 0))

    # Load warehouse transactions
    wh_txns = await db.warehouse_transactions.find(
        {"org_id": org_id, "project_id": project_id},
        {"_id": 0, "type": 1, "lines": 1}
    ).to_list(200)

    stocked_by_name = {}
    issued_by_name = {}
    returned_by_name = {}
    for wt in wh_txns:
        for wl in wt.get("lines", []):
            name = wl.get("material_name", "")
            if wt["type"] == "intake":
                stocked_by_name[name] = stocked_by_name.get(name, 0) + float(wl.get("qty_received", 0))
            elif wt["type"] == "issue":
                issued_by_name[name] = issued_by_name.get(name, 0) + float(wl.get("qty_issued", 0))
            elif wt["type"] == "return":
                returned_by_name[name] = returned_by_name.get(name, 0) + float(wl.get("qty_returned", 0))

    # Load consumption
    consumptions = await db.project_material_ops.find(
        {"org_id": org_id, "project_id": project_id, "type": "consumption"},
        {"_id": 0, "lines": 1}
    ).to_list(100)

    consumed_by_name = {}
    for co in consumptions:
        for cl in co.get("lines", []):
            name = cl.get("material_name", "")
            consumed_by_name[name] = consumed_by_name.get(name, 0) + float(cl.get("qty_consumed", 0))

    # Enrich planned rows
    enriched = []
    total_planned_value = 0
    total_purchased_value = 0

    for pm in planned:
        name = pm["material_name"]
        planned_qty = pm.get("planned_qty_with_waste", pm.get("planned_qty", 0))
        req_qty = round(requested_by_name.get(name, 0), 2)
        pur_qty = round(purchased_by_name.get(name, 0), 2)
        stk_qty = round(stocked_by_name.get(name, 0), 2)
        iss_qty = round(issued_by_name.get(name, 0), 2)
        ret_qty = round(returned_by_name.get(name, 0), 2)
        con_qty = round(consumed_by_name.get(name, 0), 2)

        remaining_to_request = round(max(0, planned_qty - req_qty), 2)
        remaining_to_purchase = round(max(0, req_qty - pur_qty), 2)
        variance_qty = round(planned_qty - pur_qty, 2)
        variance_value = round(variance_qty * pm.get("planned_unit_cost", 0), 2)

        total_planned_value += pm.get("planned_total_cost", 0)

        row = {
            **pm,
            "requested_qty": req_qty,
            "purchased_qty": pur_qty,
            "stocked_qty": stk_qty,
            "issued_qty": iss_qty,
            "consumed_qty": con_qty,
            "returned_qty": ret_qty,
            "remaining_to_request": remaining_to_request,
            "remaining_to_purchase": remaining_to_purchase,
            "variance_qty": variance_qty,
            "variance_value": variance_value,
        }
        enriched.append(row)

    summary = {
        "total_planned_rows": len(enriched),
        "total_planned_value": round(total_planned_value, 2),
        "fully_requested": sum(1 for r in enriched if r["remaining_to_request"] <= 0 and r["planned_qty_with_waste"] > 0),
        "partially_requested": sum(1 for r in enriched if 0 < r["requested_qty"] < r["planned_qty_with_waste"]),
        "not_requested": sum(1 for r in enriched if r["requested_qty"] == 0 and r["planned_qty_with_waste"] > 0),
        "fully_purchased": sum(1 for r in enriched if r["purchased_qty"] >= r["requested_qty"] > 0),
        "has_consumption_data": any(r["consumed_qty"] > 0 for r in enriched),
        "currency": "EUR",
    }

    return {"project_id": project_id, "rows": enriched, "summary": summary}


def _empty_summary():
    return {
        "total_planned_rows": 0, "total_planned_value": 0,
        "fully_requested": 0, "partially_requested": 0, "not_requested": 0,
        "fully_purchased": 0, "has_consumption_data": False, "currency": "EUR",
    }


# ═══════════════════════════════════════════════════════════════════
# PHASE 4 — PROJECT MATERIAL FINANCIAL SUMMARY
# ═══════════════════════════════════════════════════════════════════

@router.get("/project-material-summary/{project_id}")
async def get_project_material_summary(project_id: str, user: dict = Depends(require_m2)):
    """Comprehensive material financial summary for a project"""
    org_id = user["org_id"]
    project = await db.projects.find_one({"id": project_id, "org_id": org_id}, {"_id": 0, "code": 1, "name": 1})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Planned materials
    planned = await db.planned_materials.find(
        {"org_id": org_id, "project_id": project_id, "status": "active"},
        {"_id": 0}
    ).to_list(500)
    planned_value = sum(p.get("planned_total_cost", 0) for p in planned)

    # Actual purchases (supplier invoices posted)
    sinvs = await db.supplier_invoices.find(
        {"org_id": org_id, "project_id": project_id, "posted_to_warehouse": True},
        {"_id": 0, "subtotal": 1, "total": 1, "lines": 1}
    ).to_list(100)
    purchased_value = sum(si.get("subtotal", 0) or sum(l.get("total_price", 0) for l in si.get("lines", [])) for si in sinvs)

    # Warehouse issue value
    wh_issues = await db.warehouse_transactions.find(
        {"org_id": org_id, "project_id": project_id, "type": "issue"},
        {"_id": 0, "total": 1, "lines": 1}
    ).to_list(100)
    issued_value = sum(t.get("total", 0) or sum(l.get("total_price", 0) for l in t.get("lines", [])) for t in wh_issues)

    # Returns value
    wh_returns = await db.warehouse_transactions.find(
        {"org_id": org_id, "project_id": project_id, "type": "return"},
        {"_id": 0, "lines": 1}
    ).to_list(100)
    returned_value = sum(sum(l.get("total_price", 0) or 0 for l in t.get("lines", [])) for t in wh_returns)

    net_material_cost = round(issued_value - returned_value, 2)
    variance_to_plan = round(planned_value - purchased_value, 2) if planned_value > 0 else None

    metrics_available = {
        "planned_materials": len(planned) > 0,
        "purchases": len(sinvs) > 0,
        "warehouse_issues": len(wh_issues) > 0,
        "warehouse_returns": len(wh_returns) > 0,
    }

    return {
        "project_id": project_id,
        "project_code": project.get("code", ""),
        "project_name": project.get("name", ""),
        "currency": "EUR",

        "planned": {
            "total_rows": len(planned),
            "total_value": round(planned_value, 2),
        },

        "actual": {
            "purchased_value": round(purchased_value, 2),
            "issued_value": round(issued_value, 2),
            "returned_value": round(returned_value, 2),
            "net_material_cost": net_material_cost,
        },

        "variance": {
            "plan_vs_purchased": variance_to_plan,
            "plan_vs_issued": round(planned_value - issued_value, 2) if planned_value > 0 else None,
        },

        "metrics_available": metrics_available,
    }
