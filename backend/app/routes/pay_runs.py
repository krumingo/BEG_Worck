"""
Routes — Pay Runs (Core payroll settlement).
Source of truth for earned/paid/remaining per employee per period.
Formula: remaining = earned + bonuses - deductions - paid
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.services.report_normalizer import fetch_normalized_report_lines, enrich_hours

router = APIRouter(tags=["Pay Runs"])


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

class PayRunRowInput(BaseModel):
    employee_id: str
    paid_now_amount: float = 0
    bonuses_amount: float = 0
    deductions_amount: float = 0
    notes: str = ""


class PayRunCreateInput(BaseModel):
    run_type: str = "weekly"  # weekly | weekly_partial | advance | month_close
    period_start: str
    period_end: str
    week_number: Optional[int] = None
    rows: List[PayRunRowInput] = []
    note: str = ""


# ── Generate Pay Run (preview) ─────────────────────────────────────

@router.get("/pay-runs/generate")
async def generate_pay_run(
    user: dict = Depends(get_current_user),
    period_start: str = "",
    period_end: str = "",
):
    """Generate a preview of what a pay run would contain for the given period."""
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner")
    org_id = user["org_id"]

    if not period_start or not period_end:
        today = datetime.now(timezone.utc)
        # Default: current week Mon-Sun
        period_end = today.strftime("%Y-%m-%d")
        period_start = (today - timedelta(days=6)).strftime("%Y-%m-%d")

    # Get approved report lines for the period
    lines = await fetch_normalized_report_lines(
        org_id=org_id, date_from=period_start, date_to=period_end,
        status_filter="APPROVED",
    )
    for ln in lines:
        enrich_hours(ln)

    # Get employees
    employees = await db.users.find(
        {"org_id": org_id, "is_active": True},
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "avatar_url": 1, "email": 1},
    ).to_list(200)
    employees = [e for e in employees if not e.get("email", "").startswith("test_")]
    emp_map = {e["id"]: e for e in employees}

    # Profiles
    emp_ids = [e["id"] for e in employees]
    profiles = await db.employee_profiles.find(
        {"org_id": org_id, "user_id": {"$in": emp_ids}},
        {"_id": 0, "user_id": 1, "position": 1, "pay_type": 1, "pay_schedule": 1,
         "hourly_rate": 1, "daily_rate": 1, "monthly_salary": 1,
         "working_days_per_month": 1, "standard_hours_per_day": 1},
    ).to_list(200)
    prof_map = {p["user_id"]: p for p in profiles}

    # Group lines by employee
    by_emp = {}
    for ln in lines:
        wid = ln["worker_id"]
        if wid not in by_emp:
            by_emp[wid] = []
        by_emp[wid].append(ln)

    # Project names
    pids = list({ln["project_id"] for ln in lines if ln["project_id"]})
    proj_map = {}
    if pids:
        projects = await db.projects.find({"id": {"$in": pids}}, {"_id": 0, "id": 1, "name": 1}).to_list(200)
        proj_map = {p["id"]: p.get("name", "") for p in projects}

    # Check existing paid amounts for this period
    existing_runs = await db.pay_runs.find(
        {"org_id": org_id, "status": {"$in": ["confirmed", "paid"]},
         "period_start": {"$lte": period_end}, "period_end": {"$gte": period_start}},
        {"_id": 0, "employee_rows": 1},
    ).to_list(100)
    already_paid = {}  # employee_id -> total paid
    for run in existing_runs:
        for row in run.get("employee_rows", []):
            eid = row.get("employee_id", "")
            already_paid[eid] = already_paid.get(eid, 0) + row.get("paid_now_amount", 0)

    # Build rows
    rows = []
    for wid, emp_lines in by_emp.items():
        emp = emp_map.get(wid)
        if not emp:
            continue
        prof = prof_map.get(wid, {})
        rate = _calc_rate(prof)

        total_hours = round(sum(ln["hours"] for ln in emp_lines), 1)
        normal_hours = round(sum(ln.get("normal_hours", 0) for ln in emp_lines), 1)
        overtime_hours = round(sum(ln.get("overtime_hours", 0) for ln in emp_lines), 1)
        days_set = {ln["date"] for ln in emp_lines}
        approved_days = len(days_set)

        earned = round(total_hours * rate, 2)
        prev_paid = round(already_paid.get(wid, 0), 2)
        remaining = round(earned - prev_paid, 2)

        # Sites worked
        sites = list({proj_map.get(ln["project_id"], ln["project_id"]) for ln in emp_lines if ln["project_id"]})

        rows.append({
            "employee_id": wid,
            "first_name": emp.get("first_name", ""),
            "last_name": emp.get("last_name", ""),
            "avatar_url": emp.get("avatar_url"),
            "position": prof.get("position", ""),
            "pay_type": prof.get("pay_type", ""),
            "hourly_rate": rate,
            "approved_days": approved_days,
            "approved_hours": total_hours,
            "normal_hours": normal_hours,
            "overtime_hours": overtime_hours,
            "earned_amount": earned,
            "bonuses_amount": 0,
            "deductions_amount": 0,
            "previously_paid": prev_paid,
            "paid_now_amount": 0,
            "remaining_after_payment": remaining,
            "sites": sites,
        })

    rows.sort(key=lambda r: (0 if r["earned_amount"] > 0 else 1, r["last_name"]))

    return {
        "period_start": period_start,
        "period_end": period_end,
        "rows": rows,
        "totals": {
            "employees": len(rows),
            "hours": round(sum(r["approved_hours"] for r in rows), 1),
            "earned": round(sum(r["earned_amount"] for r in rows), 2),
            "remaining": round(sum(r["remaining_after_payment"] for r in rows), 2),
        },
    }


# ── Create / Confirm Pay Run ───────────────────────────────────────

@router.post("/pay-runs")
async def create_pay_run(data: PayRunCreateInput, user: dict = Depends(get_current_user)):
    """Create and confirm a pay run with frozen values."""
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner")
    org_id = user["org_id"]
    now = datetime.now(timezone.utc).isoformat()

    # Generate fresh data for the period
    preview = await generate_pay_run(
        user, period_start=data.period_start, period_end=data.period_end,
    )

    # Apply user overrides (paid_now, bonuses, deductions)
    override_map = {r.employee_id: r for r in data.rows}

    # Build frozen employee rows
    employee_rows = []
    grand_earned = 0
    grand_bonuses = 0
    grand_deductions = 0
    grand_paid = 0
    grand_remaining = 0

    for row in preview["rows"]:
        eid = row["employee_id"]
        ovr = override_map.get(eid)

        bonuses = ovr.bonuses_amount if ovr else 0
        deductions = ovr.deductions_amount if ovr else 0
        paid_now = ovr.paid_now_amount if ovr else row["remaining_after_payment"]
        notes = ovr.notes if ovr else ""

        # Formula: remaining = earned + bonuses - deductions - previously_paid - paid_now
        remaining = round(
            row["earned_amount"] + bonuses - deductions - row["previously_paid"] - paid_now, 2
        )

        frozen_row = {
            "employee_id": eid,
            "first_name": row["first_name"],
            "last_name": row["last_name"],
            "position": row.get("position", ""),
            "pay_type": row.get("pay_type", ""),
            "frozen_hourly_rate": row["hourly_rate"],
            "approved_days": row["approved_days"],
            "approved_hours": row["approved_hours"],
            "normal_hours": row.get("normal_hours", 0),
            "overtime_hours": row.get("overtime_hours", 0),
            "earned_amount": row["earned_amount"],
            "bonuses_amount": round(bonuses, 2),
            "deductions_amount": round(deductions, 2),
            "previously_paid": row["previously_paid"],
            "paid_now_amount": round(paid_now, 2),
            "remaining_after_payment": remaining,
            "sites": row.get("sites", []),
            "notes": notes,
        }
        employee_rows.append(frozen_row)

        grand_earned += row["earned_amount"]
        grand_bonuses += bonuses
        grand_deductions += deductions
        grand_paid += paid_now
        grand_remaining += remaining

    # Auto-number
    count = await db.pay_runs.count_documents({"org_id": org_id})
    run_number = f"PR-{count + 1:04d}"

    # Calculate week number
    week_num = data.week_number
    if not week_num:
        d = datetime.strptime(data.period_start, "%Y-%m-%d")
        week_num = d.isocalendar()[1]

    pay_run = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "number": run_number,
        "run_type": data.run_type,
        "period_start": data.period_start,
        "period_end": data.period_end,
        "week_number": week_num,
        "status": "confirmed",
        "employee_rows": employee_rows,
        "totals": {
            "employees": len(employee_rows),
            "hours": round(sum(r["approved_hours"] for r in employee_rows), 1),
            "earned": round(grand_earned, 2),
            "bonuses": round(grand_bonuses, 2),
            "deductions": round(grand_deductions, 2),
            "paid": round(grand_paid, 2),
            "remaining": round(grand_remaining, 2),
        },
        "note": data.note,
        "created_by": user["id"],
        "created_at": now,
        "confirmed_at": now,
        "paid_at": None,
    }

    await db.pay_runs.insert_one(pay_run)
    return {k: v for k, v in pay_run.items() if k != "_id"}


# ── List Pay Runs ──────────────────────────────────────────────────

@router.get("/pay-runs")
async def list_pay_runs(
    user: dict = Depends(get_current_user),
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    org_id = user["org_id"]
    q = {"org_id": org_id}
    if status:
        q["status"] = status

    total = await db.pay_runs.count_documents(q)
    runs = await db.pay_runs.find(
        q, {"_id": 0, "id": 1, "number": 1, "run_type": 1,
            "period_start": 1, "period_end": 1, "week_number": 1,
            "status": 1, "totals": 1, "created_at": 1, "paid_at": 1},
    ).sort("created_at", -1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)

    return {"items": runs, "total": total, "page": page, "page_size": page_size}


# ── Get Single Pay Run ─────────────────────────────────────────────

@router.get("/pay-runs/{run_id}")
async def get_pay_run(run_id: str, user: dict = Depends(get_current_user)):
    run = await db.pay_runs.find_one(
        {"id": run_id, "org_id": user["org_id"]}, {"_id": 0}
    )
    if not run:
        raise HTTPException(status_code=404, detail="Pay run not found")
    return run


# ── Mark Pay Run as Paid ───────────────────────────────────────────

@router.post("/pay-runs/{run_id}/mark-paid")
async def mark_pay_run_paid(run_id: str, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner")
    org_id = user["org_id"]
    run = await db.pay_runs.find_one({"id": run_id, "org_id": org_id})
    if not run:
        raise HTTPException(status_code=404, detail="Not found")
    if run.get("status") == "paid":
        raise HTTPException(status_code=400, detail="Already paid")

    now = datetime.now(timezone.utc).isoformat()
    await db.pay_runs.update_one(
        {"id": run_id},
        {"$set": {"status": "paid", "paid_at": now}},
    )
    return {"ok": True, "status": "paid"}
