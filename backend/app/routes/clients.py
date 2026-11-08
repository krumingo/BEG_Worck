"""
Routes - Clients (Private Persons) CRUD with pagination and filters.
"""
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request
from typing import Any, Dict, Optional
from datetime import datetime, timezone
import uuid
import re

from app.db import db
from app.tenancy.data_access import TenantData
from app.deps.auth import get_current_user
from app.deps.modules import require_m5
from app.permissions.money_write import require_money_write
from app.utils.audit import log_audit
from app.services import counterparty_rules as cr
from app.services import master_records as mr
from app.services.master_write import audit, conflict, kw, once_in_tx, require_key
from pydantic import BaseModel, EmailStr

router = APIRouter(tags=["Clients"])


def _tenant(user: dict) -> TenantData:
    """W0-03E-A1: the session user's tenant view of the legacy database."""
    return TenantData.for_user(db, user)


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
    include_archived: bool = False,
):
    """List clients with pagination, sorting, and filters (archived hidden — R48.4)"""
    tenant = _tenant(user)
    base_query = {"org_id": user["org_id"]}
    
    if active_only:
        base_query["is_active"] = True
    
    # Parse additional filters
    parsed_filters = parse_filters(filters)
    query = build_mongo_query(user["org_id"], parsed_filters, base_query)
    query = mr.hide_archived(query, include_archived)
    
    # Global search
    if search:
        query["$or"] = [
            {"first_name": {"$regex": re.escape(search), "$options": "i"}},
            {"last_name": {"$regex": re.escape(search), "$options": "i"}},
            {"companyName": {"$regex": re.escape(search), "$options": "i"}},
            {"name": {"$regex": re.escape(search), "$options": "i"}},
            {"eik": {"$regex": re.escape(search), "$options": "i"}},
            {"phone": {"$regex": re.escape(search), "$options": "i"}},
            {"email": {"$regex": re.escape(search), "$options": "i"}},
            {"address": {"$regex": re.escape(search), "$options": "i"}},
        ]
    
    # Count total
    total = await tenant.clients.count_documents(query)
    
    # Sort
    sort_direction = 1 if sort_dir == "asc" else -1
    
    # Paginate
    skip = (page - 1) * page_size
    clients = await tenant.clients.find(query, {"_id": 0}).sort(sort_by, sort_direction).skip(skip).limit(page_size).to_list(page_size)
    
    # Add invoice count for each client
    for client in clients:
        # Count invoices through linked counterparties
        linked_counterparties = await tenant.counterparties.find(
            {"org_id": user["org_id"], "client_id": client["id"]},
            {"_id": 0, "id": 1}
        ).to_list(100)
        
        cp_ids = [cp["id"] for cp in linked_counterparties]
        if cp_ids:
            invoice_count = await tenant.invoices.count_documents({
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
async def create_client(data: ClientCreate, user: dict = Depends(require_m5),
                        idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """Create a new client (private person) — Accountant/Admin/Owner (R48.5), key (R29)"""
    mr.require_writer(user)
    require_key(idempotency_key)
    phone_normalized = normalize_phone(data.phone)
    if not phone_normalized:
        raise HTTPException(status_code=400, detail="Phone number is required")

    async def check(tenant, session):
        if await tenant.clients.find_one({"phone_normalized": phone_normalized}, {"_id": 0, "id": 1},
                                         **kw(session)):
            raise HTTPException(status_code=400, detail="Client with this phone number already exists")

    client = {
        "first_name": data.first_name, "last_name": data.last_name, "phone": data.phone,
        "phone_normalized": phone_normalized, "email": data.email, "address": data.address,
        "notes": data.notes, "is_active": True,
    }
    return await mr.create(db, user, idempotency_key, collection="clients", doc=client,
                           fingerprint=data.model_dump(), check=check)


@router.get("/clients/{client_id}")
async def get_client(client_id: str, user: dict = Depends(require_m5)):
    """Get client details"""
    tenant = _tenant(user)
    client = await tenant.clients.find_one(
        {"id": client_id, "org_id": user["org_id"]},
        {"_id": 0}
    )
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    # Get linked counterparties
    linked_counterparties = await tenant.counterparties.find(
        {"org_id": user["org_id"], "client_id": client_id},
        {"_id": 0, "id": 1, "name": 1, "type": 1}
    ).to_list(100)
    
    client["linked_counterparties"] = linked_counterparties
    
    return client


@router.put("/clients/{client_id}")
async def update_client(client_id: str, data: ClientUpdate, user: dict = Depends(require_m5),
                        idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """Update client — Accountant/Admin/Owner, key, CAS, AuditEvent (CP-01)"""
    mr.require_writer(user)
    require_key(idempotency_key)
    client = await _tenant(user).clients.get(client_id, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    if data.is_active is not None and data.is_active != (
            cr.lifecycle_of(client, "clients") == cr.LIFECYCLE_ACTIVE):
        raise HTTPException(status_code=422, detail={
            "error_code": "USE_LIFECYCLE_ROUTE",
            "message": "Активност се сменя с …/deactivate или …/reactivate (с причина)"})
    changes: Dict[str, Any] = {}
    phone_normalized = None
    if data.phone is not None:
        phone_normalized = normalize_phone(data.phone)
        if phone_normalized != client.get("phone_normalized"):
            changes["phone"] = data.phone
            changes["phone_normalized"] = phone_normalized
    for field in ["first_name", "last_name", "email", "address", "notes"]:
        value = getattr(data, field)
        if value is not None:
            changes[field] = value

    async def check(tenant, session, before):
        if "phone_normalized" in changes and await tenant.clients.find_one(
                {"phone_normalized": phone_normalized, "id": {"$ne": client_id}}, {"_id": 0, "id": 1},
                **kw(session)):
            raise HTTPException(status_code=400, detail="Client with this phone number already exists")

    return await mr.update(db, user, idempotency_key, collection="clients", record_id=client_id,
                           changes=changes, check=check,
                           fingerprint={"id": client_id, "body": data.model_dump()})


@router.delete("/clients/{client_id}")
async def delete_client(client_id: str, request: Request, user: dict = Depends(require_m5)):
    """R48.4: a client is never deleted → 409 COUNTERPARTY_NO_DELETE, nothing written."""
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    client = await _tenant(user).clients.get(client_id, {"_id": 0, "id": 1})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    raise mr.no_delete("clients")


def _lifecycle_route(collection: str, action: str):
    async def handler(record_id: str, body: Dict[str, Any] = Body(default={}),
                      user: dict = Depends(require_m5),
                      idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
        return await mr.lifecycle(db, user, idempotency_key, collection=collection,
                                  record_id=record_id, action=action, body=body)
    handler.__name__ = "%s_%s" % (action, collection)
    return handler


for _action in mr.LIFECYCLE_ACTIONS:
    router.add_api_route("/clients/{record_id}/%s" % _action, _lifecycle_route("clients", _action),
                         methods=["POST"])


# ── Client-Counterparty Linking ──────────────────────────────────────────────

@router.post("/clients/find-or-create")
async def find_or_create_client(data: ClientCreate, user: dict = Depends(require_m5),
                                idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """Find existing client by phone or create new one. Creating is a master-data write:
    Accountant/Admin/Owner only, with an Idempotency-Key (CP-01, R48.5, R29)."""
    tenant = _tenant(user)
    phone_normalized = normalize_phone(data.phone)
    if not phone_normalized:
        raise HTTPException(status_code=400, detail="Phone number is required")
    existing = await tenant.clients.find_one({"phone_normalized": phone_normalized}, {"_id": 0})
    if existing:
        return {"client": existing, "created": False}
    mr.require_writer(user)
    require_key(idempotency_key)

    async def check(tenant_, session):
        if await tenant_.clients.find_one({"phone_normalized": phone_normalized}, {"_id": 0, "id": 1},
                                          **kw(session)):
            raise conflict("CLIENT_EXISTS", "Клиент с този телефон вече съществува")

    client = {
        "first_name": data.first_name, "last_name": data.last_name, "phone": data.phone,
        "phone_normalized": phone_normalized, "email": data.email, "address": data.address,
        "notes": data.notes, "is_active": True,
    }
    return await mr.create(db, user, idempotency_key, collection="clients", doc=client,
                           fingerprint=data.model_dump(), check=check,
                           result=lambda row: {"client": row, "created": True})


@router.get("/clients/by-phone/{phone}")
async def get_client_by_phone(phone: str, user: dict = Depends(require_m5)):
    """Find client by phone number"""
    tenant = _tenant(user)
    phone_normalized = normalize_phone(phone)
    
    client = await tenant.clients.find_one({
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
    """R48.3: ``******1234`` (last 4 digits) for every reader."""
    return cr.mask_egn(egn)


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
    tenant = _tenant(user)
    org_id = user["org_id"]
    results = []
    
    q = (query or "").strip()
    q_normalized = normalize_phone(q) if q else ""
    q_lower = q.lower() if q else ""
    
    # Search companies
    if not type or type == "company":
        companies = await tenant.companies.find(mr.hide_archived({"org_id": org_id}), {"_id": 0}).to_list(500)
        
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
        persons = await tenant.persons.find(mr.hide_archived({"org_id": org_id}), {"_id": 0}).to_list(500)
        
        for p in persons:
            full_name = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
            
            if q:
                name_match = q_lower in full_name.lower()
                # FG-227 (R48.3): searching by ЕГН would confirm a person's ЕГН — only the roles
                # that may see it in full (Owner / Accountant) may search by it
                egn_match = cr.can_reveal_egn(user) and normalize_egn(q) and \
                    normalize_egn(q) in normalize_egn(p.get("egn") or "")
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
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """Create a new company client with duplicate detection (CP-01: R48.5, R29, AuditEvent)"""
    mr.require_writer(user)
    require_key(idempotency_key)
    eik = normalize_eik(data.eik)
    if not validate_eik(eik):
        raise HTTPException(status_code=400, detail="Невалиден ЕИК. Трябва да е 9 или 13 цифри.")
    tenant = _tenant(user)

    async def check(tenant_, session):
        await _claim_company_eik(tenant_, session, eik)
        if await tenant_.companies.find_one({"eik": eik}, {"_id": 0, "id": 1}, **kw(session)):
            raise conflict("EIK_ALREADY_EXISTS", "Вече съществува фирма с ЕИК %s" % eik,
                           existing_id=None)

    company = {
        "name": data.company_name.strip(),
        "eik": eik,
        "vat_number": data.vat_number.strip() if data.vat_number else None,
        "mol": data.mol.strip() if data.mol else None,
        "address": data.address.strip() if data.address else None,
        "email": data.email.strip().lower() if data.email else None,
        "phone": normalize_phone(data.phone) if data.phone else None,
        "notes": data.notes or "",
        "is_active": True,
    }
    return await company_duplicate_dq(tenant, user, eik, lambda: mr.create(
        db, user, idempotency_key, collection="companies", doc=company,
        fingerprint=data.model_dump(), check=check,
        result=lambda row: {"id": row["id"], "type": "company",
                            "display_name": row["name"], "identifier": row["eik"]}))


async def _claim_company_eik(tenant, session, eik: str) -> None:
    """Two concurrent creates of the same ЕИК write the same claim row → one conflicts."""
    await tenant.company_eik_claims.update_one(
        {"id": "eik:" + eik}, {"$set": {"touched_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True, **kw(session))


async def company_duplicate_dq(tenant, user, eik: str, work):
    """``work()``; an EIK_ALREADY_EXISTS refusal leaves a DQ row (outside the aborted tx)."""
    from app.services.master_write import dq_issue
    try:
        return await work()
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        if exc.status_code == 409 and detail.get("error_code") == "EIK_ALREADY_EXISTS":
            existing = await tenant.companies.find_one({"eik": eik}, {"_id": 0, "id": 1})
            await dq_issue(tenant, None, code="DUPLICATE_EIK", severity="critical", entity_type="company",
                           entity_id=existing["id"] if existing else None,
                           message="Опит за втора фирма със същия ЕИК", data={"eik": eik},
                           created_by=user["id"])
        raise


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
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """Create a new person client with duplicate detection (CP-01: R48.5, R29; ЕГН masked)"""
    mr.require_writer(user)
    require_key(idempotency_key)
    egn = normalize_egn(data.egn) if data.egn else None
    phone = normalize_phone(data.phone) if data.phone else None
    if egn and not validate_egn(egn):
        raise HTTPException(status_code=400, detail="Невалидно ЕГН. Трябва да е 10 цифри.")

    async def check(tenant, session):
        if egn:
            existing = await tenant.persons.find_one({"egn": egn}, {"_id": 0}, **kw(session))
            if existing:
                name = f"{existing.get('first_name', '')} {existing.get('last_name', '')}".strip()
                raise HTTPException(status_code=409,
                                    detail=f"Вече съществува лице с ЕГН {mask_egn(egn)}: {name}")
        if phone and not egn:
            existing = await tenant.persons.find_one(
                {"$or": [{"phone": data.phone}, {"phone_normalized": phone}]}, {"_id": 0}, **kw(session))
            if existing:
                name = f"{existing.get('first_name', '')} {existing.get('last_name', '')}".strip()
                raise HTTPException(status_code=409,
                                    detail=f"Вече съществува лице с телефон {data.phone}: {name}")

    name_parts = data.full_name.strip().split(" ", 1)
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else ""
    person = {
        "first_name": first_name.strip(),
        "last_name": last_name.strip(),
        "egn": egn,
        "phone": data.phone,
        "phone_normalized": phone,
        "email": data.email.strip().lower() if data.email else None,
        "address": data.address.strip() if data.address else None,
        "notes": data.notes or "",
        "is_active": True,
    }
    fp = data.model_dump()
    if fp.get("egn"):
        import hashlib
        fp["egn"] = hashlib.sha256(fp["egn"].encode()).hexdigest()   # never stored in clear
    return await mr.create(db, user, idempotency_key, collection="persons", doc=person,
                           fingerprint=fp, check=check,
                           result=lambda row: {"id": row["id"], "type": "person",
                                               "display_name": f"{first_name} {last_name}".strip(),
                                               "identifier": mask_egn(egn) if egn else ""})


# ══════════════════════════════════════════════════════════════════════════════
# PROJECT CLIENT ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/projects/{project_id}/client-info")
async def get_project_client_info(
    project_id: str,
    user: dict = Depends(get_current_user),
):
    """Get the client linked to a project with full details"""
    tenant = _tenant(user)
    org_id = user["org_id"]
    
    project = await tenant.projects.find_one({"id": project_id, "org_id": org_id}, {"_id": 0})
    if not project:
        raise HTTPException(status_code=404, detail="Проектът не е намерен")
    
    owner_type = project.get("owner_type")
    owner_id = project.get("owner_id")
    
    if not owner_type or not owner_id:
        return {"has_client": False, "client": None}
    
    if owner_type == "company":
        company = await tenant.companies.find_one({"id": owner_id, "org_id": org_id}, {"_id": 0})
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
        person = await tenant.persons.find_one({"id": owner_id, "org_id": org_id}, {"_id": 0})
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
    user: dict = Depends(require_money_write(
        "project.client_link.update", module="M5", resource_type="project")),  # SEC-01
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """Link or unlink a client to/from a project.

    R22: the client of a project is changed only by Owner / Admin / Accountant. CP-01: an
    inactive / archived client is not chosen (422); key (R29), CAS, AuditEvent."""
    mr.require_writer(user)
    key = require_key(idempotency_key)
    tenant = _tenant(user)
    data = data if isinstance(data, dict) else {}
    client_id = data.get("client_id")
    client_type = data.get("client_type")

    async def tx(session):
        project = await tenant.projects.find_one({"id": project_id}, {"_id": 0}, **kw(session))
        if not project:
            raise HTTPException(status_code=404, detail="Проектът не е намерен")
        now = datetime.now(timezone.utc).isoformat()
        ctype = client_type
        if client_id is None:
            new_type, new_id, message = None, None, "Клиентът е премахнат от проекта"
        else:
            client = None
            if ctype == "company":
                client = await tenant.companies.find_one({"id": client_id}, {"_id": 0}, **kw(session))
            elif ctype == "person":
                client = await tenant.persons.find_one({"id": client_id}, {"_id": 0}, **kw(session))
            else:
                client = await tenant.companies.find_one({"id": client_id}, {"_id": 0}, **kw(session))
                if client:
                    ctype = "company"
                else:
                    client = await tenant.persons.find_one({"id": client_id}, {"_id": 0}, **kw(session))
                    if client:
                        ctype = "person"
            if not client:
                raise HTTPException(status_code=404, detail="Клиентът не е намерен")
            if not cr.is_selectable(client, "companies" if ctype == "company" else "persons"):
                raise HTTPException(status_code=422, detail={
                    "error_code": "COUNTERPARTY_NOT_SELECTABLE",
                    "message": "Клиентът е неактивен или архивиран — не може да се избира"})
            new_type, new_id, message = ctype, client_id, "Клиентът е свързан с проекта"
        version = mr.next_version(project)
        res = await tenant.projects.update_one(
            mr.cas_filter(project),
            {"$set": {"owner_type": new_type, "owner_id": new_id, "updated_at": now, "version": version}},
            **kw(session))
        if res.matched_count != 1:
            raise conflict("VERSION_CONFLICT", "Проектът е променен междувременно — презаредете")
        await audit(db, session, user, "project.client_link_changed", entity_type="project",
                    entity_id=project_id, key=key, entity_version=str(version), source_flow="FLOW-010",
                    diff={"owner_type": {"before": project.get("owner_type"), "after": new_type},
                          "owner_id": {"before": project.get("owner_id"), "after": new_id}})
        return {"ok": True, "message": message}

    return await once_in_tx(db, user, key, "project.client_link", {"id": project_id, "body": data}, tx)



# ═══════════════════════════════════════════════════════════════════
# CLIENT SUMMARY (unified card)
# ═══════════════════════════════════════════════════════════════════

@router.get("/clients/{client_id}/summary")
async def get_client_summary(client_id: str, user: dict = Depends(require_m5)):
    """Full client summary: projects, invoices, totals, activity."""
    tenant = _tenant(user)
    org_id = user["org_id"]
    client = await tenant.clients.find_one({"id": client_id, "org_id": org_id}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Projects linked to this client
    projects = await tenant.projects.find(
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
        invs = await tenant.invoices.find(
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
        inv_docs = await tenant.invoices.find(
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
    tenant = _tenant(user)
    org_id = user["org_id"]
    projects = await tenant.projects.find(
        {"org_id": org_id, "owner_id": client_id},
        {"_id": 0, "id": 1, "name": 1, "code": 1, "status": 1, "start_date": 1, "end_date": 1},
    ).to_list(100)
    return {"items": projects, "total": len(projects)}


@router.get("/clients/{client_id}/invoices")
async def get_client_invoices(client_id: str, user: dict = Depends(require_m5)):
    tenant = _tenant(user)
    org_id = user["org_id"]
    projects = await tenant.projects.find(
        {"org_id": org_id, "owner_id": client_id}, {"_id": 0, "id": 1}
    ).to_list(100)
    pids = [p["id"] for p in projects]
    if not pids:
        return {"items": [], "total": 0}
    invoices = await tenant.invoices.find(
        {"org_id": org_id, "project_id": {"$in": pids}}, {"_id": 0}
    ).sort("issue_date", -1).to_list(200)
    return {"items": invoices, "total": len(invoices)}
