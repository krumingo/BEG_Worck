from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request
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
import stripe

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

# ── Subscription Plans Configuration ────────────────────────────────
# Plan module mappings based on user requirements:
# Free: Projects (M1), Attendance (M3), WorkReports (part of M3), Reminders/Notifications (M0 core)
# Pro: ALL modules
# Enterprise: Pro + placeholder limits/support

SUBSCRIPTION_PLANS = {
    "free": {
        "name": "Free Trial",
        "price": 0,
        "stripe_price_id": None,  # No Stripe for free tier
        "allowed_modules": ["M0", "M1", "M3"],  # Core + Projects + Attendance/WorkReports
        "limits": {
            "users": 3,
            "projects": 2,
            "monthly_invoices": 5,
            "storage_mb": 100
        },
        "trial_days": 14,
        "description": "14-day trial with basic features",
    },
    "pro": {
        "name": "Professional",
        "price": 49.00,
        "stripe_price_id": os.environ.get("STRIPE_PRICE_ID_PRO"),
        "allowed_modules": ["M0", "M1", "M2", "M3", "M4", "M5", "M9"],  # All current modules
        "limits": {
            "users": 20,
            "projects": 50,
            "monthly_invoices": 500,
            "storage_mb": 2000
        },
        "trial_days": 0,
        "description": "Full access to all features",
    },
    "enterprise": {
        "name": "Enterprise",
        "price": 149.00,
        "stripe_price_id": os.environ.get("STRIPE_PRICE_ID_ENTERPRISE"),
        "allowed_modules": ["M0", "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9"],
        "limits": {
            "users": 100,
            "projects": 500,
            "monthly_invoices": 5000,
            "storage_mb": 20000
        },
        "trial_days": 0,
        "description": "Unlimited users and premium support",
        "support_priority": "priority",
        "custom_integrations": True,
    }
}

# Limit warning threshold (80%)
LIMIT_WARNING_THRESHOLD = 0.8

SUBSCRIPTION_STATUSES = ["trialing", "active", "past_due", "canceled", "incomplete"]
STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY", "")

# STRIPE_MOCK_MODE: When True, Stripe API calls are simulated for development/testing
# Real Stripe integration requires: STRIPE_API_KEY, STRIPE_PRICE_ID_PRO, STRIPE_PRICE_ID_ENTERPRISE, STRIPE_WEBHOOK_SECRET
def is_stripe_configured():
    """Check if Stripe is properly configured for real payments"""
    api_key = os.environ.get("STRIPE_API_KEY", "")
    # Check if we have a real API key (not placeholder or test emergent key)
    if not api_key or api_key == "sk_test_emergent" or api_key.startswith("sk_test_emergent"):
        return False
    pro_price = os.environ.get("STRIPE_PRICE_ID_PRO")
    enterprise_price = os.environ.get("STRIPE_PRICE_ID_ENTERPRISE")
    return bool(pro_price and enterprise_price)

STRIPE_MOCK_MODE = not is_stripe_configured()

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

# ── M2 Estimates / BOQ Models ────────────────────────────────────

OFFER_STATUSES = ["Draft", "Sent", "Accepted", "Rejected", "Archived"]
OFFER_UNITS = ["m2", "m", "pcs", "hours", "lot", "kg", "l"]

class OfferLineInput(BaseModel):
    activity_code: Optional[str] = None
    activity_name: str
    unit: str = "pcs"
    qty: float = 1
    material_unit_cost: float = 0
    labor_unit_cost: float = 0
    labor_hours_per_unit: Optional[float] = None
    note: Optional[str] = None
    sort_order: int = 0

class OfferCreate(BaseModel):
    project_id: str
    title: str
    currency: str = "EUR"
    vat_percent: float = 20.0
    notes: str = ""
    lines: List[OfferLineInput] = []

class OfferUpdate(BaseModel):
    title: Optional[str] = None
    currency: Optional[str] = None
    vat_percent: Optional[float] = None
    notes: Optional[str] = None

class OfferLinesUpdate(BaseModel):
    lines: List[OfferLineInput]

class OfferReject(BaseModel):
    reason: Optional[str] = None

class ActivityCatalogCreate(BaseModel):
    project_id: str
    code: Optional[str] = None
    name: str
    default_unit: str = "pcs"
    default_material_unit_cost: float = 0
    default_labor_unit_cost: float = 0
    default_labor_hours_per_unit: Optional[float] = None
    active: bool = True

class ActivityCatalogUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    default_unit: Optional[str] = None
    default_material_unit_cost: Optional[float] = None
    default_labor_unit_cost: Optional[float] = None
    default_labor_hours_per_unit: Optional[float] = None
    active: Optional[bool] = None

# ── M4 HR / Payroll Models ────────────────────────────────────────

PAY_TYPES = ["Hourly", "Daily", "Monthly"]
PAY_SCHEDULES = ["Weekly", "Monthly"]
ADVANCE_TYPES = ["Advance", "Loan"]
ADVANCE_STATUSES = ["Open", "Closed"]
PAYROLL_STATUSES = ["Draft", "Finalized", "Paid"]
PAYSLIP_STATUSES = ["Draft", "Finalized", "Paid"]
PAYMENT_METHODS = ["Cash", "BankTransfer"]

class EmployeeProfileCreate(BaseModel):
    user_id: str
    pay_type: str = "Daily"
    hourly_rate: Optional[float] = None
    daily_rate: Optional[float] = None
    monthly_salary: Optional[float] = None
    standard_hours_per_day: float = 8
    pay_schedule: str = "Monthly"
    active: bool = True
    start_date: Optional[str] = None

class EmployeeProfileUpdate(BaseModel):
    pay_type: Optional[str] = None
    hourly_rate: Optional[float] = None
    daily_rate: Optional[float] = None
    monthly_salary: Optional[float] = None
    standard_hours_per_day: Optional[float] = None
    pay_schedule: Optional[str] = None
    active: Optional[bool] = None
    start_date: Optional[str] = None

class AdvanceLoanCreate(BaseModel):
    user_id: str
    type: str = "Advance"
    amount: float
    currency: str = "EUR"
    issued_date: Optional[str] = None
    note: Optional[str] = None

class PayrollRunCreate(BaseModel):
    period_type: str = "Monthly"
    period_start: str
    period_end: str

class SetDeductionsRequest(BaseModel):
    deductions_amount: float = 0
    advances_to_deduct: List[dict] = []  # [{advance_id, amount}]

class MarkPaidRequest(BaseModel):
    method: str = "Cash"
    reference: Optional[str] = None
    note: Optional[str] = None

# ── M5 Finance Models ─────────────────────────────────────────────

ACCOUNT_TYPES = ["Cash", "Bank"]
INVOICE_DIRECTIONS = ["Issued", "Received"]
INVOICE_STATUSES = ["Draft", "Sent", "PartiallyPaid", "Paid", "Overdue", "Cancelled"]
PAYMENT_DIRECTIONS = ["Inflow", "Outflow"]
COST_CATEGORIES = ["Materials", "Labor", "Subcontract", "Other"]

class FinancialAccountCreate(BaseModel):
    name: str
    type: str = "Cash"
    currency: str = "EUR"
    opening_balance: float = 0
    active: bool = True

class FinancialAccountUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    opening_balance: Optional[float] = None
    active: Optional[bool] = None

class InvoiceLineInput(BaseModel):
    description: str
    unit: Optional[str] = None
    qty: float = 1
    unit_price: float = 0
    project_id: Optional[str] = None
    cost_category: Optional[str] = None

class InvoiceCreate(BaseModel):
    direction: str  # Issued or Received
    invoice_no: str
    project_id: Optional[str] = None
    counterparty_name: Optional[str] = None
    issue_date: str
    due_date: str
    currency: str = "EUR"
    vat_percent: float = 20.0
    notes: Optional[str] = None
    lines: List[InvoiceLineInput] = []

class InvoiceUpdate(BaseModel):
    invoice_no: Optional[str] = None
    counterparty_name: Optional[str] = None
    project_id: Optional[str] = None
    issue_date: Optional[str] = None
    due_date: Optional[str] = None
    vat_percent: Optional[float] = None
    notes: Optional[str] = None

class InvoiceLinesUpdate(BaseModel):
    lines: List[InvoiceLineInput]

class PaymentCreate(BaseModel):
    direction: str  # Inflow or Outflow
    amount: float
    currency: str = "EUR"
    date: str
    method: str = "Cash"
    account_id: str
    counterparty_name: Optional[str] = None
    reference: Optional[str] = None
    note: Optional[str] = None

class AllocationInput(BaseModel):
    invoice_id: str
    amount: float

class AllocatePaymentRequest(BaseModel):
    allocations: List[AllocationInput]

# ── M9 Overhead Cost Models ───────────────────────────────────────

OVERHEAD_FREQUENCIES = ["OneTime", "Monthly", "Weekly"]
OVERHEAD_ALLOCATION_TYPES = ["CompanyWide", "PerPerson", "PerAssetAmortized"]
OVERHEAD_METHODS = ["PersonDays", "Hours"]

class OverheadCategoryCreate(BaseModel):
    name: str
    active: bool = True

class OverheadCategoryUpdate(BaseModel):
    name: Optional[str] = None
    active: Optional[bool] = None

class OverheadCostCreate(BaseModel):
    category_id: str
    name: str
    amount: float
    currency: str = "EUR"
    vat_percent: float = 20.0
    date_incurred: str
    frequency: str = "OneTime"
    allocation_type: str = "CompanyWide"
    note: Optional[str] = None

class OverheadCostUpdate(BaseModel):
    category_id: Optional[str] = None
    name: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    vat_percent: Optional[float] = None
    date_incurred: Optional[str] = None
    frequency: Optional[str] = None
    allocation_type: Optional[str] = None
    note: Optional[str] = None

class OverheadAssetCreate(BaseModel):
    name: str
    purchase_cost: float
    currency: str = "EUR"
    purchase_date: str
    useful_life_months: int = 60
    assigned_to_user_id: Optional[str] = None
    active: bool = True
    note: Optional[str] = None

class OverheadAssetUpdate(BaseModel):
    name: Optional[str] = None
    purchase_cost: Optional[float] = None
    currency: Optional[str] = None
    purchase_date: Optional[str] = None
    useful_life_months: Optional[int] = None
    assigned_to_user_id: Optional[str] = None
    active: Optional[bool] = None
    note: Optional[str] = None

class OverheadSnapshotCompute(BaseModel):
    period_start: str
    period_end: str
    method: str = "PersonDays"
    notes: Optional[str] = None

class OverheadAllocateRequest(BaseModel):
    method: str = "PersonDays"

# ── Billing Models ─────────────────────────────────────────────────

class OrgSignupRequest(BaseModel):
    org_name: str
    owner_name: str
    owner_email: str
    password: str

class CreateCheckoutRequest(BaseModel):
    plan_id: str
    origin_url: str

class SubscriptionUpdate(BaseModel):
    plan_id: Optional[str] = None
    status: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    current_period_start: Optional[str] = None
    current_period_end: Optional[str] = None
    trial_ends_at: Optional[str] = None

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

# ── Module Access Enforcement ────────────────────────────────────
# Server-side enforcement: Never trust frontend for subscription status

async def check_module_access_for_org(org_id: str, module_code: str) -> tuple[bool, str]:
    """
    Check if an organization has access to a module based on their subscription.
    Returns (allowed: bool, reason: str or None)
    """
    sub = await db.subscriptions.find_one({"org_id": org_id}, {"_id": 0})
    if not sub:
        return False, "No subscription"
    
    plan = SUBSCRIPTION_PLANS.get(sub.get("plan_id", "free"), SUBSCRIPTION_PLANS["free"])
    status = sub.get("status", "")
    trial_ends_at = sub.get("trial_ends_at")
    
    # Check trial expiration
    if status == "trialing" and trial_ends_at:
        now = datetime.now(timezone.utc)
        try:
            trial_end_dt = datetime.fromisoformat(trial_ends_at.replace("Z", "+00:00"))
            if now >= trial_end_dt:
                await db.subscriptions.update_one(
                    {"org_id": org_id},
                    {"$set": {"status": "past_due", "updated_at": now.isoformat()}}
                )
                status = "past_due"
        except (ValueError, TypeError):
            pass
    
    # Check if subscription is active
    if status in ["canceled", "past_due", "incomplete"]:
        if module_code == "M0":
            return True, None  # Always allow core
        return False, f"Subscription {status}. Please upgrade your plan."
    
    allowed = module_code in plan["allowed_modules"]
    return allowed, None if allowed else "Module not in your current plan"

async def require_module(module_code: str, user: dict) -> dict:
    """Enforce module access for a user's organization. Raises HTTPException if not allowed."""
    allowed, reason = await check_module_access_for_org(user["org_id"], module_code)
    if not allowed:
        raise HTTPException(status_code=403, detail=reason or f"Module {module_code} not available")
    return user

# Dependency factories for module enforcement
def require_m2(user: dict = Depends(get_current_user)):
    """Require M2 (Estimates/BOQ) module access"""
    return require_module("M2", user)

def require_m4(user: dict = Depends(get_current_user)):
    """Require M4 (HR/Payroll) module access"""
    return require_module("M4", user)

def require_m5(user: dict = Depends(get_current_user)):
    """Require M5 (Finance) module access"""
    return require_module("M5", user)

def require_m9(user: dict = Depends(get_current_user)):
    """Require M9 (Admin Console/BI) module access"""
    return require_module("M9", user)

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

# ── M2 Estimates / BOQ Routes ────────────────────────────────────

async def get_next_offer_no(org_id: str) -> str:
    """Generate sequential offer number like OFF-0001"""
    last = await db.offers.find_one(
        {"org_id": org_id},
        {"_id": 0, "offer_no": 1},
        sort=[("created_at", -1)]
    )
    if last and last.get("offer_no"):
        try:
            num = int(last["offer_no"].split("-")[1]) + 1
        except:
            num = 1
    else:
        num = 1
    return f"OFF-{num:04d}"

def compute_offer_line(line: dict) -> dict:
    """Compute line totals"""
    qty = line.get("qty", 0)
    material = line.get("material_unit_cost", 0)
    labor = line.get("labor_unit_cost", 0)
    line["line_material_cost"] = round(qty * material, 2)
    line["line_labor_cost"] = round(qty * labor, 2)
    line["line_total"] = round(line["line_material_cost"] + line["line_labor_cost"], 2)
    return line

