"""
Service - Site Pulse Generator.
Aggregates daily snapshot from all data sources per project.
"""
from datetime import datetime, timezone
from collections import defaultdict
from app.db import db


async def generate_pulse(org_id: str, site_id: str, date: str) -> dict:
    """Generate a daily pulse snapshot for a site/project."""
    now = datetime.now(timezone.utc).isoformat()
    ds = f"{date}T00:00:00"
    de = f"{date}T23:59:59"

    # a. Workers + hours from work_sessions
    sessions = await db.work_sessions.find(
        {"org_id": org_id, "site_id": site_id, "ended_at": {"$ne": None},
         "started_at": {"$gte": ds, "$lte": de}},
        {"_id": 0},
    ).to_list(1000)

    by_worker = defaultdict(lambda: {"hours": 0, "sessions": 0, "smr_types": set(), "ot": 0, "cost": 0})
    for s in sessions:
        wid = s["worker_id"]
        by_worker[wid]["hours"] += s.get("duration_hours", 0)
        by_worker[wid]["sessions"] += 1
        by_worker[wid]["cost"] += s.get("labor_cost", 0)
        if s.get("is_overtime"):
            by_worker[wid]["ot"] += s.get("duration_hours", 0)
        if s.get("smr_type_id"):
            by_worker[wid]["smr_types"].add(s["smr_type_id"])
        by_worker[wid]["name"] = s.get("worker_name", "")

    workers = []
    for wid, d in by_worker.items():
        workers.append({
            "worker_id": wid, "worker_name": d["name"],
            "hours": round(d["hours"], 2), "sessions_count": d["sessions"],
            "smr_types": list(d["smr_types"]), "overtime_hours": round(d["ot"], 2),
            "labor_cost": round(d["cost"], 2),
        })

    total_hours = round(sum(w["hours"] for w in workers), 2)
    total_labor = round(sum(w["labor_cost"] for w in workers), 2)
    overtime_hours = round(sum(w["overtime_hours"] for w in workers), 2)

    # b. SMR breakdown
    smr_map = defaultdict(lambda: {"hours": 0, "cost": 0, "workers": set()})
    for s in sessions:
        st = s.get("smr_type_id") or "general"
        smr_map[st]["hours"] += s.get("duration_hours", 0)
        smr_map[st]["cost"] += s.get("labor_cost", 0)
        smr_map[st]["workers"].add(s["worker_id"])
    smr_summary = [{"smr_type": k, "total_hours": round(v["hours"], 2), "total_cost": round(v["cost"], 2), "workers_count": len(v["workers"])} for k, v in smr_map.items()]

    # c. Materials from warehouse transactions
    txns = await db.warehouse_transactions.find(
        {"org_id": org_id, "project_id": site_id, "type": "issue",
         "created_at": {"$gte": ds, "$lte": de}},
        {"_id": 0, "lines": 1},
    ).to_list(100)
    materials = []
    mat_cost = 0
    for t in txns:
        for ln in t.get("lines", []):
            qty = float(ln.get("qty_issued", 0))
            uc = float(ln.get("unit_cost", 0))
            cost = round(qty * uc, 2)
            materials.append({"item_name": ln.get("material_name", ""), "qty": qty, "unit": ln.get("unit", ""), "cost": cost, "source": "warehouse"})
            mat_cost += cost
    mat_cost = round(mat_cost, 2)

    # d. Budget snapshot
    budgets = await db.activity_budgets.find(
        {"org_id": org_id, "project_id": site_id}, {"_id": 0, "labor_budget": 1}
    ).to_list(100)
    total_budget = sum(b.get("labor_budget", 0) for b in budgets)
    all_sessions_cost = 0
    all_sess = await db.work_sessions.find(
        {"org_id": org_id, "site_id": site_id, "ended_at": {"$ne": None}},
        {"_id": 0, "labor_cost": 1},
    ).to_list(5000)
    all_sessions_cost = sum(s.get("labor_cost", 0) for s in all_sess)
    burn_pct = round(all_sessions_cost / total_budget * 100, 1) if total_budget > 0 else 0
    budget_status = "on_track" if burn_pct <= 80 else ("warning" if burn_pct <= 100 else "over_budget")
    budget_snapshot = {
        "total_budget": round(total_budget, 2), "total_spent": round(all_sessions_cost, 2),
        "remaining": round(total_budget - all_sessions_cost, 2), "burn_pct": burn_pct, "status": budget_status,
    }

    # e. Calendar summary
    cal_entries = await db.worker_calendar.find(
        {"org_id": org_id, "date": date, "site_id": site_id},
        {"_id": 0, "status": 1},
    ).to_list(200)
    cal = {"working": 0, "sick": 0, "vacation": 0, "absent": 0}
    for e in cal_entries:
        st = e.get("status", "")
        if st == "working": cal["working"] += 1
        elif st in ("sick_paid", "sick_unpaid"): cal["sick"] += 1
        elif st in ("vacation_paid", "vacation_unpaid"): cal["vacation"] += 1
        elif st == "absent_unauthorized": cal["absent"] += 1

    # f. Missing SMR count
    missing_count = await db.missing_smr.count_documents(
        {"org_id": org_id, "project_id": site_id, "created_at": {"$gte": ds, "$lte": de}}
    )

    # g. Daily report
    report = await db.work_reports.find_one(
        {"org_id": org_id, "project_id": site_id, "date": date, "status": {"$in": ["Submitted", "Approved"]}},
    )
    report_submitted = report is not None

    # Alerts
    alerts = []
    if len(workers) == 0:
        alerts.append({"type": "no_workers", "message": "Няма хора на обекта", "severity": "warning"})
    if overtime_hours > 0:
        alerts.append({"type": "overtime", "message": f"Извънреден труд: {overtime_hours}ч", "severity": "info"})
    if burn_pct > 100:
        alerts.append({"type": "budget_warning", "message": f"Надхвърлен бюджет! ({burn_pct}%)", "severity": "critical"})
    elif burn_pct > 80:
        alerts.append({"type": "budget_warning", "message": f"Бюджетът е {burn_pct}% изхарчен", "severity": "warning"})
    if not report_submitted:
        alerts.append({"type": "no_report", "message": "Липсва дневен отчет", "severity": "info"})
    if cal["sick"] >= 2:
        alerts.append({"type": "sick_spike", "message": f"{cal['sick']} болни на обекта", "severity": "warning"})

    # Get project info
    project = await db.projects.find_one({"id": site_id, "org_id": org_id}, {"_id": 0, "name": 1, "code": 1})

    pulse = {
        "id": None,  # set below
        "org_id": org_id,
        "site_id": site_id,
        "site_name": (project or {}).get("name", ""),
        "site_code": (project or {}).get("code", ""),
        "date": date,
        "generated_at": now,
        "generation_method": "auto",
        "workers": workers,
        "total_workers": len(workers),
        "total_hours": total_hours,
        "total_labor_cost": total_labor,
        "overtime_hours": overtime_hours,
        "smr_summary": smr_summary,
        "materials_used": materials,
        "total_material_cost": mat_cost,
        "budget_snapshot": budget_snapshot,
        "calendar_summary": cal,
        "missing_smr_count": missing_count,
        "daily_report_submitted": report_submitted,
        "alerts": alerts,
        "notes": None,
    }

    # Upsert
    import uuid
    existing = await db.site_pulses.find_one({"org_id": org_id, "site_id": site_id, "date": date})
    if existing:
        pulse["id"] = existing["id"]
        await db.site_pulses.update_one({"id": existing["id"]}, {"$set": pulse})
    else:
        pulse["id"] = str(uuid.uuid4())
        await db.site_pulses.insert_one(pulse)

    return {k: v for k, v in pulse.items() if k != "_id"}


async def generate_all_pulses(org_id: str, date: str) -> list:
    """Generate pulses for all active projects."""
    projects = await db.projects.find(
        {"org_id": org_id, "status": {"$in": ["Active", "Draft"]}},
        {"_id": 0, "id": 1},
    ).to_list(200)
    results = []
    for p in projects:
        pulse = await generate_pulse(org_id, p["id"], date)
        results.append(pulse)
    return results
