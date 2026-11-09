"""
Routes - Labor by SMR / Execution Package.
Phase 1: Time entry linkage to execution packages
Phase 2: Planned hours engine
Phase 3: Actual labor cost by execution package
Phase 4: Variance + progress + warnings
Phase 5: Project/profit integration
"""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from typing import Optional
from datetime import datetime, timezone
import uuid

from app.db import db
from app.tenancy.data_access import TenantData
from app.tenancy.settings_identity import WORKER_RATES, settings_id
from app.deps.auth import get_current_user
from app.deps.modules import require_m2
from app.permissions.money_write import (require_field_cost_write, require_finance_read, money_values_visible, without_keys, strip_money_for_non_finance,
                                         require_money_write, audit_money_write)
from app.permissions.finance_read import LABOR_MONEY_FIELDS
from app.permissions.money_input import (MoneyWrite, money_value, project_in_tenant,  # SEC-01-C03
                                         labor_money_visible, without_labor_money)
from app.services.labor_cost import (compute_person_labor, load_smr_terms, project_labor_cost,
                                     package_labor_split, MANUAL_APPROVED, MANUAL_PENDING, SYNC_SOURCE)
from app.services.report_normalizer import LABOR_LINE_FIELDS


def _tenant(user: dict) -> TenantData:
    """The request's tenant — from the server-loaded session user only (W0-03E-A2C)."""
    return TenantData.for_user(db, user)


# SEC-01-C02 (FG-26): a labor row that is neither a reversal nor reversed. Sums need no
# filter (a reversal carries the negative hours/cost); counts use this.
ACTIVE_LABOR_ROW = {"entry_kind": {"$ne": "reversal"}, "reversed_by_entry_id": None}


def _sync_fingerprint(row: dict) -> tuple:
    """What makes two synced labor rows the same row (SEC-01-C02, FG-26)."""
    cost = row.get("labor_cost")
    rate = row.get("hourly_rate")
    return (row.get("work_report_id"), row.get("employee_id"), row.get("date", ""),
            round(float(row.get("hours", 0) or 0), 4), row.get("activity_name", ""),
            row.get("note", ""), row.get("execution_package_id"), row.get("offer_line_id"),
            None if rate is None else round(float(rate), 4),
            None if cost is None else round(float(cost), 2))


def _pricing_basis(row: dict) -> tuple:
    """LAB-01: the pricing basis of a synced row — a changed approved quantity / piece rate /
    cost type is a different row (reversal + new row), never an in-place edit."""
    q, pr = row.get("approved_quantity"), row.get("piece_rate")
    return (row.get("cost_type"), row.get("pay_type"),
            None if q is None else round(float(q), 4), None if pr is None else round(float(pr), 4))


def _same_synced_row(old: dict, new: dict) -> bool:
    """Same fingerprint (hours, rate, cost …) and — when the stored row was priced by LAB-01 —
    the same pricing basis. A row synced before LAB-01 (no ``labor_calc``) with the same
    hours, rate and cost is the same row: nothing changed in money, nothing is written."""
    if _sync_fingerprint(old) != _sync_fingerprint(new):
        return False
    return not old.get("labor_calc") or _pricing_basis(old) == _pricing_basis(new)

router = APIRouter(tags=["Labor by SMR"])


# ═══════════════════════════════════════════════════════════════════
# PHASE 1 — TIME ENTRY LINKAGE
# ═══════════════════════════════════════════════════════════════════

