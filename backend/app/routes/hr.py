"""
Routes - HR / Payroll (M4) Endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from datetime import datetime, timezone
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import require_m4
from app.utils.audit import log_audit
from ..models.hr import (
    PAY_TYPES, PAY_SCHEDULES, ADVANCE_TYPES, ADVANCE_STATUSES,
    PAYROLL_STATUSES, PAYSLIP_STATUSES, PAYMENT_METHODS,
    EmployeeProfileCreate, EmployeeProfileUpdate,
    AdvanceLoanCreate, PayrollRunCreate,
    SetDeductionsRequest, MarkPaidRequest
)

router = APIRouter(tags=["HR / Payroll"])

# ── Helpers ────────────────────────────────────────────────────────

def payroll_permission(user: dict) -> bool:
    """Check if user has payroll access"""
    return user["role"] in ["Admin", "Owner", "Accountant"]


# ── Employee Profiles ──────────────────────────────────────────────

@router.get("/employees")
async def list_employees(user: dict = Depends(require_m4)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    users = await db.users.find(
        {"org_id": user["org_id"], "role": {"$ne": "Admin"}},
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "name": 1, "email": 1, "role": 1, "phone": 1, "avatar_url": 1}
    ).to_list(500)
    
    # Get profiles
    profiles = await db.employee_profiles.find(
        {"org_id": user["org_id"]},
        {"_id": 0}
    ).to_list(500)
    profile_map = {p["user_id"]: p for p in profiles}
    
    result = []
    for u in users:
        prof = profile_map.get(u["id"])
        result.append({
            **u,
            "profile": prof,
            "has_profile": prof is not None,
        })
    return result


@router.get("/employees/{user_id}")
async def get_employee(user_id: str, user: dict = Depends(require_m4)):
    # Technicians can view own profile
    if user["id"] != user_id and not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    target = await db.users.find_one(
        {"id": user_id, "org_id": user["org_id"]},
        {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1}
    )
    if not target:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    profile = await db.employee_profiles.find_one(
        {"org_id": user["org_id"], "user_id": user_id},
        {"_id": 0}
    )
    return {**target, "profile": profile}


@router.post("/employees", status_code=201)
async def upsert_employee_profile(data: EmployeeProfileCreate, user: dict = Depends(require_m4)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    target = await db.users.find_one({"id": data.user_id, "org_id": user["org_id"]})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    
    now = datetime.now(timezone.utc).isoformat()
    existing = await db.employee_profiles.find_one({"org_id": user["org_id"], "user_id": data.user_id})
    
    profile = {
        "org_id": user["org_id"],
        "user_id": data.user_id,
        "pay_type": data.pay_type,
        "position": data.position,
        "hourly_rate": data.hourly_rate,
        "daily_rate": data.daily_rate,
        "monthly_salary": data.monthly_salary,
        "akord_note": data.akord_note,
        "standard_hours_per_day": data.standard_hours_per_day,
        "working_days_per_month": data.working_days_per_month,
        "pay_schedule": data.pay_schedule,
        "active": data.active,
        "start_date": data.start_date,
        "updated_at": now,
    }
    
    if existing:
        await db.employee_profiles.update_one(
            {"id": existing["id"]},
            {"$set": profile}
        )
        profile["id"] = existing["id"]
        profile["created_at"] = existing["created_at"]
    else:
        profile["id"] = str(uuid.uuid4())
        profile["created_at"] = now
        await db.employee_profiles.insert_one(profile)
    
    await log_audit(user["org_id"], user["id"], user["email"], "employee_profile_updated", "employee", data.user_id,
                    {"pay_type": data.pay_type})
    
    return {k: v for k, v in profile.items() if k != "_id"}


@router.put("/employees/{user_id}")
async def update_employee_profile(user_id: str, data: EmployeeProfileUpdate, user: dict = Depends(require_m4)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    profile = await db.employee_profiles.find_one({"org_id": user["org_id"], "user_id": user_id})
    if not profile:
        # Auto-create profile if missing
        now = datetime.now(timezone.utc).isoformat()
        profile = {
            "id": str(uuid.uuid4()),
            "org_id": user["org_id"],
            "user_id": user_id,
            "pay_type": "Monthly",
            "active": True,
            "standard_hours_per_day": 8,
            "working_days_per_month": 22,
            "created_at": now,
            "updated_at": now,
        }
        await db.employee_profiles.insert_one(profile)
    
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    await db.employee_profiles.update_one({"id": profile["id"]}, {"$set": update})
    await log_audit(user["org_id"], user["id"], user["email"], "employee_profile_updated", "employee", user_id, update)
    
    return await db.employee_profiles.find_one({"id": profile["id"]}, {"_id": 0})


@router.put("/employees/{user_id}/basic")
async def update_employee_basic(user_id: str, data: dict, user: dict = Depends(require_m4)):
    """Update employee basic info (name, phone, role)"""
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    target = await db.users.find_one({"id": user_id, "org_id": user["org_id"]})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    
    allowed = ["first_name", "last_name", "phone", "role", "avatar_url", "email"]
    update = {k: v for k, v in data.items() if k in allowed and v is not None}
    if update:
        update["updated_at"] = datetime.now(timezone.utc).isoformat()
        await db.users.update_one({"id": user_id}, {"$set": update})
    
    return await db.users.find_one({"id": user_id}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "email": 1, "phone": 1, "role": 1, "avatar_url": 1})


# ── Advances / Loans ───────────────────────────────────────────────

@router.get("/advances")
async def list_advances(
    user: dict = Depends(require_m4),
    user_id: Optional[str] = None,
    status: Optional[str] = None,
):
    # Technicians can view own advances
    if user["role"] == "Technician":
        user_id = user["id"]
    elif not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    query = {"org_id": user["org_id"]}
    if user_id:
        query["user_id"] = user_id
    if status:
        query["status"] = status
    
    advances = await db.advances.find(query, {"_id": 0}).sort("issued_date", -1).to_list(500)
    
    # Enrich with user name
    for adv in advances:
        u = await db.users.find_one({"id": adv["user_id"]}, {"_id": 0, "name": 1, "email": 1})
        adv["user_name"] = u.get("name", u.get("email", "Unknown").split("@")[0]) if u else "Unknown"
    
    return advances


@router.post("/advances", status_code=201)
async def create_advance(data: AdvanceLoanCreate, user: dict = Depends(require_m4)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    target = await db.users.find_one({"id": data.user_id, "org_id": user["org_id"]})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    
    now = datetime.now(timezone.utc).isoformat()
    advance = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "user_id": data.user_id,
        "type": data.type,
        "amount": data.amount,
        "remaining_amount": data.amount,
        "currency": data.currency,
        "issued_date": data.issued_date or now[:10],
        "note": data.note,
        "status": "Open",
        "created_at": now,
        "updated_at": now,
    }
    await db.advances.insert_one(advance)
    
    await log_audit(user["org_id"], user["id"], user["email"], "advance_created", "advance", advance["id"],
                    {"user_id": data.user_id, "type": data.type, "amount": data.amount})
    
    return {k: v for k, v in advance.items() if k != "_id"}


@router.post("/advances/{advance_id}/apply-deduction")
async def apply_advance_deduction(advance_id: str, amount: float, user: dict = Depends(require_m4)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    advance = await db.advances.find_one({"id": advance_id, "org_id": user["org_id"]})
    if not advance:
        raise HTTPException(status_code=404, detail="Advance not found")
    if advance["status"] == "Closed":
        raise HTTPException(status_code=400, detail="Advance already closed")
    if amount > advance["remaining_amount"]:
        raise HTTPException(status_code=400, detail="Amount exceeds remaining balance")
    
    new_remaining = round(advance["remaining_amount"] - amount, 2)
    new_status = "Closed" if new_remaining <= 0 else "Open"
    
    await db.advances.update_one({"id": advance_id}, {"$set": {
        "remaining_amount": new_remaining,
        "status": new_status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }})
    
    return await db.advances.find_one({"id": advance_id}, {"_id": 0})


# ── Payroll Runs ───────────────────────────────────────────────────

@router.get("/payroll-runs")
async def list_payroll_runs(user: dict = Depends(require_m4), status: Optional[str] = None):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    query = {"org_id": user["org_id"]}
    if status:
        query["status"] = status
    
    runs = await db.payroll_runs.find(query, {"_id": 0}).sort("created_at", -1).to_list(100)
    
    # Enrich with payslip counts
    for run in runs:
        payslip_count = await db.payslips.count_documents({"payroll_run_id": run["id"]})
        paid_count = await db.payslips.count_documents({"payroll_run_id": run["id"], "status": "Paid"})
        run["payslip_count"] = payslip_count
        run["paid_count"] = paid_count
    
    return runs


@router.post("/payroll-runs", status_code=201)
async def create_payroll_run(data: PayrollRunCreate, user: dict = Depends(require_m4)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    now = datetime.now(timezone.utc).isoformat()
    run = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "period_type": data.period_type,
        "period_start": data.period_start,
        "period_end": data.period_end,
        "status": "Draft",
        "created_by_user_id": user["id"],
        "created_at": now,
        "updated_at": now,
    }
    await db.payroll_runs.insert_one(run)
    
    await log_audit(user["org_id"], user["id"], user["email"], "payroll_run_created", "payroll_run", run["id"],
                    {"period_start": data.period_start, "period_end": data.period_end})
    
    return {k: v for k, v in run.items() if k != "_id"}


@router.get("/payroll-runs/{run_id}")
async def get_payroll_run(run_id: str, user: dict = Depends(require_m4)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    run = await db.payroll_runs.find_one({"id": run_id, "org_id": user["org_id"]}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    
    # Get payslips
    payslips = await db.payslips.find({"payroll_run_id": run_id}, {"_id": 0}).to_list(500)
    for ps in payslips:
        u = await db.users.find_one({"id": ps["user_id"]}, {"_id": 0, "name": 1, "email": 1})
        ps["user_name"] = u.get("name", u.get("email", "Unknown").split("@")[0]) if u else "Unknown"
        ps["user_email"] = u.get("email", "") if u else ""
    
    run["payslips"] = payslips
    return run


@router.post("/payroll-runs/{run_id}/generate")
async def generate_payroll(run_id: str, user: dict = Depends(require_m4)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    run = await db.payroll_runs.find_one({"id": run_id, "org_id": user["org_id"]})
    if not run:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    if run["status"] != "Draft":
        raise HTTPException(status_code=400, detail="Can only generate for Draft runs")
    
    period_start = run["period_start"]
    period_end = run["period_end"]
    org_id = user["org_id"]
    now = datetime.now(timezone.utc).isoformat()
    
    # Get active employee profiles
    profiles = await db.employee_profiles.find(
        {"org_id": org_id, "active": True},
        {"_id": 0}
    ).to_list(500)
    
    warnings = []
    created = 0
    
    # Get org currency
    org = await db.organizations.find_one({"id": org_id}, {"_id": 0, "currency": 1})
    currency = org.get("currency", "EUR") if org else "EUR"
    
    for profile in profiles:
        emp_user_id = profile["user_id"]
        pay_type = profile["pay_type"]
        base_amount = 0
        details = {
            "pay_type": pay_type,
            "period_start": period_start,
            "period_end": period_end,
        }
        
        if pay_type == "Hourly":
            # Sum hours from Submitted/Approved work reports
            reports = await db.work_reports.find({
                "org_id": org_id,
                "user_id": emp_user_id,
                "date": {"$gte": period_start, "$lte": period_end},
                "status": {"$in": ["Submitted", "Approved"]},
            }, {"_id": 0, "total_hours": 1}).to_list(500)
            total_hours = sum(r.get("total_hours", 0) for r in reports)
            hourly_rate = profile.get("hourly_rate") or 0
            base_amount = round(total_hours * hourly_rate, 2)
            details["total_hours"] = total_hours
            details["hourly_rate"] = hourly_rate
            
        elif pay_type == "Daily":
            # Count Present/Late attendance entries
            attendance = await db.attendance_entries.count_documents({
                "org_id": org_id,
                "user_id": emp_user_id,
                "date": {"$gte": period_start, "$lte": period_end},
                "status": {"$in": ["Present", "Late"]},
            })
            daily_rate = profile.get("daily_rate") or 0
            base_amount = round(attendance * daily_rate, 2)
            details["days_present"] = attendance
            details["daily_rate"] = daily_rate
            
        elif pay_type == "Monthly":
            # Fixed salary
            base_amount = profile.get("monthly_salary") or 0
            details["monthly_salary"] = base_amount
        
        # Check if payslip exists, update or create
        existing = await db.payslips.find_one({
            "payroll_run_id": run_id,
            "user_id": emp_user_id,
        })
        
        payslip = {
            "org_id": org_id,
            "payroll_run_id": run_id,
            "user_id": emp_user_id,
            "base_amount": base_amount,
            "overtime_amount": 0,
            "deductions_amount": existing.get("deductions_amount", 0) if existing else 0,
            "advances_deducted_amount": existing.get("advances_deducted_amount", 0) if existing else 0,
            "currency": currency,
            "details_json": details,
            "status": "Draft",
            "paid_at": None,
            "paid_by_user_id": None,
            "updated_at": now,
        }
        payslip["net_pay"] = round(
            payslip["base_amount"] + payslip["overtime_amount"] 
            - payslip["deductions_amount"] - payslip["advances_deducted_amount"], 2
        )
        
        if existing:
            await db.payslips.update_one({"id": existing["id"]}, {"$set": payslip})
        else:
            payslip["id"] = str(uuid.uuid4())
            payslip["created_at"] = now
            await db.payslips.insert_one(payslip)
            created += 1
    
    # Log users without profiles
    all_users = await db.users.find(
        {"org_id": org_id, "role": {"$nin": ["Admin", "Owner", "Accountant"]}},
        {"_id": 0, "id": 1, "name": 1, "email": 1}
    ).to_list(500)
    profile_user_ids = {p["user_id"] for p in profiles}
    for u in all_users:
        if u["id"] not in profile_user_ids:
            name = u.get("name", u.get("email", "Unknown").split("@")[0])
            warnings.append(f"{name} has no pay profile")
    
    await log_audit(org_id, user["id"], user["email"], "payroll_generated", "payroll_run", run_id,
                    {"created": created, "profiles": len(profiles)})
    
    return {
        "ok": True,
        "created": created,
        "updated": len(profiles) - created,
        "warnings": warnings,
    }


@router.post("/payroll-runs/{run_id}/finalize")
async def finalize_payroll(run_id: str, user: dict = Depends(require_m4)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    run = await db.payroll_runs.find_one({"id": run_id, "org_id": user["org_id"]})
    if not run:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    if run["status"] != "Draft":
        raise HTTPException(status_code=400, detail="Can only finalize Draft runs")
    
    # Check there are payslips
    count = await db.payslips.count_documents({"payroll_run_id": run_id})
    if count == 0:
        raise HTTPException(status_code=400, detail="Generate payslips before finalizing")
    
    now = datetime.now(timezone.utc).isoformat()
    
    # Finalize run and all payslips
    await db.payroll_runs.update_one({"id": run_id}, {"$set": {
        "status": "Finalized",
        "updated_at": now,
    }})
    await db.payslips.update_many({"payroll_run_id": run_id}, {"$set": {
        "status": "Finalized",
        "updated_at": now,
    }})
    
    await log_audit(user["org_id"], user["id"], user["email"], "payroll_finalized", "payroll_run", run_id, {})
    
    return await db.payroll_runs.find_one({"id": run_id}, {"_id": 0})


@router.delete("/payroll-runs/{run_id}")
async def delete_payroll_run(run_id: str, user: dict = Depends(require_m4)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    run = await db.payroll_runs.find_one({"id": run_id, "org_id": user["org_id"]})
    if not run:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    if run["status"] != "Draft":
        raise HTTPException(status_code=400, detail="Can only delete Draft runs")
    
    await db.payslips.delete_many({"payroll_run_id": run_id})
    await db.payroll_runs.delete_one({"id": run_id})
    
    return {"ok": True}


# ── Payslips ───────────────────────────────────────────────────────

@router.get("/payslips")
async def list_payslips(
    user: dict = Depends(require_m4),
    payroll_run_id: Optional[str] = None,
    user_id: Optional[str] = None,
):
    # Technicians can only view own
    if user["role"] == "Technician":
        user_id = user["id"]
    elif not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    query = {"org_id": user["org_id"]}
    if payroll_run_id:
        query["payroll_run_id"] = payroll_run_id
    if user_id:
        query["$or"] = [{"user_id": user_id}, {"employee_id": user_id}]
    
    payslips = await db.payslips.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    
    # Enrich
    for ps in payslips:
        uid = ps.get("user_id") or ps.get("employee_id")
        u = await db.users.find_one({"id": uid}, {"_id": 0, "first_name": 1, "last_name": 1, "email": 1})
        if u:
            ps["user_name"] = f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or u.get("email", "Unknown").split("@")[0]
        elif ps.get("employee_name"):
            ps["user_name"] = ps["employee_name"]
        else:
            ps["user_name"] = "Unknown"
        # Period: from payroll_run or from payslip directly (synced records)
        if not ps.get("period_start"):
            run = await db.payroll_runs.find_one({"id": ps.get("payroll_run_id")}, {"_id": 0, "period_start": 1, "period_end": 1})
            if run:
                ps["period_start"] = run.get("period_start")
                ps["period_end"] = run.get("period_end")
    
    return payslips


@router.get("/payslips/{payslip_id}")
async def get_payslip(payslip_id: str, user: dict = Depends(require_m4)):
    payslip = await db.payslips.find_one({"id": payslip_id, "org_id": user["org_id"]}, {"_id": 0})
    if not payslip:
        raise HTTPException(status_code=404, detail="Payslip not found")
    
    # Technicians can only view own
    if user["role"] == "Technician" and payslip["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Enrich
    u = await db.users.find_one({"id": payslip["user_id"]}, {"_id": 0, "name": 1, "email": 1})
    payslip["user_name"] = u.get("name", u.get("email", "Unknown").split("@")[0]) if u else "Unknown"
    payslip["user_email"] = u.get("email", "") if u else ""
    
    run = await db.payroll_runs.find_one({"id": payslip["payroll_run_id"]}, {"_id": 0})
    payslip["payroll_run"] = run
    
    return payslip


@router.post("/payslips/{payslip_id}/set-deductions")
async def set_payslip_deductions(payslip_id: str, data: SetDeductionsRequest, user: dict = Depends(require_m4)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    payslip = await db.payslips.find_one({"id": payslip_id, "org_id": user["org_id"]})
    if not payslip:
        raise HTTPException(status_code=404, detail="Payslip not found")
    
    run = await db.payroll_runs.find_one({"id": payslip["payroll_run_id"]})
    if run["status"] != "Draft":
        raise HTTPException(status_code=400, detail="Can only edit deductions for Draft payroll")
    
    # Process advance deductions
    advances_total = 0
    advance_details = []
    for adv_ded in data.advances_to_deduct:
        adv_id = adv_ded.get("advance_id")
        adv_amount = adv_ded.get("amount", 0)
        if adv_id and adv_amount > 0:
            advance = await db.advances.find_one({"id": adv_id, "org_id": user["org_id"]})
            if advance and advance["status"] == "Open":
                actual = min(adv_amount, advance["remaining_amount"])
                advances_total += actual
                advance_details.append({"advance_id": adv_id, "amount": actual})
    
    net_pay = round(
        payslip["base_amount"] + payslip.get("overtime_amount", 0) 
        - data.deductions_amount - advances_total, 2
    )
    
    await db.payslips.update_one({"id": payslip_id}, {"$set": {
        "deductions_amount": data.deductions_amount,
        "advances_deducted_amount": advances_total,
        "advance_deductions": advance_details,
        "net_pay": net_pay,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }})
    
    return await db.payslips.find_one({"id": payslip_id}, {"_id": 0})


@router.post("/payslips/{payslip_id}/mark-paid")
async def mark_payslip_paid(payslip_id: str, data: MarkPaidRequest, user: dict = Depends(require_m4)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    payslip = await db.payslips.find_one({"id": payslip_id, "org_id": user["org_id"]})
    if not payslip:
        raise HTTPException(status_code=404, detail="Payslip not found")
    
    run = await db.payroll_runs.find_one({"id": payslip["payroll_run_id"]})
    if run["status"] == "Draft":
        raise HTTPException(status_code=400, detail="Finalize payroll before marking paid")
    if payslip["status"] == "Paid":
        raise HTTPException(status_code=400, detail="Already paid")
    
    now = datetime.now(timezone.utc).isoformat()
    
    # Apply advance deductions
    for adv_ded in payslip.get("advance_deductions", []):
        adv_id = adv_ded.get("advance_id")
        adv_amount = adv_ded.get("amount", 0)
        if adv_id and adv_amount > 0:
            advance = await db.advances.find_one({"id": adv_id})
            if advance and advance["status"] == "Open":
                new_remaining = max(0, round(advance["remaining_amount"] - adv_amount, 2))
                new_status = "Closed" if new_remaining <= 0 else "Open"
                await db.advances.update_one({"id": adv_id}, {"$set": {
                    "remaining_amount": new_remaining,
                    "status": new_status,
                    "updated_at": now,
                }})
    
    # Create payment record
    payment = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "payroll_run_id": payslip["payroll_run_id"],
        "payslip_id": payslip_id,
        "user_id": payslip["user_id"],
        "amount": payslip["net_pay"],
        "currency": payslip["currency"],
        "method": data.method,
        "reference": data.reference,
        "note": data.note,
        "paid_at": now,
        "paid_by_user_id": user["id"],
    }
    await db.payroll_payments.insert_one(payment)
    
    # Update payslip
    await db.payslips.update_one({"id": payslip_id}, {"$set": {
        "status": "Paid",
        "paid_at": now,
        "paid_by_user_id": user["id"],
        "updated_at": now,
    }})
    
    # Check if all payslips paid -> update run status
    unpaid = await db.payslips.count_documents({
        "payroll_run_id": payslip["payroll_run_id"],
        "status": {"$ne": "Paid"},
    })
    if unpaid == 0:
        await db.payroll_runs.update_one({"id": payslip["payroll_run_id"]}, {"$set": {
            "status": "Paid",
            "updated_at": now,
        }})
    
    await log_audit(user["org_id"], user["id"], user["email"], "payslip_paid", "payslip", payslip_id,
                    {"amount": payslip["net_pay"], "method": data.method})
    
    return await db.payslips.find_one({"id": payslip_id}, {"_id": 0})


@router.get("/payroll-enums")
async def get_payroll_enums():
    return {
        "pay_types": PAY_TYPES,
        "pay_schedules": PAY_SCHEDULES,
        "advance_types": ADVANCE_TYPES,
        "payroll_statuses": PAYROLL_STATUSES,
        "payment_methods": PAYMENT_METHODS,
    }



# ── Employee Dashboard / Detail ────────────────────────────────────

@router.get("/employees/{user_id}/dashboard")
async def get_employee_dashboard(user_id: str, user: dict = Depends(require_m4)):
    """Comprehensive employee detail with attendance, projects, hours"""
    org_id = user["org_id"]
    if user["id"] != user_id and not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    target = await db.users.find_one({"id": user_id, "org_id": org_id},
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "email": 1, "role": 1, "phone": 1, "avatar_url": 1})
    if not target:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    profile = await db.employee_profiles.find_one({"org_id": org_id, "user_id": user_id}, {"_id": 0})
    
    # Recent attendance (last 30 days)
    from datetime import timedelta
    cutoff_30 = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    attendance = await db.attendance_entries.find(
        {"org_id": org_id, "user_id": user_id, "date": {"$gte": cutoff_30}},
        {"_id": 0}
    ).sort("date", -1).to_list(60)
    
    # Enrich attendance with project names
    for att in attendance:
        if att.get("project_id"):
            p = await db.projects.find_one({"id": att["project_id"]}, {"_id": 0, "code": 1, "name": 1})
            att["project_code"] = p["code"] if p else ""
            att["project_name"] = p["name"] if p else ""
    
    # Project history from team assignments
    team_entries = await db.project_team.find(
        {"user_id": user_id}, {"_id": 0}
    ).to_list(100)
    
    project_history = []
    for te in team_entries:
        p = await db.projects.find_one({"id": te["project_id"], "org_id": org_id}, {"_id": 0, "code": 1, "name": 1, "status": 1})
        if p:
            # Count attendance days for this project
            days = await db.attendance_entries.count_documents(
                {"org_id": org_id, "user_id": user_id, "project_id": te["project_id"], "status": "Present"})
            # Count work report hours
            reports = await db.work_reports.find(
                {"org_id": org_id, "user_id": user_id, "project_id": te["project_id"]},
                {"_id": 0, "lines": 1}
            ).to_list(500)
            total_hours = sum(
                sum(l.get("hours", 0) for l in r.get("lines", []))
                for r in reports
            )
            last_att = await db.attendance_entries.find_one(
                {"org_id": org_id, "user_id": user_id, "project_id": te["project_id"]},
                {"_id": 0, "date": 1}, sort=[("date", -1)])
            
            project_history.append({
                "project_id": te["project_id"],
                "project_code": p["code"],
                "project_name": p["name"],
                "project_status": p["status"],
                "role_in_project": te.get("role_in_project", ""),
                "days_present": days,
                "total_hours": round(total_hours, 1),
                "last_attendance": last_att["date"] if last_att else None,
                "active": te.get("active", True),
            })
    
    project_history.sort(key=lambda x: x.get("last_attendance") or "", reverse=True)
    
    # Also include projects from daily reports not covered by project_team
    daily_project_ids = await db.employee_daily_reports.distinct("day_entries.project_id", {"org_id": org_id, "employee_id": user_id})
    existing_pids = set(ph["project_id"] for ph in project_history)
    for dpid in daily_project_ids:
        if not dpid or dpid in existing_pids:
            continue
        p = await db.projects.find_one({"id": dpid, "org_id": org_id}, {"_id": 0, "code": 1, "name": 1, "status": 1})
        if not p:
            continue
        # Count hours from daily reports
        dr_list = await db.employee_daily_reports.find(
            {"org_id": org_id, "employee_id": user_id, "day_entries.project_id": dpid},
            {"_id": 0, "day_entries": 1, "report_date": 1}
        ).to_list(500)
        dr_hours = 0
        dr_days = set()
        last_date = None
        for dr in dr_list:
            for e in dr.get("day_entries", []):
                if e.get("project_id") == dpid:
                    dr_hours += e.get("hours_worked", 0)
                    dr_days.add(dr["report_date"])
            if not last_date or dr["report_date"] > last_date:
                last_date = dr["report_date"]
        project_history.append({
            "project_id": dpid,
            "project_code": p["code"],
            "project_name": p["name"],
            "project_status": p.get("status", ""),
            "role_in_project": "",
            "days_present": len(dr_days),
            "total_hours": round(dr_hours, 1),
            "last_attendance": last_date,
            "active": True,
            "source": "daily_reports",
        })
    project_history.sort(key=lambda x: x.get("last_attendance") or "", reverse=True)
    
    # Hours summary (current month) — includes both old work_reports and new daily_reports
    month_start = datetime.now(timezone.utc).strftime("%Y-%m-01")
    month_att = await db.attendance_entries.count_documents(
        {"org_id": org_id, "user_id": user_id, "date": {"$gte": month_start}, "status": "Present"})
    month_reports = await db.work_reports.find(
        {"org_id": org_id, "user_id": user_id, "created_at": {"$gte": month_start + "T00:00:00"}},
        {"_id": 0, "lines": 1}
    ).to_list(100)
    month_hours = sum(sum(l.get("hours", 0) for l in r.get("lines", [])) for r in month_reports)
    
    # Add hours from daily reports
    month_daily = await db.employee_daily_reports.find(
        {"org_id": org_id, "employee_id": user_id, "report_date": {"$gte": month_start}},
        {"_id": 0, "total_hours": 1, "report_date": 1}
    ).to_list(31)
    daily_hours = sum(r.get("total_hours", 0) for r in month_daily)
    daily_days = len(month_daily)
    
    combined_hours = month_hours + daily_hours
    combined_days = month_att + daily_days
    
    # Recent payslips - enrich with period info from payroll_run
    payslips_raw = await db.payslips.find(
        {"org_id": org_id, "user_id": user_id},
        {"_id": 0, "id": 1, "payroll_run_id": 1, "base_amount": 1, "net_pay": 1, "status": 1}
    ).sort("created_at", -1).limit(5).to_list(5)
    
    payslips = []
    for ps in payslips_raw:
        run = await db.payroll_runs.find_one({"id": ps["payroll_run_id"]}, {"_id": 0, "period_start": 1, "period_end": 1})
        ps["period_start"] = run.get("period_start") if run else None
        ps["period_end"] = run.get("period_end") if run else None
        ps["gross_pay"] = ps.get("base_amount", 0)
        del ps["payroll_run_id"]
        del ps["base_amount"]
        payslips.append(ps)
    
    return {
        "employee": target,
        "profile": profile,
        "attendance": attendance,
        "project_history": project_history,
        "hours_summary": {
            "current_month_days": combined_days,
            "current_month_hours": round(combined_hours, 1),
            "total_projects": len(project_history),
        },
        "payslips": payslips,
    }


@router.get("/employees/{user_id}/calendar")
async def get_employee_calendar(user_id: str, month: str = None, user: dict = Depends(require_m4)):
    """Get calendar data for employee (attendance + work reports by day)"""
    org_id = user["org_id"]
    if user["id"] != user_id and not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    if not month:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
    
    date_from = f"{month}-01"
    # Calculate last day of month
    y, m = int(month[:4]), int(month[5:7])
    if m == 12:
        date_to = f"{y+1}-01-01"
    else:
        date_to = f"{y}-{m+1:02d}-01"
    
    attendance = await db.attendance_entries.find(
        {"org_id": org_id, "user_id": user_id, "date": {"$gte": date_from, "$lt": date_to}},
        {"_id": 0}
    ).to_list(31)
    
    # Enrich with project info
    for att in attendance:
        if att.get("project_id"):
            p = await db.projects.find_one({"id": att["project_id"]}, {"_id": 0, "code": 1, "name": 1})
            att["project_code"] = p["code"] if p else ""
    
    work_reports = await db.work_reports.find(
        {"org_id": org_id, "user_id": user_id, "date": {"$gte": date_from, "$lt": date_to}},
        {"_id": 0, "date": 1, "project_id": 1, "lines": 1, "status": 1}
    ).to_list(31)
    
    for wr in work_reports:
        wr["total_hours"] = sum(l.get("hours", 0) for l in wr.get("lines", []))
        if wr.get("project_id"):
            p = await db.projects.find_one({"id": wr["project_id"]}, {"_id": 0, "code": 1})
            wr["project_code"] = p["code"] if p else ""
    
    # Build calendar entries by day
    days = {}
    for att in attendance:
        d = att["date"]
        if d not in days:
            days[d] = {"date": d, "attendance": None, "work_reports": [], "daily_report": None, "total_hours": 0}
        days[d]["attendance"] = {"status": att["status"], "project_code": att.get("project_code", "")}
    
    for wr in work_reports:
        d = wr.get("date", "")
        if d and d not in days:
            days[d] = {"date": d, "attendance": None, "work_reports": [], "daily_report": None, "total_hours": 0}
        if d:
            days[d]["work_reports"].append({"project_code": wr.get("project_code", ""), "hours": wr["total_hours"]})
            days[d]["total_hours"] += wr["total_hours"]
    
    # Include employee_daily_reports (new structured reports)
    daily_reports = await db.employee_daily_reports.find(
        {"org_id": org_id, "employee_id": user_id, "report_date": {"$gte": date_from, "$lt": date_to}},
        {"_id": 0, "report_date": 1, "day_status": 1, "approval_status": 1, "total_hours": 1, "day_entries": 1}
    ).to_list(31)
    
    for dr in daily_reports:
        d = dr.get("report_date", "")
        if not d:
            continue
        if d not in days:
            days[d] = {"date": d, "attendance": None, "work_reports": [], "daily_report": None, "total_hours": 0}
        # Build project codes from entries
        proj_codes = []
        for entry in dr.get("day_entries", []):
            if entry.get("project_id"):
                p = await db.projects.find_one({"id": entry["project_id"]}, {"_id": 0, "code": 1})
                if p:
                    proj_codes.append(p["code"])
        days[d]["daily_report"] = {
            "day_status": dr["day_status"],
            "approval_status": dr["approval_status"],
            "hours": dr.get("total_hours", 0),
            "project_codes": list(set(proj_codes)),
        }
        # Add hours if not already counted
        if days[d]["total_hours"] == 0:
            days[d]["total_hours"] += dr.get("total_hours", 0)
        # Set attendance from daily report if no old attendance exists
        if not days[d]["attendance"] and dr["day_status"] == "WORKING":
            days[d]["attendance"] = {"status": "Present", "project_code": ", ".join(set(proj_codes))}
        elif not days[d]["attendance"] and dr["day_status"] == "LEAVE":
            days[d]["attendance"] = {"status": "Leave", "project_code": ""}
        elif not days[d]["attendance"] and dr["day_status"] == "SICK":
            days[d]["attendance"] = {"status": "Sick", "project_code": ""}
        elif not days[d]["attendance"] and dr["day_status"] == "ABSENT_UNEXCUSED":
            days[d]["attendance"] = {"status": "Absent", "project_code": ""}
    
    return {
        "month": month,
        "days": sorted(days.values(), key=lambda x: x["date"]),
        "total_present": sum(1 for d in days.values() if d.get("attendance") and d["attendance"].get("status") == "Present"),
        "total_hours": round(sum(d["total_hours"] for d in days.values()), 1),
    }


# ═══════════════════════════════════════════════════════════════════
# WEEKLY PAYROLL + CONTRACT PAYMENTS
# ═══════════════════════════════════════════════════════════════════

from pydantic import BaseModel as PydanticBaseModel
from typing import List as TypingList

class WeeklyRunCreate(PydanticBaseModel):
    week_start: str
    week_end: str
    name: Optional[str] = None

class ContractPaymentCreate(PydanticBaseModel):
    worker_name: str
    worker_id: Optional[str] = None
    contract_type: str = "one_time"
    description: str = ""
    total_amount: float
    site_id: Optional[str] = None
    activity_budget_id: Optional[str] = None
    tranches: list = []

class ContractPaymentUpdate(PydanticBaseModel):
    worker_name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None

class PayTrancheRequest(PydanticBaseModel):
    tranche_index: int
    paid_date: Optional[str] = None
    notes: Optional[str] = None


# ── Weekly Payroll ─────────────────────────────────────────────────

@router.post("/payroll/weekly-run", status_code=201)
async def create_weekly_run(data: WeeklyRunCreate, user: dict = Depends(require_m4)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    now = datetime.now(timezone.utc).isoformat()
    name = data.name or f"Седмичен {data.week_start} — {data.week_end}"
    run = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "period_type": "weekly",
        "period_start": data.week_start,
        "period_end": data.week_end,
        "source": "work_sessions",
        "status": "Draft",
        "name": name,
        "created_by_user_id": user["id"],
        "created_at": now,
        "updated_at": now,
    }
    await db.payroll_runs.insert_one(run)
    return {k: v for k, v in run.items() if k != "_id"}


@router.post("/payroll/{run_id}/generate-weekly")
async def generate_weekly_payroll(run_id: str, user: dict = Depends(require_m4)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    run = await db.payroll_runs.find_one({"id": run_id, "org_id": user["org_id"]})
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run["status"] != "Draft":
        raise HTTPException(status_code=400, detail="Can only generate for Draft runs")

    org_id = user["org_id"]
    ws = run.get("period_start", "")
    we = run.get("period_end", "")
    now = datetime.now(timezone.utc).isoformat()

    # Get all work sessions in the period
    sessions = await db.work_sessions.find(
        {"org_id": org_id, "ended_at": {"$ne": None},
         "started_at": {"$gte": f"{ws}T00:00:00", "$lte": f"{we}T23:59:59"}},
        {"_id": 0},
    ).to_list(5000)

    # Group by worker
    by_worker = {}
    for s in sessions:
        wid = s["worker_id"]
        if wid not in by_worker:
            by_worker[wid] = []
        by_worker[wid].append(s)

    org = await db.organizations.find_one({"id": org_id}, {"_id": 0, "currency": 1})
    currency = org.get("currency", "EUR") if org else "EUR"

    created = 0
    for wid, worker_sessions in by_worker.items():
        regular_hours = 0
        ot_over8 = 0
        ot_after20 = 0
        ot_weekend = 0
        regular_amount = 0
        overtime_amount = 0
        session_ids = []

        for s in worker_sessions:
            dur = s.get("duration_hours", 0) or 0
            rate = s.get("hourly_rate_at_date", 0) or 0
            coeff = s.get("overtime_coefficient", 1.0) or 1.0
            session_ids.append(s["id"])

            if s.get("is_overtime"):
                ot_type = s.get("overtime_type", "over_8h")
                if ot_type == "weekend":
                    ot_weekend += dur
                elif ot_type == "after_20":
                    ot_after20 += dur
                else:
                    ot_over8 += dur
                overtime_amount += round(dur * rate * coeff, 2)
            else:
                regular_hours += dur
                regular_amount += round(dur * rate, 2)

        gross = round(regular_amount + overtime_amount, 2)

        # Get pending advances for deduction
        advances = await db.advances.find(
            {"org_id": org_id, "user_id": wid, "status": "Open"},
            {"_id": 0},
        ).to_list(50)
        deductions = 0
        advance_refs = []
        for adv in advances:
            remaining = (adv.get("amount", 0) or 0) - (adv.get("deducted_amount", 0) or 0)
            if remaining > 0:
                to_deduct = min(remaining, gross - deductions)
                if to_deduct > 0:
                    deductions += to_deduct
                    advance_refs.append({"advance_id": adv["id"], "amount": round(to_deduct, 2)})

        net = round(gross - deductions, 2)

        # Get worker info
        u = await db.users.find_one({"id": wid}, {"_id": 0, "name": 1, "first_name": 1, "last_name": 1, "email": 1})
        worker_name = ""
        if u:
            worker_name = u.get("name") or f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()

        existing = await db.payslips.find_one({"payroll_run_id": run_id, "user_id": wid})

        payslip = {
            "org_id": org_id,
            "payroll_run_id": run_id,
            "user_id": wid,
            "base_amount": round(regular_amount, 2),
            "overtime_amount": round(overtime_amount, 2),
            "regular_hours": round(regular_hours, 2),
            "overtime_hours": round(ot_over8 + ot_after20 + ot_weekend, 2),
            "overtime_breakdown": {
                "over_8h": round(ot_over8, 2),
                "after_20": round(ot_after20, 2),
                "weekend": round(ot_weekend, 2),
            },
            "regular_amount": round(regular_amount, 2),
            "gross_amount": gross,
            "deductions_amount": round(deductions, 2),
            "advances_deducted_amount": round(deductions, 2),
            "net_pay": net,
            "currency": currency,
            "work_sessions_ids": session_ids,
            "advance_refs": advance_refs,
            "details_json": {"source": "work_sessions", "period": f"{ws} — {we}", "worker_name": worker_name},
            "status": "Draft",
            "paid_at": None,
            "paid_by_user_id": None,
            "updated_at": now,
        }

        if existing:
            await db.payslips.update_one({"id": existing["id"]}, {"$set": payslip})
        else:
            payslip["id"] = str(uuid.uuid4())
            payslip["created_at"] = now
            await db.payslips.insert_one(payslip)
            created += 1

    return {"ok": True, "created": created, "workers": len(by_worker)}


@router.get("/payroll/my-weekly-summary")
async def my_weekly_summary(
    week_start: Optional[str] = None,
    week_end: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    org_id = user["org_id"]
    wid = user["id"]
    now = datetime.now(timezone.utc)

    if not week_start:
        # Current week (Mon-Sun)
        mon = now - __import__("datetime").timedelta(days=now.weekday())
        week_start = mon.strftime("%Y-%m-%d")
    if not week_end:
        ws_dt = datetime.strptime(week_start, "%Y-%m-%d")
        week_end = (ws_dt + __import__("datetime").timedelta(days=6)).strftime("%Y-%m-%d")

    sessions = await db.work_sessions.find(
        {"org_id": org_id, "worker_id": wid, "ended_at": {"$ne": None},
         "started_at": {"$gte": f"{week_start}T00:00:00", "$lte": f"{week_end}T23:59:59"}},
        {"_id": 0},
    ).to_list(200)

    regular_hours = 0
    ot_hours = 0
    ot_breakdown = {"over_8h": 0, "after_20": 0, "weekend": 0}
    gross = 0
    for s in sessions:
        dur = s.get("duration_hours", 0) or 0
        cost = s.get("labor_cost", 0) or 0
        gross += cost
        if s.get("is_overtime"):
            ot_hours += dur
            ot_type = s.get("overtime_type", "over_8h")
            ot_breakdown[ot_type] = ot_breakdown.get(ot_type, 0) + dur
        else:
            regular_hours += dur

    # Pending advances
    advances = await db.advances.find({"org_id": org_id, "user_id": wid, "status": "Open"}, {"_id": 0}).to_list(20)
    pending_deductions = sum(max((a.get("amount", 0) or 0) - (a.get("deducted_amount", 0) or 0), 0) for a in advances)

    net = round(gross - min(pending_deductions, gross), 2)

    return {
        "week_start": week_start,
        "week_end": week_end,
        "regular_hours": round(regular_hours, 2),
        "overtime_hours": round(ot_hours, 2),
        "overtime_breakdown": {k: round(v, 2) for k, v in ot_breakdown.items()},
        "gross": round(gross, 2),
        "pending_deductions": round(pending_deductions, 2),
        "net": net,
        "sessions_count": len(sessions),
    }


# ── Contract Payments ──────────────────────────────────────────────

@router.post("/contract-payments", status_code=201)
async def create_contract_payment(data: ContractPaymentCreate, user: dict = Depends(require_m4)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    now = datetime.now(timezone.utc).isoformat()
    tranches = data.tranches
    if not tranches:
        tranches = [{"amount": data.total_amount, "due_date": now[:10], "paid_date": None, "status": "pending", "paid_by": None, "notes": ""}]
    else:
        for t in tranches:
            t.setdefault("status", "pending")
            t.setdefault("paid_date", None)
            t.setdefault("paid_by", None)
            t.setdefault("notes", "")

    doc = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "worker_name": data.worker_name,
        "worker_id": data.worker_id,
        "contract_type": data.contract_type,
        "description": data.description,
        "total_amount": data.total_amount,
        "site_id": data.site_id,
        "activity_budget_id": data.activity_budget_id,
        "tranches": tranches,
        "status": "active",
        "created_at": now,
        "updated_at": now,
        "created_by": user["id"],
    }
    await db.contract_payments.insert_one(doc)
    return {k: v for k, v in doc.items() if k != "_id"}


@router.get("/contract-payments")
async def list_contract_payments(
    site_id: Optional[str] = None,
    status: Optional[str] = None,
    worker_name: Optional[str] = None,
    user: dict = Depends(require_m4),
):
    query = {"org_id": user["org_id"]}
    if site_id:
        query["site_id"] = site_id
    if status:
        query["status"] = status
    if worker_name:
        query["worker_name"] = {"$regex": worker_name, "$options": "i"}
    items = await db.contract_payments.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"items": items, "total": len(items)}


@router.get("/contract-payments/{payment_id}")
async def get_contract_payment(payment_id: str, user: dict = Depends(require_m4)):
    doc = await db.contract_payments.find_one({"id": payment_id, "org_id": user["org_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Contract payment not found")
    return doc


@router.put("/contract-payments/{payment_id}")
async def update_contract_payment(payment_id: str, data: ContractPaymentUpdate, user: dict = Depends(require_m4)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    doc = await db.contract_payments.find_one({"id": payment_id, "org_id": user["org_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.contract_payments.update_one({"id": payment_id}, {"$set": update})
    return await db.contract_payments.find_one({"id": payment_id}, {"_id": 0})


@router.post("/contract-payments/{payment_id}/pay-tranche")
async def pay_tranche(payment_id: str, data: PayTrancheRequest, user: dict = Depends(require_m4)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    doc = await db.contract_payments.find_one({"id": payment_id, "org_id": user["org_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")

    tranches = doc.get("tranches", [])
    idx = data.tranche_index
    if idx < 0 or idx >= len(tranches):
        raise HTTPException(status_code=400, detail="Invalid tranche index")
    if tranches[idx]["status"] == "paid":
        raise HTTPException(status_code=400, detail="Tranche already paid")

    now = datetime.now(timezone.utc).isoformat()
    tranches[idx]["status"] = "paid"
    tranches[idx]["paid_date"] = data.paid_date or now[:10]
    tranches[idx]["paid_by"] = user["id"]
    tranches[idx]["notes"] = data.notes or tranches[idx].get("notes", "")

    # Check if all tranches paid → complete
    all_paid = all(t["status"] == "paid" for t in tranches)
    new_status = "completed" if all_paid else "active"

    await db.contract_payments.update_one(
        {"id": payment_id},
        {"$set": {"tranches": tranches, "status": new_status, "updated_at": now}},
    )
    return await db.contract_payments.find_one({"id": payment_id}, {"_id": 0})


@router.delete("/contract-payments/{payment_id}")
async def delete_contract_payment(payment_id: str, user: dict = Depends(require_m4)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    doc = await db.contract_payments.find_one({"id": payment_id, "org_id": user["org_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    if any(t["status"] == "paid" for t in doc.get("tranches", [])):
        raise HTTPException(status_code=400, detail="Cannot delete: has paid tranches")
    await db.contract_payments.delete_one({"id": payment_id})
    return {"ok": True}
