from fastapi import FastAPI, APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel
from typing import Optional, List
import uuid
from datetime import datetime, timezone, timedelta
from passlib.context import CryptContext
from jose import jwt, JWTError
from zoneinfo import ZoneInfo
import asyncio

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

JWT_SECRET = os.environ['JWT_SECRET']
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

ROLES = ["Admin", "Owner", "SiteManager", "Technician", "Accountant", "Warehousekeeper", "Driver", "Viewer"]

MODULES = {
    "M0": {"name": "Core / SaaS", "description": "Tenants, auth, roles, settings, audit, billing"},
    "M1": {"name": "Projects", "description": "Project management and tracking"},
    "M2": {"name": "Estimates / BOQ", "description": "Offers, activities, bill of quantities"},
    "M3": {"name": "Attendance & Reports", "description": "Daily attendance, work reports, reminders"},
    "M4": {"name": "HR / Payroll", "description": "Hourly/daily/monthly pay, advances, payslips"},
    "M5": {"name": "Finance", "description": "Invoices, payments, cash/bank management"},
    "M6": {"name": "AI Invoice Capture", "description": "Upload, parse, approval queue"},
    "M7": {"name": "Inventory", "description": "Items, stock movements, warehouses"},
    "M8": {"name": "Assets & QR", "description": "Checkout/checkin, maintenance, warranty"},
    "M9": {"name": "Admin Console / BI", "description": "Statistics, alerts, overhead costs"},
}

app = FastAPI(title="BEG_Work API")
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ── Pydantic Models ──────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str

class UserCreate(BaseModel):
    email: str
    password: str
    first_name: str
    last_name: str
    role: str = "Viewer"
    phone: str = ""

class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: Optional[str] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None

class OrgUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    attendance_start: Optional[str] = None
    attendance_end: Optional[str] = None
    work_report_deadline: Optional[str] = None
    max_reminders_per_day: Optional[int] = None
    escalation_after_days: Optional[int] = None
    org_timezone: Optional[str] = None

class ModuleToggle(BaseModel):
    module_code: str
    enabled: bool

# ── Project Models ───────────────────────────────────────────────

PROJECT_STATUSES = ["Draft", "Active", "Paused", "Completed", "Cancelled"]
PROJECT_TYPES = ["Billable", "Overhead", "Warranty"]
PROJECT_TEAM_ROLES = ["SiteManager", "Technician", "Viewer"]

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

# ── Attendance Models ────────────────────────────────────────────

ATTENDANCE_STATUSES = ["Present", "Absent", "Late", "SickLeave", "Vacation"]

class AttendanceMarkSelf(BaseModel):
    project_id: Optional[str] = None
    status: str = "Present"
    note: str = ""
    source: str = "Web"

class AttendanceMarkForUser(BaseModel):
    user_id: str
    project_id: Optional[str] = None
    status: str = "Present"
    note: str = ""
    source: str = "Web"

# ── Work Report Models ───────────────────────────────────────────

REPORT_STATUSES = ["Draft", "Submitted", "Approved", "Rejected"]

class WorkReportLineInput(BaseModel):
    activity_name: str
    hours: float
    note: str = ""

class WorkReportDraftCreate(BaseModel):
    project_id: str
    date: Optional[str] = None

class WorkReportUpdate(BaseModel):
    summary_note: Optional[str] = None
    lines: Optional[List[WorkReportLineInput]] = None

class WorkReportReject(BaseModel):
    reason: str

# ── Reminder / Notification Models ───────────────────────────────

REMINDER_TYPES = ["MissingAttendance", "MissingWorkReport"]
REMINDER_STATUSES = ["Open", "Reminded", "Resolved", "Excused"]

class SendReminderRequest(BaseModel):
    type: str
    date: Optional[str] = None
    user_ids: List[str]
    project_id: Optional[str] = None

class ExcuseRequest(BaseModel):
    type: str
    date: str
    user_id: str
    project_id: Optional[str] = None
    reason: str

# ── Auth Helpers ─────────────────────────────────────────────────

