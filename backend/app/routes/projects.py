"""
Project routes - /api/projects/*, /api/project-enums, /api/persons/*, /api/companies/*
Includes owner (person/company) management merged from Sites module.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone
from pathlib import Path
import uuid
import re

from app.db import db
from app.deps.auth import (
    get_current_user, require_admin,
    can_access_project, can_manage_project, get_user_project_ids,
)
from app.deps.modules import enforce_limit
from app.utils.audit import log_audit

router = APIRouter(tags=["projects"])

# Constants
PROJECT_STATUSES = ["Draft", "Active", "Paused", "Stopped", "Completed", "Cancelled", "Overhead", "Archived", "Finished"]
PROJECT_TYPES = ["Billable", "Overhead", "Warranty"]
PROJECT_TEAM_ROLES = ["SiteManager", "Technician", "Viewer"]
OWNER_TYPES = ["person", "company"]
WARRANTY_OPTIONS = [3, 6, 12, 24]  # months
OBJECT_TYPES = ["apartment", "house", "office", "commercial", "industrial", "public", "other"]

# Models
class ProjectCreate(BaseModel):
    code: str
    name: str
    status: str = "Draft"
    type: str = "Billable"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    planned_days: Optional[int] = None
    budget_planned: Optional[float] = None
    default_site_manager_id: Optional[str] = None
    tags: List[str] = []
    notes: str = ""
    # Owner fields (from Sites merge)
    address_text: Optional[str] = None
    owner_type: Optional[str] = None  # "person" or "company"
    owner_id: Optional[str] = None
    warranty_months: Optional[int] = None  # 3, 6, 12, 24
    # Extended fields
    object_type: Optional[str] = None
    structured_address: Optional[dict] = None
    contacts: Optional[dict] = None
    invoice_details: Optional[dict] = None
    object_details: Optional[dict] = None
    parent_project_id: Optional[str] = None

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    type: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    planned_days: Optional[int] = None
    budget_planned: Optional[float] = None
    default_site_manager_id: Optional[str] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None
    # Owner fields (from Sites merge)
    address_text: Optional[str] = None
    owner_type: Optional[str] = None
    owner_id: Optional[str] = None
    warranty_months: Optional[int] = None  # 3, 6, 12, 24
    # Extended fields
    object_type: Optional[str] = None
    structured_address: Optional[dict] = None
    contacts: Optional[dict] = None
    invoice_details: Optional[dict] = None
    object_details: Optional[dict] = None
    parent_project_id: Optional[str] = None

class TeamMemberAdd(BaseModel):
    user_id: str
    role_in_project: str = "Technician"
    from_date: Optional[str] = None
    to_date: Optional[str] = None

class PhaseCreate(BaseModel):
    name: str
    order: int = 0
    status: str = "Draft"
    planned_start: Optional[str] = None
    planned_end: Optional[str] = None

class PhaseUpdate(BaseModel):
    name: Optional[str] = None
    order: Optional[int] = None
    status: Optional[str] = None
    planned_start: Optional[str] = None
    planned_end: Optional[str] = None

# Enums
@router.get("/project-enums")
async def get_project_enums():
    return {
        "statuses": PROJECT_STATUSES,
        "types": PROJECT_TYPES,
        "team_roles": PROJECT_TEAM_ROLES,
        "object_types": OBJECT_TYPES,
    }

# Project CRUD
@router.get("/projects")
async def list_projects(
    user: dict = Depends(get_current_user),
    status: Optional[str] = None,
    type: Optional[str] = None,
    search: Optional[str] = None,
):
    org_id = user["org_id"]
    query = {"org_id": org_id}
    if status:
        query["status"] = status
    if type:
        query["type"] = type
    if user["role"] not in ["Admin", "Owner", "Accountant"]:
        assigned_ids = await get_user_project_ids(user["id"])
        query["id"] = {"$in": assigned_ids}
    projects = await db.projects.find(query, {"_id": 0}).sort("updated_at", -1).to_list(1000)
    if search:
        s = search.lower()
        projects = [p for p in projects if s in p.get("code", "").lower() or s in p.get("name", "").lower()]
    for p in projects:
        if p.get("default_site_manager_id"):
            mgr = await db.users.find_one({"id": p["default_site_manager_id"]}, {"_id": 0, "first_name": 1, "last_name": 1})
            p["site_manager_name"] = f"{mgr['first_name']} {mgr['last_name']}" if mgr else ""
        else:
            p["site_manager_name"] = ""
        p["team_count"] = await db.project_team.count_documents({"project_id": p["id"], "active": True})
    return projects

@router.post("/projects", status_code=201)
async def create_project(data: ProjectCreate, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions to create projects")
    await enforce_limit(user["org_id"], "projects")
    if data.status not in PROJECT_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be: {', '.join(PROJECT_STATUSES)}")
    if data.type not in PROJECT_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid type. Must be: {', '.join(PROJECT_TYPES)}")
    # Validate owner type if provided
    if data.owner_type and data.owner_type not in OWNER_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid owner type. Must be: {', '.join(OWNER_TYPES)}")
    existing = await db.projects.find_one({"org_id": user["org_id"], "code": data.code})
    if existing:
        raise HTTPException(status_code=400, detail="Project code already exists in this organization")
    now = datetime.now(timezone.utc).isoformat()

    # Generate formatted address_text from structured_address if provided
    addr_text = data.address_text
    sa = data.structured_address
    if sa and not addr_text:
        parts = []
        if sa.get("city"): parts.append(f"гр. {sa['city']}")
        if sa.get("district"): parts.append(f"кв. {sa['district']}")
        if sa.get("street"): parts.append(sa["street"])
        if sa.get("block"): parts.append(f"бл. {sa['block']}")
        if sa.get("entrance"): parts.append(f"вх. {sa['entrance']}")
        if sa.get("floor"): parts.append(f"ет. {sa['floor']}")
        if sa.get("apartment"): parts.append(f"ап. {sa['apartment']}")
        if parts:
            addr_text = ", ".join(parts)

    project = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "code": data.code,
        "name": data.name,
        "status": data.status,
        "type": data.type,
        "start_date": data.start_date,
        "end_date": data.end_date,
        "planned_days": data.planned_days,
        "budget_planned": data.budget_planned,
        "default_site_manager_id": data.default_site_manager_id,
        "tags": data.tags,
        "notes": data.notes,
        # Owner fields
        "address_text": addr_text,
        "owner_type": data.owner_type,
        "owner_id": data.owner_id,
        "warranty_months": data.warranty_months,
        # Extended fields
        "object_type": data.object_type,
        "structured_address": data.structured_address,
        "contacts": data.contacts,
        "invoice_details": data.invoice_details,
        "object_details": data.object_details,
        "created_at": now,
        "updated_at": now,
    }
    await db.projects.insert_one(project)
    if data.default_site_manager_id:
        await db.project_team.insert_one({
            "id": str(uuid.uuid4()),
            "project_id": project["id"],
            "user_id": data.default_site_manager_id,
            "role_in_project": "SiteManager",
            "active": True,
            "from_date": data.start_date,
            "to_date": data.end_date,
        })
    await log_audit(user["org_id"], user["id"], user["email"], "created", "project", project["id"], {"code": data.code, "name": data.name})
    return {k: v for k, v in project.items() if k != "_id"}

@router.get("/projects/{project_id}")
async def get_project(project_id: str, user: dict = Depends(get_current_user)):
    project = await db.projects.find_one({"id": project_id, "org_id": user["org_id"]}, {"_id": 0})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not await can_access_project(user, project_id):
        raise HTTPException(status_code=403, detail="Access denied")
    if project.get("default_site_manager_id"):
        mgr = await db.users.find_one({"id": project["default_site_manager_id"]}, {"_id": 0, "first_name": 1, "last_name": 1})
        project["site_manager_name"] = f"{mgr['first_name']} {mgr['last_name']}" if mgr else ""
    else:
        project["site_manager_name"] = ""
    project["team_count"] = await db.project_team.count_documents({"project_id": project_id, "active": True})
    return project

@router.put("/projects/{project_id}")
async def update_project(project_id: str, data: ProjectUpdate, user: dict = Depends(get_current_user)):
    project = await db.projects.find_one({"id": project_id, "org_id": user["org_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not await can_manage_project(user, project_id):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    if "status" in update and update["status"] not in PROJECT_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    
    # Enforce status transitions
    if "status" in update:
        TRANSITIONS = {
            "Draft": ["Active", "Cancelled"],
            "Active": ["Paused", "Stopped", "Completed"],
            "Paused": ["Active", "Stopped", "Cancelled"],
            "Stopped": ["Active", "Cancelled"],
            "Completed": ["Archived"],
            "Cancelled": ["Archived"],
            "Overhead": ["Active", "Archived"],
            "Archived": [],
        }
        current_status = project.get("status", "Draft")
        new_status = update["status"]
        if current_status != new_status:
            allowed = TRANSITIONS.get(current_status, [])
            if new_status not in allowed:
                raise HTTPException(
                    status_code=400,
                    detail=f"Не е позволен преход от {current_status} към {new_status}. Позволени: {', '.join(allowed) if allowed else 'няма'}",
                )
    if "type" in update and update["type"] not in PROJECT_TYPES:
        raise HTTPException(status_code=400, detail="Invalid type")
    # Auto-generate address_text from structured_address
    sa = update.get("structured_address")
    if sa and "address_text" not in update:
        parts = []
        if sa.get("city"): parts.append(f"гр. {sa['city']}")
        if sa.get("district"): parts.append(f"кв. {sa['district']}")
        if sa.get("street"): parts.append(sa["street"])
        if sa.get("block"): parts.append(f"бл. {sa['block']}")
        if sa.get("entrance"): parts.append(f"вх. {sa['entrance']}")
        if sa.get("floor"): parts.append(f"ет. {sa['floor']}")
        if sa.get("apartment"): parts.append(f"ап. {sa['apartment']}")
        if parts:
            update["address_text"] = ", ".join(parts)
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.projects.update_one({"id": project_id}, {"$set": update})
    await log_audit(user["org_id"], user["id"], user["email"], "updated", "project", project_id, update)
    return await db.projects.find_one({"id": project_id}, {"_id": 0})

@router.delete("/projects/{project_id}")
async def delete_project(project_id: str, user: dict = Depends(require_admin)):
    project = await db.projects.find_one({"id": project_id, "org_id": user["org_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    # Guard: don't delete parent with children
    child_count = await db.projects.count_documents({"parent_project_id": project_id, "org_id": user["org_id"]})
    if child_count > 0:
        raise HTTPException(status_code=400, detail=f"Обектът има {child_count} под-обекта. Изтрийте или преместете ги първо.")
    await db.projects.delete_one({"id": project_id})
    await db.project_team.delete_many({"project_id": project_id})
    await db.project_phases.delete_many({"project_id": project_id})
    await log_audit(user["org_id"], user["id"], user["email"], "deleted", "project", project_id, {"code": project.get("code")})
    return {"ok": True}

# ── Extended Project Details Endpoints ──────────────────────────────

@router.get("/projects/{project_id}/invoice-details")
async def get_invoice_details(project_id: str, user: dict = Depends(get_current_user)):
    project = await db.projects.find_one({"id": project_id, "org_id": user["org_id"]}, {"_id": 0, "invoice_details": 1, "id": 1})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project_id": project_id, "invoice_details": project.get("invoice_details") or {}}


@router.post("/projects/{project_id}/import-client-invoice")
async def import_client_invoice(project_id: str, user: dict = Depends(get_current_user)):
    """Copy invoice_details from the project's linked client/company record."""
    project = await db.projects.find_one({"id": project_id, "org_id": user["org_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not await can_manage_project(user, project_id):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    owner_id = project.get("owner_id")
    owner_type = project.get("owner_type")
    if not owner_id:
        raise HTTPException(status_code=400, detail="Project has no linked client")

    invoice = {}
    if owner_type == "company":
        company = await db.companies.find_one({"id": owner_id, "org_id": user["org_id"]}, {"_id": 0})
        if not company:
            company = await db.clients.find_one({"id": owner_id, "org_id": user["org_id"]}, {"_id": 0})
        if company:
            invoice = {
                "company_name": company.get("name") or company.get("companyName") or "",
                "eik": company.get("eik") or "",
                "vat_number": company.get("vat_number") or company.get("vatNumber") or "",
                "mol": company.get("mol") or "",
                "registered_address": company.get("address") or "",
                "correspondence_address": "",
                "bank_name": "",
                "iban": "",
                "is_vat_registered": bool(company.get("vat_number") or company.get("vatNumber")),
                "notes": "",
            }
    elif owner_type == "person":
        person = await db.persons.find_one({"id": owner_id, "org_id": user["org_id"]}, {"_id": 0})
        if not person:
            person = await db.clients.find_one({"id": owner_id, "org_id": user["org_id"]}, {"_id": 0})
        if person:
            invoice = {
                "company_name": person.get("full_name") or person.get("fullName") or f"{person.get('first_name', '')} {person.get('last_name', '')}".strip(),
                "eik": person.get("egn") or "",
                "registered_address": person.get("address") or "",
                "is_vat_registered": False,
            }

    if not invoice:
        raise HTTPException(status_code=404, detail="Client data not found")

    now = datetime.now(timezone.utc).isoformat()
    await db.projects.update_one({"id": project_id}, {"$set": {"invoice_details": invoice, "updated_at": now}})
    return {"ok": True, "invoice_details": invoice}


# Team routes
@router.get("/projects/{project_id}/team")
async def list_project_team(project_id: str, user: dict = Depends(get_current_user)):
    project = await db.projects.find_one({"id": project_id, "org_id": user["org_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not await can_access_project(user, project_id):
        raise HTTPException(status_code=403, detail="Access denied")
    members = await db.project_team.find({"project_id": project_id, "active": True}, {"_id": 0}).to_list(100)
    for m in members:
        u = await db.users.find_one({"id": m["user_id"]}, {"_id": 0, "first_name": 1, "last_name": 1, "email": 1, "role": 1})
        if u:
            m["user_name"] = f"{u['first_name']} {u['last_name']}"
            m["user_email"] = u["email"]
            m["user_role"] = u["role"]
        else:
            m["user_name"] = "Unknown"
            m["user_email"] = ""
            m["user_role"] = ""
    return members

@router.post("/projects/{project_id}/team", status_code=201)
async def add_team_member(project_id: str, data: TeamMemberAdd, user: dict = Depends(get_current_user)):
    project = await db.projects.find_one({"id": project_id, "org_id": user["org_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not await can_manage_project(user, project_id):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if data.role_in_project not in PROJECT_TEAM_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be: {', '.join(PROJECT_TEAM_ROLES)}")
    target_user = await db.users.find_one({"id": data.user_id, "org_id": user["org_id"]})
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found in organization")
    existing = await db.project_team.find_one({"project_id": project_id, "user_id": data.user_id, "active": True})
    if existing:
        raise HTTPException(status_code=400, detail="User already on team")
    member = {
        "id": str(uuid.uuid4()),
        "project_id": project_id,
        "user_id": data.user_id,
        "role_in_project": data.role_in_project,
        "active": True,
        "from_date": data.from_date,
        "to_date": data.to_date,
    }
    await db.project_team.insert_one(member)
    await log_audit(user["org_id"], user["id"], user["email"], "team_added", "project", project_id, {"member_id": data.user_id, "role": data.role_in_project})
    return {k: v for k, v in member.items() if k != "_id"}

@router.delete("/projects/{project_id}/team/{member_id}")
async def remove_team_member(project_id: str, member_id: str, user: dict = Depends(get_current_user)):
    project = await db.projects.find_one({"id": project_id, "org_id": user["org_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not await can_manage_project(user, project_id):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    result = await db.project_team.update_one({"id": member_id, "project_id": project_id}, {"$set": {"active": False}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Team member not found")
    await log_audit(user["org_id"], user["id"], user["email"], "team_removed", "project", project_id, {"member_id": member_id})
    return {"ok": True}

# Phase routes
@router.get("/projects/{project_id}/phases")
async def list_phases(project_id: str, user: dict = Depends(get_current_user)):
    project = await db.projects.find_one({"id": project_id, "org_id": user["org_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not await can_access_project(user, project_id):
        raise HTTPException(status_code=403, detail="Access denied")
    return await db.project_phases.find({"project_id": project_id}, {"_id": 0}).sort("order", 1).to_list(100)

@router.post("/projects/{project_id}/phases", status_code=201)
async def create_phase(project_id: str, data: PhaseCreate, user: dict = Depends(get_current_user)):
    project = await db.projects.find_one({"id": project_id, "org_id": user["org_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not await can_manage_project(user, project_id):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    phase = {
        "id": str(uuid.uuid4()),
        "project_id": project_id,
        "name": data.name,
        "order": data.order,
        "status": data.status,
        "planned_start": data.planned_start,
        "planned_end": data.planned_end,
    }
    await db.project_phases.insert_one(phase)
    await log_audit(user["org_id"], user["id"], user["email"], "phase_created", "project", project_id, {"phase": data.name})
    return {k: v for k, v in phase.items() if k != "_id"}

@router.put("/projects/{project_id}/phases/{phase_id}")
async def update_phase(project_id: str, phase_id: str, data: PhaseUpdate, user: dict = Depends(get_current_user)):
    project = await db.projects.find_one({"id": project_id, "org_id": user["org_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not await can_manage_project(user, project_id):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    result = await db.project_phases.update_one({"id": phase_id, "project_id": project_id}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Phase not found")
    return await db.project_phases.find_one({"id": phase_id}, {"_id": 0})

@router.delete("/projects/{project_id}/phases/{phase_id}")
async def delete_phase(project_id: str, phase_id: str, user: dict = Depends(get_current_user)):
    project = await db.projects.find_one({"id": project_id, "org_id": user["org_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not await can_manage_project(user, project_id):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    result = await db.project_phases.delete_one({"id": phase_id, "project_id": project_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Phase not found")
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════════
# OWNER HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def normalize_phone(phone: str) -> str:
    """Normalize phone number - keep only digits and +"""
    return re.sub(r'[^\d+]', '', phone.strip())


def normalize_eik(eik: str) -> str:
    """Normalize EIK - keep only digits"""
    return re.sub(r'\D', '', eik.strip())


async def get_owner_info(owner_type: str, owner_id: str, org_id: str) -> dict:
    """Get owner display info for a project"""
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
# PERSONS (ЧАСТНИ ЛИЦА) - Owners for Projects
# ══════════════════════════════════════════════════════════════════════════════

class PersonCreate(BaseModel):
    phone: str
    first_name: str
    last_name: str
    email: Optional[str] = None
    notes: Optional[str] = ""


class PersonUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None


@router.get("/persons")
async def list_persons(user: dict = Depends(get_current_user), q: Optional[str] = None):
    """List all persons in organization"""
    query = {"org_id": user["org_id"]}
    persons = await db.persons.find(query, {"_id": 0}).sort("last_name", 1).to_list(500)
    if q:
        q_lower = q.lower()
        persons = [p for p in persons if q_lower in p.get("first_name", "").lower()
                   or q_lower in p.get("last_name", "").lower()
                   or q_lower in p.get("phone", "").lower()]
    return persons


@router.post("/persons", status_code=201)
async def create_person(data: PersonCreate, user: dict = Depends(get_current_user)):
    """Create a new person"""
    org_id = user["org_id"]
    phone = normalize_phone(data.phone)
    if not phone:
        raise HTTPException(status_code=400, detail="Phone number is required")
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
async def find_person_by_phone(phone: str, user: dict = Depends(get_current_user)):
    """Find person by phone number"""
    normalized = normalize_phone(phone)
    person = await db.persons.find_one({"org_id": user["org_id"], "phone": normalized}, {"_id": 0})
    if not person:
        return {"found": False, "person": None}
    return {"found": True, "person": person}


@router.get("/persons/{person_id}")
async def get_person(person_id: str, user: dict = Depends(get_current_user)):
    """Get person by ID"""
    person = await db.persons.find_one({"id": person_id, "org_id": user["org_id"]}, {"_id": 0})
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
    return await db.persons.find_one({"id": person_id}, {"_id": 0})


@router.delete("/persons/{person_id}")
async def delete_person(person_id: str, user: dict = Depends(require_admin)):
    """Delete person (admin only)"""
    person = await db.persons.find_one({"id": person_id, "org_id": user["org_id"]})
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    project_count = await db.projects.count_documents({"owner_type": "person", "owner_id": person_id})
    if project_count > 0:
        raise HTTPException(status_code=400, detail=f"Cannot delete: person is owner of {project_count} project(s)")
    await db.persons.delete_one({"id": person_id})
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════════
# COMPANIES (ФИРМИ) - Owners for Projects
# ══════════════════════════════════════════════════════════════════════════════

class CompanyCreate(BaseModel):
    eik: str
    name: str
    vat_number: Optional[str] = None
    mol: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = ""


class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    vat_number: Optional[str] = None
    mol: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None


@router.get("/companies")
async def list_companies(user: dict = Depends(get_current_user), q: Optional[str] = None):
    """List all companies in organization"""
    query = {"org_id": user["org_id"]}
    companies = await db.companies.find(query, {"_id": 0}).sort("name", 1).to_list(500)
    if q:
        q_lower = q.lower()
        companies = [c for c in companies if q_lower in c.get("name", "").lower() or q_lower in c.get("eik", "").lower()]
    return companies


@router.post("/companies", status_code=201)
async def create_company(data: CompanyCreate, user: dict = Depends(get_current_user)):
    """Create a new company"""
    org_id = user["org_id"]
    eik = normalize_eik(data.eik)
    if not eik:
        raise HTTPException(status_code=400, detail="EIK is required")
    existing = await db.companies.find_one({"org_id": org_id, "eik": eik})
    if existing:
        raise HTTPException(status_code=400, detail="Company with this EIK already exists")
    now = datetime.now(timezone.utc).isoformat()
    company = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "eik": eik,
        "name": data.name.strip(),
        "vat_number": data.vat_number.strip() if data.vat_number else None,
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
async def find_company_by_eik(eik: str, user: dict = Depends(get_current_user)):
    """Find company by EIK"""
    normalized = normalize_eik(eik)
    company = await db.companies.find_one({"org_id": user["org_id"], "eik": normalized}, {"_id": 0})
    if not company:
        return {"found": False, "company": None}
    return {"found": True, "company": company}


@router.get("/companies/{company_id}")
async def get_company(company_id: str, user: dict = Depends(get_current_user)):
    """Get company by ID"""
    company = await db.companies.find_one({"id": company_id, "org_id": user["org_id"]}, {"_id": 0})
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
    return await db.companies.find_one({"id": company_id}, {"_id": 0})


@router.delete("/companies/{company_id}")
async def delete_company(company_id: str, user: dict = Depends(require_admin)):
    """Delete company (admin only)"""
    company = await db.companies.find_one({"id": company_id, "org_id": user["org_id"]})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    project_count = await db.projects.count_documents({"owner_type": "company", "owner_id": company_id})
    if project_count > 0:
        raise HTTPException(status_code=400, detail=f"Cannot delete: company is owner of {project_count} project(s)")
    await db.companies.delete_one({"id": company_id})
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════════
# PROJECT PHOTOS
# ══════════════════════════════════════════════════════════════════════════════

ALLOWED_PHOTO_TYPES = ["image/jpeg", "image/png", "image/webp", "image/heic"]
MAX_PHOTO_SIZE_MB = 10


@router.get("/projects/{project_id}/photos")
async def list_project_photos(project_id: str, user: dict = Depends(get_current_user)):
    """List all photos for a project"""
    org_id = user["org_id"]
    project = await db.projects.find_one({"id": project_id, "org_id": org_id}, {"_id": 0, "id": 1})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    photos = await db.project_photos.find({"project_id": project_id, "org_id": org_id}, {"_id": 0}).sort("uploaded_at", -1).to_list(100)
    user_ids = list(set(p.get("uploaded_by") for p in photos if p.get("uploaded_by")))
    users_map = {}
    if user_ids:
        users = await db.users.find({"id": {"$in": user_ids}}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1}).to_list(100)
        users_map = {u["id"]: f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() for u in users}
    for photo in photos:
        photo["uploader_name"] = users_map.get(photo.get("uploaded_by"), "")
    return photos


@router.post("/projects/{project_id}/photos", status_code=201)
async def upload_project_photo(
    project_id: str,
    file: UploadFile = File(...),
    note: str = Form(""),
    user: dict = Depends(get_current_user)
):
    """Upload a photo to a project"""
    org_id = user["org_id"]
    project = await db.projects.find_one({"id": project_id, "org_id": org_id}, {"_id": 0, "id": 1, "name": 1})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if file.content_type not in ALLOWED_PHOTO_TYPES:
        raise HTTPException(status_code=400, detail={"error_code": "INVALID_FILE_TYPE", "message": f"Allowed: {ALLOWED_PHOTO_TYPES}"})
    content = await file.read()
    file_size = len(content)
    if file_size > MAX_PHOTO_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail={"error_code": "FILE_TOO_LARGE", "message": f"Max {MAX_PHOTO_SIZE_MB}MB"})
    ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    photo_id = str(uuid.uuid4())
    filename = f"project_{photo_id}.{ext}"
    upload_dir = Path("/app/backend/uploads/projects")
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / filename
    with open(file_path, "wb") as f:
        f.write(content)
    file_url = f"/api/projects/photos/file/{filename}"
    now = datetime.now(timezone.utc).isoformat()
    photo = {
        "id": photo_id,
        "org_id": org_id,
        "project_id": project_id,
        "url": file_url,
        "filename": file.filename,
        "stored_filename": filename,
        "content_type": file.content_type,
        "file_size": file_size,
        "note": note.strip() if note else "",
        "uploaded_by": user["id"],
        "uploaded_at": now,
    }
    await db.project_photos.insert_one(photo)
    await log_audit(org_id, user["id"], user["email"], "photo_uploaded", "project", project_id, {"photo_id": photo_id})
    result = {k: v for k, v in photo.items() if k != "_id"}
    result["uploader_name"] = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
    return result


@router.get("/projects/photos/file/{filename}")
async def serve_project_photo(filename: str, user: dict = Depends(get_current_user)):
    """Serve project photo file"""
    from fastapi.responses import FileResponse
    UPLOAD_DIR = Path("/app/backend/uploads/projects")
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    file_path = (UPLOAD_DIR / filename).resolve()
    if not str(file_path).startswith(str(UPLOAD_DIR.resolve())):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    photo = await db.project_photos.find_one({"stored_filename": filename, "org_id": user["org_id"]}, {"_id": 0, "content_type": 1})
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found or access denied")
    return FileResponse(file_path, media_type=photo.get("content_type", "image/jpeg"))


@router.delete("/projects/photos/{photo_id}")
async def delete_project_photo(photo_id: str, user: dict = Depends(get_current_user)):
    """Delete a project photo (owner or admin only)"""
    org_id = user["org_id"]
    photo = await db.project_photos.find_one({"id": photo_id, "org_id": org_id}, {"_id": 0})
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")
    if photo.get("uploaded_by") != user["id"] and user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only the uploader or admin can delete this photo")
    stored_filename = photo.get("stored_filename")
    if stored_filename:
        file_path = Path("/app/backend/uploads/projects") / stored_filename
        if file_path.exists():
            try:
                file_path.unlink()
            except OSError:
                pass
    await db.project_photos.delete_one({"id": photo_id})
    await log_audit(org_id, user["id"], user["email"], "photo_deleted", "project", photo.get("project_id"), {"photo_id": photo_id})
    return {"ok": True, "deleted": photo_id}


# ══════════════════════════════════════════════════════════════════════════════
# PROJECT DASHBOARD - Single endpoint for all card data
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/projects/{project_id}/dashboard")
async def get_project_dashboard(project_id: str, user: dict = Depends(get_current_user)):
    """
    Get all dashboard data for a project in one call.
    Returns structured data for all 8 cards.
    """
    org_id = user["org_id"]
    
    # ── Fetch project ───────────────────────────────────────────────────────
    project = await db.projects.find_one({"id": project_id, "org_id": org_id}, {"_id": 0})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # ── Card 1: Project Info ────────────────────────────────────────────────
    card_project = {
        "id": project["id"],
        "code": project.get("code", ""),
        "name": project.get("name", ""),
        "status": project.get("status", ""),
        "type": project.get("type", ""),
        "warranty_months": project.get("warranty_months"),
        "address_text": project.get("address_text", ""),
        "notes": project.get("notes", ""),
        "parent_project_id": project.get("parent_project_id"),
    }

    # ── Sub-projects ────────────────────────────────────────────────────
    children = await db.projects.find(
        {"org_id": org_id, "parent_project_id": project_id},
        {"_id": 0, "id": 1, "code": 1, "name": 1, "status": 1, "type": 1},
    ).sort("code", 1).to_list(50)

    # Parent info if this is a child
    parent_info = None
    if project.get("parent_project_id"):
        parent = await db.projects.find_one(
            {"id": project["parent_project_id"], "org_id": org_id},
            {"_id": 0, "id": 1, "code": 1, "name": 1},
        )
        parent_info = parent
    
    # ── Card 2: Owner/Client Info ───────────────────────────────────────────
    # For child projects, inherit shared data from parent
    effective_project = project
    if project.get("parent_project_id"):
        parent_full = await db.projects.find_one(
            {"id": project["parent_project_id"], "org_id": org_id},
            {"_id": 0, "owner_type": 1, "owner_id": 1, "address_text": 1,
             "structured_address": 1, "contacts": 1, "invoice_details": 1},
        )
        if parent_full:
            effective_project = {**project}
            for field in ["owner_type", "owner_id", "address_text", "structured_address", "contacts", "invoice_details"]:
                if not effective_project.get(field) and parent_full.get(field):
                    effective_project[field] = parent_full[field]

    card_client = {
        "owner_type": effective_project.get("owner_type"),
        "owner_id": effective_project.get("owner_id"),
        "owner_data": None,
    }
    
    if effective_project.get("owner_type") == "person" and effective_project.get("owner_id"):
        person = await db.persons.find_one({"id": effective_project["owner_id"], "org_id": org_id}, {"_id": 0})
        if person:
            card_client["owner_data"] = {
                "type": "person",
                "first_name": person.get("first_name", ""),
                "last_name": person.get("last_name", ""),
                "phone": person.get("phone", ""),
                "email": person.get("email", ""),
                "notes": person.get("notes", ""),
            }
    elif effective_project.get("owner_type") == "company" and effective_project.get("owner_id"):
        company = await db.companies.find_one({"id": effective_project["owner_id"], "org_id": org_id}, {"_id": 0})
        if company:
            card_client["owner_data"] = {
                "type": "company",
                "name": company.get("name", ""),
                "eik": company.get("eik", ""),
                "vat_number": company.get("vat_number", ""),
                "mol": company.get("mol", ""),
                "phone": company.get("phone", ""),
                "email": company.get("email", ""),
                "address": company.get("address", ""),
                "notes": company.get("notes", ""),
            }
    
    # ── Card 3: Progress/Timeline ───────────────────────────────────────────
    start_date = project.get("start_date")
    end_date = project.get("end_date")
    planned_days = project.get("planned_days") or 0
    
    days_total = 0
    days_elapsed = 0
    days_remaining = 0
    progress_percent = 0
    
    if start_date and end_date:
        try:
            from datetime import date
            start = date.fromisoformat(start_date[:10])
            end = date.fromisoformat(end_date[:10])
            today = date.today()
            
            days_total = (end - start).days
            if days_total > 0:
                days_elapsed = min(max((today - start).days, 0), days_total)
                days_remaining = max(days_total - days_elapsed, 0)
                progress_percent = round((days_elapsed / days_total) * 100, 1)
        except:
            pass
    
    card_progress = {
        "start_date": start_date,
        "end_date": end_date,
        "planned_days": planned_days,
        "days_total": days_total,
        "days_elapsed": days_elapsed,
        "days_remaining": days_remaining,
        "progress_percent": progress_percent,
    }
    
    # ── Card 4: Team/Personnel ──────────────────────────────────────────────
    team_members = await db.project_team.find(
        {"project_id": project_id, "active": True},
        {"_id": 0}
    ).to_list(100)
    
    user_ids = [m["user_id"] for m in team_members]
    users_map = {}
    if user_ids:
        users = await db.users.find(
            {"id": {"$in": user_ids}},
            {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "role": 1}
        ).to_list(100)
        users_map = {u["id"]: u for u in users}
    
    team_list = []
    for m in team_members:
        u = users_map.get(m["user_id"], {})
        team_list.append({
            "user_id": m["user_id"],
            "name": f"{u.get('first_name', '')} {u.get('last_name', '')}".strip(),
            "role_in_project": m.get("role_in_project", ""),
            "system_role": u.get("role", ""),
        })
    
    # Calculate total paid salaries for this project (from payroll if exists)
    total_salaries_paid = 0
    try:
        payroll_entries = await db.payroll_entries.find(
            {"project_id": project_id, "org_id": org_id, "status": "Paid"},
            {"_id": 0, "net_pay": 1}
        ).to_list(1000)
        total_salaries_paid = sum(e.get("net_pay", 0) for e in payroll_entries)
    except:
        pass
    
    card_team = {
        "members": team_list,
        "count": len(team_list),
        "total_salaries_paid": total_salaries_paid,
    }

    # Reported/Approved today for this project (from employee_daily_reports)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    drafts_today = await db.employee_daily_reports.find(
        {"org_id": org_id, "project_id": project_id, "date": today, "worker_id": {"$exists": True}},
        {"_id": 0, "worker_id": 1, "worker_name": 1, "hours": 1, "status": 1},
    ).to_list(200)

    # Also check new-style daily reports (day_entries with project_id)
    new_style_reports = await db.employee_daily_reports.find(
        {"org_id": org_id, "report_date": today, "day_entries.project_id": project_id},
        {"_id": 0, "employee_id": 1, "day_entries": 1, "approval_status": 1},
    ).to_list(200)

    reported_ids = set()
    approved_ids = set()
    total_hours = 0

    # Old-style reports
    for d in drafts_today:
        reported_ids.add(d.get("worker_id"))
        total_hours += d.get("hours", 0)
        if (d.get("status") or "").upper() == "APPROVED":
            approved_ids.add(d.get("worker_id"))

    # New-style reports
    for r in new_style_reports:
        emp_id = r.get("employee_id")
        if emp_id:
            reported_ids.add(emp_id)
            if (r.get("approval_status") or "").upper() == "APPROVED":
                approved_ids.add(emp_id)
            for entry in r.get("day_entries", []):
                if entry.get("project_id") == project_id:
                    total_hours += float(entry.get("hours_worked", 0))

    card_team["reported_today"] = len(reported_ids)
    card_team["approved_today"] = len(approved_ids)
    card_team["reported_hours"] = round(total_hours, 1)

    # "На обекта днес" = attendance_entries for today (source of truth from Теренен портал → Хора)
    attendance_today = await db.attendance_entries.find(
        {"org_id": org_id, "project_id": project_id, "date": today,
         "status": {"$in": ["Present", "Late"]}},
        {"_id": 0, "user_id": 1},
    ).to_list(200)
    on_site_ids = set(a["user_id"] for a in attendance_today)
    # Also count reported workers as "on site" (fallback for projects without formal attendance)
    on_site_ids |= reported_ids
    card_team["on_site_today"] = len(on_site_ids)

    # Pending approval count for this project
    pending = await db.employee_daily_reports.count_documents(
        {"org_id": org_id, "project_id": project_id, "status": "SUBMITTED"}
    )
    card_team["pending_approval"] = pending
    
    # ── Card 5: Invoices ────────────────────────────────────────────────────
    # Source of truth: invoice.paid_amount, invoice.remaining_amount, invoice.total
    invoices = await db.invoices.find(
        {"project_id": project_id, "org_id": org_id},
        {"_id": 0}
    ).sort("created_at", -1).to_list(500)
    
    invoice_list = []
    totals_paid = 0
    totals_unpaid = 0
    totals_subtotal = 0
    totals_vat = 0
    totals_total = 0
    
    # Batch-fetch all payment allocations for this project's invoices
    invoice_ids = [inv.get("id") for inv in invoices if inv.get("id")]
    all_allocations = []
    if invoice_ids:
        all_allocations = await db.payment_allocations.find(
            {"invoice_id": {"$in": invoice_ids}},
            {"_id": 0}
        ).sort("allocated_at", -1).to_list(2000)
    
    # Batch-fetch all related finance_payments
    payment_ids = list(set(a.get("payment_id") for a in all_allocations if a.get("payment_id")))
    payments_map = {}
    if payment_ids:
        fp_list = await db.finance_payments.find(
            {"id": {"$in": payment_ids}},
            {"_id": 0, "id": 1, "date": 1, "method": 1, "reference": 1, "note": 1}
        ).to_list(2000)
        payments_map = {fp["id"]: fp for fp in fp_list}
    
    # Group allocations by invoice_id
    alloc_by_invoice = {}
    for a in all_allocations:
        inv_id = a.get("invoice_id")
        if inv_id not in alloc_by_invoice:
            alloc_by_invoice[inv_id] = []
        fp = payments_map.get(a.get("payment_id"), {})
        alloc_by_invoice[inv_id].append({
            "id": a.get("id"),
            "amount": a.get("amount_allocated", 0),
            "date": fp.get("date"),
            "method": fp.get("method"),
            "reference": fp.get("reference"),
            "note": fp.get("note"),
        })
    
    for inv in invoices:
        subtotal = inv.get("subtotal", 0) or 0
        vat_amount = inv.get("vat_amount", 0) or 0
        total = inv.get("total", 0) or 0
        paid_amount = inv.get("paid_amount", 0) or 0
        remaining_amount = inv.get("remaining_amount", total) if inv.get("remaining_amount") is not None else total
        
        # Skip cancelled invoices from financial totals
        if inv.get("status") != "Cancelled":
            totals_paid += paid_amount
            totals_unpaid += remaining_amount
            totals_subtotal += subtotal
            totals_vat += vat_amount
            totals_total += total
        
        inv_id = inv.get("id")
        invoice_list.append({
            "id": inv_id,
            "invoice_no": inv.get("invoice_no", ""),
            "direction": inv.get("direction", "Issued"),
            "lines_count": len(inv.get("lines", [])),
            "client_name": inv.get("counterparty_name", ""),
            "project_code": project.get("code", ""),
            "issue_date": inv.get("issue_date"),
            "due_date": inv.get("due_date"),
            "currency": inv.get("currency", "BGN"),
            "vat_percent": inv.get("vat_percent", 20),
            "subtotal": subtotal,
            "vat_amount": vat_amount,
            "total": total,
            "paid_amount": paid_amount,
            "remaining_amount": remaining_amount,
            "status": inv.get("status", "Draft"),
            "payments": alloc_by_invoice.get(inv_id, []),
        })
    
    card_invoices = {
        "invoices": invoice_list,
        "count": len(invoice_list),
        "totals": {
            "subtotal": round(totals_subtotal, 2),
            "vat": round(totals_vat, 2),
            "total": round(totals_total, 2),
            "paid": round(totals_paid, 2),
            "unpaid": round(totals_unpaid, 2),
        },
    }
    
    # ── Card 6: Offers ──────────────────────────────────────────────────────
    offers = await db.offers.find(
        {"project_id": project_id, "org_id": org_id, "status": "Accepted"},
        {"_id": 0, "total_ex_vat": 1, "total_vat": 1, "total_inc_vat": 1}
    ).to_list(500)
    
    offers_ex_vat = sum(o.get("total_ex_vat", 0) or 0 for o in offers)
    offers_vat = sum(o.get("total_vat", 0) or 0 for o in offers)
    offers_inc_vat = sum(o.get("total_inc_vat", 0) or 0 for o in offers)
    
    # Extra offers for this project
    all_offers = await db.offers.find(
        {"project_id": project_id, "org_id": org_id},
        {"_id": 0, "id": 1, "offer_no": 1, "title": 1, "status": 1, "offer_type": 1,
         "version": 1, "total": 1, "subtotal": 1, "currency": 1,
         "sent_at": 1, "accepted_at": 1, "created_at": 1, "review_token": 1,
         "lines": 1}
    ).sort("created_at", -1).to_list(100)
    
    extra_offers = [o for o in all_offers if o.get("offer_type") == "extra"]
    accepted_offers = [o for o in all_offers if o.get("status") == "Accepted"]
    accepted_lines = sum(len(o.get("lines", [])) for o in accepted_offers)
    
    # Strip lines from the list response to save bandwidth
    for o in all_offers:
        o.pop("lines", None)
    
    card_offers = {
        "approved_count": len(offers),
        "accepted_count": len(accepted_offers),
        "accepted_lines": accepted_lines,
        "total_ex_vat": offers_ex_vat,
        "total_vat": offers_vat,
        "total_inc_vat": offers_inc_vat,
        "extra_offers": extra_offers,
    }
    
    # ── Card 7: Materials (Warehouse) ───────────────────────────────────────
    # Check if warehouse_transactions collection exists
    materials_ex_vat = 0
    materials_vat = 0
    materials_inc_vat = 0
    
    try:
        warehouse_txns = await db.warehouse_transactions.find(
            {"project_id": project_id, "org_id": org_id},
            {"_id": 0, "total_ex_vat": 1, "total_vat": 1, "total_inc_vat": 1}
        ).to_list(1000)
        materials_ex_vat = sum(t.get("total_ex_vat", 0) or 0 for t in warehouse_txns)
        materials_vat = sum(t.get("total_vat", 0) or 0 for t in warehouse_txns)
        materials_inc_vat = sum(t.get("total_inc_vat", 0) or 0 for t in warehouse_txns)
    except:
        pass
    
    card_materials = {
        "total_ex_vat": materials_ex_vat,
        "total_vat": materials_vat,
        "total_inc_vat": materials_inc_vat,
    }
    
    # ── Card 8: Balance ─────────────────────────────────────────────────────
    # Income = actual paid amounts from invoices (source of truth: paid_amount)
    income = totals_paid
    
    # Check for project payments (additional income)
    try:
        payments = await db.project_payments.find(
            {"project_id": project_id, "org_id": org_id, "type": "incoming"},
            {"_id": 0, "amount": 1}
        ).to_list(1000)
        income += sum(p.get("amount", 0) or 0 for p in payments)
    except:
        pass
    
    # Expenses = salaries + materials
    expenses = total_salaries_paid + materials_inc_vat
    
    card_balance = {
        "income": income,
        "expenses": expenses,
        "balance": income - expenses,
    }
    
    # ── Return all cards ────────────────────────────────────────────────────
    return {
        "project": card_project,
        "client": card_client,
        "progress": card_progress,
        "team": card_team,
        "invoices": card_invoices,
        "offers": card_offers,
        "materials": card_materials,
        "balance": card_balance,
        "sub_projects": children,
        "parent_project": parent_info,
    }



# ── Project pending reports (for inline approve) ──────────────────

@router.get("/projects/{project_id}/pending-reports")
async def get_project_pending_reports(project_id: str, user: dict = Depends(get_current_user)):
    """Reports submitted for this project, awaiting approval."""
    org_id = user["org_id"]
    reports = await db.employee_daily_reports.find(
        {"org_id": org_id, "project_id": project_id,
         "status": "SUBMITTED", "worker_id": {"$exists": True}},
        {"_id": 0, "id": 1, "worker_id": 1, "worker_name": 1, "date": 1,
         "hours": 1, "smr_type": 1, "notes": 1, "status": 1, "created_at": 1},
    ).sort("date", -1).to_list(100)
    return {"items": reports, "total": len(reports)}



# ── Cyrillic auto-letter sub-project creation ─────────────────────
CYRILLIC_LETTERS = "АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩЪЬЮЯ"


class CreateSubProjectRequest(BaseModel):
    name: str  # Name for the NEW sub-project (Б, В, Г...)


@router.post("/projects/{project_id}/create-sub-project", status_code=201)
async def create_sub_project(project_id: str, data: CreateSubProjectRequest, user: dict = Depends(get_current_user)):
    """
    Auto-letter sub-project creation with Cyrillic suffixes.
    First call: original → child А (migrates data), new empty child Б.
    Subsequent calls: new child В, Г, Д...
    """
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    org_id = user["org_id"]
    parent = await db.projects.find_one({"id": project_id, "org_id": org_id}, {"_id": 0})
    if not parent:
        raise HTTPException(status_code=404, detail="Project not found")

    # Don't allow nested sub-projects (a child can't have children)
    if parent.get("parent_project_id"):
        raise HTTPException(status_code=400, detail="Под-обект не може да има собствени под-обекти")

    now = datetime.now(timezone.utc).isoformat()
    existing_children = await db.projects.find(
        {"org_id": org_id, "parent_project_id": project_id},
        {"_id": 0, "id": 1, "code": 1},
    ).to_list(50)

    parent_code = parent.get("code", "")
    results = {"parent_id": project_id, "children_created": []}

    if len(existing_children) == 0:
        # ══ FIRST TIME: Migrate original → child А, create child Б ══

        # --- Child А: clone of original with all operational data ---
        child_a_id = str(uuid.uuid4())
        child_a_code = f"{parent_code}-А"
        child_a = {
            "id": child_a_id,
            "org_id": org_id,
            "code": child_a_code,
            "name": parent.get("name", ""),
            "status": parent.get("status", "Active"),
            "type": parent.get("type", "Billable"),
            "start_date": parent.get("start_date"),
            "end_date": parent.get("end_date"),
            "planned_days": parent.get("planned_days"),
            "budget_planned": parent.get("budget_planned"),
            "default_site_manager_id": parent.get("default_site_manager_id"),
            "tags": parent.get("tags", []),
            "notes": parent.get("notes", ""),
            "warranty_months": parent.get("warranty_months"),
            "object_type": parent.get("object_type"),
            # Shared data inherited from parent (not stored on child)
            "parent_project_id": project_id,
            "created_at": now,
            "updated_at": now,
        }
        await db.projects.insert_one(child_a)

        # --- Migrate operational data from parent → child А ---
        collections_to_migrate = [
            ("invoices", "project_id"),
            ("offers", "project_id"),
            ("employee_daily_reports", "project_id"),
            ("extra_works", "project_id"),
            ("payroll_payment_allocations", "project_id"),
            ("warehouse_transactions", "project_id"),
            ("subcontractor_payments", "project_id"),
        ]
        migration_log = {}
        for coll_name, field in collections_to_migrate:
            coll = db[coll_name]
            result = await coll.update_many(
                {field: project_id, "org_id": org_id},
                {"$set": {field: child_a_id, "updated_at": now}},
            )
            if result.modified_count > 0:
                migration_log[coll_name] = result.modified_count

        # Work sessions use site_id instead of project_id
        ws_result = await db.work_sessions.update_many(
            {"site_id": project_id, "org_id": org_id},
            {"$set": {"site_id": child_a_id, "updated_at": now}},
        )
        if ws_result.modified_count > 0:
            migration_log["work_sessions"] = ws_result.modified_count

        # Contract payments also use site_id
        cp_result = await db.contract_payments.update_many(
            {"site_id": project_id, "org_id": org_id},
            {"$set": {"site_id": child_a_id, "updated_at": now}},
        )
        if cp_result.modified_count > 0:
            migration_log["contract_payments"] = cp_result.modified_count

        # Project team: clone (not move) so parent can still display
        team_members = await db.project_team.find(
            {"project_id": project_id, "org_id": org_id},
            {"_id": 0},
        ).to_list(100)
        for tm in team_members:
            await db.project_team.insert_one({
                **tm,
                "_id": None,
                "id": str(uuid.uuid4()),
                "project_id": child_a_id,
            })
        if team_members:
            migration_log["project_team_cloned"] = len(team_members)

        results["children_created"].append({
            "id": child_a_id, "code": child_a_code,
            "name": child_a.get("name"), "letter": "А",
            "migration": migration_log,
        })

        # --- Child Б: new empty sub-project ---
        child_b_id = str(uuid.uuid4())
        child_b_code = f"{parent_code}-Б"
        child_b = {
            "id": child_b_id,
            "org_id": org_id,
            "code": child_b_code,
            "name": data.name,
            "status": "Draft",
            "type": parent.get("type", "Billable"),
            "start_date": None,
            "end_date": None,
            "planned_days": None,
            "budget_planned": None,
            "default_site_manager_id": None,
            "tags": [],
            "notes": "",
            "warranty_months": parent.get("warranty_months"),
            "object_type": parent.get("object_type"),
            "parent_project_id": project_id,
            "created_at": now,
            "updated_at": now,
        }
        await db.projects.insert_one(child_b)
        results["children_created"].append({
            "id": child_b_id, "code": child_b_code,
            "name": data.name, "letter": "Б",
        })

        # Mark parent as wrapper (clear operational budget, keep shared data)
        await db.projects.update_one(
            {"id": project_id},
            {"$set": {"updated_at": now, "is_parent": True}},
        )

        await log_audit(org_id, user["id"], user["email"], "split_to_subprojects", "project", project_id,
                        {"child_a": child_a_code, "child_b": child_b_code, "migration": migration_log})

    else:
        # ══ SUBSEQUENT: Just add next letter ══
        next_idx = len(existing_children)
        if next_idx >= len(CYRILLIC_LETTERS):
            raise HTTPException(status_code=400, detail="Максимален брой под-обекти достигнат")

        letter = CYRILLIC_LETTERS[next_idx]
        new_child_id = str(uuid.uuid4())
        new_child_code = f"{parent_code}-{letter}"

        # Check code uniqueness
        if await db.projects.find_one({"org_id": org_id, "code": new_child_code}):
            raise HTTPException(status_code=400, detail=f"Код {new_child_code} вече съществува")

        new_child = {
            "id": new_child_id,
            "org_id": org_id,
            "code": new_child_code,
            "name": data.name,
            "status": "Draft",
            "type": parent.get("type", "Billable"),
            "start_date": None,
            "end_date": None,
            "planned_days": None,
            "budget_planned": None,
            "default_site_manager_id": None,
            "tags": [],
            "notes": "",
            "warranty_months": parent.get("warranty_months"),
            "object_type": parent.get("object_type"),
            "parent_project_id": project_id,
            "created_at": now,
            "updated_at": now,
        }
        await db.projects.insert_one(new_child)
        results["children_created"].append({
            "id": new_child_id, "code": new_child_code,
            "name": data.name, "letter": letter,
        })

        await log_audit(org_id, user["id"], user["email"], "created_subproject", "project", project_id,
                        {"child": new_child_code, "letter": letter})

    return results


# ── Parent aggregate (own + children, read-only) ──────────────────

@router.get("/projects/{project_id}/aggregate")
async def get_project_aggregate(project_id: str, user: dict = Depends(get_current_user)):
    """Read-only aggregate: own data + all direct children data."""
    org_id = user["org_id"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Get all project IDs (parent + children)
    children = await db.projects.find(
        {"org_id": org_id, "parent_project_id": project_id},
        {"_id": 0, "id": 1, "name": 1, "code": 1, "status": 1},
    ).to_list(50)
    child_ids = [c["id"] for c in children]

    if not child_ids:
        return {"has_children": False}

    # ── Team ──
    async def count_team(pid):
        return await db.project_team.count_documents({"org_id": org_id, "project_id": pid})

    async def count_reported(pid):
        reps = await db.employee_daily_reports.find(
            {"org_id": org_id, "project_id": pid, "date": today, "worker_id": {"$exists": True}},
            {"_id": 0, "worker_id": 1, "status": 1, "hours": 1},
        ).to_list(200)
        reported = len(set(r.get("worker_id") for r in reps))
        approved = len(set(r.get("worker_id") for r in reps if (r.get("status") or "").upper() == "APPROVED"))
        hours = round(sum(r.get("hours", 0) for r in reps), 1)
        return {"reported": reported, "approved": approved, "hours": hours}

    own_team = await count_team(project_id)
    own_rpt = await count_reported(project_id)
    child_team = 0
    child_rpt = {"reported": 0, "approved": 0, "hours": 0}
    per_child = {}
    for c in children:
        cid = c["id"]
        ct = await count_team(cid)
        cr = await count_reported(cid)
        child_team += ct
        child_rpt["reported"] += cr["reported"]
        child_rpt["approved"] += cr["approved"]
        child_rpt["hours"] += cr["hours"]
        per_child[cid] = {"team": {"count": ct, **cr}}

    # ── Invoices ──
    async def count_invoices(pids):
        invs = await db.invoices.find(
            {"org_id": org_id, "project_id": {"$in": pids}},
            {"_id": 0, "total": 1, "paid_amount": 1, "status": 1, "due_date": 1},
        ).to_list(500)
        count = len(invs)
        invoiced = round(sum(i.get("total", 0) for i in invs if i.get("status") not in ["Draft", "Cancelled"]), 2)
        paid = round(sum(i.get("paid_amount", 0) or 0 for i in invs), 2)
        unpaid = round(invoiced - paid, 2)
        overdue = round(sum(
            (i.get("total", 0) - (i.get("paid_amount") or 0))
            for i in invs
            if i.get("status") not in ["Draft", "Cancelled", "Paid"]
            and (i.get("due_date") or "9999") < today
        ), 2)
        return {"count": count, "invoiced": invoiced, "paid": paid, "unpaid": unpaid, "overdue": overdue}

    own_inv = await count_invoices([project_id])
    child_inv = await count_invoices(child_ids) if child_ids else {"count": 0, "invoiced": 0, "paid": 0, "unpaid": 0, "overdue": 0}
    for c in children:
        per_child[c["id"]]["invoices"] = await count_invoices([c["id"]])

    # ── Offers ──
    async def count_offers(pids):
        count = await db.offers.count_documents({"org_id": org_id, "project_id": {"$in": pids}})
        approved = await db.offers.count_documents({"org_id": org_id, "project_id": {"$in": pids}, "status": "Approved"})
        return {"count": count, "approved": approved}

    own_off = await count_offers([project_id])
    child_off = await count_offers(child_ids) if child_ids else {"count": 0, "approved": 0}
    for c in children:
        per_child[c["id"]]["offers"] = await count_offers([c["id"]])

    # ── Reports total (all time) ──
    async def count_report_hours(pids):
        reps = await db.employee_daily_reports.find(
            {"org_id": org_id, "project_id": {"$in": pids}, "worker_id": {"$exists": True}},
            {"_id": 0, "hours": 1},
        ).to_list(5000)
        return {"count": len(reps), "hours": round(sum(r.get("hours", 0) for r in reps), 1)}

    own_reps = await count_report_hours([project_id])
    child_reps = await count_report_hours(child_ids) if child_ids else {"count": 0, "hours": 0}
    for c in children:
        per_child[c["id"]]["reports"] = await count_report_hours([c["id"]])

    def merge(own, children):
        return {k: round((own.get(k, 0) or 0) + (children.get(k, 0) or 0), 2) for k in set(list(own.keys()) + list(children.keys()))}

    return {
        "has_children": True,
        "children_count": len(children),
        "children": [
            {
                "id": c["id"], "code": c.get("code", ""), "name": c["name"], "status": c.get("status", ""),
                **(per_child.get(c["id"], {})),
            }
            for c in children
        ],
        "team": {
            "own": {"count": own_team, **own_rpt},
            "children": {"count": child_team, **child_rpt},
            "total": {"count": own_team + child_team, "reported": own_rpt["reported"] + child_rpt["reported"], "approved": own_rpt["approved"] + child_rpt["approved"], "hours": round(own_rpt["hours"] + child_rpt["hours"], 1)},
        },
        "invoices": {
            "own": own_inv,
            "children": child_inv,
            "total": merge(own_inv, child_inv),
        },
        "offers": {
            "own": own_off,
            "children": child_off,
            "total": merge(own_off, child_off),
        },
        "reports": {
            "own": own_reps,
            "children": child_reps,
            "total": merge(own_reps, child_reps),
        },
    }
