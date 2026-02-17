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
