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
from app.services.payroll_sync import sync_on_confirm, sync_on_paid, sync_on_reopen

router = APIRouter(tags=["Pay Runs"])


# ── Earned Calculation Engine ──────────────────────────────────────

def calc_earned(profile: dict, approved_hours: float, approved_days: int,
                period_days: int = 7, approved_value: float = 0) -> dict:
    """
    Multi pay-type earned engine.
    Returns: {earned, rate, rate_type, daily_rate, hourly_rate, formula}
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
                "daily_rate": round(hr * hd, 2), "hourly_rate": hr,
                "formula": f"{approved_hours}ч × {hr} EUR/ч"}

    elif pay == "Daily":
        earned = round(approved_days * dr, 2)
        effective_hr = round(dr / max(hd, 1), 2)
        return {"earned": earned, "rate": dr, "rate_type": "daily",
                "daily_rate": dr, "hourly_rate": effective_hr,
                "formula": f"{approved_days}д × {dr} EUR/д"}

    elif pay == "Monthly":
        # Pro-rated: (monthly / working_days) × approved_days
        daily = round(ms / max(wd, 1), 2)
        earned = round(daily * approved_days, 2)
        effective_hr = round(daily / max(hd, 1), 2)
        return {"earned": earned, "rate": ms, "rate_type": "monthly",
                "daily_rate": daily, "hourly_rate": effective_hr,
                "formula": f"{ms} EUR/мес ÷ {wd}д = {daily} EUR/д × {approved_days}д"}

    elif pay == "Akord":
        # Piecework: use approved_value if available, else hours × rate
        if approved_value > 0:
            earned = round(approved_value, 2)
            formula = f"Одобрена стойност: {approved_value} EUR"
        elif hr > 0:
            earned = round(approved_hours * hr, 2)
            formula = f"{approved_hours}ч × {hr} EUR/ч (акорд)"
        else:
            earned = 0
            formula = "Няма ставка / стойност"
        return {"earned": earned, "rate": hr, "rate_type": "piecework",
                "daily_rate": 0, "hourly_rate": hr, "formula": formula}

    else:  # mixed
        # Sum applicable: daily part + hourly overtime if any
        daily = round(ms / max(wd, 1), 2) if ms > 0 else dr
        base_earned = round(daily * approved_days, 2) if daily > 0 else 0
        effective_hr = round(daily / max(hd, 1), 2) if daily > 0 else hr
        overtime_h = max(0, approved_hours - approved_days * hd)
        ot_earned = round(overtime_h * effective_hr * 1.5, 2) if overtime_h > 0 else 0
        earned = round(base_earned + ot_earned, 2)
        formula = f"{approved_days}д × {daily} EUR/д"
        if ot_earned > 0:
            formula += f" + {overtime_h}ч OT × {effective_hr}×1.5"
        return {"earned": earned, "rate": daily, "rate_type": "mixed",
                "daily_rate": daily, "hourly_rate": effective_hr, "formula": formula}


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
    status: str = "draft"  # draft | confirmed


class PayRunReopenInput(BaseModel):
    employee_ids: List[str] = []  # empty = reopen all
    reason: str = ""


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

    # Previously paid — dedup: only count LATEST pay run per week per employee
    existing_runs = await db.pay_runs.find(
        {"org_id": org_id, "status": {"$in": ["confirmed", "paid"]},
         "period_start": {"$lte": period_end}, "period_end": {"$gte": period_start}},
        {"_id": 0, "employee_rows": 1, "week_number": 1, "number": 1},
    ).sort("number", -1).to_list(100)
    # Dedup: keep only latest pay_run per week_number
    seen_weeks = set()
    already_paid = {}
    for run in existing_runs:
        wn = run.get("week_number", 0)
        if wn in seen_weeks:
            continue
        seen_weeks.add(wn)
        for row in run.get("employee_rows", []):
            eid = row.get("employee_id", "")
            already_paid[eid] = already_paid.get(eid, 0) + row.get("paid_now_amount", 0)
    # Count overlapping runs for warning
    overlap_count = await db.pay_runs.count_documents(
        {"org_id": org_id, "status": {"$in": ["confirmed", "paid"]},
         "period_start": {"$lte": period_end}, "period_end": {"$gte": period_start}})

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

        # Per-day breakdown
        by_day = {}
        for ln in emp_lines:
            d = ln["date"]
            if d not in by_day:
                by_day[d] = {"date": d, "hours": 0, "sites": []}
            by_day[d]["hours"] += ln["hours"]
            site_name = proj_map.get(ln["project_id"], "")
            if site_name and site_name not in by_day[d]["sites"]:
                by_day[d]["sites"].append(site_name)
        # Compute day values using rate
        day_cells = []
        for d in sorted(by_day.keys()):
            dd = by_day[d]
            day_val = round(dd["hours"] * e["hourly_rate"], 2)
            day_cells.append({"date": d, "hours": round(dd["hours"], 1), "value": day_val, "sites": dd["sites"]})

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
            "earned_formula": e.get("formula", ""),
            "adjustments": [],
            "bonuses_amount": 0,
            "deductions_amount": 0,
            "previously_paid": prev_paid,
            "paid_now_amount": 0,
            "remaining_after_payment": remaining,
            "sites": sites,
            "day_cells": day_cells,
        })

    rows.sort(key=lambda r: (0 if r["earned_amount"] > 0 else 1, r["last_name"]))

    # Build full date range
    all_dates = []
    d = datetime.strptime(period_start, "%Y-%m-%d")
    end = datetime.strptime(period_end, "%Y-%m-%d")
    while d <= end:
        all_dates.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)

    return {
        "period_start": period_start,
        "period_end": period_end,
        "dates": all_dates,
        "rows": rows,
        "totals": {
            "employees": len(rows),
            "hours": round(sum(r["approved_hours"] for r in rows), 1),
            "earned": round(sum(r["earned_amount"] for r in rows), 2),
            "remaining": round(sum(r["remaining_after_payment"] for r in rows), 2),
        },
        "warnings": [f"Има {overlap_count} съществуващи плащания за този период"] if overlap_count > 0 else [],
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
            "row_status": "included",
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
            "day_cells": row.get("day_cells", []),
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
        "status": data.status if data.status in ("draft", "confirmed") else "draft",
        "version": 1,
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
        "confirmed_at": now if data.status == "confirmed" else None,
        "paid_at": None,
        "history": [{
            "version": 1,
            "action": "created" if data.status == "draft" else "created_confirmed",
            "changed_by": user["id"],
            "changed_at": now,
            "reason": "",
            "totals_snapshot": {
                "earned": round(grand["earned"], 2),
                "paid": round(grand["paid"], 2),
                "remaining": round(grand["remaining"], 2),
            },
        }],
    }

    await db.pay_runs.insert_one(pay_run)
    # Only generate slips for confirmed runs
    if data.status == "confirmed" and slips:
        await db.payment_slips.insert_many(slips)

    # Generate allocations for confirmed runs
    # ═══════════════════════════════════════════════════════════════
    # DEFINITIVE ALLOCATION RULE:
    # Level 1 (Days): paid_now proportional to day source_value
    # Level 2 (Sites): day_paid proportional to per-site value
    # Fallback: equal split ONLY when all source_values = 0
    # Rounding: last row absorbs remainder to guarantee exact totals
    # ═══════════════════════════════════════════════════════════════
    if data.status == "confirmed":
        allocations = []
        for er in employee_rows:
            eid = er["employee_id"]
            paid_total = er["paid_now_amount"]
            cells = er.get("day_cells", [])
            total_cell_value = sum(c.get("value", 0) for c in cells)
            use_value_method = total_cell_value > 0

            # Level 1: allocate paid_total across days
            day_allocs = []
            running_paid = 0.0

            for idx, dc in enumerate(cells):
                is_last_day = idx == len(cells) - 1
                day_value = dc.get("value", 0)

                if use_value_method:
                    if is_last_day:
                        day_paid = round(paid_total - running_paid, 2)
                    else:
                        day_paid = round(paid_total * day_value / total_cell_value, 2)
                    method_day = "proportional_value"
                else:
                    if is_last_day:
                        day_paid = round(paid_total - running_paid, 2)
                    else:
                        day_paid = round(paid_total / max(len(cells), 1), 2)
                    method_day = "equal_split_fallback"

                running_paid += day_paid
                day_remaining = round(day_value - day_paid, 2)

                # Level 2: allocate day_paid across sites
                sites = dc.get("sites", [])
                if len(sites) <= 1:
                    site_allocs = [{
                        "site_name": sites[0] if sites else "",
                        "hours": dc.get("hours", 0),
                        "source_value": day_value,
                        "paid": day_paid,
                        "remaining": day_remaining,
                        "method": "single_site",
                    }]
                else:
                    # Need per-site source values — currently we only have site names
                    # Proportional by equal value assumption (no per-site value in day_cells)
                    site_allocs = []
                    site_running = 0.0
                    site_count = len(sites)
                    for si, s in enumerate(sites):
                        is_last_site = si == site_count - 1
                        site_val = round(day_value / site_count, 2)
                        site_hrs = round(dc.get("hours", 0) / site_count, 1)
                        if is_last_site:
                            site_paid = round(day_paid - site_running, 2)
                            site_val_adj = round(day_value - sum(sa["source_value"] for sa in site_allocs), 2)
                        else:
                            site_paid = round(day_paid / site_count, 2)
                            site_val_adj = site_val
                        site_running += site_paid
                        site_allocs.append({
                            "site_name": s,
                            "hours": site_hrs,
                            "source_value": site_val_adj,
                            "paid": site_paid,
                            "remaining": round(site_val_adj - site_paid, 2),
                            "method": "proportional_equal" if si < site_count - 1 else "proportional_equal_remainder",
                        })

                day_allocs.append({
                    "date": dc.get("date", ""),
                    "hours": dc.get("hours", 0),
                    "source_value": day_value,
                    "allocated_paid": day_paid,
                    "allocated_remaining": day_remaining,
                    "allocation_method": method_day,
                    "sites": site_allocs,
                })

            # Validation: sum must match
            sum_day_paid = round(sum(d["allocated_paid"] for d in day_allocs), 2)
            rounding_adj = round(paid_total - sum_day_paid, 2)

            allocations.append({
                "id": str(uuid.uuid4()),
                "org_id": org_id,
                "pay_run_id": run_id,
                "pay_run_number": run_number,
                "employee_id": eid,
                "first_name": er["first_name"],
                "last_name": er["last_name"],
                "period_start": data.period_start,
                "period_end": data.period_end,
                "week_number": week_num,
                "paid_now_amount": paid_total,
                "remaining_carry_forward": er["remaining_after_payment"],
                "allocation_method_day": "proportional_value" if use_value_method else "equal_split_fallback",
                "rounding_adjustment": rounding_adj,
                "validation": {
                    "sum_day_paid": sum_day_paid,
                    "expected_paid": paid_total,
                    "match": sum_day_paid == paid_total,
                },
                "day_allocations": day_allocs,
                "created_at": now,
            })

        if allocations:
            await db.pay_run_allocations.insert_many(allocations)

        # Store allocation summary on the pay_run
        site_summary = {}
        for alloc in allocations:
            for da in alloc.get("day_allocations", []):
                for sa in da.get("sites", []):
                    sn = sa["site_name"] or "Без обект"
                    if sn not in site_summary:
                        site_summary[sn] = {"site_name": sn, "paid": 0, "remaining": 0, "hours": 0}
                    site_summary[sn]["paid"] += sa["paid"]
                    site_summary[sn]["remaining"] += sa["remaining"]
                    site_summary[sn]["hours"] += sa["hours"]
        for v in site_summary.values():
            v["paid"] = round(v["paid"], 2)
            v["remaining"] = round(v["remaining"], 2)
            v["hours"] = round(v["hours"], 1)

        await db.pay_runs.update_one({"id": run_id}, {"$set": {
            "allocation_summary": list(site_summary.values()),
        }})

    # ── Sync to downstream v2/v1 consumers ────────────────────────
    if data.status == "confirmed":
        await sync_on_confirm(pay_run, org_id, user["id"])

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

class MarkPaidInput(BaseModel):
    payment_method: str = ""  # cash | bank_transfer | card | other
    payment_reference: str = ""  # e.g. bank transfer number
    payment_note: str = ""


@router.post("/pay-runs/{run_id}/mark-paid")
async def mark_pay_run_paid(run_id: str, body: Optional[MarkPaidInput] = None, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner")
    org_id = user["org_id"]
    run = await db.pay_runs.find_one({"id": run_id, "org_id": org_id})
    if not run:
        raise HTTPException(status_code=404, detail="Not found")
    if run.get("status") == "paid":
        raise HTTPException(status_code=400, detail="Already paid")

    now = datetime.now(timezone.utc).isoformat()
    payment_info = {
        "status": "paid",
        "paid_at": now,
        "paid_by": user["id"],
        "payment_method": (body.payment_method if body else "") or "",
        "payment_reference": (body.payment_reference if body else "") or "",
        "payment_note": (body.payment_note if body else "") or "",
    }
    await db.pay_runs.update_one({"id": run_id}, {"$set": payment_info})

    # Update v3 slips
    await db.payment_slips.update_many(
        {"pay_run_id": run_id, "org_id": org_id},
        {"$set": {"status": "paid", "paid_at": now,
                  "payment_method": payment_info["payment_method"],
                  "payment_reference": payment_info["payment_reference"]}},
    )

    # Add to version history
    await db.pay_runs.update_one({"id": run_id}, {"$push": {"history": {
        "version": (run.get("version") or 1) + 1,
        "action": "marked_paid",
        "changed_by": user["id"],
        "changed_at": now,
        "reason": payment_info["payment_note"],
        "payment_method": payment_info["payment_method"],
        "payment_reference": payment_info["payment_reference"],
        "totals_snapshot": run.get("totals", {}),
    }}})

    # Sync downstream
    await sync_on_paid(run, org_id, now)

    return {"ok": True, "status": "paid", "paid_at": now,
            "payment_method": payment_info["payment_method"],
            "payment_reference": payment_info["payment_reference"]}


# ── Update Draft ───────────────────────────────────────────────────

@router.patch("/pay-runs/{run_id}")
async def update_pay_run(run_id: str, data: PayRunCreateInput, user: dict = Depends(get_current_user)):
    """Update a draft or reopened pay run. Increments version."""
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner")
    org_id = user["org_id"]
    run = await db.pay_runs.find_one({"id": run_id, "org_id": org_id})
    if not run:
        raise HTTPException(status_code=404, detail="Not found")
    if run.get("status") not in ("draft", "reopened"):
        raise HTTPException(status_code=400, detail="Can only edit draft or reopened pay runs")

    now = datetime.now(timezone.utc).isoformat()
    preview = await generate_pay_run(user, period_start=data.period_start, period_end=data.period_end)
    override_map = {r.employee_id: r for r in data.rows}

    employee_rows = []
    grand = {"earned": 0, "bonuses": 0, "deductions": 0, "paid": 0, "remaining": 0}

    for row in preview["rows"]:
        eid = row["employee_id"]
        ovr = override_map.get(eid)
        adj_list, total_bonuses, total_deductions = [], 0, 0
        if ovr:
            for a in ovr.adjustments:
                adj_list.append({"type": a.type, "title": a.title, "amount": a.amount, "note": a.note})
                if a.type == "bonus":
                    total_bonuses += a.amount
                else:
                    total_deductions += a.amount
        paid_now = ovr.paid_now_amount if ovr else row["remaining_after_payment"]
        remaining = round(row["earned_amount"] + total_bonuses - total_deductions - row["previously_paid"] - paid_now, 2)

        employee_rows.append({
            "employee_id": eid, "row_status": "included",
            "first_name": row["first_name"], "last_name": row["last_name"],
            "position": row.get("position", ""), "pay_type": row.get("pay_type", ""),
            "payment_schedule": row.get("payment_schedule", ""),
            "rate_type": row.get("rate_type", ""),
            "frozen_hourly_rate": row["hourly_rate"],
            "frozen_daily_rate": row.get("daily_rate", 0),
            "approved_days": row["approved_days"], "approved_hours": row["approved_hours"],
            "normal_hours": row.get("normal_hours", 0), "overtime_hours": row.get("overtime_hours", 0),
            "earned_amount": row["earned_amount"],
            "adjustments": adj_list,
            "bonuses_amount": round(total_bonuses, 2),
            "deductions_amount": round(total_deductions, 2),
            "previously_paid": row["previously_paid"],
            "paid_now_amount": round(paid_now, 2),
            "remaining_after_payment": remaining,
            "sites": row.get("sites", []), "notes": ovr.notes if ovr else "",
        })
        grand["earned"] += row["earned_amount"]
        grand["bonuses"] += total_bonuses
        grand["deductions"] += total_deductions
        grand["paid"] += paid_now
        grand["remaining"] += remaining

    new_version = (run.get("version") or 1) + 1
    history_entry = {
        "version": new_version,
        "action": "updated",
        "changed_by": user["id"],
        "changed_at": now,
        "reason": data.note or "",
        "totals_snapshot": {
            "earned": round(grand["earned"], 2),
            "paid": round(grand["paid"], 2),
            "remaining": round(grand["remaining"], 2),
        },
    }

    await db.pay_runs.update_one({"id": run_id}, {
        "$set": {
            "employee_rows": employee_rows,
            "version": new_version,
            "status": data.status if data.status in ("draft", "confirmed") else run["status"],
            "confirmed_at": now if data.status == "confirmed" else run.get("confirmed_at"),
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
            "updated_at": now,
        },
        "$push": {"history": history_entry},
    })

    # Generate slips if confirming
    if data.status == "confirmed":
        # Delete old slips for this run
        await db.payment_slips.delete_many({"pay_run_id": run_id, "org_id": org_id})
        slip_counter = await db.payment_slips.count_documents({"org_id": org_id})
        slips = []
        week_num = run.get("week_number", 0)
        for er in employee_rows:
            slip_counter += 1
            slips.append({
                "id": str(uuid.uuid4()), "org_id": org_id,
                "slip_number": f"SL-{slip_counter:05d}",
                "pay_run_id": run_id, "pay_run_number": run.get("number", ""),
                "employee_id": er["employee_id"],
                "first_name": er["first_name"], "last_name": er["last_name"],
                "position": er.get("position", ""), "pay_type": er.get("pay_type", ""),
                "payment_schedule": er.get("payment_schedule", ""),
                "period_start": data.period_start, "period_end": data.period_end,
                "week_number": week_num,
                "approved_days": er["approved_days"], "approved_hours": er["approved_hours"],
                "normal_hours": er.get("normal_hours", 0), "overtime_hours": er.get("overtime_hours", 0),
                "frozen_hourly_rate": er["frozen_hourly_rate"],
                "earned_amount": er["earned_amount"],
                "adjustments": er.get("adjustments", []),
                "bonuses_amount": er.get("bonuses_amount", 0),
                "deductions_amount": er.get("deductions_amount", 0),
                "previously_paid": er.get("previously_paid", 0),
                "paid_now_amount": er["paid_now_amount"],
                "remaining_after_payment": er["remaining_after_payment"],
                "sites": er.get("sites", []),
                "status": "confirmed", "paid_at": None, "created_at": now,
            })
        if slips:
            await db.payment_slips.insert_many(slips)

    updated = await db.pay_runs.find_one({"id": run_id}, {"_id": 0})
    return updated


# ── Reopen ─────────────────────────────────────────────────────────

@router.post("/pay-runs/{run_id}/reopen")
async def reopen_pay_run(run_id: str, data: PayRunReopenInput, user: dict = Depends(get_current_user)):
    """Reopen entire batch or specific employee rows."""
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner")
    org_id = user["org_id"]
    run = await db.pay_runs.find_one({"id": run_id, "org_id": org_id})
    if not run:
        raise HTTPException(status_code=404, detail="Not found")
    if run.get("status") == "paid":
        raise HTTPException(status_code=400, detail="Cannot reopen paid batch")

    now = datetime.now(timezone.utc).isoformat()
    new_version = (run.get("version") or 1) + 1
    reopen_all = len(data.employee_ids) == 0

    employee_rows = run.get("employee_rows", [])
    reopened_count = 0
    for er in employee_rows:
        if reopen_all or er["employee_id"] in data.employee_ids:
            er["row_status"] = "reopened"
            reopened_count += 1

    history_entry = {
        "version": new_version,
        "action": "reopened_all" if reopen_all else "reopened_rows",
        "changed_by": user["id"],
        "changed_at": now,
        "reason": data.reason,
        "reopened_employees": data.employee_ids if not reopen_all else ["ALL"],
        "totals_snapshot": run.get("totals", {}),
    }

    new_status = "reopened" if reopen_all else run.get("status", "confirmed")

    await db.pay_runs.update_one({"id": run_id}, {
        "$set": {
            "status": new_status,
            "version": new_version,
            "employee_rows": employee_rows,
            "updated_at": now,
        },
        "$push": {"history": history_entry},
    })

    # Mark affected slips as superseded
    if reopen_all:
        await db.payment_slips.update_many(
            {"pay_run_id": run_id, "org_id": org_id},
            {"$set": {"status": "superseded"}},
        )
    elif data.employee_ids:
        await db.payment_slips.update_many(
            {"pay_run_id": run_id, "org_id": org_id, "employee_id": {"$in": data.employee_ids}},
            {"$set": {"status": "superseded"}},
        )

    # Sync reopen downstream
    await sync_on_reopen(run, org_id, data.employee_ids if not reopen_all else None)

    return {"ok": True, "status": new_status, "reopened_count": reopened_count, "version": new_version}


# ── History ────────────────────────────────────────────────────────

@router.get("/pay-runs/{run_id}/history")
async def get_pay_run_history(run_id: str, user: dict = Depends(get_current_user)):
    run = await db.pay_runs.find_one(
        {"id": run_id, "org_id": user["org_id"]},
        {"_id": 0, "id": 1, "number": 1, "version": 1, "status": 1, "history": 1},
    )
    if not run:
        raise HTTPException(status_code=404, detail="Not found")
    return {"id": run["id"], "number": run.get("number"), "version": run.get("version", 1),
            "status": run.get("status"), "history": run.get("history", [])}



# ── Allocations ────────────────────────────────────────────────────

@router.get("/pay-runs/{run_id}/allocations")
async def get_pay_run_allocations(run_id: str, user: dict = Depends(get_current_user)):
    """Get allocation breakdown for a pay run — by employee, day, site."""
    org_id = user["org_id"]
    allocs = await db.pay_run_allocations.find(
        {"org_id": org_id, "pay_run_id": run_id}, {"_id": 0}
    ).to_list(200)

    # Also get allocation_summary from the run itself
    run = await db.pay_runs.find_one(
        {"id": run_id, "org_id": org_id},
        {"_id": 0, "allocation_summary": 1},
    )

    total_paid = round(sum(a.get("paid_now_amount", 0) for a in allocs), 2)
    total_remaining = round(sum(a.get("remaining_carry_forward", 0) for a in allocs), 2)

    return {
        "pay_run_id": run_id,
        "employees": allocs,
        "site_summary": (run or {}).get("allocation_summary", []),
        "total_paid": total_paid,
        "total_remaining": total_remaining,
    }


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


@router.get("/payment-slips/{slip_id}/pdf")
async def export_slip_pdf(slip_id: str, user: dict = Depends(get_current_user)):
    """Generate printable PDF payment slip."""
    from fastapi.responses import StreamingResponse
    import io

    org_id = user["org_id"]
    slip = await db.payment_slips.find_one({"id": slip_id, "org_id": org_id}, {"_id": 0})
    if not slip:
        raise HTTPException(status_code=404, detail="Slip not found")

    org = await db.organizations.find_one({"id": org_id}, {"_id": 0, "name": 1, "eik": 1, "address": 1, "city": 1})
    org_name = (org or {}).get("name", "")

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        # Register Cyrillic font
        import os
        font_path = os.path.join(os.path.dirname(__file__), "..", "..", "artifacts", "DejaVuSans.ttf")
        if not os.path.exists(font_path):
            font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        if os.path.exists(font_path):
            pdfmetrics.registerFont(TTFont("DejaVu", font_path))
            font_name = "DejaVu"
        else:
            font_name = "Helvetica"

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        w, h = A4

        def t(x, y, text, size=10, bold=False):
            fn = font_name
            c.setFont(fn, size)
            c.drawString(x * mm, (h - y * mm), str(text))

        def line(y):
            c.setStrokeColorRGB(0.3, 0.3, 0.3)
            c.line(15 * mm, h - y * mm, (w - 15 * mm), h - y * mm)

        # Header
        t(15, 20, org_name, 14)
        t(15, 27, f"ФИШ ЗА ЗАПЛАТА  №{slip.get('slip_number', '')}", 12)
        t(w / mm - 60, 27, f"Дата: {(slip.get('paid_at') or slip.get('created_at', ''))[:10]}", 9)

        line(32)

        # Employee info
        t(15, 40, f"Служител: {slip.get('first_name', '')} {slip.get('last_name', '')}", 11)
        t(15, 47, f"Длъжност: {slip.get('position', '—')}", 9)
        t(100, 40, f"Тип: {slip.get('pay_type', '')}", 9)
        t(100, 47, f"График: {slip.get('payment_schedule', '—')}", 9)

        line(52)

        # Period
        t(15, 58, f"Период: {slip.get('period_start', '')} — {slip.get('period_end', '')}", 10)
        t(100, 58, f"Седмица №: {slip.get('week_number', '—')}", 10)

        # Work summary
        t(15, 68, f"Работни дни: {slip.get('approved_days', 0)}", 10)
        t(70, 68, f"Часове: {slip.get('approved_hours', 0)}", 10)
        t(120, 68, f"Ставка: {slip.get('frozen_hourly_rate', 0)} EUR/ч", 10)

        line(73)

        # Calculation
        y = 82
        t(15, y, "ИЗЧИСЛЕНИЕ:", 10)
        y += 8
        t(20, y, "Изработено:", 10)
        t(120, y, f"{slip.get('earned_amount', 0):.2f} EUR", 10)

        if slip.get("adjustments"):
            for adj in slip["adjustments"]:
                y += 7
                prefix = "+" if adj.get("type") == "bonus" else "-"
                t(20, y, f"  {adj.get('title', adj.get('type', ''))}: {adj.get('note', '')}", 9)
                t(120, y, f"{prefix}{adj.get('amount', 0):.2f} EUR", 9)

        if slip.get("bonuses_amount", 0) > 0:
            y += 7
            t(20, y, "Бонуси:", 10)
            t(120, y, f"+{slip['bonuses_amount']:.2f} EUR", 10)

        if slip.get("deductions_amount", 0) > 0:
            y += 7
            t(20, y, "Удръжки:", 10)
            t(120, y, f"-{slip['deductions_amount']:.2f} EUR", 10)

        if slip.get("previously_paid", 0) > 0:
            y += 7
            t(20, y, "Вече платено:", 10)
            t(120, y, f"-{slip['previously_paid']:.2f} EUR", 10)

        y += 3
        line(y)
        y += 8
        t(20, y, "ПЛАТЕНО С ТОЗИ ФИШ:", 11)
        t(120, y, f"{slip.get('paid_now_amount', 0):.2f} EUR", 11)
        y += 8
        t(20, y, "ОСТАТЪК СЛЕД ПЛАЩАНЕТО:", 10)
        t(120, y, f"{slip.get('remaining_after_payment', 0):.2f} EUR", 10)

        # Sites
        if slip.get("sites"):
            y += 12
            t(15, y, f"Обекти: {', '.join(slip['sites'])}", 9)

        # Signatures
        y += 25
        line(y)
        y += 10
        t(20, y, "Работодател: _______________", 10)
        t(110, y, "Служител: _______________", 10)

        y += 15
        t(15, y, "Формула: Остатък = Изработено + Бонуси - Удръжки - Вече платено - Платено сега", 8)

        c.save()
        buf.seek(0)

        filename = f"fish_{slip.get('slip_number', 'unknown')}.pdf"
        return StreamingResponse(buf, media_type="application/pdf",
                                 headers={"Content-Disposition": f"inline; filename={filename}"})

    except ImportError:
        raise HTTPException(status_code=500, detail="PDF library not available")


# ── Payroll Weeks (calendar view) ──────────────────────────────────

@router.get("/payroll-weeks")
async def get_payroll_weeks(
    user: dict = Depends(get_current_user),
    employee_id: Optional[str] = None,
    month: Optional[str] = None,
    status: Optional[str] = None,
    only_unpaid: bool = False,
):
    """
    Payroll weeks view: all pay run rows grouped by week + unmatched approved weeks.
    """
    org_id = user["org_id"]

    q = {"org_id": org_id}
    if status:
        q["status"] = status
    runs = await db.pay_runs.find(q, {"_id": 0}).sort("period_start", -1).to_list(200)

    # Flatten: one row per employee per pay run
    rows = []
    for run in runs:
        for er in run.get("employee_rows", []):
            if employee_id and er.get("employee_id") != employee_id:
                continue
            if month:
                ps = run.get("period_start", "")
                pe = run.get("period_end", "")
                month_start = month + "-01"
                # Last day of month
                y, m = int(month[:4]), int(month[5:7])
                import calendar as cal_mod
                month_end = f"{month}-{cal_mod.monthrange(y, m)[1]:02d}"
                # Check overlap: period overlaps month
                if pe < month_start or ps > month_end:
                    continue

            row = {
                "pay_run_id": run["id"],
                "pay_run_number": run.get("number", ""),
                "run_type": run.get("run_type", ""),
                "period_start": run.get("period_start", ""),
                "period_end": run.get("period_end", ""),
                "week_number": run.get("week_number"),
                "run_status": run.get("status", ""),
                "paid_at": run.get("paid_at"),
                "employee_id": er.get("employee_id", ""),
                "first_name": er.get("first_name", ""),
                "last_name": er.get("last_name", ""),
                "position": er.get("position", ""),
                "pay_type": er.get("pay_type", ""),
                "approved_days": er.get("approved_days", 0),
                "approved_hours": er.get("approved_hours", 0),
                "earned_amount": er.get("earned_amount", 0),
                "bonuses_amount": er.get("bonuses_amount", 0),
                "deductions_amount": er.get("deductions_amount", 0),
                "previously_paid": er.get("previously_paid", 0),
                "paid_now_amount": er.get("paid_now_amount", 0),
                "remaining_after_payment": er.get("remaining_after_payment", 0),
                "adjustments": er.get("adjustments", []),
                "sites": er.get("sites", []),
            }

            if only_unpaid and row["run_status"] == "paid":
                continue

            # Find associated slip
            slip = await db.payment_slips.find_one(
                {"org_id": org_id, "pay_run_id": run["id"], "employee_id": er["employee_id"]},
                {"_id": 0, "id": 1, "slip_number": 1, "status": 1},
            )
            row["slip_id"] = slip["id"] if slip else None
            row["slip_number"] = slip["slip_number"] if slip else None
            row["slip_status"] = slip["status"] if slip else None

            rows.append(row)

    return {
        "items": rows,
        "total": len(rows),
    }
