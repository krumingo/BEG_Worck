"""
Routes — Pay Runs (Payroll settlement with multi-pay-type earned engine + payment slips).
Formula: remaining = earned + bonuses - deductions - previously_paid - paid_now
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


# ── Earned Calculation Engine ──────────────────────────────────────

def calc_earned(profile: dict, approved_hours: float, approved_days: int,
                period_days: int = 7) -> dict:
    """
    Multi pay-type earned engine.
    Returns: {earned, rate, rate_type, daily_rate, hourly_rate}
    """
    pay = (profile.get("pay_type") or "Monthly").strip()
    hr = float(profile.get("hourly_rate") or 0)
    dr = float(profile.get("daily_rate") or 0)
    ms = float(profile.get("monthly_salary") or 0)
    wd = int(profile.get("working_days_per_month") or 22)
    hd = int(profile.get("standard_hours_per_day") or 8)

    if pay == "Hourly":
        earned = round(approved_hours * hr, 2)
        return {"earned": earned, "rate": hr, "rate_type": "hourly",
                "daily_rate": round(hr * hd, 2), "hourly_rate": hr}

    elif pay == "Daily":
        effective_hr = round(dr / max(hd, 1), 2)
        earned = round(approved_hours * effective_hr, 2)
        return {"earned": earned, "rate": dr, "rate_type": "daily",
                "daily_rate": dr, "hourly_rate": effective_hr}

    elif pay == "Monthly":
        effective_hr = round(ms / max(wd * hd, 1), 2)
        earned = round(approved_hours * effective_hr, 2)
        return {"earned": earned, "rate": ms, "rate_type": "monthly",
                "daily_rate": round(ms / max(wd, 1), 2), "hourly_rate": effective_hr}

    elif pay == "Akord":
        # Piecework: earned from approved value directly, rate=0
        earned = round(approved_hours * hr, 2) if hr > 0 else 0
        return {"earned": earned, "rate": hr, "rate_type": "piecework",
                "daily_rate": 0, "hourly_rate": hr}

    else:  # mixed or unknown
        effective_hr = round(ms / max(wd * hd, 1), 2) if ms > 0 else hr
        earned = round(approved_hours * effective_hr, 2)
        return {"earned": earned, "rate": effective_hr, "rate_type": "mixed",
                "daily_rate": round(effective_hr * hd, 2), "hourly_rate": effective_hr}


# ── Models ─────────────────────────────────────────────────────────

class AdjustmentRow(BaseModel):
    type: str = "deduction"  # bonus | advance | loan | loan_repayment | deduction | manual_correction
    title: str = ""
    amount: float = 0
    note: str = ""


class PayRunRowInput(BaseModel):
    employee_id: str
    paid_now_amount: float = 0
    adjustments: List[AdjustmentRow] = []
    notes: str = ""


class PayRunCreateInput(BaseModel):
    run_type: str = "weekly"
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
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner")
    org_id = user["org_id"]

    if not period_start or not period_end:
        today = datetime.now(timezone.utc)
        period_end = today.strftime("%Y-%m-%d")
        period_start = (today - timedelta(days=6)).strftime("%Y-%m-%d")

    lines = await fetch_normalized_report_lines(
        org_id=org_id, date_from=period_start, date_to=period_end,
        status_filter="APPROVED",
    )
    for ln in lines:
        enrich_hours(ln)

    employees = await db.users.find(
        {"org_id": org_id, "is_active": True},
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "avatar_url": 1, "email": 1},
    ).to_list(200)
    employees = [e for e in employees if not e.get("email", "").startswith("test_")]
    emp_map = {e["id"]: e for e in employees}
    emp_ids = [e["id"] for e in employees]

    profiles = await db.employee_profiles.find(
        {"org_id": org_id, "user_id": {"$in": emp_ids}},
        {"_id": 0},
    ).to_list(200)
    prof_map = {p["user_id"]: p for p in profiles}

    by_emp = {}
    for ln in lines:
        wid = ln["worker_id"]
        if wid not in by_emp:
            by_emp[wid] = []
        by_emp[wid].append(ln)

    pids = list({ln["project_id"] for ln in lines if ln["project_id"]})
    proj_map = {}
    if pids:
        projects = await db.projects.find({"id": {"$in": pids}}, {"_id": 0, "id": 1, "name": 1}).to_list(200)
        proj_map = {p["id"]: p.get("name", "") for p in projects}

    # Previously paid
    existing_runs = await db.pay_runs.find(
        {"org_id": org_id, "status": {"$in": ["confirmed", "paid"]},
         "period_start": {"$lte": period_end}, "period_end": {"$gte": period_start}},
        {"_id": 0, "employee_rows": 1},
    ).to_list(100)
    already_paid = {}
    for run in existing_runs:
        for row in run.get("employee_rows", []):
            eid = row.get("employee_id", "")
            already_paid[eid] = already_paid.get(eid, 0) + row.get("paid_now_amount", 0)

    period_days = (datetime.strptime(period_end, "%Y-%m-%d") - datetime.strptime(period_start, "%Y-%m-%d")).days + 1

    rows = []
    for wid, emp_lines in by_emp.items():
        emp = emp_map.get(wid)
        if not emp:
            continue
        prof = prof_map.get(wid, {})

        total_hours = round(sum(ln["hours"] for ln in emp_lines), 1)
        normal_hours = round(sum(ln.get("normal_hours", 0) for ln in emp_lines), 1)
        overtime_hours = round(sum(ln.get("overtime_hours", 0) for ln in emp_lines), 1)
        days_set = {ln["date"] for ln in emp_lines}
        approved_days = len(days_set)

        e = calc_earned(prof, total_hours, approved_days, period_days)
        prev_paid = round(already_paid.get(wid, 0), 2)
        remaining = round(e["earned"] - prev_paid, 2)
        sites = list({proj_map.get(ln["project_id"], ln["project_id"]) for ln in emp_lines if ln["project_id"]})

        rows.append({
            "employee_id": wid,
            "first_name": emp.get("first_name", ""),
            "last_name": emp.get("last_name", ""),
            "avatar_url": emp.get("avatar_url"),
            "position": prof.get("position", ""),
            "pay_type": prof.get("pay_type", ""),
            "payment_schedule": prof.get("pay_schedule", ""),
            "hourly_rate": e["hourly_rate"],
            "daily_rate": e["daily_rate"],
            "rate_type": e["rate_type"],
            "approved_days": approved_days,
            "approved_hours": total_hours,
            "normal_hours": normal_hours,
            "overtime_hours": overtime_hours,
            "earned_amount": e["earned"],
            "adjustments": [],
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


# ── Create / Confirm Pay Run + Generate Slips ──────────────────────

@router.post("/pay-runs")
async def create_pay_run(data: PayRunCreateInput, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner")
    org_id = user["org_id"]
    now = datetime.now(timezone.utc).isoformat()

    preview = await generate_pay_run(user, period_start=data.period_start, period_end=data.period_end)
    override_map = {r.employee_id: r for r in data.rows}

    employee_rows = []
    slips = []
    grand = {"earned": 0, "bonuses": 0, "deductions": 0, "paid": 0, "remaining": 0}

    # Auto-number
    run_count = await db.pay_runs.count_documents({"org_id": org_id})
    run_number = f"PR-{run_count + 1:04d}"
    slip_counter = await db.payment_slips.count_documents({"org_id": org_id})

    week_num = data.week_number
    if not week_num:
        week_num = datetime.strptime(data.period_start, "%Y-%m-%d").isocalendar()[1]

    run_id = str(uuid.uuid4())

    for row in preview["rows"]:
        eid = row["employee_id"]
        ovr = override_map.get(eid)

        # Adjustments from input
        adj_list = []
        total_bonuses = 0
        total_deductions = 0
        if ovr:
            for a in ovr.adjustments:
                adj_list.append({"type": a.type, "title": a.title, "amount": a.amount, "note": a.note})
                if a.type == "bonus":
                    total_bonuses += a.amount
                else:
                    total_deductions += a.amount

        paid_now = ovr.paid_now_amount if ovr else row["remaining_after_payment"]
        notes = ovr.notes if ovr else ""

        remaining = round(
            row["earned_amount"] + total_bonuses - total_deductions - row["previously_paid"] - paid_now, 2
        )

        frozen_row = {
            "employee_id": eid,
            "first_name": row["first_name"],
            "last_name": row["last_name"],
            "position": row.get("position", ""),
            "pay_type": row.get("pay_type", ""),
            "payment_schedule": row.get("payment_schedule", ""),
            "rate_type": row.get("rate_type", ""),
            "frozen_hourly_rate": row["hourly_rate"],
            "frozen_daily_rate": row.get("daily_rate", 0),
            "approved_days": row["approved_days"],
            "approved_hours": row["approved_hours"],
            "normal_hours": row.get("normal_hours", 0),
            "overtime_hours": row.get("overtime_hours", 0),
            "earned_amount": row["earned_amount"],
            "adjustments": adj_list,
            "bonuses_amount": round(total_bonuses, 2),
            "deductions_amount": round(total_deductions, 2),
            "previously_paid": row["previously_paid"],
            "paid_now_amount": round(paid_now, 2),
            "remaining_after_payment": remaining,
            "sites": row.get("sites", []),
            "notes": notes,
        }
        employee_rows.append(frozen_row)

        grand["earned"] += row["earned_amount"]
        grand["bonuses"] += total_bonuses
        grand["deductions"] += total_deductions
        grand["paid"] += paid_now
        grand["remaining"] += remaining

        # Generate payment slip
        slip_counter += 1
        slip = {
            "id": str(uuid.uuid4()),
            "org_id": org_id,
            "slip_number": f"SL-{slip_counter:05d}",
            "pay_run_id": run_id,
            "pay_run_number": run_number,
            "employee_id": eid,
            "first_name": row["first_name"],
            "last_name": row["last_name"],
            "position": row.get("position", ""),
            "pay_type": row.get("pay_type", ""),
            "payment_schedule": row.get("payment_schedule", ""),
            "period_start": data.period_start,
            "period_end": data.period_end,
            "week_number": week_num,
            "approved_days": row["approved_days"],
            "approved_hours": row["approved_hours"],
            "normal_hours": row.get("normal_hours", 0),
            "overtime_hours": row.get("overtime_hours", 0),
            "frozen_hourly_rate": row["hourly_rate"],
            "earned_amount": row["earned_amount"],
            "adjustments": adj_list,
            "bonuses_amount": round(total_bonuses, 2),
            "deductions_amount": round(total_deductions, 2),
            "previously_paid": row["previously_paid"],
            "paid_now_amount": round(paid_now, 2),
            "remaining_after_payment": remaining,
            "sites": row.get("sites", []),
            "status": "confirmed",
            "paid_at": None,
            "created_at": now,
        }
        slips.append(slip)

    pay_run = {
        "id": run_id,
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
            "earned": round(grand["earned"], 2),
            "bonuses": round(grand["bonuses"], 2),
            "deductions": round(grand["deductions"], 2),
            "paid": round(grand["paid"], 2),
            "remaining": round(grand["remaining"], 2),
        },
        "note": data.note,
        "created_by": user["id"],
        "created_at": now,
        "confirmed_at": now,
        "paid_at": None,
    }

    await db.pay_runs.insert_one(pay_run)
    if slips:
        await db.payment_slips.insert_many(slips)

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


@router.get("/pay-runs/{run_id}")
async def get_pay_run(run_id: str, user: dict = Depends(get_current_user)):
    run = await db.pay_runs.find_one({"id": run_id, "org_id": user["org_id"]}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Pay run not found")
    return run


# ── Mark Paid + update slips ───────────────────────────────────────

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
        {"id": run_id}, {"$set": {"status": "paid", "paid_at": now}},
    )
    # Update slips
    await db.payment_slips.update_many(
        {"pay_run_id": run_id, "org_id": org_id},
        {"$set": {"status": "paid", "paid_at": now}},
    )
    return {"ok": True, "status": "paid"}


# ── Payment Slips ──────────────────────────────────────────────────

@router.get("/payment-slips")
async def list_payment_slips(
    user: dict = Depends(get_current_user),
    employee_id: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    org_id = user["org_id"]
    q = {"org_id": org_id}
    if employee_id:
        q["employee_id"] = employee_id
    if status:
        q["status"] = status
    total = await db.payment_slips.count_documents(q)
    slips = await db.payment_slips.find(
        q, {"_id": 0},
    ).sort("created_at", -1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    return {"items": slips, "total": total, "page": page, "page_size": page_size}


@router.get("/payment-slips/{slip_id}")
async def get_payment_slip(slip_id: str, user: dict = Depends(get_current_user)):
    slip = await db.payment_slips.find_one(
        {"id": slip_id, "org_id": user["org_id"]}, {"_id": 0}
    )
    if not slip:
        raise HTTPException(status_code=404, detail="Slip not found")
    return slip
