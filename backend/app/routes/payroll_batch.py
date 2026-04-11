"""
Routes — Payroll Batch (Sat→Fri payroll week).
Additive layer: collects approved+unpaid entries, allows day selection,
generates gross/deductions/net, manages payment status.
Does NOT allocate back to projects.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, List
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
import uuid

from app.db import db
from app.deps.auth import get_current_user

router = APIRouter(tags=["Payroll Batch"])

NORMAL_DAY = 8


def _get_payroll_week(ref_date: str) -> tuple:
    d = datetime.strptime(ref_date, "%Y-%m-%d")
    weekday = d.weekday()
    days_since_sat = (weekday - 5) % 7
    sat = d - timedelta(days=days_since_sat)
    fri = sat + timedelta(days=6)
    return sat.strftime("%Y-%m-%d"), fri.strftime("%Y-%m-%d")


def _week_dates(sat_str: str) -> list:
    sat = datetime.strptime(sat_str, "%Y-%m-%d")
    return [(sat + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]


def _calc_rate(profile: dict) -> float:
    pay = (profile.get("pay_type") or "Monthly").strip()
    if pay == "Hourly":
        return float(profile.get("hourly_rate") or 0)
    elif pay == "Daily":
        return round(float(profile.get("daily_rate") or 0) / 8, 2)
    else:
        ms = float(profile.get("monthly_salary") or 0)
        days = int(profile.get("working_days_per_month") or 22)
        hrs = int(profile.get("standard_hours_per_day") or 8)
        return round(ms / max(days * hrs, 1), 2)


# ── Models ─────────────────────────────────────────────────────────

class AdjustmentInput(BaseModel):
    worker_id: str
    type: str  # bonus, deduction, loan, rent, fine
    amount: float
    note: str = ""


class BatchCreateInput(BaseModel):
    week_of: str
    included_days: List[str]  # list of date strings to include
    adjustments: List[AdjustmentInput] = []
    note: str = ""


class BatchPayInput(BaseModel):
    paid_at: Optional[str] = None
    note: str = ""


# ── Eligible entries for a payroll week ────────────────────────────

@router.get("/payroll-batch/eligible")
async def get_eligible_entries(
    user: dict = Depends(get_current_user),
    week_of: Optional[str] = None,
):
    """
    Get approved + unpaid entries for a payroll week, grouped by worker.
    """
    org_id = user["org_id"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ref = week_of or today
    sat, fri = _get_payroll_week(ref)
    dates = _week_dates(sat)

    # Check if batch already exists for this week
    existing_batch = await db.payroll_batches.find_one(
        {"org_id": org_id, "week_start": sat},
        {"_id": 0, "id": 1, "status": 1},
    )

    # Active employees (filter test accounts)
    employees = await db.users.find(
        {"org_id": org_id, "is_active": True},
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "avatar_url": 1, "email": 1},
    ).to_list(200)
    employees = [e for e in employees if not (
        e.get("email", "").startswith("test_")
        or e.get("email", "").startswith("fullflow_")
        or e.get("email", "").startswith("ui_fixed_")
    )]
    emp_ids = [e["id"] for e in employees]
    emp_map = {e["id"]: e for e in employees}

    # Profiles
    profiles = await db.employee_profiles.find(
        {"org_id": org_id, "user_id": {"$in": emp_ids}},
        {"_id": 0, "user_id": 1, "position": 1, "pay_type": 1,
         "hourly_rate": 1, "daily_rate": 1, "monthly_salary": 1,
         "working_days_per_month": 1, "standard_hours_per_day": 1},
    ).to_list(200)
    prof_map = {p["user_id"]: p for p in profiles}

    # Approved new-style reports in period (not yet paid)
    new_reports = await db.employee_daily_reports.find(
        {"org_id": org_id, "worker_id": {"$exists": True},
         "date": {"$gte": sat, "$lte": fri},
         "status": "APPROVED",
         "payroll_status": {"$nin": ["paid", "batched"]}},
        {"_id": 0},
    ).to_list(5000)

    # Approved old-style reports
    old_reports = await db.employee_daily_reports.find(
        {"org_id": org_id, "employee_id": {"$exists": True},
         "report_date": {"$gte": sat, "$lte": fri},
         "approval_status": "APPROVED",
         "payroll_status": {"$nin": ["paid", "batched"]}},
        {"_id": 0},
    ).to_list(5000)

    # Project names
    project_ids = set()
    for r in new_reports:
        if r.get("project_id"):
            project_ids.add(r["project_id"])
    for r in old_reports:
        for e in r.get("day_entries", []):
            if e.get("project_id"):
                project_ids.add(e["project_id"])
    proj_map = {}
    if project_ids:
        projects = await db.projects.find(
            {"id": {"$in": list(project_ids)}},
            {"_id": 0, "id": 1, "name": 1},
        ).to_list(200)
        proj_map = {p["id"]: p.get("name", "") for p in projects}

    # Build worker → date → entries
    wd_map = {}

    for r in new_reports:
        wid = r.get("worker_id")
        d = r.get("date", "")
        if wid not in wd_map:
            wd_map[wid] = {}
        if d not in wd_map[wid]:
            wd_map[wid][d] = []
        wd_map[wid][d].append({
            "report_id": r["id"],
            "smr": r.get("smr_type", ""),
            "hours": float(r.get("hours") or 0),
            "project_id": r.get("project_id", ""),
            "project_name": proj_map.get(r.get("project_id", ""), ""),
        })

    for r in old_reports:
        wid = r.get("employee_id")
        d = r.get("report_date", "")
        if wid not in wd_map:
            wd_map[wid] = {}
        for e in r.get("day_entries", []):
            if d not in wd_map[wid]:
                wd_map[wid][d] = []
            wd_map[wid][d].append({
                "report_id": r["id"],
                "smr": e.get("work_description", ""),
                "hours": float(e.get("hours_worked") or 0),
                "project_id": e.get("project_id", ""),
                "project_name": proj_map.get(e.get("project_id", ""), ""),
            })

    # Advances
    advances = await db.advances.find(
        {"org_id": org_id, "user_id": {"$in": emp_ids},
         "status": {"$in": ["active", "approved"]}},
        {"_id": 0, "user_id": 1, "remaining_amount": 1, "type": 1, "note": 1},
    ).to_list(500)
    adv_map = {}
    for a in advances:
        uid = a["user_id"]
        if uid not in adv_map:
            adv_map[uid] = []
        remaining = float(a.get("remaining_amount") or a.get("amount", 0))
        if remaining > 0:
            adv_map[uid].append({
                "type": a.get("type", "advance"),
                "remaining": remaining,
                "note": a.get("note", ""),
            })

    # Build worker summaries
    workers = []
    for uid, day_entries in wd_map.items():
        emp = emp_map.get(uid)
        if not emp:
            continue
        prof = prof_map.get(uid, {})
        rate = _calc_rate(prof)

        days = []
        total_hours = 0
        total_normal = 0
        total_overtime = 0

        for d in dates:
            entries = day_entries.get(d, [])
            day_hours = sum(e["hours"] for e in entries)
            day_normal = min(day_hours, NORMAL_DAY) if day_hours > 0 else 0
            day_ot = max(0, day_hours - NORMAL_DAY)
            days.append({
                "date": d,
                "hours": round(day_hours, 1),
                "normal": round(day_normal, 1),
                "overtime": round(day_ot, 1),
                "entries": entries,
                "has_data": len(entries) > 0,
            })
            total_hours += day_hours
            total_normal += day_normal
            total_overtime += day_ot

        gross = round(total_hours * rate, 2)
        pending_advances = sum(a["remaining"] for a in adv_map.get(uid, []))

        workers.append({
            "worker_id": uid,
            "first_name": emp.get("first_name", ""),
            "last_name": emp.get("last_name", ""),
            "avatar_url": emp.get("avatar_url"),
            "position": prof.get("position", ""),
            "pay_type": prof.get("pay_type", ""),
            "hourly_rate": rate,
            "days": days,
            "total_hours": round(total_hours, 1),
            "total_normal": round(total_normal, 1),
            "total_overtime": round(total_overtime, 1),
            "gross": gross,
            "pending_advances": round(pending_advances, 2),
        })

    workers.sort(key=lambda w: (0 if w["total_hours"] > 0 else 1, w["last_name"]))

    return {
        "week_start": sat,
        "week_end": fri,
        "dates": dates,
        "workers": workers,
        "existing_batch": existing_batch,
        "total_eligible_hours": round(sum(w["total_hours"] for w in workers), 1),
        "total_eligible_gross": round(sum(w["gross"] for w in workers), 2),
    }


# ── Create / Save Batch ───────────────────────────────────────────

@router.post("/payroll-batch")
async def create_payroll_batch(data: BatchCreateInput, user: dict = Depends(get_current_user)):
    """Create a new payroll batch for the specified week with selected days."""
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner can create payroll batches")

    org_id = user["org_id"]
    sat, fri = _get_payroll_week(data.week_of)
    now = datetime.now(timezone.utc).isoformat()

    # Check for existing batch
    existing = await db.payroll_batches.find_one({"org_id": org_id, "week_start": sat, "status": {"$nin": ["cancelled"]}})
    if existing:
        raise HTTPException(status_code=409, detail="Batch already exists for this week")

    # Get eligible data
    eligible_res = await get_eligible_entries(user, week_of=data.week_of)
    included_set = set(data.included_days)

    # Build adjustments map
    adj_map = {}
    for adj in data.adjustments:
        if adj.worker_id not in adj_map:
            adj_map[adj.worker_id] = []
        adj_map[adj.worker_id].append({
            "type": adj.type,
            "amount": adj.amount,
            "note": adj.note,
        })

    # Profiles for rate calc
    emp_ids = [w["worker_id"] for w in eligible_res["workers"]]
    profiles = await db.employee_profiles.find(
        {"org_id": org_id, "user_id": {"$in": emp_ids}},
        {"_id": 0, "user_id": 1, "position": 1, "pay_type": 1,
         "hourly_rate": 1, "daily_rate": 1, "monthly_salary": 1,
         "working_days_per_month": 1, "standard_hours_per_day": 1},
    ).to_list(200)
    prof_map = {p["user_id"]: p for p in profiles}

    # Build employee summaries
    employee_summaries = []
    included_report_ids = []
    grand_gross = 0
    grand_deductions = 0
    grand_net = 0

    for w in eligible_res["workers"]:
        wid = w["worker_id"]
        rate = _calc_rate(prof_map.get(wid, {}))
        inc_hours = 0
        inc_normal = 0
        inc_overtime = 0
        inc_days = 0
        day_report_ids = []

        for day in w["days"]:
            if day["date"] in included_set and day["has_data"]:
                inc_hours += day["hours"]
                inc_normal += day["normal"]
                inc_overtime += day["overtime"]
                inc_days += 1
                for e in day["entries"]:
                    day_report_ids.append(e["report_id"])

        if inc_hours == 0:
            continue

        gross = round(inc_hours * rate, 2)
        adjustments = adj_map.get(wid, [])
        total_bonuses = sum(a["amount"] for a in adjustments if a["type"] == "bonus")
        total_deductions = sum(a["amount"] for a in adjustments if a["type"] in ("deduction", "loan", "rent", "fine"))
        net = round(gross + total_bonuses - total_deductions, 2)

        employee_summaries.append({
            "worker_id": wid,
            "first_name": w["first_name"],
            "last_name": w["last_name"],
            "position": w.get("position", ""),
            "pay_type": w.get("pay_type", ""),
            "hourly_rate": rate,
            "included_days": inc_days,
            "total_hours": round(inc_hours, 1),
            "normal_hours": round(inc_normal, 1),
            "overtime_hours": round(inc_overtime, 1),
            "gross": gross,
            "bonuses": round(total_bonuses, 2),
            "deductions": round(total_deductions, 2),
            "net": net,
            "adjustments": adjustments,
            "report_ids": list(set(day_report_ids)),
            "payroll_status": "batched",
        })
        included_report_ids.extend(day_report_ids)
        grand_gross += gross
        grand_deductions += total_deductions
        grand_net += net

    batch = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "week_start": sat,
        "week_end": fri,
        "included_days": sorted(list(included_set)),
        "status": "batched",
        "employee_summaries": employee_summaries,
        "report_ids": list(set(included_report_ids)),
        "totals": {
            "gross": round(grand_gross, 2),
            "deductions": round(grand_deductions, 2),
            "net": round(grand_net, 2),
            "workers": len(employee_summaries),
            "hours": round(sum(e["total_hours"] for e in employee_summaries), 1),
        },
        "note": data.note,
        "created_by": user["id"],
        "created_at": now,
        "updated_at": now,
        "paid_at": None,
    }
    await db.payroll_batches.insert_one(batch)

    # Mark reports as batched
    if included_report_ids:
        await db.employee_daily_reports.update_many(
            {"id": {"$in": included_report_ids}, "org_id": org_id},
            {"$set": {"payroll_status": "batched", "payroll_batch_id": batch["id"]}},
        )

    return {k: v for k, v in batch.items() if k != "_id"}


# ── List batches ───────────────────────────────────────────────────

@router.get("/payroll-batch/list")
async def list_payroll_batches(user: dict = Depends(get_current_user)):
    org_id = user["org_id"]
    batches = await db.payroll_batches.find(
        {"org_id": org_id},
        {"_id": 0, "id": 1, "week_start": 1, "week_end": 1, "status": 1,
         "totals": 1, "created_at": 1, "paid_at": 1},
    ).sort("week_start", -1).to_list(100)
    return {"items": batches}


# ── Get single batch ───────────────────────────────────────────────

@router.get("/payroll-batch/{batch_id}")
async def get_payroll_batch(batch_id: str, user: dict = Depends(get_current_user)):
    batch = await db.payroll_batches.find_one(
        {"id": batch_id, "org_id": user["org_id"]}, {"_id": 0}
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return batch


# ── Mark batch as paid + ALLOCATE back to projects ─────────────────

@router.post("/payroll-batch/{batch_id}/pay")
async def mark_batch_paid(batch_id: str, data: BatchPayInput, user: dict = Depends(get_current_user)):
    """
    Mark batch as paid AND create allocation back to projects.
    Allocation rule:
    - gross labor is allocated per included report lines to their projects
    - first by value (hours × rate per line), fallback by hours proportion
    - deductions do NOT reduce project labor expense
    - project expense = allocated gross labor
    """
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner")

    org_id = user["org_id"]
    batch = await db.payroll_batches.find_one({"id": batch_id, "org_id": org_id})
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch.get("status") == "paid":
        raise HTTPException(status_code=400, detail="Already paid")

    now = datetime.now(timezone.utc).isoformat()
    paid_at = data.paid_at or now

    # ── Build allocations from batch employee_summaries ────────────
    report_ids = batch.get("report_ids", [])

    # Fetch all included reports to get project_id + hours for each line
    new_reports = await db.employee_daily_reports.find(
        {"id": {"$in": report_ids}, "org_id": org_id, "worker_id": {"$exists": True}},
        {"_id": 0, "id": 1, "worker_id": 1, "project_id": 1, "hours": 1, "smr_type": 1, "date": 1},
    ).to_list(5000)

    old_reports = await db.employee_daily_reports.find(
        {"id": {"$in": [rid.split("_")[0] for rid in report_ids]}, "org_id": org_id, "employee_id": {"$exists": True}},
        {"_id": 0, "id": 1, "employee_id": 1, "report_date": 1, "day_entries": 1},
    ).to_list(5000)

    # Get profiles for rate calculation
    worker_ids = list({r.get("worker_id") for r in new_reports if r.get("worker_id")})
    worker_ids += list({r.get("employee_id") for r in old_reports if r.get("employee_id")})
    worker_ids = list(set(worker_ids))

    profiles = await db.employee_profiles.find(
        {"org_id": org_id, "user_id": {"$in": worker_ids}},
        {"_id": 0, "user_id": 1, "pay_type": 1, "hourly_rate": 1, "daily_rate": 1,
         "monthly_salary": 1, "working_days_per_month": 1, "standard_hours_per_day": 1},
    ).to_list(300)
    prof_map = {p["user_id"]: p for p in profiles}

    # Build flat list: {worker_id, project_id, hours, report_id, date, smr}
    flat_lines = []
    for r in new_reports:
        flat_lines.append({
            "worker_id": r.get("worker_id"),
            "project_id": r.get("project_id", ""),
            "hours": float(r.get("hours") or 0),
            "report_id": r["id"],
            "date": r.get("date", ""),
            "smr": r.get("smr_type", ""),
        })

    for r in old_reports:
        for e in r.get("day_entries", []):
            flat_lines.append({
                "worker_id": r.get("employee_id"),
                "project_id": e.get("project_id", ""),
                "hours": float(e.get("hours_worked") or 0),
                "report_id": r["id"],
                "date": r.get("report_date", ""),
                "smr": e.get("work_description", ""),
            })

    # Group by worker → project, compute allocated gross
    # worker → {project → {hours, gross}}
    allocations = []
    worker_project_map = {}

    for line in flat_lines:
        wid = line["worker_id"]
        pid = line["project_id"]
        if not wid or not pid:
            continue
        rate = _calc_rate(prof_map.get(wid, {}))
        line_gross = round(line["hours"] * rate, 2)

        key = f"{wid}_{pid}"
        if key not in worker_project_map:
            worker_project_map[key] = {
                "worker_id": wid, "project_id": pid,
                "hours": 0, "gross": 0, "lines": [],
            }
        worker_project_map[key]["hours"] += line["hours"]
        worker_project_map[key]["gross"] += line_gross
        worker_project_map[key]["lines"].append({
            "report_id": line["report_id"],
            "date": line["date"],
            "smr": line["smr"],
            "hours": line["hours"],
            "gross": line_gross,
        })

    # Project names
    all_pids = list({v["project_id"] for v in worker_project_map.values()})
    proj_names = {}
    if all_pids:
        projects = await db.projects.find(
            {"id": {"$in": all_pids}}, {"_id": 0, "id": 1, "name": 1}
        ).to_list(200)
        proj_names = {p["id"]: p.get("name", "") for p in projects}

    # Worker names
    users_docs = await db.users.find(
        {"id": {"$in": worker_ids}},
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1},
    ).to_list(300)
    user_names = {u["id"]: f"{u.get('first_name','')} {u.get('last_name','')}".strip() for u in users_docs}

    # Create allocation documents
    for wp in worker_project_map.values():
        alloc = {
            "id": str(uuid.uuid4()),
            "org_id": org_id,
            "payroll_batch_id": batch_id,
            "worker_id": wp["worker_id"],
            "worker_name": user_names.get(wp["worker_id"], ""),
            "project_id": wp["project_id"],
            "project_name": proj_names.get(wp["project_id"], ""),
            "allocated_hours": round(wp["hours"], 2),
            "allocated_gross_labor": round(wp["gross"], 2),
            "allocation_basis": "value" if wp["gross"] > 0 else "hours",
            "lines": wp["lines"],
            "week_start": batch.get("week_start", ""),
            "week_end": batch.get("week_end", ""),
            "paid_at": paid_at,
            "created_by": user["id"],
            "created_at": now,
        }
        allocations.append(alloc)

    if allocations:
        await db.payroll_payment_allocations.insert_many(allocations)

    # Update batch status
    alloc_summary = {}
    for a in allocations:
        pid = a["project_id"]
        if pid not in alloc_summary:
            alloc_summary[pid] = {"project_name": a["project_name"], "gross": 0, "hours": 0, "workers": set()}
        alloc_summary[pid]["gross"] += a["allocated_gross_labor"]
        alloc_summary[pid]["hours"] += a["allocated_hours"]
        alloc_summary[pid]["workers"].add(a["worker_id"])

    alloc_by_project = [
        {"project_id": pid, "project_name": v["project_name"],
         "allocated_gross": round(v["gross"], 2), "allocated_hours": round(v["hours"], 1),
         "worker_count": len(v["workers"])}
        for pid, v in alloc_summary.items()
    ]

    await db.payroll_batches.update_one(
        {"id": batch_id},
        {"$set": {
            "status": "paid",
            "paid_at": paid_at,
            "updated_at": now,
            "allocation_created": True,
            "allocation_count": len(allocations),
            "allocation_by_project": alloc_by_project,
        }},
    )

    # Mark all included reports as paid
    if report_ids:
        await db.employee_daily_reports.update_many(
            {"id": {"$in": report_ids}, "org_id": org_id},
            {"$set": {"payroll_status": "paid", "payroll_allocated": True}},
        )

    return {
        "ok": True,
        "status": "paid",
        "paid_at": paid_at,
        "allocations_created": len(allocations),
        "allocation_by_project": alloc_by_project,
        "total_allocated_gross": round(sum(a["allocated_gross_labor"] for a in allocations), 2),
    }


# ── Carry forward unpaid ───────────────────────────────────────────

@router.post("/payroll-batch/carry-forward")
async def carry_forward_unpaid(user: dict = Depends(get_current_user), week_of: str = ""):
    """Mark approved but unbatched entries in a past week as carry_forward."""
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner")

    org_id = user["org_id"]
    if not week_of:
        raise HTTPException(status_code=400, detail="week_of required")

    sat, fri = _get_payroll_week(week_of)
    now = datetime.now(timezone.utc).isoformat()

    result = await db.employee_daily_reports.update_many(
        {"org_id": org_id, "date": {"$gte": sat, "$lte": fri},
         "status": "APPROVED",
         "payroll_status": {"$nin": ["paid", "batched"]}},
        {"$set": {"payroll_status": "carry_forward", "updated_at": now}},
    )

    return {"ok": True, "modified": result.modified_count}


# ── Allocation Read Endpoints ──────────────────────────────────────

@router.get("/payroll-batch/{batch_id}/allocations")
async def get_batch_allocations(batch_id: str, user: dict = Depends(get_current_user)):
    """Get all allocations created by a specific batch."""
    org_id = user["org_id"]
    allocs = await db.payroll_payment_allocations.find(
        {"org_id": org_id, "payroll_batch_id": batch_id},
        {"_id": 0},
    ).to_list(500)
    # Group by project
    by_project = {}
    for a in allocs:
        pid = a["project_id"]
        if pid not in by_project:
            by_project[pid] = {"project_id": pid, "project_name": a.get("project_name", ""),
                               "allocated_gross": 0, "hours": 0, "workers": []}
        by_project[pid]["allocated_gross"] += a["allocated_gross_labor"]
        by_project[pid]["hours"] += a["allocated_hours"]
        by_project[pid]["workers"].append({
            "worker_id": a["worker_id"], "worker_name": a.get("worker_name", ""),
            "hours": a["allocated_hours"], "gross": a["allocated_gross_labor"],
            "lines": a.get("lines", []),
        })
    projects = sorted(by_project.values(), key=lambda x: x["allocated_gross"], reverse=True)
    for p in projects:
        p["allocated_gross"] = round(p["allocated_gross"], 2)
        p["hours"] = round(p["hours"], 1)
    return {
        "batch_id": batch_id,
        "allocations": allocs,
        "by_project": projects,
        "total_allocated": round(sum(a["allocated_gross_labor"] for a in allocs), 2),
    }


@router.get("/projects/{project_id}/paid-labor")
async def get_project_paid_labor(project_id: str, user: dict = Depends(get_current_user)):
    """Get all paid labor allocations for a project (real project expense layer)."""
    org_id = user["org_id"]
    allocs = await db.payroll_payment_allocations.find(
        {"org_id": org_id, "project_id": project_id},
        {"_id": 0},
    ).to_list(500)

    total_gross = round(sum(a["allocated_gross_labor"] for a in allocs), 2)
    total_hours = round(sum(a["allocated_hours"] for a in allocs), 1)

    # Group by worker
    by_worker = {}
    for a in allocs:
        wid = a["worker_id"]
        if wid not in by_worker:
            by_worker[wid] = {"worker_id": wid, "worker_name": a.get("worker_name", ""),
                              "gross": 0, "hours": 0, "batches": []}
        by_worker[wid]["gross"] += a["allocated_gross_labor"]
        by_worker[wid]["hours"] += a["allocated_hours"]
        by_worker[wid]["batches"].append(a.get("payroll_batch_id"))

    workers = sorted(by_worker.values(), key=lambda x: x["gross"], reverse=True)
    for w in workers:
        w["gross"] = round(w["gross"], 2)
        w["hours"] = round(w["hours"], 1)
        w["batches"] = list(set(w["batches"]))

    # Group by week
    by_week = {}
    for a in allocs:
        ws = a.get("week_start", "")
        if ws not in by_week:
            by_week[ws] = {"week_start": ws, "week_end": a.get("week_end", ""), "gross": 0, "hours": 0}
        by_week[ws]["gross"] += a["allocated_gross_labor"]
        by_week[ws]["hours"] += a["allocated_hours"]
    weeks = sorted(by_week.values(), key=lambda x: x["week_start"], reverse=True)
    for w in weeks:
        w["gross"] = round(w["gross"], 2)
        w["hours"] = round(w["hours"], 1)

    return {
        "project_id": project_id,
        "total_paid_labor": total_gross,
        "total_paid_hours": total_hours,
        "by_worker": workers,
        "by_week": weeks,
        "allocation_count": len(allocs),
    }
