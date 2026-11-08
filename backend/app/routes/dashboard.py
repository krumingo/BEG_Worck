"""
Routes - Dashboard Activity & Finance Details
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List
from datetime import datetime, timezone, timedelta
from calendar import monthrange
import re

from app.db import db
from app.tenancy.data_access import TenantData
from app.services.paid_labor import paid_labor_v3
from app.deps.auth import get_current_user
from app.deps.modules import require_m5

router = APIRouter(tags=["Dashboard"])


def _tenant(user: dict) -> TenantData:
    """W0-03E-A1: the session user's tenant view — every record below is read through it."""
    return TenantData.for_user(db, user)


# ── Pending Payments ──────────────────────────────────────────────

@router.get("/dashboard/pending-payments")
async def get_pending_payments(user: dict = Depends(get_current_user)):
    org_id = user["org_id"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    invoices = await _tenant(user).invoices.find(
        {"org_id": org_id, "direction": {"$in": ["issued", "Issued"]}, "status": {"$in": ["Sent", "PartiallyPaid"]}},
        {"_id": 0, "id": 1, "invoice_no": 1, "counterparty_name": 1, "total": 1,
         "paid_amount": 1, "due_date": 1, "status": 1, "project_id": 1},
    ).to_list(500)

    unpaid = []
    total_unpaid = 0
    total_overdue = 0
    for inv in invoices:
        remaining = round((inv.get("total", 0) or 0) - (inv.get("paid_amount", 0) or 0), 2)
        if remaining <= 0:
            continue
        is_overdue = (inv.get("due_date") or "9999") < today
        unpaid.append({
            "id": inv["id"],
            "invoice_no": inv.get("invoice_no", ""),
            "counterparty": inv.get("counterparty_name", ""),
            "total": inv.get("total", 0),
            "remaining": remaining,
            "due_date": inv.get("due_date", ""),
            "is_overdue": is_overdue,
        })
        total_unpaid += remaining
        if is_overdue:
            total_overdue += remaining

    unpaid.sort(key=lambda x: (0 if x["is_overdue"] else 1, x.get("due_date", "")))

    return {
        "count": len(unpaid),
        "total_unpaid": round(total_unpaid, 2),
        "total_overdue": round(total_overdue, 2),
        "items": unpaid[:20],
    }



# ── Personnel Today ────────────────────────────────────────────────

@router.get("/dashboard/personnel-today")
async def get_personnel_today(user: dict = Depends(get_current_user)):
    """
    Read-only dashboard projection: today's personnel status.
    Sources: users, employee_profiles, worker_calendar, site_daily_rosters, employee_daily_reports
    """
    tenant = _tenant(user)
    org_id = user["org_id"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 1) All active employees (exclude test users)
    employees = await _tenant(user).users.find(
        {"org_id": org_id, "is_active": True},
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "email": 1, "role": 1, "avatar_url": 1},
    ).to_list(200)
    emp_ids = [e["id"] for e in employees]
    # Filter out obvious test accounts
    employees = [e for e in employees if not (e.get("email", "").startswith("test_") or e.get("email", "").startswith("fullflow_") or e.get("email", "").startswith("ui_fixed_"))]
    emp_ids = [e["id"] for e in employees]

    # 2) Profiles (position)
    profiles = await tenant.employee_profiles.find(
        {"org_id": org_id, "user_id": {"$in": emp_ids}},
        {"_id": 0, "user_id": 1, "position": 1},
    ).to_list(200)
    profile_map = {p["user_id"]: p for p in profiles}

    # 3) Worker calendar entries for today (source of approved statuses)
    calendar = await tenant.worker_calendar.find(
        {"org_id": org_id, "date": today, "worker_id": {"$in": emp_ids}},
        {"_id": 0, "worker_id": 1, "status": 1, "site_id": 1, "hours": 1, "notes": 1},
    ).to_list(200)
    cal_map = {c["worker_id"]: c for c in calendar}

    # 4) Roster presence today (across all projects)
    rosters = await tenant.site_daily_rosters.find(
        {"org_id": org_id, "date": today},
        {"_id": 0, "project_id": 1, "workers": 1},
    ).to_list(100)
    # Build worker_id -> project_id map
    roster_map = {}  # worker_id -> project_id
    for r in rosters:
        for w in r.get("workers", []):
            wid = w.get("worker_id")
            if wid:
                roster_map[wid] = r["project_id"]

    # 5) Draft/submitted/approved reports today
    reports = await tenant.employee_daily_reports.find(
        {"org_id": org_id, "date": today, "worker_id": {"$in": emp_ids}},
        {"_id": 0, "worker_id": 1, "status": 1, "approval_status": 1, "hours": 1, "project_id": 1},
    ).to_list(500)
    # Group by worker: aggregate hours and pick best status
    report_map = {}  # worker_id -> {has_report, hours, status, project_id}
    for rpt in reports:
        wid = rpt.get("worker_id")
        if not wid:
            continue
        status = rpt.get("status") or rpt.get("approval_status", "")
        hours = float(rpt.get("hours") or 0)
        if wid not in report_map:
            report_map[wid] = {"has_report": True, "hours": 0, "status": status, "project_id": rpt.get("project_id")}
        report_map[wid]["hours"] += hours

    # 6) Project names lookup
    all_project_ids = set(roster_map.values())
    for rm in report_map.values():
        if rm.get("project_id"):
            all_project_ids.add(rm["project_id"])
    for c in calendar:
        if c.get("site_id"):
            all_project_ids.add(c["site_id"])
    project_names = {}
    if all_project_ids:
        # W0-03E-A1: only the caller's own projects (was a bare-id read).
        projects = await _tenant(user).projects.get_many(all_project_ids, {"_id": 0, "id": 1, "name": 1, "code": 1})
        project_names = {pid: p.get("name") or p.get("code", "") for pid, p in projects.items()}

    # 7) Build personnel list
    personnel = []
    for emp in employees:
        uid = emp["id"]
        prof = profile_map.get(uid, {})
        cal = cal_map.get(uid)
        in_roster = uid in roster_map
        rpt = report_map.get(uid)

        # Determine status
        cal_status = (cal.get("status", "") if cal else "").lower()
        if cal_status in ("sick", "болен"):
            day_status = "sick"
        elif cal_status in ("leave", "отпуска", "vacation"):
            day_status = "leave"
        elif cal_status in ("absent_unexcused", "самоотлъчка", "absent"):
            day_status = "absent"
        elif in_roster or cal_status == "working":
            day_status = "working"
        elif rpt and rpt["has_report"]:
            day_status = "working"
        else:
            day_status = "unknown"

        # Determine site
        site_id = roster_map.get(uid) or (cal.get("site_id") if cal else None) or (rpt.get("project_id") if rpt else None)
        site_name = project_names.get(site_id, "") if site_id else ""

        has_report = bool(rpt and rpt["has_report"])
        total_hours = round(rpt["hours"], 1) if rpt else 0

        personnel.append({
            "id": uid,
            "first_name": emp.get("first_name", ""),
            "last_name": emp.get("last_name", ""),
            "avatar_url": emp.get("avatar_url"),
            "position": prof.get("position", ""),
            "role": emp.get("role", ""),
            "day_status": day_status,
            "site_id": site_id,
            "site_name": site_name,
            "has_report": has_report,
            "hours": total_hours,
        })

    # Sort: problems first (absent, working-no-report, unknown), then working, then leave/sick
    STATUS_ORDER = {"absent": 0, "unknown": 1, "working": 2, "sick": 3, "leave": 4}
    personnel.sort(key=lambda p: (
        STATUS_ORDER.get(p["day_status"], 5),
        0 if (p["day_status"] == "working" and not p["has_report"]) else 1,
        p["last_name"],
    ))

    # Counters
    total = len(personnel)
    working = sum(1 for p in personnel if p["day_status"] == "working")
    with_report = sum(1 for p in personnel if p["day_status"] == "working" and p["has_report"])
    no_report = sum(1 for p in personnel if p["day_status"] == "working" and not p["has_report"])
    sick = sum(1 for p in personnel if p["day_status"] == "sick")
    leave = sum(1 for p in personnel if p["day_status"] == "leave")
    absent = sum(1 for p in personnel if p["day_status"] == "absent")
    unknown = sum(1 for p in personnel if p["day_status"] == "unknown")

    return {
        "date": today,
        "counters": {
            "total": total,
            "working": working,
            "with_report": with_report,
            "no_report": no_report,
            "sick": sick,
            "leave": leave,
            "absent": absent,
            "unknown": unknown,
        },
        "personnel": personnel,
    }



