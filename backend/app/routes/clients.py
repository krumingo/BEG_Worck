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


# ══════════════════════════════════════════════════════════════════════════════
# UNIFIED CLIENT SEARCH (companies + persons)
# ══════════════════════════════════════════════════════════════════════════════

def normalize_eik(eik: str) -> str:
    """Normalize EIK (Bulgarian company ID)"""
    if not eik:
        return ""
    return re.sub(r"[^0-9]", "", eik)


def normalize_egn(egn: str) -> str:
    """Normalize EGN (Bulgarian personal ID)"""
    if not egn:
        return ""
    return re.sub(r"[^0-9]", "", egn)


def mask_egn(egn: str) -> str:
    """Mask EGN for display in lists (show first 2 and last 2 digits)"""
    if not egn or len(egn) < 6:
        return egn or ""
    return egn[:2] + "****" + egn[-2:]


def validate_eik(eik: str) -> bool:
    """Basic EIK validation (9 or 13 digits)"""
    normalized = normalize_eik(eik)
    return len(normalized) in [9, 13]


def validate_egn(egn: str) -> bool:
    """Basic EGN validation (10 digits)"""
    normalized = normalize_egn(egn)
    return len(normalized) == 10


@router.get("/clients/search/unified")
async def unified_client_search(
    user: dict = Depends(get_current_user),
    query: str = Query(None, description="Search by name, EIK, EGN, phone"),
    type: str = Query(None, description="Filter by type: company or person"),
    limit: int = Query(20, ge=1, le=100),
):
    """
    Unified client search across companies and persons.
    Search by name, EIK, EGN, or phone number.
    """
    org_id = user["org_id"]
    results = []
    
    q = (query or "").strip()
    q_normalized = normalize_phone(q) if q else ""
    q_lower = q.lower() if q else ""
    
    # Search companies
    if not type or type == "company":
        companies = await db.companies.find({"org_id": org_id}, {"_id": 0}).to_list(500)
        
        for c in companies:
            if q:
                name_match = q_lower in (c.get("name") or "").lower()
                eik_match = normalize_eik(q) and normalize_eik(q) in normalize_eik(c.get("eik") or "")
                vat_match = q_lower in (c.get("vat_number") or "").lower()
                phone_match = q_normalized and q_normalized in normalize_phone(c.get("phone") or "")
                mol_match = q_lower in (c.get("mol") or "").lower()
                
                if not (name_match or eik_match or vat_match or phone_match or mol_match):
                    continue
            
            results.append({
                "id": c["id"],
                "type": "company",
                "display_name": c.get("name", ""),
                "identifier": c.get("eik", ""),
                "identifier_label": "ЕИК",
                "phone": c.get("phone", ""),
                "email": c.get("email", ""),
                "address": c.get("address", ""),
                "mol": c.get("mol", ""),
                "vat_number": c.get("vat_number", ""),
                "is_active": c.get("is_active", True),
            })
    
    # Search persons
    if not type or type == "person":
        persons = await db.persons.find({"org_id": org_id}, {"_id": 0}).to_list(500)
        
        for p in persons:
            full_name = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
            
            if q:
                name_match = q_lower in full_name.lower()
                egn_match = normalize_egn(q) and normalize_egn(q) in normalize_egn(p.get("egn") or "")
                phone_match = q_normalized and q_normalized in normalize_phone(p.get("phone") or "")
                
                if not (name_match or egn_match or phone_match):
                    continue
            
            results.append({
                "id": p["id"],
                "type": "person",
                "display_name": full_name,
                "identifier": mask_egn(p.get("egn", "")),
                "identifier_label": "ЕГН",
                "phone": p.get("phone", ""),
                "email": p.get("email", ""),
                "address": p.get("address", ""),
                "is_active": p.get("is_active", True),
            })
    
    results.sort(key=lambda x: x["display_name"].lower())
    
    return {
        "items": results[:limit],
        "total": len(results),
        "query": query,
        "type_filter": type,
    }


