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
from app.tenancy.data_access import TenantData


async def get_overhead_rate(org_id: str) -> float:
    """Get current overhead per person per day."""
    try:
        from app.services.overhead_realtime import compute_realtime_overhead
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        oh = await compute_realtime_overhead(org_id, month)
        return oh.get("overhead_per_person_day", 0)
    except Exception:
        return 0


async def build_centralized_reports(org_id: str, project_id: str, *,
                                    with_entries: bool = False) -> dict:
    """
    Build unified reports from:
    - employee_daily_reports (Draft/Submitted entries)
    - project_labor_cost (R62: approved report lines + Owner-approved manual rows — the cost)
    Returns: unified entries list + three projections.
    """
    tenant = TenantData.for_resolved_org(db, org_id)
    overhead_rate = await get_overhead_rate(org_id)
    overhead_hourly = round(overhead_rate / 8, 2) if overhead_rate > 0 else 0

    # ── Collect all report entries ──────────────────────────────
    entries = []

    # A) Draft/Submitted entries from employee_daily_reports
    drafts = await tenant.employee_daily_reports.find(
        {"org_id": org_id, "project_id": project_id,
         "status": {"$in": ["Draft", "Submitted", "SUBMITTED"]}},
        {"_id": 0},
    ).to_list(2000)

    # R62 (FG-421): a draft / submitted (not approved) report is LISTED for visibility but
    # never counts — no rate, no money. The money is THE labor cost below.
    for d in drafts:
        hours = d.get("hours") or d.get("hours_worked", 0)
        entries.append({
            "id": d.get("id"),
            "worker_id": d.get("worker_id", ""),
            "worker_name": d.get("worker_name", ""),
            "project_id": project_id,
            "report_date": d.get("date", ""),
            "smr_type": d.get("smr_type") or d.get("activity_type", ""),
            "hours": round(hours, 2),
            "hourly_rate": None,
            "approval_status": "draft",
            "amount_clean_labor": 0.0,
            "amount_overhead": 0.0,
            "amount_labor_with_overhead": 0.0,
            "counted": False,
            "not_counted_reason": "R62: неодобрен отчет не влиза в разхода",
            "slip_number": d.get("slip_number"),
            "created_by": d.get("submitted_by") or d.get("created_by"),
            "approved_by": None,
            "payroll_ready": False,
            "source": "employee_daily_reports",
            "missing_rate": False,
            "rate_source": None,
        })

    # B) Approved entries — R62 (FG-421): THE labor cost's lines (approved reports priced by
    # the one labor calculation + Owner-approved manual rows), not the work_sessions
    from app.services.labor_cost import project_labor_cost
    lc = await project_labor_cost(org_id, project_id)
    names = {}
    wids = sorted({r.get("worker_id") for r in lc["lines"] if r.get("worker_id")})
    if wids:
        for u in await tenant.users.find({"org_id": org_id, "id": {"$in": wids}},
                                         {"_id": 0, "id": 1, "first_name": 1, "last_name": 1}).to_list(len(wids)):
            names[u["id"]] = f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
    for rec in lc["lines"]:
        hours = float(rec.get("hours") or 0)
        clean = round(float(rec.get("amount") or 0), 2)
        oh_amount = round(hours * overhead_hourly, 2)
        rid = str(rec.get("report_id") or "")
        doc_id = rid.split("_")[0] if rid and not rid.startswith("manual:") else None
        rep = None
        if doc_id:
            rep = await tenant.employee_daily_reports.find_one(
                {"id": doc_id}, {"_id": 0, "slip_number": 1, "approved_by": 1, "payroll_ready": 1,
                                 "submitted_by": 1})
        entries.append({
            "id": rid,
            "worker_id": rec.get("worker_id"),
            "worker_name": names.get(rec.get("worker_id"), ""),
            "project_id": project_id,
            "report_date": rec.get("date", ""),
            "smr_type": rec.get("smr_type", ""),
            "hours": round(hours, 2),
            "hourly_rate": rec.get("rate"),
            "approval_status": "approved",
            "amount_clean_labor": clean,
            "amount_overhead": oh_amount,
            "amount_labor_with_overhead": round(clean + oh_amount, 2),
            "counted": True,
            "cost_type": rec.get("cost_type"),
            "slip_number": (rep or {}).get("slip_number"),
            "created_by": (rep or {}).get("submitted_by"),
            "approved_by": (rep or {}).get("approved_by"),
            "payroll_ready": (rep or {}).get("payroll_ready", False),
            "source": "project_labor_cost",
            "missing_rate": "MISSING_RATE" in (rec.get("dq") or []),
            "rate_source": rec.get("pay_type_source"),
        })

    # ── PROJECTION 1: Activities ────────────────────────────────
    # Test/dev noise filter
    NOISE_PREFIXES = ("test_", "тест_", "dummy", "sample", "tmp_")
    def _is_noise(name):
        return name.lower().strip().startswith(NOISE_PREFIXES) if name else True

    budgets = await tenant.activity_budgets.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0}
    ).to_list(200)

    # Extra activities from missing_smr
    extras = await tenant.missing_smr.find(
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
        # FG-460: an entry with no SMR is kept (key "") — it becomes the "Без СМР" row, so
        # the activity parts add up to the report total
        key = (e["smr_type"] or "").lower().strip()
        by_smr[key].setdefault("label", e["smr_type"] or "")
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
    used = set()       # FG-460: the by_smr keys a row already shows
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

        tkey = b.get("type", "").lower().strip()
        smr_key = key if key in by_smr else (tkey if tkey in by_smr else None)
        if smr_key in used:
            smr_key = None          # one SMR's hours / cost are shown once
        smr = by_smr.get(smr_key, {}) if smr_key is not None else {}
        if smr_key is not None:
            used.add(smr_key)
        dh = round(smr.get("draft_hours", 0), 1)
        ah = round(smr.get("approved_hours", 0), 1)
        total_h = round(dh + ah, 1)
        burn_approved = round(ah / planned * 100, 1) if planned > 0 else 0
        burn_total = round(total_h / planned * 100, 1) if planned > 0 else 0
        status = "green" if burn_total < 80 else ("yellow" if burn_total <= 100 else "red")

        # R62: drafts carry 0 — the cost is the approved (counted) labor only
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
        smr = by_smr.get(key, {}) if key not in used else {}
        if key in by_smr:
            used.add(key)
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

    # FG-460 (R62): an SMR with labor but no budget row (or no SMR at all, e.g. an approved
    # manual row) is listed as "без бюджет" — never dropped, so the activities add up to
    # the report's labor total.
    for key in sorted(k for k in by_smr if k not in used):
        smr = by_smr[key]
        dh = round(smr.get("draft_hours", 0), 1)
        ah = round(smr.get("approved_hours", 0), 1)
        total_clean = round(smr.get("draft_clean", 0) + smr.get("approved_clean", 0), 2)
        total_oh = round(smr.get("draft_oh", 0) + smr.get("approved_oh", 0), 2)
        if not (dh or ah or total_clean or total_oh):
            continue
        activities.append({
            "category": "Без бюджет",
            "activity_name": smr.get("label") or "Без СМР",
            "unit": "", "qty": 0,
            "material_budget": 0, "labor_budget": 0, "total_budget": 0,
            "planned_hours": 0, "draft_hours": dh, "approved_hours": ah,
            "total_reported_hours": round(dh + ah, 1),
            "clean_labor_cost": total_clean,
            "labor_cost_with_overhead": round(total_clean + total_oh, 2),
            "subcontractor_price": None,
            "burn_pct_approved": 0, "burn_pct_total": 0,
            "risk_status": "yellow" if (dh + ah) > 0 else "green",
            "is_extra": False, "source": "labor_without_budget", "without_budget": True,
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

    # Materials — 5C-C22: the ONE shared helper (canonical consumption +
    # „фира" + legacy issues dated before the tenant cutover, Р13).
    from app.services.canonical_material_cost import project_material_cost, cost_basis
    _mat = await project_material_cost(tenant, org_id, project_id)
    total_materials = _mat["total_cost"]

    # R86 (FG-565): revenue = the payments RECEIVED (FLOW-006 ledger), net — the one shared
    # rule of the project P&L; the invoiced amount is shown apart
    from app.services.project_pnl import received_revenue
    rec = await received_revenue(tenant, org_id, [project_id])
    total_revenue = rec["received_net"]

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
        "material_waste": _mat["waste_cost"],         # „фира", part of total_materials
        "material_cost_basis": cost_basis(_mat),
        "total_expense": total_expense,
        "total_revenue": total_revenue,
        "revenue_basis": rec["revenue_basis"],
        "invoiced_net": rec["invoiced_net"],
        "awaiting_payment_net": rec["awaiting_payment_net"],
        "balance": balance,
        "margin_pct": margin,
        "missing_rate_count": sum(1 for e in entries if e.get("missing_rate")),
    }

    out = {
        "project_id": project_id,
        "entries_count": len(entries),
        "overhead_hourly_rate": overhead_hourly,
        "activities": activities,
        "personnel": personnel,
        "finance": finance,
    }
    if with_entries:
        # SEC-02-F (FG-74): the per-worker pay behind the "spent" figures, for the R31
        # count of paid workers (app.permissions.money_write.project_labor_workers).
        # Never part of an API response.
        out["entries"] = entries
    return out