# ── Dashboard Activity ─────────────────────────────────────────────

@router.get("/dashboard/activity")
async def get_dashboard_activity(
    user: dict = Depends(require_m5),
    limit: int = Query(20, ge=1, le=100),
    page: int = Query(1, ge=1),
):
    """
    Get aggregated recent activity for dashboard.
    Combines audit logs, invoices, payments, and other important events.
    """
    org_id = user["org_id"]
    skip = (page - 1) * limit
    
    # Get audit logs
    query = {"org_id": org_id}
    total = await _tenant(user).audit_logs.count(query)
    
    logs = await _tenant(user).audit_logs.find(
        query,
        {"_id": 0}
    ).sort("timestamp", -1).skip(skip).limit(limit).to_list(limit)
    
    # Enrich with additional details
    activities = []
    for log in logs:
        activity = {
            "id": log.get("id"),
            "timestamp": log.get("timestamp"),
            "user_id": log.get("user_id"),
            "user_email": log.get("user_email"),
            "action": log.get("action"),
            "entity_type": log.get("entity_type"),
            "entity_id": log.get("entity_id"),
            "details": log.get("details", {}),
            "link": None,
        }
        
        # Generate link based on entity type
        entity_type = log.get("entity_type", "").lower()
        entity_id = log.get("entity_id")
        
        if entity_type == "invoice" and entity_id:
            activity["link"] = f"/invoices/{entity_id}"
        elif entity_type == "project" and entity_id:
            activity["link"] = f"/projects/{entity_id}"
        elif entity_type == "counterparty" and entity_id:
            activity["link"] = f"/data/counterparties?id={entity_id}"
        elif entity_type == "client" and entity_id:
            activity["link"] = f"/data/clients?id={entity_id}"
        elif entity_type == "warehouse" and entity_id:
            activity["link"] = f"/data/warehouses?id={entity_id}"
        elif entity_type == "user" and entity_id:
            activity["link"] = f"/users/{entity_id}"
        
        activities.append(activity)
    
    return {
        "items": activities,
        "total": total,
        "page": page,
        "page_size": limit,
        "total_pages": (total + limit - 1) // limit,
    }