def compute_offer_totals(offer: dict) -> dict:
    """Compute offer subtotal, vat, total"""
    lines = offer.get("lines", [])
    subtotal = sum(l.get("line_total", 0) for l in lines)
    vat_percent = offer.get("vat_percent", 0)
    vat_amount = round(subtotal * vat_percent / 100, 2)
    total = round(subtotal + vat_amount, 2)
    offer["subtotal"] = round(subtotal, 2)
    offer["vat_amount"] = vat_amount
    offer["total"] = total
    return offer

async def can_edit_offer(user: dict, offer: dict) -> bool:
    """Check if user can edit offer (must be Draft and have project access)"""
    if offer["status"] != "Draft":
        return False
    return await can_manage_project(user, offer["project_id"])

# ── Offer CRUD ────────────────────────────────────────────────────

@api_router.post("/offers", status_code=201)
async def create_offer(data: OfferCreate, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    project = await db.projects.find_one({"id": data.project_id, "org_id": user["org_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not await can_manage_project(user, data.project_id):
        raise HTTPException(status_code=403, detail="Not authorized for this project")
    
    now = datetime.now(timezone.utc).isoformat()
    offer_no = await get_next_offer_no(user["org_id"])
    
    lines = []
    for i, line in enumerate(data.lines):
        l = {
            "id": str(uuid.uuid4()),
            "activity_code": line.activity_code,
            "activity_name": line.activity_name,
            "unit": line.unit,
            "qty": line.qty,
            "material_unit_cost": line.material_unit_cost,
            "labor_unit_cost": line.labor_unit_cost,
            "labor_hours_per_unit": line.labor_hours_per_unit,
            "note": line.note,
            "sort_order": line.sort_order or i,
        }
        lines.append(compute_offer_line(l))
    
    offer = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "project_id": data.project_id,
        "offer_no": offer_no,
        "title": data.title,
        "status": "Draft",
        "version": 1,
        "parent_offer_id": None,
        "currency": data.currency,
        "vat_percent": data.vat_percent,
        "lines": lines,
        "notes": data.notes,
        "created_at": now,
        "updated_at": now,
        "sent_at": None,
        "accepted_at": None,
    }
    offer = compute_offer_totals(offer)
    
    await db.offers.insert_one(offer)
    await log_audit(user["org_id"], user["id"], user["email"], "offer_created", "offer", offer["id"], 
                    {"offer_no": offer_no, "title": data.title, "project_id": data.project_id})
    
    return {k: v for k, v in offer.items() if k != "_id"}

@api_router.get("/offers")
async def list_offers(
    user: dict = Depends(get_current_user),
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
):
    query = {"org_id": user["org_id"]}
    
    if project_id:
        if not await can_access_project(user, project_id):
            raise HTTPException(status_code=403, detail="Access denied to project")
        query["project_id"] = project_id
    elif user["role"] not in ["Admin", "Owner", "Accountant"]:
        # Limit to assigned projects
        assigned = await get_user_project_ids(user["id"])
        query["project_id"] = {"$in": assigned}
    
    if status:
        query["status"] = status
    
    offers = await db.offers.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    
    if search:
        s = search.lower()
        offers = [o for o in offers if s in o.get("offer_no", "").lower() or s in o.get("title", "").lower()]
    
    # Enrich with project info
    for o in offers:
        p = await db.projects.find_one({"id": o["project_id"]}, {"_id": 0, "code": 1, "name": 1})
        o["project_code"] = p["code"] if p else ""
        o["project_name"] = p["name"] if p else ""
        o["line_count"] = len(o.get("lines", []))
    
    return offers

@api_router.get("/offers/{offer_id}")
async def get_offer(offer_id: str, user: dict = Depends(get_current_user)):
    offer = await db.offers.find_one({"id": offer_id, "org_id": user["org_id"]}, {"_id": 0})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if not await can_access_project(user, offer["project_id"]):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Enrich
    p = await db.projects.find_one({"id": offer["project_id"]}, {"_id": 0, "code": 1, "name": 1})
    offer["project_code"] = p["code"] if p else ""
    offer["project_name"] = p["name"] if p else ""
    
    return offer

@api_router.put("/offers/{offer_id}")
async def update_offer(offer_id: str, data: OfferUpdate, user: dict = Depends(get_current_user)):
    offer = await db.offers.find_one({"id": offer_id, "org_id": user["org_id"]})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if not await can_edit_offer(user, offer):
        raise HTTPException(status_code=403, detail="Can only edit Draft offers you manage")
    
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    await db.offers.update_one({"id": offer_id}, {"$set": update})
    
    # Recompute if vat changed
    if "vat_percent" in update:
        updated = await db.offers.find_one({"id": offer_id})
        updated = compute_offer_totals({k: v for k, v in updated.items() if k != "_id"})
        await db.offers.update_one({"id": offer_id}, {"$set": {
            "subtotal": updated["subtotal"],
            "vat_amount": updated["vat_amount"],
            "total": updated["total"],
        }})
    
    await log_audit(user["org_id"], user["id"], user["email"], "offer_updated", "offer", offer_id, update)
    return await db.offers.find_one({"id": offer_id}, {"_id": 0})

@api_router.put("/offers/{offer_id}/lines")
async def update_offer_lines(offer_id: str, data: OfferLinesUpdate, user: dict = Depends(get_current_user)):
    offer = await db.offers.find_one({"id": offer_id, "org_id": user["org_id"]})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if not await can_edit_offer(user, offer):
        raise HTTPException(status_code=403, detail="Can only edit Draft offers you manage")
    
    lines = []
    for i, line in enumerate(data.lines):
        l = {
            "id": str(uuid.uuid4()),
            "activity_code": line.activity_code,
            "activity_name": line.activity_name,
            "unit": line.unit,
            "qty": line.qty,
            "material_unit_cost": line.material_unit_cost,
            "labor_unit_cost": line.labor_unit_cost,
            "labor_hours_per_unit": line.labor_hours_per_unit,
            "note": line.note,
            "sort_order": line.sort_order or i,
        }
        lines.append(compute_offer_line(l))
    
    now = datetime.now(timezone.utc).isoformat()
    updated = {
        "lines": lines,
        "updated_at": now,
    }
    
    # Compute totals
    offer["lines"] = lines
    offer["vat_percent"] = offer.get("vat_percent", 0)
    offer = compute_offer_totals(offer)
    updated["subtotal"] = offer["subtotal"]
    updated["vat_amount"] = offer["vat_amount"]
    updated["total"] = offer["total"]
    
    await db.offers.update_one({"id": offer_id}, {"$set": updated})
    await log_audit(user["org_id"], user["id"], user["email"], "offer_lines_updated", "offer", offer_id, 
                    {"line_count": len(lines)})
    
    return await db.offers.find_one({"id": offer_id}, {"_id": 0})

@api_router.post("/offers/{offer_id}/send")
async def send_offer(offer_id: str, user: dict = Depends(get_current_user)):
    offer = await db.offers.find_one({"id": offer_id, "org_id": user["org_id"]})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if not await can_manage_project(user, offer["project_id"]):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if offer["status"] != "Draft":
        raise HTTPException(status_code=400, detail="Only Draft offers can be sent")
    if len(offer.get("lines", [])) == 0:
        raise HTTPException(status_code=400, detail="Offer must have at least one line")
    
    now = datetime.now(timezone.utc).isoformat()
    await db.offers.update_one({"id": offer_id}, {"$set": {
        "status": "Sent",
        "sent_at": now,
        "updated_at": now,
    }})
    await log_audit(user["org_id"], user["id"], user["email"], "offer_sent", "offer", offer_id, 
                    {"offer_no": offer["offer_no"]})
    
    return await db.offers.find_one({"id": offer_id}, {"_id": 0})

@api_router.post("/offers/{offer_id}/accept")
async def accept_offer(offer_id: str, user: dict = Depends(get_current_user)):
    offer = await db.offers.find_one({"id": offer_id, "org_id": user["org_id"]})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner can accept offers")
    if offer["status"] != "Sent":
        raise HTTPException(status_code=400, detail="Only Sent offers can be accepted")
    
    now = datetime.now(timezone.utc).isoformat()
    await db.offers.update_one({"id": offer_id}, {"$set": {
        "status": "Accepted",
        "accepted_at": now,
        "updated_at": now,
    }})
    await log_audit(user["org_id"], user["id"], user["email"], "offer_accepted", "offer", offer_id,
                    {"offer_no": offer["offer_no"], "total": offer.get("total", 0)})
    
    return await db.offers.find_one({"id": offer_id}, {"_id": 0})

@api_router.post("/offers/{offer_id}/reject")
async def reject_offer(offer_id: str, data: OfferReject, user: dict = Depends(get_current_user)):
    offer = await db.offers.find_one({"id": offer_id, "org_id": user["org_id"]})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner can reject offers")
    if offer["status"] != "Sent":
        raise HTTPException(status_code=400, detail="Only Sent offers can be rejected")
    
    now = datetime.now(timezone.utc).isoformat()
    await db.offers.update_one({"id": offer_id}, {"$set": {
        "status": "Rejected",
        "reject_reason": data.reason,
        "updated_at": now,
    }})
    await log_audit(user["org_id"], user["id"], user["email"], "offer_rejected", "offer", offer_id,
                    {"offer_no": offer["offer_no"], "reason": data.reason})
    
    return await db.offers.find_one({"id": offer_id}, {"_id": 0})

@api_router.post("/offers/{offer_id}/new-version")
async def create_offer_version(offer_id: str, user: dict = Depends(get_current_user)):
    offer = await db.offers.find_one({"id": offer_id, "org_id": user["org_id"]})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if not await can_manage_project(user, offer["project_id"]):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if offer["status"] not in ["Sent", "Accepted", "Rejected"]:
        raise HTTPException(status_code=400, detail="Can only version non-Draft offers")
    
    now = datetime.now(timezone.utc).isoformat()
    new_version = offer.get("version", 1) + 1
    
    # Clone lines with new IDs
    new_lines = []
    for line in offer.get("lines", []):
        l = {k: v for k, v in line.items() if k != "_id"}
        l["id"] = str(uuid.uuid4())
        new_lines.append(l)
    
    new_offer = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "project_id": offer["project_id"],
        "offer_no": offer["offer_no"],  # Keep same offer_no
        "title": offer["title"],
        "status": "Draft",
        "version": new_version,
        "parent_offer_id": offer["id"],
        "currency": offer["currency"],
        "vat_percent": offer["vat_percent"],
        "lines": new_lines,
        "subtotal": offer["subtotal"],
        "vat_amount": offer["vat_amount"],
        "total": offer["total"],
        "notes": offer.get("notes", ""),
        "created_at": now,
        "updated_at": now,
        "sent_at": None,
        "accepted_at": None,
    }
    
    await db.offers.insert_one(new_offer)
    await log_audit(user["org_id"], user["id"], user["email"], "offer_versioned", "offer", new_offer["id"],
                    {"offer_no": offer["offer_no"], "version": new_version, "from_version": offer.get("version", 1)})
    
    return {k: v for k, v in new_offer.items() if k != "_id"}

@api_router.delete("/offers/{offer_id}")
async def delete_offer(offer_id: str, user: dict = Depends(get_current_user)):
    offer = await db.offers.find_one({"id": offer_id, "org_id": user["org_id"]})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner can delete offers")
    if offer["status"] == "Accepted":
        raise HTTPException(status_code=400, detail="Cannot delete accepted offers")
    
    await db.offers.delete_one({"id": offer_id})
    await log_audit(user["org_id"], user["id"], user["email"], "offer_deleted", "offer", offer_id,
                    {"offer_no": offer["offer_no"]})
    return {"ok": True}

# ── Activity Catalog CRUD ─────────────────────────────────────────

@api_router.get("/activity-catalog")
async def list_activity_catalog(
    user: dict = Depends(get_current_user),
    project_id: Optional[str] = None,
    active_only: bool = True,
):
    query = {"org_id": user["org_id"]}
    if project_id:
        if not await can_access_project(user, project_id):
            raise HTTPException(status_code=403, detail="Access denied")
        query["project_id"] = project_id
    if active_only:
        query["active"] = True
    
    items = await db.activity_catalog.find(query, {"_id": 0}).sort("name", 1).to_list(500)
    return items

@api_router.post("/activity-catalog", status_code=201)
async def create_activity(data: ActivityCatalogCreate, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    project = await db.projects.find_one({"id": data.project_id, "org_id": user["org_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not await can_manage_project(user, data.project_id):
        raise HTTPException(status_code=403, detail="Not authorized for this project")
    
    now = datetime.now(timezone.utc).isoformat()
    item = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "project_id": data.project_id,
        "code": data.code,
        "name": data.name,
        "default_unit": data.default_unit,
        "default_material_unit_cost": data.default_material_unit_cost,
        "default_labor_unit_cost": data.default_labor_unit_cost,
        "default_labor_hours_per_unit": data.default_labor_hours_per_unit,
        "active": data.active,
        "created_at": now,
        "updated_at": now,
    }
    await db.activity_catalog.insert_one(item)
    return {k: v for k, v in item.items() if k != "_id"}

@api_router.put("/activity-catalog/{item_id}")
async def update_activity(item_id: str, data: ActivityCatalogUpdate, user: dict = Depends(get_current_user)):
    item = await db.activity_catalog.find_one({"id": item_id, "org_id": user["org_id"]})
    if not item:
        raise HTTPException(status_code=404, detail="Activity not found")
    if not await can_manage_project(user, item["project_id"]):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    await db.activity_catalog.update_one({"id": item_id}, {"$set": update})
    return await db.activity_catalog.find_one({"id": item_id}, {"_id": 0})

@api_router.delete("/activity-catalog/{item_id}")
async def delete_activity(item_id: str, user: dict = Depends(get_current_user)):
    item = await db.activity_catalog.find_one({"id": item_id, "org_id": user["org_id"]})
    if not item:
        raise HTTPException(status_code=404, detail="Activity not found")
    if not await can_manage_project(user, item["project_id"]):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    await db.activity_catalog.delete_one({"id": item_id})
    return {"ok": True}

@api_router.get("/offer-enums")
async def get_offer_enums():
    return {
        "statuses": OFFER_STATUSES,
        "units": OFFER_UNITS,
    }

# ── M4 HR / Payroll Routes ────────────────────────────────────────

def payroll_permission(user: dict):
    """Check if user has payroll access"""
    return user["role"] in ["Admin", "Owner", "Accountant"]

# ── Employee Profiles ─────────────────────────────────────────────

@api_router.get("/employees")
async def list_employees(user: dict = Depends(get_current_user)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    users = await db.users.find(
        {"org_id": user["org_id"], "role": {"$ne": "Admin"}},
        {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1}
    ).to_list(500)
    
    # Get profiles
    profiles = await db.employee_profiles.find(
        {"org_id": user["org_id"]},
        {"_id": 0}
    ).to_list(500)
    profile_map = {p["user_id"]: p for p in profiles}
    
    result = []
    for u in users:
        prof = profile_map.get(u["id"])
        result.append({
            **u,
            "profile": prof,
            "has_profile": prof is not None,
        })
    return result

@api_router.get("/employees/{user_id}")
async def get_employee(user_id: str, user: dict = Depends(get_current_user)):
    # Technicians can view own profile
    if user["id"] != user_id and not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    target = await db.users.find_one(
        {"id": user_id, "org_id": user["org_id"]},
        {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1}
    )
    if not target:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    profile = await db.employee_profiles.find_one(
        {"org_id": user["org_id"], "user_id": user_id},
        {"_id": 0}
    )
    return {**target, "profile": profile}

@api_router.post("/employees", status_code=201)
async def upsert_employee_profile(data: EmployeeProfileCreate, user: dict = Depends(get_current_user)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    target = await db.users.find_one({"id": data.user_id, "org_id": user["org_id"]})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    
    now = datetime.now(timezone.utc).isoformat()
    existing = await db.employee_profiles.find_one({"org_id": user["org_id"], "user_id": data.user_id})
    
    profile = {
        "org_id": user["org_id"],
        "user_id": data.user_id,
        "pay_type": data.pay_type,
        "hourly_rate": data.hourly_rate,
        "daily_rate": data.daily_rate,
        "monthly_salary": data.monthly_salary,
        "standard_hours_per_day": data.standard_hours_per_day,
        "pay_schedule": data.pay_schedule,
        "active": data.active,
        "start_date": data.start_date,
        "updated_at": now,
    }
    
    if existing:
        await db.employee_profiles.update_one(
            {"id": existing["id"]},
            {"$set": profile}
        )
        profile["id"] = existing["id"]
        profile["created_at"] = existing["created_at"]
    else:
        profile["id"] = str(uuid.uuid4())
        profile["created_at"] = now
        await db.employee_profiles.insert_one(profile)
    
    await log_audit(user["org_id"], user["id"], user["email"], "employee_profile_updated", "employee", data.user_id,
                    {"pay_type": data.pay_type})
    
    return {k: v for k, v in profile.items() if k != "_id"}

@api_router.put("/employees/{user_id}")
async def update_employee_profile(user_id: str, data: EmployeeProfileUpdate, user: dict = Depends(get_current_user)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    profile = await db.employee_profiles.find_one({"org_id": user["org_id"], "user_id": user_id})
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    await db.employee_profiles.update_one({"id": profile["id"]}, {"$set": update})
    await log_audit(user["org_id"], user["id"], user["email"], "employee_profile_updated", "employee", user_id, update)
    
    return await db.employee_profiles.find_one({"id": profile["id"]}, {"_id": 0})

# ── Advances / Loans ──────────────────────────────────────────────

@api_router.get("/advances")
async def list_advances(
    user: dict = Depends(get_current_user),
    user_id: Optional[str] = None,
    status: Optional[str] = None,
):
    # Technicians can view own advances
    if user["role"] == "Technician":
        user_id = user["id"]
    elif not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    query = {"org_id": user["org_id"]}
    if user_id:
        query["user_id"] = user_id
    if status:
        query["status"] = status
    
    advances = await db.advances.find(query, {"_id": 0}).sort("issued_date", -1).to_list(500)
    
    # Enrich with user name
    for adv in advances:
        u = await db.users.find_one({"id": adv["user_id"]}, {"_id": 0, "name": 1, "email": 1})
        adv["user_name"] = u.get("name", u.get("email", "Unknown").split("@")[0]) if u else "Unknown"
    
    return advances

@api_router.post("/advances", status_code=201)
async def create_advance(data: AdvanceLoanCreate, user: dict = Depends(get_current_user)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    target = await db.users.find_one({"id": data.user_id, "org_id": user["org_id"]})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    
    now = datetime.now(timezone.utc).isoformat()
    advance = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "user_id": data.user_id,
        "type": data.type,
        "amount": data.amount,
        "remaining_amount": data.amount,
        "currency": data.currency,
        "issued_date": data.issued_date or now[:10],
        "note": data.note,
        "status": "Open",
        "created_at": now,
        "updated_at": now,
    }
    await db.advances.insert_one(advance)
    
    await log_audit(user["org_id"], user["id"], user["email"], "advance_created", "advance", advance["id"],
                    {"user_id": data.user_id, "type": data.type, "amount": data.amount})
    
    return {k: v for k, v in advance.items() if k != "_id"}

@api_router.post("/advances/{advance_id}/apply-deduction")
async def apply_advance_deduction(advance_id: str, amount: float, user: dict = Depends(get_current_user)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    advance = await db.advances.find_one({"id": advance_id, "org_id": user["org_id"]})
    if not advance:
        raise HTTPException(status_code=404, detail="Advance not found")
    if advance["status"] == "Closed":
        raise HTTPException(status_code=400, detail="Advance already closed")
    if amount > advance["remaining_amount"]:
        raise HTTPException(status_code=400, detail="Amount exceeds remaining balance")
    
    new_remaining = round(advance["remaining_amount"] - amount, 2)
    new_status = "Closed" if new_remaining <= 0 else "Open"
    
    await db.advances.update_one({"id": advance_id}, {"$set": {
        "remaining_amount": new_remaining,
        "status": new_status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }})
    
    return await db.advances.find_one({"id": advance_id}, {"_id": 0})

# ── Payroll Runs ──────────────────────────────────────────────────

@api_router.get("/payroll-runs")
async def list_payroll_runs(user: dict = Depends(get_current_user), status: Optional[str] = None):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    query = {"org_id": user["org_id"]}
    if status:
        query["status"] = status
    
    runs = await db.payroll_runs.find(query, {"_id": 0}).sort("created_at", -1).to_list(100)
    
    # Enrich with payslip counts
    for run in runs:
        payslip_count = await db.payslips.count_documents({"payroll_run_id": run["id"]})
        paid_count = await db.payslips.count_documents({"payroll_run_id": run["id"], "status": "Paid"})
        run["payslip_count"] = payslip_count
        run["paid_count"] = paid_count
    
    return runs

@api_router.post("/payroll-runs", status_code=201)
async def create_payroll_run(data: PayrollRunCreate, user: dict = Depends(get_current_user)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    now = datetime.now(timezone.utc).isoformat()
    run = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "period_type": data.period_type,
        "period_start": data.period_start,
        "period_end": data.period_end,
        "status": "Draft",
        "created_by_user_id": user["id"],
        "created_at": now,
        "updated_at": now,
    }
    await db.payroll_runs.insert_one(run)
    
    await log_audit(user["org_id"], user["id"], user["email"], "payroll_run_created", "payroll_run", run["id"],
                    {"period_start": data.period_start, "period_end": data.period_end})
    
    return {k: v for k, v in run.items() if k != "_id"}

@api_router.get("/payroll-runs/{run_id}")
async def get_payroll_run(run_id: str, user: dict = Depends(get_current_user)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    run = await db.payroll_runs.find_one({"id": run_id, "org_id": user["org_id"]}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    
    # Get payslips
    payslips = await db.payslips.find({"payroll_run_id": run_id}, {"_id": 0}).to_list(500)
    for ps in payslips:
        u = await db.users.find_one({"id": ps["user_id"]}, {"_id": 0, "name": 1, "email": 1})
        ps["user_name"] = u.get("name", u.get("email", "Unknown").split("@")[0]) if u else "Unknown"
        ps["user_email"] = u.get("email", "") if u else ""
    
    run["payslips"] = payslips
    return run

@api_router.post("/payroll-runs/{run_id}/generate")
async def generate_payroll(run_id: str, user: dict = Depends(get_current_user)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    run = await db.payroll_runs.find_one({"id": run_id, "org_id": user["org_id"]})
    if not run:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    if run["status"] != "Draft":
        raise HTTPException(status_code=400, detail="Can only generate for Draft runs")
    
    period_start = run["period_start"]
    period_end = run["period_end"]
    org_id = user["org_id"]
    now = datetime.now(timezone.utc).isoformat()
    
    # Get active employee profiles
    profiles = await db.employee_profiles.find(
        {"org_id": org_id, "active": True},
        {"_id": 0}
    ).to_list(500)
    
    warnings = []
    created = 0
    
    # Get org currency
    org = await db.organizations.find_one({"id": org_id}, {"_id": 0, "currency": 1})
    currency = org.get("currency", "EUR") if org else "EUR"
    
    for profile in profiles:
        user_id = profile["user_id"]
        pay_type = profile["pay_type"]
        base_amount = 0
        details = {
            "pay_type": pay_type,
            "period_start": period_start,
            "period_end": period_end,
        }
        
        if pay_type == "Hourly":
            # Sum hours from Submitted/Approved work reports
            reports = await db.work_reports.find({
                "org_id": org_id,
                "user_id": user_id,
                "date": {"$gte": period_start, "$lte": period_end},
                "status": {"$in": ["Submitted", "Approved"]},
            }, {"_id": 0, "total_hours": 1}).to_list(500)
            total_hours = sum(r.get("total_hours", 0) for r in reports)
            hourly_rate = profile.get("hourly_rate") or 0
            base_amount = round(total_hours * hourly_rate, 2)
            details["total_hours"] = total_hours
            details["hourly_rate"] = hourly_rate
            
        elif pay_type == "Daily":
            # Count Present/Late attendance entries
            attendance = await db.attendance_entries.count_documents({
                "org_id": org_id,
                "user_id": user_id,
                "date": {"$gte": period_start, "$lte": period_end},
                "status": {"$in": ["Present", "Late"]},
            })
            daily_rate = profile.get("daily_rate") or 0
            base_amount = round(attendance * daily_rate, 2)
            details["days_present"] = attendance
            details["daily_rate"] = daily_rate
            
        elif pay_type == "Monthly":
            # Fixed salary
            base_amount = profile.get("monthly_salary") or 0
            details["monthly_salary"] = base_amount
        
        # Check if payslip exists, update or create
        existing = await db.payslips.find_one({
            "payroll_run_id": run_id,
            "user_id": user_id,
        })
        
        payslip = {
            "org_id": org_id,
            "payroll_run_id": run_id,
            "user_id": user_id,
            "base_amount": base_amount,
            "overtime_amount": 0,
            "deductions_amount": existing.get("deductions_amount", 0) if existing else 0,
            "advances_deducted_amount": existing.get("advances_deducted_amount", 0) if existing else 0,
            "currency": currency,
            "details_json": details,
            "status": "Draft",
            "paid_at": None,
            "paid_by_user_id": None,
            "updated_at": now,
        }
        payslip["net_pay"] = round(
            payslip["base_amount"] + payslip["overtime_amount"] 
            - payslip["deductions_amount"] - payslip["advances_deducted_amount"], 2
        )
        
        if existing:
            await db.payslips.update_one({"id": existing["id"]}, {"$set": payslip})
        else:
            payslip["id"] = str(uuid.uuid4())
            payslip["created_at"] = now
            await db.payslips.insert_one(payslip)
            created += 1
    
    # Log users without profiles
    all_users = await db.users.find(
        {"org_id": org_id, "role": {"$nin": ["Admin", "Owner", "Accountant"]}},
        {"_id": 0, "id": 1, "name": 1, "email": 1}
    ).to_list(500)
    profile_user_ids = {p["user_id"] for p in profiles}
    for u in all_users:
        if u["id"] not in profile_user_ids:
            name = u.get("name", u.get("email", "Unknown").split("@")[0])
            warnings.append(f"{name} has no pay profile")
    
    await log_audit(org_id, user["id"], user["email"], "payroll_generated", "payroll_run", run_id,
                    {"created": created, "profiles": len(profiles)})
    
    return {
        "ok": True,
        "created": created,
        "updated": len(profiles) - created,
        "warnings": warnings,
    }

@api_router.post("/payroll-runs/{run_id}/finalize")
async def finalize_payroll(run_id: str, user: dict = Depends(get_current_user)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    run = await db.payroll_runs.find_one({"id": run_id, "org_id": user["org_id"]})
    if not run:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    if run["status"] != "Draft":
        raise HTTPException(status_code=400, detail="Can only finalize Draft runs")
    
    # Check there are payslips
    count = await db.payslips.count_documents({"payroll_run_id": run_id})
    if count == 0:
        raise HTTPException(status_code=400, detail="Generate payslips before finalizing")
    
    now = datetime.now(timezone.utc).isoformat()
    
    # Finalize run and all payslips
    await db.payroll_runs.update_one({"id": run_id}, {"$set": {
        "status": "Finalized",
        "updated_at": now,
    }})
    await db.payslips.update_many({"payroll_run_id": run_id}, {"$set": {
        "status": "Finalized",
        "updated_at": now,
    }})
    
    await log_audit(user["org_id"], user["id"], user["email"], "payroll_finalized", "payroll_run", run_id, {})
    
    return await db.payroll_runs.find_one({"id": run_id}, {"_id": 0})

@api_router.delete("/payroll-runs/{run_id}")
async def delete_payroll_run(run_id: str, user: dict = Depends(get_current_user)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    run = await db.payroll_runs.find_one({"id": run_id, "org_id": user["org_id"]})
    if not run:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    if run["status"] != "Draft":
        raise HTTPException(status_code=400, detail="Can only delete Draft runs")
    
    await db.payslips.delete_many({"payroll_run_id": run_id})
    await db.payroll_runs.delete_one({"id": run_id})
    
    return {"ok": True}

# ── Payslips ──────────────────────────────────────────────────────

@api_router.get("/payslips")
async def list_payslips(
    user: dict = Depends(get_current_user),
    payroll_run_id: Optional[str] = None,
    user_id: Optional[str] = None,
):
    # Technicians can only view own
    if user["role"] == "Technician":
        user_id = user["id"]
    elif not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    query = {"org_id": user["org_id"]}
    if payroll_run_id:
        query["payroll_run_id"] = payroll_run_id
    if user_id:
        query["user_id"] = user_id
    
    payslips = await db.payslips.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    
    # Enrich
    for ps in payslips:
        u = await db.users.find_one({"id": ps["user_id"]}, {"_id": 0, "name": 1, "email": 1})
        ps["user_name"] = u.get("name", u.get("email", "Unknown").split("@")[0]) if u else "Unknown"
        run = await db.payroll_runs.find_one({"id": ps["payroll_run_id"]}, {"_id": 0, "period_start": 1, "period_end": 1})
        if run:
            ps["period_start"] = run["period_start"]
            ps["period_end"] = run["period_end"]
    
    return payslips

@api_router.get("/payslips/{payslip_id}")
async def get_payslip(payslip_id: str, user: dict = Depends(get_current_user)):
    payslip = await db.payslips.find_one({"id": payslip_id, "org_id": user["org_id"]}, {"_id": 0})
    if not payslip:
        raise HTTPException(status_code=404, detail="Payslip not found")
    
    # Technicians can only view own
    if user["role"] == "Technician" and payslip["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Enrich
    u = await db.users.find_one({"id": payslip["user_id"]}, {"_id": 0, "name": 1, "email": 1})
    payslip["user_name"] = u.get("name", u.get("email", "Unknown").split("@")[0]) if u else "Unknown"
    payslip["user_email"] = u.get("email", "") if u else ""
    
    run = await db.payroll_runs.find_one({"id": payslip["payroll_run_id"]}, {"_id": 0})
    payslip["payroll_run"] = run
    
    return payslip

@api_router.post("/payslips/{payslip_id}/set-deductions")
async def set_payslip_deductions(payslip_id: str, data: SetDeductionsRequest, user: dict = Depends(get_current_user)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    payslip = await db.payslips.find_one({"id": payslip_id, "org_id": user["org_id"]})
    if not payslip:
        raise HTTPException(status_code=404, detail="Payslip not found")
    
    run = await db.payroll_runs.find_one({"id": payslip["payroll_run_id"]})
    if run["status"] != "Draft":
        raise HTTPException(status_code=400, detail="Can only edit deductions for Draft payroll")
    
    # Process advance deductions
    advances_total = 0
    advance_details = []
    for adv_ded in data.advances_to_deduct:
        adv_id = adv_ded.get("advance_id")
        adv_amount = adv_ded.get("amount", 0)
        if adv_id and adv_amount > 0:
            advance = await db.advances.find_one({"id": adv_id, "org_id": user["org_id"]})
            if advance and advance["status"] == "Open":
                actual = min(adv_amount, advance["remaining_amount"])
                advances_total += actual
                advance_details.append({"advance_id": adv_id, "amount": actual})
    
    net_pay = round(
        payslip["base_amount"] + payslip.get("overtime_amount", 0) 
        - data.deductions_amount - advances_total, 2
    )
    
    await db.payslips.update_one({"id": payslip_id}, {"$set": {
        "deductions_amount": data.deductions_amount,
        "advances_deducted_amount": advances_total,
        "advance_deductions": advance_details,
        "net_pay": net_pay,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }})
    
    return await db.payslips.find_one({"id": payslip_id}, {"_id": 0})

@api_router.post("/payslips/{payslip_id}/mark-paid")
async def mark_payslip_paid(payslip_id: str, data: MarkPaidRequest, user: dict = Depends(get_current_user)):
    if not payroll_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    payslip = await db.payslips.find_one({"id": payslip_id, "org_id": user["org_id"]})
    if not payslip:
        raise HTTPException(status_code=404, detail="Payslip not found")
    
    run = await db.payroll_runs.find_one({"id": payslip["payroll_run_id"]})
    if run["status"] == "Draft":
        raise HTTPException(status_code=400, detail="Finalize payroll before marking paid")
    if payslip["status"] == "Paid":
        raise HTTPException(status_code=400, detail="Already paid")
    
    now = datetime.now(timezone.utc).isoformat()
    
    # Apply advance deductions
    for adv_ded in payslip.get("advance_deductions", []):
        adv_id = adv_ded.get("advance_id")
        adv_amount = adv_ded.get("amount", 0)
        if adv_id and adv_amount > 0:
            advance = await db.advances.find_one({"id": adv_id})
            if advance and advance["status"] == "Open":
                new_remaining = max(0, round(advance["remaining_amount"] - adv_amount, 2))
                new_status = "Closed" if new_remaining <= 0 else "Open"
                await db.advances.update_one({"id": adv_id}, {"$set": {
                    "remaining_amount": new_remaining,
                    "status": new_status,
                    "updated_at": now,
                }})
    
    # Create payment record
    payment = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "payroll_run_id": payslip["payroll_run_id"],
        "payslip_id": payslip_id,
        "user_id": payslip["user_id"],
        "amount": payslip["net_pay"],
        "currency": payslip["currency"],
        "method": data.method,
        "reference": data.reference,
        "note": data.note,
        "paid_at": now,
        "paid_by_user_id": user["id"],
    }
    await db.payroll_payments.insert_one(payment)
    
    # Update payslip
    await db.payslips.update_one({"id": payslip_id}, {"$set": {
        "status": "Paid",
        "paid_at": now,
        "paid_by_user_id": user["id"],
        "updated_at": now,
    }})
    
    # Check if all payslips paid -> update run status
    unpaid = await db.payslips.count_documents({
        "payroll_run_id": payslip["payroll_run_id"],
        "status": {"$ne": "Paid"},
    })
    if unpaid == 0:
        await db.payroll_runs.update_one({"id": payslip["payroll_run_id"]}, {"$set": {
            "status": "Paid",
            "updated_at": now,
        }})
    
    await log_audit(user["org_id"], user["id"], user["email"], "payslip_paid", "payslip", payslip_id,
                    {"amount": payslip["net_pay"], "method": data.method})
    
    return await db.payslips.find_one({"id": payslip_id}, {"_id": 0})

@api_router.get("/payroll-enums")
async def get_payroll_enums():
    return {
        "pay_types": PAY_TYPES,
        "pay_schedules": PAY_SCHEDULES,
        "advance_types": ADVANCE_TYPES,
        "payroll_statuses": PAYROLL_STATUSES,
        "payment_methods": PAYMENT_METHODS,
    }

# ── M5 Finance Routes ─────────────────────────────────────────────

def finance_permission(user: dict):
    """Check if user has finance access"""
    return user["role"] in ["Admin", "Owner", "Accountant"]

def compute_invoice_line(line: dict) -> dict:
    """Compute line total"""
    qty = line.get("qty", 1) or 1
    unit_price = line.get("unit_price", 0) or 0
    line["line_total"] = round(qty * unit_price, 2)
    return line

def compute_invoice_totals(invoice: dict) -> dict:
    """Compute invoice subtotal, vat, total"""
    lines = invoice.get("lines", [])
    subtotal = sum(l.get("line_total", 0) for l in lines)
    vat_percent = invoice.get("vat_percent", 0) or 0
    vat_amount = round(subtotal * vat_percent / 100, 2)
    total = round(subtotal + vat_amount, 2)
    invoice["subtotal"] = round(subtotal, 2)
    invoice["vat_amount"] = vat_amount
    invoice["total"] = total
    return invoice

async def update_invoice_status(invoice_id: str, org_id: str):
    """Auto-update invoice status based on allocations and due date"""
    invoice = await db.invoices.find_one({"id": invoice_id, "org_id": org_id})
    if not invoice or invoice["status"] == "Cancelled":
        return
    
    # Calculate paid amount from allocations
    allocations = await db.payment_allocations.find({"invoice_id": invoice_id}).to_list(100)
    paid_amount = sum(a.get("amount_allocated", 0) for a in allocations)
    remaining = round(invoice["total"] - paid_amount, 2)
    
    # Determine status
    if remaining <= 0:
        new_status = "Paid"
    elif paid_amount > 0:
        new_status = "PartiallyPaid"
    elif invoice["status"] == "Sent" and invoice.get("due_date"):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if invoice["due_date"] < today:
            new_status = "Overdue"
        else:
            new_status = "Sent"
    else:
        new_status = invoice["status"]
    
    await db.invoices.update_one({"id": invoice_id}, {"$set": {
        "paid_amount": round(paid_amount, 2),
        "remaining_amount": max(0, remaining),
        "status": new_status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }})

# ── Financial Accounts ────────────────────────────────────────────

@api_router.get("/finance/accounts")
async def list_accounts(user: dict = Depends(get_current_user)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    accounts = await db.financial_accounts.find(
        {"org_id": user["org_id"]},
        {"_id": 0}
    ).sort("name", 1).to_list(100)
    
    # Calculate current balance for each account
    for acc in accounts:
        inflows = await db.finance_payments.aggregate([
            {"$match": {"org_id": user["org_id"], "account_id": acc["id"], "direction": "Inflow"}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
        ]).to_list(1)
        outflows = await db.finance_payments.aggregate([
            {"$match": {"org_id": user["org_id"], "account_id": acc["id"], "direction": "Outflow"}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
        ]).to_list(1)
        inflow_total = inflows[0]["total"] if inflows else 0
        outflow_total = outflows[0]["total"] if outflows else 0
        acc["current_balance"] = round(acc.get("opening_balance", 0) + inflow_total - outflow_total, 2)
    
    return accounts

@api_router.post("/finance/accounts", status_code=201)
async def create_account(data: FinancialAccountCreate, user: dict = Depends(get_current_user)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    now = datetime.now(timezone.utc).isoformat()
    account = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "name": data.name,
        "type": data.type,
        "currency": data.currency,
        "opening_balance": data.opening_balance,
        "active": data.active,
        "created_at": now,
        "updated_at": now,
    }
    await db.financial_accounts.insert_one(account)
    await log_audit(user["org_id"], user["id"], user["email"], "account_created", "account", account["id"],
                    {"name": data.name, "type": data.type})
    return {k: v for k, v in account.items() if k != "_id"}

@api_router.put("/finance/accounts/{account_id}")
async def update_account(account_id: str, data: FinancialAccountUpdate, user: dict = Depends(get_current_user)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    account = await db.financial_accounts.find_one({"id": account_id, "org_id": user["org_id"]})
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    await db.financial_accounts.update_one({"id": account_id}, {"$set": update})
    return await db.financial_accounts.find_one({"id": account_id}, {"_id": 0})

@api_router.delete("/finance/accounts/{account_id}")
async def delete_account(account_id: str, user: dict = Depends(get_current_user)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    # Check if any payments use this account
    payment_count = await db.finance_payments.count_documents({"account_id": account_id})
    if payment_count > 0:
        raise HTTPException(status_code=400, detail="Cannot delete account with existing payments")
    
    await db.financial_accounts.delete_one({"id": account_id, "org_id": user["org_id"]})
    return {"ok": True}

# ── Invoices ──────────────────────────────────────────────────────

async def get_next_invoice_no(org_id: str, direction: str) -> str:
    """Generate sequential invoice number"""
    prefix = "INV" if direction == "Issued" else "BILL"
    last = await db.invoices.find_one(
        {"org_id": org_id, "direction": direction},
        {"_id": 0, "invoice_no": 1},
        sort=[("created_at", -1)]
    )
    if last and last.get("invoice_no"):
        try:
            parts = last["invoice_no"].split("-")
            num = int(parts[-1]) + 1
        except:
            num = 1
    else:
        num = 1
    return f"{prefix}-{num:04d}"

@api_router.get("/finance/invoices")
async def list_invoices(
    user: dict = Depends(get_current_user),
    direction: Optional[str] = None,
    status: Optional[str] = None,
    project_id: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
):
    if not finance_permission(user):
        # SiteManager can see project-linked invoices only
        if user["role"] == "SiteManager":
            assigned = await get_user_project_ids(user["id"])
            if not assigned:
                return []
            project_id = project_id or {"$in": assigned}
        else:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    query = {"org_id": user["org_id"]}
    if direction:
        query["direction"] = direction
    if status:
        query["status"] = status
    if project_id:
        if isinstance(project_id, dict):
            query["project_id"] = project_id
        else:
            query["project_id"] = project_id
    if from_date:
        query["issue_date"] = {"$gte": from_date}
    if to_date:
        query.setdefault("issue_date", {})["$lte"] = to_date
    
    invoices = await db.invoices.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    
    # Check for overdue
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for inv in invoices:
        if inv["status"] in ["Sent", "PartiallyPaid"] and inv.get("due_date", "") < today:
            inv["is_overdue"] = True
        else:
            inv["is_overdue"] = False
        # Enrich with project code
        if inv.get("project_id"):
            p = await db.projects.find_one({"id": inv["project_id"]}, {"_id": 0, "code": 1, "name": 1})
            inv["project_code"] = p["code"] if p else ""
            inv["project_name"] = p["name"] if p else ""
    
    return invoices

@api_router.post("/finance/invoices", status_code=201)
async def create_invoice(data: InvoiceCreate, user: dict = Depends(get_current_user)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    # Check invoice_no uniqueness
    existing = await db.invoices.find_one({
        "org_id": user["org_id"],
        "direction": data.direction,
        "invoice_no": data.invoice_no,
    })
    if existing:
        raise HTTPException(status_code=400, detail="Invoice number already exists")
    
    now = datetime.now(timezone.utc).isoformat()
    
    # Process lines
    lines = []
    for i, line in enumerate(data.lines):
        l = {
            "id": str(uuid.uuid4()),
            "description": line.description,
            "unit": line.unit,
            "qty": line.qty,
            "unit_price": line.unit_price,
            "project_id": line.project_id,
            "cost_category": line.cost_category,
            "sort_order": i,
        }
        lines.append(compute_invoice_line(l))
    
    invoice = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "direction": data.direction,
        "invoice_no": data.invoice_no,
        "status": "Draft",
        "project_id": data.project_id,
        "counterparty_name": data.counterparty_name,
        "issue_date": data.issue_date,
        "due_date": data.due_date,
        "currency": data.currency,
        "vat_percent": data.vat_percent,
        "lines": lines,
        "notes": data.notes,
        "paid_amount": 0,
        "remaining_amount": 0,
        "created_at": now,
        "updated_at": now,
    }
    invoice = compute_invoice_totals(invoice)
    invoice["remaining_amount"] = invoice["total"]
    
    await db.invoices.insert_one(invoice)
    await log_audit(user["org_id"], user["id"], user["email"], "invoice_created", "invoice", invoice["id"],
                    {"invoice_no": data.invoice_no, "direction": data.direction})
    
    return {k: v for k, v in invoice.items() if k != "_id"}

@api_router.get("/finance/invoices/{invoice_id}")
async def get_invoice(invoice_id: str, user: dict = Depends(get_current_user)):
    invoice = await db.invoices.find_one({"id": invoice_id, "org_id": user["org_id"]}, {"_id": 0})
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    # Permission check
    if not finance_permission(user):
        if user["role"] == "SiteManager":
            assigned = await get_user_project_ids(user["id"])
            if invoice.get("project_id") not in assigned:
                raise HTTPException(status_code=403, detail="Access denied")
        else:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    # Enrich with project
    if invoice.get("project_id"):
        p = await db.projects.find_one({"id": invoice["project_id"]}, {"_id": 0, "code": 1, "name": 1})
        invoice["project_code"] = p["code"] if p else ""
        invoice["project_name"] = p["name"] if p else ""
    
    # Get allocations
    allocations = await db.payment_allocations.find(
        {"invoice_id": invoice_id},
        {"_id": 0}
    ).to_list(100)
    for alloc in allocations:
        payment = await db.finance_payments.find_one({"id": alloc["payment_id"]}, {"_id": 0, "date": 1, "reference": 1, "method": 1})
        if payment:
            alloc["payment_date"] = payment.get("date")
            alloc["payment_reference"] = payment.get("reference")
            alloc["payment_method"] = payment.get("method")
    invoice["allocations"] = allocations
    
    return invoice

@api_router.put("/finance/invoices/{invoice_id}")
async def update_invoice(invoice_id: str, data: InvoiceUpdate, user: dict = Depends(get_current_user)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    invoice = await db.invoices.find_one({"id": invoice_id, "org_id": user["org_id"]})
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice["status"] not in ["Draft"]:
        raise HTTPException(status_code=400, detail="Can only edit Draft invoices")
    
    # Check invoice_no uniqueness if changed
    if data.invoice_no and data.invoice_no != invoice["invoice_no"]:
        existing = await db.invoices.find_one({
            "org_id": user["org_id"],
            "direction": invoice["direction"],
            "invoice_no": data.invoice_no,
            "id": {"$ne": invoice_id},
        })
        if existing:
            raise HTTPException(status_code=400, detail="Invoice number already exists")
    
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    await db.invoices.update_one({"id": invoice_id}, {"$set": update})
    
    # Recompute if vat changed
    if "vat_percent" in update:
        updated = await db.invoices.find_one({"id": invoice_id})
        updated = compute_invoice_totals({k: v for k, v in updated.items() if k != "_id"})
        await db.invoices.update_one({"id": invoice_id}, {"$set": {
            "subtotal": updated["subtotal"],
            "vat_amount": updated["vat_amount"],
            "total": updated["total"],
            "remaining_amount": updated["total"],
        }})
    
    return await db.invoices.find_one({"id": invoice_id}, {"_id": 0})

@api_router.put("/finance/invoices/{invoice_id}/lines")
async def update_invoice_lines(invoice_id: str, data: InvoiceLinesUpdate, user: dict = Depends(get_current_user)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    invoice = await db.invoices.find_one({"id": invoice_id, "org_id": user["org_id"]})
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice["status"] not in ["Draft"]:
        raise HTTPException(status_code=400, detail="Can only edit Draft invoice lines")
    
    lines = []
    for i, line in enumerate(data.lines):
        l = {
            "id": str(uuid.uuid4()),
            "description": line.description,
            "unit": line.unit,
            "qty": line.qty,
            "unit_price": line.unit_price,
            "project_id": line.project_id,
            "cost_category": line.cost_category,
            "sort_order": i,
        }
        lines.append(compute_invoice_line(l))
    
    now = datetime.now(timezone.utc).isoformat()
    invoice["lines"] = lines
    invoice = compute_invoice_totals(invoice)
    
    await db.invoices.update_one({"id": invoice_id}, {"$set": {
        "lines": lines,
        "subtotal": invoice["subtotal"],
        "vat_amount": invoice["vat_amount"],
        "total": invoice["total"],
        "remaining_amount": invoice["total"] - invoice.get("paid_amount", 0),
        "updated_at": now,
    }})
    
    return await db.invoices.find_one({"id": invoice_id}, {"_id": 0})

@api_router.post("/finance/invoices/{invoice_id}/send")
async def send_invoice(invoice_id: str, user: dict = Depends(get_current_user)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    invoice = await db.invoices.find_one({"id": invoice_id, "org_id": user["org_id"]})
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice["status"] != "Draft":
        raise HTTPException(status_code=400, detail="Only Draft invoices can be sent")
    if len(invoice.get("lines", [])) == 0:
        raise HTTPException(status_code=400, detail="Invoice must have at least one line")
    
    now = datetime.now(timezone.utc).isoformat()
    
    # Check if already overdue
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    new_status = "Overdue" if invoice.get("due_date", "") < today else "Sent"
    
    await db.invoices.update_one({"id": invoice_id}, {"$set": {
        "status": new_status,
        "sent_at": now,
        "updated_at": now,
    }})
    
    await log_audit(user["org_id"], user["id"], user["email"], "invoice_sent", "invoice", invoice_id,
                    {"invoice_no": invoice["invoice_no"]})
    
    return await db.invoices.find_one({"id": invoice_id}, {"_id": 0})

@api_router.post("/finance/invoices/{invoice_id}/cancel")
async def cancel_invoice(invoice_id: str, user: dict = Depends(get_current_user)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    invoice = await db.invoices.find_one({"id": invoice_id, "org_id": user["org_id"]})
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice["status"] == "Paid":
        raise HTTPException(status_code=400, detail="Cannot cancel paid invoices")
    
    # Check for allocations
    alloc_count = await db.payment_allocations.count_documents({"invoice_id": invoice_id})
    if alloc_count > 0:
        raise HTTPException(status_code=400, detail="Cannot cancel invoice with payment allocations")
    
    now = datetime.now(timezone.utc).isoformat()
    await db.invoices.update_one({"id": invoice_id}, {"$set": {
        "status": "Cancelled",
        "updated_at": now,
    }})
    
    await log_audit(user["org_id"], user["id"], user["email"], "invoice_cancelled", "invoice", invoice_id,
                    {"invoice_no": invoice["invoice_no"]})
    
    return await db.invoices.find_one({"id": invoice_id}, {"_id": 0})

@api_router.delete("/finance/invoices/{invoice_id}")
async def delete_invoice(invoice_id: str, user: dict = Depends(get_current_user)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    invoice = await db.invoices.find_one({"id": invoice_id, "org_id": user["org_id"]})
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice["status"] != "Draft":
        raise HTTPException(status_code=400, detail="Can only delete Draft invoices")
    
    await db.invoices.delete_one({"id": invoice_id})
    return {"ok": True}

# ── Payments ──────────────────────────────────────────────────────

@api_router.get("/finance/payments")
async def list_payments(
    user: dict = Depends(get_current_user),
    account_id: Optional[str] = None,
    direction: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    query = {"org_id": user["org_id"]}
    if account_id:
        query["account_id"] = account_id
    if direction:
        query["direction"] = direction
    if from_date:
        query["date"] = {"$gte": from_date}
    if to_date:
        query.setdefault("date", {})["$lte"] = to_date
    
    payments = await db.finance_payments.find(query, {"_id": 0}).sort("date", -1).to_list(500)
    
    # Enrich with account name and allocation info
    for pay in payments:
        acc = await db.financial_accounts.find_one({"id": pay["account_id"]}, {"_id": 0, "name": 1, "type": 1})
        pay["account_name"] = acc["name"] if acc else "Unknown"
        pay["account_type"] = acc["type"] if acc else ""
        
        # Get allocations
        allocations = await db.payment_allocations.find({"payment_id": pay["id"]}, {"_id": 0}).to_list(100)
        allocated = sum(a.get("amount_allocated", 0) for a in allocations)
        pay["allocated_amount"] = round(allocated, 2)
        pay["unallocated_amount"] = round(pay["amount"] - allocated, 2)
        pay["allocation_count"] = len(allocations)
    
    return payments

@api_router.post("/finance/payments", status_code=201)
async def create_payment(data: PaymentCreate, user: dict = Depends(get_current_user)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    # Verify account exists
    account = await db.financial_accounts.find_one({"id": data.account_id, "org_id": user["org_id"]})
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    now = datetime.now(timezone.utc).isoformat()
    payment = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "direction": data.direction,
        "amount": data.amount,
        "currency": data.currency,
        "date": data.date,
        "method": data.method,
        "account_id": data.account_id,
        "counterparty_name": data.counterparty_name,
        "reference": data.reference,
        "note": data.note,
        "created_at": now,
        "updated_at": now,
    }
    await db.finance_payments.insert_one(payment)
    
    await log_audit(user["org_id"], user["id"], user["email"], "payment_created", "payment", payment["id"],
                    {"amount": data.amount, "direction": data.direction, "account_id": data.account_id})
    
    return {k: v for k, v in payment.items() if k != "_id"}

@api_router.get("/finance/payments/{payment_id}")
async def get_payment(payment_id: str, user: dict = Depends(get_current_user)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    payment = await db.finance_payments.find_one({"id": payment_id, "org_id": user["org_id"]}, {"_id": 0})
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    
    # Enrich
    acc = await db.financial_accounts.find_one({"id": payment["account_id"]}, {"_id": 0, "name": 1, "type": 1})
    payment["account_name"] = acc["name"] if acc else "Unknown"
    
    # Get allocations
    allocations = await db.payment_allocations.find({"payment_id": payment_id}, {"_id": 0}).to_list(100)
    for alloc in allocations:
        inv = await db.invoices.find_one({"id": alloc["invoice_id"]}, {"_id": 0, "invoice_no": 1, "direction": 1, "total": 1})
        if inv:
            alloc["invoice_no"] = inv["invoice_no"]
            alloc["invoice_direction"] = inv["direction"]
            alloc["invoice_total"] = inv["total"]
    payment["allocations"] = allocations
    
    allocated = sum(a.get("amount_allocated", 0) for a in allocations)
    payment["allocated_amount"] = round(allocated, 2)
    payment["unallocated_amount"] = round(payment["amount"] - allocated, 2)
    
    return payment

@api_router.post("/finance/payments/{payment_id}/allocate")
async def allocate_payment(payment_id: str, data: AllocatePaymentRequest, user: dict = Depends(get_current_user)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    payment = await db.finance_payments.find_one({"id": payment_id, "org_id": user["org_id"]})
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    
    # Get current allocations
    existing_allocs = await db.payment_allocations.find({"payment_id": payment_id}).to_list(100)
    current_allocated = sum(a.get("amount_allocated", 0) for a in existing_allocs)
    available = payment["amount"] - current_allocated
    
    now = datetime.now(timezone.utc).isoformat()
    results = []
    
    for alloc in data.allocations:
        if alloc.amount <= 0:
            continue
        
        # Check payment has enough available
        if alloc.amount > available:
            raise HTTPException(status_code=400, detail=f"Allocation exceeds available payment amount ({available})")
        
        # Check invoice exists and has remaining
        invoice = await db.invoices.find_one({"id": alloc.invoice_id, "org_id": user["org_id"]})
        if not invoice:
            raise HTTPException(status_code=404, detail=f"Invoice {alloc.invoice_id} not found")
        if invoice["status"] == "Cancelled":
            raise HTTPException(status_code=400, detail="Cannot allocate to cancelled invoice")
        
        remaining = invoice.get("remaining_amount", invoice["total"])
        if alloc.amount > remaining:
            raise HTTPException(status_code=400, detail=f"Allocation exceeds invoice remaining ({remaining})")
        
        # Check direction match
        expected_dir = "Inflow" if invoice["direction"] == "Issued" else "Outflow"
        if payment["direction"] != expected_dir:
            raise HTTPException(status_code=400, detail="Payment direction doesn't match invoice type")
        
        # Create allocation
        allocation = {
            "id": str(uuid.uuid4()),
            "org_id": user["org_id"],
            "payment_id": payment_id,
            "invoice_id": alloc.invoice_id,
            "amount_allocated": alloc.amount,
            "allocated_at": now,
        }
        await db.payment_allocations.insert_one(allocation)
        results.append({k: v for k, v in allocation.items() if k != "_id"})
        
        available -= alloc.amount
        
        # Update invoice status
        await update_invoice_status(alloc.invoice_id, user["org_id"])
    
    await log_audit(user["org_id"], user["id"], user["email"], "payment_allocated", "payment", payment_id,
                    {"allocations": len(results)})
    
    return {"ok": True, "allocations": results}

@api_router.delete("/finance/payments/{payment_id}")
async def delete_payment(payment_id: str, user: dict = Depends(get_current_user)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    payment = await db.finance_payments.find_one({"id": payment_id, "org_id": user["org_id"]})
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    
    # Check for allocations
    alloc_count = await db.payment_allocations.count_documents({"payment_id": payment_id})
    if alloc_count > 0:
        raise HTTPException(status_code=400, detail="Cannot delete payment with allocations")
    
    await db.finance_payments.delete_one({"id": payment_id})
    return {"ok": True}

# ── Finance Stats ─────────────────────────────────────────────────

@api_router.get("/finance/stats")
async def get_finance_stats(user: dict = Depends(get_current_user)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    org_id = user["org_id"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    # Receivables (Issued invoices not fully paid)
    receivables = await db.invoices.aggregate([
        {"$match": {"org_id": org_id, "direction": "Issued", "status": {"$nin": ["Draft", "Cancelled", "Paid"]}}},
        {"$group": {"_id": None, "total": {"$sum": "$remaining_amount"}, "count": {"$sum": 1}}}
    ]).to_list(1)
    
    # Overdue receivables
    overdue_recv = await db.invoices.aggregate([
        {"$match": {"org_id": org_id, "direction": "Issued", "status": {"$nin": ["Draft", "Cancelled", "Paid"]}, "due_date": {"$lt": today}}},
        {"$group": {"_id": None, "total": {"$sum": "$remaining_amount"}, "count": {"$sum": 1}}}
    ]).to_list(1)
    
    # Payables (Received invoices not fully paid)
    payables = await db.invoices.aggregate([
        {"$match": {"org_id": org_id, "direction": "Received", "status": {"$nin": ["Draft", "Cancelled", "Paid"]}}},
        {"$group": {"_id": None, "total": {"$sum": "$remaining_amount"}, "count": {"$sum": 1}}}
    ]).to_list(1)
    
    # Overdue payables
    overdue_pay = await db.invoices.aggregate([
        {"$match": {"org_id": org_id, "direction": "Received", "status": {"$nin": ["Draft", "Cancelled", "Paid"]}, "due_date": {"$lt": today}}},
        {"$group": {"_id": None, "total": {"$sum": "$remaining_amount"}, "count": {"$sum": 1}}}
    ]).to_list(1)
    
    # Account balances
    accounts = await db.financial_accounts.find({"org_id": org_id, "active": True}, {"_id": 0}).to_list(100)
    cash_balance = 0
    bank_balance = 0
    for acc in accounts:
        inflows = await db.finance_payments.aggregate([
            {"$match": {"org_id": org_id, "account_id": acc["id"], "direction": "Inflow"}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
        ]).to_list(1)
        outflows = await db.finance_payments.aggregate([
            {"$match": {"org_id": org_id, "account_id": acc["id"], "direction": "Outflow"}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
        ]).to_list(1)
        balance = acc.get("opening_balance", 0) + (inflows[0]["total"] if inflows else 0) - (outflows[0]["total"] if outflows else 0)
        if acc["type"] == "Cash":
            cash_balance += balance
        else:
            bank_balance += balance
    
    return {
        "receivables_total": round(receivables[0]["total"], 2) if receivables else 0,
        "receivables_count": receivables[0]["count"] if receivables else 0,
        "receivables_overdue": round(overdue_recv[0]["total"], 2) if overdue_recv else 0,
        "receivables_overdue_count": overdue_recv[0]["count"] if overdue_recv else 0,
        "payables_total": round(payables[0]["total"], 2) if payables else 0,
        "payables_count": payables[0]["count"] if payables else 0,
        "payables_overdue": round(overdue_pay[0]["total"], 2) if overdue_pay else 0,
        "payables_overdue_count": overdue_pay[0]["count"] if overdue_pay else 0,
        "cash_balance": round(cash_balance, 2),
        "bank_balance": round(bank_balance, 2),
    }

@api_router.get("/finance/enums")
async def get_finance_enums():
    return {
        "account_types": ACCOUNT_TYPES,
        "invoice_directions": INVOICE_DIRECTIONS,
        "invoice_statuses": INVOICE_STATUSES,
        "payment_directions": PAYMENT_DIRECTIONS,
        "cost_categories": COST_CATEGORIES,
    }

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

# ── M9 Overhead Cost System Routes ────────────────────────────────

def check_overhead_access(user: dict, write: bool = False):
    """Check if user has access to overhead cost system"""
    if user["role"] in ["Admin", "Owner", "Accountant"]:
        return True
    if user["role"] == "SiteManager" and not write:
        return True
    return False

# Overhead Categories
@api_router.get("/overhead/categories")
async def list_overhead_categories(user: dict = Depends(get_current_user)):
    if not check_overhead_access(user):
        raise HTTPException(status_code=403, detail="Access denied")
    cursor = db.overhead_categories.find({"org_id": user["org_id"]}, {"_id": 0})
    return await cursor.to_list(None)

@api_router.post("/overhead/categories")
async def create_overhead_category(data: OverheadCategoryCreate, user: dict = Depends(get_current_user)):
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "name": data.name,
        "active": data.active,
        "created_at": now,
        "updated_at": now,
    }
    await db.overhead_categories.insert_one(doc)
    await log_audit(user, "created", "overhead_category", doc["id"], {"name": data.name})
    return {k: v for k, v in doc.items() if k != "_id"}

@api_router.put("/overhead/categories/{cat_id}")
async def update_overhead_category(cat_id: str, data: OverheadCategoryUpdate, user: dict = Depends(get_current_user)):
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    existing = await db.overhead_categories.find_one({"id": cat_id, "org_id": user["org_id"]})
    if not existing:
        raise HTTPException(status_code=404, detail="Category not found")
    updates = {k: v for k, v in data.dict().items() if v is not None}
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.overhead_categories.update_one({"id": cat_id}, {"$set": updates})
    await log_audit(user, "updated", "overhead_category", cat_id, updates)
    doc = await db.overhead_categories.find_one({"id": cat_id}, {"_id": 0})
    return doc

@api_router.delete("/overhead/categories/{cat_id}")
async def delete_overhead_category(cat_id: str, user: dict = Depends(get_current_user)):
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    result = await db.overhead_categories.delete_one({"id": cat_id, "org_id": user["org_id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Category not found")
    await log_audit(user, "deleted", "overhead_category", cat_id, {})
    return {"deleted": True}

# Overhead Costs
@api_router.get("/overhead/costs")
async def list_overhead_costs(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    category_id: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    if not check_overhead_access(user):
        raise HTTPException(status_code=403, detail="Access denied")
    query = {"org_id": user["org_id"]}
    if date_from and date_to:
        query["date_incurred"] = {"$gte": date_from, "$lte": date_to}
    elif date_from:
        query["date_incurred"] = {"$gte": date_from}
    elif date_to:
        query["date_incurred"] = {"$lte": date_to}
    if category_id:
        query["category_id"] = category_id
    cursor = db.overhead_costs.find(query, {"_id": 0}).sort("date_incurred", -1)
    costs = await cursor.to_list(None)
    # Enrich with category name
    cat_ids = list(set(c.get("category_id") for c in costs if c.get("category_id")))
    cats = {}
    if cat_ids:
        cat_cursor = db.overhead_categories.find({"id": {"$in": cat_ids}}, {"_id": 0})
        cat_list = await cat_cursor.to_list(None)
        cats = {c["id"]: c["name"] for c in cat_list}
    for c in costs:
        c["category_name"] = cats.get(c.get("category_id"), "")
    return costs

@api_router.post("/overhead/costs")
async def create_overhead_cost(data: OverheadCostCreate, user: dict = Depends(get_current_user)):
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    if data.frequency not in OVERHEAD_FREQUENCIES:
        raise HTTPException(status_code=400, detail="Invalid frequency")
    if data.allocation_type not in OVERHEAD_ALLOCATION_TYPES:
        raise HTTPException(status_code=400, detail="Invalid allocation type")
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "category_id": data.category_id,
        "name": data.name,
        "amount": data.amount,
        "currency": data.currency,
        "vat_percent": data.vat_percent,
        "date_incurred": data.date_incurred,
        "frequency": data.frequency,
        "allocation_type": data.allocation_type,
        "note": data.note,
        "created_at": now,
        "updated_at": now,
    }
    await db.overhead_costs.insert_one(doc)
    await log_audit(user, "created", "overhead_cost", doc["id"], {"name": data.name, "amount": data.amount})
    return {k: v for k, v in doc.items() if k != "_id"}

@api_router.put("/overhead/costs/{cost_id}")
async def update_overhead_cost(cost_id: str, data: OverheadCostUpdate, user: dict = Depends(get_current_user)):
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    existing = await db.overhead_costs.find_one({"id": cost_id, "org_id": user["org_id"]})
    if not existing:
        raise HTTPException(status_code=404, detail="Cost not found")
    updates = {k: v for k, v in data.dict().items() if v is not None}
    if "frequency" in updates and updates["frequency"] not in OVERHEAD_FREQUENCIES:
        raise HTTPException(status_code=400, detail="Invalid frequency")
    if "allocation_type" in updates and updates["allocation_type"] not in OVERHEAD_ALLOCATION_TYPES:
        raise HTTPException(status_code=400, detail="Invalid allocation type")
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.overhead_costs.update_one({"id": cost_id}, {"$set": updates})
    await log_audit(user, "updated", "overhead_cost", cost_id, updates)
    doc = await db.overhead_costs.find_one({"id": cost_id}, {"_id": 0})
    return doc

@api_router.delete("/overhead/costs/{cost_id}")
async def delete_overhead_cost(cost_id: str, user: dict = Depends(get_current_user)):
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    result = await db.overhead_costs.delete_one({"id": cost_id, "org_id": user["org_id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Cost not found")
    await log_audit(user, "deleted", "overhead_cost", cost_id, {})
    return {"deleted": True}

# Overhead Assets
@api_router.get("/overhead/assets")
async def list_overhead_assets(active_only: bool = True, user: dict = Depends(get_current_user)):
    if not check_overhead_access(user):
        raise HTTPException(status_code=403, detail="Access denied")
    query = {"org_id": user["org_id"]}
    if active_only:
        query["active"] = True
    cursor = db.overhead_assets.find(query, {"_id": 0}).sort("purchase_date", -1)
    assets = await cursor.to_list(None)
    # Add computed daily amortization
    for asset in assets:
        life_days = asset.get("useful_life_months", 60) * 30.4375
        daily_amort = asset.get("purchase_cost", 0) / life_days if life_days > 0 else 0
        asset["daily_amortization"] = round(daily_amort, 4)
    return assets

@api_router.post("/overhead/assets")
async def create_overhead_asset(data: OverheadAssetCreate, user: dict = Depends(get_current_user)):
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "name": data.name,
        "purchase_cost": data.purchase_cost,
        "currency": data.currency,
        "purchase_date": data.purchase_date,
        "useful_life_months": data.useful_life_months,
        "assigned_to_user_id": data.assigned_to_user_id,
        "active": data.active,
        "note": data.note,
        "created_at": now,
        "updated_at": now,
    }
    await db.overhead_assets.insert_one(doc)
    await log_audit(user, "created", "overhead_asset", doc["id"], {"name": data.name, "purchase_cost": data.purchase_cost})
    # Add computed daily amortization
    result = {k: v for k, v in doc.items() if k != "_id"}
    life_days = data.useful_life_months * 30.4375
    result["daily_amortization"] = round(data.purchase_cost / life_days, 4) if life_days > 0 else 0
    return result

@api_router.put("/overhead/assets/{asset_id}")
async def update_overhead_asset(asset_id: str, data: OverheadAssetUpdate, user: dict = Depends(get_current_user)):
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    existing = await db.overhead_assets.find_one({"id": asset_id, "org_id": user["org_id"]})
    if not existing:
        raise HTTPException(status_code=404, detail="Asset not found")
    updates = {k: v for k, v in data.dict().items() if v is not None}
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.overhead_assets.update_one({"id": asset_id}, {"$set": updates})
    await log_audit(user, "updated", "overhead_asset", asset_id, updates)
    doc = await db.overhead_assets.find_one({"id": asset_id}, {"_id": 0})
    return doc

@api_router.delete("/overhead/assets/{asset_id}")
async def delete_overhead_asset(asset_id: str, user: dict = Depends(get_current_user)):
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    result = await db.overhead_assets.delete_one({"id": asset_id, "org_id": user["org_id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Asset not found")
    await log_audit(user, "deleted", "overhead_asset", asset_id, {})
    return {"deleted": True}

# Overhead Snapshots - Compute
@api_router.post("/overhead/snapshots/compute")
async def compute_overhead_snapshot(data: OverheadSnapshotCompute, user: dict = Depends(get_current_user)):
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    if data.method not in OVERHEAD_METHODS:
        raise HTTPException(status_code=400, detail="Invalid method")
    
    org_id = user["org_id"]
    period_start = data.period_start
    period_end = data.period_end
    
    # Calculate number of days in period
    from datetime import date
    d_start = date.fromisoformat(period_start)
    d_end = date.fromisoformat(period_end)
    num_days = (d_end - d_start).days + 1
    
    # 1. Sum overhead costs in period
    costs_cursor = db.overhead_costs.find({
        "org_id": org_id,
        "date_incurred": {"$gte": period_start, "$lte": period_end}
    }, {"_id": 0})
    costs = await costs_cursor.to_list(None)
    total_costs = sum(c.get("amount", 0) for c in costs)
    
    # 2. Calculate asset amortization for all active assets
    assets_cursor = db.overhead_assets.find({"org_id": org_id, "active": True}, {"_id": 0})
    assets = await assets_cursor.to_list(None)
    total_amortization = 0
    for asset in assets:
        life_days = asset.get("useful_life_months", 60) * 30.4375
        if life_days > 0:
            daily_amort = asset.get("purchase_cost", 0) / life_days
            total_amortization += daily_amort * num_days
    
    total_overhead = round(total_costs + total_amortization, 2)
    
    # 3. Count person-days (unique user+date with Present/Late)
    attendance_pipeline = [
        {"$match": {
            "org_id": org_id,
            "date": {"$gte": period_start, "$lte": period_end},
            "status": {"$in": ["Present", "Late"]}
        }},
        {"$group": {"_id": {"user_id": "$user_id", "date": "$date"}}},
        {"$count": "total"}
    ]
    att_result = await db.attendance_entries.aggregate(attendance_pipeline).to_list(None)
    total_person_days = att_result[0]["total"] if att_result else 0
    
    # 4. Sum work report hours (Submitted/Approved)
    hours_pipeline = [
        {"$match": {
            "org_id": org_id,
            "date": {"$gte": period_start, "$lte": period_end},
            "status": {"$in": ["Submitted", "Approved"]}
        }},
        {"$group": {"_id": None, "total_hours": {"$sum": "$total_hours"}}}
    ]
    hours_result = await db.work_reports.aggregate(hours_pipeline).to_list(None)
    total_hours = round(hours_result[0]["total_hours"], 2) if hours_result else 0
    
    # 5. Calculate rates
    rate_per_person_day = round(total_overhead / total_person_days, 2) if total_person_days > 0 else 0
    rate_per_hour = round(total_overhead / total_hours, 2) if total_hours > 0 else 0
    
    # 6. Create immutable snapshot
    now = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "period_start": period_start,
        "period_end": period_end,
        "method": data.method,
        "total_overhead": total_overhead,
        "total_costs": round(total_costs, 2),
        "total_amortization": round(total_amortization, 2),
        "total_person_days": total_person_days,
        "total_hours": total_hours,
        "overhead_rate_per_person_day": rate_per_person_day,
        "overhead_rate_per_hour": rate_per_hour,
        "computed_at": now,
        "computed_by_user_id": user["id"],
        "computed_by_name": user.get("name", user.get("email", "")),
        "notes": data.notes,
    }
    await db.overhead_snapshots.insert_one(snapshot)
    await log_audit(user, "computed", "overhead_snapshot", snapshot["id"], {
        "period": f"{period_start} - {period_end}",
        "total_overhead": total_overhead,
        "method": data.method
    })
    return {k: v for k, v in snapshot.items() if k != "_id"}

@api_router.get("/overhead/snapshots")
async def list_overhead_snapshots(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    if not check_overhead_access(user):
        raise HTTPException(status_code=403, detail="Access denied")
    query = {"org_id": user["org_id"]}
    if date_from and date_to:
        query["period_start"] = {"$gte": date_from}
        query["period_end"] = {"$lte": date_to}
    cursor = db.overhead_snapshots.find(query, {"_id": 0}).sort("computed_at", -1)
    return await cursor.to_list(None)

@api_router.get("/overhead/snapshots/{snapshot_id}")
async def get_overhead_snapshot(snapshot_id: str, user: dict = Depends(get_current_user)):
    if not check_overhead_access(user):
        raise HTTPException(status_code=403, detail="Access denied")
    snapshot = await db.overhead_snapshots.find_one({"id": snapshot_id, "org_id": user["org_id"]}, {"_id": 0})
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    # Get allocations
    allocs = await db.project_overhead_allocations.find(
        {"overhead_snapshot_id": snapshot_id}, {"_id": 0}
    ).to_list(None)
    snapshot["allocations"] = allocs
    return snapshot

# Overhead Allocation to Projects
@api_router.post("/overhead/snapshots/{snapshot_id}/allocate")
async def allocate_overhead_to_projects(snapshot_id: str, data: OverheadAllocateRequest, user: dict = Depends(get_current_user)):
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    
    snapshot = await db.overhead_snapshots.find_one({"id": snapshot_id, "org_id": user["org_id"]}, {"_id": 0})
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    
    org_id = user["org_id"]
    period_start = snapshot["period_start"]
    period_end = snapshot["period_end"]
    total_overhead = snapshot["total_overhead"]
    method = data.method
    
    # Delete existing allocations for this snapshot
    await db.project_overhead_allocations.delete_many({"overhead_snapshot_id": snapshot_id})
    
    allocations = []
    now = datetime.now(timezone.utc).isoformat()
    
    if method == "PersonDays":
        # Group attendance by project
        total_person_days = snapshot["total_person_days"]
        if total_person_days == 0:
            raise HTTPException(status_code=400, detail="No person-days to allocate")
        
        pipeline = [
            {"$match": {
                "org_id": org_id,
                "date": {"$gte": period_start, "$lte": period_end},
                "status": {"$in": ["Present", "Late"]},
                "project_id": {"$exists": True, "$ne": None}
            }},
            {"$group": {
                "_id": "$project_id",
                "person_days": {"$addToSet": {"user_id": "$user_id", "date": "$date"}}
            }},
            {"$project": {"project_id": "$_id", "count": {"$size": "$person_days"}}}
        ]
        result = await db.attendance_entries.aggregate(pipeline).to_list(None)
        
        # Get project names
        project_ids = [r["project_id"] for r in result]
        projects = {}
        if project_ids:
            proj_cursor = db.projects.find({"id": {"$in": project_ids}}, {"_id": 0, "id": 1, "code": 1, "name": 1})
            proj_list = await proj_cursor.to_list(None)
            projects = {p["id"]: p for p in proj_list}
        
        for r in result:
            proj_id = r["project_id"]
            proj_days = r["count"]
            allocated = round(total_overhead * (proj_days / total_person_days), 2)
            proj_info = projects.get(proj_id, {})
            alloc = {
                "id": str(uuid.uuid4()),
                "org_id": org_id,
                "overhead_snapshot_id": snapshot_id,
                "project_id": proj_id,
                "project_code": proj_info.get("code", ""),
                "project_name": proj_info.get("name", ""),
                "basis_person_days": proj_days,
                "basis_hours": 0,
                "allocated_amount": allocated,
                "created_at": now,
            }
            allocations.append(alloc)
    else:
        # Hours method
        total_hours = snapshot["total_hours"]
        if total_hours == 0:
            raise HTTPException(status_code=400, detail="No hours to allocate")
        
        pipeline = [
            {"$match": {
                "org_id": org_id,
                "date": {"$gte": period_start, "$lte": period_end},
                "status": {"$in": ["Submitted", "Approved"]}
            }},
            {"$group": {
                "_id": "$project_id",
                "total_hours": {"$sum": "$total_hours"}
            }}
        ]
        result = await db.work_reports.aggregate(pipeline).to_list(None)
        
        project_ids = [r["_id"] for r in result if r["_id"]]
        projects = {}
        if project_ids:
            proj_cursor = db.projects.find({"id": {"$in": project_ids}}, {"_id": 0, "id": 1, "code": 1, "name": 1})
            proj_list = await proj_cursor.to_list(None)
            projects = {p["id"]: p for p in proj_list}
        
        for r in result:
            proj_id = r["_id"]
            if not proj_id:
                continue
            proj_hours = r["total_hours"]
            allocated = round(total_overhead * (proj_hours / total_hours), 2)
            proj_info = projects.get(proj_id, {})
            alloc = {
                "id": str(uuid.uuid4()),
                "org_id": org_id,
                "overhead_snapshot_id": snapshot_id,
                "project_id": proj_id,
                "project_code": proj_info.get("code", ""),
                "project_name": proj_info.get("name", ""),
                "basis_person_days": 0,
                "basis_hours": round(proj_hours, 2),
                "allocated_amount": allocated,
                "created_at": now,
            }
            allocations.append(alloc)
    
    if allocations:
        await db.project_overhead_allocations.insert_many(allocations)
    
    await log_audit(user, "allocated", "overhead_snapshot", snapshot_id, {
        "method": method,
        "project_count": len(allocations),
        "total_allocated": sum(a["allocated_amount"] for a in allocations)
    })
    
    return {"allocations": [{k: v for k, v in a.items() if k != "_id"} for a in allocations]}

@api_router.get("/overhead/allocations")
async def list_overhead_allocations(
    snapshot_id: Optional[str] = None,
    project_id: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    if not check_overhead_access(user):
        raise HTTPException(status_code=403, detail="Access denied")
    query = {"org_id": user["org_id"]}
    if snapshot_id:
        query["overhead_snapshot_id"] = snapshot_id
    if project_id:
        query["project_id"] = project_id
    cursor = db.project_overhead_allocations.find(query, {"_id": 0})
    return await cursor.to_list(None)

@api_router.get("/overhead/enums")
async def get_overhead_enums(user: dict = Depends(get_current_user)):
    return {
        "frequencies": OVERHEAD_FREQUENCIES,
        "allocation_types": OVERHEAD_ALLOCATION_TYPES,
        "methods": OVERHEAD_METHODS
    }

# ── Billing & Subscription Routes ─────────────────────────────────────

# Configure Stripe
stripe.api_key = STRIPE_API_KEY
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "https://construction-pay-3.preview.emergentagent.com")

# Log Stripe configuration status at startup
logger.info(f"Stripe Mock Mode: {STRIPE_MOCK_MODE}")
if STRIPE_MOCK_MODE:
    logger.warning("STRIPE_MOCK_MODE is enabled. Real Stripe payments disabled.")
    logger.warning("Required env vars for real Stripe: STRIPE_API_KEY, STRIPE_PRICE_ID_PRO, STRIPE_PRICE_ID_ENTERPRISE, STRIPE_WEBHOOK_SECRET")

@api_router.get("/billing/plans")
async def list_billing_plans():
    """Public endpoint - list available plans"""
    return [
        {
            "id": plan_id,
            "name": plan["name"],
            "price": plan["price"],
            "allowed_modules": plan["allowed_modules"],
            "module_names": [MODULES[m]["name"] for m in plan["allowed_modules"] if m in MODULES],
            "limits": plan["limits"],
            "trial_days": plan.get("trial_days", 0),
            "description": plan.get("description", ""),
        }
        for plan_id, plan in SUBSCRIPTION_PLANS.items()
    ]

@api_router.get("/billing/config")
async def get_billing_config():
    """Get billing system configuration - used by frontend to show correct UI"""
    return {
        "stripe_mock_mode": STRIPE_MOCK_MODE,
        "stripe_configured": not STRIPE_MOCK_MODE,
        "required_env_vars": [
            {"name": "STRIPE_API_KEY", "configured": bool(os.environ.get("STRIPE_API_KEY")) and os.environ.get("STRIPE_API_KEY") != "sk_test_emergent"},
            {"name": "STRIPE_PRICE_ID_PRO", "configured": bool(os.environ.get("STRIPE_PRICE_ID_PRO"))},
            {"name": "STRIPE_PRICE_ID_ENTERPRISE", "configured": bool(os.environ.get("STRIPE_PRICE_ID_ENTERPRISE"))},
            {"name": "STRIPE_WEBHOOK_SECRET", "configured": bool(os.environ.get("STRIPE_WEBHOOK_SECRET"))},
        ]
    }

@api_router.post("/billing/signup")
async def signup_organization(data: OrgSignupRequest):
    """Public endpoint - create new organization with owner"""
    # Check if email already exists
    existing = await db.users.find_one({"email": data.owner_email.lower()})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    now = datetime.now(timezone.utc).isoformat()
    org_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    
    # Parse owner name into first_name and last_name
    name_parts = data.owner_name.strip().split(" ", 1)
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else ""
    
    # Create organization
    org = {
        "id": org_id,
        "name": data.org_name,
        "slug": data.org_name.lower().replace(" ", "-").replace("_", "-")[:50],
        "email": data.owner_email.lower(),
        "phone": "",
        "address": "",
        "logo_url": "",
        "vat_percent": 20.0,
        "attendance_start": "06:00",
        "attendance_end": "10:00",
        "work_report_deadline": "18:30",
        "max_reminders_per_day": 2,
        "escalation_after_days": 2,
        "org_timezone": "Europe/Sofia",
        "created_at": now,
        "updated_at": now,
    }
    await db.organizations.insert_one(org)
    
    # Create owner user - matching existing user schema
    user = {
        "id": user_id,
        "org_id": org_id,
        "email": data.owner_email.lower(),
        "password_hash": hash_password(data.password),
        "first_name": first_name,
        "last_name": last_name,
        "role": "Owner",
        "phone": "",
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    await db.users.insert_one(user)
    
    # Create subscription with free trial (14 days)
    trial_ends = datetime.now(timezone.utc) + timedelta(days=SUBSCRIPTION_PLANS["free"]["trial_days"])
    subscription = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "plan_id": "free",
        "status": "trialing",
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
        "current_period_start": now,
        "current_period_end": trial_ends.isoformat(),
        "trial_ends_at": trial_ends.isoformat(),
        "created_at": now,
        "updated_at": now,
    }
    await db.subscriptions.insert_one(subscription)
    
    # Create default feature flags based on free plan
    free_modules = SUBSCRIPTION_PLANS["free"]["allowed_modules"]
    for mod_code in MODULES.keys():
        flag = {
            "id": str(uuid.uuid4()),
            "org_id": org_id,
            "module_code": mod_code,
            "module_name": MODULES[mod_code]["name"],
            "description": MODULES[mod_code]["description"],
            "enabled": mod_code in free_modules,
            "updated_at": now,
            "updated_by": user_id,
        }
        await db.feature_flags.insert_one(flag)
    
    # Create token for auto-login
    token = create_token({"user_id": user_id, "org_id": org_id, "role": "Owner"})
    
    await log_audit(org_id, user_id, data.owner_email, "signup", "organization", org_id, {"name": data.org_name})
    
    return {
        "token": token,
        "user": {
            "id": user_id,
            "first_name": first_name,
            "last_name": last_name,
            "email": data.owner_email.lower(),
            "role": "Owner",
            "org_id": org_id,
        },
        "organization": {
            "id": org_id,
            "name": data.org_name,
        },
        "subscription": {
            "plan_id": "free",
            "status": "trialing",
            "trial_ends_at": trial_ends.isoformat(),
            "days_remaining": SUBSCRIPTION_PLANS["free"]["trial_days"],
        }
    }

@api_router.post("/billing/create-checkout-session")
async def create_checkout_session(data: CreateCheckoutRequest, user: dict = Depends(get_current_user)):
    """Create Stripe checkout session for plan upgrade"""
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin or Owner can manage billing")
    
    plan = SUBSCRIPTION_PLANS.get(data.plan_id)
    if not plan:
        raise HTTPException(status_code=400, detail="Invalid plan")
    
    if data.plan_id == "free":
        raise HTTPException(status_code=400, detail="Cannot checkout for free plan")
    
    org_id = user["org_id"]
    sub = await db.subscriptions.find_one({"org_id": org_id}, {"_id": 0})
    
    # MOCK MODE: Simulate successful checkout without real Stripe
    if STRIPE_MOCK_MODE:
        now = datetime.now(timezone.utc)
        mock_session_id = f"mock_cs_{str(uuid.uuid4())[:8]}"
        
        # Update subscription directly in mock mode
        period_end = now + timedelta(days=30)
        await db.subscriptions.update_one(
            {"org_id": org_id},
            {"$set": {
                "plan_id": data.plan_id,
                "status": "active",
                "stripe_customer_id": f"mock_cus_{org_id[:8]}",
                "stripe_subscription_id": f"mock_sub_{str(uuid.uuid4())[:8]}",
                "trial_ends_at": None,
                "current_period_start": now.isoformat(),
                "current_period_end": period_end.isoformat(),
                "updated_at": now.isoformat(),
            }}
        )
        
        # Update feature flags based on new plan
        allowed_modules = plan.get("allowed_modules", [])
        for mod_code in MODULES.keys():
            await db.feature_flags.update_one(
                {"org_id": org_id, "module_code": mod_code},
                {"$set": {"enabled": mod_code in allowed_modules}}
            )
        
        await log_audit(org_id, user["id"], user["email"], "checkout_mock", "billing", mock_session_id, {"plan_id": data.plan_id})
        
        return {
            "mock_mode": True,
            "checkout_url": f"{data.origin_url}/billing/success?session_id={mock_session_id}&mock=true",
            "session_id": mock_session_id,
            "message": "STRIPE_MOCK_MODE active. Subscription upgraded directly without payment.",
        }
    
    # REAL STRIPE MODE
    if not plan.get("stripe_price_id"):
        raise HTTPException(status_code=400, detail="This plan is not available for purchase (no Stripe price configured)")
    
    # Get or create Stripe customer
    customer_id = sub.get("stripe_customer_id") if sub else None
    if not customer_id:
        org = await db.organizations.find_one({"id": org_id}, {"_id": 0})
        try:
            customer = stripe.Customer.create(
                email=user["email"],
                name=org.get("name", ""),
                metadata={"org_id": org_id}
            )
            customer_id = customer.id
            await db.subscriptions.update_one(
                {"org_id": org_id},
                {"$set": {"stripe_customer_id": customer_id, "updated_at": datetime.now(timezone.utc).isoformat()}}
            )
        except stripe.error.StripeError as e:
            raise HTTPException(status_code=500, detail=f"Stripe error: {str(e)}")
    
    # Create checkout session
    success_url = f"{data.origin_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{data.origin_url}/billing/cancel"
    
    try:
        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[{
                "price": plan["stripe_price_id"],
                "quantity": 1,
            }],
            mode="subscription",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "org_id": org_id,
                "plan_id": data.plan_id,
            }
        )
        
        await log_audit(org_id, user["id"], user["email"], "checkout_started", "billing", session.id, {"plan_id": data.plan_id})
        
        return {"checkout_url": session.url, "session_id": session.id, "mock_mode": False}
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=500, detail=f"Stripe error: {str(e)}")

@api_router.post("/billing/create-portal-session")
async def create_portal_session(user: dict = Depends(get_current_user)):
    """Create Stripe customer portal session"""
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin or Owner can manage billing")
    
    sub = await db.subscriptions.find_one({"org_id": user["org_id"]}, {"_id": 0})
    
    # MOCK MODE
    if STRIPE_MOCK_MODE:
        return {
            "mock_mode": True,
            "portal_url": None,
            "message": "STRIPE_MOCK_MODE active. Customer portal not available. Manage subscription in app settings.",
        }
    
    if not sub or not sub.get("stripe_customer_id"):
        raise HTTPException(status_code=400, detail="No billing information found")
    
    try:
        session = stripe.billing_portal.Session.create(
            customer=sub["stripe_customer_id"],
            return_url=f"{APP_BASE_URL}/settings",
        )
        return {"portal_url": session.url, "mock_mode": False}
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=500, detail=f"Stripe error: {str(e)}")

@api_router.post("/billing/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events"""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    
    # Verify webhook signature in production
    if STRIPE_WEBHOOK_SECRET:
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid payload")
        except stripe.error.SignatureVerificationError:
            raise HTTPException(status_code=400, detail="Invalid signature")
    else:
        # Development mode - parse without verification
        import json
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON payload")
    
    event_type = event.get("type", "")
    data = event.get("data", {}).get("object", {})
    
    now = datetime.now(timezone.utc).isoformat()
    logger.info(f"Stripe webhook received: {event_type}")
    
    if event_type == "checkout.session.completed":
        org_id = data.get("metadata", {}).get("org_id")
        plan_id = data.get("metadata", {}).get("plan_id")
        customer_id = data.get("customer")
        subscription_id = data.get("subscription")
        
        if org_id and plan_id:
            plan = SUBSCRIPTION_PLANS.get(plan_id, {})
            await db.subscriptions.update_one(
                {"org_id": org_id},
                {"$set": {
                    "plan_id": plan_id,
                    "status": "active",
                    "stripe_customer_id": customer_id,
                    "stripe_subscription_id": subscription_id,
                    "trial_ends_at": None,
                    "updated_at": now,
                }}
            )
            # Update feature flags based on plan
            allowed_modules = plan.get("allowed_modules", [])
            for mod_code in MODULES.keys():
                await db.feature_flags.update_one(
                    {"org_id": org_id, "module_code": mod_code},
                    {"$set": {"enabled": mod_code in allowed_modules}}
                )
            logger.info(f"Subscription activated for org {org_id} with plan {plan_id}")
    
    elif event_type == "customer.subscription.updated":
        subscription_id = data.get("id")
        status = data.get("status")
        period_start = data.get("current_period_start")
        period_end = data.get("current_period_end")
        
        sub = await db.subscriptions.find_one({"stripe_subscription_id": subscription_id}, {"_id": 0})
        if sub:
            update_data = {"status": status, "updated_at": now}
            if period_start:
                update_data["current_period_start"] = datetime.fromtimestamp(period_start, tz=timezone.utc).isoformat()
            if period_end:
                update_data["current_period_end"] = datetime.fromtimestamp(period_end, tz=timezone.utc).isoformat()
            
            await db.subscriptions.update_one({"stripe_subscription_id": subscription_id}, {"$set": update_data})
            logger.info(f"Subscription {subscription_id} updated to status {status}")
    
    elif event_type == "customer.subscription.deleted":
        subscription_id = data.get("id")
        sub = await db.subscriptions.find_one({"stripe_subscription_id": subscription_id}, {"_id": 0})
        if sub:
            # Downgrade to free plan
            free_modules = SUBSCRIPTION_PLANS["free"]["allowed_modules"]
            await db.subscriptions.update_one(
                {"stripe_subscription_id": subscription_id},
                {"$set": {
                    "plan_id": "free",
                    "status": "canceled",
                    "stripe_subscription_id": None,
                    "updated_at": now,
                }}
            )
            for mod_code in MODULES.keys():
                await db.feature_flags.update_one(
                    {"org_id": sub["org_id"], "module_code": mod_code},
                    {"$set": {"enabled": mod_code in free_modules}}
                )
            logger.info(f"Subscription {subscription_id} canceled, downgraded to free")
    
    elif event_type == "invoice.payment_succeeded":
        subscription_id = data.get("subscription")
        if subscription_id:
            sub = await db.subscriptions.find_one({"stripe_subscription_id": subscription_id}, {"_id": 0})
            if sub and sub.get("status") == "past_due":
                await db.subscriptions.update_one(
                    {"stripe_subscription_id": subscription_id},
                    {"$set": {"status": "active", "updated_at": now}}
                )
                logger.info(f"Payment succeeded, subscription {subscription_id} reactivated")
    
    elif event_type == "invoice.payment_failed":
        subscription_id = data.get("subscription")
        if subscription_id:
            sub = await db.subscriptions.find_one({"stripe_subscription_id": subscription_id}, {"_id": 0})
            if sub:
                await db.subscriptions.update_one(
                    {"stripe_subscription_id": subscription_id},
                    {"$set": {"status": "past_due", "updated_at": now}}
                )
                logger.info(f"Payment failed, subscription {subscription_id} marked as past_due")
    
    return {"status": "received"}

@api_router.get("/billing/subscription")
async def get_billing_subscription(user: dict = Depends(get_current_user)):
    """Get current subscription details with plan info and trial status"""
    sub = await db.subscriptions.find_one({"org_id": user["org_id"]}, {"_id": 0})
    if not sub:
        return None
    
    plan = SUBSCRIPTION_PLANS.get(sub.get("plan_id", "free"), SUBSCRIPTION_PLANS["free"])
    now = datetime.now(timezone.utc)
    
    # Calculate trial status
    trial_ends_at = sub.get("trial_ends_at")
    is_trial_active = False
    trial_days_remaining = 0
    trial_expired = False
    
    if trial_ends_at and sub.get("status") == "trialing":
        trial_end_dt = datetime.fromisoformat(trial_ends_at.replace("Z", "+00:00"))
        if now < trial_end_dt:
            is_trial_active = True
            trial_days_remaining = (trial_end_dt - now).days
        else:
            trial_expired = True
            # Auto-update status to past_due if trial expired
            await db.subscriptions.update_one(
                {"org_id": user["org_id"]},
                {"$set": {"status": "past_due", "updated_at": now.isoformat()}}
            )
            sub["status"] = "past_due"
    
    return {
        **sub,
        "plan": {
            "id": sub.get("plan_id", "free"),
            "name": plan["name"],
            "price": plan["price"],
            "allowed_modules": plan["allowed_modules"],
            "limits": plan["limits"],
            "description": plan.get("description", ""),
        },
        "trial_active": is_trial_active,
        "trial_days_remaining": trial_days_remaining,
        "trial_expired": trial_expired,
        "stripe_mock_mode": STRIPE_MOCK_MODE,
    }

@api_router.get("/billing/check-module/{module_code}")
async def check_module_access(module_code: str, user: dict = Depends(get_current_user)):
    """Check if current subscription allows access to a module - SERVER-SIDE ENFORCEMENT"""
    sub = await db.subscriptions.find_one({"org_id": user["org_id"]}, {"_id": 0})
    if not sub:
        return {"allowed": False, "reason": "No subscription"}
    
    plan = SUBSCRIPTION_PLANS.get(sub.get("plan_id", "free"), SUBSCRIPTION_PLANS["free"])
    
    # Check trial expiration
    status = sub.get("status", "")
    trial_ends_at = sub.get("trial_ends_at")
    
    if status == "trialing" and trial_ends_at:
        now = datetime.now(timezone.utc)
        trial_end_dt = datetime.fromisoformat(trial_ends_at.replace("Z", "+00:00"))
        if now >= trial_end_dt:
            # Trial expired - update status and restrict to free modules
            await db.subscriptions.update_one(
                {"org_id": user["org_id"]},
                {"$set": {"status": "past_due", "updated_at": now.isoformat()}}
            )
            status = "past_due"
    
    # Check if subscription is active or trialing
    if status in ["canceled", "past_due", "incomplete"]:
        # Allow core read-only access for past_due (keeping minimal functionality)
        if module_code == "M0":
            return {"allowed": True, "reason": None, "limited": True}
        return {"allowed": False, "reason": f"Subscription {status}. Please upgrade your plan."}
    
    allowed = module_code in plan["allowed_modules"]
    return {"allowed": allowed, "reason": None if allowed else "Module not in your current plan. Please upgrade."}

# ── Misc Routes ──────────────────────────────────────────────────

@api_router.get("/roles")
async def list_roles():
    return ROLES

@api_router.get("/subscription")
async def get_subscription(user: dict = Depends(get_current_user)):
    sub = await db.subscriptions.find_one({"org_id": user["org_id"]}, {"_id": 0})
    if sub:
        plan = SUBSCRIPTION_PLANS.get(sub.get("plan_id", "free"), SUBSCRIPTION_PLANS["free"])
        sub["plan_name"] = plan["name"]
        sub["plan_price"] = plan["price"]
        sub["allowed_modules"] = plan["allowed_modules"]
        sub["limits"] = plan["limits"]
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
    await db.reminder_logs.create_index([("org_id", 1), ("type", 1), ("date", 1), ("user_id", 1)])
    await db.notifications.create_index([("org_id", 1), ("user_id", 1), ("created_at", -1)])
    await db.notifications.create_index([("org_id", 1), ("user_id", 1), ("is_read", 1)])
    # M2 Estimates indexes
    await db.offers.create_index([("org_id", 1), ("offer_no", 1)])
    await db.offers.create_index([("org_id", 1), ("project_id", 1)])
    await db.offers.create_index([("org_id", 1), ("status", 1)])
    await db.activity_catalog.create_index([("org_id", 1), ("project_id", 1)])
    await db.activity_catalog.create_index([("org_id", 1), ("project_id", 1), ("active", 1)])
    # M4 Payroll indexes
    await db.employee_profiles.create_index([("org_id", 1), ("user_id", 1)], unique=True)
    await db.advances.create_index([("org_id", 1), ("user_id", 1)])
    await db.advances.create_index([("org_id", 1), ("status", 1)])
    await db.payroll_runs.create_index([("org_id", 1), ("status", 1)])
    await db.payslips.create_index([("org_id", 1), ("payroll_run_id", 1)])
    await db.payslips.create_index([("org_id", 1), ("user_id", 1)])
    await db.payroll_payments.create_index([("org_id", 1), ("payroll_run_id", 1)])
    # M9 Overhead indexes
    await db.overhead_categories.create_index([("org_id", 1)])
    await db.overhead_costs.create_index([("org_id", 1), ("date_incurred", -1)])
    await db.overhead_costs.create_index([("org_id", 1), ("category_id", 1)])
    await db.overhead_assets.create_index([("org_id", 1), ("active", 1)])
    await db.overhead_snapshots.create_index([("org_id", 1), ("computed_at", -1)])
    await db.overhead_snapshots.create_index([("org_id", 1), ("period_start", 1), ("period_end", 1)])
    await db.project_overhead_allocations.create_index([("org_id", 1), ("overhead_snapshot_id", 1)])
    await db.project_overhead_allocations.create_index([("org_id", 1), ("project_id", 1)])
    # Billing indexes
    await db.subscriptions.create_index([("org_id", 1)], unique=True)
    await db.subscriptions.create_index([("stripe_subscription_id", 1)])
    await db.subscriptions.create_index([("stripe_customer_id", 1)])

    # Start background reminder scheduler
    async def reminder_loop():
        while True:
            await asyncio.sleep(900)  # 15 minutes
            try:
                await run_reminder_jobs()
                logger.info("Reminder jobs completed")
            except Exception as e:
                logger.error(f"Reminder job error: {e}")
    asyncio.create_task(reminder_loop())

@app.on_event("shutdown")
async def shutdown():
    client.close()
