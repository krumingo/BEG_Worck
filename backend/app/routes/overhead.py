"""
Routes - Dashboard Stats + Overhead (M9) Endpoints.
"""
from fastapi import APIRouter, Depends, Header, HTTPException
from typing import Optional
from datetime import datetime, timezone, date as date_type
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import require_m9
from app.utils.audit import log_audit
from app.permissions.money_write import require_money_write
from ..models.overhead import (
    OVERHEAD_FREQUENCIES, OVERHEAD_ALLOCATION_TYPES, OVERHEAD_METHODS,
    OverheadCategoryCreate, OverheadCategoryUpdate,
    OverheadCostCreate, OverheadCostUpdate,
    OverheadAssetCreate, OverheadAssetUpdate,
    OverheadSnapshotCompute, OverheadAllocateRequest
)
from app.tenancy.data_access import TenantData
from app.services.overhead_lifecycle import (  # OH-01
    KeyedWrite, NOT_ARCHIVED, STATUS_ARCHIVED, audit_overhead_event, require_key,
    COMPUTE_LOCK, allocation_version_key, overhead_lock, period_key, period_lock,
    audit_overhead_event_once, current_allocations, legacy_audit_once, publish_allocation_batch,
)


def _tenant(user: dict) -> TenantData:
    """The request's tenant — from the server-loaded session user only (W0-03E-A2C)."""
    return TenantData.for_user(db, user)

router = APIRouter(tags=["Dashboard / Overhead"])

# ── Helpers ────────────────────────────────────────────────────────

def today_str():
    """Return today's date as YYYY-MM-DD string in UTC."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def check_overhead_access(user: dict, write: bool = False) -> bool:
    """Check if user has access to overhead cost system.

    SEC-02 (R20-1, Krum 06.11.2026): overhead is company finance — Owner/Admin/Accountant
    only, for reads too. The former SiteManager read is removed; ``write`` is kept for the
    callers' signature (the write rule was already the same three roles)."""
    return user["role"] in ["Admin", "Owner", "Accountant"]


# ── OH-01: archive instead of delete (CLAUDE.md §2.9, FLOW-024) ────

def _not_archived(query: dict, include_archived: bool) -> dict:
    """A list hides archived records unless asked; a legacy record without status is active."""
    if not include_archived:
        query["status"] = NOT_ARCHIVED
    return query


async def _category_usage(tenant: TenantData, cat_id: str) -> dict:
    """A category is used when any overhead cost (archived ones too) names it."""
    n = await tenant.overhead_costs.count_documents({"category_id": cat_id})
    return {"overhead_costs": n} if n else {}


async def _cost_usage(tenant: TenantData, cost: dict) -> dict:
    """A cost is used when a computed snapshot's period covers its date: the snapshot's
    total was summed from it (snapshots keep totals, not cost ids)."""
    d = cost.get("date_incurred")
    if not d:
        return {}
    snaps = await tenant.overhead_snapshots.find(
        {"period_start": {"$lte": d}, "period_end": {"$gte": d}}, {"_id": 0, "id": 1}
    ).to_list(None)
    return {"overhead_snapshots": sorted(s["id"] for s in snaps)} if snaps else {}


async def _asset_usage(tenant: TenantData, asset: dict) -> dict:
    """An asset is used when any snapshot was computed after it existed: its
    amortization may be inside that total (conservative — an inactive asset counts too)."""
    snaps = await tenant.overhead_snapshots.find(
        {"period_start": {"$exists": True},
         "computed_at": {"$gte": asset.get("created_at") or ""}}, {"_id": 0, "id": 1}
    ).to_list(None)
    return {"overhead_snapshots": sorted(s["id"] for s in snaps)} if snaps else {}


async def _archive_record(tenant: TenantData, coll, user: dict, entity_type: str,
                          existing: dict, usage: dict, reason: Optional[str],
                          idempotency_key: Optional[str]) -> dict:
    """409 when used or already archived; otherwise status=archived (who/when/why).
    Nothing is ever deleted. Idempotent under the request's Idempotency-Key (R29)."""
    record_id = existing["id"]
    kw = await KeyedWrite.begin(db, user, "overhead.%s.archive" % entity_type, idempotency_key,
                                {"id": record_id, "reason": reason})
    if kw.replay_id:
        doc = await coll.find_one({"id": kw.replay_id}, {"_id": 0})
        return {"archived": True, "deleted": False, "id": kw.replay_id, "record": doc}
    # OH74-02: THIS operation (same key) already archived it and was interrupted before
    # its audit — the retry resumes and completes the audit, with no second status change
    resumed = (existing.get("status") == STATUS_ARCHIVED
               and existing.get("archive_operation_key") == kw.key)
    if existing.get("status") == STATUS_ARCHIVED and not resumed:
        raise await kw.refuse(HTTPException(status_code=409, detail={
            "error_code": "ALREADY_ARCHIVED", "message": "Записът вече е архивиран"}))
    if usage and not resumed:
        raise await kw.refuse(HTTPException(status_code=409, detail={
            "error_code": "OVERHEAD_RECORD_IN_USE",
            "message": "Записът е използван и не може да бъде изтрит или архивиран",
            "used_by": usage}))
    async with kw:
        now = datetime.now(timezone.utc).isoformat()
        archive = {
            "status": STATUS_ARCHIVED,
            "archived_at": now,
            "archived_by_user_id": user["id"],
            "archived_by_name": user.get("name", user.get("email", "")),
            "archive_reason": reason,
            "archive_operation_key": kw.key,     # OH74-02: whose archive this is
            "updated_at": now,
        }
        won = None if resumed else await coll.update_one(
            {"id": record_id, "status": NOT_ARCHIVED}, {"$set": archive})
        if won is not None and won.modified_count != 1:
            # OH01-2: a concurrent request archived it first — this one wrote nothing
            # and must not claim (or audit) the archive.
            raise HTTPException(status_code=409, detail={
                "error_code": "ALREADY_ARCHIVED", "message": "Записът вече е архивиран"})

        async def _audit():
            await audit_overhead_event_once(
                db, user, action="overhead.%s.archived" % entity_type, entity_type=entity_type,
                entity_id=record_id, reason=reason or "archived instead of delete (OH-01)",
                structured_diff={"status": {"before": existing.get("status"),
                                            "after": STATUS_ARCHIVED}},
                idempotency_key=kw.key)

        async def _legacy_audit():
            await legacy_audit_once(db, user, "archived", entity_type, record_id,
                                    {"reason": reason}, kw.key)
        await kw.wf.step("audit", _audit)
        await kw.wf.step("legacy_audit", _legacy_audit)
        kw.result_id = record_id
    doc = await coll.find_one({"id": record_id}, {"_id": 0})
    return {"archived": True, "deleted": False, "id": record_id, "record": doc}


