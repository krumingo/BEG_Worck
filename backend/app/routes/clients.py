"""
Routes - Clients (Private Persons) CRUD with pagination and filters.
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
from pydantic import BaseModel, EmailStr

router = APIRouter(tags=["Clients"])


def finance_permission(user: dict) -> bool:
    """Check if user has finance access"""
    return user["role"] in ["Admin", "Owner", "Accountant"]


def normalize_phone(phone: str) -> str:
    """Normalize phone number by removing all non-digit characters except leading +"""
    if not phone:
        return ""
    # Keep leading + if present, then only digits
    if phone.startswith("+"):
        return "+" + re.sub(r"[^0-9]", "", phone[1:])
    return re.sub(r"[^0-9]", "", phone)


def parse_filters(filters: Optional[str]) -> dict:
    """Parse filter string"""
    if not filters:
        return {}
    result = {}
    for part in filters.split(","):
        if "=" in part:
            key, value = part.split("=", 1)
            result[key] = value
    return result


def build_mongo_query(org_id: str, filters: dict, base_query: dict = None) -> dict:
    """Build MongoDB query from parsed filters"""
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
    
    return query


# ── Pydantic Models ─────────────────────────────────────────────────────────

class ClientCreate(BaseModel):
    first_name: str
    last_name: str
    phone: str
    email: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool = True


class ClientUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


# ── Clients CRUD ─────────────────────────────────────────────────────────────

@router.get("/clients")
async def list_clients(
    user: dict = Depends(require_m5),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("last_name"),
    sort_dir: str = Query("asc"),
    search: Optional[str] = None,
    filters: Optional[str] = None,
    active_only: bool = True,
):
    """List clients with pagination, sorting, and filters"""
    base_query = {"org_id": user["org_id"]}
    
    if active_only:
        base_query["is_active"] = True
    
    # Parse additional filters
    parsed_filters = parse_filters(filters)
    query = build_mongo_query(user["org_id"], parsed_filters, base_query)
    
    # Global search
    if search:
        query["$or"] = [
            {"first_name": {"$regex": re.escape(search), "$options": "i"}},
            {"last_name": {"$regex": re.escape(search), "$options": "i"}},
            {"phone": {"$regex": re.escape(search), "$options": "i"}},
            {"email": {"$regex": re.escape(search), "$options": "i"}},
            {"address": {"$regex": re.escape(search), "$options": "i"}},
        ]
    
    # Count total
    total = await db.clients.count_documents(query)
    
    # Sort
    sort_direction = 1 if sort_dir == "asc" else -1
    
    # Paginate
    skip = (page - 1) * page_size
    clients = await db.clients.find(query, {"_id": 0}).sort(sort_by, sort_direction).skip(skip).limit(page_size).to_list(page_size)
    
    # Add invoice count for each client
    for client in clients:
        # Count invoices through linked counterparties
        linked_counterparties = await db.counterparties.find(
            {"org_id": user["org_id"], "client_id": client["id"]},
            {"_id": 0, "id": 1}
        ).to_list(100)
        
        cp_ids = [cp["id"] for cp in linked_counterparties]
        if cp_ids:
            invoice_count = await db.invoices.count_documents({
                "org_id": user["org_id"],
                "supplier_counterparty_id": {"$in": cp_ids}
            })
        else:
            invoice_count = 0
        client["invoice_count"] = invoice_count
        client["linked_counterparties_count"] = len(cp_ids)
    
    return {
        "items": clients,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.post("/clients", status_code=201)
async def create_client(data: ClientCreate, user: dict = Depends(require_m5)):
    """Create a new client (private person)"""
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    # Normalize phone
    phone_normalized = normalize_phone(data.phone)
    
    if not phone_normalized:
        raise HTTPException(status_code=400, detail="Phone number is required")
    
    # Check phone uniqueness within org
    existing = await db.clients.find_one({
        "org_id": user["org_id"],
        "phone_normalized": phone_normalized
    })
    if existing:
        raise HTTPException(status_code=400, detail="Client with this phone number already exists")
    
    now = datetime.now(timezone.utc).isoformat()
    client = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "first_name": data.first_name,
        "last_name": data.last_name,
        "phone": data.phone,
        "phone_normalized": phone_normalized,
        "email": data.email,
        "address": data.address,
        "notes": data.notes,
        "is_active": data.is_active,
        "created_at": now,
        "updated_at": now,
    }
    
    await db.clients.insert_one(client)
    
    await log_audit(user["org_id"], user["id"], user["email"], "client_created", "client", client["id"],
                    {"name": f"{data.first_name} {data.last_name}", "phone": data.phone})
    
    return {k: v for k, v in client.items() if k != "_id"}


@router.get("/clients/{client_id}")
async def get_client(client_id: str, user: dict = Depends(require_m5)):
    """Get client details"""
    client = await db.clients.find_one(
        {"id": client_id, "org_id": user["org_id"]},
        {"_id": 0}
    )
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    # Get linked counterparties
    linked_counterparties = await db.counterparties.find(
        {"org_id": user["org_id"], "client_id": client_id},
        {"_id": 0, "id": 1, "name": 1, "type": 1}
    ).to_list(100)
    
    client["linked_counterparties"] = linked_counterparties
    
    return client


@router.put("/clients/{client_id}")
async def update_client(client_id: str, data: ClientUpdate, user: dict = Depends(require_m5)):
    """Update client"""
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    client = await db.clients.find_one({"id": client_id, "org_id": user["org_id"]})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    update = {}
    
    # Handle phone update with uniqueness check
    if data.phone is not None:
        phone_normalized = normalize_phone(data.phone)
        if phone_normalized != client.get("phone_normalized"):
            existing = await db.clients.find_one({
                "org_id": user["org_id"],
                "phone_normalized": phone_normalized,
                "id": {"$ne": client_id}
            })
            if existing:
                raise HTTPException(status_code=400, detail="Client with this phone number already exists")
            update["phone"] = data.phone
            update["phone_normalized"] = phone_normalized
    
    # Update other fields
    for field in ["first_name", "last_name", "email", "address", "notes", "is_active"]:
        value = getattr(data, field)
        if value is not None:
            update[field] = value
    
    if update:
        update["updated_at"] = datetime.now(timezone.utc).isoformat()
        await db.clients.update_one({"id": client_id}, {"$set": update})
    
    return await db.clients.find_one({"id": client_id}, {"_id": 0})


@router.delete("/clients/{client_id}")
async def delete_client(client_id: str, user: dict = Depends(require_m5)):
    """Delete client (soft delete if has linked counterparties)"""
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    client = await db.clients.find_one({"id": client_id, "org_id": user["org_id"]})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    # Check if has linked counterparties
    linked_count = await db.counterparties.count_documents({
        "org_id": user["org_id"],
        "client_id": client_id
    })
    
    if linked_count > 0:
        # Soft delete only
        await db.clients.update_one(
            {"id": client_id},
            {"$set": {"is_active": False, "updated_at": datetime.now(timezone.utc).isoformat()}}
        )
        return {"ok": True, "soft_deleted": True, "reason": "Has linked counterparties"}
    
    await db.clients.delete_one({"id": client_id})
    return {"ok": True}


# ── Client-Counterparty Linking ──────────────────────────────────────────────

@router.post("/clients/find-or-create")
async def find_or_create_client(data: ClientCreate, user: dict = Depends(require_m5)):
    """Find existing client by phone or create new one"""
    phone_normalized = normalize_phone(data.phone)
    
    if not phone_normalized:
        raise HTTPException(status_code=400, detail="Phone number is required")
    
    # Try to find existing client
    existing = await db.clients.find_one({
        "org_id": user["org_id"],
        "phone_normalized": phone_normalized
    }, {"_id": 0})
    
    if existing:
        return {"client": existing, "created": False}
    
    # Create new client
    now = datetime.now(timezone.utc).isoformat()
    client = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "first_name": data.first_name,
        "last_name": data.last_name,
        "phone": data.phone,
        "phone_normalized": phone_normalized,
        "email": data.email,
        "address": data.address,
        "notes": data.notes,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    
    await db.clients.insert_one(client)
    
    return {"client": {k: v for k, v in client.items() if k != "_id"}, "created": True}


@router.get("/clients/by-phone/{phone}")
async def get_client_by_phone(phone: str, user: dict = Depends(require_m5)):
    """Find client by phone number"""
    phone_normalized = normalize_phone(phone)
    
    client = await db.clients.find_one({
        "org_id": user["org_id"],
        "phone_normalized": phone_normalized
    }, {"_id": 0})
    
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    return client
