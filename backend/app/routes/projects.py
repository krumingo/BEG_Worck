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
PROJECT_STATUSES = ["Draft", "Active", "Paused", "Completed", "Cancelled", "Finished", "Archived"]
PROJECT_TYPES = ["Billable", "Overhead", "Warranty"]
PROJECT_TEAM_ROLES = ["SiteManager", "Technician", "Viewer"]
OWNER_TYPES = ["person", "company"]
WARRANTY_OPTIONS = [3, 6, 12, 24]  # months

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
        "address_text": data.address_text,
        "owner_type": data.owner_type,
        "owner_id": data.owner_id,
        "warranty_months": data.warranty_months,
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
    if "type" in update and update["type"] not in PROJECT_TYPES:
        raise HTTPException(status_code=400, detail="Invalid type")
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.projects.update_one({"id": project_id}, {"$set": update})
    await log_audit(user["org_id"], user["id"], user["email"], "updated", "project", project_id, update)
    return await db.projects.find_one({"id": project_id}, {"_id": 0})

@router.delete("/projects/{project_id}")
async def delete_project(project_id: str, user: dict = Depends(require_admin)):
    project = await db.projects.find_one({"id": project_id, "org_id": user["org_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await db.projects.delete_one({"id": project_id})
    await db.project_team.delete_many({"project_id": project_id})
    await db.project_phases.delete_many({"project_id": project_id})
    await log_audit(user["org_id"], user["id"], user["email"], "deleted", "project", project_id, {"code": project.get("code")})
    return {"ok": True}

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
    mol: Optional[str] = None
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
    }
    
    # ── Card 2: Owner/Client Info ───────────────────────────────────────────
    card_client = {
        "owner_type": project.get("owner_type"),
        "owner_id": project.get("owner_id"),
        "owner_data": None,
    }
    
    if project.get("owner_type") == "person" and project.get("owner_id"):
        person = await db.persons.find_one({"id": project["owner_id"], "org_id": org_id}, {"_id": 0})
        if person:
            card_client["owner_data"] = {
                "type": "person",
                "first_name": person.get("first_name", ""),
                "last_name": person.get("last_name", ""),
                "phone": person.get("phone", ""),
                "email": person.get("email", ""),
                "notes": person.get("notes", ""),
            }
    elif project.get("owner_type") == "company" and project.get("owner_id"):
        company = await db.companies.find_one({"id": project["owner_id"], "org_id": org_id}, {"_id": 0})
        if company:
            card_client["owner_data"] = {
                "type": "company",
                "name": company.get("name", ""),
                "eik": company.get("eik", ""),
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
    
    # ── Card 5: Invoices ────────────────────────────────────────────────────
    invoices = await db.invoices.find(
        {"project_id": project_id, "org_id": org_id},
        {"_id": 0}
    ).sort("created_at", -1).to_list(500)
    
    invoice_list = []
    totals_paid_ex_vat = 0
    totals_unpaid_ex_vat = 0
    totals_paid_inc_vat = 0
    totals_unpaid_inc_vat = 0
    
    for inv in invoices:
        total_ex_vat = inv.get("total_ex_vat", 0) or 0
        total_vat = inv.get("total_vat", 0) or 0
        total_inc_vat = inv.get("total_inc_vat", 0) or total_ex_vat + total_vat
        is_paid = inv.get("status") == "Paid"
        
        if is_paid:
            totals_paid_ex_vat += total_ex_vat
            totals_paid_inc_vat += total_inc_vat
        else:
            totals_unpaid_ex_vat += total_ex_vat
            totals_unpaid_inc_vat += total_inc_vat
        
        # Get client name
        client_name = ""
        if inv.get("client_id"):
            client = await db.companies.find_one({"id": inv["client_id"]}, {"_id": 0, "name": 1})
            if client:
                client_name = client.get("name", "")
        
        invoice_list.append({
            "id": inv.get("id"),
            "invoice_no": inv.get("invoice_no", ""),
            "lines_count": len(inv.get("lines", [])),
            "client_name": client_name,
            "project_code": project.get("code", ""),
            "issue_date": inv.get("issue_date"),
            "due_date": inv.get("due_date"),
            "currency": inv.get("currency", "BGN"),
            "vat_percent": inv.get("vat_percent", 20),
            "total_ex_vat": total_ex_vat,
            "total_vat": total_vat,
            "total_inc_vat": total_inc_vat,
            "status": inv.get("status", "Draft"),
            "paid_ex_vat": total_ex_vat if is_paid else 0,
            "unpaid_ex_vat": 0 if is_paid else total_ex_vat,
            "paid_inc_vat": total_inc_vat if is_paid else 0,
            "unpaid_inc_vat": 0 if is_paid else total_inc_vat,
        })
    
    card_invoices = {
        "invoices": invoice_list,
        "count": len(invoice_list),
        "totals": {
            "paid_ex_vat": totals_paid_ex_vat,
            "unpaid_ex_vat": totals_unpaid_ex_vat,
            "paid_inc_vat": totals_paid_inc_vat,
            "unpaid_inc_vat": totals_unpaid_inc_vat,
        },
    }
    
    # ── Card 6: Offers ──────────────────────────────────────────────────────
    offers = await db.offers.find(
        {"project_id": project_id, "org_id": org_id, "status": "Approved"},
        {"_id": 0, "total_ex_vat": 1, "total_vat": 1, "total_inc_vat": 1}
    ).to_list(500)
    
    offers_ex_vat = sum(o.get("total_ex_vat", 0) or 0 for o in offers)
    offers_vat = sum(o.get("total_vat", 0) or 0 for o in offers)
    offers_inc_vat = sum(o.get("total_inc_vat", 0) or 0 for o in offers)
    
    card_offers = {
        "approved_count": len(offers),
        "total_ex_vat": offers_ex_vat,
        "total_vat": offers_vat,
        "total_inc_vat": offers_inc_vat,
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
    # Income = paid invoices
    income = totals_paid_inc_vat
    
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
    }