@router.post("/labor-entries", status_code=201)
async def create_labor_entry(
    data: dict,
    request: Request,
    _sec01: dict = Depends(require_field_cost_write(
        "labor.entry.create", module="M2", resource_type="labor_entry",
        project_from="body")),  # SEC-01 + C01 (R16): before any read/write
    user: dict = Depends(require_m2),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """Create a labor time entry linked to an execution package"""
    tenant = _tenant(user)
    org_id = user["org_id"]
    hours = money_value(data.get("hours"), "hours", places=None)  # SEC-01-C03: finite > 0, else 422 before any write
    await project_in_tenant(tenant, data.get("project_id"))  # SEC-01-C03-B (FG-29)
    now = datetime.now(timezone.utc).isoformat()

    entry = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "project_id": data.get("project_id"),
        "employee_id": data.get("employee_id", user["id"]),
        "execution_package_id": data.get("execution_package_id"),
        "offer_line_id": data.get("offer_line_id"),
        "work_report_id": data.get("work_report_id"),
        "date": data.get("date", now[:10]),
        "hours": hours,
        "activity_name": data.get("activity_name", ""),
        "note": data.get("note", ""),
        "hourly_rate": None,  # populated by aggregator
        "labor_cost": None,
        "source": data.get("source", "manual"),
        # R62 / FG-58: a manual labor row counts in the project's labor cost only after
        # the Owner approved it (POST /labor-entries/{id}/approve)
        "approval_status": MANUAL_PENDING,
        "created_by": user["id"],
        "created_at": now,
    }
    if entry["source"] == SYNC_SOURCE:
        # the synced rows are a projection of approved work reports — only the sync writes them
        raise HTTPException(status_code=422, detail=(
            "Източник „work_report_sync“ се записва само от синхронизацията на одобрени отчети"))

    # Resolve hourly rate
    profile = await tenant.employee_profiles.find_one({"org_id": org_id, "user_id": entry["employee_id"]}, {"_id": 0, "hourly_rate": 1})
    if profile and profile.get("hourly_rate"):
        entry["hourly_rate"] = profile["hourly_rate"]
        entry["labor_cost"] = round(entry["hours"] * profile["hourly_rate"], 2)

    mw = await MoneyWrite.begin(user, "labor.entry.create", idempotency_key, data)
    # SEC-01-C03-B (FG-15): the stored row keeps the rate and cost; neither the response nor
    # a replay shows them to a caller without the finance right (an R16 member).
    show_money = await labor_money_visible(request, user)
    if mw.replay_id:
        replay = await tenant.labor_entries.find_one({"id": mw.replay_id}, {"_id": 0})
        return replay if show_money else without_labor_money(replay)
    entry["id"] = mw.new_id("labor_entry")
    async with mw:
        async with mw.insert_once():
            await tenant.labor_entries.insert_one(mw.unique(entry))
        mw.result_id = entry["id"]
    out = {k: v for k, v in entry.items() if k != "_id"}
    return out if show_money else without_labor_money(out)


# R62 / FG-58 (Krum 09.11.2026): only the Owner approves a manual labor row.
MANUAL_ROW_APPROVE_ACTION = "labor.manual_entry.approve"


@router.post("/labor-entries/{entry_id}/approve")
async def approve_manual_labor_entry(
    entry_id: str,
    request: Request,
    _owner: dict = Depends(require_money_write(
        MANUAL_ROW_APPROVE_ACTION, module="M2", resource_type="labor_entry",
        roles=("Owner",))),   # R62: Owner only (off/shadow: the legacy role; enforce: the action)
    user: dict = Depends(require_m2),
):
    """R62 / FG-58: the Owner approves a manual labor row; from then on it counts in THE
    project labor cost (``project_labor_cost``). Once only: a second approval → 409. A
    synced or reversal row is not a manual row → 409. Canonical AuditEvent (before/after)."""
    tenant = _tenant(user)
    org_id = user["org_id"]
    row = await tenant.labor_entries.find_one({"org_id": org_id, "id": entry_id}, {"_id": 0})
    if not row:
        raise HTTPException(status_code=404, detail="Редът за труд не е намерен")
    if row.get("source") == SYNC_SOURCE or row.get("entry_kind") == "reversal" or row.get("reversed_by_entry_id"):
        raise HTTPException(status_code=409, detail=(
            "Това не е активен ръчен ред — редовете от одобрени отчети не се одобряват отделно"))
    now = datetime.now(timezone.utc).isoformat()
    res = await tenant.labor_entries.update_one(
        {"org_id": org_id, "id": entry_id, "approval_status": {"$ne": MANUAL_APPROVED}},
        {"$set": {"approval_status": MANUAL_APPROVED, "approved_by": user["id"], "approved_at": now}})
    if not getattr(res, "modified_count", 0):
        raise HTTPException(status_code=409, detail={"code": "ALREADY_APPROVED",
                                                     "message": "Редът вече е одобрен"})
    await audit_money_write(
        request, user, action=MANUAL_ROW_APPROVE_ACTION, source_flow="FLOW-028",
        entity_type="labor_entry", entity_id=entry_id,
        before={"approval_status": row.get("approval_status")},
        after={"approval_status": MANUAL_APPROVED, "approved_by": user["id"]},
        scope_type="project", scope_id=row.get("project_id"),
        reason="R62: manual labor row approved by the Owner — counts in the project labor cost")
    return await tenant.labor_entries.find_one({"org_id": org_id, "id": entry_id}, {"_id": 0})