# ── Finance Series (Rolling N Months) ──────────────────────────────

@router.get("/reports/company-finance-series")
async def get_finance_series(
    user: dict = Depends(require_m5),
    months: int = Query(3, ge=1, le=24),
):
    """
    Get monthly finance totals for the last N months.
    Used for rolling period charts on dashboard.
    """
    tenant = _tenant(user)
    org_id = user["org_id"]
    
    # Calculate date range
    today = datetime.now(timezone.utc)
    current_month = today.month
    current_year = today.year
    
    # Generate list of months to fetch
    months_to_fetch = []
    for i in range(months):
        m = current_month - i
        y = current_year
        while m <= 0:
            m += 12
            y -= 1
        months_to_fetch.append((y, m))
    
    # Reverse to get chronological order
    months_to_fetch.reverse()
    
    # Fetch data for each month
    results = []
    for year, month in months_to_fetch:
        _, days_in_month = monthrange(year, month)
        date_from = f"{year}-{month:02d}-01"
        date_to = f"{year}-{month:02d}-{days_in_month:02d}"
        
        # Income from issued invoices
        issued_invoices = await _tenant(user).invoices.find({
            "org_id": org_id,
            "direction": "Issued",
            "issue_date": {"$gte": date_from, "$lte": date_to}
        }, {"_id": 0, "total": 1, "subtotal": 1}).to_list(1000)
        income_invoices = sum((inv.get("subtotal") if inv.get("subtotal") is not None else inv.get("total", 0)) for inv in issued_invoices)
        
        # Income from cash
        cash_income = await tenant.cash_transactions.find({
            "org_id": org_id,
            "date": {"$gte": date_from, "$lte": date_to},
            "type": "income"
        }, {"_id": 0, "amount": 1}).to_list(1000)
        income_cash = sum(t.get("amount", 0) for t in cash_income)
        
        # Expenses from received invoices
        received_invoices = await _tenant(user).invoices.find({
            "org_id": org_id,
            "direction": "Received",
            "issue_date": {"$gte": date_from, "$lte": date_to}
        }, {"_id": 0, "total": 1, "subtotal": 1}).to_list(1000)
        expenses_invoices = sum((inv.get("subtotal") if inv.get("subtotal") is not None else inv.get("total", 0)) for inv in received_invoices)
        
        # Expenses from cash
        cash_expense = await tenant.cash_transactions.find({
            "org_id": org_id,
            "date": {"$gte": date_from, "$lte": date_to},
            "type": "expense"
        }, {"_id": 0, "amount": 1}).to_list(1000)
        expenses_cash = sum(t.get("amount", 0) for t in cash_expense)
        
        # Overhead
        overhead = await tenant.overhead_transactions.find({
            "org_id": org_id,
            "date": {"$gte": date_from, "$lte": date_to}
        }, {"_id": 0, "amount": 1}).to_list(1000)
        expenses_overhead = sum(t.get("amount", 0) for t in overhead)
        
        # Payroll
        payroll = await paid_labor_v3(org_id, date_from, date_to)
        expenses_payroll = sum(p.get("net_salary", 0) for p in payroll)
        
        # Bonus
        bonus = await tenant.bonus_payments.find({
            "org_id": org_id,
            "date": {"$gte": date_from, "$lte": date_to}
        }, {"_id": 0, "amount": 1}).to_list(1000)
        expenses_bonus = sum(b.get("amount", 0) for b in bonus)
        
        # Calculate totals
        income_total = income_invoices + income_cash
        expenses_total = expenses_invoices + expenses_cash + expenses_overhead + expenses_payroll + expenses_bonus
        net = income_total - expenses_total
        
        month_names = ["Яну", "Фев", "Мар", "Апр", "Май", "Юни", "Юли", "Авг", "Сеп", "Окт", "Ное", "Дек"]
        
        results.append({
            "year": year,
            "month": month,
            "month_name": month_names[month - 1],
            "income_total": round(income_total, 2),
            "expenses_total": round(expenses_total, 2),
            "net": round(net, 2),
            "breakdown": {
                "income_invoices": round(income_invoices, 2),
                "income_cash": round(income_cash, 2),
                "expenses_invoices": round(expenses_invoices, 2),
                "expenses_cash": round(expenses_cash, 2),
                "expenses_overhead": round(expenses_overhead, 2),
                "expenses_payroll": round(expenses_payroll, 2),
                "expenses_bonus": round(expenses_bonus, 2),
            }
        })
    
    # Calculate overall totals
    total_income = sum(r["income_total"] for r in results)
    total_expenses = sum(r["expenses_total"] for r in results)
    total_net = total_income - total_expenses
    
    return {
        "months": results,
        "period_months": months,
        "totals": {
            "income": round(total_income, 2),
            "expenses": round(total_expenses, 2),
            "net": round(total_net, 2),
        }
    }


