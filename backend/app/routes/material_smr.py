"""
Routes - Material Cost by SMR / Execution Package.
Phase 1: Material entry linkage
Phase 2: Material actual cost by execution package
Phase 3: Execution package material budget/actual/variance
Phase 4: Package profit/margin impact
Phase 5: Warnings + project/profit integration
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from datetime import datetime, timezone
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import require_m2

router = APIRouter(tags=["Material Cost by SMR"])


# ═══════════════════════════════════════════════════════════════════
# PHASE 1 — MATERIAL ENTRY LINKAGE
# ═══════════════════════════════════════════════════════════════════

@router.post("/material-entries/sync/{project_id}")
async def sync_material_entries(project_id: str, user: dict = Depends(require_m2)):
    """Sync material entries from warehouse transactions + consumption ops, linking to execution packages"""
    org_id = user["org_id"]

    # Load execution packages for mapping
    exec_pkgs = await db.execution_packages.find(
        {"org_id": org_id, "project_id": project_id},
        {"_id": 0, "id": 1, "activity_name": 1, "offer_line_id": 1}
    ).to_list(200)

    # Load planned materials for mapping (material_name → execution_package_id)
    planned = await db.planned_materials.find(
        {"org_id": org_id, "project_id": project_id, "status": "active"},
        {"_id": 0, "id": 1, "material_name": 1, "execution_package_id": 1, "offer_line_id": 1}
    ).to_list(500)
    planned_by_name = {}
    for pm in planned:
        name = (pm.get("material_name") or "").lower().strip()
        if name:
            planned_by_name[name] = pm

    # Clear old synced entries
    await db.material_entries.delete_many({"org_id": org_id, "project_id": project_id, "source": "sync"})

    now = datetime.now(timezone.utc).isoformat()
    created = 0

    # Process warehouse issues
    issues = await db.warehouse_transactions.find(
        {"org_id": org_id, "project_id": project_id, "type": "issue"}, {"_id": 0}
    ).to_list(200)
    for txn in issues:
        for line in txn.get("lines", []):
            name = line.get("material_name", "")
            name_lower = name.lower().strip()
            pm = planned_by_name.get(name_lower)

            entry = {
                "id": str(uuid.uuid4()), "org_id": org_id, "project_id": project_id,
                "execution_package_id": pm["execution_package_id"] if pm else None,
                "planned_material_id": pm["id"] if pm else None,
                "offer_line_id": pm.get("offer_line_id") if pm else None,
                "material_name": name,
                "qty": float(line.get("qty_issued", 0)),
                "unit": line.get("unit", ""),
                "unit_cost": float(line.get("unit_price", 0)) if line.get("unit_price") else None,
                "total_cost": float(line.get("total_price", 0)) if line.get("total_price") else None,
                "movement_type": "issue",
                "source_doc_type": "warehouse_transaction",
                "source_doc_id": txn.get("id"),
                "date": txn.get("issue_date", txn.get("created_at", "")[:10]),
                "mapped": pm is not None,
                "source": "sync", "created_at": now,
            }
            await db.material_entries.insert_one(entry)
            created += 1

    # Process returns
    returns = await db.warehouse_transactions.find(
        {"org_id": org_id, "project_id": project_id, "type": "return"}, {"_id": 0}
    ).to_list(200)
    for txn in returns:
        for line in txn.get("lines", []):
            name = line.get("material_name", "")
            pm = planned_by_name.get(name.lower().strip())
            entry = {
                "id": str(uuid.uuid4()), "org_id": org_id, "project_id": project_id,
                "execution_package_id": pm["execution_package_id"] if pm else None,
                "planned_material_id": pm["id"] if pm else None,
                "material_name": name, "qty": -float(line.get("qty_returned", 0)),
                "unit": line.get("unit", ""), "unit_cost": None,
                "total_cost": -(float(line.get("total_price", 0)) or 0),
                "movement_type": "return",
                "source_doc_type": "warehouse_transaction", "source_doc_id": txn.get("id"),
                "date": txn.get("return_date", txn.get("created_at", "")[:10]),
                "mapped": pm is not None, "source": "sync", "created_at": now,
            }
            await db.material_entries.insert_one(entry)
            created += 1

    # Process consumption
    consumptions = await db.project_material_ops.find(
        {"org_id": org_id, "project_id": project_id, "type": "consumption"}, {"_id": 0}
    ).to_list(200)
    for op in consumptions:
        for line in op.get("lines", []):
            name = line.get("material_name", "")
            pm = planned_by_name.get(name.lower().strip())
            entry = {
                "id": str(uuid.uuid4()), "org_id": org_id, "project_id": project_id,
                "execution_package_id": pm["execution_package_id"] if pm else None,
                "planned_material_id": pm["id"] if pm else None,
                "material_name": name, "qty": float(line.get("qty_consumed", 0)),
                "unit": line.get("unit", ""), "unit_cost": None, "total_cost": None,
                "movement_type": "consumption",
                "source_doc_type": "project_material_op", "source_doc_id": op.get("id"),
                "date": op.get("date", op.get("created_at", "")[:10]),
                "mapped": pm is not None, "source": "sync", "created_at": now,
            }
            await db.material_entries.insert_one(entry)
            created += 1

    return {"ok": True, "synced": created, "project_id": project_id}


@router.get("/material-entries")
async def list_material_entries(
    project_id: Optional[str] = None, execution_package_id: Optional[str] = None,
    planned_material_id: Optional[str] = None, user: dict = Depends(require_m2),
):
    q = {"org_id": user["org_id"]}
    if project_id: q["project_id"] = project_id
    if execution_package_id: q["execution_package_id"] = execution_package_id
    if planned_material_id: q["planned_material_id"] = planned_material_id
    return await db.material_entries.find(q, {"_id": 0}).sort("date", -1).to_list(500)


# ═══════════════════════════════════════════════════════════════════
# PHASE 2 — MATERIAL ACTUAL COST BY EXECUTION PACKAGE
# ═══════════════════════════════════════════════════════════════════

@router.get("/material-cost/by-execution-package/{pkg_id}")
async def get_material_cost_by_exec_pkg(pkg_id: str, user: dict = Depends(require_m2)):
    """Detailed material cost breakdown for an execution package"""
    org_id = user["org_id"]
    pkg = await db.execution_packages.find_one({"id": pkg_id, "org_id": org_id}, {"_id": 0})
    if not pkg:
        raise HTTPException(status_code=404, detail="Execution package not found")

    entries = await db.material_entries.find(
        {"org_id": org_id, "execution_package_id": pkg_id}, {"_id": 0}
    ).sort("date", -1).to_list(500)

    by_material = {}
    total_issued_qty = 0
    total_returned_qty = 0
    total_cost = 0
    partial_cost = False

    for e in entries:
        name = e.get("material_name", "")
        qty = float(e.get("qty", 0))
        cost = e.get("total_cost")
        mt = e.get("movement_type", "")

        if mt == "issue":
            total_issued_qty += qty
        elif mt == "return":
            total_returned_qty += abs(qty)

        if cost is not None:
            total_cost += cost
        elif mt in ["issue", "return"]:
            partial_cost = True

        if name not in by_material:
            by_material[name] = {"material_name": name, "unit": e.get("unit", ""), "issued_qty": 0, "returned_qty": 0, "consumed_qty": 0, "net_cost": 0}
        if mt == "issue":
            by_material[name]["issued_qty"] += qty
            if cost: by_material[name]["net_cost"] += cost
        elif mt == "return":
            by_material[name]["returned_qty"] += abs(qty)
            if cost: by_material[name]["net_cost"] += cost
        elif mt == "consumption":
            by_material[name]["consumed_qty"] += qty

    for v in by_material.values():
        for k in ["issued_qty", "returned_qty", "consumed_qty", "net_cost"]:
            v[k] = round(v[k], 2)

    budget = pkg.get("material_budget_total", 0)
    variance = round(total_cost - budget, 2) if budget > 0 and not partial_cost else None

    return {
        "execution_package_id": pkg_id,
        "activity_name": pkg.get("activity_name", ""),
        "material_budget": budget,
        "material_actual_cost": round(total_cost, 2),
        "material_variance": variance,
        "total_issued_qty": round(total_issued_qty, 2),
        "total_returned_qty": round(total_returned_qty, 2),
        "net_qty": round(total_issued_qty - total_returned_qty, 2),
        "partial_cost_data": partial_cost,
        "currency": "EUR",
        "entries_count": len(entries),
        "by_material": sorted(by_material.values(), key=lambda x: abs(x["net_cost"]), reverse=True),
    }


# ═══════════════════════════════════════════════════════════════════
# PHASE 3 — RECOMPUTE MATERIAL BUDGET/ACTUAL/VARIANCE
# ═══════════════════════════════════════════════════════════════════

@router.post("/execution-packages/recompute-material/{project_id}")
async def recompute_execution_package_material(project_id: str, user: dict = Depends(require_m2)):
    """Recompute material budget and actual for execution packages"""
    org_id = user["org_id"]
    pkgs = await db.execution_packages.find({"org_id": org_id, "project_id": project_id}, {"_id": 0}).to_list(200)
    if not pkgs:
        return {"ok": True, "updated": 0}

    # Load planned materials for budget linkage
    planned = await db.planned_materials.find(
        {"org_id": org_id, "project_id": project_id, "status": "active"},
        {"_id": 0, "execution_package_id": 1, "planned_total_cost": 1}
    ).to_list(500)
    budget_by_pkg = {}
    for pm in planned:
        ep_id = pm.get("execution_package_id")
        if ep_id:
            budget_by_pkg[ep_id] = budget_by_pkg.get(ep_id, 0) + (pm.get("planned_total_cost", 0) or 0)

    # Aggregate actual from material_entries
    entries = await db.material_entries.find(
        {"org_id": org_id, "project_id": project_id, "movement_type": {"$in": ["issue", "return"]}},
        {"_id": 0, "execution_package_id": 1, "total_cost": 1}
    ).to_list(5000)
    actual_by_pkg = {}
    for e in entries:
        ep_id = e.get("execution_package_id")
        if ep_id and e.get("total_cost") is not None:
            actual_by_pkg[ep_id] = actual_by_pkg.get(ep_id, 0) + float(e["total_cost"])

    updated = 0
    for pkg in pkgs:
        pid = pkg["id"]
        budget = budget_by_pkg.get(pid) or pkg.get("material_budget_total", 0)
        actual = round(actual_by_pkg.get(pid, 0), 2)
        variance_val = round(actual - budget, 2) if budget > 0 else None
        variance_pct = round(variance_val / budget * 100, 1) if budget > 0 and variance_val is not None else None

        await db.execution_packages.update_one({"id": pid}, {"$set": {
            "material_budget_total": round(budget, 2),
            "actual_material_cost": actual,
            "material_variance_value": variance_val,
            "material_variance_percent": variance_pct,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }})
        updated += 1

    return {"ok": True, "updated": updated}


# ═══════════════════════════════════════════════════════════════════
# PHASE 4 — PACKAGE FINANCIAL SUMMARY (PROFIT/MARGIN)
# ═══════════════════════════════════════════════════════════════════

@router.get("/execution-packages/{pkg_id}/financial")
async def get_package_financial_summary(pkg_id: str, user: dict = Depends(require_m2)):
    """Package-level financial summary with margin impact"""
    org_id = user["org_id"]
    pkg = await db.execution_packages.find_one({"id": pkg_id, "org_id": org_id}, {"_id": 0})
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")

    sale = pkg.get("sale_total", 0)
    mat_actual = pkg.get("actual_material_cost", 0)
    lab_actual = pkg.get("actual_labor_cost", 0)

    # Subcontract for this package
    sub_lines = await db.subcontractor_package_lines.find(
        {"org_id": org_id, "execution_package_id": pkg_id},
        {"_id": 0, "certified_total": 1}
    ).to_list(50)
    sub_certified = sum(l.get("certified_total", 0) for l in sub_lines)

    total_actual = round(mat_actual + lab_actual + sub_certified, 2)
    has_actuals = mat_actual > 0 or lab_actual > 0 or sub_certified > 0
    gross_margin = round(sale - total_actual, 2) if has_actuals else None
    margin_percent = round(gross_margin / sale * 100, 1) if sale > 0 and gross_margin is not None else None

    budget_total = pkg.get("budget_total", 0)
    expected_margin = round(sale - budget_total, 2) if budget_total > 0 else None
    margin_variance = round(gross_margin - expected_margin, 2) if gross_margin is not None and expected_margin is not None else None

    return {
        "execution_package_id": pkg_id,
        "activity_name": pkg.get("activity_name", ""),
        "unit": pkg.get("unit", ""),
        "qty": pkg.get("qty", 0),
        "currency": "EUR",
        "sale_total": sale,
        "budget": {
            "material": pkg.get("material_budget_total", 0),
            "labor": pkg.get("labor_budget_total", 0),
            "total": budget_total,
        },
        "actual": {
            "material": mat_actual,
            "labor": lab_actual,
            "subcontract": round(sub_certified, 2),
            "total": total_actual,
        },
        "margin": {
            "gross_margin": gross_margin,
            "margin_percent": margin_percent,
            "expected_margin": expected_margin,
            "margin_variance": margin_variance,
        },
        "progress_percent": pkg.get("progress_percent", 0),
        "metrics_partial": not has_actuals,
    }


@router.get("/execution-packages/financial-breakdown/{project_id}")
async def get_project_package_breakdown(project_id: str, user: dict = Depends(require_m2)):
    """All execution packages financial breakdown for a project"""
    org_id = user["org_id"]
    pkgs = await db.execution_packages.find({"org_id": org_id, "project_id": project_id}, {"_id": 0}).to_list(200)

    # Load subcontract by package
    sub_lines = await db.subcontractor_package_lines.find(
        {"org_id": org_id, "project_id": project_id},
        {"_id": 0, "execution_package_id": 1, "certified_total": 1}
    ).to_list(500)
    sub_by_pkg = {}
    for sl in sub_lines:
        ep_id = sl.get("execution_package_id")
        if ep_id:
            sub_by_pkg[ep_id] = sub_by_pkg.get(ep_id, 0) + sl.get("certified_total", 0)

    breakdown = []
    for pkg in pkgs:
        pid = pkg["id"]
        sale = pkg.get("sale_total", 0)
        mat = pkg.get("actual_material_cost", 0)
        lab = pkg.get("actual_labor_cost", 0)
        sub = round(sub_by_pkg.get(pid, 0), 2)
        total_actual = round(mat + lab + sub, 2)
        has_actuals = total_actual > 0
        margin = round(sale - total_actual, 2) if has_actuals else None

        breakdown.append({
            "id": pid,
            "activity_name": pkg.get("activity_name", ""),
            "sale_total": sale,
            "material_budget": pkg.get("material_budget_total", 0),
            "material_actual": mat,
            "material_variance": pkg.get("material_variance_value"),
            "labor_budget": pkg.get("labor_budget_total", 0),
            "labor_actual": lab,
            "labor_variance": pkg.get("labor_variance_value"),
            "subcontract_actual": sub,
            "total_actual": total_actual,
            "gross_margin": margin,
            "progress": pkg.get("progress_percent", 0),
            "status": pkg.get("status", ""),
        })

    return {"project_id": project_id, "packages": breakdown, "currency": "EUR"}


# ═══════════════════════════════════════════════════════════════════
# PHASE 5 — WARNINGS + SUMMARY HELPER
# ═══════════════════════════════════════════════════════════════════

@router.get("/material-warnings/{project_id}")
async def get_material_warnings(project_id: str, user: dict = Depends(require_m2)):
    """Material cost warnings for a project"""
    org_id = user["org_id"]
    pkgs = await db.execution_packages.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0}
    ).to_list(200)

    unmapped = await db.material_entries.count_documents(
        {"org_id": org_id, "project_id": project_id, "execution_package_id": None})
    total = await db.material_entries.count_documents(
        {"org_id": org_id, "project_id": project_id})

    warnings = []
    for pkg in pkgs:
        name = pkg.get("activity_name", "")
        budget = pkg.get("material_budget_total", 0)
        actual = pkg.get("actual_material_cost", 0)

        if budget == 0 and actual > 0:
            warnings.append({"type": "missing_material_budget", "package_id": pkg["id"], "activity": name,
                           "message": f"{name}: разход {actual} EUR без бюджет"})
        elif budget > 0 and actual > budget:
            over = round(actual - budget, 2)
            warnings.append({"type": "over_material_budget", "package_id": pkg["id"], "activity": name,
                           "message": f"{name}: {actual} EUR / {budget} EUR бюджет (+{over} EUR)"})

    if unmapped > 0:
        warnings.append({"type": "unmapped_material_entries", "message": f"{unmapped} от {total} материални записа нямат връзка към СМР"})

    return {"project_id": project_id, "warnings": warnings, "total_entries": total, "unmapped_entries": unmapped}


async def get_material_summary_for_project(org_id: str, project_id: str) -> dict:
    """Get aggregated material cost summary for profit integration"""
    mapped = await db.material_entries.find(
        {"org_id": org_id, "project_id": project_id, "execution_package_id": {"$ne": None}, "movement_type": {"$in": ["issue", "return"]}},
        {"_id": 0, "total_cost": 1}
    ).to_list(5000)
    mapped_cost = sum(float(e["total_cost"]) for e in mapped if e.get("total_cost") is not None)

    unmapped = await db.material_entries.find(
        {"org_id": org_id, "project_id": project_id, "execution_package_id": None, "movement_type": {"$in": ["issue", "return"]}},
        {"_id": 0, "total_cost": 1}
    ).to_list(5000)
    unmapped_cost = sum(float(e["total_cost"]) for e in unmapped if e.get("total_cost") is not None)

    pkgs = await db.execution_packages.find(
        {"org_id": org_id, "project_id": project_id},
        {"_id": 0, "material_budget_total": 1}
    ).to_list(200)
    budget = sum(p.get("material_budget_total", 0) for p in pkgs)

    total = round(mapped_cost + unmapped_cost, 2)
    return {
        "total_cost": total,
        "mapped_cost": round(mapped_cost, 2),
        "unmapped_cost": round(unmapped_cost, 2),
        "budget_total": round(budget, 2),
        "variance_value": round(total - budget, 2) if budget > 0 else None,
        "currency": "EUR",
        "has_data": len(mapped) + len(unmapped) > 0,
    }
