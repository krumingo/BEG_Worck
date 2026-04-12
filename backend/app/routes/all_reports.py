"""
Routes — All Reports (Central read-only table).
Uses unified report normalizer.
"""
from fastapi import APIRouter, Depends, Query
from typing import Optional
from datetime import datetime, timezone, timedelta

from app.db import db
from app.deps.auth import get_current_user
from app.services.report_normalizer import fetch_normalized_report_lines, enrich_hours, NORMAL_DAY

router = APIRouter(tags=["All Reports"])


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

    if not date_from:
        date_from = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    if not date_to:
        date_to = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ── Fetch unified normalized lines ─────────────────────────────
    rows = await fetch_normalized_report_lines(
        org_id=org_id,
        date_from=date_from,
        date_to=date_to,
        worker_id=worker_id,
        project_id=project_id,
        smr_filter=smr,
        status_filter=report_status,
    )

    # Enrich hours
    for r in rows:
        enrich_hours(r)

    # Filter overtime
    if only_overtime:
        rows = [r for r in rows if r["overtime_hours"] > 0]

    # ── Enrich with names, rates ────────────────────────────────
    worker_ids = list({r["worker_id"] for r in rows if r["worker_id"]})
    project_ids = list({r["project_id"] for r in rows if r["project_id"]})
    all_user_ids = list(set(
        worker_ids
        + [r["submitted_by"] for r in rows if r.get("submitted_by")]
        + [r["approved_by"] for r in rows if r.get("approved_by")]
    ))

    users_docs = await db.users.find(
        {"id": {"$in": all_user_ids}},
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "avatar_url": 1},
    ).to_list(300)
    user_map = {u["id"]: u for u in users_docs}

    profiles = await db.employee_profiles.find(
        {"org_id": org_id, "user_id": {"$in": worker_ids}},
        {"_id": 0, "user_id": 1, "hourly_rate": 1, "daily_rate": 1, "monthly_salary": 1,
         "pay_type": 1, "position": 1, "working_days_per_month": 1, "standard_hours_per_day": 1},
    ).to_list(300)
    prof_map = {p["user_id"]: p for p in profiles}

    projects = await db.projects.find(
        {"id": {"$in": project_ids}},
        {"_id": 0, "id": 1, "name": 1, "code": 1},
    ).to_list(200)
    proj_map = {p["id"]: p.get("name") or p.get("code", "") for p in projects}

    def _user_name(uid):
        u = user_map.get(uid)
        return f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() if u else ""

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

    # ── Sort ────────────────────────────────────────────────────
    rev = sort_dir == "desc"
    sort_keys = {
        "date": lambda r: r.get("date", ""),
        "worker": lambda r: r.get("worker_name", ""),
        "hours": lambda r: r.get("hours", 0),
        "value": lambda r: r.get("labor_value", 0),
        "status": lambda r: r.get("status", ""),
    }
    rows.sort(key=sort_keys.get(sort_by, sort_keys["date"]), reverse=rev)

    # ── Paginate & summary ──────────────────────────────────────
    total = len(rows)
    start = (page - 1) * page_size
    page_rows = rows[start:start + page_size]

    total_hours = sum(r["hours"] for r in rows)
    total_normal = sum(r["normal_hours"] for r in rows)
    total_overtime = sum(r["overtime_hours"] for r in rows)
    total_value = sum(r["labor_value"] for r in rows)
    by_status = {}
    for r in rows:
        s = r["status"] or "UNKNOWN"
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