# ── Finance Details Endpoints ──────────────────────────────────────

def parse_date_preset(preset: str) -> tuple:
    """Convert date preset to date_from, date_to"""
    today = datetime.now(timezone.utc)
    
    if preset == "this_month":
        date_from = today.replace(day=1).strftime("%Y-%m-%d")
        _, last_day = monthrange(today.year, today.month)
        date_to = today.replace(day=last_day).strftime("%Y-%m-%d")
    elif preset == "last_month":
        first_of_month = today.replace(day=1)
        last_month = first_of_month - timedelta(days=1)
        date_from = last_month.replace(day=1).strftime("%Y-%m-%d")
        date_to = last_month.strftime("%Y-%m-%d")
    elif preset == "last_3_months":
        date_to = today.strftime("%Y-%m-%d")
        date_from = (today - timedelta(days=90)).strftime("%Y-%m-%d")
    elif preset == "last_6_months":
        date_to = today.strftime("%Y-%m-%d")
        date_from = (today - timedelta(days=180)).strftime("%Y-%m-%d")
    elif preset == "last_12_months":
        date_to = today.strftime("%Y-%m-%d")
        date_from = (today - timedelta(days=365)).strftime("%Y-%m-%d")
    elif preset == "this_year":
        date_from = f"{today.year}-01-01"
        date_to = today.strftime("%Y-%m-%d")
    else:
        date_from = None
        date_to = None
    
    return date_from, date_to


@router.get("/reports/finance-details/summary")
async def get_finance_details_summary(
    user: dict = Depends(require_m5),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    preset: Optional[str] = None,
    project_id: Optional[str] = None,
    counterparty_id: Optional[str] = None,
    client_id: Optional[str] = None,
    warehouse_id: Optional[str] = None,
):
    """Get finance summary with KPIs for the selected filters."""
    org_id = user["org_id"]
    
    # Handle preset
    if preset and not (date_from and date_to):
        date_from, date_to = parse_date_preset(preset)
    
    if not date_from or not date_to:
        # Default to last 3 months
        today = datetime.now(timezone.utc)
        date_to = today.strftime("%Y-%m-%d")
        date_from = (today - timedelta(days=90)).strftime("%Y-%m-%d")
    
    # Build base query for invoices
    inv_query = {
        "org_id": org_id,
        "issue_date": {"$gte": date_from, "$lte": date_to}
    }
    
    if counterparty_id:
        inv_query["supplier_counterparty_id"] = counterparty_id
    if project_id:
        inv_query["allocations"] = {"$elemMatch": {"type": "project", "ref_id": project_id}}
    if warehouse_id:
        inv_query["allocations"] = {"$elemMatch": {"type": "warehouse", "ref_id": warehouse_id}}
    
    # Issued invoices (income)
    issued_query = {**inv_query, "direction": "Issued"}
    issued = await _tenant(user).invoices.find(issued_query, {"_id": 0, "total": 1, "subtotal": 1, "vat": 1}).to_list(10000)
    income_invoices = sum((i.get("subtotal") if i.get("subtotal") is not None else i.get("total", 0)) for i in issued)
    income_count = len(issued)
    
    # Received invoices (expenses)
    received_query = {**inv_query, "direction": "Received"}
    received = await _tenant(user).invoices.find(received_query, {"_id": 0, "total": 1, "subtotal": 1, "vat": 1}).to_list(10000)
    expenses_invoices = sum((i.get("subtotal") if i.get("subtotal") is not None else i.get("total", 0)) for i in received)
    expenses_invoice_count = len(received)
    
    # Cash transactions
    cash_query = {"org_id": org_id, "date": {"$gte": date_from, "$lte": date_to}}
    cash_txns = await _tenant(user).cash_transactions.find(cash_query, {"_id": 0, "type": 1, "amount": 1}).to_list(10000)
    income_cash = sum(t.get("amount", 0) for t in cash_txns if t.get("type") == "income")
    expenses_cash = sum(t.get("amount", 0) for t in cash_txns if t.get("type") == "expense")
    
    # Overhead
    overhead_query = {"org_id": org_id, "date": {"$gte": date_from, "$lte": date_to}}
    overhead = await _tenant(user).overhead_transactions.find(overhead_query, {"_id": 0, "amount": 1}).to_list(10000)
    expenses_overhead = sum(t.get("amount", 0) for t in overhead)
    
    # Payroll
    payroll = await paid_labor_v3(org_id, date_from, date_to)
    expenses_payroll = sum(p.get("net_salary", 0) for p in payroll)
    
    # Bonus
    bonus_query = {"org_id": org_id, "date": {"$gte": date_from, "$lte": date_to}}
    bonus = await _tenant(user).bonus_payments.find(bonus_query, {"_id": 0, "amount": 1}).to_list(10000)
    expenses_bonus = sum(b.get("amount", 0) for b in bonus)
    
    # Calculate totals
    total_income = income_invoices + income_cash
    total_expenses = expenses_invoices + expenses_cash + expenses_overhead + expenses_payroll + expenses_bonus
    net = total_income - total_expenses
    
    # Calculate weeks in period for average
    start = datetime.strptime(date_from, "%Y-%m-%d")
    end = datetime.strptime(date_to, "%Y-%m-%d")
    weeks_in_period = max(1, (end - start).days / 7)
    
    avg_weekly_income = total_income / weeks_in_period
    avg_weekly_expenses = total_expenses / weeks_in_period
    
    # Calculate shares
    total_exp_for_share = total_expenses if total_expenses > 0 else 1
    
    return {
        "period": {"date_from": date_from, "date_to": date_to},
        "totals": {
            "income": round(total_income, 2),
            "expenses": round(total_expenses, 2),
            "net": round(net, 2),
        },
        "breakdown": {
            "income_invoices": round(income_invoices, 2),
            "income_cash": round(income_cash, 2),
            "expenses_invoices": round(expenses_invoices, 2),
            "expenses_cash": round(expenses_cash, 2),
            "expenses_overhead": round(expenses_overhead, 2),
            "expenses_payroll": round(expenses_payroll, 2),
            "expenses_bonus": round(expenses_bonus, 2),
        },
        "counts": {
            "income_invoice_count": income_count,
            "expenses_invoice_count": expenses_invoice_count,
            "cash_count": len(cash_txns),
            "overhead_count": len(overhead),
            "payroll_count": len(payroll),
            "bonus_count": len(bonus),
        },
        "kpis": {
            "avg_weekly_income": round(avg_weekly_income, 2),
            "avg_weekly_expenses": round(avg_weekly_expenses, 2),
            "weeks_in_period": round(weeks_in_period, 1),
            "invoice_share": round((expenses_invoices / total_exp_for_share) * 100, 1),
            "cash_share": round((expenses_cash / total_exp_for_share) * 100, 1),
            "overhead_share": round((expenses_overhead / total_exp_for_share) * 100, 1),
            "payroll_share": round((expenses_payroll / total_exp_for_share) * 100, 1),
            "bonus_share": round((expenses_bonus / total_exp_for_share) * 100, 1),
        }
    }


