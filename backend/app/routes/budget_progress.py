"""
Routes - Execution Budget Freeze + Actual Progress Input.
Phase 1: Budget freeze
Phase 2: Progress updates
Phase 3: Progress history + current state
Phase 4: Progress vs cost comparison
Phase 5: Warnings + risk impact
Phase 6: Read models for UI readiness
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from datetime import datetime, timezone
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import require_m2

router = APIRouter(tags=["Budget Freeze / Progress"])


# ═══════════════════════════════════════════════════════════════════
# PHASE 1 — BUDGET FREEZE
# ═══════════════════════════════════════════════════════════════════

@router.post("/budget-freezes/{project_id}", status_code=201)
async def create_budget_freeze(project_id: str, data: dict = {}, user: dict = Depends(require_m2)):
    """Freeze current budget state for all execution packages in a project"""
    org_id = user["org_id"]
    project = await db.projects.find_one({"id": project_id, "org_id": org_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    pkgs = await db.execution_packages.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0}
    ).to_list(200)
    if not pkgs:
        raise HTTPException(status_code=400, detail="No execution packages to freeze")

    # Version check — increment from last freeze
    last = await db.budget_freezes.find_one(
        {"org_id": org_id, "project_id": project_id},
        sort=[("freeze_version", -1)]
    )
    version = (last.get("freeze_version", 0) + 1) if last else 1

    now = datetime.now(timezone.utc).isoformat()
    pkg_snapshots = []
    totals = {"material": 0, "labor": 0, "subcontract": 0, "overhead": 0, "planned_hours": 0}

    for pkg in pkgs:
        snap = {
            "execution_package_id": pkg["id"],
            "activity_name": pkg.get("activity_name", ""),
            "unit": pkg.get("unit", ""),
            "qty": pkg.get("qty", 0),
            "sale_total": pkg.get("sale_total", 0),
            "material_budget_total": pkg.get("material_budget_total", 0),
            "labor_budget_total": pkg.get("labor_budget_total", 0),
            "subcontract_budget_total": pkg.get("subcontract_budget_total", 0),
            "overhead_budget_total": pkg.get("overhead_budget_total", 0),
            "budget_total": pkg.get("budget_total", 0),
            "planned_margin": pkg.get("planned_margin", 0),
            "planned_hours": pkg.get("planned_hours"),
        }
        pkg_snapshots.append(snap)
        for k in ["material", "labor", "subcontract", "overhead"]:
            totals[k] += snap.get(f"{k}_budget_total", 0)
        totals["planned_hours"] += snap.get("planned_hours") or 0

    freeze = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "project_id": project_id,
        "freeze_version": version,
        "frozen_at": now,
        "frozen_by": user["id"],
        "label": data.get("label", f"v{version}"),
        "source_offer_id": data.get("source_offer_id"),
        "package_count": len(pkg_snapshots),
        "packages": pkg_snapshots,
        "totals": {
            "material_budget": round(totals["material"], 2),
            "labor_budget": round(totals["labor"], 2),
            "subcontract_budget": round(totals["subcontract"], 2),
            "overhead_budget": round(totals["overhead"], 2),
            "total_budget": round(sum(totals[k] for k in ["material", "labor", "subcontract", "overhead"]), 2),
            "planned_hours": round(totals["planned_hours"], 1),
            "total_sale": round(sum(s["sale_total"] for s in pkg_snapshots), 2),
        },
        "currency": "EUR",
    }
    await db.budget_freezes.insert_one(freeze)
    return {k: v for k, v in freeze.items() if k != "_id"}


@router.get("/budget-freezes/{project_id}")
async def list_budget_freezes(project_id: str, user: dict = Depends(require_m2)):
    q = {"org_id": user["org_id"], "project_id": project_id}
    freezes = await db.budget_freezes.find(q, {"_id": 0}).sort("freeze_version", -1).to_list(50)
    return freezes


@router.get("/budget-freezes/{project_id}/latest")
async def get_latest_budget_freeze(project_id: str, user: dict = Depends(require_m2)):
    freeze = await db.budget_freezes.find_one(
        {"org_id": user["org_id"], "project_id": project_id},
        {"_id": 0}, sort=[("freeze_version", -1)]
    )
    if not freeze:
        raise HTTPException(status_code=404, detail="No budget freeze found")
    return freeze


# ═══════════════════════════════════════════════════════════════════
# PHASE 2 — ACTUAL PROGRESS INPUT
# ═══════════════════════════════════════════════════════════════════

@router.post("/progress-updates", status_code=201)
async def create_progress_update(data: dict, user: dict = Depends(require_m2)):
    """Record actual progress for an execution package"""
    org_id = user["org_id"]
    pkg_id = data.get("execution_package_id")
    if not pkg_id:
        raise HTTPException(status_code=400, detail="execution_package_id required")

    pkg = await db.execution_packages.find_one({"id": pkg_id, "org_id": org_id})
    if not pkg:
        raise HTTPException(status_code=404, detail="Execution package not found")

    progress = float(data.get("progress_percent_actual", 0))
    if progress < 0 or progress > 100:
        raise HTTPException(status_code=400, detail="Progress must be 0-100")

    now = datetime.now(timezone.utc).isoformat()
    update = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "project_id": pkg["project_id"],
        "execution_package_id": pkg_id,
        "date": data.get("date", now[:10]),
        "progress_percent_actual": progress,
        "note": data.get("note", ""),
        "updated_by": user["id"],
        "source": data.get("source", "manual"),
        "created_at": now,
    }
    await db.progress_updates.insert_one(update)

    # Update execution package with latest progress
    await db.execution_packages.update_one({"id": pkg_id}, {"$set": {
        "progress_percent": progress,
        "progress_last_updated_at": now,
        "progress_source": update["source"],
        "updated_at": now,
    }})

    return {k: v for k, v in update.items() if k != "_id"}


@router.get("/progress-updates")
async def list_progress_updates(
    project_id: Optional[str] = None,
    execution_package_id: Optional[str] = None,
    user: dict = Depends(require_m2),
):
    q = {"org_id": user["org_id"]}
    if project_id: q["project_id"] = project_id
    if execution_package_id: q["execution_package_id"] = execution_package_id
    return await db.progress_updates.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)


# ═══════════════════════════════════════════════════════════════════
# PHASE 3 — PROGRESS HISTORY + CURRENT STATE
# ═══════════════════════════════════════════════════════════════════

@router.get("/progress-updates/{pkg_id}/latest")
async def get_latest_progress(pkg_id: str, user: dict = Depends(require_m2)):
    """Get latest progress update for an execution package"""
    update = await db.progress_updates.find_one(
        {"org_id": user["org_id"], "execution_package_id": pkg_id},
        {"_id": 0}, sort=[("created_at", -1)]
    )
    if not update:
        return {"execution_package_id": pkg_id, "has_progress": False}
    return {**update, "has_progress": True}


@router.get("/progress-updates/{pkg_id}/history")
async def get_progress_history(pkg_id: str, user: dict = Depends(require_m2)):
    """Get full progress history for an execution package"""
    history = await db.progress_updates.find(
        {"org_id": user["org_id"], "execution_package_id": pkg_id},
        {"_id": 0}
    ).sort("created_at", 1).to_list(200)

    # Load user names
    user_ids = list(set(h.get("updated_by", "") for h in history if h.get("updated_by")))
    users = await db.users.find({"id": {"$in": user_ids}}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1}).to_list(50)
    name_map = {u["id"]: f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() for u in users}

    for h in history:
        h["updated_by_name"] = name_map.get(h.get("updated_by", ""), "")

    return {"execution_package_id": pkg_id, "entries": history, "count": len(history)}


# ═══════════════════════════════════════════════════════════════════
# PHASE 4 — PROGRESS VS COST COMPARISON
# ═══════════════════════════════════════════════════════════════════

@router.get("/progress-comparison/{pkg_id}")
async def get_progress_vs_cost(pkg_id: str, user: dict = Depends(require_m2)):
    """Compare physical progress vs cost usage for an execution package"""
    org_id = user["org_id"]
    pkg = await db.execution_packages.find_one({"id": pkg_id, "org_id": org_id}, {"_id": 0})
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")

    actual_progress = pkg.get("progress_percent", 0) or 0
    has_progress = pkg.get("progress_last_updated_at") is not None

    # Labor usage %
    planned_hours = pkg.get("planned_hours")
    used_hours = pkg.get("used_hours", 0)
    labor_usage_pct = round(used_hours / planned_hours * 100, 1) if planned_hours and planned_hours > 0 else None

    # Material usage %
    mat_budget = pkg.get("material_budget_total", 0)
    mat_actual = pkg.get("actual_material_cost", 0)
    material_usage_pct = round(mat_actual / mat_budget * 100, 1) if mat_budget > 0 else None

    # Subcontract progress proxy
    sub_lines = await db.subcontractor_package_lines.find(
        {"org_id": org_id, "execution_package_id": pkg_id},
        {"_id": 0, "assigned_qty": 1, "certified_qty": 1}
    ).to_list(50)
    if sub_lines:
        total_assigned = sum(l.get("assigned_qty", 0) for l in sub_lines)
        total_certified = sum(l.get("certified_qty", 0) for l in sub_lines)
        sub_progress_pct = round(total_certified / total_assigned * 100, 1) if total_assigned > 0 else None
    else:
        sub_progress_pct = None

    # Gaps (positive = cost ahead of progress, negative = cost behind progress)
    labor_gap = round(labor_usage_pct - actual_progress, 1) if labor_usage_pct is not None and has_progress else None
    material_gap = round(material_usage_pct - actual_progress, 1) if material_usage_pct is not None and has_progress else None
    sub_gap = round(sub_progress_pct - actual_progress, 1) if sub_progress_pct is not None and has_progress else None

    return {
        "execution_package_id": pkg_id,
        "activity_name": pkg.get("activity_name", ""),
        "progress": {
            "actual_percent": actual_progress,
            "has_update": has_progress,
            "last_updated": pkg.get("progress_last_updated_at"),
            "source": pkg.get("progress_source"),
        },
        "usage": {
            "labor_percent": labor_usage_pct,
            "material_percent": material_usage_pct,
            "subcontract_percent": sub_progress_pct,
        },
        "gaps": {
            "labor_vs_progress": labor_gap,
            "material_vs_progress": material_gap,
            "subcontract_vs_progress": sub_gap,
        },
        "raw": {
            "planned_hours": planned_hours,
            "used_hours": used_hours,
            "material_budget": mat_budget,
            "material_actual": mat_actual,
        },
        "metrics_partial": not has_progress or labor_usage_pct is None,
    }


# ═══════════════════════════════════════════════════════════════════
# PHASE 5 — WARNINGS + RISK IMPACT
# ═══════════════════════════════════════════════════════════════════

@router.get("/progress-warnings/{project_id}")
async def get_progress_warnings(project_id: str, user: dict = Depends(require_m2)):
    """Progress deviation warnings for a project"""
    org_id = user["org_id"]
    pkgs = await db.execution_packages.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0}
    ).to_list(200)

    warnings = []
    missing_updates = 0

    for pkg in pkgs:
        name = pkg.get("activity_name", "")
        progress = pkg.get("progress_percent", 0) or 0
        has_update = pkg.get("progress_last_updated_at") is not None

        if not has_update:
            missing_updates += 1
            continue

        # Labor ahead of progress
        planned_h = pkg.get("planned_hours")
        used_h = pkg.get("used_hours", 0)
        if planned_h and planned_h > 0:
            labor_pct = used_h / planned_h * 100
            if labor_pct > progress + 15:
                warnings.append({
                    "type": "labor_ahead_of_progress",
                    "severity": "warning",
                    "package_id": pkg["id"],
                    "activity": name,
                    "message": f"{name}: труд {round(labor_pct, 1)}% vs прогрес {progress}%",
                })

        # Material ahead of progress
        mat_bud = pkg.get("material_budget_total", 0)
        mat_act = pkg.get("actual_material_cost", 0)
        if mat_bud > 0:
            mat_pct = mat_act / mat_bud * 100
            if mat_pct > progress + 20:
                warnings.append({
                    "type": "materials_ahead_of_progress",
                    "severity": "warning",
                    "package_id": pkg["id"],
                    "activity": name,
                    "message": f"{name}: материали {round(mat_pct, 1)}% vs прогрес {progress}%",
                })

        # Progress lag (low progress with significant cost)
        total_cost_pct = 0
        if pkg.get("budget_total", 0) > 0:
            actual_total = (pkg.get("actual_material_cost", 0) or 0) + (pkg.get("actual_labor_cost", 0) or 0)
            total_cost_pct = actual_total / pkg["budget_total"] * 100
        if progress < 20 and total_cost_pct > 40:
            warnings.append({
                "type": "progress_lag",
                "severity": "critical",
                "package_id": pkg["id"],
                "activity": name,
                "message": f"{name}: прогрес {progress}% но разход {round(total_cost_pct, 1)}% от бюджет",
            })

    if missing_updates > 0:
        warnings.append({
            "type": "missing_progress_updates",
            "severity": "info",
            "message": f"{missing_updates} от {len(pkgs)} пакета нямат въведен прогрес",
        })

    # Budget burn warnings from work_sessions
    budgets = await db.activity_budgets.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0}
    ).to_list(100)
    sessions = await db.work_sessions.find(
        {"org_id": org_id, "site_id": project_id, "ended_at": {"$ne": None}},
        {"_id": 0, "labor_cost": 1},
    ).to_list(5000)
    total_session_cost = sum(s.get("labor_cost", 0) for s in sessions)
    total_labor_budget = sum(b.get("labor_budget", 0) for b in budgets)
    if total_labor_budget > 0:
        burn_pct = total_session_cost / total_labor_budget * 100
        overall_progress = sum(p.get("progress_percent", 0) for p in pkgs) / max(len(pkgs), 1)
        if burn_pct > 100:
            warnings.append({"type": "budget_overrun", "severity": "critical", "message": f"Бюджетът за труд е надхвърлен: {round(burn_pct, 1)}%"})
        elif burn_pct > 80 and overall_progress < 50:
            warnings.append({"type": "budget_burn_high", "severity": "warning", "message": f"Бюджетът е {round(burn_pct, 1)}% изхарчен при {round(overall_progress, 1)}% прогрес"})

    return {
        "project_id": project_id,
        "warnings": warnings,
        "total": len(warnings),
        "packages_total": len(pkgs),
        "packages_with_progress": len(pkgs) - missing_updates,
        "packages_without_progress": missing_updates,
    }


async def get_progress_risk(org_id: str, project_id: str) -> dict:
    """Get progress risk flags for integration into project risk"""
    pkgs = await db.execution_packages.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0}
    ).to_list(200)
    if not pkgs:
        return {"available": False, "flags": []}

    total = len(pkgs)
    with_progress = sum(1 for p in pkgs if p.get("progress_last_updated_at"))
    missing = total - with_progress

    flags = []
    if missing == total:
        flags.append("no_progress_data")
    elif missing > total * 0.5:
        flags.append("insufficient_progress_data")

    # Check for lag
    for pkg in pkgs:
        progress = pkg.get("progress_percent", 0) or 0
        budget = pkg.get("budget_total", 0)
        actual = (pkg.get("actual_material_cost", 0) or 0) + (pkg.get("actual_labor_cost", 0) or 0)
        if budget > 0 and progress < 20 and actual > budget * 0.4:
            flags.append("critical_progress_lag")
            break

    return {"available": True, "flags": flags, "with_progress": with_progress, "total": total}


# ═══════════════════════════════════════════════════════════════════
# PHASE 6 — READ MODELS FOR UI READINESS
# ═══════════════════════════════════════════════════════════════════

@router.get("/project-progress-summary/{project_id}")
async def get_project_progress_summary(project_id: str, user: dict = Depends(require_m2)):
    """Project-level progress summary across all execution packages"""
    org_id = user["org_id"]
    pkgs = await db.execution_packages.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0}
    ).to_list(200)

    if not pkgs:
        return {"project_id": project_id, "packages": [], "summary": {}}

    total_sale = sum(p.get("sale_total", 0) for p in pkgs)
    weighted_progress = 0
    with_progress = 0

    package_summaries = []
    for pkg in pkgs:
        progress = pkg.get("progress_percent", 0) or 0
        sale = pkg.get("sale_total", 0)
        has_update = pkg.get("progress_last_updated_at") is not None

        if has_update:
            with_progress += 1
            if total_sale > 0:
                weighted_progress += progress * (sale / total_sale)

        package_summaries.append({
            "id": pkg["id"],
            "activity_name": pkg.get("activity_name", ""),
            "qty": pkg.get("qty", 0),
            "unit": pkg.get("unit", ""),
            "progress_percent": progress,
            "has_progress_update": has_update,
            "last_updated": pkg.get("progress_last_updated_at"),
            "sale_total": sale,
            "used_hours": pkg.get("used_hours", 0),
            "planned_hours": pkg.get("planned_hours"),
            "status": pkg.get("status", ""),
        })

    # Latest freeze for comparison
    freeze = await db.budget_freezes.find_one(
        {"org_id": org_id, "project_id": project_id},
        {"_id": 0, "freeze_version": 1, "frozen_at": 1, "totals": 1},
        sort=[("freeze_version", -1)]
    )

    return {
        "project_id": project_id,
        "currency": "EUR",
        "packages": package_summaries,
        "summary": {
            "total_packages": len(pkgs),
            "packages_with_progress": with_progress,
            "weighted_progress_percent": round(weighted_progress, 1),
            "total_sale": round(total_sale, 2),
        },
        "budget_freeze": {
            "version": freeze.get("freeze_version") if freeze else None,
            "frozen_at": freeze.get("frozen_at") if freeze else None,
            "totals": freeze.get("totals") if freeze else None,
        } if freeze else None,
    }