# ══════════════════════════════════════════════════════════════════════════════
# CREATE COMPANY CLIENT
# ══════════════════════════════════════════════════════════════════════════════

class CompanyClientCreate(BaseModel):
    company_name: str
    eik: str
    vat_number: Optional[str] = None
    mol: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None


@router.post("/clients/company", status_code=201)
async def create_company_client(
    data: CompanyClientCreate,
    user: dict = Depends(get_current_user),
):
    """Create a new company client with duplicate detection"""
    org_id = user["org_id"]
    
    eik = normalize_eik(data.eik)
    if not validate_eik(eik):
        raise HTTPException(status_code=400, detail="Невалиден ЕИК. Трябва да е 9 или 13 цифри.")
    
    existing = await db.companies.find_one({"org_id": org_id, "eik": eik})
    if existing:
        raise HTTPException(
            status_code=409, 
            detail=f"Вече съществува фирма с ЕИК {eik}: {existing.get('name')}"
        )
    
    now = datetime.now(timezone.utc).isoformat()
    company = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "name": data.company_name.strip(),
        "eik": eik,
        "vat_number": data.vat_number.strip() if data.vat_number else None,
        "mol": data.mol.strip() if data.mol else None,
        "address": data.address.strip() if data.address else None,
        "email": data.email.strip().lower() if data.email else None,
        "phone": normalize_phone(data.phone) if data.phone else None,
        "notes": data.notes or "",
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    
    await db.companies.insert_one(company)
    
    return {
        "id": company["id"],
        "type": "company",
        "display_name": company["name"],
        "identifier": company["eik"],
    }


# ══════════════════════════════════════════════════════════════════════════════
# CREATE PERSON CLIENT
# ══════════════════════════════════════════════════════════════════════════════

class PersonClientCreate(BaseModel):
    full_name: str
    egn: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None


@router.post("/clients/person", status_code=201)
async def create_person_client(
    data: PersonClientCreate,
    user: dict = Depends(get_current_user),
):
    """Create a new person client with duplicate detection"""
    org_id = user["org_id"]
    
    egn = normalize_egn(data.egn) if data.egn else None
    phone = normalize_phone(data.phone) if data.phone else None
    
    if egn and not validate_egn(egn):
        raise HTTPException(status_code=400, detail="Невалидно ЕГН. Трябва да е 10 цифри.")
    
    if egn:
        existing = await db.persons.find_one({"org_id": org_id, "egn": egn})
        if existing:
            name = f"{existing.get('first_name', '')} {existing.get('last_name', '')}".strip()
            raise HTTPException(
                status_code=409,
                detail=f"Вече съществува лице с ЕГН {mask_egn(egn)}: {name}"
            )
    
    if phone and not egn:
        existing = await db.persons.find_one({
            "org_id": org_id,
            "$or": [{"phone": data.phone}, {"phone_normalized": phone}]
        })
        if existing:
            name = f"{existing.get('first_name', '')} {existing.get('last_name', '')}".strip()
            raise HTTPException(
                status_code=409,
                detail=f"Вече съществува лице с телефон {data.phone}: {name}"
            )
    
    name_parts = data.full_name.strip().split(" ", 1)
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else ""
    
    now = datetime.now(timezone.utc).isoformat()
    person = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "first_name": first_name.strip(),
        "last_name": last_name.strip(),
        "egn": egn,
        "phone": data.phone,
        "phone_normalized": phone,
        "email": data.email.strip().lower() if data.email else None,
        "address": data.address.strip() if data.address else None,
        "notes": data.notes or "",
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    
    await db.persons.insert_one(person)
    
    return {
        "id": person["id"],
        "type": "person",
        "display_name": f"{first_name} {last_name}".strip(),
        "identifier": mask_egn(egn) if egn else "",
    }


