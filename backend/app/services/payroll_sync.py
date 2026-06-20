"""
Payroll Sync Service — Safe adapter between v3 pay_runs and downstream v2/v1 consumers.

Source of truth: v3 pay_runs, payment_slips, pay_run_allocations
Downstream mirrors:
  A. payroll_payment_allocations (v2) — legacy; project P&L now reads v3 directly
  B. employee_daily_reports.payroll_status — marks reports as batched/paid (CORE, kept)
  C. payslips (v1) — feeds MyPayslipsPage worker self-view (legacy readers remain)
  D. payroll_payments (v1) — RETIRED: finance dashboard/reports now read v3 directly

STATUS LIFECYCLE:
  CONFIRM:   allocations=provisional, reports=batched, payslips=Generated
  MARK-PAID: allocations=active, reports=paid, payslips=Paid
  REOPEN:    allocations=reversed, reports=none, payslips=Reversed

Finance Dashboard / Reports read paid labor from v3 (paid_labor_v3), not payroll_payments.
Project P&L reads paid labor from v3 (paid_labor_allocations_v3), not payroll_payment_allocations.
"""
from app.db import db


async def sync_on_confirm(pay_run: dict, org_id: str, user_id: str):
    """
    Called after v3 pay_run is CONFIRMED (not yet paid).
    Creates provisional mirrors. Finance does NOT see these yet.
    """
    run_id = pay_run["id"]
    now = pay_run.get("confirmed_at") or pay_run.get("created_at", "")

    # ── A. Mirror to payroll_payment_allocations (v2 format) ──────
    # Idempotent: only create if no active/provisional records exist
    existing_active = await db.payroll_payment_allocations.count_documents(
        {"source_pay_run_id": run_id, "org_id": org_id, "status": {"$in": ["provisional", "active"]}}
    )
    if existing_active == 0:
        v2_allocs = []
        for er in pay_run.get("employee_rows", []):
            eid = er["employee_id"]
            paid = er.get("paid_now_amount", 0)
            if paid == 0:
                continue

            by_project = {}
            day_cells = er.get("day_cells", [])
            if day_cells:
                for dc in day_cells:
                    for site in dc.get("sites", [""]):
                        if site not in by_project:
                            by_project[site] = {"hours": 0, "gross": 0}
                        by_project[site]["hours"] += dc.get("hours", 0)
                        by_project[site]["gross"] += dc.get("value", 0)
            else:
                # Fallback: use sites list from employee_row
                for site in er.get("sites", [""]):
                    if site not in by_project:
                        by_project[site] = {"hours": er.get("approved_hours", 0) / max(len(er.get("sites", [""])), 1), "gross": er.get("earned_amount", 0) / max(len(er.get("sites", [""])), 1)}

            total_val = sum(p["gross"] for p in by_project.values())

            for site_name, site_data in by_project.items():
                ratio = site_data["gross"] / total_val if total_val > 0 else 1.0 / max(len(by_project), 1)
                alloc_paid = round(paid * ratio, 2)

                proj = await db.projects.find_one(
                    {"name": site_name, "org_id": org_id}, {"_id": 0, "id": 1}
                ) if site_name else None

                v2_allocs.append({
                    "org_id": org_id,
                    "source_pay_run_id": run_id,
                    "payroll_batch_id": f"sync_{run_id}",
                    "worker_id": eid,
                    "worker_name": f"{er.get('first_name', '')} {er.get('last_name', '')}".strip(),
                    "project_id": (proj or {}).get("id", ""),
                    "project_name": site_name,
                    "allocated_hours": round(site_data["hours"], 2),
                    "allocated_gross_labor": alloc_paid,
                    "allocation_basis": "value" if total_val > 0 else "equal_fallback",
                    "rate_source": "frozen",
                    "lines": [],
                    "week_start": pay_run.get("period_start", ""),
                    "week_end": pay_run.get("period_end", ""),
                    "paid_at": None,
                    "created_by": user_id,
                    "created_at": now,
                    "status": "provisional",
                })

        if v2_allocs:
            await db.payroll_payment_allocations.insert_many(v2_allocs)

    # ── B. Reports → BATCHED (not paid!) ──────────────────────────
    # P0-2A.2: prefer explicit selected_report_ids if provided by frontend (per-report precision).
    # Fall back to date-based bulk update for backwards compatibility (P0-2A and earlier).
    # P0-1 guard remains: $nin ["paid", "batched"] — already-locked reports never get re-marked.
    for er in pay_run.get("employee_rows", []):
        if er.get("paid_now_amount", 0) == 0:
            continue
        eid = er["employee_id"]
        selected_ids = er.get("selected_report_ids", []) or []
        if selected_ids:
            # P0-2A.2 precise mode: mark only the explicitly selected reports.
            await db.employee_daily_reports.update_many(
                {"org_id": org_id, "worker_id": eid, "id": {"$in": selected_ids},
                 "status": "APPROVED",
                 "payroll_status": {"$nin": ["paid", "batched"]}},
                {"$set": {"payroll_status": "batched", "payroll_source": f"pay_run:{run_id}"}},
            )
        else:
            # Legacy mode: mark all approved unpaid reports for the selected days.
            dates = [dc["date"] for dc in er.get("day_cells", []) if dc.get("date")]
            if dates:
                await db.employee_daily_reports.update_many(
                    {"org_id": org_id, "worker_id": eid, "date": {"$in": dates},
                     "status": "APPROVED",
                     "payroll_status": {"$nin": ["paid", "batched"]}},
                    {"$set": {"payroll_status": "batched", "payroll_source": f"pay_run:{run_id}"}},
                )

    # ── C. v1 payslips mirror — RETIRED. Admin HR + cashflow now read v3
    # payment_slips via the legacy_payslips adapter; no mirror is written.


