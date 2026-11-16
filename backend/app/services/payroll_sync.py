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
from app.services.report_normalizer import old_line_id
from app.tenancy.data_access import TenantData

LOCKED = ("paid", "batched")


# ═══════════════════════════════ LAB-R96 step 4: payment state on BOTH stored formats
# Р100 "плащането заключва реда": the pay run marks the exact LINES it holds — flat lines by
# ``id`` (``worker_id`` rows), old-format reports (``employee_id / report_date / day_entries``)
# per day entry, by the line id ``<report>_<entry>`` that report_normalizer gives them
# (``day_entries.<i>.payroll_status / payroll_source``). The report-level ``payroll_status`` of
# an old report follows its entries (all paid → paid, all batched/paid → batched).
def row_line_ids(er: dict) -> list:
    """The line ids a frozen employee row holds: its explicit selection, else every line of
    its day cells (the preview only offers approved, unpaid lines)."""
    ids = list(er.get("selected_report_ids") or [])
    if ids:
        return ids
    for dc in er.get("day_cells") or []:
        for r in dc.get("reports") or []:
            if r.get("report_id") and r["report_id"] not in ids:
                ids.append(r["report_id"])
        for rid in dc.get("report_ids") or []:
            if rid and rid not in ids:
                ids.append(rid)
    return ids


def _row_dates(er: dict) -> list:
    return [dc["date"] for dc in er.get("day_cells", []) if dc.get("date")]


def _doc_level(doc: dict, entries: list) -> str:
    states = [e.get("payroll_status") or doc.get("payroll_status") or "none" for e in entries]
    if states and all(st == "paid" for st in states):
        return "paid"
    if states and all(st in LOCKED for st in states):
        return "batched"
    return "none"


async def _mark_old(tenant, org_id: str, docs: list, pick, new_status: str, source) -> int:
    """Set ``new_status`` (and ``source``; None unsets) on the entries ``pick(doc, entry)``
    selects, then the report-level status. Returns how many entries changed."""
    changed = 0
    for doc in docs:
        entries = [dict(e) for e in doc.get("day_entries") or []]
        sets = {}
        for i, e in enumerate(entries):
            if not pick(doc, e):
                continue
            e["payroll_status"], e["payroll_source"] = new_status, source
            sets["day_entries.%d.payroll_status" % i] = new_status
            sets["day_entries.%d.payroll_source" % i] = source
            changed += 1
        if not sets:
            continue
        level = _doc_level(dict(doc, payroll_status=None), entries)
        sets["payroll_status"] = level
        srcs = {e.get("payroll_source") for e in entries}
        sets["payroll_source"] = srcs.pop() if len(srcs) == 1 else None
        await tenant.employee_daily_reports.update_one(
            {"org_id": org_id, "id": doc["id"]}, {"$inc": {"version": 1}, "$set": sets})
    return changed


async def _old_docs(tenant, org_id: str, eid: str, flt: dict) -> list:
    return await tenant.employee_daily_reports.find(
        {"org_id": org_id, "employee_id": eid, **flt}, {"_id": 0}).to_list(1000)


async def batch_row_lines(tenant, org_id: str, er: dict, run_id: str) -> None:
    """CONFIRM: the row's approved, not yet batched/paid lines → batched by this run."""
    eid, src = er["employee_id"], "pay_run:%s" % run_id
    ids, dates = row_line_ids(er), _row_dates(er)
    upd = {"$inc": {"version": 1}, "$set": {"payroll_status": "batched", "payroll_source": src}}
    if ids:
        await tenant.employee_daily_reports.update_many(
            {"org_id": org_id, "worker_id": eid, "id": {"$in": ids}, "status": "APPROVED",
             "payroll_status": {"$nin": list(LOCKED)}}, upd)
    elif dates:
        # Legacy mode (a row without line ids): all approved unpaid flat lines of its days.
        await tenant.employee_daily_reports.update_many(
            {"org_id": org_id, "worker_id": eid, "date": {"$in": dates}, "status": "APPROVED",
             "payroll_status": {"$nin": list(LOCKED)}}, upd)
    if not (ids or dates):
        return
    wanted = set(ids)
    docs = await _old_docs(tenant, org_id, eid, {"report_date": {"$in": dates}} if dates else {})

    def pick(doc, e):
        if (doc.get("approval_status") or "").upper() != "APPROVED":
            return False
        if (e.get("payroll_status") or doc.get("payroll_status") or "none") in LOCKED:
            return False
        return old_line_id(doc, e) in wanted if wanted else doc.get("report_date") in dates
    await _mark_old(tenant, org_id, docs, pick, "batched", src)


