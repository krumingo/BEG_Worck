"""
Payroll Sync Service — Safe adapter between v3 pay_runs and downstream v2/v1 consumers.

Source of truth: v3 pay_runs, payment_slips, pay_run_allocations
Downstream mirrors:
  A. payroll_payment_allocations (v2) — feeds project_financial_results.py
  B. employee_daily_reports.payroll_status — marks reports as paid
  C. payslips (v1) — feeds MyPayslipsPage worker self-view

All operations are IDEMPOTENT: dedupe by source_pay_run_id.
Reopen/reverse: marks mirrors as reversed, restores report statuses.
"""
from app.db import db


async def sync_on_confirm(pay_run: dict, org_id: str, user_id: str):
    """
    Called after v3 pay_run is confirmed.
    Syncs to v2 allocations + report statuses + v1 payslips.
    Idempotent: skips if already synced for this pay_run_id.
    """
    run_id = pay_run["id"]
    now = pay_run.get("confirmed_at") or pay_run.get("created_at", "")

    # ── A. Mirror to payroll_payment_allocations (v2 format) ──────
    existing_allocs = await db.payroll_payment_allocations.count_documents(
        {"source_pay_run_id": run_id, "org_id": org_id}
    )
    if existing_allocs == 0:
        v2_allocs = []
        for er in pay_run.get("employee_rows", []):
            eid = er["employee_id"]
            paid = er.get("paid_now_amount", 0)
            if paid == 0:
                continue

            # Build per-project breakdown from day_cells
            by_project = {}
            for dc in er.get("day_cells", []):
                for site in dc.get("sites", [""]):
                    if site not in by_project:
                        by_project[site] = {"hours": 0, "gross": 0}
                    by_project[site]["hours"] += dc.get("hours", 0)
                    by_project[site]["gross"] += dc.get("value", 0)

            total_val = sum(p["gross"] for p in by_project.values())

            for site_name, site_data in by_project.items():
                # Proportional allocation of paid amount
                if total_val > 0:
                    ratio = site_data["gross"] / total_val
                else:
                    ratio = 1.0 / max(len(by_project), 1)
                alloc_paid = round(paid * ratio, 2)

                # Lookup project_id by name
                proj = await db.projects.find_one(
                    {"name": site_name, "org_id": org_id},
                    {"_id": 0, "id": 1}
                ) if site_name else None
                proj_id = proj["id"] if proj else ""

                v2_allocs.append({
                    "org_id": org_id,
                    "source_pay_run_id": run_id,
                    "payroll_batch_id": f"sync_{run_id}",
                    "worker_id": eid,
                    "worker_name": f"{er.get('first_name', '')} {er.get('last_name', '')}".strip(),
                    "project_id": proj_id,
                    "project_name": site_name,
                    "allocated_hours": round(site_data["hours"], 2),
                    "allocated_gross_labor": alloc_paid,
                    "allocation_basis": "value" if total_val > 0 else "equal_fallback",
                    "rate_source": "frozen",
                    "lines": [],
                    "week_start": pay_run.get("period_start", ""),
                    "week_end": pay_run.get("period_end", ""),
                    "paid_at": now,
                    "created_by": user_id,
                    "created_at": now,
                    "status": "active",
                })

        if v2_allocs:
            await db.payroll_payment_allocations.insert_many(v2_allocs)

    # ── B. Update employee_daily_reports.payroll_status ────────────
    # Collect all report-related dates + worker_ids to find matching reports
    for er in pay_run.get("employee_rows", []):
        if er.get("paid_now_amount", 0) == 0:
            continue
        eid = er["employee_id"]
        dates = [dc["date"] for dc in er.get("day_cells", []) if dc.get("date")]
        if dates:
            await db.employee_daily_reports.update_many(
                {"org_id": org_id, "worker_id": eid, "date": {"$in": dates},
                 "status": "APPROVED",
                 "payroll_status": {"$nin": ["paid"]}},
                {"$set": {"payroll_status": "paid", "payroll_source": f"pay_run:{run_id}"}},
            )

    # ── C. Mirror to payslips (v1 format for MyPayslipsPage) ──────
    existing_v1 = await db.payslips.count_documents(
        {"source_pay_run_id": run_id, "org_id": org_id}
    )
    if existing_v1 == 0:
        v1_slips = []
        for er in pay_run.get("employee_rows", []):
            eid = er["employee_id"]
            paid = er.get("paid_now_amount", 0)
            v1_slips.append({
                "org_id": org_id,
                "source_pay_run_id": run_id,
                "payroll_run_id": f"sync_{run_id}",
                "employee_id": eid,
                "period_start": pay_run.get("period_start", ""),
                "period_end": pay_run.get("period_end", ""),
                "gross_pay": round(er.get("earned_amount", 0), 2),
                "deductions": round(er.get("deductions_amount", 0), 2),
                "bonuses": round(er.get("bonuses_amount", 0), 2),
                "net_pay": round(paid, 2),
                "status": "Paid" if paid > 0 else "Generated",
                "employee_name": f"{er.get('first_name', '')} {er.get('last_name', '')}".strip(),
                "week_number": pay_run.get("week_number"),
                "created_at": now,
                "synced_from": "v3_pay_runs",
            })
        if v1_slips:
            await db.payslips.insert_many(v1_slips)