@router.post("/labor-entries/sync-from-work-reports")
async def sync_labor_entries_from_work_reports(
    data: dict,
    _sec01: dict = Depends(require_field_cost_write(
        "labor.work_report_sync.execute", module="M2", resource_type="labor_entry",
        project_from="body")),  # SEC-01-C01 (R16): before any read/write
    user: dict = Depends(require_m2),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """SEC-01-C03-C (F-69-02, R29): key required (428); the inputs are fingerprinted and a
    repeat of the key returns the stored answer, without running the sync again."""
    mw = await MoneyWrite.begin(user, "labor.work_report_sync.execute", idempotency_key, data)
    if mw.replay_id:
        return mw.replay_payload()
    async with mw:
        mw.result_payload = await _sync_labor_entries(data, user)
    return mw.result_payload


async def _sync_labor_entries(data: dict, user: dict) -> dict:
    """Sync labor entries from existing work reports for a project, with optional execution package mapping"""
    tenant = _tenant(user)
    org_id = user["org_id"]
    project_id = data.get("project_id")
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id required")

    # Load execution packages for name-based mapping
    exec_pkgs = await tenant.execution_packages.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0, "id": 1, "activity_name": 1, "offer_line_id": 1}
    ).to_list(200)
    pkg_by_name = {}
    for ep in exec_pkgs:
        name = (ep.get("activity_name") or "").lower().strip()
        if name:
            pkg_by_name[name] = ep

    # LAB-01 (FG-51, FLOW-019/028): ONLY approved work reports; every line priced by the
    # one labor calculation (salary → approved hours × rate, akord → approved quantity ×
    # piece rate, DOWNTIME apart). No rate → labor_cost None + DQ, never a default.
    reports = await tenant.work_reports.find(
        {"org_id": org_id, "project_id": project_id,
         "status": {"$in": ["Approved", "APPROVED", "approved"]}}, {"_id": 0}
    ).to_list(1000)
    worker_ids = sorted({wr.get("user_id") for wr in reports if wr.get("user_id")})
    profiles = await tenant.employee_profiles.find(
        {"org_id": org_id, "user_id": {"$in": worker_ids}}, {"_id": 0}).to_list(len(worker_ids) or 1)
    prof_map = {p["user_id"]: p for p in profiles}

    # normalized lines per worker (the shape app.services.labor_cost reads)
    by_worker = {}
    for wr in reports:
        for i, line in enumerate(wr.get("lines", [])):
            hours = float(line.get("hours", 0) or 0)
            if hours <= 0 and line.get("quantity") in (None, ""):
                continue
            act_name = line.get("activity_name", "")
            matched_pkg = pkg_by_name.get(act_name.lower().strip())
            nl = {
                "id": f"{wr['id']}:{i}", "worker_id": wr["user_id"], "date": wr.get("date", ""),
                "project_id": project_id, "smr_type": act_name, "hours": hours,
                "status": "APPROVED", "note": line.get("note", ""),
                "execution_package_id": line.get("execution_package_id") or (matched_pkg or {}).get("id"),
                "offer_line_id": (matched_pkg or {}).get("offer_line_id"),
                "work_report_id": wr["id"],
                # LAB-01-D (FG-72): what a labor approval binds to
                "report_doc_id": wr["id"],
                "entry_id": str(line.get("id") or i),
                "report_version": int(wr.get("report_version") or 0),
            }
            for k in LABOR_LINE_FIELDS:
                if k != "execution_package_id":
                    nl[k] = line.get(k)
            by_worker.setdefault(wr["user_id"], []).append(nl)

    smr_terms = await load_smr_terms(
        tenant, org_id, [nl for ls in by_worker.values() for nl in ls])

    # SEC-01-C02 (FG-26; CLAUDE.md §2.9, §7): NO delete. Labor rows are the basis of
    # pay (FLOW-028), so a re-sync never removes or edits one. It compares the rows the
    # approved work reports give NOW (priced by LAB-01) with the active synced rows:
    #   same row (fingerprint, pricing basis included) -> kept as it is;
    #   row no longer given     -> a REVERSAL row (negative hours/cost, same date and
    #                              package) is appended and the original is marked
    #                              reversed_by_entry_id — every sum stays correct;
    #   new row                 -> inserted.
    # A re-sync with no change writes nothing (idempotent by content).
    now = datetime.now(timezone.utc).isoformat()
    dq_warnings = []

    desired = []
    for uid, lines in by_worker.items():
        lc = compute_person_labor(prof_map.get(uid, {}), lines, smr_terms)
        src = {nl["id"]: nl for nl in lines}
        dq_warnings.extend(lc["dq_warnings"])
        for rec in lc["lines"]:
            nl = src[rec["report_id"]]
            ep_id = nl["execution_package_id"]
            priced = not rec["dq"] or rec["dq"] == ["DOWNTIME_UNCLASSIFIED"]
            desired.append({
                "id": str(uuid.uuid4()),
                "org_id": org_id,
                "project_id": project_id,
                "employee_id": uid,
                "execution_package_id": ep_id,
                "offer_line_id": nl["offer_line_id"],
                "work_report_id": nl["work_report_id"],
                "date": nl["date"],
                "hours": rec["hours"],
                "activity_name": nl["smr_type"],
                "note": nl["note"],
                "cost_type": rec["cost_type"],
                "pay_type": rec["pay_type"],
                "pay_type_source": rec["pay_type_source"],
                "approved_quantity": rec["approved_quantity"],
                "piece_rate": rec["piece_rate"],
                "hourly_rate": rec["rate"] if rec["pay_type"] != "Akord" and priced else None,
                "labor_cost": rec["amount"] if priced else None,
                "labor_formula": rec["formula"],
                "dq_warnings": rec["dq"],
                "labor_calc": "LAB-01",
                "source": "work_report_sync",
                "mapped": ep_id is not None,
                "created_at": now,
            })

    active = await tenant.labor_entries.find(
        {"org_id": org_id, "project_id": project_id, "source": "work_report_sync",
         "entry_kind": {"$ne": "reversal"}, "reversed_by_entry_id": None},
        {"_id": 0}).to_list(10000)
    pool = {}
    for row in active:
        pool.setdefault(_sync_fingerprint(row), []).append(row)

    created = unchanged = 0
    for entry in desired:
        same = pool.get(_sync_fingerprint(entry)) or []
        match = next((i for i, old in enumerate(same) if _same_synced_row(old, entry)), None)
        if match is not None:
            same.pop(match)
            unchanged += 1
            continue
        await tenant.labor_entries.insert_one(entry)
        created += 1

    reversed_count = 0
    for rows in pool.values():
        for old in rows:
            reversal = {
                "id": str(uuid.uuid4()), "org_id": org_id, "project_id": project_id,
                "employee_id": old.get("employee_id"),
                "execution_package_id": old.get("execution_package_id"),
                "offer_line_id": old.get("offer_line_id"),
                "work_report_id": old.get("work_report_id"),
                "date": old.get("date", ""),
                "hours": -float(old.get("hours", 0) or 0),
                "activity_name": old.get("activity_name", ""),
                "note": "Сторно при повторна синхронизация",
                "hourly_rate": old.get("hourly_rate"),
                "labor_cost": (-float(old["labor_cost"]) if old.get("labor_cost") is not None
                               else None),
                # LAB-01: the reversed row's pricing basis, the quantity negated
                "cost_type": old.get("cost_type"), "pay_type": old.get("pay_type"),
                "piece_rate": old.get("piece_rate"),
                "approved_quantity": (-float(old["approved_quantity"])
                                      if old.get("approved_quantity") is not None else None),
                "labor_calc": old.get("labor_calc"),
                "source": "work_report_sync", "entry_kind": "reversal",
                "reverses_entry_id": old["id"], "mapped": old.get("mapped", False),
                "created_by": user["id"], "created_at": now,
            }
            await tenant.labor_entries.insert_one(reversal)
            await tenant.labor_entries.update_one(
                {"id": old["id"], "org_id": org_id, "reversed_by_entry_id": None},
                {"$set": {"reversed_by_entry_id": reversal["id"], "reversed_at": now}})
            reversed_count += 1

    return {"ok": True, "synced": created, "unchanged": unchanged,
            "reversed": reversed_count, "project_id": project_id, "dq_warnings": dq_warnings}


