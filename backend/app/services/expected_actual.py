"""
Service - Expected vs Actual comparison layer.
Compares planned (budgets/analyses) vs real (work_sessions) by activity, group, location.
"""
from app.db import db
from app.routes.activity_budgets import compute_avg_daily_wage, DEFAULT_DAILY_WAGE


def _status(actual, planned):
    if planned <= 0:
        return "on_track" if actual <= 0 else "over"
    pct = actual / planned * 100
    if pct > 100:
        return "over"
    if pct >= 80:
        return "warning"
    return "on_track"


def _variance_pct(actual, planned):
    if planned <= 0:
        return 0
    return round((actual - planned) / planned * 100, 1)


async def build_expected_actual(org_id: str, project_id: str, date_from: str = None, date_to: str = None) -> dict:
    # ── Compute real hourly rate for this project ────────────────
    avg_daily = await compute_avg_daily_wage(org_id, project_id)
    hourly_rate = round(avg_daily / 8, 2) if avg_daily > 0 else round(DEFAULT_DAILY_WAGE / 8, 2)

    # ── Planned data ────────────────────────────────────────────
    budgets = await db.activity_budgets.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0}
    ).to_list(200)

    planned_by_type = {}
    for b in budgets:
        key = b.get("type", "Общо")
        if key not in planned_by_type:
            planned_by_type[key] = {"hours": 0, "cost": 0}
        lb = b.get("labor_budget", 0)
        planned_by_type[key]["cost"] += lb
        # Prefer snapshot planned_man_hours if available, else compute on-the-fly
        snapshot_hours = b.get("planned_man_hours")
        if snapshot_hours is not None:
            planned_by_type[key]["hours"] += snapshot_hours
        else:
            coeff = b.get("coefficient", 1) or 1
            planned_by_type[key]["hours"] += round(lb / hourly_rate / coeff, 1) if lb > 0 else 0

    # ── Actual data (work_sessions) ─────────────────────────────
    ws_query = {"org_id": org_id, "site_id": project_id, "ended_at": {"$ne": None}}
    if date_from:
        ws_query.setdefault("started_at", {})["$gte"] = f"{date_from}T00:00:00"
    if date_to:
        ws_query.setdefault("started_at", {})["$lte"] = f"{date_to}T23:59:59"

    sessions = await db.work_sessions.find(ws_query, {"_id": 0, "smr_type_id": 1, "duration_hours": 1, "labor_cost": 1}).to_list(5000)

    actual_by_type = {}
    for s in sessions:
        key = s.get("smr_type_id") or "Общо"
        if key not in actual_by_type:
            actual_by_type[key] = {"hours": 0, "cost": 0}
        actual_by_type[key]["hours"] += s.get("duration_hours", 0)
        actual_by_type[key]["cost"] += s.get("labor_cost", 0)

    # ── A. By Activity ──────────────────────────────────────────
    all_types = set(list(planned_by_type.keys()) + list(actual_by_type.keys()))
    activities = []
    for t in sorted(all_types):
        pl = planned_by_type.get(t, {"hours": 0, "cost": 0})
        ac = actual_by_type.get(t, {"hours": 0, "cost": 0})
        activities.append({
            "name": t,
            "planned_hours": round(pl["hours"], 1),
            "actual_hours": round(ac["hours"], 1),
            "variance_hours": round(ac["hours"] - pl["hours"], 1),
            "variance_hours_pct": _variance_pct(ac["hours"], pl["hours"]),
            "planned_cost": round(pl["cost"], 2),
            "actual_cost": round(ac["cost"], 2),
            "variance_cost": round(ac["cost"] - pl["cost"], 2),
            "status": _status(ac["cost"], pl["cost"]) if pl["cost"] > 0 else _status(ac["hours"], pl["hours"]),
        })

    # ── B. By Group ─────────────────────────────────────────────
    groups_data = await db.smr_groups.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0, "id": 1, "name": 1}
    ).to_list(100)

    groups = []
    for g in groups_data:
        # Get lines in group from analyses
        analyses = await db.smr_analyses.find(
            {"org_id": org_id, "project_id": project_id, "lines.group_id": g["id"]}, {"_id": 0, "lines": 1}
        ).to_list(50)
        planned_h = 0
        planned_c = 0
        for a in analyses:
            for ln in a.get("lines", []):
                if ln.get("group_id") == g["id"] and ln.get("is_active", True):
                    planned_c += ln.get("final_total", 0)
                    planned_h += (ln.get("labor_price_per_unit", 0) * ln.get("qty", 0)) / hourly_rate if ln.get("labor_price_per_unit") else 0

        # Actual from sessions with matching smr_type
        actual_h = 0
        actual_c = 0
        # Simplified: sum all sessions for project (group-level tracking requires smr_type matching)
        # For now, distribute proportionally
        total_planned = sum(a.get("planned_cost", 0) for a in activities) or 1
        if planned_c > 0:
            ratio = planned_c / total_planned
            total_actual_h = sum(s.get("duration_hours", 0) for s in sessions)
            total_actual_c = sum(s.get("labor_cost", 0) for s in sessions)
            actual_h = round(total_actual_h * ratio, 1)
            actual_c = round(total_actual_c * ratio, 2)

        groups.append({
            "name": g["name"], "group_id": g["id"],
            "planned_hours": round(planned_h, 1), "actual_hours": actual_h,
            "variance_hours": round(actual_h - planned_h, 1),
            "planned_cost": round(planned_c, 2), "actual_cost": actual_c,
            "variance_cost": round(actual_c - planned_c, 2),
            "status": _status(actual_c, planned_c),
        })

    # ── C. By Location ──────────────────────────────────────────
    locations_data = await db.location_nodes.find(
        {"org_id": org_id, "project_id": project_id, "type": {"$in": ["room", "floor"]}},
        {"_id": 0, "id": 1, "name": 1, "type": 1},
    ).to_list(100)

    locations = []
    for loc in locations_data:
        # Count analyses lines with this location
        loc_analyses = await db.smr_analyses.find(
            {"org_id": org_id, "project_id": project_id, "lines.location_id": loc["id"]}, {"_id": 0, "lines": 1}
        ).to_list(50)
        planned_c = 0
        for a in loc_analyses:
            for ln in a.get("lines", []):
                if ln.get("location_id") == loc["id"] and ln.get("is_active", True):
                    planned_c += ln.get("final_total", 0)

        # Missing SMR at this location
        ms_count = await db.missing_smr.count_documents(
            {"org_id": org_id, "project_id": project_id, "location_id": loc["id"]}
        )

        locations.append({
            "name": loc["name"], "location_id": loc["id"], "type": loc["type"],
            "planned_cost": round(planned_c, 2), "actual_cost": 0,
            "variance_cost": round(-planned_c, 2),
            "missing_smr_count": ms_count,
            "status": "on_track",
        })

    # ── D. Summary ──────────────────────────────────────────────
    total_planned_h = round(sum(a["planned_hours"] for a in activities), 1)
    total_actual_h = round(sum(a["actual_hours"] for a in activities), 1)
    total_planned_c = round(sum(a["planned_cost"] for a in activities), 2)
    total_actual_c = round(sum(a["actual_cost"] for a in activities), 2)

    warning_count = sum(1 for a in activities if a["status"] == "warning")
    over_count = sum(1 for a in activities if a["status"] == "over")

    biggest_act = max(activities, key=lambda x: x["variance_cost"]) if activities else None
    biggest_grp = max(groups, key=lambda x: x.get("variance_cost", 0)) if groups else None

    summary = {
        "total_planned_hours": total_planned_h,
        "total_actual_hours": total_actual_h,
        "total_planned_cost": total_planned_c,
        "total_actual_cost": total_actual_c,
        "variance_hours": round(total_actual_h - total_planned_h, 1),
        "variance_cost": round(total_actual_c - total_planned_c, 2),
        "overall_status": _status(total_actual_c, total_planned_c),
        "warning_count": warning_count,
        "over_count": over_count,
        "biggest_overrun_activity": biggest_act["name"] if biggest_act and biggest_act["variance_cost"] > 0 else None,
        "biggest_overrun_group": biggest_grp["name"] if biggest_grp and biggest_grp.get("variance_cost", 0) > 0 else None,
    }

    return {"summary": summary, "activities": activities, "groups": groups, "locations": locations}
