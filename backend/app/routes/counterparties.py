"""
Routes - Counterparties (Suppliers and Clients).
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from datetime import datetime, timezone
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import require_m5
from app.utils.audit import log_audit
from ..models.finance import CounterpartyCreate, CounterpartyUpdate

router = APIRouter(tags=["Counterparties"])


def finance_permission(user: dict) -> bool:
    """Check if user has finance access"""
    return user["role"] in ["Admin", "Owner", "Accountant"]


# ── Counterparties CRUD ────────────────────────────────────────────

@router.get("/counterparties")
async def list_counterparties(
    user: dict = Depends(require_m5),
    type: Optional[str] = None,  # supplier, client, both
    search: Optional[str] = None,
    active_only: bool = True,
):
    """List all counterparties (suppliers/clients)"""
    query = {"org_id": user["org_id"]}
    
    if type:
        query["type"] = type
    if active_only:
        query["active"] = True
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"eik": {"$regex": search, "$options": "i"}},
            {"vat_number": {"$regex": search, "$options": "i"}},
        ]
    
    counterparties = await db.counterparties.find(query, {"_id": 0}).sort("name", 1).to_list(500)
    
    # Add invoice counts
    for cp in counterparties:
        # Count invoices where this is the supplier
        invoice_count = await db.invoices.count_documents({
            "org_id": user["org_id"],
            "supplier_counterparty_id": cp["id"]
        })
        cp["invoice_count"] = invoice_count
    
    return counterparties


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