@router.get("/labor-entries")
async def list_labor_entries(
    request: Request,
    project_id: Optional[str] = None,
    execution_package_id: Optional[str] = None,
    employee_id: Optional[str] = None,
    user: dict = Depends(require_m2),
):
    """SEC-02 (FG-1 GET; R20-5, R16, FLOW-037 §3.4).

    Finance roles: every row, with rate and cost (as before). Every other role: only the
    rows of projects they are a CURRENT member of (date-aware project_team membership,
    the same relation as R16), and never ``hourly_rate`` / ``labor_cost``. A project
    filter on a project they are not a member of is a 403.
    """
    tenant = _tenant(user)
    q = {"org_id": user["org_id"]}
    show_money = await money_values_visible(request, user)
    if not show_money:
        from app.tenancy import project_team
        team = project_team.tenant_for(db, user)
        if project_id:
            if not await project_team.is_member(team, user["id"], project_id):
                raise HTTPException(status_code=403, detail="Access denied")
        else:
            candidates = await project_team.assigned_project_ids(team, user["id"])
            current = [p for p in candidates
                       if await project_team.is_member(team, user["id"], p)]
            q["project_id"] = {"$in": current}
    if project_id: q["project_id"] = project_id
    if execution_package_id: q["execution_package_id"] = execution_package_id
    if employee_id: q["employee_id"] = employee_id
    entries = await tenant.labor_entries.find(q, {"_id": 0}).sort("date", -1).to_list(500)
    if not show_money:
        entries = without_keys(entries, LABOR_MONEY_FIELDS)
    return entries