def hash_password(pw: str) -> str:
    return pwd_context.hash(pw)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_token(data: dict) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS)
    return jwt.encode({**data, "exp": expire}, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        user = await db.users.find_one({"id": user_id}, {"_id": 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        if not user.get("is_active", True):
            raise HTTPException(status_code=403, detail="Account disabled")
        return user
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def require_admin(user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

# ── Project Permission Helpers ───────────────────────────────────

async def get_user_project_ids(user_id: str) -> List[str]:
    members = await db.project_team.find({"user_id": user_id, "active": True}, {"_id": 0, "project_id": 1}).to_list(1000)
    return [m["project_id"] for m in members]

async def can_access_project(user: dict, project_id: str) -> bool:
    if user["role"] in ["Admin", "Owner"]:
        return True
    member = await db.project_team.find_one({"project_id": project_id, "user_id": user["id"], "active": True})
    return member is not None

async def can_manage_project(user: dict, project_id: str) -> bool:
    if user["role"] in ["Admin", "Owner"]:
        return True
    if user["role"] == "SiteManager":
        member = await db.project_team.find_one({"project_id": project_id, "user_id": user["id"], "active": True, "role_in_project": "SiteManager"})
        return member is not None
    return False

# ── Audit Helper ─────────────────────────────────────────────────

async def log_audit(org_id, user_id, user_email, action, entity_type, entity_id="", details=None):
    await db.audit_logs.insert_one({
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "user_id": user_id,
        "user_email": user_email,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "details": details or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

# ── Seed ─────────────────────────────────────────────────────────

async def seed_data():
    existing = await db.users.find_one({"email": "admin@begwork.com"})
    if existing:
        logger.info("Seed data already exists, skipping")
        return

    org_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    expires = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()

    await db.organizations.insert_one({
        "id": org_id,
        "name": "BEG_Work Demo",
        "slug": "begwork-demo",
        "address": "",
        "phone": "",
        "email": "admin@begwork.com",
        "logo_url": "",
        "subscription_plan": "enterprise",
        "subscription_status": "active",
        "subscription_expires_at": expires,
        "created_at": now,
        "updated_at": now,
    })

    user_id = str(uuid.uuid4())
    await db.users.insert_one({
        "id": user_id,
        "org_id": org_id,
        "email": "admin@begwork.com",
        "password_hash": hash_password("admin123"),
        "first_name": "System",
        "last_name": "Admin",
        "role": "Admin",
        "phone": "",
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    })

    for code, info in MODULES.items():
        await db.feature_flags.insert_one({
            "id": str(uuid.uuid4()),
            "org_id": org_id,
            "module_code": code,
            "module_name": info["name"],
            "description": info["description"],
            "enabled": code == "M0",
            "updated_at": now,
            "updated_by": user_id,
        })

    await db.subscriptions.insert_one({
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "plan": "enterprise",
        "status": "active",
        "started_at": now,
        "expires_at": expires,
        "payment_method": "seed",
        "amount": 0,
        "currency": "EUR",
        "created_at": now,
    })

    logger.info("Seed data created: admin@begwork.com / admin123")

# ── Auth Routes ──────────────────────────────────────────────────

@api_router.post("/auth/login")
async def login(req: LoginRequest):
    user = await db.users.find_one({"email": req.email}, {"_id": 0})
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account disabled")
    token = create_token({"user_id": user["id"], "org_id": user["org_id"], "role": user["role"]})
    await log_audit(user["org_id"], user["id"], user["email"], "login", "auth")
    return {"token": token, "user": {k: v for k, v in user.items() if k != "password_hash"}}

@api_router.get("/auth/me")
async def get_me(user: dict = Depends(get_current_user)):
    return {k: v for k, v in user.items() if k != "password_hash"}

# ── Organization Routes ──────────────────────────────────────────

@api_router.get("/organization")
async def get_organization(user: dict = Depends(get_current_user)):
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org

@api_router.put("/organization")
async def update_organization(data: OrgUpdate, user: dict = Depends(require_admin)):
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.organizations.update_one({"id": user["org_id"]}, {"$set": update})
    await log_audit(user["org_id"], user["id"], user["email"], "updated", "organization", user["org_id"], update)
    return await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})

# ── User Routes ──────────────────────────────────────────────────

@api_router.get("/users")
async def list_users(user: dict = Depends(get_current_user)):
    return await db.users.find({"org_id": user["org_id"]}, {"_id": 0, "password_hash": 0}).to_list(1000)

@api_router.post("/users", status_code=201)
async def create_user(data: UserCreate, user: dict = Depends(require_admin)):
    if await db.users.find_one({"email": data.email, "org_id": user["org_id"]}):
        raise HTTPException(status_code=400, detail="Email already exists in this organization")
    if data.role not in ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {', '.join(ROLES)}")
    now = datetime.now(timezone.utc).isoformat()
    new_user = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "email": data.email,
        "password_hash": hash_password(data.password),
        "first_name": data.first_name,
        "last_name": data.last_name,
        "role": data.role,
        "phone": data.phone,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    await db.users.insert_one(new_user)
    await log_audit(user["org_id"], user["id"], user["email"], "created", "user", new_user["id"], {"email": data.email, "role": data.role})
    return {k: v for k, v in new_user.items() if k not in ("password_hash", "_id")}

@api_router.put("/users/{user_id}")
async def update_user(user_id: str, data: UserUpdate, user: dict = Depends(require_admin)):
    target = await db.users.find_one({"id": user_id, "org_id": user["org_id"]})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    if "role" in update and update["role"] not in ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.users.update_one({"id": user_id}, {"$set": update})
    await log_audit(user["org_id"], user["id"], user["email"], "updated", "user", user_id, update)
    return await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})

@api_router.delete("/users/{user_id}")
async def delete_user(user_id: str, user: dict = Depends(require_admin)):
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    target = await db.users.find_one({"id": user_id, "org_id": user["org_id"]})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    await db.users.delete_one({"id": user_id})
    await log_audit(user["org_id"], user["id"], user["email"], "deleted", "user", user_id)
    return {"ok": True}

# ── Feature Flags Routes ─────────────────────────────────────────

@api_router.get("/feature-flags")
async def list_feature_flags(user: dict = Depends(get_current_user)):
    return await db.feature_flags.find({"org_id": user["org_id"]}, {"_id": 0}).to_list(100)

@api_router.put("/feature-flags")
async def toggle_feature_flag(data: ModuleToggle, user: dict = Depends(require_admin)):
    if data.module_code == "M0":
        raise HTTPException(status_code=400, detail="Core module cannot be disabled")
    result = await db.feature_flags.update_one(
        {"org_id": user["org_id"], "module_code": data.module_code},
        {"$set": {"enabled": data.enabled, "updated_at": datetime.now(timezone.utc).isoformat(), "updated_by": user["id"]}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Module not found")
    await log_audit(user["org_id"], user["id"], user["email"], "toggled", "feature_flag", data.module_code, {"enabled": data.enabled})
    return await db.feature_flags.find({"org_id": user["org_id"]}, {"_id": 0}).to_list(100)

# ── Audit Log Routes ─────────────────────────────────────────────

@api_router.get("/audit-logs")
async def list_audit_logs(user: dict = Depends(require_admin), limit: int = 50, skip: int = 0):
    logs = await db.audit_logs.find(
        {"org_id": user["org_id"]}, {"_id": 0}
    ).sort("timestamp", -1).skip(skip).limit(limit).to_list(limit)
    total = await db.audit_logs.count_documents({"org_id": user["org_id"]})
    return {"logs": logs, "total": total}

# ── Project Routes ────────────────────────────────────────────────

@api_router.get("/projects")
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

    # Role-based filtering
    if user["role"] not in ["Admin", "Owner", "Accountant"]:
        assigned_ids = await get_user_project_ids(user["id"])
        query["id"] = {"$in": assigned_ids}

    projects = await db.projects.find(query, {"_id": 0}).sort("updated_at", -1).to_list(1000)

    if search:
        s = search.lower()
        projects = [p for p in projects if s in p.get("code", "").lower() or s in p.get("name", "").lower()]

    # Enrich with site manager name
    for p in projects:
        if p.get("default_site_manager_id"):
            mgr = await db.users.find_one({"id": p["default_site_manager_id"]}, {"_id": 0, "first_name": 1, "last_name": 1})
            p["site_manager_name"] = f"{mgr['first_name']} {mgr['last_name']}" if mgr else ""
        else:
            p["site_manager_name"] = ""
        # Team count
        p["team_count"] = await db.project_team.count_documents({"project_id": p["id"], "active": True})

    return projects

@api_router.post("/projects", status_code=201)
async def create_project(data: ProjectCreate, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions to create projects")
    if data.status not in PROJECT_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be: {', '.join(PROJECT_STATUSES)}")
    if data.type not in PROJECT_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid type. Must be: {', '.join(PROJECT_TYPES)}")

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
        "created_at": now,
        "updated_at": now,
    }
    await db.projects.insert_one(project)

    # Auto-assign site manager if provided
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

@api_router.get("/projects/{project_id}")
async def get_project(project_id: str, user: dict = Depends(get_current_user)):
    project = await db.projects.find_one({"id": project_id, "org_id": user["org_id"]}, {"_id": 0})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not await can_access_project(user, project_id):
        raise HTTPException(status_code=403, detail="Access denied")

    # Enrich
    if project.get("default_site_manager_id"):
        mgr = await db.users.find_one({"id": project["default_site_manager_id"]}, {"_id": 0, "first_name": 1, "last_name": 1})
        project["site_manager_name"] = f"{mgr['first_name']} {mgr['last_name']}" if mgr else ""
    else:
        project["site_manager_name"] = ""
    project["team_count"] = await db.project_team.count_documents({"project_id": project_id, "active": True})
    return project

@api_router.put("/projects/{project_id}")
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

@api_router.delete("/projects/{project_id}")
async def delete_project(project_id: str, user: dict = Depends(require_admin)):
    project = await db.projects.find_one({"id": project_id, "org_id": user["org_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await db.projects.delete_one({"id": project_id})
    await db.project_team.delete_many({"project_id": project_id})
    await db.project_phases.delete_many({"project_id": project_id})
    await log_audit(user["org_id"], user["id"], user["email"], "deleted", "project", project_id, {"code": project.get("code")})
    return {"ok": True}

# ── Project Team Routes ──────────────────────────────────────────

@api_router.get("/projects/{project_id}/team")
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

@api_router.post("/projects/{project_id}/team", status_code=201)
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
    await log_audit(user["org_id"], user["id"], user["email"], "team_added", "project", project_id,
                    {"member_id": data.user_id, "role": data.role_in_project})
    return {k: v for k, v in member.items() if k != "_id"}

@api_router.delete("/projects/{project_id}/team/{member_id}")
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

# ── Project Phase Routes ─────────────────────────────────────────

@api_router.get("/projects/{project_id}/phases")
async def list_phases(project_id: str, user: dict = Depends(get_current_user)):
    project = await db.projects.find_one({"id": project_id, "org_id": user["org_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not await can_access_project(user, project_id):
        raise HTTPException(status_code=403, detail="Access denied")
    return await db.project_phases.find({"project_id": project_id}, {"_id": 0}).sort("order", 1).to_list(100)

@api_router.post("/projects/{project_id}/phases", status_code=201)
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

@api_router.put("/projects/{project_id}/phases/{phase_id}")
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

@api_router.delete("/projects/{project_id}/phases/{phase_id}")
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

# ── Attendance Helpers ────────────────────────────────────────────

def today_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def now_hour():
    return datetime.now(timezone.utc).hour

async def get_org_attendance_window(org_id: str):
    org = await db.organizations.find_one({"id": org_id}, {"_id": 0, "attendance_start": 1, "attendance_end": 1})
    start = org.get("attendance_start", "06:00") if org else "06:00"
    end = org.get("attendance_end", "10:00") if org else "10:00"
    return start, end

async def get_user_active_project_ids(user_id: str):
    members = await db.project_team.find({"user_id": user_id, "active": True}, {"_id": 0, "project_id": 1}).to_list(100)
    pids = [m["project_id"] for m in members]
    if not pids:
        return []
    active = await db.projects.find({"id": {"$in": pids}, "status": "Active"}, {"_id": 0, "id": 1}).to_list(100)
    return [p["id"] for p in active]

async def is_past_deadline(org_id: str):
    _, end = await get_org_attendance_window(org_id)
    end_hour = int(end.split(":")[0])
    return now_hour() >= end_hour

async def create_attendance_entry(org_id, date, project_id, user_id, status, note, marked_by, source):
    existing = await db.attendance_entries.find_one({"org_id": org_id, "date": date, "user_id": user_id})
    if existing:
        raise HTTPException(status_code=400, detail="Attendance already marked for this user today")

    if status not in ATTENDANCE_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be: {', '.join(ATTENDANCE_STATUSES)}")

    # Auto-late if past deadline and user marks Present
    if status == "Present" and await is_past_deadline(org_id) and marked_by == user_id:
        status = "Late"

    entry = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "date": date,
        "project_id": project_id,
        "user_id": user_id,
        "status": status,
        "note": note,
        "marked_at": datetime.now(timezone.utc).isoformat(),
        "marked_by_user_id": marked_by,
        "source": source,
    }
    await db.attendance_entries.insert_one(entry)
    # Auto-resolve any MissingAttendance reminders
    await auto_resolve_reminders(org_id, "MissingAttendance", date, user_id, user_id)
    return {k: v for k, v in entry.items() if k != "_id"}

# ── Attendance Routes ────────────────────────────────────────────

@api_router.post("/attendance/mark", status_code=201)
async def mark_attendance_self(data: AttendanceMarkSelf, user: dict = Depends(get_current_user)):
    date = today_str()
    entry = await create_attendance_entry(
        user["org_id"], date, data.project_id, user["id"],
        data.status, data.note, user["id"], data.source
    )
    await log_audit(user["org_id"], user["id"], user["email"], "attendance_marked", "attendance", entry["id"],
                    {"status": entry["status"], "date": date})
    return entry

@api_router.post("/attendance/mark-for-user", status_code=201)
async def mark_attendance_for_user(data: AttendanceMarkForUser, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Only managers/admins can mark for others")

    target = await db.users.find_one({"id": data.user_id, "org_id": user["org_id"]})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    # SiteManager: verify they manage a project the target user is on
    if user["role"] == "SiteManager":
        mgr_projects = await db.project_team.find(
            {"user_id": user["id"], "active": True, "role_in_project": "SiteManager"}, {"_id": 0, "project_id": 1}
        ).to_list(100)
        mgr_pids = {m["project_id"] for m in mgr_projects}
        target_projects = await db.project_team.find(
            {"user_id": data.user_id, "active": True}, {"_id": 0, "project_id": 1}
        ).to_list(100)
        target_pids = {m["project_id"] for m in target_projects}
        if not mgr_pids & target_pids:
            raise HTTPException(status_code=403, detail="User not in any of your managed projects")

    date = today_str()
    entry = await create_attendance_entry(
        user["org_id"], date, data.project_id, data.user_id,
        data.status, data.note, user["id"], data.source
    )
    await log_audit(user["org_id"], user["id"], user["email"], "attendance_overridden", "attendance", entry["id"],
                    {"for_user": data.user_id, "status": entry["status"], "date": date})
    return entry

@api_router.get("/attendance/my-today")
async def get_my_attendance_today(user: dict = Depends(get_current_user)):
    date = today_str()
    entry = await db.attendance_entries.find_one({"org_id": user["org_id"], "date": date, "user_id": user["id"]}, {"_id": 0})
    past_deadline = await is_past_deadline(user["org_id"])
    active_pids = await get_user_active_project_ids(user["id"])
    # Get project names
    projects = []
    if active_pids:
        projs = await db.projects.find({"id": {"$in": active_pids}}, {"_id": 0, "id": 1, "code": 1, "name": 1}).to_list(100)
        projects = projs
    _, end = await get_org_attendance_window(user["org_id"])
    return {
        "entry": entry,
        "date": date,
        "past_deadline": past_deadline,
        "deadline": end,
        "active_projects": projects,
    }

@api_router.get("/attendance/my-range")
async def get_my_attendance_range(user: dict = Depends(get_current_user), from_date: str = "", to_date: str = ""):
    if not from_date:
        from_date = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%d")
    if not to_date:
        to_date = today_str()
    entries = await db.attendance_entries.find(
        {"org_id": user["org_id"], "user_id": user["id"], "date": {"$gte": from_date, "$lte": to_date}},
        {"_id": 0}
    ).sort("date", -1).to_list(100)
    return entries

@api_router.get("/attendance/site-today")
async def get_site_attendance_today(user: dict = Depends(get_current_user), project_id: str = ""):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Manager access required")

    date = today_str()
    org_id = user["org_id"]

    if project_id:
        # Verify access
        if user["role"] == "SiteManager":
            mgr = await db.project_team.find_one({"project_id": project_id, "user_id": user["id"], "active": True, "role_in_project": "SiteManager"})
            if not mgr:
                raise HTTPException(status_code=403, detail="Not managing this project")
        members = await db.project_team.find({"project_id": project_id, "active": True}, {"_id": 0}).to_list(100)
    else:
        # Admin/Owner: all org team members in active projects
        if user["role"] == "SiteManager":
            mgr_projects = await db.project_team.find(
                {"user_id": user["id"], "active": True, "role_in_project": "SiteManager"}, {"_id": 0, "project_id": 1}
            ).to_list(100)
            pids = [m["project_id"] for m in mgr_projects]
            members = await db.project_team.find({"project_id": {"$in": pids}, "active": True}, {"_id": 0}).to_list(500)
        else:
            active_projs = await db.projects.find({"org_id": org_id, "status": "Active"}, {"_id": 0, "id": 1}).to_list(100)
            pids = [p["id"] for p in active_projs]
            members = await db.project_team.find({"project_id": {"$in": pids}, "active": True}, {"_id": 0}).to_list(500)

    # Deduplicate by user_id
    seen = set()
    unique_user_ids = []
    for m in members:
        if m["user_id"] not in seen:
            seen.add(m["user_id"])
            unique_user_ids.append(m["user_id"])

    # Get attendance entries for today
    entries_map = {}
    if unique_user_ids:
        entries = await db.attendance_entries.find(
            {"org_id": org_id, "date": date, "user_id": {"$in": unique_user_ids}}, {"_id": 0}
        ).to_list(500)
        entries_map = {e["user_id"]: e for e in entries}

    # Build response
    result = []
    for uid in unique_user_ids:
        u = await db.users.find_one({"id": uid}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "email": 1, "role": 1})
        if not u:
            continue
        entry = entries_map.get(uid)
        result.append({
            "user_id": uid,
            "user_name": f"{u['first_name']} {u['last_name']}",
            "user_email": u["email"],
            "user_role": u["role"],
            "attendance": entry,
            "marked": entry is not None,
        })

    missing_count = sum(1 for r in result if not r["marked"])
    return {"users": result, "missing_count": missing_count, "date": date}

@api_router.get("/attendance/missing-today")
async def get_missing_attendance_today(user: dict = Depends(get_current_user), project_id: str = ""):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Manager access required")

    date = today_str()
    org_id = user["org_id"]

    if project_id:
        if user["role"] == "SiteManager":
            mgr = await db.project_team.find_one({"project_id": project_id, "user_id": user["id"], "active": True, "role_in_project": "SiteManager"})
            if not mgr:
                raise HTTPException(status_code=403, detail="Not managing this project")
        proj = await db.projects.find_one({"id": project_id, "org_id": org_id, "status": "Active"})
        if not proj:
            return {"missing": [], "count": 0}
        members = await db.project_team.find({"project_id": project_id, "active": True}, {"_id": 0}).to_list(100)
    else:
        if user["role"] == "SiteManager":
            mgr_projects = await db.project_team.find(
                {"user_id": user["id"], "active": True, "role_in_project": "SiteManager"}, {"_id": 0, "project_id": 1}
            ).to_list(100)
            pids = [m["project_id"] for m in mgr_projects]
        else:
            active_projs = await db.projects.find({"org_id": org_id, "status": "Active"}, {"_id": 0, "id": 1}).to_list(100)
            pids = [p["id"] for p in active_projs]
        members = await db.project_team.find({"project_id": {"$in": pids}, "active": True}, {"_id": 0}).to_list(500)

    seen = set()
    unique_uids = []
    for m in members:
        if m["user_id"] not in seen:
            seen.add(m["user_id"])
            unique_uids.append(m["user_id"])

    # Find who has no entry
    marked_uids = set()
    if unique_uids:
        entries = await db.attendance_entries.find(
            {"org_id": org_id, "date": date, "user_id": {"$in": unique_uids}}, {"_id": 0, "user_id": 1}
        ).to_list(500)
        marked_uids = {e["user_id"] for e in entries}

    missing = []
    for uid in unique_uids:
        if uid not in marked_uids:
            u = await db.users.find_one({"id": uid}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "email": 1})
            if u:
                missing.append({"user_id": uid, "user_name": f"{u['first_name']} {u['last_name']}", "user_email": u["email"]})

    return {"missing": missing, "count": len(missing), "date": date}

@api_router.get("/attendance/statuses")
async def get_attendance_statuses():
    return ATTENDANCE_STATUSES

# ── Work Report Helpers ──────────────────────────────────────────

async def can_access_report(user: dict, report: dict) -> bool:
    if user["role"] in ["Admin", "Owner"]:
        return True
    if report["user_id"] == user["id"]:
        return True
    if user["role"] == "SiteManager":
        mgr = await db.project_team.find_one({
            "project_id": report["project_id"], "user_id": user["id"],
            "active": True, "role_in_project": "SiteManager"
        })
        return mgr is not None
    return False

async def can_review_report(user: dict, report: dict) -> bool:
    if user["role"] in ["Admin", "Owner"]:
        return True
    if user["role"] == "SiteManager":
        mgr = await db.project_team.find_one({
            "project_id": report["project_id"], "user_id": user["id"],
            "active": True, "role_in_project": "SiteManager"
        })
        return mgr is not None
    return False

def enrich_report(report: dict) -> dict:
    r = {k: v for k, v in report.items() if k != "_id"}
    r["total_hours"] = sum(line.get("hours", 0) for line in r.get("lines", []))
    return r

# ── Work Report Routes ───────────────────────────────────────────

@api_router.post("/work-reports/draft", status_code=201)
async def create_or_get_draft(data: WorkReportDraftCreate, user: dict = Depends(get_current_user)):
    date = data.date or today_str()
    org_id = user["org_id"]

    # Check attendance
    att = await db.attendance_entries.find_one({
        "org_id": org_id, "date": date, "user_id": user["id"],
        "status": {"$in": ["Present", "Late"]}
    })
    if not att:
        raise HTTPException(status_code=400, detail="Attendance must be marked as Present or Late before creating a work report")

    # Check project exists
    project = await db.projects.find_one({"id": data.project_id, "org_id": org_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check existing
    existing = await db.work_reports.find_one({
        "org_id": org_id, "date": date, "user_id": user["id"], "project_id": data.project_id
    }, {"_id": 0})
    if existing:
        return enrich_report(existing)

    now = datetime.now(timezone.utc).isoformat()
    report = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "date": date,
        "project_id": data.project_id,
        "user_id": user["id"],
        "attendance_entry_id": att["id"],
        "status": "Draft",
        "summary_note": "",
        "lines": [],
        "submitted_at": None,
        "approved_at": None,
        "approved_by_user_id": None,
        "reject_reason": None,
        "created_at": now,
        "updated_at": now,
    }
    await db.work_reports.insert_one(report)
    await log_audit(org_id, user["id"], user["email"], "report_draft_created", "work_report", report["id"], {"date": date, "project": data.project_id})
    return enrich_report(report)

@api_router.put("/work-reports/{report_id}")
async def update_work_report(report_id: str, data: WorkReportUpdate, user: dict = Depends(get_current_user)):
    report = await db.work_reports.find_one({"id": report_id, "org_id": user["org_id"]})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if report["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Can only edit your own reports")
    if report["status"] not in ["Draft", "Rejected"]:
        raise HTTPException(status_code=400, detail="Can only edit Draft or Rejected reports")

    update = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if data.summary_note is not None:
        update["summary_note"] = data.summary_note
    if data.lines is not None:
        update["lines"] = [
            {"id": str(uuid.uuid4()), "activity_name": l.activity_name, "hours": l.hours, "note": l.note}
            for l in data.lines
        ]
    # If rejected, re-open as Draft
    if report["status"] == "Rejected":
        update["status"] = "Draft"
        update["reject_reason"] = None

    await db.work_reports.update_one({"id": report_id}, {"$set": update})
    await log_audit(user["org_id"], user["id"], user["email"], "report_edited", "work_report", report_id)
    updated = await db.work_reports.find_one({"id": report_id}, {"_id": 0})
    return enrich_report(updated)

@api_router.post("/work-reports/{report_id}/submit")
async def submit_work_report(report_id: str, user: dict = Depends(get_current_user)):
    report = await db.work_reports.find_one({"id": report_id, "org_id": user["org_id"]})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if report["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Can only submit your own reports")
    if report["status"] not in ["Draft", "Rejected"]:
        raise HTTPException(status_code=400, detail="Report already submitted")
    if not report.get("lines") or len(report["lines"]) == 0:
        raise HTTPException(status_code=400, detail="Report must have at least one activity line")

    now = datetime.now(timezone.utc).isoformat()
    await db.work_reports.update_one({"id": report_id}, {"$set": {
        "status": "Submitted", "submitted_at": now, "reject_reason": None, "updated_at": now
    }})
    await log_audit(user["org_id"], user["id"], user["email"], "report_submitted", "work_report", report_id, {"date": report["date"]})
    # Auto-resolve MissingWorkReport reminders
    await auto_resolve_reminders(user["org_id"], "MissingWorkReport", report["date"], user["id"], user["id"])
    updated = await db.work_reports.find_one({"id": report_id}, {"_id": 0})
    return enrich_report(updated)

@api_router.post("/work-reports/{report_id}/approve")
async def approve_work_report(report_id: str, user: dict = Depends(get_current_user)):
    report = await db.work_reports.find_one({"id": report_id, "org_id": user["org_id"]})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if not await can_review_report(user, report):
        raise HTTPException(status_code=403, detail="Insufficient permissions to approve")
    if report["status"] != "Submitted":
        raise HTTPException(status_code=400, detail="Only submitted reports can be approved")

    now = datetime.now(timezone.utc).isoformat()
    await db.work_reports.update_one({"id": report_id}, {"$set": {
        "status": "Approved", "approved_at": now, "approved_by_user_id": user["id"], "updated_at": now
    }})
    await log_audit(user["org_id"], user["id"], user["email"], "report_approved", "work_report", report_id, {"date": report["date"]})
    updated = await db.work_reports.find_one({"id": report_id}, {"_id": 0})
    return enrich_report(updated)

@api_router.post("/work-reports/{report_id}/reject")
async def reject_work_report(report_id: str, data: WorkReportReject, user: dict = Depends(get_current_user)):
    report = await db.work_reports.find_one({"id": report_id, "org_id": user["org_id"]})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if not await can_review_report(user, report):
        raise HTTPException(status_code=403, detail="Insufficient permissions to reject")
    if report["status"] != "Submitted":
        raise HTTPException(status_code=400, detail="Only submitted reports can be rejected")

    now = datetime.now(timezone.utc).isoformat()
    await db.work_reports.update_one({"id": report_id}, {"$set": {
        "status": "Rejected", "reject_reason": data.reason, "updated_at": now
    }})
    await log_audit(user["org_id"], user["id"], user["email"], "report_rejected", "work_report", report_id, {"reason": data.reason})
    updated = await db.work_reports.find_one({"id": report_id}, {"_id": 0})
    return enrich_report(updated)

@api_router.get("/work-reports/my-today")
async def get_my_work_reports_today(user: dict = Depends(get_current_user)):
    date = today_str()
    reports = await db.work_reports.find(
        {"org_id": user["org_id"], "date": date, "user_id": user["id"]}, {"_id": 0}
    ).to_list(50)
    return [enrich_report(r) for r in reports]

@api_router.get("/work-reports/my-range")
async def get_my_work_reports_range(user: dict = Depends(get_current_user), from_date: str = "", to_date: str = ""):
    if not from_date:
        from_date = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%d")
    if not to_date:
        to_date = today_str()
    reports = await db.work_reports.find(
        {"org_id": user["org_id"], "user_id": user["id"], "date": {"$gte": from_date, "$lte": to_date}},
        {"_id": 0}
    ).sort("date", -1).to_list(200)
    return [enrich_report(r) for r in reports]

@api_router.get("/work-reports/project-day")
async def get_project_day_reports(user: dict = Depends(get_current_user), project_id: str = "", date: str = ""):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Manager access required")
    if not date:
        date = today_str()

    query = {"org_id": user["org_id"], "date": date}
    if project_id:
        if user["role"] == "SiteManager":
            mgr = await db.project_team.find_one({
                "project_id": project_id, "user_id": user["id"], "active": True, "role_in_project": "SiteManager"
            })
            if not mgr:
                raise HTTPException(status_code=403, detail="Not managing this project")
        query["project_id"] = project_id
    elif user["role"] == "SiteManager":
        mgr_projects = await db.project_team.find(
            {"user_id": user["id"], "active": True, "role_in_project": "SiteManager"}, {"_id": 0, "project_id": 1}
        ).to_list(100)
        pids = [m["project_id"] for m in mgr_projects]
        query["project_id"] = {"$in": pids}

    reports = await db.work_reports.find(query, {"_id": 0}).to_list(200)
    enriched = []
    for r in reports:
        er = enrich_report(r)
        u = await db.users.find_one({"id": r["user_id"]}, {"_id": 0, "first_name": 1, "last_name": 1, "email": 1})
        er["user_name"] = f"{u['first_name']} {u['last_name']}" if u else "Unknown"
        er["user_email"] = u["email"] if u else ""
        p = await db.projects.find_one({"id": r["project_id"]}, {"_id": 0, "code": 1, "name": 1})
        er["project_code"] = p["code"] if p else ""
        er["project_name"] = p["name"] if p else ""
        enriched.append(er)
    return enriched

@api_router.get("/work-reports/{report_id}")
async def get_work_report(report_id: str, user: dict = Depends(get_current_user)):
    report = await db.work_reports.find_one({"id": report_id, "org_id": user["org_id"]}, {"_id": 0})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if not await can_access_report(user, report):
        raise HTTPException(status_code=403, detail="Access denied")
    er = enrich_report(report)
    p = await db.projects.find_one({"id": report["project_id"]}, {"_id": 0, "code": 1, "name": 1})
    er["project_code"] = p["code"] if p else ""
    er["project_name"] = p["name"] if p else ""
    return er

# ── Reminder Service Functions ────────────────────────────────────

async def get_org_reminder_policy(org_id: str):
    org = await db.organizations.find_one({"id": org_id}, {"_id": 0})
    return {
        "attendance_deadline": org.get("attendance_end", "10:00"),
        "work_report_deadline": org.get("work_report_deadline", "18:30"),
        "max_reminders_per_day": org.get("max_reminders_per_day", 2),
        "escalation_after_days": org.get("escalation_after_days", 2),
        "timezone": org.get("org_timezone", "Europe/Sofia"),
    }

def get_local_now(tz_name: str):
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("Europe/Sofia")
    return datetime.now(tz)

async def compute_missing_attendance(org_id: str, date: str, scoped_project_ids=None):
    """Users assigned to active projects with no attendance entry on date."""
    if scoped_project_ids:
        pids = scoped_project_ids
    else:
        active = await db.projects.find({"org_id": org_id, "status": "Active"}, {"_id": 0, "id": 1}).to_list(200)
        pids = [p["id"] for p in active]
    if not pids:
        return []

    members = await db.project_team.find({"project_id": {"$in": pids}, "active": True}, {"_id": 0}).to_list(1000)
    seen = set()
    unique_uids = []
    for m in members:
        if m["user_id"] not in seen:
            seen.add(m["user_id"])
            unique_uids.append(m["user_id"])

    if not unique_uids:
        return []

    marked = await db.attendance_entries.find(
        {"org_id": org_id, "date": date, "user_id": {"$in": unique_uids}}, {"_id": 0, "user_id": 1}
    ).to_list(1000)
    marked_set = {e["user_id"] for e in marked}

    missing = []
    for uid in unique_uids:
        if uid not in marked_set:
            u = await db.users.find_one({"id": uid}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "email": 1, "role": 1})
            if u and u.get("role") not in ["Admin", "Owner"]:
                missing.append({"user_id": uid, "user_name": f"{u['first_name']} {u['last_name']}", "user_email": u["email"], "user_role": u.get("role", "")})
    return missing

async def compute_missing_work_reports(org_id: str, date: str, scoped_project_ids=None):
    """Users with Present/Late attendance but no Submitted/Approved report."""
    present = await db.attendance_entries.find(
        {"org_id": org_id, "date": date, "status": {"$in": ["Present", "Late"]}}, {"_id": 0, "user_id": 1}
    ).to_list(1000)
    present_uids = list({e["user_id"] for e in present})
    if not present_uids:
        return []

    if scoped_project_ids:
        pids = scoped_project_ids
    else:
        active = await db.projects.find({"org_id": org_id, "status": "Active"}, {"_id": 0, "id": 1}).to_list(200)
        pids = [p["id"] for p in active]

    members = await db.project_team.find({"project_id": {"$in": pids}, "active": True, "user_id": {"$in": present_uids}}, {"_id": 0}).to_list(1000)
    user_projects = {}
    for m in members:
        user_projects.setdefault(m["user_id"], []).append(m["project_id"])

    submitted = await db.work_reports.find(
        {"org_id": org_id, "date": date, "status": {"$in": ["Submitted", "Approved"]}}, {"_id": 0, "user_id": 1, "project_id": 1}
    ).to_list(1000)
    submitted_keys = {(r["user_id"], r["project_id"]) for r in submitted}

    missing = []
    for uid, proj_ids in user_projects.items():
        for pid in proj_ids:
            if (uid, pid) not in submitted_keys:
                u = await db.users.find_one({"id": uid}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "email": 1})
                p = await db.projects.find_one({"id": pid}, {"_id": 0, "code": 1, "name": 1})
                if u:
                    missing.append({
                        "user_id": uid, "project_id": pid,
                        "user_name": f"{u['first_name']} {u['last_name']}", "user_email": u["email"],
                        "project_code": p["code"] if p else "", "project_name": p["name"] if p else "",
                    })
    return missing

async def create_notification(org_id, user_id, ntype, title, message, data=None):
    notif = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "user_id": user_id,
        "type": ntype,
        "title": title,
        "message": message,
        "data": data or {},
        "is_read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.notifications.insert_one(notif)
    return {k: v for k, v in notif.items() if k != "_id"}

async def send_reminder_for_user(org_id, rtype, date, user_id, project_id, policy, triggered_by="system"):
    key = {"org_id": org_id, "type": rtype, "date": date, "user_id": user_id}
    if project_id:
        key["project_id"] = project_id

    existing = await db.reminder_logs.find_one(key)
    now = datetime.now(timezone.utc).isoformat()

    if existing:
        if existing["status"] in ["Resolved", "Excused"]:
            return None
        if existing["reminder_count"] >= policy["max_reminders_per_day"]:
            return None
        if existing.get("last_reminded_at"):
            last = datetime.fromisoformat(existing["last_reminded_at"])
            if (datetime.now(timezone.utc) - last).total_seconds() < 3600:
                return None
        await db.reminder_logs.update_one({"id": existing["id"]}, {"$set": {
            "status": "Reminded",
            "reminder_count": existing["reminder_count"] + 1,
            "last_reminded_at": now,
            "updated_at": now,
        }})
        reminder_id = existing["id"]
    else:
        reminder_id = str(uuid.uuid4())
        log_entry = {
            "id": reminder_id,
            "org_id": org_id,
            "type": rtype,
            "date": date,
            "user_id": user_id,
            "project_id": project_id,
            "status": "Reminded",
            "reminder_count": 1,
            "last_reminded_at": now,
            "resolved_at": None,
            "resolved_by_user_id": None,
            "excused_reason": None,
            "created_at": now,
            "updated_at": now,
        }
        await db.reminder_logs.insert_one(log_entry)

    if rtype == "MissingAttendance":
        title = "Attendance Reminder"
        message = f"You haven't marked attendance for {date}. Please mark now."
    else:
        title = "Work Report Reminder"
        message = f"You haven't submitted your work report for {date}. Please fill it now."

    await create_notification(org_id, user_id, rtype, title, message, {"date": date, "project_id": project_id})
    return reminder_id

async def auto_resolve_reminders(org_id, rtype, date, user_id, resolved_by=None):
    query = {"org_id": org_id, "type": rtype, "date": date, "user_id": user_id, "status": {"$in": ["Open", "Reminded"]}}
    now = datetime.now(timezone.utc).isoformat()
    result = await db.reminder_logs.update_many(query, {"$set": {
        "status": "Resolved", "resolved_at": now, "resolved_by_user_id": resolved_by, "updated_at": now,
    }})
    return result.modified_count

async def run_reminder_jobs():
    orgs = await db.organizations.find({}, {"_id": 0, "id": 1}).to_list(100)
    for org in orgs:
        org_id = org["id"]
        policy = await get_org_reminder_policy(org_id)
        local_now = get_local_now(policy["timezone"])
        date = local_now.strftime("%Y-%m-%d")
        current_time = local_now.strftime("%H:%M")

        if current_time >= policy["attendance_deadline"]:
            missing_att = await compute_missing_attendance(org_id, date)
            for m in missing_att:
                await send_reminder_for_user(org_id, "MissingAttendance", date, m["user_id"], None, policy)

        if current_time >= policy["work_report_deadline"]:
            missing_rep = await compute_missing_work_reports(org_id, date)
            for m in missing_rep:
                await send_reminder_for_user(org_id, "MissingWorkReport", date, m["user_id"], m["project_id"], policy)

        # Auto-resolve
        open_reminders = await db.reminder_logs.find(
            {"org_id": org_id, "date": date, "status": {"$in": ["Open", "Reminded"]}}, {"_id": 0}
        ).to_list(1000)
        for rl in open_reminders:
            if rl["type"] == "MissingAttendance":
                att = await db.attendance_entries.find_one({"org_id": org_id, "date": date, "user_id": rl["user_id"]})
                if att:
                    await auto_resolve_reminders(org_id, "MissingAttendance", date, rl["user_id"])
            elif rl["type"] == "MissingWorkReport":
                rep = await db.work_reports.find_one({
                    "org_id": org_id, "date": date, "user_id": rl["user_id"],
                    "project_id": rl.get("project_id"), "status": {"$in": ["Submitted", "Approved"]}
                })
                if rep:
                    await auto_resolve_reminders(org_id, "MissingWorkReport", date, rl["user_id"])

# ── Reminder Routes ──────────────────────────────────────────────

@api_router.get("/reminders/policy")
async def get_reminder_policy(user: dict = Depends(get_current_user)):
    return await get_org_reminder_policy(user["org_id"])

@api_router.get("/reminders/missing-attendance")
async def api_missing_attendance(user: dict = Depends(get_current_user), date: str = ""):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Manager access required")
    if not date:
        date = today_str()
    scoped = None
    if user["role"] == "SiteManager":
        mgr = await db.project_team.find({"user_id": user["id"], "active": True, "role_in_project": "SiteManager"}, {"_id": 0, "project_id": 1}).to_list(100)
        scoped = [m["project_id"] for m in mgr]
    return await compute_missing_attendance(user["org_id"], date, scoped)

@api_router.get("/reminders/missing-work-reports")
async def api_missing_work_reports(user: dict = Depends(get_current_user), date: str = ""):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Manager access required")
    if not date:
        date = today_str()
    scoped = None
    if user["role"] == "SiteManager":
        mgr = await db.project_team.find({"user_id": user["id"], "active": True, "role_in_project": "SiteManager"}, {"_id": 0, "project_id": 1}).to_list(100)
        scoped = [m["project_id"] for m in mgr]
    return await compute_missing_work_reports(user["org_id"], date, scoped)

@api_router.get("/reminders/logs")
async def get_reminder_logs(user: dict = Depends(get_current_user), date: str = "", rtype: str = ""):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Manager access required")
    if not date:
        date = today_str()
    query = {"org_id": user["org_id"], "date": date}
    if rtype:
        query["type"] = rtype
    if user["role"] == "SiteManager":
        mgr = await db.project_team.find({"user_id": user["id"], "active": True, "role_in_project": "SiteManager"}, {"_id": 0, "project_id": 1}).to_list(100)
        pids = [m["project_id"] for m in mgr]
        members = await db.project_team.find({"project_id": {"$in": pids}, "active": True}, {"_id": 0, "user_id": 1}).to_list(500)
        uids = list({m["user_id"] for m in members})
        query["user_id"] = {"$in": uids}

    logs = await db.reminder_logs.find(query, {"_id": 0}).sort("updated_at", -1).to_list(500)
    for rl in logs:
        u = await db.users.find_one({"id": rl["user_id"]}, {"_id": 0, "first_name": 1, "last_name": 1, "email": 1})
        rl["user_name"] = f"{u['first_name']} {u['last_name']}" if u else "Unknown"
        rl["user_email"] = u["email"] if u else ""
        if rl.get("project_id"):
            p = await db.projects.find_one({"id": rl["project_id"]}, {"_id": 0, "code": 1, "name": 1})
            rl["project_code"] = p["code"] if p else ""
        else:
            rl["project_code"] = ""
    return logs

@api_router.post("/reminders/send")
async def send_reminders_manual(data: SendReminderRequest, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Manager access required")
    if data.type not in REMINDER_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid type. Must be: {', '.join(REMINDER_TYPES)}")

    date = data.date or today_str()
    policy = await get_org_reminder_policy(user["org_id"])
    sent = 0
    for uid in data.user_ids:
        result = await send_reminder_for_user(user["org_id"], data.type, date, uid, data.project_id, policy, user["id"])
        if result:
            sent += 1
    await log_audit(user["org_id"], user["id"], user["email"], "reminder_sent", "reminder", "", {"type": data.type, "count": sent, "date": date})
    return {"sent": sent, "total": len(data.user_ids)}

@api_router.post("/reminders/excuse")
async def excuse_reminder(data: ExcuseRequest, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Manager access required")

    query = {"org_id": user["org_id"], "type": data.type, "date": data.date, "user_id": data.user_id}
    if data.project_id:
        query["project_id"] = data.project_id

    existing = await db.reminder_logs.find_one(query)
    now = datetime.now(timezone.utc).isoformat()
    if existing:
        await db.reminder_logs.update_one({"id": existing["id"]}, {"$set": {
            "status": "Excused", "excused_reason": data.reason, "resolved_by_user_id": user["id"], "updated_at": now,
        }})
    else:
        await db.reminder_logs.insert_one({
            "id": str(uuid.uuid4()), "org_id": user["org_id"], "type": data.type, "date": data.date,
            "user_id": data.user_id, "project_id": data.project_id, "status": "Excused",
            "reminder_count": 0, "last_reminded_at": None, "resolved_at": None,
            "resolved_by_user_id": user["id"], "excused_reason": data.reason,
            "created_at": now, "updated_at": now,
        })
    await log_audit(user["org_id"], user["id"], user["email"], "reminder_excused", "reminder", "", {"type": data.type, "user_id": data.user_id, "reason": data.reason})
    return {"ok": True}

@api_router.post("/internal/run-reminder-jobs")
async def trigger_reminder_jobs():
    await run_reminder_jobs()
    return {"ok": True, "ran_at": datetime.now(timezone.utc).isoformat()}

# ── Notification Routes ──────────────────────────────────────────

@api_router.get("/notifications/my")
async def get_my_notifications(user: dict = Depends(get_current_user), limit: int = 30):
    notifs = await db.notifications.find(
        {"org_id": user["org_id"], "user_id": user["id"]}, {"_id": 0}
    ).sort("created_at", -1).limit(limit).to_list(limit)
    unread = await db.notifications.count_documents({"org_id": user["org_id"], "user_id": user["id"], "is_read": False})
    return {"notifications": notifs, "unread_count": unread}

@api_router.post("/notifications/mark-read")
async def mark_notifications_read(user: dict = Depends(get_current_user)):
    await db.notifications.update_many(
        {"org_id": user["org_id"], "user_id": user["id"], "is_read": False},
        {"$set": {"is_read": True}}
    )
    return {"ok": True}

# ── Dashboard Stats ──────────────────────────────────────────────

@api_router.get("/dashboard/stats")
async def get_dashboard_stats(user: dict = Depends(get_current_user)):
    org_id = user["org_id"]
    status_counts = {}
    async for doc in db.projects.aggregate([
        {"$match": {"org_id": org_id}},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}}
    ]):
        status_counts[doc["_id"]] = doc["count"]

    users_count = await db.users.count_documents({"org_id": org_id, "is_active": True})

    # Attendance stats for today
    date = today_str()
    today_marked = await db.attendance_entries.count_documents({"org_id": org_id, "date": date})
    today_present = await db.attendance_entries.count_documents({"org_id": org_id, "date": date, "status": {"$in": ["Present", "Late"]}})

    # Work report stats
    pending_reports = await db.work_reports.count_documents({"org_id": org_id, "date": date, "status": "Submitted"})

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

@api_router.get("/project-enums")
async def get_project_enums():
    return {"statuses": PROJECT_STATUSES, "types": PROJECT_TYPES, "team_roles": PROJECT_TEAM_ROLES}

# ── Misc Routes ──────────────────────────────────────────────────

@api_router.get("/roles")
async def list_roles():
    return ROLES

@api_router.get("/subscription")
async def get_subscription(user: dict = Depends(get_current_user)):
    sub = await db.subscriptions.find_one({"org_id": user["org_id"]}, {"_id": 0})
    return sub

@api_router.get("/modules")
async def list_modules():
    return MODULES

@api_router.get("/health")
async def health():
    return {"status": "ok"}

# ── App Setup ────────────────────────────────────────────────────

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    await seed_data()
    await db.users.create_index("email")
    await db.users.create_index("org_id")
    await db.organizations.create_index("id", unique=True)
    await db.feature_flags.create_index([("org_id", 1), ("module_code", 1)])
    await db.audit_logs.create_index([("org_id", 1), ("timestamp", -1)])
    await db.projects.create_index([("org_id", 1), ("code", 1)], unique=True)
    await db.projects.create_index([("org_id", 1), ("status", 1)])
    await db.project_team.create_index([("project_id", 1), ("user_id", 1)])
    await db.project_team.create_index("user_id")
    await db.project_phases.create_index("project_id")
    await db.attendance_entries.create_index([("org_id", 1), ("date", 1), ("user_id", 1)], unique=True)
    await db.attendance_entries.create_index([("org_id", 1), ("date", 1)])
    await db.work_reports.create_index([("org_id", 1), ("date", 1), ("user_id", 1), ("project_id", 1)], unique=True)
    await db.work_reports.create_index([("org_id", 1), ("date", 1)])
    await db.work_reports.create_index([("org_id", 1), ("user_id", 1)])

@app.on_event("shutdown")
async def shutdown():
    client.close()
