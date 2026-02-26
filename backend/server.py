from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
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

# ── Helper Functions ────────────────────────────────
def today_str():
    """Return today's date as YYYY-MM-DD string in UTC."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

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

# ── Mobile Integration Models ────────────────────────────────────

# Available mobile modules
MOBILE_MODULES = [
    "attendance",      # Clock in/out, view attendance
    "workReports",     # Create/view daily work reports
    "deliveries",      # Delivery tracking (for drivers)
    "machines",        # Machine assignments and usage
    "messages",        # In-app messaging
    "media",           # Photo uploads
    "profile",         # User profile view
]

# Available actions per mobile module
MOBILE_ACTIONS = {
    "attendance": ["view", "clockIn", "clockOut", "viewHistory"],
    "workReports": ["view", "create", "edit", "submit", "addNote", "uploadPhoto"],
    "deliveries": ["view", "create", "updateStatus", "addNote", "uploadPhoto", "viewHistory"],
    "machines": ["view", "assignSelf", "releaseSelf", "reportIssue", "uploadPhoto"],
    "messages": ["view", "send", "viewHistory"],
    "media": ["view", "upload", "delete"],
    "profile": ["view", "edit"],
}

# Available fields per mobile module (for list and detail views)
MOBILE_FIELDS = {
    "attendance": {
        "list": ["date", "user_name", "status", "clock_in", "clock_out", "project_name"],
        "detail": ["date", "user_name", "user_id", "status", "clock_in", "clock_out", "project_id", "project_name", "location", "notes", "photo_url"],
    },
    "workReports": {
        "list": ["date", "user_name", "project_name", "status", "hours_total"],
        "detail": ["id", "date", "user_id", "user_name", "project_id", "project_name", "status", "lines", "notes", "photo_urls", "submitted_at", "approved_at", "approved_by"],
    },
    "deliveries": {
        "list": ["id", "date", "destination", "status", "items_count"],
        "detail": ["id", "date", "origin", "destination", "status", "driver_id", "driver_name", "vehicle", "items", "notes", "photo_urls", "started_at", "completed_at"],
    },
    "machines": {
        "list": ["id", "name", "type", "status", "assigned_to_name", "project_name"],
        "detail": ["id", "name", "type", "status", "serial_number", "assigned_to_id", "assigned_to_name", "project_id", "project_name", "location", "notes", "last_maintenance", "photo_url"],
    },
    "messages": {
        "list": ["id", "from_user_name", "preview", "created_at", "is_read"],
        "detail": ["id", "from_user_id", "from_user_name", "to_user_id", "to_user_name", "content", "created_at", "is_read"],
    },
    "media": {
        "list": ["id", "filename", "context_type", "created_at", "thumbnail_url"],
        "detail": ["id", "filename", "url", "context_type", "context_id", "owner_user_id", "owner_user_name", "created_at", "file_size"],
    },
    "profile": {
        "list": [],
        "detail": ["id", "first_name", "last_name", "email", "phone", "role", "photo_url"],
    },
}

# Default mobile configurations per role
DEFAULT_MOBILE_CONFIGS = {
    "Technician": {
        "enabledModules": ["attendance", "workReports", "machines", "messages", "media", "profile"],
        "configs": {
            "attendance": {
                "listFields": ["date", "status", "clock_in", "clock_out"],
                "detailFields": ["date", "status", "clock_in", "clock_out", "project_name", "notes"],
                "allowedActions": ["view", "clockIn", "clockOut", "viewHistory"],
                "defaultFilters": {"assignedToMe": True},
            },
            "workReports": {
                "listFields": ["date", "project_name", "status", "hours_total"],
                "detailFields": ["date", "project_name", "status", "lines", "notes", "photo_urls"],
                "allowedActions": ["view", "create", "edit", "submit", "addNote", "uploadPhoto"],
                "defaultFilters": {"assignedToMe": True},
            },
            "machines": {
                "listFields": ["name", "type", "status", "assigned_to_name"],
                "detailFields": ["name", "type", "status", "serial_number", "assigned_to_name", "project_name", "notes"],
                "allowedActions": ["view", "assignSelf", "releaseSelf", "reportIssue"],
                "defaultFilters": {"assignedToMe": True},
            },
            "messages": {
                "listFields": ["from_user_name", "preview", "created_at", "is_read"],
                "detailFields": ["from_user_name", "content", "created_at"],
                "allowedActions": ["view", "send"],
                "defaultFilters": {},
            },
            "media": {
                "listFields": ["filename", "context_type", "created_at"],
                "detailFields": ["filename", "url", "context_type", "created_at"],
                "allowedActions": ["view", "upload"],
                "defaultFilters": {"ownOnly": True},
            },
            "profile": {
                "listFields": [],
                "detailFields": ["first_name", "last_name", "email", "phone", "role"],
                "allowedActions": ["view"],
                "defaultFilters": {},
            },
        },
    },
    "Driver": {
        "enabledModules": ["deliveries", "machines", "messages", "media", "profile"],
        "configs": {
            "deliveries": {
                "listFields": ["date", "destination", "status", "items_count"],
                "detailFields": ["date", "origin", "destination", "status", "vehicle", "items", "notes", "photo_urls"],
                "allowedActions": ["view", "updateStatus", "addNote", "uploadPhoto"],
                "defaultFilters": {"assignedToMe": True},
            },
            "machines": {
                "listFields": ["name", "type", "status"],
                "detailFields": ["name", "type", "status", "serial_number", "notes"],
                "allowedActions": ["view", "reportIssue"],
                "defaultFilters": {"vehiclesOnly": True},
            },
            "messages": {
                "listFields": ["from_user_name", "preview", "created_at", "is_read"],
                "detailFields": ["from_user_name", "content", "created_at"],
                "allowedActions": ["view", "send"],
                "defaultFilters": {},
            },
            "media": {
                "listFields": ["filename", "context_type", "created_at"],
                "detailFields": ["filename", "url", "context_type", "created_at"],
                "allowedActions": ["view", "upload"],
                "defaultFilters": {"ownOnly": True},
            },
            "profile": {
                "listFields": [],
                "detailFields": ["first_name", "last_name", "email", "phone", "role"],
                "allowedActions": ["view"],
                "defaultFilters": {},
            },
        },
    },
    "SiteManager": {
        "enabledModules": ["attendance", "workReports", "deliveries", "machines", "messages", "media", "profile"],
        "configs": {
            "attendance": {
                "listFields": ["date", "user_name", "status", "clock_in", "clock_out", "project_name"],
                "detailFields": ["date", "user_name", "status", "clock_in", "clock_out", "project_name", "notes"],
                "allowedActions": ["view", "viewHistory"],
                "defaultFilters": {"projectScoped": True},
            },
            "workReports": {
                "listFields": ["date", "user_name", "project_name", "status", "hours_total"],
                "detailFields": ["date", "user_name", "project_name", "status", "lines", "notes", "photo_urls", "submitted_at"],
                "allowedActions": ["view", "viewHistory"],
                "defaultFilters": {"projectScoped": True},
            },
            "deliveries": {
                "listFields": ["date", "destination", "status", "driver_name"],
                "detailFields": ["date", "origin", "destination", "status", "driver_name", "vehicle", "items", "notes"],
                "allowedActions": ["view"],
                "defaultFilters": {"projectScoped": True},
            },
            "machines": {
                "listFields": ["name", "type", "status", "assigned_to_name", "project_name"],
                "detailFields": ["name", "type", "status", "serial_number", "assigned_to_name", "project_name", "location", "notes"],
                "allowedActions": ["view"],
                "defaultFilters": {"projectScoped": True},
            },
            "messages": {
                "listFields": ["from_user_name", "preview", "created_at", "is_read"],
                "detailFields": ["from_user_name", "content", "created_at"],
                "allowedActions": ["view", "send"],
                "defaultFilters": {},
            },
            "media": {
                "listFields": ["filename", "context_type", "created_at"],
                "detailFields": ["filename", "url", "context_type", "created_at"],
                "allowedActions": ["view", "upload"],
                "defaultFilters": {},
            },
            "profile": {
                "listFields": [],
                "detailFields": ["first_name", "last_name", "email", "phone", "role"],
                "allowedActions": ["view", "edit"],
                "defaultFilters": {},
            },
        },
    },
}

class MobileSettingsUpdate(BaseModel):
    enabled_modules: List[str]

class MobileViewConfigUpdate(BaseModel):
    role: str
    module_code: str
    list_fields: List[str]
    detail_fields: List[str]
    allowed_actions: List[str]
    default_filters: dict = {}

class MediaUploadContext(BaseModel):
    context_type: str  # e.g., "workReport", "delivery", "machine", "attendance"
    context_id: str

class MediaLinkRequest(BaseModel):
    context_type: str
    context_id: str
    media_id: str

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
    """
    Production-safe seed function.
    
    Only creates initial admin user if BOTH environment variables are set:
    - SEED_ADMIN_EMAIL
    - SEED_ADMIN_PASSWORD
    
    This prevents predictable default credentials (admin123) in production.
    For dev/test, set these env vars or use pytest fixtures.
    """
    # Check for explicit seed configuration
    seed_email = os.environ.get("SEED_ADMIN_EMAIL", "").strip()
    seed_password = os.environ.get("SEED_ADMIN_PASSWORD", "").strip()
    
    # Production safety: require explicit credentials
    if not seed_email or not seed_password:
        logger.warning(
            "Seed skipped: missing SEED_ADMIN_EMAIL/SEED_ADMIN_PASSWORD. "
            "Set both env vars to create initial admin user."
        )
        return
    
    # Idempotent check: skip if admin already exists
    existing = await db.users.find_one({"email": seed_email})
    if existing:
        logger.info(f"Seed data already exists for {seed_email}, skipping")
        return
    
    logger.info(f"Creating seed data with admin: {seed_email}")

    org_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    expires = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()

    await db.organizations.insert_one({
        "id": org_id,
        "name": "BEG_Work Production",
        "slug": "begwork-prod",
        "address": "",
        "phone": "",
        "email": seed_email,
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
        "email": seed_email,
        "password_hash": hash_password(seed_password),
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
        "plan_id": "enterprise",
        "status": "active",
        "started_at": now,
        "expires_at": expires,
        "payment_method": "seed",
        "amount": 0,
        "currency": "EUR",
        "created_at": now,
    })

    logger.info(f"Seed data created successfully for: {seed_email}")

# ── Auth Routes ──────────────────────────────────────────────────

# Import health router - includes health, debug routes
from app.routes.health import router as health_router
api_router.include_router(health_router)

# Import auth router - includes auth, org, users, feature-flags, audit-logs
from app.routes.auth import router as auth_router
api_router.include_router(auth_router)

# Import projects router - includes projects, team, phases, enums
from app.routes.projects import router as projects_router
api_router.include_router(projects_router)

# Import attendance router - includes attendance, work-reports, reminders, notifications
from app.routes.attendance import router as attendance_router
api_router.include_router(attendance_router)

# Import offers router - includes offers, activity-catalog, offer-enums
from app.routes.offers import router as offers_router
api_router.include_router(offers_router)

# Import HR/payroll router - includes employees, advances, payroll-runs, payslips, payroll-enums
from app.routes.hr import router as hr_router
api_router.include_router(hr_router)

# Import finance router - includes accounts, invoices, payments, finance stats/enums
from app.routes.finance import router as finance_router
api_router.include_router(finance_router)

# Import overhead router - includes dashboard/stats, overhead categories/costs/assets/snapshots/allocations
from app.routes.overhead import router as overhead_router
api_router.include_router(overhead_router)

# Import billing router - includes plans, config, signup, checkout, webhook, subscription, usage
from app.routes.billing import router as billing_router
api_router.include_router(billing_router)

# Import mobile router - includes bootstrap, settings, view-configs
from app.routes.mobile import router as mobile_router
api_router.include_router(mobile_router)

# Import media router - includes upload, link, file serving
from app.routes.media import router as media_router
api_router.include_router(media_router)

# Import warehouse router
from app.routes.warehouses import router as warehouses_router
api_router.include_router(warehouses_router)

# Import scan docs router
from app.routes.scan_docs import router as scan_docs_router
api_router.include_router(scan_docs_router)

# Import invoice lines router (separate collection)
from app.routes.invoice_lines import router as invoice_lines_router
api_router.include_router(invoice_lines_router)

# Import counterparties router (suppliers/clients)
from app.routes.counterparties import router as counterparties_router
api_router.include_router(counterparties_router)

# Import items router (materials/inventory items)
from app.routes.items import router as items_router
api_router.include_router(items_router)

# Import reports router (prices, turnover)
from app.routes.reports import router as reports_router
api_router.include_router(reports_router)

# Clients router
from app.routes.clients import router as clients_router
api_router.include_router(clients_router)

# Dashboard routes (activity, finance details)
from app.routes.dashboard import router as dashboard_extra_router
api_router.include_router(dashboard_extra_router)

# Import platform bootstrap router - ONE-TIME USE for production setup
from app.routes.platform import router as platform_router
app.include_router(platform_router)  # Direct to app (not under /api prefix)

# Import work logs router (Дневник + Промени СМР)
from app.routes.work_logs import router as work_logs_router
api_router.include_router(work_logs_router)

# ── App Setup ────────────────────────────────────────────────────
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
    # Mobile integration indexes
    await db.org_mobile_settings.create_index([("org_id", 1)], unique=True)
    await db.mobile_view_configs.create_index([("org_id", 1), ("role", 1), ("module_code", 1)], unique=True)
    await db.media_files.create_index([("org_id", 1), ("owner_user_id", 1)])
    await db.media_files.create_index([("org_id", 1), ("context_type", 1), ("context_id", 1)])
    
    # Warehouses indexes
    await db.warehouses.create_index([("org_id", 1), ("code", 1)], unique=True)
    await db.warehouses.create_index([("org_id", 1), ("type", 1)])
    await db.warehouses.create_index([("org_id", 1), ("project_id", 1)])
    await db.warehouses.create_index([("org_id", 1), ("active", 1)])
    
    # Scan docs indexes
    await db.scan_docs.create_index([("org_id", 1), ("linked_invoice_id", 1)])
    await db.scan_docs.create_index([("org_id", 1), ("uploaded_by_user_id", 1)])
    await db.scan_docs.create_index([("org_id", 1), ("created_at", -1)])
    
    # Invoice lines indexes (separate collection)
    await db.invoice_lines.create_index([("org_id", 1), ("invoice_id", 1)])
    await db.invoice_lines.create_index([("org_id", 1), ("allocation_type", 1), ("allocation_ref_id", 1)])
    await db.invoice_lines.create_index([("org_id", 1), ("purchased_by_user_id", 1)])
    await db.invoice_lines.create_index([("invoice_id", 1), ("line_no", 1)], unique=True)
    
    # Counterparties indexes
    await db.counterparties.create_index([("org_id", 1), ("name", 1)])
    await db.counterparties.create_index([("org_id", 1), ("eik", 1)], sparse=True)  # Non-unique - check manually in code
    await db.counterparties.create_index([("org_id", 1), ("type", 1)])
    await db.counterparties.create_index([("org_id", 1), ("active", 1)])
    
    # Items indexes
    await db.items.create_index([("org_id", 1), ("sku", 1)], unique=True)
    await db.items.create_index([("org_id", 1), ("name", 1)])
    await db.items.create_index([("org_id", 1), ("category", 1)])
    await db.items.create_index([("org_id", 1), ("is_active", 1)])
    
    # Cash transactions indexes
    await db.cash_transactions.create_index([("org_id", 1), ("date", -1)])
    await db.cash_transactions.create_index([("org_id", 1), ("type", 1)])
    
    # Overhead transactions indexes
    await db.overhead_transactions.create_index([("org_id", 1), ("date", -1)])
    
    # Bonus payments indexes
    await db.bonus_payments.create_index([("org_id", 1), ("date", -1)])
    
    # Clients indexes
    await db.clients.create_index([("org_id", 1), ("phone_normalized", 1)], unique=True)
    await db.clients.create_index([("org_id", 1), ("last_name", 1)])
    await db.clients.create_index([("org_id", 1), ("is_active", 1)])
    await db.bonus_payments.create_index([("org_id", 1), ("user_id", 1)])
    
    # Payroll payments indexes (if not already exists)
    await db.payroll_payments.create_index([("org_id", 1), ("payment_date", -1)])

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