# ═══════════════════════════════════════════════════════════════════
# PHASE 2 — PLANNED HOURS ENGINE
# ═══════════════════════════════════════════════════════════════════

@router.post("/execution-packages/recompute-labor/{project_id}")
async def recompute_execution_package_labor(
    project_id: str,
    _sec01: dict = Depends(require_field_cost_write(
        "labor.package_recompute.execute", module="M2", resource_type="execution_package",
        project_from="path")),  # SEC-01-C01 (R16): before any read/write
    user: dict = Depends(require_m2),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """SEC-01-C03-C (F-69-02, R29): key required (428); a repeat returns the stored answer."""
    mw = await MoneyWrite.begin(user, "labor.package_recompute.execute", idempotency_key,
                                {"project_id": project_id})
    if mw.replay_id:
        return mw.replay_payload()
    async with mw:
        mw.result_payload = await _recompute_package_labor(project_id, user)
    return mw.result_payload


async def _recompute_package_labor(project_id: str, user: dict) -> dict:
    """Recompute planned hours and labor budget for execution packages"""
    tenant = _tenant(user)
    org_id = user["org_id"]
    pkgs = await tenant.execution_packages.find({"org_id": org_id, "project_id": project_id}, {"_id": 0}).to_list(200)
    if not pkgs:
        return {"ok": True, "updated": 0}

    # Load offer lines for labor_hours_per_unit
    offer_ids = list(set(p.get("source_offer_id") for p in pkgs if p.get("source_offer_id")))
    offers = await tenant.offers.find({"id": {"$in": offer_ids}}, {"_id": 0, "lines": 1}).to_list(20)
    offer_line_map = {}
    for o in offers:
        for l in o.get("lines", []):
            if l.get("id"):
                offer_line_map[l["id"]] = l

    # Load org worker rates for estimation
    # W0-03E-A2C: per-tenant settings row id + tenant-scoped read.
    settings = await TenantData.for_resolved_org(db, org_id).settings.find_one(
        {"_id": settings_id(WORKER_RATES, org_id)})
    default_rate = 18  # EUR/h fallback

    # R62: used hours / actual labor cost per package from THE labor cost (approved reports
    # + Owner-approved manual rows), not from the raw labor_entries
    split = await package_labor_split(org_id, project_id)
    used_by_pkg = {k: v["hours"] + v["downtime_hours"] for k, v in split.items() if k}
    cost_by_pkg = {k: v["cost"] for k, v in split.items() if k}

    updated = 0
    for pkg in pkgs:
        ol = offer_line_map.get(pkg.get("offer_line_id"), {})
        labor_hours_per_unit = ol.get("labor_hours_per_unit")
        qty = pkg.get("qty", 0)

        # Planned hours
        if labor_hours_per_unit and labor_hours_per_unit > 0:
            planned_hours = round(qty * labor_hours_per_unit, 1)
            planned_hours_source = "offer_line"
        elif pkg.get("labor_budget_total", 0) > 0:
            # Estimate from budget: budget / default_rate
            planned_hours = round(pkg["labor_budget_total"] / default_rate, 1)
            planned_hours_source = "budget_estimate"
        else:
            planned_hours = None
            planned_hours_source = "unavailable"

        used_hours = round(used_by_pkg.get(pkg["id"], 0), 1)
        labor_actual_cost = round(cost_by_pkg.get(pkg["id"], 0), 2)

        remaining_hours = round(planned_hours - used_hours, 1) if planned_hours is not None else None
        progress_by_hours = round(used_hours / planned_hours * 100, 1) if planned_hours and planned_hours > 0 else None

        labor_budget = pkg.get("labor_budget_total", 0)
        labor_variance_value = round(labor_actual_cost - labor_budget, 2) if labor_budget > 0 else None
        labor_variance_percent = round(labor_variance_value / labor_budget * 100, 1) if labor_budget > 0 and labor_variance_value is not None else None

        update_fields = {
            "planned_hours": planned_hours,
            "planned_hours_source": planned_hours_source,
            "used_hours": used_hours,
            "remaining_hours": remaining_hours,
            "progress_percent_by_hours": progress_by_hours,
            "actual_labor_cost": labor_actual_cost,
            "labor_variance_value": labor_variance_value,
            "labor_variance_percent": labor_variance_percent,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await tenant.execution_packages.update_one({"id": pkg["id"]}, {"$set": update_fields})
        updated += 1

    return {"ok": True, "updated": updated}


# ═══════════════════════════════════════════════════════════════════
# PHASE 3 — ACTUAL LABOR COST BY EXECUTION PACKAGE
# ═══════════════════════════════════════════════════════════════════

@router.get("/labor-cost/by-execution-package/{pkg_id}")
async def get_labor_cost_by_exec_pkg(
    pkg_id: str,
    _sec02: dict = Depends(require_finance_read(
        "finance.package_labor_cost.read", module="M2", resource_type="package_labor_cost")),  # SEC-02 (R20-2): before any read
    user: dict = Depends(require_m2)):
    """Detailed labor cost breakdown for an execution package"""
    tenant = _tenant(user)
    org_id = user["org_id"]
    pkg = await tenant.execution_packages.find_one({"id": pkg_id, "org_id": org_id}, {"_id": 0})
    if not pkg:
        raise HTTPException(status_code=404, detail="Execution package not found")

    # R62: THE labor cost of the package's project, the package's lines only (approved
    # reports + Owner-approved manual rows) — not the raw labor_entries
    lc = await project_labor_cost(org_id, pkg.get("project_id")) if pkg.get("project_id") else {"lines": []}
    entries = [r for r in lc["lines"] if (r.get("execution_package_id") or "") == pkg_id]

    # Load employee names
    emp_ids = list(set(e.get("worker_id") for e in entries if e.get("worker_id")))
    users = await tenant.users.find({"id": {"$in": emp_ids}}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1}).to_list(50)
    name_map = {u["id"]: f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() for u in users}

    total_hours = 0
    total_cost = 0
    by_employee = {}
    by_date = {}
    partial_cost = False

    for e in entries:
        h = float(e.get("hours", 0) or 0)
        c = e.get("amount", 0) or 0
        total_hours += h
        total_cost += c
        if e.get("dq"):
            partial_cost = True

        uid = e.get("worker_id")
        if uid not in by_employee:
            by_employee[uid] = {"employee_id": uid, "name": name_map.get(uid, ""), "hours": 0, "cost": 0, "rate": e.get("rate")}
        by_employee[uid]["hours"] += h
        by_employee[uid]["cost"] += c

        d = e.get("date", "")
        if d not in by_date:
            by_date[d] = {"date": d, "hours": 0, "cost": 0}
        by_date[d]["hours"] += h
        by_date[d]["cost"] += c

    for v in by_employee.values():
        v["hours"] = round(v["hours"], 1)
        v["cost"] = round(v["cost"], 2)
    for v in by_date.values():
        v["hours"] = round(v["hours"], 1)
        v["cost"] = round(v["cost"], 2)

    return {
        "execution_package_id": pkg_id,
        "activity_name": pkg.get("activity_name", ""),
        "planned_hours": pkg.get("planned_hours"),
        "used_hours": round(total_hours, 1),
        "remaining_hours": round(pkg["planned_hours"] - total_hours, 1) if pkg.get("planned_hours") is not None else None,
        "labor_budget": pkg.get("labor_budget_total", 0),
        "labor_actual_cost": round(total_cost, 2),
        "labor_variance": round(total_cost - pkg.get("labor_budget_total", 0), 2) if pkg.get("labor_budget_total", 0) > 0 else None,
        "currency": "EUR",
        "entries_count": len(entries),
        "partial_cost_data": partial_cost,
        "by_employee": sorted(by_employee.values(), key=lambda x: x["cost"], reverse=True),
        "by_date": sorted(by_date.values(), key=lambda x: x["date"], reverse=True),
    }


# ═══════════════════════════════════════════════════════════════════
# PHASE 4 — VARIANCE + PROGRESS + WARNINGS
# ═══════════════════════════════════════════════════════════════════

@router.get("/labor-warnings/{project_id}")
@strip_money_for_non_finance   # SEC-02-B (R20-5M)
async def get_labor_warnings(project_id: str, request: Request,
                             user: dict = Depends(require_m2)):
    """Get labor warnings for all execution packages in a project"""
    # SEC-02-B (SEC02-1): the money is stripped by the decorator; a caller without the
    # finance right also needs a CURRENT membership of the project.
    if not await money_values_visible(request, user):
        from app.tenancy import project_team
        if not await project_team.is_member(project_team.tenant_for(db, user), user["id"],
                                            project_id):
            raise HTTPException(status_code=403, detail="Access denied")
    tenant = _tenant(user)
    org_id = user["org_id"]
    pkgs = await tenant.execution_packages.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0}
    ).to_list(200)

    # Count unmapped entries
    # SEC-01-C02: count the active rows only (a reversal and the row it reverses cancel out).
    unmapped = await tenant.labor_entries.count_documents(
        {"org_id": org_id, "project_id": project_id, "execution_package_id": None, **ACTIVE_LABOR_ROW}
    )
    total_entries = await tenant.labor_entries.count_documents(
        {"org_id": org_id, "project_id": project_id, **ACTIVE_LABOR_ROW}
    )

    warnings = []
    pkg_summaries = []
    labor_split = await package_labor_split(org_id, project_id)   # R62: THE labor cost, at read time

    for pkg in pkgs:
        planned = pkg.get("planned_hours")
        used = pkg.get("used_hours", 0)
        budget = pkg.get("labor_budget_total", 0)
        actual = (labor_split.get(pkg["id"]) or {}).get("cost", 0.0)
        name = pkg.get("activity_name", "")

        flags = []
        if planned is None:
            flags.append("missing_planned_hours")
        elif used > planned:
            flags.append("over_hours")
            warnings.append({"type": "over_hours", "package_id": pkg["id"], "activity": name,
                           "message": f"{name}: {used}h / {planned}h planned ({round(used - planned, 1)}h over)"})
        if budget > 0 and actual > budget:
            flags.append("over_labor_budget")
            warnings.append({"type": "over_labor_budget", "package_id": pkg["id"], "activity": name,
                           "message": f"{name}: {actual} EUR / {budget} EUR budget ({round(actual - budget, 2)} EUR over)"})

        pkg_summaries.append({
            "id": pkg["id"],
            "activity_name": name,
            "planned_hours": planned,
            "used_hours": used,
            "remaining_hours": pkg.get("remaining_hours"),
            "progress_by_hours": pkg.get("progress_percent_by_hours"),
            "labor_budget": budget,
            "labor_actual": actual,
            "variance_value": pkg.get("labor_variance_value"),
            "variance_percent": pkg.get("labor_variance_percent"),
            "flags": flags,
        })

    if unmapped > 0:
        warnings.append({"type": "unmapped_time_entries", "message": f"{unmapped} от {total_entries} записа за труд нямат връзка към СМР/пакет"})

    return {
        "project_id": project_id,
        "warnings": warnings,
        "packages": pkg_summaries,
        "total_entries": total_entries,
        "unmapped_entries": unmapped,
        "metrics_available": {
            "labor_entries": total_entries > 0,
            "execution_packages": len(pkgs) > 0,
            "planned_hours": any(p.get("planned_hours") is not None for p in pkgs),
        },
    }