@router.get("/reports/finance-details/by-counterparty")
async def get_finance_by_counterparty(
    user: dict = Depends(require_m5),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    preset: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("total"),
    sort_dir: str = Query("desc"),
):
    """Get finance breakdown by counterparty."""
    org_id = user["org_id"]
    
    if preset and not (date_from and date_to):
        date_from, date_to = parse_date_preset(preset)
    
    if not date_from or not date_to:
        today = datetime.now(timezone.utc)
        date_to = today.strftime("%Y-%m-%d")
        date_from = (today - timedelta(days=90)).strftime("%Y-%m-%d")
    
    # Aggregate invoices by counterparty
    pipeline = [
        {"$match": {
            "org_id": org_id,
            "issue_date": {"$gte": date_from, "$lte": date_to},
            "supplier_counterparty_id": {"$exists": True, "$ne": None}
        }},
        {"$group": {
            "_id": "$supplier_counterparty_id",
            "total_income": {"$sum": {"$cond": [{"$eq": ["$direction", "Issued"]}, "$total", 0]}},
            "total_expenses": {"$sum": {"$cond": [{"$eq": ["$direction", "Received"]}, "$total", 0]}},
            "invoice_count": {"$sum": 1},
        }},
        {"$project": {
            "_id": 0,
            "counterparty_id": "$_id",
            "total_income": 1,
            "total_expenses": 1,
            "total": {"$add": ["$total_income", "$total_expenses"]},
            "invoice_count": 1,
        }},
    ]
    
    # Sort
    sort_field = sort_by if sort_by in ["total", "total_income", "total_expenses", "invoice_count"] else "total"
    sort_direction = -1 if sort_dir == "desc" else 1
    pipeline.append({"$sort": {sort_field: sort_direction}})
    
    # Count total
    count_pipeline = pipeline.copy()
    count_pipeline.append({"$count": "total"})
    count_result = await _tenant(user).invoices.aggregate(count_pipeline).to_list(1)
    total = count_result[0]["total"] if count_result else 0
    
    # Paginate
    pipeline.append({"$skip": (page - 1) * page_size})
    pipeline.append({"$limit": page_size})
    
    results = await _tenant(user).invoices.aggregate(pipeline).to_list(page_size)
    
    # Enrich with counterparty names
    cp_ids = [r["counterparty_id"] for r in results]
    counterparties = await _tenant(user).counterparties.find(
        {"id": {"$in": cp_ids}, "org_id": org_id},  # W0-03E-R1: names of this org only
        {"_id": 0, "id": 1, "name": 1, "type": 1}
    ).to_list(len(cp_ids))
    cp_map = {cp["id"]: cp for cp in counterparties}
    
    for r in results:
        cp = cp_map.get(r["counterparty_id"], {})
        r["counterparty_name"] = cp.get("name", "Unknown")
        r["counterparty_type"] = cp.get("type", "")
    
    return {
        "items": results,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "period": {"date_from": date_from, "date_to": date_to},
    }


