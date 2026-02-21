"""
Sites (Обекти) routes - /api/sites/*, /api/persons/*, /api/companies/*
Phase 1: Owner (person/company), Address, Status/Filters
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone
import uuid
import re

from app.db import db
from app.deps.auth import get_current_user, require_admin
from app.utils.audit import log_audit

router = APIRouter(tags=["sites"])

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

SITE_STATUSES = ["Active", "Paused", "Finished", "Archived"]
OWNER_TYPES = ["person", "company"]


# ══════════════════════════════════════════════════════════════════════════════
# MODELS - Persons (Частни лица)
# ══════════════════════════════════════════════════════════════════════════════

class PersonCreate(BaseModel):
    phone: str  # Unique key
    first_name: str
    last_name: str
    email: Optional[str] = None
    notes: Optional[str] = ""


class PersonUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# MODELS - Companies (Фирми)
# ══════════════════════════════════════════════════════════════════════════════

class CompanyCreate(BaseModel):
    eik: str  # Unique key (Bulgarian company ID)
    name: str
    mol: Optional[str] = None  # Manager name
    address: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = ""


class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    mol: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# MODELS - Sites (Обекти)
# ══════════════════════════════════════════════════════════════════════════════

class SiteCreate(BaseModel):
    name: str
    address_text: str  # Required
    owner_type: str  # "person" or "company"
    owner_id: str  # Reference to person or company
    status: str = "Active"
    project_id: Optional[str] = None  # Link to project
    notes: Optional[str] = ""


class SiteUpdate(BaseModel):
    name: Optional[str] = None
    address_text: Optional[str] = None
    owner_type: Optional[str] = None
    owner_id: Optional[str] = None
    status: Optional[str] = None
    project_id: Optional[str] = None
    notes: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def normalize_phone(phone: str) -> str:
    """Normalize phone number - keep only digits and +"""
    return re.sub(r'[^\d+]', '', phone.strip())


def normalize_eik(eik: str) -> str:
    """Normalize EIK - keep only digits"""
    return re.sub(r'\D', '', eik.strip())


async def get_owner_info(owner_type: str, owner_id: str, org_id: str) -> dict:
    """Get owner display info"""
    if owner_type == "person":
        person = await db.persons.find_one({"id": owner_id, "org_id": org_id}, {"_id": 0})
        if person:
            return {
                "owner_name": f"{person.get('first_name', '')} {person.get('last_name', '')}".strip(),
                "owner_identifier": person.get("phone", ""),
            }
    elif owner_type == "company":
        company = await db.companies.find_one({"id": owner_id, "org_id": org_id}, {"_id": 0})
        if company:
            return {
                "owner_name": company.get("name", ""),
                "owner_identifier": company.get("eik", ""),
            }
    return {"owner_name": "", "owner_identifier": ""}


# ══════════════════════════════════════════════════════════════════════════════
# PERSONS ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/persons")
async def list_persons(
    user: dict = Depends(get_current_user),
    q: Optional[str] = None,
):
    """List all persons in organization"""
    query = {"org_id": user["org_id"]}
    persons = await db.persons.find(query, {"_id": 0}).sort("last_name", 1).to_list(500)
    
    if q:
        q_lower = q.lower()
        persons = [
            p for p in persons
            if q_lower in p.get("first_name", "").lower()
            or q_lower in p.get("last_name", "").lower()
            or q_lower in p.get("phone", "").lower()
        ]
    
    return persons


@router.post("/persons", status_code=201)
async def create_person(data: PersonCreate, user: dict = Depends(get_current_user)):
    """Create a new person (private individual)"""
    org_id = user["org_id"]
    phone = normalize_phone(data.phone)
    
    if not phone:
        raise HTTPException(status_code=400, detail="Phone number is required")
    
    # Check uniqueness by phone
    existing = await db.persons.find_one({"org_id": org_id, "phone": phone})
    if existing:
        raise HTTPException(status_code=400, detail="Person with this phone already exists")
    
    now = datetime.now(timezone.utc).isoformat()
    person = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "phone": phone,
        "first_name": data.first_name.strip(),
        "last_name": data.last_name.strip(),
        "email": data.email.strip() if data.email else None,
        "notes": data.notes or "",
        "created_at": now,
        "updated_at": now,
    }
    
    await db.persons.insert_one(person)
    await log_audit(org_id, user["id"], user["email"], "created", "person", person["id"], 
                    {"phone": phone, "name": f"{data.first_name} {data.last_name}"})
    
    return {k: v for k, v in person.items() if k != "_id"}


@router.get("/persons/find-by-phone")
async def find_person_by_phone(
    phone: str,
    user: dict = Depends(get_current_user),
):
    """Find person by phone number"""
    normalized = normalize_phone(phone)
    person = await db.persons.find_one(
        {"org_id": user["org_id"], "phone": normalized},
        {"_id": 0}
    )
    if not person:
        return {"found": False, "person": None}
    return {"found": True, "person": person}


@router.get("/persons/{person_id}")
async def get_person(person_id: str, user: dict = Depends(get_current_user)):
    """Get person by ID"""
    person = await db.persons.find_one(
        {"id": person_id, "org_id": user["org_id"]},
        {"_id": 0}
    )
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    return person


@router.put("/persons/{person_id}")
async def update_person(person_id: str, data: PersonUpdate, user: dict = Depends(get_current_user)):
    """Update person"""
    person = await db.persons.find_one({"id": person_id, "org_id": user["org_id"]})
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    
    update = {k: v.strip() if isinstance(v, str) else v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    await db.persons.update_one({"id": person_id}, {"$set": update})
    await log_audit(user["org_id"], user["id"], user["email"], "updated", "person", person_id, update)
    
    return await db.persons.find_one({"id": person_id}, {"_id": 0})


@router.delete("/persons/{person_id}")
async def delete_person(person_id: str, user: dict = Depends(require_admin)):
    """Delete person (admin only)"""
    person = await db.persons.find_one({"id": person_id, "org_id": user["org_id"]})
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    
    # Check if person is used as owner
    site_count = await db.sites.count_documents({"owner_type": "person", "owner_id": person_id})
    if site_count > 0:
        raise HTTPException(status_code=400, detail=f"Cannot delete: person is owner of {site_count} site(s)")
    
    await db.persons.delete_one({"id": person_id})
    await log_audit(user["org_id"], user["id"], user["email"], "deleted", "person", person_id, 
                    {"phone": person.get("phone")})
    
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════════
# COMPANIES ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/companies")
async def list_companies(
    user: dict = Depends(get_current_user),
    q: Optional[str] = None,
):
    """List all companies in organization"""
    query = {"org_id": user["org_id"]}
    companies = await db.companies.find(query, {"_id": 0}).sort("name", 1).to_list(500)
    
    if q:
        q_lower = q.lower()
        companies = [
            c for c in companies
            if q_lower in c.get("name", "").lower()
            or q_lower in c.get("eik", "").lower()
        ]
    
    return companies


@router.post("/companies", status_code=201)
async def create_company(data: CompanyCreate, user: dict = Depends(get_current_user)):
    """Create a new company"""
    org_id = user["org_id"]
    eik = normalize_eik(data.eik)
    
    if not eik:
        raise HTTPException(status_code=400, detail="EIK is required")
    
    # Check uniqueness by EIK
    existing = await db.companies.find_one({"org_id": org_id, "eik": eik})
    if existing:
        raise HTTPException(status_code=400, detail="Company with this EIK already exists")
    
    now = datetime.now(timezone.utc).isoformat()
    company = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "eik": eik,
        "name": data.name.strip(),
        "mol": data.mol.strip() if data.mol else None,
        "address": data.address.strip() if data.address else None,
        "email": data.email.strip() if data.email else None,
        "phone": normalize_phone(data.phone) if data.phone else None,
        "notes": data.notes or "",
        "created_at": now,
        "updated_at": now,
    }
    
    await db.companies.insert_one(company)
    await log_audit(org_id, user["id"], user["email"], "created", "company", company["id"], 
                    {"eik": eik, "name": data.name})
    
    return {k: v for k, v in company.items() if k != "_id"}


@router.get("/companies/find-by-eik")
async def find_company_by_eik(
    eik: str,
    user: dict = Depends(get_current_user),
):
    """Find company by EIK"""
    normalized = normalize_eik(eik)
    company = await db.companies.find_one(
        {"org_id": user["org_id"], "eik": normalized},
        {"_id": 0}
    )
    if not company:
        return {"found": False, "company": None}
    return {"found": True, "company": company}


@router.get("/companies/{company_id}")
async def get_company(company_id: str, user: dict = Depends(get_current_user)):
    """Get company by ID"""
    company = await db.companies.find_one(
        {"id": company_id, "org_id": user["org_id"]},
        {"_id": 0}
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


@router.put("/companies/{company_id}")
async def update_company(company_id: str, data: CompanyUpdate, user: dict = Depends(get_current_user)):
    """Update company"""
    company = await db.companies.find_one({"id": company_id, "org_id": user["org_id"]})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    
    update = {}
    for k, v in data.model_dump().items():
        if v is not None:
            if k == "phone" and v:
                update[k] = normalize_phone(v)
            elif isinstance(v, str):
                update[k] = v.strip()
            else:
                update[k] = v
    
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    await db.companies.update_one({"id": company_id}, {"$set": update})
    await log_audit(user["org_id"], user["id"], user["email"], "updated", "company", company_id, update)
    
    return await db.companies.find_one({"id": company_id}, {"_id": 0})


@router.delete("/companies/{company_id}")
async def delete_company(company_id: str, user: dict = Depends(require_admin)):
    """Delete company (admin only)"""
    company = await db.companies.find_one({"id": company_id, "org_id": user["org_id"]})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    
    # Check if company is used as owner
    site_count = await db.sites.count_documents({"owner_type": "company", "owner_id": company_id})
    if site_count > 0:
        raise HTTPException(status_code=400, detail=f"Cannot delete: company is owner of {site_count} site(s)")
    
    await db.companies.delete_one({"id": company_id})
    await log_audit(user["org_id"], user["id"], user["email"], "deleted", "company", company_id, 
                    {"eik": company.get("eik")})
    
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════════
# SITES ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/site-enums")
async def get_site_enums():
    """Get site-related enums"""
    return {
        "statuses": SITE_STATUSES,
        "owner_types": OWNER_TYPES,
    }


@router.get("/sites")
async def list_sites(
    user: dict = Depends(get_current_user),
    status: Optional[str] = None,
    q: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
):
    """
    List sites with filters.
    - status: filter by status (Active, Paused, Finished, Archived)
    - q: search by name, address, owner name, phone, or EIK
    - from_date/to_date: filter by created_at range
    """
    org_id = user["org_id"]
    query = {"org_id": org_id}
    
    # Status filter
    if status:
        if status not in SITE_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status. Must be: {', '.join(SITE_STATUSES)}")
        query["status"] = status
    
    # Date range filter
    if from_date:
        query["created_at"] = {"$gte": from_date}
    if to_date:
        if "created_at" in query:
            query["created_at"]["$lte"] = to_date + "T23:59:59"
        else:
            query["created_at"] = {"$lte": to_date + "T23:59:59"}
    
    sites = await db.sites.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    
    # Enrich with owner info (batch for performance)
    person_ids = [s["owner_id"] for s in sites if s.get("owner_type") == "person"]
    company_ids = [s["owner_id"] for s in sites if s.get("owner_type") == "company"]
    
    persons_map = {}
    companies_map = {}
    
    if person_ids:
        persons = await db.persons.find(
            {"id": {"$in": person_ids}, "org_id": org_id},
            {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "phone": 1}
        ).to_list(500)
        persons_map = {p["id"]: p for p in persons}
    
    if company_ids:
        companies = await db.companies.find(
            {"id": {"$in": company_ids}, "org_id": org_id},
            {"_id": 0, "id": 1, "name": 1, "eik": 1}
        ).to_list(500)
        companies_map = {c["id"]: c for c in companies}
    
    for site in sites:
        owner_type = site.get("owner_type")
        owner_id = site.get("owner_id")
        
        if owner_type == "person" and owner_id in persons_map:
            p = persons_map[owner_id]
            site["owner_name"] = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
            site["owner_identifier"] = p.get("phone", "")
        elif owner_type == "company" and owner_id in companies_map:
            c = companies_map[owner_id]
            site["owner_name"] = c.get("name", "")
            site["owner_identifier"] = c.get("eik", "")
        else:
            site["owner_name"] = ""
            site["owner_identifier"] = ""
    
    # Search filter (after enrichment)
    if q:
        q_lower = q.lower()
        sites = [
            s for s in sites
            if q_lower in s.get("name", "").lower()
            or q_lower in s.get("address_text", "").lower()
            or q_lower in s.get("owner_name", "").lower()
            or q_lower in s.get("owner_identifier", "").lower()
        ]
    
    return sites


@router.post("/sites", status_code=201)
async def create_site(data: SiteCreate, user: dict = Depends(get_current_user)):
    """Create a new site"""
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions to create sites")
    
    org_id = user["org_id"]
    
    # Validate required fields
    if not data.address_text or not data.address_text.strip():
        raise HTTPException(status_code=400, detail="Address is required")
    
    if data.owner_type not in OWNER_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid owner type. Must be: {', '.join(OWNER_TYPES)}")
    
    if data.status not in SITE_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be: {', '.join(SITE_STATUSES)}")
    
    # Validate owner exists
    if data.owner_type == "person":
        owner = await db.persons.find_one({"id": data.owner_id, "org_id": org_id})
        if not owner:
            raise HTTPException(status_code=400, detail="Person not found")
    else:
        owner = await db.companies.find_one({"id": data.owner_id, "org_id": org_id})
        if not owner:
            raise HTTPException(status_code=400, detail="Company not found")
    
    # Validate project if provided
    if data.project_id:
        project = await db.projects.find_one({"id": data.project_id, "org_id": org_id})
        if not project:
            raise HTTPException(status_code=400, detail="Project not found")
    
    now = datetime.now(timezone.utc).isoformat()
    site = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "name": data.name.strip(),
        "address_text": data.address_text.strip(),
        "owner_type": data.owner_type,
        "owner_id": data.owner_id,
        "status": data.status,
        "project_id": data.project_id,
        "notes": data.notes or "",
        "created_at": now,
        "updated_at": now,
    }
    
    await db.sites.insert_one(site)
    await log_audit(org_id, user["id"], user["email"], "created", "site", site["id"], 
                    {"name": data.name, "address": data.address_text})
    
    # Enrich response with owner info
    owner_info = await get_owner_info(data.owner_type, data.owner_id, org_id)
    result = {k: v for k, v in site.items() if k != "_id"}
    result.update(owner_info)
    
    return result


@router.get("/sites/{site_id}")
async def get_site(site_id: str, user: dict = Depends(get_current_user)):
    """Get site by ID"""
    site = await db.sites.find_one(
        {"id": site_id, "org_id": user["org_id"]},
        {"_id": 0}
    )
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    
    # Enrich with owner info
    owner_info = await get_owner_info(site.get("owner_type"), site.get("owner_id"), user["org_id"])
    site.update(owner_info)
    
    return site


@router.put("/sites/{site_id}")
async def update_site(site_id: str, data: SiteUpdate, user: dict = Depends(get_current_user)):
    """Update site"""
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    site = await db.sites.find_one({"id": site_id, "org_id": user["org_id"]})
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    
    org_id = user["org_id"]
    update = {}
    
    for k, v in data.model_dump().items():
        if v is not None:
            if isinstance(v, str):
                update[k] = v.strip()
            else:
                update[k] = v
    
    # Validate status
    if "status" in update and update["status"] not in SITE_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    
    # Validate owner type
    if "owner_type" in update and update["owner_type"] not in OWNER_TYPES:
        raise HTTPException(status_code=400, detail="Invalid owner type")
    
    # Validate owner exists if changing
    if "owner_id" in update or "owner_type" in update:
        owner_type = update.get("owner_type", site.get("owner_type"))
        owner_id = update.get("owner_id", site.get("owner_id"))
        
        if owner_type == "person":
            owner = await db.persons.find_one({"id": owner_id, "org_id": org_id})
            if not owner:
                raise HTTPException(status_code=400, detail="Person not found")
        else:
            owner = await db.companies.find_one({"id": owner_id, "org_id": org_id})
            if not owner:
                raise HTTPException(status_code=400, detail="Company not found")
    
    # Validate address not empty
    if "address_text" in update and not update["address_text"]:
        raise HTTPException(status_code=400, detail="Address cannot be empty")
    
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    await db.sites.update_one({"id": site_id}, {"$set": update})
    await log_audit(org_id, user["id"], user["email"], "updated", "site", site_id, update)
    
    # Return updated site with owner info
    updated = await db.sites.find_one({"id": site_id}, {"_id": 0})
    owner_info = await get_owner_info(updated.get("owner_type"), updated.get("owner_id"), org_id)
    updated.update(owner_info)
    
    return updated


@router.delete("/sites/{site_id}")
async def delete_site(site_id: str, user: dict = Depends(require_admin)):
    """Delete site (admin only)"""
    site = await db.sites.find_one({"id": site_id, "org_id": user["org_id"]})
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    
    await db.sites.delete_one({"id": site_id})
    await log_audit(user["org_id"], user["id"], user["email"], "deleted", "site", site_id, 
                    {"name": site.get("name")})
    
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════════
# SITE PHOTOS ROUTES
# ══════════════════════════════════════════════════════════════════════════════

from fastapi import UploadFile, File, Form
from pathlib import Path

ALLOWED_PHOTO_TYPES = ["image/jpeg", "image/png", "image/webp", "image/heic"]
MAX_PHOTO_SIZE_MB = 10


class SitePhotoCreate(BaseModel):
    note: Optional[str] = ""


@router.get("/sites/{site_id}/photos")
async def list_site_photos(site_id: str, user: dict = Depends(get_current_user)):
    """List all photos for a site"""
    org_id = user["org_id"]
    
    # Verify site exists and user has access
    site = await db.sites.find_one({"id": site_id, "org_id": org_id}, {"_id": 0, "id": 1})
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    
    # Get photos
    photos = await db.site_photos.find(
        {"site_id": site_id, "org_id": org_id},
        {"_id": 0}
    ).sort("uploaded_at", -1).to_list(100)
    
    # Enrich with uploader names (batch)
    user_ids = list(set(p.get("uploaded_by") for p in photos if p.get("uploaded_by")))
    users_map = {}
    if user_ids:
        users = await db.users.find(
            {"id": {"$in": user_ids}},
            {"_id": 0, "id": 1, "first_name": 1, "last_name": 1}
        ).to_list(100)
        users_map = {u["id"]: f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() for u in users}
    
    for photo in photos:
        photo["uploader_name"] = users_map.get(photo.get("uploaded_by"), "")
    
    return photos


@router.post("/sites/{site_id}/photos", status_code=201)
async def upload_site_photo(
    site_id: str,
    file: UploadFile = File(...),
    note: str = Form(""),
    user: dict = Depends(get_current_user)
):
    """Upload a photo to a site"""
    org_id = user["org_id"]
    
    # Verify site exists and user has access
    site = await db.sites.find_one({"id": site_id, "org_id": org_id}, {"_id": 0, "id": 1, "name": 1})
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    
    # Validate file type
    if file.content_type not in ALLOWED_PHOTO_TYPES:
        raise HTTPException(status_code=400, detail={
            "error_code": "INVALID_FILE_TYPE",
            "message": f"File type not allowed. Allowed: {ALLOWED_PHOTO_TYPES}",
        })
    
    # Read file content
    content = await file.read()
    file_size = len(content)
    
    # Validate file size
    if file_size > MAX_PHOTO_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail={
            "error_code": "FILE_TOO_LARGE",
            "message": f"File size exceeds {MAX_PHOTO_SIZE_MB}MB limit",
        })
    
    # Generate unique filename
    ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    photo_id = str(uuid.uuid4())
    filename = f"site_{photo_id}.{ext}"
    
    # Store file
    upload_dir = Path("/app/backend/uploads/sites")
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / filename
    
    with open(file_path, "wb") as f:
        f.write(content)
    
    # Generate URL
    file_url = f"/api/sites/photos/file/{filename}"
    
    now = datetime.now(timezone.utc).isoformat()
    
    photo = {
        "id": photo_id,
        "org_id": org_id,
        "site_id": site_id,
        "url": file_url,
        "filename": file.filename,
        "stored_filename": filename,
        "content_type": file.content_type,
        "file_size": file_size,
        "note": note.strip() if note else "",
        "uploaded_by": user["id"],
        "uploaded_at": now,
    }
    
    await db.site_photos.insert_one(photo)
    await log_audit(org_id, user["id"], user["email"], "photo_uploaded", "site", site_id, 
                    {"photo_id": photo_id, "site_name": site.get("name")})
    
    # Add uploader name to response
    result = {k: v for k, v in photo.items() if k != "_id"}
    result["uploader_name"] = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
    
    return result


@router.get("/sites/photos/file/{filename}")
async def serve_site_photo(filename: str, user: dict = Depends(get_current_user)):
    """Serve site photo file"""
    from fastapi.responses import FileResponse
    
    UPLOAD_DIR = Path("/app/backend/uploads/sites")
    
    # Check for path traversal attempts
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    # Resolve path safely
    file_path = (UPLOAD_DIR / filename).resolve()
    if not str(file_path).startswith(str(UPLOAD_DIR.resolve())):
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    # Check file exists
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    # Verify photo belongs to user's org
    photo = await db.site_photos.find_one(
        {"stored_filename": filename, "org_id": user["org_id"]},
        {"_id": 0, "content_type": 1}
    )
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found or access denied")
    
    return FileResponse(file_path, media_type=photo.get("content_type", "image/jpeg"))


@router.delete("/sites/photos/{photo_id}")
async def delete_site_photo(photo_id: str, user: dict = Depends(get_current_user)):
    """Delete a site photo (owner or admin only)"""
    org_id = user["org_id"]
    
    photo = await db.site_photos.find_one({"id": photo_id, "org_id": org_id}, {"_id": 0})
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")
    
    # Only uploader or admin can delete
    if photo.get("uploaded_by") != user["id"] and user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only the uploader or admin can delete this photo")
    
    # Delete file from disk
    stored_filename = photo.get("stored_filename")
    if stored_filename:
        file_path = Path("/app/backend/uploads/sites") / stored_filename
        if file_path.exists():
            try:
                file_path.unlink()
            except OSError:
                pass
    
    # Delete from database
    await db.site_photos.delete_one({"id": photo_id})
    await log_audit(org_id, user["id"], user["email"], "photo_deleted", "site", photo.get("site_id"), 
                    {"photo_id": photo_id})
    
    return {"ok": True, "deleted": photo_id}
