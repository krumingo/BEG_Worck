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
    return {
        "active_projects": status_counts.get("Active", 0),
        "paused_projects": status_counts.get("Paused", 0),
        "completed_projects": status_counts.get("Completed", 0),
        "draft_projects": status_counts.get("Draft", 0),
        "total_projects": sum(status_counts.values()),
        "users_count": users_count,
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

@app.on_event("shutdown")
async def shutdown():
    client.close()