@router.get("/reports/finance-details/by-project")
async def get_finance_by_project(
    user: dict = Depends(require_m5),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    preset: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """Get finance breakdown by project (from invoice allocations)."""
    org_id = user["org_id"]
    
    if preset and not (date_from and date_to):
        date_from, date_to = parse_date_preset(preset)
    
    if not date_from or not date_to:
        today = datetime.now(timezone.utc)
        date_to = today.strftime("%Y-%m-%d")
        date_from = (today - timedelta(days=90)).strftime("%Y-%m-%d")
    
    # WH-FIX-01 (FG-154): each project gets ITS share of an invoice — the
    # per-line allocation (invoice line ``allocations[]``, or the deprecated
    # single allocation for the whole line; the same reading as Path B /
    # ``canonical_material_cost.effective_allocations``): share of the line =
    # allocated qty / line qty × the line's amount incl. VAT. Before, the
    # WHOLE invoice total was added to every allocated project.
    results, unsplit = await _finance_by_project_rows(
        _tenant(user), org_id, date_from, date_to)
    total = len(results)
    results = results[(page - 1) * page_size:(page - 1) * page_size + page_size]

    # Enrich with project names
    project_ids = [r["project_id"] for r in results]
    projects = await _tenant(user).projects.find(
        {"id": {"$in": project_ids}, "org_id": org_id},  # W0-03E-R1: this org only
        {"_id": 0, "id": 1, "code": 1, "name": 1}
    ).to_list(len(project_ids))
    proj_map = {p["id"]: p for p in projects}
    
    for r in results:
        proj = proj_map.get(r["project_id"], {})
        r["project_code"] = proj.get("code", "")
        r["project_name"] = proj.get("name", "Unknown")
    # the bucket's header destinations get this tenant's names only
    dest_ids = sorted({d["ref_id"] for u in unsplit for d in u["header_destinations"]
                       if d["type"] == "project" and d["ref_id"]})
    if dest_ids:
        dest_map = {p["id"]: p async for p in _tenant(user).projects.find(
            {"id": {"$in": dest_ids}, "org_id": org_id}, {"_id": 0, "id": 1, "code": 1, "name": 1})}
        for u in unsplit:
            for d in u["header_destinations"]:
                if d["type"] == "project":
                    proj = dest_map.get(d["ref_id"], {})
                    d["project_code"] = proj.get("code", "")
                    d["project_name"] = proj.get("name", "Unknown")
    
    return {
        "items": results,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "period": {"date_from": date_from, "date_to": date_to},
        # A4 #8 — „фактури за разпределяне": every invoice of the period that
        # is not finally allocated by lines (counted on no project, never dropped).
        "to_allocate": unsplit,
    }


def _f_or_none(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def _line_amount(line: dict) -> float:
    """A line's amount incl. VAT (stored total, else ex VAT + VAT)."""
    if line.get("line_total_inc_vat") is not None:
        return float(line.get("line_total_inc_vat") or 0)
    ex = line.get("line_total_ex_vat")
    if ex is None:
        ex = float(line.get("qty") or 0) * float(line.get("unit_price") or 0)
    ex = float(ex or 0)
    vat = line.get("vat_amount")
    if vat is None:
        vat = ex * float(line.get("vat_percent") or 0) / 100
    return ex + float(vat or 0)


async def _finance_by_project_rows(tenant, org_id: str, date_from: str, date_to: str):
    """WH-FIX-01 (FG-154) — {project: expenses / income / invoices} from the
    per-line allocations of the period's invoices."""
    from app.services.canonical_material_cost import effective_allocations
    invoices = {}
    async for inv in tenant.invoices.find(
            {"org_id": org_id, "issue_date": {"$gte": date_from, "$lte": date_to}},
            {"_id": 0, "id": 1, "direction": 1, "total": 1, "allocations": 1,
             "invoice_no": 1, "status": 1, "project_id": 1, "lines": 1, "vat_percent": 1}):
        invoices[inv["id"]] = inv
    agg: dict = {}
    unsplit = []

    def _add(pid, inv, amount):
        row = agg.setdefault(pid, {"project_id": pid, "total_expenses": 0.0,
                                   "total_income": 0.0, "_invoices": set()})
        if inv.get("direction") == "Received":
            row["total_expenses"] += amount
        elif inv.get("direction") == "Issued":
            row["total_income"] += amount
        row["_invoices"].add(inv["id"])

    # A4 / Р45 (oracle Q002): the allocation unit is the invoice LINE. Only
    # line allocations reach a project (FG-154: allocated qty / line qty × the
    # line amount). No provisional split by header / percentage (A4 #12). An
    # invoice that is not finally allocated by lines is NEVER dropped: it is
    # listed in `to_allocate` („фактури за разпределяне", A4 #8).
    from app.services.invoice_allocation import (
        ALLOCATED, header_destinations, invoice_final_state,
    )
    with_line_docs = set()          # invoices with a line-level PROJECT allocation
    seen_line_docs = set()          # invoices with invoice_lines documents
    embedded_projects = set()       # invoices with an embedded line project allocation
    if invoices:
        async for line in tenant.invoice_lines.find(
                {"org_id": org_id, "invoice_id": {"$in": list(invoices)}},
                {"_id": 0, "invoice_id": 1, "qty": 1, "unit_price": 1, "vat_percent": 1,
                 "vat_amount": 1, "line_total_ex_vat": 1, "line_total_inc_vat": 1,
                 "allocations": 1, "allocation_type": 1, "allocation_ref_id": 1}):
            inv = invoices.get(line.get("invoice_id"))
            if inv is None:
                continue
            if any(a["type"] == "project" and a["ref_id"] for a in effective_allocations(line)):
                with_line_docs.add(inv["id"])
            seen_line_docs.add(inv["id"])
            amount = _line_amount(line)
            qty = line.get("qty")
            qty = float(qty) if qty not in (None, "") else None
            for a in effective_allocations(line):
                if a["type"] != "project" or not a["ref_id"]:
                    continue
                if a["qty"] is not None and qty and qty > 0:
                    share = min(a["qty"], qty) / qty
                else:
                    share = 1.0
                _add(a["ref_id"], inv, amount * share)
    # FG-200: an invoice of the finance UI keeps its lines EMBEDDED — the same
    # per-line rule on them (a line's `allocations[]`, or its `project_id`).
    from app.services.invoice_allocation import embedded_as_line
    for inv in invoices.values():
        if inv["id"] in seen_line_docs:
            continue
        vat = float(inv.get("vat_percent") or 0)
        for el in inv.get("lines") or []:
            if not isinstance(el, dict):
                continue
            line = embedded_as_line(el)
            ex = float(el.get("line_total") if el.get("line_total") is not None
                       else float(el.get("qty") or 0) * float(el.get("unit_price") or 0))
            amount = ex * (1 + vat / 100)
            qty = _f_or_none(line.get("qty"))
            for a in effective_allocations(line):
                if a["type"] != "project" or not a["ref_id"]:
                    continue
                embedded_projects.add(inv["id"])
                share = (min(a["qty"], qty) / qty) if (a["qty"] is not None and qty) else 1.0
                _add(a["ref_id"], inv, amount * share)
    from app.services.invoice_allocation import under_r45
    # FG-215: an INCOME (Issued) invoice keeps main's behaviour — with no line
    # carrying a project allocation, its header allocation is counted (every
    # header project gets the total, as the pipeline of main did).
    line_projects = set()
    for inv in invoices.values():
        if inv["id"] in with_line_docs or inv["id"] in embedded_projects:
            line_projects.add(inv["id"])
    for inv in invoices.values():
        if under_r45(inv) or inv["id"] in line_projects:
            continue
        for a in inv.get("allocations") or []:
            if isinstance(a, dict) and a.get("type") == "project" and a.get("ref_id"):
                _add(a["ref_id"], inv, float(inv.get("total") or 0))
    for inv in invoices.values():
        if not under_r45(inv):
            continue
        state = await invoice_final_state(tenant, inv)
        if state["status"] != ALLOCATED:
            unsplit.append({"invoice_id": inv["id"], "invoice_no": inv.get("invoice_no"),
                            "direction": inv.get("direction"), "total": inv.get("total"),
                            "allocation_status": state["status"],
                            "header_destinations": [
                                {"type": d.get("type"), "ref_id": d.get("ref_id") or d.get("refId")}
                                for d in header_destinations(inv)],
                            "pending_lines": [{"line_id": p["line_id"],
                                               "unallocated_qty": p["unallocated_qty"]}
                                              for p in state["pending_lines"]]})
    results = []
    for row in agg.values():
        exp, inc = round(row["total_expenses"], 2), round(row["total_income"], 2)
        results.append({"project_id": row["project_id"], "total_expenses": exp,
                        "total_income": inc, "total": round(exp + inc, 2),
                        "invoice_count": len(row["_invoices"])})
    results.sort(key=lambda r: (-r["total"], r["project_id"]))
    return results, unsplit


@router.get("/reports/finance-details/transactions")
async def get_finance_transactions(
    user: dict = Depends(require_m5),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    preset: Optional[str] = None,
    transaction_type: Optional[str] = None,  # invoice, cash, overhead, payroll, bonus
    direction: Optional[str] = None,  # income, expense
    counterparty_id: Optional[str] = None,
    project_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("date"),
    sort_dir: str = Query("desc"),
):
    """Get list of all transactions with filters."""
    tenant = _tenant(user)
    org_id = user["org_id"]
    
    if preset and not (date_from and date_to):
        date_from, date_to = parse_date_preset(preset)
    
    if not date_from or not date_to:
        today = datetime.now(timezone.utc)
        date_to = today.strftime("%Y-%m-%d")
        date_from = (today - timedelta(days=90)).strftime("%Y-%m-%d")
    
    transactions = []
    
    # Invoices
    if not transaction_type or transaction_type == "invoice":
        inv_query = {
            "org_id": org_id,
            "issue_date": {"$gte": date_from, "$lte": date_to}
        }
        if counterparty_id:
            inv_query["supplier_counterparty_id"] = counterparty_id
        if direction == "income":
            inv_query["direction"] = "Issued"
        elif direction == "expense":
            inv_query["direction"] = "Received"
        
        invoices = await _tenant(user).invoices.find(inv_query, {"_id": 0, "id": 1, "invoice_number": 1, "issue_date": 1, "direction": 1, "total": 1, "supplier_counterparty_id": 1}).to_list(1000)
        
        for inv in invoices:
            transactions.append({
                "id": inv["id"],
                "type": "invoice",
                "date": inv.get("issue_date"),
                "direction": "income" if inv.get("direction") == "Issued" else "expense",
                "amount": inv.get("total", 0),
                "description": f"Фактура {inv.get('invoice_number', '')}",
                "counterparty_id": inv.get("supplier_counterparty_id"),
                "link": f"/invoices/{inv['id']}",
            })
    
    # Cash transactions
    if not transaction_type or transaction_type == "cash":
        cash_query = {"org_id": org_id, "date": {"$gte": date_from, "$lte": date_to}}
        if direction:
            cash_query["type"] = direction
        
        cash = await _tenant(user).cash_transactions.find(cash_query, {"_id": 0}).to_list(1000)
        for c in cash:
            transactions.append({
                "id": c.get("id"),
                "type": "cash",
                "date": c.get("date"),
                "direction": c.get("type", "expense"),
                "amount": c.get("amount", 0),
                "description": c.get("description") or c.get("category", "Каса"),
                "counterparty_id": None,
                "link": None,
            })
    
    # Overhead
    if not transaction_type or transaction_type == "overhead":
        if not direction or direction == "expense":
            overhead = await tenant.overhead_transactions.find({
                "org_id": org_id,
                "date": {"$gte": date_from, "$lte": date_to}
            }, {"_id": 0}).to_list(1000)
            for o in overhead:
                transactions.append({
                    "id": o.get("id"),
                    "type": "overhead",
                    "date": o.get("date"),
                    "direction": "expense",
                    "amount": o.get("amount", 0),
                    "description": o.get("category", "Режийни"),
                    "counterparty_id": None,
                    "link": None,
                })
    
    # Payroll
    if not transaction_type or transaction_type == "payroll":
        if not direction or direction == "expense":
            payroll = await paid_labor_v3(org_id, date_from, date_to)
            for p in payroll:
                transactions.append({
                    "id": p.get("id"),
                    "type": "payroll",
                    "date": p.get("payment_date"),
                    "direction": "expense",
                    "amount": p.get("net_salary", 0),
                    "description": "Заплата",
                    "counterparty_id": None,
                    "link": None,
                })
    
    # Bonus
    if not transaction_type or transaction_type == "bonus":
        if not direction or direction == "expense":
            bonus = await tenant.bonus_payments.find({
                "org_id": org_id,
                "date": {"$gte": date_from, "$lte": date_to}
            }, {"_id": 0}).to_list(1000)
            for b in bonus:
                transactions.append({
                    "id": b.get("id"),
                    "type": "bonus",
                    "date": b.get("date"),
                    "direction": "expense",
                    "amount": b.get("amount", 0),
                    "description": b.get("description", "Бонус"),
                    "counterparty_id": None,
                    "link": None,
                })
    
    # Sort
    reverse = sort_dir == "desc"
    if sort_by == "date":
        transactions.sort(key=lambda x: x.get("date", ""), reverse=reverse)
    elif sort_by == "amount":
        transactions.sort(key=lambda x: x.get("amount", 0), reverse=reverse)
    elif sort_by == "type":
        transactions.sort(key=lambda x: x.get("type", ""), reverse=reverse)
    
    total = len(transactions)
    
    # Paginate
    start = (page - 1) * page_size
    end = start + page_size
    paginated = transactions[start:end]
    
    return {
        "items": paginated,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "period": {"date_from": date_from, "date_to": date_to},
    }


@router.get("/reports/finance-details/top-counterparties")
async def get_top_counterparties(
    user: dict = Depends(require_m5),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    preset: Optional[str] = None,
    limit: int = Query(10, ge=1, le=50),
    direction: str = Query("expense"),  # expense or income
):
    """Get top counterparties by spend or income."""
    org_id = user["org_id"]
    
    if preset and not (date_from and date_to):
        date_from, date_to = parse_date_preset(preset)
    
    if not date_from or not date_to:
        today = datetime.now(timezone.utc)
        date_to = today.strftime("%Y-%m-%d")
        date_from = (today - timedelta(days=90)).strftime("%Y-%m-%d")
    
    inv_direction = "Received" if direction == "expense" else "Issued"
    
    pipeline = [
        {"$match": {
            "org_id": org_id,
            "issue_date": {"$gte": date_from, "$lte": date_to},
            "direction": inv_direction,
            "supplier_counterparty_id": {"$exists": True, "$ne": None}
        }},
        {"$group": {
            "_id": "$supplier_counterparty_id",
            "total": {"$sum": "$total"},
            "count": {"$sum": 1},
        }},
        {"$sort": {"total": -1}},
        {"$limit": limit},
    ]
    
    results = await _tenant(user).invoices.aggregate(pipeline).to_list(limit)
    
    # Enrich with names
    cp_ids = [r["_id"] for r in results]
    counterparties = await _tenant(user).counterparties.find(
        {"id": {"$in": cp_ids}, "org_id": org_id},  # W0-03E-R1: names of this org only
        {"_id": 0, "id": 1, "name": 1}
    ).to_list(len(cp_ids))
    cp_map = {cp["id"]: cp["name"] for cp in counterparties}
    
    enriched = []
    for r in results:
        enriched.append({
            "counterparty_id": r["_id"],
            "counterparty_name": cp_map.get(r["_id"], "Unknown"),
            "total": round(r["total"], 2),
            "invoice_count": r["count"],
        })
    
    return {"items": enriched, "direction": direction}
