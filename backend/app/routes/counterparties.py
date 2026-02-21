"""
Routes - Counterparties (Suppliers and Clients) with pagination and filters.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from datetime import datetime, timezone
import uuid
import re

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import require_m5
from app.utils.audit import log_audit
from ..models.finance import CounterpartyCreate, CounterpartyUpdate

router = APIRouter(tags=["Counterparties"])


def finance_permission(user: dict) -> bool:
    """Check if user has finance access"""
    return user["role"] in ["Admin", "Owner", "Accountant"]


def parse_filters(filters: Optional[str]) -> dict:
    """
    Parse filter string like 'name.contains=test,type.in=supplier|client,active.bool=true'
    Supports operators: contains, equals, in, bool, min, max, from, to
    """
    if not filters:
        return {}
    result = {}
    for part in filters.split(","):
        if "=" in part:
            key, value = part.split("=", 1)
            result[key] = value
    return result


def build_mongo_query(org_id: str, filters: dict, base_query: dict = None) -> dict:
    """Build MongoDB query from parsed filters with full operator support"""
    query = base_query or {"org_id": org_id}
    
    for key, value in filters.items():
        if "." in key:
            field, op = key.rsplit(".", 1)
        else:
            field, op = key, "equals"
        
        if op == "contains":
            query[field] = {"$regex": re.escape(value), "$options": "i"}
        elif op == "equals":
            query[field] = value
        elif op == "in":
            query[field] = {"$in": value.split("|")}
        elif op == "bool":
            query[field] = value.lower() == "true"
        elif op == "min":
            if field not in query:
                query[field] = {}
            query[field]["$gte"] = float(value)
        elif op == "max":
            if field not in query:
                query[field] = {}
            query[field]["$lte"] = float(value)
        elif op == "from":
            if field not in query:
                query[field] = {}
            query[field]["$gte"] = value
        elif op == "to":
            if field not in query:
                query[field] = {}
            query[field]["$lte"] = value
    
    return query


# ── Counterparties CRUD ────────────────────────────────────────────

@router.get("/counterparties")
async def list_counterparties(
    user: dict = Depends(require_m5),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("name"),
    sort_dir: str = Query("asc"),
    search: Optional[str] = None,
    filters: Optional[str] = None,
    type: Optional[str] = None,
    active_only: bool = True,
):
    """List counterparties with pagination, sorting, and filters"""
    base_query = {"org_id": user["org_id"]}
    
    if type:
        base_query["type"] = type
    if active_only:
        base_query["active"] = True
    
    # Parse additional filters
    parsed_filters = parse_filters(filters)
    query = build_mongo_query(user["org_id"], parsed_filters, base_query)
    
    # Global search
    if search:
        query["$or"] = [
            {"name": {"$regex": re.escape(search), "$options": "i"}},
            {"eik": {"$regex": re.escape(search), "$options": "i"}},
            {"vat_number": {"$regex": re.escape(search), "$options": "i"}},
            {"email": {"$regex": re.escape(search), "$options": "i"}},
            {"phone": {"$regex": re.escape(search), "$options": "i"}},
        ]
    
    # Count total
    total = await db.counterparties.count_documents(query)
    
    # Sort
    sort_direction = 1 if sort_dir == "asc" else -1
    
    # Paginate
    skip = (page - 1) * page_size
    counterparties = await db.counterparties.find(query, {"_id": 0}).sort(sort_by, sort_direction).skip(skip).limit(page_size).to_list(page_size)
    
    # Add invoice counts
    for cp in counterparties:
        # Count invoices where this is the supplier
        invoice_count = await db.invoices.count_documents({
            "org_id": user["org_id"],
            "supplier_counterparty_id": cp["id"]
        })
        cp["invoice_count"] = invoice_count
    
    return {
        "items": counterparties,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.post("/counterparties", status_code=201)
async def create_counterparty(data: CounterpartyCreate, user: dict = Depends(require_m5)):
    """Create a new counterparty (supplier/client)"""
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    # Check EIK uniqueness if provided
    if data.eik:
        existing = await db.counterparties.find_one({
            "org_id": user["org_id"],
            "eik": data.eik
        })
        if existing:
            raise HTTPException(status_code=400, detail="Counterparty with this EIK already exists")
    
    now = datetime.now(timezone.utc).isoformat()
    counterparty = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "name": data.name,
        "type": data.type,
        "eik": data.eik,
        "vat_number": data.vat_number,
        "address": data.address,
        "phone": data.phone,
        "email": data.email,
        "contact_person": data.contact_person,
        "payment_terms_days": data.payment_terms_days,
        "notes": data.notes,
        "active": data.active,
        "created_at": now,
        "updated_at": now,
    }
    
    await db.counterparties.insert_one(counterparty)
    await log_audit(user["org_id"], user["id"], user["email"], "counterparty_created", "counterparty", counterparty["id"],
                    {"name": data.name, "type": data.type})
    
    return {k: v for k, v in counterparty.items() if k != "_id"}


@router.get("/counterparties/{counterparty_id}")
async def get_counterparty(counterparty_id: str, user: dict = Depends(require_m5)):
    """Get counterparty details"""
    counterparty = await db.counterparties.find_one(
        {"id": counterparty_id, "org_id": user["org_id"]},
        {"_id": 0}
    )
    if not counterparty:
        raise HTTPException(status_code=404, detail="Counterparty not found")
    
    # Get related invoices summary
    invoices = await db.invoices.find(
        {"org_id": user["org_id"], "supplier_counterparty_id": counterparty_id},
        {"_id": 0, "id": 1, "invoice_no": 1, "total": 1, "status": 1, "issue_date": 1}
    ).sort("issue_date", -1).to_list(20)
    
    counterparty["recent_invoices"] = invoices
    counterparty["total_invoiced"] = sum(inv.get("total", 0) for inv in invoices)
    
    return counterparty


@router.put("/counterparties/{counterparty_id}")
async def update_counterparty(counterparty_id: str, data: CounterpartyUpdate, user: dict = Depends(require_m5)):
    """Update counterparty"""
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    counterparty = await db.counterparties.find_one({"id": counterparty_id, "org_id": user["org_id"]})
    if not counterparty:
        raise HTTPException(status_code=404, detail="Counterparty not found")
    
    # Check EIK uniqueness if changed
    if data.eik and data.eik != counterparty.get("eik"):
        existing = await db.counterparties.find_one({
            "org_id": user["org_id"],
            "eik": data.eik,
            "id": {"$ne": counterparty_id}
        })
        if existing:
            raise HTTPException(status_code=400, detail="Counterparty with this EIK already exists")
    
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    await db.counterparties.update_one({"id": counterparty_id}, {"$set": update})
    return await db.counterparties.find_one({"id": counterparty_id}, {"_id": 0})


@router.delete("/counterparties/{counterparty_id}")
async def delete_counterparty(counterparty_id: str, user: dict = Depends(require_m5)):
    """Delete counterparty (soft delete)"""
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    counterparty = await db.counterparties.find_one({"id": counterparty_id, "org_id": user["org_id"]})
    if not counterparty:
        raise HTTPException(status_code=404, detail="Counterparty not found")
    
    # Check if has invoices
    invoice_count = await db.invoices.count_documents({"supplier_counterparty_id": counterparty_id})
    if invoice_count > 0:
        # Soft delete only
        await db.counterparties.update_one(
            {"id": counterparty_id},
            {"$set": {"active": False, "updated_at": datetime.now(timezone.utc).isoformat()}}
        )
        return {"ok": True, "soft_deleted": True, "reason": "Has linked invoices"}
    
    await db.counterparties.delete_one({"id": counterparty_id})
    return {"ok": True}


@router.get("/counterparties/enums/types")
async def get_counterparty_types():
    """Get available counterparty types"""
    return {"types": ["supplier", "client", "both"]}