async def pay_row_lines(tenant, org_id: str, er: dict, run_id: str) -> None:
    """MARK-PAID: the lines this run batched → paid."""
    eid, src = er["employee_id"], "pay_run:%s" % run_id
    await tenant.employee_daily_reports.update_many(
        {"org_id": org_id, "worker_id": eid, "payroll_source": src},
        {"$inc": {"version": 1}, "$set": {"payroll_status": "paid"}})
    docs = await _old_docs(tenant, org_id, eid, {"day_entries.payroll_source": src})
    await _mark_old(tenant, org_id, docs, lambda d, e: e.get("payroll_source") == src, "paid", src)


async def release_row_lines(tenant, org_id: str, er: dict, run_id: str) -> None:
    """REOPEN: the lines this run batched (not paid) → back to unpaid."""
    eid, src = er["employee_id"], "pay_run:%s" % run_id
    dates = _row_dates(er)
    if dates:
        await tenant.employee_daily_reports.update_many(
            {"org_id": org_id, "worker_id": eid, "date": {"$in": dates}, "payroll_source": src,
             "payroll_status": "batched"},
            {"$inc": {"version": 1}, "$set": {"payroll_status": "none", "payroll_source": None}})
    docs = await _old_docs(tenant, org_id, eid, {"day_entries.payroll_source": src})
    await _mark_old(tenant, org_id, docs,
                    lambda d, e: e.get("payroll_source") == src and e.get("payroll_status") == "batched",
                    "none", None)


async def sync_on_confirm(pay_run: dict, org_id: str, user_id: str):
    """
    Called after v3 pay_run is CONFIRMED (not yet paid).
    Creates provisional mirrors. Finance does NOT see these yet.
    """
    tenant = TenantData.for_resolved_org(db, org_id)
    run_id = pay_run["id"]
    now = pay_run.get("confirmed_at") or pay_run.get("created_at", "")

    # ── A. Mirror to payroll_payment_allocations (v2 format) ──────
    # Idempotent: only create if no active/provisional records exist
    existing_active = await tenant.payroll_payment_allocations.count_documents(
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

                proj = await tenant.projects.find_one(
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
            await tenant.payroll_payment_allocations.insert_many(v2_allocs)

    # ── B. Reports → BATCHED (not paid!) ──────────────────────────
    # P0-2A.2 / P0-1: only the row's lines, never already-locked ones. LAB-R96 step 4: both
    # stored formats, by line id (batch_row_lines).
    for er in pay_run.get("employee_rows", []):
        if er.get("paid_now_amount", 0) == 0:
            continue
        await batch_row_lines(tenant, org_id, er, run_id)

    # ── C. v1 payslips mirror — RETIRED. Admin HR + cashflow now read v3
    # payment_slips via the legacy_payslips adapter; no mirror is written.


async def sync_on_paid(pay_run: dict, org_id: str, paid_at: str):
    """
    Called after v3 pay_run is MARKED AS PAID.
    Promotes mirrors from provisional → active/paid.
    Only NOW does finance see the paid labor.
    """
    tenant = TenantData.for_resolved_org(db, org_id)
    run_id = pay_run["id"]

    # A. Allocations: provisional → active (finance sees them now)
    await tenant.payroll_payment_allocations.update_many(
        {"source_pay_run_id": run_id, "org_id": org_id, "status": "provisional"},
        {"$set": {"status": "active", "paid_at": paid_at}},
    )

    # B. Reports: batched → paid (LAB-R96 step 4: both stored formats)
    for er in pay_run.get("employee_rows", []):
        if er.get("paid_now_amount", 0) == 0:
            continue
        await pay_row_lines(tenant, org_id, er, run_id)

    # C. v1 payslips mirror — RETIRED (no status update needed).

    # D. payroll_payments mirror — RETIRED.
    # Finance dashboard/reports now read paid labor directly from v3
    # (paid payment_slips) via paid_labor_v3 — no mirror is written.


async def sync_on_reopen(pay_run: dict, org_id: str, employee_ids: list = None):
    """
    Called after v3 pay_run is REOPENED.
    Reverses downstream mirrors.
    """
    tenant = TenantData.for_resolved_org(db, org_id)
    run_id = pay_run["id"]
    reopen_all = not employee_ids

    if reopen_all:
        await tenant.payroll_payment_allocations.update_many(
            {"source_pay_run_id": run_id, "org_id": org_id},
            {"$set": {"status": "reversed"}},
        )
        # C. v1 payslips mirror — RETIRED (no status update needed).
        # D. payroll_payments mirror — RETIRED (nothing to delete).
        for er in pay_run.get("employee_rows", []):
            await release_row_lines(tenant, org_id, er, run_id)
    else:
        for eid in employee_ids:
            await tenant.payroll_payment_allocations.update_many(
                {"source_pay_run_id": run_id, "org_id": org_id, "worker_id": eid},
                {"$set": {"status": "reversed"}},
            )
            # C. v1 payslips mirror — RETIRED (no status update needed).
            # D. payroll_payments mirror — RETIRED (nothing to delete).
            er = next((r for r in pay_run.get("employee_rows", []) if r["employee_id"] == eid), None)
            if er:
                await release_row_lines(tenant, org_id, er, run_id)