# ── Dashboard Stats ────────────────────────────────────────────────

@router.get("/dashboard/stats")
async def get_dashboard_stats(user: dict = Depends(get_current_user)):
    tenant = _tenant(user)
    org_id = user["org_id"]
    status_counts = {}
    async for doc in tenant.projects.aggregate([
        {"$match": {"org_id": org_id}},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}}
    ]):
        status_counts[doc["_id"]] = doc["count"]

    users_count = await tenant.users.count_documents({"org_id": org_id, "is_active": True})

    # Attendance stats for today
    date = today_str()
    # FG-647: distinct workers marked today, not entries (one entry per object — FLOW-013)
    today_marked = len(await tenant.attendance_entries.distinct("user_id", {"org_id": org_id, "date": date}))
    today_present = len(await tenant.attendance_entries.distinct(
        "user_id", {"org_id": org_id, "date": date, "status": {"$in": ["Present", "Late"]}}))

    # Work report stats
    pending_reports = await tenant.work_reports.count_documents({"org_id": org_id, "date": date, "status": "Submitted"})

    return {
        "active_projects": status_counts.get("Active", 0),
        "paused_projects": status_counts.get("Paused", 0),
        "completed_projects": status_counts.get("Completed", 0),
        "draft_projects": status_counts.get("Draft", 0),
        "total_projects": sum(status_counts.values()),
        "users_count": users_count,
        "today_marked": today_marked,
        "today_present": today_present,
        "pending_reports": pending_reports,
    }


async def _guarded_update(tenant: TenantData, coll, user: dict, entity_type: str,
                          existing: dict, usage: dict, updates: dict) -> dict:
    """FG-87 (CLAUDE.md §7): an archived record is read-only; a USED record is not edited
    in place — the correction is a new record (and a new snapshot version), never an
    overwrite of what a snapshot already summed. Every accepted edit writes the canonical
    AuditEvent with before/after of the changed fields."""
    record_id = existing["id"]
    if existing.get("status") == STATUS_ARCHIVED:
        raise HTTPException(status_code=409, detail={
            "error_code": "RECORD_ARCHIVED", "message": "Архивиран запис не може да се редактира"})
    if usage:
        raise HTTPException(status_code=409, detail={
            "error_code": "OVERHEAD_RECORD_IN_USE",
            "message": "Записът е използван в snapshot/разход и не се редактира; направете "
                       "корекция с нов запис и преизчислете snapshot-а",
            "used_by": usage})
    won = await coll.update_one({"id": record_id, "status": NOT_ARCHIVED}, {"$set": updates})
    if won.matched_count != 1:      # archived by a concurrent request after the read
        raise HTTPException(status_code=409, detail={
            "error_code": "RECORD_ARCHIVED", "message": "Архивиран запис не може да се редактира"})
    changed = {k: {"before": existing.get(k), "after": v} for k, v in updates.items()
               if k != "updated_at" and existing.get(k) != v}
    await audit_overhead_event(db, user, action="overhead.%s.updated" % entity_type,
                               entity_type=entity_type, entity_id=record_id,
                               reason="overhead record edited (not used by any snapshot)",
                               structured_diff=changed)
    await log_audit(user["org_id"], user["id"], user["email"], "updated", entity_type, record_id, updates)
    return await coll.find_one({"id": record_id}, {"_id": 0})


# ── Overhead Categories ────────────────────────────────────────────

@router.get("/overhead/categories")
async def list_overhead_categories(include_archived: bool = False, user: dict = Depends(require_m9)):
    tenant = _tenant(user)
    if not check_overhead_access(user):
        raise HTTPException(status_code=403, detail="Access denied")
    query = _not_archived({"org_id": user["org_id"]}, include_archived)
    cursor = tenant.overhead_categories.find(query, {"_id": 0})
    return await cursor.to_list(None)


@router.post("/overhead/categories")
async def create_overhead_category(data: OverheadCategoryCreate, user: dict = Depends(require_m9)):
    tenant = _tenant(user)
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "name": data.name,
        "active": data.active,
        "created_at": now,
        "updated_at": now,
    }
    await tenant.overhead_categories.insert_one(doc)
    await log_audit(user["org_id"], user["id"], user["email"], "created", "overhead_category", doc["id"], {"name": data.name})
    return {k: v for k, v in doc.items() if k != "_id"}


