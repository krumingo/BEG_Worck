"""
Routes — All Reports (Central read-only table).
Merges employee_daily_reports (both old & new style) + work_sessions
into a unified flat view for admin/office use.
"""
from fastapi import APIRouter, Depends, Query
from typing import Optional
from datetime import datetime, timezone, timedelta

from app.db import db
from app.deps.auth import get_current_user

router = APIRouter(tags=["All Reports"])

NORMAL_DAY = 8


@router.get("/all-reports")
async def get_all_reports(
    user: dict = Depends(get_current_user),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    worker_id: Optional[str] = None,
    project_id: Optional[str] = None,
    smr: Optional[str] = None,
    report_status: Optional[str] = None,
    only_overtime: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort_by: str = Query("date"),
    sort_dir: str = Query("desc"),
):
    org_id = user["org_id"]

    # Default: last 30 days
    if not date_from:
        date_from = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    if not date_to:
        date_to = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ── 1. Collect all flat rows ───────────────────────────────────
    rows = []

    # A) New-style reports (from technician portal) — flat with worker_id
    q_new = {"org_id": org_id, "worker_id": {"$exists": True}}
    q_new["$or"] = [
        {"date": {"$gte": date_from, "$lte": date_to}},
    ]
    if worker_id:
        q_new["worker_id"] = worker_id
    if project_id:
        q_new["project_id"] = project_id
    if smr:
        q_new["smr_type"] = {"$regex": smr, "$options": "i"}
    if report_status:
        upper = report_status.upper()
        q_new["status"] = {"$in": [report_status, upper, report_status.capitalize()]}

    new_docs = await db.employee_daily_reports.find(q_new, {"_id": 0}).to_list(2000)
    for d in new_docs:
        hours = float(d.get("hours") or 0)
        rows.append({
            "id": d["id"],
            "source": "tech_report",
            "date": d.get("date", ""),
            "worker_id": d.get("worker_id", ""),
            "worker_name": d.get("worker_name", ""),
            "project_id": d.get("project_id", ""),
            "smr_type": d.get("smr_type", ""),
            "hours": hours,
            "normal_hours": min(hours, NORMAL_DAY),
            "overtime_hours": max(0, hours - NORMAL_DAY),
            "notes": d.get("notes", ""),
            "report_status": (d.get("status") or "").upper(),
            "submitted_by": d.get("submitted_by"),
            "approved_by": d.get("approved_by"),
            "approved_at": d.get("approved_at"),
            "entered_by_admin": d.get("entered_by_admin", False),
            "entry_mode": d.get("entry_mode", ""),
            "created_at": d.get("created_at", ""),
            # Payroll fields (not yet implemented)
            "payroll_status": d.get("payroll_status", "none"),
            "slip_number": d.get("slip_number"),
            # Will be enriched below
            "hourly_rate": 0,
            "labor_value": 0,
            "site_name": "",
        })

    # B) Old-style reports (structured with day_entries) — expand to flat
    q_old = {"org_id": org_id, "employee_id": {"$exists": True}}
    if report_status:
        upper = report_status.upper()
        q_old["approval_status"] = {"$in": [report_status, upper, report_status.capitalize()]}

    old_docs = await db.employee_daily_reports.find(q_old, {"_id": 0}).to_list(2000)
    for d in old_docs:
        emp_id = d.get("employee_id", "")
        if worker_id and emp_id != worker_id:
            continue
        report_date = d.get("report_date", "")
        if report_date < date_from or report_date > date_to:
            continue
        for entry in d.get("day_entries", []):
            pid = entry.get("project_id", "")
            if project_id and pid != project_id:
                continue
            desc = entry.get("work_description", "")
            if smr and smr.lower() not in desc.lower():
                continue
            hours = float(entry.get("hours_worked") or 0)
            rows.append({
                "id": d["id"] + "_" + entry.get("id", ""),
                "source": "structured_report",
                "date": report_date,
                "worker_id": emp_id,
                "worker_name": "",
                "project_id": pid,
                "smr_type": desc,
                "hours": hours,
                "normal_hours": min(hours, NORMAL_DAY),
                "overtime_hours": max(0, hours - NORMAL_DAY),
                "notes": d.get("notes", ""),
                "report_status": (d.get("approval_status") or "").upper(),
                "submitted_by": d.get("submitted_by"),
                "approved_by": d.get("approved_by"),
                "approved_at": d.get("approved_at"),
                "entered_by_admin": False,
                "entry_mode": "",
                "created_at": d.get("created_at", ""),
                "payroll_status": "none",
                "slip_number": d.get("slip_number"),
                "hourly_rate": 0,
                "labor_value": 0,
                "site_name": "",
            })

    # ── 2. Filter overtime ─────────────────────────────────────────
    if only_overtime:
        rows = [r for r in rows if r["overtime_hours"] > 0]

    # ── 3. Enrich with names, rates ────────────────────────────────
    worker_ids = list({r["worker_id"] for r in rows if r["worker_id"]})
    project_ids = list({r["project_id"] for r in rows if r["project_id"]})
    submitter_ids = list({r["submitted_by"] for r in rows if r["submitted_by"]})
    approver_ids = list({r["approved_by"] for r in rows if r["approved_by"]})
    all_user_ids = list(set(worker_ids + submitter_ids + approver_ids))

    # Users
    users_docs = await db.users.find(
        {"id": {"$in": all_user_ids}},
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "avatar_url": 1},
    ).to_list(300)
    user_map = {u["id"]: u for u in users_docs}

    # Profiles (rates, position, pay_type)
    profiles = await db.employee_profiles.find(
        {"org_id": org_id, "user_id": {"$in": worker_ids}},
        {"_id": 0, "user_id": 1, "hourly_rate": 1, "daily_rate": 1, "monthly_salary": 1,
         "pay_type": 1, "position": 1, "working_days_per_month": 1, "standard_hours_per_day": 1},
    ).to_list(300)
    prof_map = {p["user_id"]: p for p in profiles}

    # Projects
    projects = await db.projects.find(
        {"id": {"$in": project_ids}},
        {"_id": 0, "id": 1, "name": 1, "code": 1},
    ).to_list(200)
    proj_map = {p["id"]: p.get("name") or p.get("code", "") for p in projects}

    def _user_name(uid):
        u = user_map.get(uid)
        if u:
            return f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
        return ""

    def _calc_rate(uid):
        p = prof_map.get(uid)
        if not p:
            return 0
        pay = (p.get("pay_type") or "Monthly").strip()
        if pay == "Hourly":
            return float(p.get("hourly_rate") or 0)
        elif pay == "Daily":
            return round(float(p.get("daily_rate") or 0) / 8, 2)
        else:
            ms = float(p.get("monthly_salary") or 0)
            days = int(p.get("working_days_per_month") or 22)
            hrs = int(p.get("standard_hours_per_day") or 8)
            return round(ms / max(days * hrs, 1), 2)

    for r in rows:
        wid = r["worker_id"]
        if not r["worker_name"]:
            r["worker_name"] = _user_name(wid)
        r["worker_avatar"] = user_map.get(wid, {}).get("avatar_url")
        r["site_name"] = proj_map.get(r["project_id"], "")
        prof = prof_map.get(wid, {})
        r["pay_type"] = prof.get("pay_type", "")
        r["position"] = prof.get("position", "")
        rate = _calc_rate(wid)
        r["hourly_rate"] = rate
        r["labor_value"] = round(r["hours"] * rate, 2)
        r["submitted_by_name"] = _user_name(r["submitted_by"]) if r["submitted_by"] else ""
        r["approved_by_name"] = _user_name(r["approved_by"]) if r["approved_by"] else ""

    # ── 4. Sort ────────────────────────────────────────────────────
    rev = sort_dir == "desc"
    if sort_by == "date":
        rows.sort(key=lambda r: r.get("date", ""), reverse=rev)
    elif sort_by == "worker":
        rows.sort(key=lambda r: r.get("worker_name", ""), reverse=rev)
    elif sort_by == "hours":
        rows.sort(key=lambda r: r.get("hours", 0), reverse=rev)
    elif sort_by == "value":
        rows.sort(key=lambda r: r.get("labor_value", 0), reverse=rev)
    elif sort_by == "status":
        rows.sort(key=lambda r: r.get("report_status", ""), reverse=rev)
    else:
        rows.sort(key=lambda r: r.get("date", ""), reverse=rev)

    # ── 5. Paginate & summary ──────────────────────────────────────
    total = len(rows)
    start = (page - 1) * page_size
    page_rows = rows[start:start + page_size]

    total_hours = sum(r["hours"] for r in rows)
    total_normal = sum(r["normal_hours"] for r in rows)
    total_overtime = sum(r["overtime_hours"] for r in rows)
    total_value = sum(r["labor_value"] for r in rows)
    by_status = {}
    for r in rows:
        s = r["report_status"] or "UNKNOWN"
        by_status[s] = by_status.get(s, 0) + 1

    return {
        "items": page_rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
        "summary": {
            "total_hours": round(total_hours, 1),
            "normal_hours": round(total_normal, 1),
            "overtime_hours": round(total_overtime, 1),
            "total_value": round(total_value, 2),
            "by_status": by_status,
        },
    }
