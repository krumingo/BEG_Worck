"""
Routes - HR / Payroll (M4) Endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from datetime import datetime, timezone
import uuid

from app.db import db
from app.services.legacy_payslips import legacy_payslips, legacy_payslip_one
from app.deps.auth import get_current_user
from app.deps.modules import require_m4
from app.utils.audit import log_audit
from app.services.report_normalizer import fetch_normalized_report_lines, enrich_hours_batch
from ..models.hr import (
    PAY_TYPES, PAY_SCHEDULES, ADVANCE_TYPES, ADVANCE_STATUSES,
    PAYROLL_STATUSES, PAYSLIP_STATUSES, PAYMENT_METHODS,
    EmployeeProfileCreate, EmployeeProfileUpdate,
    AdvanceLoanCreate,
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
        {"org_id": user["org_id"]},
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
        "insurance_pct": data.insurance_pct,
        "insurance_amount": data.insurance_amount,
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
    
    # Enrich with recipient name (employee or external guest)
    for adv in advances:
        if adv.get("recipient_name"):
            adv["user_name"] = adv["recipient_name"]
        elif adv.get("user_id"):
            u = await db.users.find_one({"id": adv["user_id"]}, {"_id": 0, "name": 1, "email": 1})
            adv["user_name"] = u.get("name", u.get("email", "Unknown").split("@")[0]) if u else "Unknown"
        else:
            adv["user_name"] = adv.get("guest_name") or "—"
    
    return advances


@router.post("/advances", status_code=201)
async def create_advance(data: AdvanceLoanCreate, user: dict = Depends(require_m4)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    org = user["org_id"]
    is_loan = (data.type or "").lower() == "loan"

    # Resolve recipient: employee (user_id) or external guest (loan only)
    recipient_name = None
    if data.user_id:
        target = await db.users.find_one({"id": data.user_id, "org_id": org})
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        recipient_name = target.get("name") or " ".join(filter(None, [target.get("first_name"), target.get("last_name")])) or target.get("email") or "Служител"
    elif is_loan and data.guest_name:
        recipient_name = data.guest_name.strip()
    else:
        raise HTTPException(status_code=400, detail="Изберете служител (или външен човек за заем)")

    if not data.amount or data.amount <= 0:
        raise HTTPException(status_code=400, detail="Сумата трябва да е положителна")

    now = datetime.now(timezone.utc).isoformat()
    issued = data.issued_date or now[:10]
    type_label = "Заем" if is_loan else "Аванс"

    # Cash movement — money leaves Каса/Банка (the missing register entry)
    payment_id = None
    if data.account_id:
        account = await db.financial_accounts.find_one({"id": data.account_id, "org_id": org})
        if not account:
            raise HTTPException(status_code=404, detail="Сметката не е намерена")
        acc_type = (account.get("type") or "").lower()
        method = "Cash" if acc_type in ("cash", "каса") else "BankTransfer"
        payment_id = str(uuid.uuid4())
        await db.finance_payments.insert_one({
            "id": payment_id, "org_id": org, "direction": "Outflow", "amount": data.amount,
            "currency": data.currency, "date": issued, "method": method,
            "account_id": data.account_id, "counterparty_name": recipient_name,
            "reference": "", "note": f"{type_label} · {recipient_name}",
            "category": type_label,
            "user_id": data.user_id,
            "created_at": now, "updated_at": now,
        })

    advance = {
        "id": str(uuid.uuid4()),
        "org_id": org,
        "user_id": data.user_id,
        "guest_name": data.guest_name if not data.user_id else None,
        "recipient_name": recipient_name,
        "type": data.type,
        "amount": data.amount,
        "remaining_amount": data.amount,
        "currency": data.currency,
        "account_id": data.account_id,
        "project_id": data.project_id,
        "installment_amount": data.installment_amount,
        "installment_period": data.installment_period,
        "payment_id": payment_id,
        "issued_date": issued,
        "note": data.note,
        "status": "Open",
        "created_at": now,
        "updated_at": now,
    }
    await db.advances.insert_one(advance)

    await log_audit(org, user["id"], user["email"], "advance_created", "advance", advance["id"],
                    {"recipient": recipient_name, "type": data.type, "amount": data.amount})

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


@router.post("/advances/{advance_id}/repay")
async def repay_advance(advance_id: str, amount: float, account_id: str = None, user: dict = Depends(require_m4)):
    """Repay a loan with money: records a cash INFLOW and reduces the balance."""
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    org_id = user["org_id"]
    advance = await db.advances.find_one({"id": advance_id, "org_id": org_id})
    if not advance:
        raise HTTPException(status_code=404, detail="Advance not found")
    if advance.get("status") == "Closed":
        raise HTTPException(status_code=400, detail="Already closed")
    rem = round(advance.get("remaining_amount") or 0, 2)
    amt = round(amount, 2)
    if amt <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    if amt > rem:
        amt = rem
    now = datetime.now(timezone.utc).isoformat()
    new_remaining = round(rem - amt, 2)
    if new_remaining < 0:
        new_remaining = 0
    acc_id = account_id or advance.get("account_id")
    label = advance.get("recipient_name") or advance.get("guest_name") or "Заем"
    await db.finance_payments.insert_one({
        "id": str(uuid.uuid4()), "org_id": org_id, "direction": "Inflow",
        "amount": amt, "currency": advance.get("currency", "EUR"), "date": now[:10],
        "method": "Cash", "account_id": acc_id, "counterparty_name": label,
        "reference": "", "note": f"Връщане на заем · {label}", "category": "Връщане заем",
        "user_id": advance.get("user_id"),
        "created_at": now, "updated_at": now,
    })
    await db.advances.update_one({"id": advance_id, "org_id": org_id}, {
        "$set": {"remaining_amount": new_remaining,
                 "status": "Closed" if new_remaining <= 0 else "Open",
                 "updated_at": now},
        "$push": {"repayments": {"amount": amt, "date": now[:10], "account_id": acc_id, "at": now}},
    })
    return await db.advances.find_one({"id": advance_id}, {"_id": 0})


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
    
    payslips = await legacy_payslips(
        user["org_id"],
        employee_id=user_id or None,
        pay_run_id=payroll_run_id or None,
        limit=500,
    )
    
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
        # Period: from v3 pay_runs (via source_pay_run_id) or from payslip directly
        if not ps.get("period_start"):
            src_id = ps.get("source_pay_run_id") or ps.get("payroll_run_id")
            if src_id:
                run = await db.pay_runs.find_one({"id": src_id}, {"_id": 0, "period_start": 1, "period_end": 1})
                if run:
                    ps["period_start"] = run.get("period_start")
                    ps["period_end"] = run.get("period_end")
    
    return payslips


@router.get("/payslips/{payslip_id}")
async def get_payslip(payslip_id: str, user: dict = Depends(require_m4)):
    payslip = await legacy_payslip_one(user["org_id"], payslip_id)
    if not payslip:
        raise HTTPException(status_code=404, detail="Payslip not found")
    
    # Technicians can only view own
    if user["role"] == "Technician" and payslip["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Enrich
    u = await db.users.find_one({"id": payslip["user_id"]}, {"_id": 0, "name": 1, "email": 1})
    payslip["user_name"] = u.get("name", u.get("email", "Unknown").split("@")[0]) if u else "Unknown"
    payslip["user_email"] = u.get("email", "") if u else ""
    
    src_id = payslip.get("source_pay_run_id") or payslip.get("payroll_run_id")
    run = await db.pay_runs.find_one({"id": src_id}, {"_id": 0}) if src_id else None
    payslip["payroll_run"] = run
    
    return payslip




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
    
    # Recent payslips — from v3 (period already included by the adapter)
    payslips_raw = await legacy_payslips(org_id, employee_id=user_id, limit=5)
    
    payslips = []
    for ps in payslips_raw:
        src_id = ps.get("source_pay_run_id") or ps.get("payroll_run_id")
        run = await db.pay_runs.find_one({"id": src_id}, {"_id": 0, "period_start": 1, "period_end": 1}) if src_id else None
        ps["period_start"] = run.get("period_start") if run else None
        ps["period_end"] = run.get("period_end") if run else None
        ps["gross_pay"] = ps.get("base_amount", 0)
        ps.pop("payroll_run_id", None)
        ps.pop("source_pay_run_id", None)
        ps.pop("base_amount", None)
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
    
    # ─────────────────────────────────────────────────────────────
    # P1-0.2: Unified reports via normalizer (replaces 2 separate find()s).
    # Normalizer reads both NEW (worker_id+date) and OLD (employee_id+report_date+day_entries[])
    # schemas of employee_daily_reports and returns a flat unified line list.
    # enrich_hours_batch computes per-day running total → correct overtime split.
    # ─────────────────────────────────────────────────────────────
    # Calculate inclusive end-of-month date string for normalizer (which uses $lte, not $lt).
    import calendar as _cal
    last_day_of_month = _cal.monthrange(y, m)[1]
    date_to_inclusive = f"{y}-{m:02d}-{last_day_of_month:02d}"

    raw_lines = await fetch_normalized_report_lines(
        org_id=org_id,
        date_from=date_from,
        date_to=date_to_inclusive,
        worker_id=user_id,
    )
    enrich_hours_batch(raw_lines)

    # Build project_code map once (avoid N+1 queries during day building).
    pids = {ln.get("project_id") for ln in raw_lines if ln.get("project_id")}
    proj_code_map = {}
    if pids:
        projs = await db.projects.find(
            {"id": {"$in": list(pids)}}, {"_id": 0, "id": 1, "code": 1}
        ).to_list(200)
        proj_code_map = {p["id"]: p.get("code", "") for p in projs}

    # Build calendar entries by day
    days = {}

    # Step A: attendance entries → days[d].attendance
    for att in attendance:
        d = att["date"]
        if d not in days:
            days[d] = {"date": d, "attendance": None, "work_reports": [], "daily_report": None, "total_hours": 0, "reports": [], "normal_hours": 0, "overtime_hours": 0, "report_count": 0}
        days[d]["attendance"] = {"status": att["status"], "project_code": att.get("project_code", "")}

    # Step B: unified reports → days[d].reports[] + legacy work_reports[] + total_hours
    for ln in raw_lines:
        d = ln.get("date", "")
        if not d:
            continue
        if d not in days:
            days[d] = {"date": d, "attendance": None, "work_reports": [], "daily_report": None, "total_hours": 0, "reports": [], "normal_hours": 0, "overtime_hours": 0, "report_count": 0}
        proj_code = proj_code_map.get(ln.get("project_id", ""), "")
        ln_hours = float(ln.get("hours") or 0)
        ln_normal = float(ln.get("normal_hours") or 0)
        ln_overtime = float(ln.get("overtime_hours") or 0)
        # New unified per-report detail
        days[d]["reports"].append({
            "report_id": ln.get("id", ""),
            "project_id": ln.get("project_id", ""),
            "project_code": proj_code,
            "hours": ln_hours,
            "normal_hours": ln_normal,
            "overtime_hours": ln_overtime,
            "smr_type": ln.get("smr_type", ""),
            "status": ln.get("status", ""),
            "payroll_status": ln.get("payroll_status", "none"),
        })
        # Legacy compat: keep work_reports[] (project_code + hours) for old frontend
        days[d]["work_reports"].append({"project_code": proj_code, "hours": ln_hours})
        # Per-day aggregates from batch enrichment
        days[d]["total_hours"] += ln_hours
        days[d]["normal_hours"] += ln_normal
        days[d]["overtime_hours"] += ln_overtime
        days[d]["report_count"] += 1

    # Round per-day aggregates
    for d_obj in days.values():
        d_obj["total_hours"] = round(d_obj["total_hours"], 1)
        d_obj["normal_hours"] = round(d_obj["normal_hours"], 1)
        d_obj["overtime_hours"] = round(d_obj["overtime_hours"], 1)

    # Step C: OLD-schema read for day_status ONLY (read-only fallback).
    # IMPORTANT: status (APPROVED/DRAFT/REJECTED) ≠ day_status (WORKING/LEAVE/SICK/ABSENT_UNEXCUSED).
    # Normalizer flattens OLD entries into report lines (one per day_entry) but doesn't
    # carry day_status (it's a day-level field, not entry-level). We read it here purely
    # to populate days[d].daily_report.day_status — used by frontend for Leave/Sick badges.
    old_day_meta = await db.employee_daily_reports.find(
        {"org_id": org_id, "employee_id": user_id, "report_date": {"$gte": date_from, "$lt": date_to}},
        {"_id": 0, "report_date": 1, "day_status": 1, "approval_status": 1, "total_hours": 1, "day_entries": 1}
    ).to_list(31)

    for dr in old_day_meta:
        d = dr.get("report_date", "")
        if not d:
            continue
        if d not in days:
            days[d] = {"date": d, "attendance": None, "work_reports": [], "daily_report": None, "total_hours": 0, "reports": [], "normal_hours": 0, "overtime_hours": 0, "report_count": 0}
        # Build project codes from day_entries for daily_report payload (legacy field).
        proj_codes = []
        for entry in dr.get("day_entries", []):
            pid = entry.get("project_id")
            if pid:
                code = proj_code_map.get(pid, "")
                if not code:
                    p = await db.projects.find_one({"id": pid}, {"_id": 0, "code": 1})
                    code = p["code"] if p else ""
                if code:
                    proj_codes.append(code)
        days[d]["daily_report"] = {
            "day_status": dr.get("day_status"),
            "approval_status": dr.get("approval_status"),
            "hours": dr.get("total_hours", 0),
            "project_codes": list(set(proj_codes)),
        }
        # Set attendance from daily report's day_status if no attendance_entries record exists.
        # This handles Leave/Sick/Absent which come from day_status, not from report status.
        day_st = dr.get("day_status")
        if not days[d]["attendance"]:
            if day_st == "WORKING":
                days[d]["attendance"] = {"status": "Present", "project_code": ", ".join(set(proj_codes))}
            elif day_st == "LEAVE":
                days[d]["attendance"] = {"status": "Leave", "project_code": ""}
            elif day_st == "SICK":
                days[d]["attendance"] = {"status": "Sick", "project_code": ""}
            elif day_st == "ABSENT_UNEXCUSED":
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
