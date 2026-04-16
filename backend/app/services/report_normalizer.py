"""
Service — Unified Report Normalizer.

Official report model: flat line with these fields:
  id, date, worker_id, worker_name, project_id, smr_type,
  hours, status, payroll_status, notes, source_type,
  submitted_by, approved_by, approved_at,
  entered_by_admin, entry_mode, created_at

Two raw formats exist in employee_daily_reports:
  NEW-STYLE: flat with worker_id, date, hours, smr_type, project_id, status
  OLD-STYLE: structured with employee_id, report_date, day_entries[]

This normalizer reads both and returns a unified flat list.
"""
from app.db import db

NORMAL_DAY = 8


async def fetch_normalized_report_lines(
    org_id: str,
    date_from: str = None,
    date_to: str = None,
    worker_id: str = None,
    project_id: str = None,
    smr_filter: str = None,
    status_filter: str = None,
    payroll_filter: list = None,
) -> list:
    """
    Fetch and normalize all report lines from both old and new style.
    Returns flat list of unified report line dicts.
    """
    lines = []

    # ── A) New-style (flat with worker_id) ─────────────────────────
    q_new = {"org_id": org_id, "worker_id": {"$exists": True}}
    if date_from and date_to:
        q_new["date"] = {"$gte": date_from, "$lte": date_to}
    if worker_id:
        q_new["worker_id"] = worker_id
    if project_id:
        q_new["project_id"] = project_id
    if smr_filter:
        q_new["smr_type"] = {"$regex": smr_filter, "$options": "i"}
    if status_filter:
        upper = status_filter.upper()
        q_new["status"] = {"$in": [status_filter, upper, status_filter.capitalize()]}
    if payroll_filter:
        # payroll_filter can be ["!paid", "!batched"] to exclude, or ["paid"] to include
        if any(f.startswith("!") for f in payroll_filter):
            exclude = [f[1:] for f in payroll_filter if f.startswith("!")]
            q_new["payroll_status"] = {"$nin": exclude}
        else:
            q_new["payroll_status"] = {"$in": payroll_filter}

    new_docs = await db.employee_daily_reports.find(q_new, {"_id": 0}).to_list(5000)

    for d in new_docs:
        lines.append({
            "id": d.get("id", ""),
            "source_type": "new",
            "date": d.get("date", ""),
            "worker_id": d.get("worker_id", ""),
            "worker_name": d.get("worker_name", ""),
            "project_id": d.get("project_id", ""),
            "smr_type": d.get("smr_type", ""),
            "hours": float(d.get("hours") or 0),
            "status": (d.get("status") or "").upper(),
            "payroll_status": d.get("payroll_status") or "none",
            "payroll_batch_id": d.get("payroll_batch_id"),
            "notes": d.get("notes", ""),
            "submitted_by": d.get("submitted_by"),
            "approved_by": d.get("approved_by"),
            "approved_at": d.get("approved_at"),
            "entered_by_admin": d.get("entered_by_admin", False),
            "entry_mode": d.get("entry_mode", ""),
            "created_at": d.get("created_at", ""),
            "slip_number": d.get("slip_number"),
        })

    # ── B) Old-style (structured with employee_id + day_entries) ───
    q_old = {"org_id": org_id, "employee_id": {"$exists": True}}
    if status_filter:
        upper = status_filter.upper()
        q_old["approval_status"] = {"$in": [status_filter, upper, status_filter.capitalize()]}
    if payroll_filter:
        if any(f.startswith("!") for f in payroll_filter):
            exclude = [f[1:] for f in payroll_filter if f.startswith("!")]
            q_old["payroll_status"] = {"$nin": exclude}
        else:
            q_old["payroll_status"] = {"$in": payroll_filter}

    old_docs = await db.employee_daily_reports.find(q_old, {"_id": 0}).to_list(5000)

    for d in old_docs:
        emp_id = d.get("employee_id", "")
        if worker_id and emp_id != worker_id:
            continue
        report_date = d.get("report_date", "")
        if date_from and date_to and (report_date < date_from or report_date > date_to):
            continue

        for entry in d.get("day_entries", []):
            pid = entry.get("project_id", "")
            if project_id and pid != project_id:
                continue
            desc = entry.get("work_description", "")
            if smr_filter and smr_filter.lower() not in desc.lower():
                continue

            lines.append({
                "id": d.get("id", "") + "_" + entry.get("id", ""),
                "source_type": "old",
                "date": report_date,
                "worker_id": emp_id,
                "worker_name": "",
                "project_id": pid,
                "smr_type": desc,
                "hours": float(entry.get("hours_worked") or 0),
                "status": (d.get("approval_status") or "").upper(),
                "payroll_status": d.get("payroll_status") or "none",
                "payroll_batch_id": d.get("payroll_batch_id"),
                "notes": d.get("notes", ""),
                "submitted_by": d.get("submitted_by"),
                "approved_by": d.get("approved_by"),
                "approved_at": d.get("approved_at"),
                "entered_by_admin": False,
                "entry_mode": "",
                "created_at": d.get("created_at", ""),
                "slip_number": d.get("slip_number"),
            })

    return lines


