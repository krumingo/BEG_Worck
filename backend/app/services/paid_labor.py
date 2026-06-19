"""Paid labor from v3 payment_slips — replaces the legacy payroll_payments mirror.

Returns the exact shape the finance dashboard/reports already expect, so call
sites stay unchanged:
    {id, payment_date (YYYY-MM-DD), net_salary, employee_name}

Mapping mirrors what payroll_sync used to write into payroll_payments:
    net_salary   = paid_now_amount   (cash paid in that run)
    payment_date = paid_at[:10]      (date only)
Only paid slips with a non-zero amount are returned (same as the old sync).
"""
from app.db import db


async def paid_labor_v3(org_id: str, date_from: str, date_to: str) -> list[dict]:
    # paid_at is a full ISO timestamp; extend the upper bound so payments made
    # on date_to (which carry a time component) are not dropped.
    upper = date_to if "T" in (date_to or "") else (date_to or "") + "T23:59:59.999999"
    slips = await db.payment_slips.find(
        {
            "org_id": org_id,
            "status": "paid",
            "archived": {"$ne": True},
            "paid_at": {"$gte": date_from, "$lte": upper},
        },
        {"_id": 0, "id": 1, "paid_at": 1, "paid_now_amount": 1, "first_name": 1, "last_name": 1},
    ).to_list(10000)
    out = []
    for s in slips:
        amt = round(float(s.get("paid_now_amount") or 0), 2)
        if amt == 0:
            continue
        out.append({
            "id": s.get("id"),
            "payment_date": (s.get("paid_at") or "")[:10],
            "net_salary": amt,
            "employee_name": (f"{s.get('first_name', '')} {s.get('last_name', '')}").strip(),
        })
    return out


async def _paid_alloc_rows(org_id: str) -> list[dict]:
    """All per-project PAID labor allocation rows across paid pay_runs (read once).

    Reproduces exactly the proportional-by-value split the old payroll_sync used, but
    reads paid pay_runs directly (status == "paid"). Each row:
        {project_id, allocated_gross_labor, allocated_hours, worker_id, worker_name}
    When no run is paid, returns [] (paid labor = 0), matching the old "active" filter.
    """
    runs = await db.pay_runs.find(
        {"org_id": org_id, "status": "paid", "archived": {"$ne": True}},
        {"_id": 0, "employee_rows": 1},
    ).to_list(1000)

    proj_cache: dict = {}

    async def _resolve(name: str) -> str:
        if not name:
            return ""
        if name in proj_cache:
            return proj_cache[name]
        p = await db.projects.find_one({"name": name, "org_id": org_id}, {"_id": 0, "id": 1})
        pid = (p or {}).get("id", "")
        proj_cache[name] = pid
        return pid

    rows: list[dict] = []
    for run in runs:
        for er in run.get("employee_rows", []):
            paid = er.get("paid_now_amount", 0)
            if not paid:
                continue
            by_project: dict = {}
            day_cells = er.get("day_cells", [])
            if day_cells:
                for dc in day_cells:
                    for site in (dc.get("sites") or [""]):
                        b = by_project.setdefault(site, {"hours": 0, "gross": 0})
                        b["hours"] += dc.get("hours", 0)
                        b["gross"] += dc.get("value", 0)
            else:
                sites = er.get("sites") or [""]
                n = max(len(sites), 1)
                for site in sites:
                    by_project.setdefault(site, {
                        "hours": er.get("approved_hours", 0) / n,
                        "gross": er.get("earned_amount", 0) / n,
                    })
            total_val = sum(p["gross"] for p in by_project.values())
            for site_name, sd in by_project.items():
                ratio = sd["gross"] / total_val if total_val > 0 else 1.0 / max(len(by_project), 1)
                rows.append({
                    "project_id": await _resolve(site_name),
                    "allocated_gross_labor": round(paid * ratio, 2),
                    "allocated_hours": round(sd["hours"], 2),
                    "worker_id": er.get("employee_id"),
                    "worker_name": f"{er.get('first_name', '')} {er.get('last_name', '')}".strip(),
                })
    return rows


async def paid_labor_allocations_v3(org_id: str, project_id: str) -> list[dict]:
    """Paid labor allocation rows for a single project (replaces payroll_payment_allocations)."""
    rows = await _paid_alloc_rows(org_id)
    return [r for r in rows if r["project_id"] == project_id]


async def paid_labor_for_projects_v3(org_id, project_ids) -> dict:
    """Aggregate paid labor (gross + hours) across a set of project ids."""
    wanted = set(project_ids or [])
    rows = [r for r in await _paid_alloc_rows(org_id) if r["project_id"] in wanted]
    return {
        "gross_labor": round(sum(r["allocated_gross_labor"] for r in rows), 2),
        "paid_hours": round(sum(r["allocated_hours"] for r in rows), 1),
    }