# ══════════════════════════════════════════════════════════════════════════════
# PROJECT CLIENT ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/projects/{project_id}/client-info")
async def get_project_client_info(
    project_id: str,
    user: dict = Depends(get_current_user),
):
    """Get the client linked to a project with full details"""
    org_id = user["org_id"]
    
    project = await db.projects.find_one({"id": project_id, "org_id": org_id}, {"_id": 0})
    if not project:
        raise HTTPException(status_code=404, detail="Проектът не е намерен")
    
    owner_type = project.get("owner_type")
    owner_id = project.get("owner_id")
    
    if not owner_type or not owner_id:
        return {"has_client": False, "client": None}
    
    if owner_type == "company":
        company = await db.companies.find_one({"id": owner_id, "org_id": org_id}, {"_id": 0})
        if company:
            return {
                "has_client": True,
                "client": {
                    "id": company["id"],
                    "type": "company",
                    "display_name": company.get("name", ""),
                    "identifier": company.get("eik", ""),
                    "identifier_label": "ЕИК",
                    "phone": company.get("phone", ""),
                    "email": company.get("email", ""),
                    "address": company.get("address", ""),
                    "mol": company.get("mol", ""),
                    "vat_number": company.get("vat_number", ""),
                }
            }
    elif owner_type == "person":
        person = await db.persons.find_one({"id": owner_id, "org_id": org_id}, {"_id": 0})
        if person:
            full_name = f"{person.get('first_name', '')} {person.get('last_name', '')}".strip()
            return {
                "has_client": True,
                "client": {
                    "id": person["id"],
                    "type": "person",
                    "display_name": full_name,
                    "identifier": mask_egn(person.get("egn", "")),
                    "identifier_label": "ЕГН",
                    "phone": person.get("phone", ""),
                    "email": person.get("email", ""),
                    "address": person.get("address", ""),
                }
            }
    
    return {"has_client": False, "client": None}


@router.patch("/projects/{project_id}/client-link")
async def update_project_client_link(
    project_id: str,
    data: dict,
    user: dict = Depends(get_current_user),
):
    """Link or unlink a client to/from a project"""
    org_id = user["org_id"]
    
    project = await db.projects.find_one({"id": project_id, "org_id": org_id})
    if not project:
        raise HTTPException(status_code=404, detail="Проектът не е намерен")
    
    client_id = data.get("client_id")
    client_type = data.get("client_type")
    
    if client_id is None:
        await db.projects.update_one(
            {"id": project_id},
            {"$set": {"owner_type": None, "owner_id": None, "updated_at": datetime.now(timezone.utc).isoformat()}}
        )
        return {"ok": True, "message": "Клиентът е премахнат от проекта"}
    
    client = None
    if client_type == "company":
        client = await db.companies.find_one({"id": client_id, "org_id": org_id})
    elif client_type == "person":
        client = await db.persons.find_one({"id": client_id, "org_id": org_id})
    else:
        client = await db.companies.find_one({"id": client_id, "org_id": org_id})
        if client:
            client_type = "company"
        else:
            client = await db.persons.find_one({"id": client_id, "org_id": org_id})
            if client:
                client_type = "person"
    
    if not client:
        raise HTTPException(status_code=404, detail="Клиентът не е намерен")
    
    await db.projects.update_one(
        {"id": project_id},
        {"$set": {
            "owner_type": client_type,
            "owner_id": client_id,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }}
    )
    
    return {"ok": True, "message": "Клиентът е свързан с проекта"}



# ═══════════════════════════════════════════════════════════════════
# CLIENT SUMMARY (unified card)
# ═══════════════════════════════════════════════════════════════════