def enrich_hours(line: dict) -> dict:
    """Add normal_hours / overtime_hours to a normalized line.
    NOTE: This is a fallback for single-line enrichment.
    For proper per-worker-per-day calculation, use enrich_hours_batch() instead."""
    h = line.get("hours", 0)
    line["normal_hours"] = min(h, NORMAL_DAY)
    line["overtime_hours"] = max(0, h - NORMAL_DAY)
    return line


def enrich_hours_batch(lines: list) -> list:
    """Compute normal/overtime by WORKER + DATE total, not per individual line.
    Rule: first 8h of the day = normal, everything above = overtime.
    Hours are distributed proportionally across lines for the same worker+date."""

    # Group lines by worker_id + date
    from collections import defaultdict
    groups = defaultdict(list)
    for ln in lines:
        key = (ln.get("worker_id", ""), ln.get("date", ""))
        groups[key].append(ln)

    for (wid, date), group_lines in groups.items():
        day_total = sum(ln.get("hours", 0) for ln in group_lines)
        day_normal = min(day_total, NORMAL_DAY)
        day_overtime = max(0, day_total - NORMAL_DAY)

        # Store day totals on each line for UI access
        for ln in group_lines:
            ln["day_total_hours"] = round(day_total, 2)
            ln["day_normal_hours"] = round(day_normal, 2)
            ln["day_overtime_hours"] = round(day_overtime, 2)

        if day_total == 0:
            for ln in group_lines:
                ln["normal_hours"] = 0
                ln["overtime_hours"] = 0
            continue

        # Distribute proportionally
        allocated_normal = 0
        for i, ln in enumerate(group_lines):
            h = ln.get("hours", 0)
            ratio = h / day_total if day_total > 0 else 0

            if i < len(group_lines) - 1:
                ln_normal = round(day_normal * ratio, 2)
                ln_overtime = round(h - ln_normal, 2)
                allocated_normal += ln_normal
            else:
                # Last line gets remainder to avoid rounding errors
                ln_normal = round(day_normal - allocated_normal, 2)
                ln_overtime = round(h - ln_normal, 2)

            ln["normal_hours"] = max(0, ln_normal)
            ln["overtime_hours"] = max(0, ln_overtime)

        # Warnings
        level = "ok"
        warnings = []
        if day_total > 12:
            level = "critical"
            warnings.append(f"Общо {day_total:.1f}ч за деня. Проверете за грешка.")
        elif day_total > 8:
            level = "warning"
            warnings.append(f"Общо {day_total:.1f}ч за деня ({day_overtime:.1f}ч извънредни).")
        if len(group_lines) > 1:
            projects = set(ln.get("project_id") for ln in group_lines if ln.get("project_id"))
            if len(projects) > 1:
                warnings.append(f"Работил на {len(projects)} обекта в деня.")

        for ln in group_lines:
            ln["day_warnings"] = warnings
            ln["day_warning_level"] = level

    return lines


async def fetch_worker_day_map(
    org_id: str,
    date_from: str,
    date_to: str,
    worker_ids: list = None,
    status_filter: str = None,
    payroll_filter: list = None,
) -> dict:
    """
    Fetch normalized lines and group by worker_id → date → [entries].
    Used by weekly_matrix and payroll_batch eligible.
    Returns: {worker_id: {date: [{report_id, smr, hours, project_id, project_name, status}]}}
    """
    lines = await fetch_normalized_report_lines(
        org_id=org_id,
        date_from=date_from,
        date_to=date_to,
        status_filter=status_filter,
        payroll_filter=payroll_filter,
    )

    # Filter by worker_ids if provided
    if worker_ids:
        wset = set(worker_ids)
        lines = [ln for ln in lines if ln["worker_id"] in wset]

    # Group by worker → date → entries
    wd_map = {}
    project_ids = set()

    for ln in lines:
        wid = ln["worker_id"]
        d = ln["date"]
        if wid not in wd_map:
            wd_map[wid] = {}
        if d not in wd_map[wid]:
            wd_map[wid][d] = []
        wd_map[wid][d].append({
            "report_id": ln["id"].split("_")[0],
            "smr": ln["smr_type"],
            "hours": ln["hours"],
            "project_id": ln["project_id"],
            "project_name": "",
            "status": ln["status"],
            "notes": ln["notes"],
        })
        if ln["project_id"]:
            project_ids.add(ln["project_id"])

    # Enrich project names
    if project_ids:
        projects = await db.projects.find(
            {"id": {"$in": list(project_ids)}},
            {"_id": 0, "id": 1, "name": 1},
        ).to_list(200)
        proj_map = {p["id"]: p.get("name", "") for p in projects}
        for wid_data in wd_map.values():
            for day_entries in wid_data.values():
                for e in day_entries:
                    e["project_name"] = proj_map.get(e["project_id"], "")

    return wd_map, project_ids