async def sync_on_paid(pay_run: dict, org_id: str, paid_at: str):
    """
    Called after v3 pay_run is MARKED AS PAID.
    Promotes mirrors from provisional → active/paid.
    Only NOW does finance see the paid labor.
    """
    run_id = pay_run["id"]

    # A. Allocations: provisional → active (finance sees them now)
    await db.payroll_payment_allocations.update_many(
        {"source_pay_run_id": run_id, "org_id": org_id, "status": "provisional"},
        {"$set": {"status": "active", "paid_at": paid_at}},
    )

    # B. Reports: batched → paid
    for er in pay_run.get("employee_rows", []):
        if er.get("paid_now_amount", 0) == 0:
            continue
        dates = [dc["date"] for dc in er.get("day_cells", []) if dc.get("date")]
        if dates:
            await db.employee_daily_reports.update_many(
                {"org_id": org_id, "worker_id": er["employee_id"],
                 "date": {"$in": dates}, "payroll_source": f"pay_run:{run_id}"},
                {"$set": {"payroll_status": "paid"}},
            )

    # C. v1 payslips mirror — RETIRED (no status update needed).

    # D. payroll_payments mirror — RETIRED.
    # Finance dashboard/reports now read paid labor directly from v3
    # (paid payment_slips) via paid_labor_v3 — no mirror is written.


async def sync_on_reopen(pay_run: dict, org_id: str, employee_ids: list = None):
    """
    Called after v3 pay_run is REOPENED.
    Reverses downstream mirrors.
    """
    run_id = pay_run["id"]
    reopen_all = not employee_ids

    if reopen_all:
        await db.payroll_payment_allocations.update_many(
            {"source_pay_run_id": run_id, "org_id": org_id},
            {"$set": {"status": "reversed"}},
        )
        # C. v1 payslips mirror — RETIRED (no status update needed).
        # D. payroll_payments mirror — RETIRED (nothing to delete).
        for er in pay_run.get("employee_rows", []):
            dates = [dc["date"] for dc in er.get("day_cells", []) if dc.get("date")]
            if dates:
                await db.employee_daily_reports.update_many(
                    {"org_id": org_id, "worker_id": er["employee_id"],
                     "date": {"$in": dates}, "payroll_source": f"pay_run:{run_id}",
                     "payroll_status": "batched"},
                    {"$set": {"payroll_status": "none", "payroll_source": None}},
                )
    else:
        for eid in employee_ids:
            await db.payroll_payment_allocations.update_many(
                {"source_pay_run_id": run_id, "org_id": org_id, "worker_id": eid},
                {"$set": {"status": "reversed"}},
            )
            # C. v1 payslips mirror — RETIRED (no status update needed).
            # D. payroll_payments mirror — RETIRED (nothing to delete).
            er = next((r for r in pay_run.get("employee_rows", []) if r["employee_id"] == eid), None)
            if er:
                dates = [dc["date"] for dc in er.get("day_cells", []) if dc.get("date")]
                if dates:
                    await db.employee_daily_reports.update_many(
                        {"org_id": org_id, "worker_id": eid,
                         "date": {"$in": dates}, "payroll_source": f"pay_run:{run_id}",
                         "payroll_status": "batched"},
                        {"$set": {"payroll_status": "none", "payroll_source": None}},
                    )