async def sync_on_paid(pay_run: dict, org_id: str, paid_at: str):
    """
    Called after v3 pay_run is marked as paid.
    Updates mirror statuses.
    """
    run_id = pay_run["id"]

    # Update v2 allocations status
    await db.payroll_payment_allocations.update_many(
        {"source_pay_run_id": run_id, "org_id": org_id},
        {"$set": {"status": "active", "paid_at": paid_at}},
    )

    # Update v1 payslips
    await db.payslips.update_many(
        {"source_pay_run_id": run_id, "org_id": org_id},
        {"$set": {"status": "Paid", "paid_at": paid_at}},
    )


async def sync_on_reopen(pay_run: dict, org_id: str, employee_ids: list = None):
    """
    Called after v3 pay_run is reopened (whole or specific rows).
    Reverses downstream mirrors.
    """
    run_id = pay_run["id"]
    reopen_all = not employee_ids

    if reopen_all:
        # Reverse all v2 allocations for this run
        await db.payroll_payment_allocations.update_many(
            {"source_pay_run_id": run_id, "org_id": org_id},
            {"$set": {"status": "reversed"}},
        )
        # Reverse v1 payslips
        await db.payslips.update_many(
            {"source_pay_run_id": run_id, "org_id": org_id},
            {"$set": {"status": "Reversed"}},
        )
        # Restore report statuses
        for er in pay_run.get("employee_rows", []):
            dates = [dc["date"] for dc in er.get("day_cells", []) if dc.get("date")]
            if dates:
                await db.employee_daily_reports.update_many(
                    {"org_id": org_id, "worker_id": er["employee_id"],
                     "date": {"$in": dates}, "payroll_source": f"pay_run:{run_id}"},
                    {"$set": {"payroll_status": "none", "payroll_source": None}},
                )
    else:
        # Reverse only specific employees
        for eid in employee_ids:
            await db.payroll_payment_allocations.update_many(
                {"source_pay_run_id": run_id, "org_id": org_id, "worker_id": eid},
                {"$set": {"status": "reversed"}},
            )
            await db.payslips.update_many(
                {"source_pay_run_id": run_id, "org_id": org_id, "employee_id": eid},
                {"$set": {"status": "Reversed"}},
            )
            er = next((r for r in pay_run.get("employee_rows", []) if r["employee_id"] == eid), None)
            if er:
                dates = [dc["date"] for dc in er.get("day_cells", []) if dc.get("date")]
                if dates:
                    await db.employee_daily_reports.update_many(
                        {"org_id": org_id, "worker_id": eid,
                         "date": {"$in": dates}, "payroll_source": f"pay_run:{run_id}"},
                        {"$set": {"payroll_status": "none", "payroll_source": None}},
                    )
