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
from app.services.report_normalizer import fetch_worker_day_map, NORMAL_DAY

router = APIRouter(tags=["Payroll Batch"])


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

    # ── Use unified normalizer for APPROVED + unpaid ─────────────
    wd_map, project_ids = await fetch_worker_day_map(
        org_id, sat, fri,
        status_filter="APPROVED",
        payroll_filter=["!paid", "!batched"],
    )

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
            "frozen_hourly_rate": rate,
            "frozen_pay_type": (prof_map.get(wid, {}).get("pay_type") or ""),
            "included_days": inc_days,
            "total_hours": round(inc_hours, 1),
            "normal_hours": round(inc_normal, 1),
            "overtime_hours": round(inc_overtime, 1),
            "gross": gross,
            "frozen_gross": gross,
            "bonuses": round(total_bonuses, 2),
            "deductions": round(total_deductions, 2),
            "net": net,
            "adjustments": adjustments,
            "report_ids": list(set(day_report_ids)),
            "payroll_status": "batched",
            "rate_frozen_at": now,
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

    # Idempotency: check if allocations already exist for this batch
    existing_allocs = await db.payroll_payment_allocations.count_documents(
        {"org_id": org_id, "payroll_batch_id": batch_id}
    )
    if existing_allocs > 0:
        raise HTTPException(status_code=409, detail="Allocations already exist for this batch")

    now = datetime.now(timezone.utc).isoformat()
    paid_at = data.paid_at or now

    # ── Build allocations from batch employee_summaries ────────────
    report_ids = batch.get("report_ids", [])

    # Build frozen rate map from batch employee_summaries (FREEZE SOURCE)
    frozen_rate_map = {}  # worker_id -> frozen_hourly_rate
    for es in batch.get("employee_summaries", []):
        wid = es.get("worker_id")
        if wid:
            frozen_rate_map[wid] = es.get("frozen_hourly_rate") or es.get("hourly_rate", 0)

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

        # Use FROZEN rate from batch (primary), fallback to current profile (legacy)
        frozen_rate = frozen_rate_map.get(wid)
        if frozen_rate is not None and frozen_rate > 0:
            rate = frozen_rate
            rate_source = "frozen"
        else:
            rate = _calc_rate(prof_map.get(wid, {}))
            rate_source = "legacy_profile_rate"

        line_gross = round(line["hours"] * rate, 2)

        key = f"{wid}_{pid}"
        if key not in worker_project_map:
            worker_project_map[key] = {
                "worker_id": wid, "project_id": pid,
                "hours": 0, "gross": 0, "lines": [],
                "rate_source": rate_source,
            }
        worker_project_map[key]["hours"] += line["hours"]
        worker_project_map[key]["gross"] += line_gross
        worker_project_map[key]["lines"].append({
            "report_id": line["report_id"],
            "date": line["date"],
            "smr": line["smr"],
            "hours": line["hours"],
            "gross": line_gross,
            "frozen_rate": rate,
            "rate_source": rate_source,
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
            "rate_source": wp.get("rate_source", "frozen"),
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


# ── Official Payslip (per worker per batch) ────────────────────────

@router.get("/payslip/{batch_id}/{worker_id}")
async def get_official_payslip(batch_id: str, worker_id: str, user: dict = Depends(get_current_user)):
    """
    Official payslip document for a worker in a specific payroll batch.
    Shows: period, days breakdown, project breakdown, SMR breakdown,
    normal/overtime, gross, adjustments, net, status, traceability.
    """
    org_id = user["org_id"]

    batch = await db.payroll_batches.find_one(
        {"id": batch_id, "org_id": org_id}, {"_id": 0}
    )
    if not batch:
        return {"error": "Batch not found"}

    # Find this worker's summary in the batch
    worker_summary = None
    for es in batch.get("employee_summaries", []):
        if es.get("worker_id") == worker_id:
            worker_summary = es
            break
    if not worker_summary:
        return {"error": "Worker not in this batch"}

    # Get worker info
    emp = await db.users.find_one(
        {"id": worker_id, "org_id": org_id},
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "email": 1, "phone": 1, "avatar_url": 1},
    ) or {}

    prof = await db.employee_profiles.find_one(
        {"org_id": org_id, "user_id": worker_id},
        {"_id": 0, "position": 1, "pay_type": 1},
    ) or {}

    # Get included report lines for this worker
    report_ids = worker_summary.get("report_ids", [])
    reports = await db.employee_daily_reports.find(
        {"id": {"$in": report_ids}, "org_id": org_id},
        {"_id": 0, "id": 1, "date": 1, "hours": 1, "smr_type": 1, "project_id": 1, "notes": 1},
    ).to_list(500)

    # Project names
    pids = list({r.get("project_id") for r in reports if r.get("project_id")})
    proj_map = {}
    if pids:
        projects = await db.projects.find(
            {"id": {"$in": pids}}, {"_id": 0, "id": 1, "name": 1}
        ).to_list(100)
        proj_map = {p["id"]: p.get("name", "") for p in projects}

    # Build day breakdown
    NORMAL_DAY_H = 8
    by_day = {}
    by_project = {}
    by_smr = {}
    for r in reports:
        d = r.get("date", "")
        pid = r.get("project_id", "")
        smr = r.get("smr_type", "") or "Общо"
        hours = float(r.get("hours") or 0)
        pname = proj_map.get(pid, pid)

        # Day
        if d not in by_day:
            by_day[d] = {"date": d, "hours": 0, "entries": []}
        by_day[d]["hours"] += hours
        by_day[d]["entries"].append({"smr": smr, "project": pname, "hours": hours})

        # Project
        if pid not in by_project:
            by_project[pid] = {"project_id": pid, "project_name": pname, "hours": 0, "value": 0}
        by_project[pid]["hours"] += hours

        # SMR
        if smr not in by_smr:
            by_smr[smr] = {"smr": smr, "hours": 0}
        by_smr[smr]["hours"] += hours

    rate = worker_summary.get("frozen_hourly_rate") or worker_summary.get("hourly_rate", 0)
    is_frozen = "frozen_hourly_rate" in worker_summary
    for p in by_project.values():
        p["value"] = round(p["hours"] * rate, 2)
        p["hours"] = round(p["hours"], 1)

    days_list = sorted(by_day.values(), key=lambda x: x["date"])
    for d in days_list:
        d["hours"] = round(d["hours"], 1)
        d["normal"] = round(min(d["hours"], NORMAL_DAY_H), 1)
        d["overtime"] = round(max(0, d["hours"] - NORMAL_DAY_H), 1)

    # Get allocations for this worker in this batch
    allocs = await db.payroll_payment_allocations.find(
        {"org_id": org_id, "payroll_batch_id": batch_id, "worker_id": worker_id},
        {"_id": 0, "project_id": 1, "project_name": 1, "allocated_gross_labor": 1, "allocated_hours": 1},
    ).to_list(50)

    return {
        "batch_id": batch_id,
        "worker_id": worker_id,
        "week_start": batch.get("week_start", ""),
        "week_end": batch.get("week_end", ""),
        "batch_status": batch.get("status", ""),
        "paid_at": batch.get("paid_at"),
        "created_at": batch.get("created_at"),
        "worker": {
            "first_name": emp.get("first_name", worker_summary.get("first_name", "")),
            "last_name": emp.get("last_name", worker_summary.get("last_name", "")),
            "email": emp.get("email", ""),
            "phone": emp.get("phone", ""),
            "avatar_url": emp.get("avatar_url"),
            "position": prof.get("position", worker_summary.get("position", "")),
            "pay_type": prof.get("pay_type", worker_summary.get("pay_type", "")),
            "hourly_rate": rate,
            "rate_frozen": is_frozen,
            "rate_source": "frozen" if is_frozen else "legacy_profile",
        },
        "summary": {
            "included_days": worker_summary.get("included_days", 0),
            "total_hours": worker_summary.get("total_hours", 0),
            "normal_hours": worker_summary.get("normal_hours", 0),
            "overtime_hours": worker_summary.get("overtime_hours", 0),
            "gross": worker_summary.get("frozen_gross") or worker_summary.get("gross", 0),
            "bonuses": worker_summary.get("bonuses", 0),
            "deductions": worker_summary.get("deductions", 0),
            "net": worker_summary.get("net", 0),
            "adjustments": worker_summary.get("adjustments", []),
        },
        "by_day": days_list,
        "by_project": sorted(by_project.values(), key=lambda x: x["value"], reverse=True),
        "by_smr": sorted(by_smr.values(), key=lambda x: x["hours"], reverse=True),
        "allocations": [
            {"project_name": a.get("project_name", ""), "gross": a.get("allocated_gross_labor", 0), "hours": a.get("allocated_hours", 0)}
            for a in allocs
        ],
        "report_count": len(reports),
    }