# ═══════════════════════════════════════════════════════════════════
# PHASE 5 — PROJECT LABOR SUMMARY (for profit integration)
# ═══════════════════════════════════════════════════════════════════

async def get_labor_summary_for_project(org_id: str, project_id: str) -> dict:
    """The project's labor summary for the profit readers — R62: from THE labor cost
    (``project_labor_cost``: approved reports + Owner-approved manual rows), never from the
    raw labor_entries. "mapped" = linked to an execution package."""
    tenant = TenantData.for_resolved_org(db, org_id)
    lc = await project_labor_cost(org_id, project_id)
    split = lc["by_package"]
    unm = split.get("") or {"cost": 0.0, "hours": 0.0, "downtime_hours": 0.0}
    unmapped_cost = unm["cost"]
    unmapped_hours = unm["hours"] + unm["downtime_hours"]
    total_cost = lc["total"]
    total_hours = round(lc["approved_hours"] + lc.get("downtime_hours", 0), 2)
    mapped_cost = round(total_cost - unmapped_cost, 2)
    mapped_hours = round(total_hours - unmapped_hours, 2)

    # Budget from execution packages
    pkgs = await tenant.execution_packages.find(
        {"org_id": org_id, "project_id": project_id},
        {"_id": 0, "labor_budget_total": 1, "planned_hours": 1}
    ).to_list(200)
    total_budget = sum(p.get("labor_budget_total", 0) for p in pkgs)
    total_planned_hours = sum(p.get("planned_hours", 0) or 0 for p in pkgs)

    return {
        "total_hours": round(total_hours, 1),
        "total_cost": round(total_cost, 2),
        "mapped_hours": round(mapped_hours, 1),
        "mapped_cost": round(mapped_cost, 2),
        "unmapped_hours": round(unmapped_hours, 1),
        "unmapped_cost": round(unmapped_cost, 2),
        "downtime_cost": lc["downtime_total"],
        "manual_cost": lc["manual_total"],
        "budget_total": round(total_budget, 2),
        "planned_hours_total": round(total_planned_hours, 1),
        "variance_value": round(total_cost - total_budget, 2) if total_budget > 0 else None,
        "currency": "EUR",
        "has_data": len(lc["lines"]) > 0,
        "source": "project_labor_cost",
        "dq_warnings": lc["dq_warnings"],
    }
