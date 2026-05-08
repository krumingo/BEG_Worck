"""
Routes - Labor by SMR / Execution Package.
Phase 1: Time entry linkage to execution packages
Phase 2: Planned hours engine
Phase 3: Actual labor cost by execution package
Phase 4: Variance + progress + warnings
Phase 5: Project/profit integration
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from datetime import datetime, timezone
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import require_m2

router = APIRouter(tags=["Labor by SMR"])


# ═══════════════════════════════════════════════════════════════════
# PHASE 1 — TIME ENTRY LINKAGE
# ═══════════════════════════════════════════════════════════════════

@router.post("/labor-entries", status_code=201)
async def create_labor_entry(data: dict, user: dict = Depends(require_m2)):
    """Create a labor time entry linked to an execution package"""
    org_id = user["org_id"]
    now = datetime.now(timezone.utc).isoformat()

    entry = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "project_id": data.get("project_id"),
        "employee_id": data.get("employee_id", user["id"]),
        "execution_package_id": data.get("execution_package_id"),
        "offer_line_id": data.get("offer_line_id"),
        "work_report_id": data.get("work_report_id"),
        "date": data.get("date", now[:10]),
        "hours": float(data.get("hours", 0)),
        "activity_name": data.get("activity_name", ""),
        "note": data.get("note", ""),
        "hourly_rate": None,  # populated by aggregator
        "labor_cost": None,
        "source": data.get("source", "manual"),
        "created_at": now,
    }

    # Resolve hourly rate
    profile = await db.employee_profiles.find_one({"org_id": org_id, "user_id": entry["employee_id"]}, {"_id": 0, "hourly_rate": 1})
    if profile and profile.get("hourly_rate"):
        entry["hourly_rate"] = profile["hourly_rate"]
        entry["labor_cost"] = round(entry["hours"] * profile["hourly_rate"], 2)

    await db.labor_entries.insert_one(entry)
    return {k: v for k, v in entry.items() if k != "_id"}


@router.post("/labor-entries/sync-from-work-reports")
async def sync_labor_entries_from_work_reports(data: dict, user: dict = Depends(require_m2)):
    """Sync labor entries from existing work reports for a project, with optional execution package mapping"""
    org_id = user["org_id"]
    project_id = data.get("project_id")
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id required")

    # Load execution packages for name-based mapping
    exec_pkgs = await db.execution_packages.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0, "id": 1, "activity_name": 1, "offer_line_id": 1}
    ).to_list(200)
    pkg_by_name = {}
    for ep in exec_pkgs:
        name = (ep.get("activity_name") or "").lower().strip()
        if name:
            pkg_by_name[name] = ep

    # Load employee rates
    profiles = await db.employee_profiles.find({"org_id": org_id}, {"_id": 0, "user_id": 1, "hourly_rate": 1}).to_list(200)
    rate_map = {p["user_id"]: p.get("hourly_rate", 0) or 0 for p in profiles}

    # Load work reports
    reports = await db.work_reports.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0}
    ).to_list(1000)

    # Clear old synced entries for this project
    await db.labor_entries.delete_many({"org_id": org_id, "project_id": project_id, "source": "work_report_sync"})

    now = datetime.now(timezone.utc).isoformat()
    created = 0

    for wr in reports:
        uid = wr["user_id"]
        rate = rate_map.get(uid, 0)
        for line in wr.get("lines", []):
            hours = float(line.get("hours", 0))
            if hours <= 0:
                continue

            act_name = line.get("activity_name", "")
            act_lower = act_name.lower().strip()

            # Try to match execution package
            matched_pkg = pkg_by_name.get(act_lower)
            ep_id = matched_pkg["id"] if matched_pkg else None
            ol_id = matched_pkg.get("offer_line_id") if matched_pkg else None

            entry = {
                "id": str(uuid.uuid4()),
                "org_id": org_id,
                "project_id": project_id,
                "employee_id": uid,
                "execution_package_id": ep_id,
                "offer_line_id": ol_id,
                "work_report_id": wr["id"],
                "date": wr.get("date", ""),
                "hours": hours,
                "activity_name": act_name,
                "note": line.get("note", ""),
                "hourly_rate": rate if rate > 0 else None,
                "labor_cost": round(hours * rate, 2) if rate > 0 else None,
                "source": "work_report_sync",
                "mapped": ep_id is not None,
                "created_at": now,
            }
            await db.labor_entries.insert_one(entry)
            created += 1

    return {"ok": True, "synced": created, "project_id": project_id}


@router.get("/labor-entries")
async def list_labor_entries(
    project_id: Optional[str] = None,
    execution_package_id: Optional[str] = None,
    employee_id: Optional[str] = None,
    user: dict = Depends(require_m2),
):
    q = {"org_id": user["org_id"]}
    if project_id: q["project_id"] = project_id
    if execution_package_id: q["execution_package_id"] = execution_package_id
    if employee_id: q["employee_id"] = employee_id
    entries = await db.labor_entries.find(q, {"_id": 0}).sort("date", -1).to_list(500)
    return entries


# ═══════════════════════════════════════════════════════════════════
# PHASE 2 — PLANNED HOURS ENGINE
# ═══════════════════════════════════════════════════════════════════

@router.post("/execution-packages/recompute-labor/{project_id}")
async def recompute_execution_package_labor(project_id: str, user: dict = Depends(require_m2)):
    """Recompute planned hours and labor budget for execution packages"""
    org_id = user["org_id"]
    pkgs = await db.execution_packages.find({"org_id": org_id, "project_id": project_id}, {"_id": 0}).to_list(200)
    if not pkgs:
        return {"ok": True, "updated": 0}

    # Load offer lines for labor_hours_per_unit
    offer_ids = list(set(p.get("source_offer_id") for p in pkgs if p.get("source_offer_id")))
    offers = await db.offers.find({"id": {"$in": offer_ids}}, {"_id": 0, "lines": 1}).to_list(20)
    offer_line_map = {}
    for o in offers:
        for l in o.get("lines", []):
            if l.get("id"):
                offer_line_map[l["id"]] = l

    # Load org worker rates for estimation
    settings = await db.settings.find_one({"_id": "worker_rates", "org_id": org_id})
    default_rate = 18  # EUR/h fallback

    # Aggregate used hours from labor_entries
    entries = await db.labor_entries.find({"org_id": org_id, "project_id": project_id}, {"_id": 0, "execution_package_id": 1, "hours": 1, "labor_cost": 1}).to_list(5000)
    used_by_pkg = {}
    cost_by_pkg = {}
    for e in entries:
        ep_id = e.get("execution_package_id")
        if ep_id:
            used_by_pkg[ep_id] = used_by_pkg.get(ep_id, 0) + float(e.get("hours", 0))
            if e.get("labor_cost") is not None:
                cost_by_pkg[ep_id] = cost_by_pkg.get(ep_id, 0) + float(e["labor_cost"])

    updated = 0
    for pkg in pkgs:
        ol = offer_line_map.get(pkg.get("offer_line_id"), {})
        labor_hours_per_unit = ol.get("labor_hours_per_unit")
        qty = pkg.get("qty", 0)

        # Planned hours
        if labor_hours_per_unit and labor_hours_per_unit > 0:
            planned_hours = round(qty * labor_hours_per_unit, 1)
            planned_hours_source = "offer_line"
        elif pkg.get("labor_budget_total", 0) > 0:
            # Estimate from budget: budget / default_rate
            planned_hours = round(pkg["labor_budget_total"] / default_rate, 1)
            planned_hours_source = "budget_estimate"
        else:
            planned_hours = None
            planned_hours_source = "unavailable"

        used_hours = round(used_by_pkg.get(pkg["id"], 0), 1)
        labor_actual_cost = round(cost_by_pkg.get(pkg["id"], 0), 2)

        remaining_hours = round(planned_hours - used_hours, 1) if planned_hours is not None else None
        progress_by_hours = round(used_hours / planned_hours * 100, 1) if planned_hours and planned_hours > 0 else None

        labor_budget = pkg.get("labor_budget_total", 0)
        labor_variance_value = round(labor_actual_cost - labor_budget, 2) if labor_budget > 0 else None
        labor_variance_percent = round(labor_variance_value / labor_budget * 100, 1) if labor_budget > 0 and labor_variance_value is not None else None

        update_fields = {
            "planned_hours": planned_hours,
            "planned_hours_source": planned_hours_source,
            "used_hours": used_hours,
            "remaining_hours": remaining_hours,
            "progress_percent_by_hours": progress_by_hours,
            "actual_labor_cost": labor_actual_cost,
            "labor_variance_value": labor_variance_value,
            "labor_variance_percent": labor_variance_percent,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.execution_packages.update_one({"id": pkg["id"]}, {"$set": update_fields})
        updated += 1

    return {"ok": True, "updated": updated}


# ═══════════════════════════════════════════════════════════════════
# PHASE 3 — ACTUAL LABOR COST BY EXECUTION PACKAGE
# ═══════════════════════════════════════════════════════════════════

@router.get("/labor-cost/by-execution-package/{pkg_id}")
async def get_labor_cost_by_exec_pkg(pkg_id: str, user: dict = Depends(require_m2)):
    """Detailed labor cost breakdown for an execution package"""
    org_id = user["org_id"]
    pkg = await db.execution_packages.find_one({"id": pkg_id, "org_id": org_id}, {"_id": 0})
    if not pkg:
        raise HTTPException(status_code=404, detail="Execution package not found")

    entries = await db.labor_entries.find(
        {"org_id": org_id, "execution_package_id": pkg_id}, {"_id": 0}
    ).sort("date", -1).to_list(500)

    # Load employee names
    emp_ids = list(set(e["employee_id"] for e in entries))
    users = await db.users.find({"id": {"$in": emp_ids}}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1}).to_list(50)
    name_map = {u["id"]: f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() for u in users}

    total_hours = 0
    total_cost = 0
    by_employee = {}
    by_date = {}
    partial_cost = False

    for e in entries:
        h = float(e.get("hours", 0))
        c = e.get("labor_cost")
        total_hours += h
        if c is not None:
            total_cost += c
        else:
            partial_cost = True

        uid = e["employee_id"]
        if uid not in by_employee:
            by_employee[uid] = {"employee_id": uid, "name": name_map.get(uid, ""), "hours": 0, "cost": 0, "rate": e.get("hourly_rate")}
        by_employee[uid]["hours"] += h
        if c is not None:
            by_employee[uid]["cost"] += c

        d = e.get("date", "")
        if d not in by_date:
            by_date[d] = {"date": d, "hours": 0, "cost": 0}
        by_date[d]["hours"] += h
        if c is not None:
            by_date[d]["cost"] += c

    for v in by_employee.values():
        v["hours"] = round(v["hours"], 1)
        v["cost"] = round(v["cost"], 2)
    for v in by_date.values():
        v["hours"] = round(v["hours"], 1)
        v["cost"] = round(v["cost"], 2)

    return {
        "execution_package_id": pkg_id,
        "activity_name": pkg.get("activity_name", ""),
        "planned_hours": pkg.get("planned_hours"),
        "used_hours": round(total_hours, 1),
        "remaining_hours": round(pkg["planned_hours"] - total_hours, 1) if pkg.get("planned_hours") is not None else None,
        "labor_budget": pkg.get("labor_budget_total", 0),
        "labor_actual_cost": round(total_cost, 2),
        "labor_variance": round(total_cost - pkg.get("labor_budget_total", 0), 2) if pkg.get("labor_budget_total", 0) > 0 else None,
        "currency": "EUR",
        "entries_count": len(entries),
        "partial_cost_data": partial_cost,
        "by_employee": sorted(by_employee.values(), key=lambda x: x["cost"], reverse=True),
        "by_date": sorted(by_date.values(), key=lambda x: x["date"], reverse=True),
    }


# ═══════════════════════════════════════════════════════════════════
# PHASE 4 — VARIANCE + PROGRESS + WARNINGS
# ═══════════════════════════════════════════════════════════════════

@router.get("/labor-warnings/{project_id}")
async def get_labor_warnings(project_id: str, user: dict = Depends(require_m2)):
    """Get labor warnings for all execution packages in a project"""
    org_id = user["org_id"]
    pkgs = await db.execution_packages.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0}
    ).to_list(200)

    # Count unmapped entries
    unmapped = await db.labor_entries.count_documents(
        {"org_id": org_id, "project_id": project_id, "execution_package_id": None}
    )
    total_entries = await db.labor_entries.count_documents(
        {"org_id": org_id, "project_id": project_id}
    )

    warnings = []
    pkg_summaries = []

    for pkg in pkgs:
        planned = pkg.get("planned_hours")
        used = pkg.get("used_hours", 0)
        budget = pkg.get("labor_budget_total", 0)
        actual = pkg.get("actual_labor_cost", 0)
        name = pkg.get("activity_name", "")

        flags = []
        if planned is None:
            flags.append("missing_planned_hours")
        elif used > planned:
            flags.append("over_hours")
            warnings.append({"type": "over_hours", "package_id": pkg["id"], "activity": name,
                           "message": f"{name}: {used}h / {planned}h planned ({round(used - planned, 1)}h over)"})
        if budget > 0 and actual > budget:
            flags.append("over_labor_budget")
            warnings.append({"type": "over_labor_budget", "package_id": pkg["id"], "activity": name,
                           "message": f"{name}: {actual} EUR / {budget} EUR budget ({round(actual - budget, 2)} EUR over)"})

        pkg_summaries.append({
            "id": pkg["id"],
            "activity_name": name,
            "planned_hours": planned,
            "used_hours": used,
            "remaining_hours": pkg.get("remaining_hours"),
            "progress_by_hours": pkg.get("progress_percent_by_hours"),
            "labor_budget": budget,
            "labor_actual": actual,
            "variance_value": pkg.get("labor_variance_value"),
            "variance_percent": pkg.get("labor_variance_percent"),
            "flags": flags,
        })

    if unmapped > 0:
        warnings.append({"type": "unmapped_time_entries", "message": f"{unmapped} от {total_entries} записа за труд нямат връзка към СМР/пакет"})

    return {
        "project_id": project_id,
        "warnings": warnings,
        "packages": pkg_summaries,
        "total_entries": total_entries,
        "unmapped_entries": unmapped,
        "metrics_available": {
            "labor_entries": total_entries > 0,
            "execution_packages": len(pkgs) > 0,
            "planned_hours": any(p.get("planned_hours") is not None for p in pkgs),
        },
    }


# ═══════════════════════════════════════════════════════════════════
# PHASE 5 — PROJECT LABOR SUMMARY (for profit integration)
# ═══════════════════════════════════════════════════════════════════

async def get_labor_summary_for_project(org_id: str, project_id: str) -> dict:
    """Get aggregated labor summary for project profit integration"""
    # Mapped labor (linked to execution packages)
    mapped = await db.labor_entries.find(
        {"org_id": org_id, "project_id": project_id, "execution_package_id": {"$ne": None}},
        {"_id": 0, "hours": 1, "labor_cost": 1}
    ).to_list(5000)
    mapped_hours = sum(float(e.get("hours", 0)) for e in mapped)
    mapped_cost = sum(float(e["labor_cost"]) for e in mapped if e.get("labor_cost") is not None)

    # Unmapped labor
    unmapped = await db.labor_entries.find(
        {"org_id": org_id, "project_id": project_id, "execution_package_id": None},
        {"_id": 0, "hours": 1, "labor_cost": 1}
    ).to_list(5000)
    unmapped_hours = sum(float(e.get("hours", 0)) for e in unmapped)
    unmapped_cost = sum(float(e["labor_cost"]) for e in unmapped if e.get("labor_cost") is not None)

    # Budget from execution packages
    pkgs = await db.execution_packages.find(
        {"org_id": org_id, "project_id": project_id},
        {"_id": 0, "labor_budget_total": 1, "planned_hours": 1}
    ).to_list(200)
    total_budget = sum(p.get("labor_budget_total", 0) for p in pkgs)
    total_planned_hours = sum(p.get("planned_hours", 0) or 0 for p in pkgs)

    total_cost = round(mapped_cost + unmapped_cost, 2)
    total_hours = round(mapped_hours + unmapped_hours, 1)

    return {
        "total_hours": total_hours,
        "total_cost": total_cost,
        "mapped_hours": round(mapped_hours, 1),
        "mapped_cost": round(mapped_cost, 2),
        "unmapped_hours": round(unmapped_hours, 1),
        "unmapped_cost": round(unmapped_cost, 2),
        "budget_total": round(total_budget, 2),
        "planned_hours_total": round(total_planned_hours, 1),
        "variance_value": round(total_cost - total_budget, 2) if total_budget > 0 else None,
        "currency": "EUR",
        "has_data": len(mapped) + len(unmapped) > 0,
    }