@router.get("/clients/{client_id}/summary")
async def get_client_summary(client_id: str, user: dict = Depends(require_m5)):
    """Full client summary: projects, invoices, totals, activity."""
    org_id = user["org_id"]
    client = await db.clients.find_one({"id": client_id, "org_id": org_id}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Projects linked to this client
    projects = await db.projects.find(
        {"org_id": org_id, "owner_id": client_id},
        {"_id": 0, "id": 1, "name": 1, "code": 1, "status": 1, "start_date": 1, "end_date": 1},
    ).to_list(100)

    project_summaries = []
    total_revenue = 0
    total_paid = 0
    total_outstanding = 0
    active_count = 0
    completed_count = 0
    first_date = None
    last_date = None

    for p in projects:
        pid = p["id"]
        invs = await db.invoices.find(
            {"org_id": org_id, "project_id": pid},
            {"_id": 0, "total": 1, "paid_amount": 1, "status": 1},
        ).to_list(200)
        inv_total = sum(i.get("total", 0) for i in invs)
        inv_paid = sum(i.get("paid_amount", 0) or 0 for i in invs)
        inv_due = round(inv_total - inv_paid, 2)

        project_summaries.append({
            "id": pid, "name": p["name"], "code": p.get("code", ""),
            "status": p.get("status", "Draft"),
            "start_date": p.get("start_date"), "end_date": p.get("end_date"),
            "total_invoiced": round(inv_total, 2),
            "total_paid": round(inv_paid, 2),
            "balance_due": inv_due,
        })

        total_revenue += inv_total
        total_paid += inv_paid
        total_outstanding += inv_due
        if p.get("status") == "Active":
            active_count += 1
        elif p.get("status") in ("Completed", "Finished"):
            completed_count += 1
        sd = p.get("start_date")
        if sd:
            if not first_date or sd < first_date:
                first_date = sd
            if not last_date or sd > last_date:
                last_date = sd

    # Last 10 invoices
    all_pids = [p["id"] for p in projects]
    invoices = []
    if all_pids:
        inv_docs = await db.invoices.find(
            {"org_id": org_id, "project_id": {"$in": all_pids}},
            {"_id": 0, "id": 1, "invoice_number": 1, "project_id": 1, "total": 1, "paid_amount": 1, "status": 1, "issue_date": 1},
        ).sort("issue_date", -1).to_list(10)
        pid_map = {p["id"]: p["name"] for p in projects}
        for inv in inv_docs:
            invoices.append({
                "id": inv["id"], "invoice_no": inv.get("invoice_number", ""),
                "project_name": pid_map.get(inv.get("project_id"), ""),
                "total": inv.get("total", 0), "paid": inv.get("paid_amount", 0),
                "status": inv.get("status"), "issue_date": inv.get("issue_date"),
            })

    return {
        "client": client,
        "projects": project_summaries,
        "totals": {
            "projects_count": len(projects),
            "active_projects": active_count,
            "completed_projects": completed_count,
            "total_revenue": round(total_revenue, 2),
            "total_paid": round(total_paid, 2),
            "total_outstanding": round(total_outstanding, 2),
            "first_project_date": first_date,
            "last_project_date": last_date,
        },
        "invoices": invoices,
    }


@router.get("/clients/{client_id}/projects")
async def get_client_projects(client_id: str, user: dict = Depends(require_m5)):
    org_id = user["org_id"]
    projects = await db.projects.find(
        {"org_id": org_id, "owner_id": client_id},
        {"_id": 0, "id": 1, "name": 1, "code": 1, "status": 1, "start_date": 1, "end_date": 1},
    ).to_list(100)
    return {"items": projects, "total": len(projects)}


@router.get("/clients/{client_id}/invoices")
async def get_client_invoices(client_id: str, user: dict = Depends(require_m5)):
    org_id = user["org_id"]
    projects = await db.projects.find(
        {"org_id": org_id, "owner_id": client_id}, {"_id": 0, "id": 1}
    ).to_list(100)
    pids = [p["id"] for p in projects]
    if not pids:
        return {"items": [], "total": 0}
    invoices = await db.invoices.find(
        {"org_id": org_id, "project_id": {"$in": pids}}, {"_id": 0}
    ).sort("issue_date", -1).to_list(200)
    return {"items": invoices, "total": len(invoices)}
