"""
Service - Centralized Reports Model.
Single source of truth for project views: Activities, Personnel, Finance.
One report entry → three projections.
"""
from datetime import datetime, timezone
from collections import defaultdict
from app.db import db
from app.services.budget_formula import calculate_budget_formula_sync
from app.services.resolve_hourly_rate import resolve_worker_hourly_rate


async def get_overhead_rate(org_id: str) -> float:
    """Get current overhead per person per day."""
    try:
        from app.services.overhead_realtime import compute_realtime_overhead
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        oh = await compute_realtime_overhead(org_id, month)
        return oh.get("overhead_per_person_day", 0)
    except Exception:
        return 0


async def build_centralized_reports(org_id: str, project_id: str) -> dict:
    """
    Build unified reports from:
    - employee_daily_reports (Draft/Submitted entries)
    - work_sessions (Approved entries, source of truth for cost)
    Returns: unified entries list + three projections.
    """
    overhead_rate = await get_overhead_rate(org_id)
    overhead_hourly = round(overhead_rate / 8, 2) if overhead_rate > 0 else 0

    # ── Collect all report entries ──────────────────────────────
    entries = []

    # A) Draft/Submitted entries from employee_daily_reports
    drafts = await db.employee_daily_reports.find(
        {"org_id": org_id, "project_id": project_id,
         "status": {"$in": ["Draft", "Submitted", "SUBMITTED"]}},
        {"_id": 0},
    ).to_list(2000)

    # Cache resolved rates per worker
    rate_cache = {}

    for d in drafts:
        hours = d.get("hours") or d.get("hours_worked", 0)
        wid = d.get("worker_id", "")

        # Resolve rate using shared helper (cached)
        if wid not in rate_cache:
            rate_cache[wid] = await resolve_worker_hourly_rate(wid, org_id)
        resolved = rate_cache[wid]
        rate = resolved["rate"]

        clean = round(hours * rate, 2)
        oh_amount = round(hours * overhead_hourly, 2)

        entries.append({
            "id": d.get("id"),
            "worker_id": wid,
            "worker_name": d.get("worker_name", ""),
            "project_id": project_id,
            "report_date": d.get("date", ""),
            "smr_type": d.get("smr_type") or d.get("activity_type", ""),
            "hours": round(hours, 2),
            "hourly_rate": rate,
            "approval_status": "draft",
            "amount_clean_labor": clean,
            "amount_overhead": oh_amount,
            "amount_labor_with_overhead": round(clean + oh_amount, 2),
            "slip_number": d.get("slip_number"),
            "created_by": d.get("submitted_by") or d.get("created_by"),
            "approved_by": None,
            "payroll_ready": False,
            "source": "employee_daily_reports",
            "missing_rate": resolved["missing_rate"],
            "rate_source": resolved["source"],
        })

    # B) Approved entries from work_sessions
    sessions = await db.work_sessions.find(
        {"org_id": org_id, "site_id": project_id, "ended_at": {"$ne": None},
         "is_flagged": {"$ne": True}},
        {"_id": 0},
    ).to_list(5000)

    for s in sessions:
        hours = s.get("duration_hours", 0)
        rate = s.get("hourly_rate_at_date", 0)
        wid = s.get("worker_id", "")

        # If stored rate is 0, resolve from profile
        missing_rate = False
        rate_source = "work_session"
        if rate == 0 and wid:
            if wid not in rate_cache:
                rate_cache[wid] = await resolve_worker_hourly_rate(wid, org_id)
            resolved = rate_cache[wid]
            rate = resolved["rate"]
            missing_rate = resolved["missing_rate"]
            rate_source = resolved["source"]

        clean = round(hours * rate, 2) if rate > 0 else s.get("labor_cost", 0)
        oh_amount = round(hours * overhead_hourly, 2)

        # Get report info
        rid = s.get("approved_report_id")
        slip = None
        approved_by = None
        payroll_ready = False
        if rid:
            rep = await db.employee_daily_reports.find_one(
                {"id": rid}, {"_id": 0, "slip_number": 1, "approved_by": 1, "payroll_ready": 1}
            )
            if rep:
                slip = rep.get("slip_number")
                approved_by = rep.get("approved_by")
                payroll_ready = rep.get("payroll_ready", False)

        entries.append({
            "id": s.get("id"),
            "worker_id": wid,
            "worker_name": s.get("worker_name", ""),
            "project_id": project_id,
            "report_date": s.get("started_at", "")[:10],
            "smr_type": s.get("smr_type_id", ""),
            "hours": round(hours, 2),
            "hourly_rate": rate,
            "approval_status": "approved",
            "amount_clean_labor": round(clean, 2),
            "amount_overhead": oh_amount,
            "amount_labor_with_overhead": round(clean + oh_amount, 2),
            "slip_number": slip,
            "created_by": None,
            "approved_by": approved_by,
            "payroll_ready": payroll_ready,
            "source": "work_sessions",
            "missing_rate": missing_rate,
            "rate_source": rate_source,
        })

    # ── PROJECTION 1: Activities ────────────────────────────────
    # Test/dev noise filter
    NOISE_PREFIXES = ("test_", "тест_", "dummy", "sample", "tmp_")
    def _is_noise(name):
        return name.lower().strip().startswith(NOISE_PREFIXES) if name else True

    budgets = await db.activity_budgets.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0}
    ).to_list(200)

    # Extra activities from missing_smr
    extras = await db.missing_smr.find(
        {"org_id": org_id, "project_id": project_id,
         "status": {"$nin": ["closed", "rejected_by_client"]}},
        {"_id": 0, "smr_type": 1, "activity_type": 1, "qty": 1, "unit": 1},
    ).to_list(200)

    by_smr = defaultdict(lambda: {
        "draft_hours": 0, "approved_hours": 0,
        "draft_clean": 0, "approved_clean": 0,
        "draft_oh": 0, "approved_oh": 0,
        "has_missing_rate": False,
    })
    for e in entries:
        key = (e["smr_type"] or "").lower().strip()
        if not key:
            continue
        if e["approval_status"] == "draft":
            by_smr[key]["draft_hours"] += e["hours"]
            by_smr[key]["draft_clean"] += e["amount_clean_labor"]
            by_smr[key]["draft_oh"] += e["amount_overhead"]
        else:
            by_smr[key]["approved_hours"] += e["hours"]
            by_smr[key]["approved_clean"] += e["amount_clean_labor"]
            by_smr[key]["approved_oh"] += e["amount_overhead"]
        if e.get("missing_rate"):
            by_smr[key]["has_missing_rate"] = True

    activities = []
    seen = set()
    for b in budgets:
        name = b.get("subtype") or b.get("type", "")
        if _is_noise(name):
            continue
        key = name.lower().strip()
        seen.add(key)
        lb = b.get("labor_budget", 0)
        mb = b.get("materials_budget", 0)
        planned = b.get("planned_man_hours")
        if planned is None:
            r = calculate_budget_formula_sync(lb, b.get("coefficient", 1), b.get("avg_daily_wage_at_calc") or 200)
            planned = r["planned_man_hours"]

        smr = by_smr.get(key, by_smr.get(b.get("type", "").lower().strip(), {}))
        dh = round(smr.get("draft_hours", 0), 1)
        ah = round(smr.get("approved_hours", 0), 1)
        total_h = round(dh + ah, 1)
        burn_approved = round(ah / planned * 100, 1) if planned > 0 else 0
        burn_total = round(total_h / planned * 100, 1) if planned > 0 else 0
        status = "green" if burn_total < 80 else ("yellow" if burn_total <= 100 else "red")

        # Include BOTH draft AND approved costs
        total_clean = round(smr.get("draft_clean", 0) + smr.get("approved_clean", 0), 2)
        total_oh = round(smr.get("draft_oh", 0) + smr.get("approved_oh", 0), 2)

        activities.append({
            "category": b.get("type", ""),
            "activity_name": name,
            "unit": "m2",
            "qty": 0,
            "material_budget": round(mb, 2),
            "labor_budget": round(lb, 2),
            "total_budget": round(mb + lb, 2),
            "planned_hours": round(planned, 1),
            "draft_hours": dh,
            "approved_hours": ah,
            "total_reported_hours": total_h,
            "clean_labor_cost": total_clean,
            "labor_cost_with_overhead": round(total_clean + total_oh, 2),
            "subcontractor_price": None,
            "burn_pct_approved": burn_approved,
            "burn_pct_total": burn_total,
            "risk_status": status,
            "is_extra": False,
            "source": "budget",
            "has_missing_rate": smr.get("has_missing_rate", False),
        })

    for ex in extras:
        name = ex.get("smr_type") or ex.get("activity_type", "")
        if _is_noise(name):
            continue
        key = name.lower().strip()
        if key in seen:
            continue
        seen.add(key)
        smr = by_smr.get(key, {})
        dh = round(smr.get("draft_hours", 0), 1)
        ah = round(smr.get("approved_hours", 0), 1)
        total_clean = round(smr.get("draft_clean", 0) + smr.get("approved_clean", 0), 2)
        total_oh = round(smr.get("draft_oh", 0) + smr.get("approved_oh", 0), 2)
        activities.append({
            "category": "Допълнителни",
            "activity_name": name,
            "unit": ex.get("unit", ""),
            "qty": ex.get("qty", 0),
            "material_budget": 0, "labor_budget": 0, "total_budget": 0,
            "planned_hours": 0, "draft_hours": dh, "approved_hours": ah,
            "total_reported_hours": round(dh + ah, 1),
            "clean_labor_cost": total_clean,
            "labor_cost_with_overhead": round(total_clean + total_oh, 2),
            "subcontractor_price": None,
            "burn_pct_approved": 0, "burn_pct_total": 0,
            "risk_status": "yellow" if (dh + ah) > 0 else "green",
            "is_extra": True, "source": "missing_smr",
            "has_missing_rate": smr.get("has_missing_rate", False),
        })

    # ── PROJECTION 2: Personnel ─────────────────────────────────
    by_worker = defaultdict(lambda: {
        "draft_count": 0, "approved_count": 0,
        "clean_amount": 0, "overhead_amount": 0, "total_hours": 0,
        "missing_rate": False, "rate_source": "",
    })
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_workers = set()

    for e in entries:
        wid = e["worker_id"]
        if not wid:
            continue
        if e["approval_status"] == "draft":
            by_worker[wid]["draft_count"] += 1
        else:
            by_worker[wid]["approved_count"] += 1
        by_worker[wid]["clean_amount"] += e["amount_clean_labor"]
        by_worker[wid]["overhead_amount"] += e["amount_overhead"]
        by_worker[wid]["total_hours"] += e["hours"]
        by_worker[wid]["name"] = e["worker_name"]
        if e.get("missing_rate"):
            by_worker[wid]["missing_rate"] = True
        if e.get("rate_source"):
            by_worker[wid]["rate_source"] = e["rate_source"]
        if e["report_date"] == today:
            today_workers.add(wid)

    personnel = []
    for wid, w in by_worker.items():
        personnel.append({
            "worker_id": wid,
            "worker_name": w["name"],
            "today_present": wid in today_workers,
            "draft_reports_count": w["draft_count"],
            "approved_reports_count": w["approved_count"],
            "total_hours": round(w["total_hours"], 1),
            "clean_amount": round(w["clean_amount"], 2),
            "overhead_amount": round(w["overhead_amount"], 2),
            "total_amount": round(w["clean_amount"] + w["overhead_amount"], 2),
            "missing_rate": w["missing_rate"],
            "rate_source": w["rate_source"],
        })
    personnel.sort(key=lambda x: x["total_hours"], reverse=True)

    # ── PROJECTION 3: Finance ───────────────────────────────────
    total_clean = round(sum(e["amount_clean_labor"] for e in entries if e["approval_status"] == "approved"), 2)
    total_oh = round(sum(e["amount_overhead"] for e in entries if e["approval_status"] == "approved"), 2)
    total_labor_with_oh = round(total_clean + total_oh, 2)
    # Include draft amounts as separate line for visibility
    draft_clean = round(sum(e["amount_clean_labor"] for e in entries if e["approval_status"] == "draft"), 2)
    draft_oh = round(sum(e["amount_overhead"] for e in entries if e["approval_status"] == "draft"), 2)

    # Materials from warehouse
    issues = await db.warehouse_transactions.find(
        {"org_id": org_id, "project_id": project_id, "type": "issue"}, {"_id": 0, "lines": 1}
    ).to_list(200)
    total_materials = 0
    for t in issues:
        for ln in t.get("lines", []):
            total_materials += float(ln.get("unit_cost", 0)) * float(ln.get("qty_issued", 0))
    total_materials = round(total_materials, 2)

    # Revenue from invoices
    invoices = await db.invoices.find(
        {"org_id": org_id, "project_id": project_id},
        {"_id": 0, "total": 1, "paid_amount": 1, "status": 1},
    ).to_list(200)
    total_revenue = round(sum(i.get("total", 0) for i in invoices if i.get("status") in ["Sent", "Paid", "PartiallyPaid"]), 2)

    total_expense = round(total_labor_with_oh + total_materials, 2)
    balance = round(total_revenue - total_expense, 2)
    margin = round(balance / total_revenue * 100, 1) if total_revenue > 0 else 0

    finance = {
        "total_clean_labor": total_clean,
        "total_overhead": total_oh,
        "total_labor_with_overhead": total_labor_with_oh,
        "draft_clean_labor": draft_clean,
        "draft_overhead": draft_oh,
        "total_materials": total_materials,
        "total_expense": total_expense,
        "total_revenue": total_revenue,
        "balance": balance,
        "margin_pct": margin,
        "missing_rate_count": sum(1 for e in entries if e.get("missing_rate")),
    }

    return {
        "project_id": project_id,
        "entries_count": len(entries),
        "overhead_hourly_rate": overhead_hourly,
        "activities": activities,
        "personnel": personnel,
        "finance": finance,
    }