@router.put("/overhead/categories/{cat_id}")
async def update_overhead_category(cat_id: str, data: OverheadCategoryUpdate, user: dict = Depends(require_m9)):
    tenant = _tenant(user)
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    existing = await tenant.overhead_categories.find_one({"id": cat_id, "org_id": user["org_id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Category not found")
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    return await _guarded_update(tenant, tenant.overhead_categories, user, "overhead_category",
                                 existing, await _category_usage(tenant, cat_id), updates)


@router.delete("/overhead/categories/{cat_id}")
async def delete_overhead_category(
    cat_id: str,
    reason: Optional[str] = None,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    user: dict = Depends(require_m9),
):
    """OH-01: never deleted — 409 when used, otherwise archived."""
    tenant = _tenant(user)
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    require_key(idempotency_key)
    existing = await tenant.overhead_categories.find_one({"id": cat_id, "org_id": user["org_id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Category not found")
    usage = await _category_usage(tenant, cat_id)
    return await _archive_record(tenant, tenant.overhead_categories, user, "overhead_category",
                                 existing, usage, reason, idempotency_key)


# ── Overhead Costs ─────────────────────────────────────────────────

@router.get("/overhead/costs")
async def list_overhead_costs(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    category_id: Optional[str] = None,
    include_archived: bool = False,
    user: dict = Depends(require_m9)
):
    tenant = _tenant(user)
    if not check_overhead_access(user):
        raise HTTPException(status_code=403, detail="Access denied")
    query = _not_archived({"org_id": user["org_id"]}, include_archived)
    if date_from and date_to:
        query["date_incurred"] = {"$gte": date_from, "$lte": date_to}
    elif date_from:
        query["date_incurred"] = {"$gte": date_from}
    elif date_to:
        query["date_incurred"] = {"$lte": date_to}
    if category_id:
        query["category_id"] = category_id
    cursor = tenant.overhead_costs.find(query, {"_id": 0}).sort("date_incurred", -1)
    costs = await cursor.to_list(None)
    # Enrich with category name
    cat_ids = list(set(c.get("category_id") for c in costs if c.get("category_id")))
    cats = {}
    if cat_ids:
        cat_cursor = tenant.overhead_categories.find({"id": {"$in": cat_ids}}, {"_id": 0})
        cat_list = await cat_cursor.to_list(None)
        cats = {c["id"]: c["name"] for c in cat_list}
    for c in costs:
        c["category_name"] = cats.get(c.get("category_id"), "")
    return costs


@router.post("/overhead/costs")
async def create_overhead_cost(data: OverheadCostCreate, user: dict = Depends(require_m9)):
    tenant = _tenant(user)
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    if data.frequency not in OVERHEAD_FREQUENCIES:
        raise HTTPException(status_code=400, detail="Invalid frequency")
    if data.allocation_type not in OVERHEAD_ALLOCATION_TYPES:
        raise HTTPException(status_code=400, detail="Invalid allocation type")
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "category_id": data.category_id,
        "name": data.name,
        "amount": data.amount,
        "currency": data.currency,
        "vat_percent": data.vat_percent,
        "date_incurred": data.date_incurred,
        "frequency": data.frequency,
        "allocation_type": data.allocation_type,
        "note": data.note,
        "created_at": now,
        "updated_at": now,
    }
    await tenant.overhead_costs.insert_one(doc)
    await log_audit(user["org_id"], user["id"], user["email"], "created", "overhead_cost", doc["id"], {"name": data.name, "amount": data.amount})
    return {k: v for k, v in doc.items() if k != "_id"}


@router.put("/overhead/costs/{cost_id}")
async def update_overhead_cost(cost_id: str, data: OverheadCostUpdate, user: dict = Depends(require_m9)):
    tenant = _tenant(user)
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    existing = await tenant.overhead_costs.find_one({"id": cost_id, "org_id": user["org_id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Cost not found")
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if "frequency" in updates and updates["frequency"] not in OVERHEAD_FREQUENCIES:
        raise HTTPException(status_code=400, detail="Invalid frequency")
    if "allocation_type" in updates and updates["allocation_type"] not in OVERHEAD_ALLOCATION_TYPES:
        raise HTTPException(status_code=400, detail="Invalid allocation type")
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    # FG-87: the NEW date too — moving a cost into a computed period is an edit of a used cost
    usage = await _cost_usage(tenant, existing) or await _cost_usage(tenant, {**existing, **updates})
    return await _guarded_update(tenant, tenant.overhead_costs, user, "overhead_cost",
                                 existing, usage, updates)


@router.delete("/overhead/costs/{cost_id}")
async def delete_overhead_cost(
    cost_id: str,
    reason: Optional[str] = None,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    user: dict = Depends(require_m9),
):
    """OH-01: never deleted — 409 when a snapshot used it, otherwise archived."""
    tenant = _tenant(user)
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    require_key(idempotency_key)
    existing = await tenant.overhead_costs.find_one({"id": cost_id, "org_id": user["org_id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Cost not found")
    usage = await _cost_usage(tenant, existing)
    return await _archive_record(tenant, tenant.overhead_costs, user, "overhead_cost",
                                 existing, usage, reason, idempotency_key)


# ── Overhead Assets ────────────────────────────────────────────────

@router.get("/overhead/assets")
async def list_overhead_assets(active_only: bool = True, include_archived: bool = False,
                               user: dict = Depends(require_m9)):
    tenant = _tenant(user)
    if not check_overhead_access(user):
        raise HTTPException(status_code=403, detail="Access denied")
    query = _not_archived({"org_id": user["org_id"]}, include_archived)
    if active_only:
        query["active"] = True
    cursor = tenant.overhead_assets.find(query, {"_id": 0}).sort("purchase_date", -1)
    assets = await cursor.to_list(None)
    # Add computed daily amortization
    for asset in assets:
        life_days = asset.get("useful_life_months", 60) * 30.4375
        daily_amort = asset.get("purchase_cost", 0) / life_days if life_days > 0 else 0
        asset["daily_amortization"] = round(daily_amort, 4)
    return assets


@router.post("/overhead/assets")
async def create_overhead_asset(data: OverheadAssetCreate, user: dict = Depends(require_m9)):
    tenant = _tenant(user)
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "name": data.name,
        "purchase_cost": data.purchase_cost,
        "currency": data.currency,
        "purchase_date": data.purchase_date,
        "useful_life_months": data.useful_life_months,
        "assigned_to_user_id": data.assigned_to_user_id,
        "active": data.active,
        "note": data.note,
        "created_at": now,
        "updated_at": now,
    }
    await tenant.overhead_assets.insert_one(doc)
    await log_audit(user["org_id"], user["id"], user["email"], "created", "overhead_asset", doc["id"], {"name": data.name, "purchase_cost": data.purchase_cost})
    # Add computed daily amortization
    result = {k: v for k, v in doc.items() if k != "_id"}
    life_days = data.useful_life_months * 30.4375
    result["daily_amortization"] = round(data.purchase_cost / life_days, 4) if life_days > 0 else 0
    return result


@router.put("/overhead/assets/{asset_id}")
async def update_overhead_asset(asset_id: str, data: OverheadAssetUpdate, user: dict = Depends(require_m9)):
    tenant = _tenant(user)
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    existing = await tenant.overhead_assets.find_one({"id": asset_id, "org_id": user["org_id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Asset not found")
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    return await _guarded_update(tenant, tenant.overhead_assets, user, "overhead_asset",
                                 existing, await _asset_usage(tenant, existing), updates)


@router.delete("/overhead/assets/{asset_id}")
async def delete_overhead_asset(
    asset_id: str,
    reason: Optional[str] = None,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    user: dict = Depends(require_m9),
):
    """OH-01: never deleted — 409 when a snapshot may hold its amortization, otherwise archived."""
    tenant = _tenant(user)
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    require_key(idempotency_key)
    existing = await tenant.overhead_assets.find_one({"id": asset_id, "org_id": user["org_id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Asset not found")
    usage = await _asset_usage(tenant, existing)
    return await _archive_record(tenant, tenant.overhead_assets, user, "overhead_asset",
                                 existing, usage, reason, idempotency_key)


# ── Overhead Snapshots ─────────────────────────────────────────────

async def _refuse_overlap(tenant: TenantData, period_start: str, period_end: str) -> None:
    """D6 (FLOW-024 / CLAUDE.md §7: a cost is never counted twice): an ACTIVE snapshot of a
    DIFFERENT but overlapping period -> 409 PERIOD_OVERLAP, nothing written. The SAME period
    is not an overlap: it is versioned (FG-86)."""
    overlap = await tenant.overhead_snapshots.find(
        {"period_start": {"$lte": period_end}, "period_end": {"$gte": period_start},
         "superseded_by": None,
         "$nor": [{"period_start": period_start, "period_end": period_end}]},
        {"_id": 0, "id": 1, "period_start": 1, "period_end": 1}).to_list(None)
    if overlap:
        raise HTTPException(status_code=409, detail={
            "error_code": "PERIOD_OVERLAP",
            "message": "Периодът се застъпва с активен snapshot на друг период; "
                       "разходите не се броят два пъти",
            "overlapping": sorted(overlap, key=lambda x: x["period_start"])})


@router.post("/overhead/snapshots/compute")
async def compute_overhead_snapshot(
    data: OverheadSnapshotCompute,
    _sec01: dict = Depends(require_money_write(
        "finance.overhead_snapshot_compute.execute", module="M9",
        resource_type="overhead_snapshot")),  # SEC-01-C01: before any read/write
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    user: dict = Depends(require_m9),
):
    """FG-86/FG-88: R29 key required; a new snapshot of a period SUPERSEDES the active one
    (and its allocations) — one active snapshot per period, versioned, never two.
    #69 x OH-01 merge: the permission gate is #69's; the ONE key path is OH-01's KeyedWrite."""
    tenant = _tenant(user)
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    require_key(idempotency_key)
    if data.method not in OVERHEAD_METHODS:
        raise HTTPException(status_code=400, detail="Invalid method")
    
    org_id = user["org_id"]
    period_start = data.period_start
    period_end = data.period_end
    
    # Calculate number of days in period
    d_start = date_type.fromisoformat(period_start)
    d_end = date_type.fromisoformat(period_end)
    num_days = (d_end - d_start).days + 1
    
    # 1. Sum overhead costs in period
    costs_cursor = tenant.overhead_costs.find({
        "org_id": org_id,
        "date_incurred": {"$gte": period_start, "$lte": period_end},
        "status": NOT_ARCHIVED,  # OH-01
    }, {"_id": 0})
    costs = await costs_cursor.to_list(None)
    total_costs = sum(c.get("amount", 0) for c in costs)
    
    # 2. Calculate asset amortization for all active assets
    assets_cursor = tenant.overhead_assets.find({"org_id": org_id, "active": True, "status": NOT_ARCHIVED}, {"_id": 0})
    assets = await assets_cursor.to_list(None)
    total_amortization = 0
    for asset in assets:
        life_days = asset.get("useful_life_months", 60) * 30.4375
        if life_days > 0:
            daily_amort = asset.get("purchase_cost", 0) / life_days
            total_amortization += daily_amort * num_days
    
    total_overhead = round(total_costs + total_amortization, 2)
    
    # 3. Count person-days (unique user+date with Present/Late)
    attendance_pipeline = [
        {"$match": {
            "org_id": org_id,
            "date": {"$gte": period_start, "$lte": period_end},
            "status": {"$in": ["Present", "Late"]}
        }},
        {"$group": {"_id": {"user_id": "$user_id", "date": "$date"}}},
        {"$count": "total"}
    ]
    att_result = await tenant.attendance_entries.aggregate(attendance_pipeline).to_list(None)
    total_person_days = att_result[0]["total"] if att_result else 0
    
    # 4. Sum work report hours (Submitted/Approved)
    hours_pipeline = [
        {"$match": {
            "org_id": org_id,
            "date": {"$gte": period_start, "$lte": period_end},
            "status": {"$in": ["Submitted", "Approved"]}
        }},
        {"$group": {"_id": None, "total_hours": {"$sum": "$total_hours"}}}
    ]
    hours_result = await tenant.work_reports.aggregate(hours_pipeline).to_list(None)
    total_hours = round(hours_result[0]["total_hours"], 2) if hours_result else 0
    
    # 5. Calculate rates
    rate_per_person_day = round(total_overhead / total_person_days, 2) if total_person_days > 0 else 0
    rate_per_hour = round(total_overhead / total_hours, 2) if total_hours > 0 else 0
    
    # OH74-01: the per-project basis is FROZEN with the totals — an allocation uses only it
    allocation_basis = await _allocation_basis(tenant, org_id, period_start, period_end)

    # 6. Create immutable snapshot — FG-86: as the new version of the period's snapshot
    await _refuse_overlap(tenant, period_start, period_end)       # D6: before any write
    kw = await KeyedWrite.begin(db, user, "overhead.snapshot.compute", idempotency_key,
                                data.model_dump())
    if kw.replay_id:
        return await tenant.overhead_snapshots.find_one({"id": kw.replay_id}, {"_id": 0})
    now = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "id": kw.new_id("snapshot"),
        "org_id": org_id,
        "period_start": period_start,
        "period_end": period_end,
        "method": data.method,
        "total_overhead": total_overhead,
        "total_costs": round(total_costs, 2),
        "total_amortization": round(total_amortization, 2),
        "total_person_days": total_person_days,
        "total_hours": total_hours,
        "overhead_rate_per_person_day": rate_per_person_day,
        "overhead_rate_per_hour": rate_per_hour,
        "computed_at": now,
        "computed_by_user_id": user["id"],
        "computed_by_name": user.get("name", user.get("email", "")),
        "notes": data.notes,
        # stored as lists: a project id is data, never a document key
        "allocation_basis": {m: [{"project_id": k, "basis": v} for k, v in sorted(b.items())]
                             for m, b in allocation_basis.items()},
        "active_period_key": "%s|%s" % (org_id, period_key(period_start, period_end)),
        "superseded_by": None,
    }
    async with kw, overhead_lock(tenant, COMPUTE_LOCK), period_lock(tenant, period_start, period_end):
        sid = snapshot["id"]
        await _refuse_overlap(tenant, period_start, period_end)   # again, under the lock

        async def _supersede_previous():
            # the period's active snapshot(s): keyed ones and legacy ones (no key, same period)
            prev = await tenant.overhead_snapshots.find(
                {"period_start": period_start, "period_end": period_end,
                 "superseded_by": None, "id": {"$ne": sid}}, {"_id": 0}).to_list(None)
            for p in prev:
                won = await tenant.overhead_snapshots.update_one(
                    {"id": p["id"], "superseded_by": None},
                    {"$set": {"superseded_by": sid, "superseded_at": now,
                              "superseded_by_user_id": user["id"]},
                     "$unset": {"active_period_key": ""}})
                if won.modified_count != 1:
                    raise HTTPException(status_code=409, detail={
                        "error_code": "SNAPSHOT_VERSION_CONFLICT",
                        "message": "Друга заявка току-що смени snapshot-а за периода"})
                # R38 (Krum, 07.11.2026, FG-97): its allocations KEEP counting, labelled
                # "преизчислява се", until the new snapshot is allocated — that allocation
                # supersedes them (period-wide) at the moment it is written. Never 0.
                await tenant.project_overhead_allocations.update_many(
                    {"overhead_snapshot_id": p["id"], "superseded_by": None},
                    {"$set": {"recalculating": True, "recalculating_since": now,
                              "recalculating_snapshot_id": sid}})
            return max([0] + [p.get("snapshot_version") or 1 for p in prev]) + 1
        snapshot["snapshot_version"] = int(await kw.wf.step("supersede", _supersede_previous,
                                                            reference=str))
        if not await tenant.overhead_snapshots.find_one({"id": sid}, {"_id": 0, "id": 1}):
            await tenant.overhead_snapshots.insert_one(snapshot)

        async def _audit():
            await audit_overhead_event_once(
                db, user, action="overhead.snapshot.computed", entity_type="overhead_snapshot",
                entity_id=sid, reason="overhead snapshot version %d of %s - %s" % (
                    snapshot["snapshot_version"], period_start, period_end),
                structured_diff={"period": [period_start, period_end],
                                 "version": snapshot["snapshot_version"],
                                 "total_overhead": total_overhead, "method": data.method},
                idempotency_key=kw.key)

        async def _legacy_audit():
            await legacy_audit_once(db, user, "computed", "overhead_snapshot", sid, {
                "period": f"{period_start} - {period_end}",
                "total_overhead": total_overhead,
                "method": data.method,
                "snapshot_version": snapshot["snapshot_version"],
            }, kw.key)
        await kw.wf.step("audit", _audit)
        await kw.wf.step("legacy_audit", _legacy_audit)
        kw.result_id = sid
    return {k: v for k, v in snapshot.items() if k != "_id"}


@router.get("/overhead/snapshots")
async def list_overhead_snapshots(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    include_superseded: bool = False,
    user: dict = Depends(require_m9)
):
    tenant = _tenant(user)
    if not check_overhead_access(user):
        raise HTTPException(status_code=403, detail="Access denied")
    query = {"org_id": user["org_id"]}
    if not include_superseded:
        query["superseded_by"] = None  # FG-86: the active snapshot of each period
    if date_from and date_to:
        query["period_start"] = {"$gte": date_from}
        query["period_end"] = {"$lte": date_to}
    cursor = tenant.overhead_snapshots.find(query, {"_id": 0}).sort("computed_at", -1)
    return await cursor.to_list(None)


@router.get("/overhead/snapshots/{snapshot_id}")
async def get_overhead_snapshot(snapshot_id: str, user: dict = Depends(require_m9)):
    tenant = _tenant(user)
    if not check_overhead_access(user):
        raise HTTPException(status_code=403, detail="Access denied")
    snapshot = await tenant.overhead_snapshots.find_one({"id": snapshot_id, "org_id": user["org_id"]}, {"_id": 0})
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    # Get allocations
    # OH74-03: the current version is the one the period's pointer names
    allocs = await current_allocations(tenant, {"overhead_snapshot_id": snapshot_id})
    snapshot["allocations"] = allocs
    return snapshot


async def _allocation_basis(tenant: TenantData, org_id: str, period_start: str,
                            period_end: str) -> dict:
    """OH74-01: the per-project basis of BOTH methods for one period, read once. Frozen in
    the snapshot at compute time, so an allocation never mixes a frozen denominator with
    numerators read later."""
    pd = await tenant.attendance_entries.aggregate([
        {"$match": {"org_id": org_id, "date": {"$gte": period_start, "$lte": period_end},
                    "status": {"$in": ["Present", "Late"]},
                    "project_id": {"$exists": True, "$ne": None}}},
        {"$group": {"_id": "$project_id",
                    "person_days": {"$addToSet": {"user_id": "$user_id", "date": "$date"}}}},
        {"$project": {"project_id": "$_id", "count": {"$size": "$person_days"}}},
    ]).to_list(None)
    hrs = await tenant.work_reports.aggregate([
        {"$match": {"org_id": org_id, "date": {"$gte": period_start, "$lte": period_end},
                    "status": {"$in": ["Submitted", "Approved"]}}},
        {"$group": {"_id": "$project_id", "total_hours": {"$sum": "$total_hours"}}},
    ]).to_list(None)
    return {
        "PersonDays": {r["project_id"]: r["count"] for r in pd if r.get("project_id")},
        "Hours": {r["_id"]: round(r["total_hours"], 2) for r in hrs if r.get("_id")},
    }


async def _person_days_total(tenant: TenantData, org_id: str, start: str, end: str) -> int:
    """The snapshot's person-day total, read now (the rule of compute step 3)."""
    r = await tenant.attendance_entries.aggregate([
        {"$match": {"org_id": org_id, "date": {"$gte": start, "$lte": end},
                    "status": {"$in": ["Present", "Late"]}}},
        {"$group": {"_id": {"user_id": "$user_id", "date": "$date"}}},
        {"$count": "total"}]).to_list(None)
    return r[0]["total"] if r else 0


async def _hours_total(tenant: TenantData, org_id: str, start: str, end: str) -> float:
    """The snapshot's hours total, read now (the rule of compute step 4)."""
    r = await tenant.work_reports.aggregate([
        {"$match": {"org_id": org_id, "date": {"$gte": start, "$lte": end},
                    "status": {"$in": ["Submitted", "Approved"]}}},
        {"$group": {"_id": None, "total_hours": {"$sum": "$total_hours"}}}]).to_list(None)
    return round(r[0]["total_hours"], 2) if r else 0


def _split_cents(total_overhead: float, basis: dict, total_basis: float):
    """OH74-01: ``total_overhead`` split by share of ``total_basis`` in whole cents
    (largest remainder), plus the UNALLOCATED remainder (basis outside any project —
    FLOW-024 keeps "остатъка", it never disappears). Returns ({project: amount}, unallocated);
    their sum is EXACTLY the snapshot total."""
    total_c = int(round(total_overhead * 100))
    denom = max(float(total_basis), float(sum(basis.values())))
    raw = {pid: total_c * b / denom for pid, b in sorted(basis.items())}
    raw_unalloc = total_c - sum(raw.values())
    buckets = dict(raw)
    if raw_unalloc > 1e-9:
        buckets[None] = raw_unalloc
    cents = {k: int(v) for k, v in buckets.items()}
    rest = total_c - sum(cents.values())
    for k in sorted(buckets, key=lambda k: (-(buckets[k] - cents[k]), str(k)))[:rest]:
        cents[k] += 1
    assert sum(cents.values()) == total_c, (cents, total_c)
    unallocated = cents.pop(None, 0)
    return {k: v / 100 for k, v in cents.items()}, unallocated / 100


@router.post("/overhead/snapshots/{snapshot_id}/allocate")
async def allocate_overhead_to_projects(
    snapshot_id: str,
    data: OverheadAllocateRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    user: dict = Depends(require_m9),
):
    """OH-01 / FLOW-024: every allocation is a NEW version; the previous one stays with
    ``superseded_by`` and no report reads it."""
    tenant = _tenant(user)
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    require_key(idempotency_key)
    
    snapshot = await tenant.overhead_snapshots.find_one({"id": snapshot_id, "org_id": user["org_id"]}, {"_id": 0})
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    
    org_id = user["org_id"]
    period_start = snapshot["period_start"]
    period_end = snapshot["period_end"]
    total_overhead = snapshot["total_overhead"]
    method = data.method
    
    # OH-01: nothing is deleted here — the previous version is superseded below.
    # OH74-01: numerators AND denominator from ONE frozen basis — the snapshot's own.
    total_key = "total_person_days" if method == "PersonDays" else "total_hours"
    total_basis = snapshot.get(total_key) or 0
    if total_basis == 0:
        raise HTTPException(status_code=400, detail="No person-days to allocate"
                            if method == "PersonDays" else "No hours to allocate")
    frozen_rows = (snapshot.get("allocation_basis") or {}).get(method)
    frozen = None if frozen_rows is None else {r["project_id"]: r["basis"] for r in frozen_rows}
    if frozen is None:
        # a pre-OH74 snapshot has no frozen basis: use the current source only when its
        # total still IS the snapshot's total — otherwise the source changed after the
        # snapshot and a new snapshot is required (never 200 % of the overhead)
        current = (await _allocation_basis(tenant, org_id, period_start, period_end))[method]
        now_total = await (_person_days_total if method == "PersonDays" else _hours_total)(
            tenant, org_id, period_start, period_end)
        if round(float(now_total), 2) != round(float(total_basis), 2):
            raise HTTPException(status_code=409, detail={
                "error_code": "SNAPSHOT_SOURCE_CHANGED",
                "message": "Данните за периода са променени след snapshot-а; "
                           "изчислете нов snapshot и разпределете него",
                "snapshot_basis": total_basis, "current_basis": now_total})
        frozen = current
    amounts, unallocated = _split_cents(total_overhead, frozen, total_basis)
    proj_list = await tenant.projects.find(
        {"id": {"$in": sorted(amounts)}}, {"_id": 0, "id": 1, "code": 1, "name": 1}).to_list(None)
    projects = {p["id"]: p for p in proj_list}
    now = datetime.now(timezone.utc).isoformat()
    allocations = []
    for proj_id, allocated in sorted(amounts.items()):
        proj_info = projects.get(proj_id, {})
        allocations.append({
            "id": str(uuid.uuid4()),
            "org_id": org_id,
            "overhead_snapshot_id": snapshot_id,
            "project_id": proj_id,
            "project_code": proj_info.get("code", ""),
            "project_name": proj_info.get("name", ""),
            "basis_person_days": frozen[proj_id] if method == "PersonDays" else 0,
            "basis_hours": frozen[proj_id] if method != "PersonDays" else 0,
            "allocated_amount": allocated,
            "created_at": now,
        })
    # OH74-01: checked before ANY write — the version's allocated + unallocated IS the snapshot
    if int(round(sum(a["allocated_amount"] for a in allocations) * 100)) + \
            int(round(unallocated * 100)) != int(round(total_overhead * 100)):
        raise HTTPException(status_code=500, detail={"error_code": "ALLOCATION_TOTAL_MISMATCH"})

    return await _write_allocation_version(tenant, user, snapshot_id, method, allocations,
                                           idempotency_key, unallocated)


async def _write_allocation_version(tenant: TenantData, user: dict, snapshot_id: str,
                                    method: str, allocations: list,
                                    idempotency_key: Optional[str],
                                    unallocated: float = 0.0) -> dict:
    """OH-01: version N+1 of the snapshot's allocation. Order: the previous version is
    marked ``superseded_by`` FIRST, then the new rows are inserted — a report never sees two
    versions at once (the sum is never doubled). Each step runs once per Idempotency-Key."""
    coll = tenant.project_overhead_allocations
    kw = await KeyedWrite.begin(db, user, "overhead.allocation.version", idempotency_key,
                                {"snapshot_id": snapshot_id, "method": method})
    if kw.replay_id:
        rows = await coll.find({"overhead_snapshot_id": snapshot_id,
                                "allocation_batch_id": kw.replay_id}, {"_id": 0}).to_list(None)
        version = rows[0]["allocation_version"] if rows else None
        return {"allocations": rows, "allocation_batch_id": kw.replay_id,
                "allocation_version": version, "replayed": True}
    snap_doc = await tenant.overhead_snapshots.find_one(
        {"id": snapshot_id}, {"_id": 0, "period_start": 1, "period_end": 1})
    async with kw, period_lock(tenant, snap_doc["period_start"], snap_doc["period_end"]):
        batch_id = kw.new_id("batch")
        now = datetime.now(timezone.utc).isoformat()
        current = await tenant.overhead_snapshots.find_one(
            {"id": snapshot_id}, {"_id": 0, "superseded_by": 1})
        if current.get("superseded_by"):
            # FG-86: only the period's ACTIVE snapshot is allocated
            raise HTTPException(status_code=409, detail={
                "error_code": "SNAPSHOT_SUPERSEDED",
                "message": "Snapshot-ът е заменен от нова версия; разпределете активния",
                "superseded_by": current["superseded_by"]})

        async def _next_version():
            # OH01-1: under the snapshot lock, and a CAS on snapshot.allocation_version —
            # two writers can never both take the same version.
            snap = await tenant.overhead_snapshots.find_one(
                {"id": snapshot_id}, {"_id": 0, "allocation_version": 1})
            prev = (snap or {}).get("allocation_version")
            rows = await coll.find({"overhead_snapshot_id": snapshot_id},
                                   {"_id": 0, "allocation_version": 1}).to_list(None)
            # a legacy row without a version is version 1 (no migration, OH-01)
            nxt = max([prev or 0] + [r.get("allocation_version") or 1 for r in rows]) + 1
            cas = {"id": snapshot_id, "allocation_version": prev} if prev is not None \
                else {"id": snapshot_id, "allocation_version": {"$exists": False}}
            won = await tenant.overhead_snapshots.update_one(
                cas, {"$set": {"allocation_version": nxt, "current_allocation_batch_id": batch_id,
                               "current_unallocated_amount": unallocated}})
            if won.modified_count != 1:
                raise HTTPException(status_code=409, detail={
                    "error_code": "ALLOCATION_VERSION_CONFLICT",
                    "message": "Друга заявка току-що създаде нова версия — опитайте отново"})
            return nxt
        version = int(await kw.wf.step("version", _next_version, reference=str))

        for a in allocations:
            a.update({
                "id": kw.new_id("alloc:%s" % a["project_id"]),
                "allocation_batch_id": batch_id,
                "allocation_version": version,
                "version_key": allocation_version_key(user["org_id"], snapshot_id, version,
                                                      a["project_id"]),
                "allocation_method": method,
                "allocated_by_user_id": user["id"],
                "superseded_by": None,
            })

        # OH74-03: (1) the new batch is inserted STAGED — not current, no reader follows it
        have = {r["id"] for r in await coll.find(
            {"allocation_batch_id": batch_id}, {"_id": 0, "id": 1}).to_list(None)}
        missing = [a for a in allocations if a["id"] not in have]
        if missing:
            await coll.insert_many(missing)

        # (2) ONE atomic write publishes it: the period's pointer names this batch. Until
        # here the previous batch was current (R38: labelled); from here only this one.
        await kw.wf.step("publish", lambda: publish_allocation_batch(
            tenant, snap_doc["period_start"], snap_doc["period_end"], batch_id, version))

        async def _mark_history():
            # (3) history only — readers already follow the pointer: every earlier row of
            # the PERIOD (any snapshot of it, FG-86) records who replaced it
            same_period = await tenant.overhead_snapshots.distinct("id", {
                "period_start": snap_doc["period_start"], "period_end": snap_doc["period_end"]})
            await coll.update_many(
                {"overhead_snapshot_id": {"$in": same_period}, "superseded_by": None,
                 "allocation_batch_id": {"$ne": batch_id}},
                {"$set": {"superseded_by": batch_id, "superseded_at": now,
                          "superseded_by_user_id": user["id"]}})
        await kw.wf.step("supersede", _mark_history)

        total = round(sum(a["allocated_amount"] for a in allocations), 2)

        async def _audit():
            await audit_overhead_event_once(
                db, user, action="overhead.allocation.version_created",
                entity_type="overhead_allocation", entity_id=batch_id,
                reason="overhead allocation version %d of snapshot %s" % (version, snapshot_id),
                structured_diff={"overhead_snapshot_id": snapshot_id, "version": version,
                                 "method": method, "project_count": len(allocations),
                                 "total_allocated": total, "unallocated": unallocated},
                idempotency_key=kw.key)

        async def _legacy_audit():
            await legacy_audit_once(db, user, "allocated", "overhead_snapshot", snapshot_id, {
                "method": method,
                "project_count": len(allocations),
                "total_allocated": total,
                "allocation_version": version,
                "allocation_batch_id": batch_id,
            }, kw.key)
        await kw.wf.step("audit", _audit)
        await kw.wf.step("legacy_audit", _legacy_audit)
        kw.result_id = batch_id

    return {"allocations": [{k: v for k, v in a.items() if k != "_id"} for a in allocations],
            "allocation_batch_id": batch_id, "allocation_version": version,
            "unallocated_amount": unallocated}


@router.get("/overhead/allocations")
async def list_overhead_allocations(
    snapshot_id: Optional[str] = None,
    project_id: Optional[str] = None,
    include_superseded: bool = False,
    user: dict = Depends(require_m9)
):
    tenant = _tenant(user)
    if not check_overhead_access(user):
        raise HTTPException(status_code=403, detail="Access denied")
    query = {"org_id": user["org_id"]}
    if snapshot_id:
        query["overhead_snapshot_id"] = snapshot_id
    if project_id:
        query["project_id"] = project_id
    if not include_superseded:
        return await current_allocations(tenant, query)  # OH74-03: the published version only
    cursor = tenant.project_overhead_allocations.find(query, {"_id": 0})
    return await cursor.to_list(None)


@router.get("/overhead/enums")
async def get_overhead_enums(user: dict = Depends(require_m9)):
    return {
        "frequencies": OVERHEAD_FREQUENCIES,
        "allocation_types": OVERHEAD_ALLOCATION_TYPES,
        "methods": OVERHEAD_METHODS
    }
