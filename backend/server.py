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

# ── Billing & Subscription Routes ─────────────────────────────────────

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

# project-enums is now in app/routes/projects.py

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
APP_BASE_URL = os.environ.get("APP_BASE_URL", "https://beg-work-refactor.preview.emergentagent.com")

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

# ── Usage Tracking & Limits Enforcement ──────────────────────────────

async def compute_org_usage(org_id: str) -> dict:
    """Compute current usage counts for an organization"""
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    # Count users
    users_count = await db.users.count_documents({"org_id": org_id, "is_active": True})
    
    # Count projects (active only)
    projects_count = await db.projects.count_documents({"org_id": org_id, "status": {"$ne": "Archived"}})
    
    # Count invoices created this month
    invoices_count = await db.invoices.count_documents({
        "org_id": org_id,
        "created_at": {"$gte": month_start.isoformat()}
    })
    
    # Storage placeholder (would need actual file storage tracking)
    storage_used_mb = 0
    
    return {
        "users_count": users_count,
        "projects_count": projects_count,
        "invoices_count_monthly": invoices_count,
        "storage_used_mb": storage_used_mb,
        "computed_at": now.isoformat(),
        "month_start": month_start.isoformat(),
    }

async def check_limit(org_id: str, resource: str, increment: int = 1) -> dict:
    """
    Check if adding `increment` items would exceed the plan limit.
    Returns: {"allowed": bool, "error_code": str|None, "current": int, "limit": int, "warning": bool}
    """
    sub = await db.subscriptions.find_one({"org_id": org_id}, {"_id": 0})
    if not sub:
        return {"allowed": False, "error_code": "NO_SUBSCRIPTION", "current": 0, "limit": 0, "warning": False}
    
    plan = SUBSCRIPTION_PLANS.get(sub.get("plan_id", "free"), SUBSCRIPTION_PLANS["free"])
    limits = plan.get("limits", {})
    
    # Map resource to limit key and count function
    resource_map = {
        "users": ("users", lambda: db.users.count_documents({"org_id": org_id, "is_active": True})),
        "projects": ("projects", lambda: db.projects.count_documents({"org_id": org_id, "status": {"$ne": "Archived"}})),
        "invoices": ("monthly_invoices", None),  # Special handling for monthly invoices
    }
    
    if resource not in resource_map:
        return {"allowed": True, "error_code": None, "current": 0, "limit": 0, "warning": False}
    
    limit_key, count_fn = resource_map[resource]
    limit = limits.get(limit_key, -1)
    
    # Get current count
    if resource == "invoices":
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        current = await db.invoices.count_documents({
            "org_id": org_id,
            "created_at": {"$gte": month_start.isoformat()}
        })
    else:
        current = await count_fn()
    
    # Check limit (-1 means unlimited for backwards compatibility, but we're not using it now)
    would_exceed = (current + increment) > limit
    warning = (current / limit) >= LIMIT_WARNING_THRESHOLD if limit > 0 else False
    
    error_code = None
    if would_exceed:
        error_code = f"LIMIT_{resource.upper()}_EXCEEDED"
    
    return {
        "allowed": not would_exceed,
        "error_code": error_code,
        "current": current,
        "limit": limit,
        "warning": warning,
        "percent": round((current / limit) * 100, 1) if limit > 0 else 0,
    }

async def enforce_limit(org_id: str, resource: str, increment: int = 1):
    """Enforce limit - raises HTTPException if limit exceeded"""
    result = await check_limit(org_id, resource, increment)
    if not result["allowed"]:
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": result["error_code"],
                "current": result["current"],
                "limit": result["limit"],
                "message": f"Plan limit exceeded for {resource}. Current: {result['current']}, Limit: {result['limit']}",
            }
        )
    return result

@api_router.get("/billing/usage")
async def get_billing_usage(user: dict = Depends(get_current_user)):
    """Get current usage vs plan limits with percentages and warnings"""
    org_id = user["org_id"]
    
    sub = await db.subscriptions.find_one({"org_id": org_id}, {"_id": 0})
    if not sub:
        raise HTTPException(status_code=404, detail="No subscription found")
    
    plan = SUBSCRIPTION_PLANS.get(sub.get("plan_id", "free"), SUBSCRIPTION_PLANS["free"])
    limits = plan.get("limits", {})
    
    # Compute current usage
    usage = await compute_org_usage(org_id)
    
    # Build usage breakdown with limits and warnings
    usage_items = []
    
    for key, limit_key, label in [
        ("users_count", "users", "users"),
        ("projects_count", "projects", "projects"),
        ("invoices_count_monthly", "monthly_invoices", "invoices"),
        ("storage_used_mb", "storage_mb", "storage"),
    ]:
        current = usage.get(key, 0)
        limit = limits.get(limit_key, 0)
        percent = round((current / limit) * 100, 1) if limit > 0 else 0
        warning = percent >= (LIMIT_WARNING_THRESHOLD * 100)
        exceeded = current >= limit
        
        usage_items.append({
            "resource": label,
            "current": current,
            "limit": limit,
            "percent": percent,
            "warning": warning,
            "exceeded": exceeded,
            "unit": "MB" if label == "storage" else "",
        })
    
    return {
        "plan_id": sub.get("plan_id", "free"),
        "plan_name": plan["name"],
        "usage": usage_items,
        "computed_at": usage["computed_at"],
        "month_start": usage["month_start"],
        "warning_threshold": LIMIT_WARNING_THRESHOLD * 100,
    }

# ── Mobile Integration Routes ────────────────────────────────────

async def get_org_mobile_settings(org_id: str) -> dict:
    """Get mobile settings for organization, with defaults if not set"""
    settings = await db.org_mobile_settings.find_one({"org_id": org_id}, {"_id": 0})
    if not settings:
        # Return default settings
        return {
            "org_id": org_id,
            "enabled_modules": MOBILE_MODULES.copy(),  # All enabled by default
            "updated_at": None,
        }
    return settings

async def get_mobile_view_config(org_id: str, role: str, module_code: str) -> dict:
    """Get mobile view config for a specific role and module"""
    config = await db.mobile_view_configs.find_one({
        "org_id": org_id,
        "role": role,
        "module_code": module_code,
    }, {"_id": 0})
    
    if config:
        return config
    
    # Return default config for role
    role_defaults = DEFAULT_MOBILE_CONFIGS.get(role, {})
    module_config = role_defaults.get("configs", {}).get(module_code, {})
    
    if module_config:
        return {
            "org_id": org_id,
            "role": role,
            "module_code": module_code,
            "list_fields": module_config.get("listFields", []),
            "detail_fields": module_config.get("detailFields", []),
            "allowed_actions": module_config.get("allowedActions", []),
            "default_filters": module_config.get("defaultFilters", {}),
        }
    
    # Fallback: all fields visible, no actions (read-only)
    module_fields = MOBILE_FIELDS.get(module_code, {})
    return {
        "org_id": org_id,
        "role": role,
        "module_code": module_code,
        "list_fields": module_fields.get("list", []),
        "detail_fields": module_fields.get("detail", []),
        "allowed_actions": ["view"],
        "default_filters": {},
    }

def filter_fields(data: dict, allowed_fields: List[str]) -> dict:
    """Filter dictionary to only include allowed fields - SERVER-SIDE ENFORCEMENT"""
    if not allowed_fields:
        return {}
    return {k: v for k, v in data.items() if k in allowed_fields}

def filter_list_items(items: List[dict], allowed_fields: List[str]) -> List[dict]:
    """Filter list of dictionaries to only include allowed fields"""
    return [filter_fields(item, allowed_fields) for item in items]

async def check_mobile_action(org_id: str, role: str, module_code: str, action: str) -> tuple[bool, str]:
    """
    Check if an action is allowed for a role on a module.
    Returns (allowed, error_code)
    """
    config = await get_mobile_view_config(org_id, role, module_code)
    allowed_actions = config.get("allowed_actions", [])
    
    if action in allowed_actions:
        return True, None
    
    return False, "ACTION_NOT_ALLOWED"

async def enforce_mobile_action(org_id: str, role: str, module_code: str, action: str):
    """Enforce mobile action permission - raises HTTPException if not allowed"""
    allowed, error_code = await check_mobile_action(org_id, role, module_code, action)
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": error_code,
                "message": f"Action '{action}' not allowed for role '{role}' on module '{module_code}'",
            }
        )

@api_router.get("/mobile/bootstrap")
async def mobile_bootstrap(user: dict = Depends(get_current_user)):
    """
    Single source of truth for mobile app configuration.
    Returns enabled modules, view configs, and quick actions for the user's role.
    """
    org_id = user["org_id"]
    role = user["role"]
    
    # Get org-level mobile settings
    org_settings = await get_org_mobile_settings(org_id)
    org_enabled = org_settings.get("enabled_modules", MOBILE_MODULES)
    
    # Get role-level enabled modules (from defaults or custom)
    role_defaults = DEFAULT_MOBILE_CONFIGS.get(role, {})
    role_enabled = role_defaults.get("enabledModules", MOBILE_MODULES)
    
    # Effective modules = intersection of org-enabled and role-enabled
    effective_modules = [m for m in org_enabled if m in role_enabled]
    
    # Get view configs for each effective module
    view_configs = {}
    for module in effective_modules:
        config = await get_mobile_view_config(org_id, role, module)
        view_configs[module] = {
            "listFields": config.get("list_fields", []),
            "detailFields": config.get("detail_fields", []),
            "allowedActions": config.get("allowed_actions", []),
            "defaultFilters": config.get("default_filters", {}),
        }
    
    # Quick actions (role-based shortcuts)
    quick_actions = []
    if "attendance" in effective_modules and "clockIn" in view_configs.get("attendance", {}).get("allowedActions", []):
        quick_actions.append({"id": "clockIn", "module": "attendance", "icon": "clock", "labelKey": "mobile.quickAction.clockIn"})
    if "workReports" in effective_modules and "create" in view_configs.get("workReports", {}).get("allowedActions", []):
        quick_actions.append({"id": "createWorkReport", "module": "workReports", "icon": "clipboard", "labelKey": "mobile.quickAction.createWorkReport"})
    if "deliveries" in effective_modules and "updateStatus" in view_configs.get("deliveries", {}).get("allowedActions", []):
        quick_actions.append({"id": "updateDelivery", "module": "deliveries", "icon": "truck", "labelKey": "mobile.quickAction.updateDelivery"})
    
    return {
        "user": {
            "id": user["id"],
            "first_name": user.get("first_name", ""),
            "last_name": user.get("last_name", ""),
            "role": role,
            "org_id": org_id,
        },
        "enabledModules": effective_modules,
        "viewConfigs": view_configs,
        "quickActions": quick_actions,
        "availableModules": MOBILE_MODULES,
    }

@api_router.get("/mobile/settings")
async def get_mobile_settings(user: dict = Depends(require_admin)):
    """Get organization mobile settings (admin only)"""
    settings = await get_org_mobile_settings(user["org_id"])
    return {
        **settings,
        "availableModules": MOBILE_MODULES,
        "availableActions": MOBILE_ACTIONS,
        "availableFields": MOBILE_FIELDS,
        "defaultConfigs": DEFAULT_MOBILE_CONFIGS,
    }

@api_router.put("/mobile/settings")
async def update_mobile_settings(data: MobileSettingsUpdate, user: dict = Depends(require_admin)):
    """Update organization mobile settings (admin only)"""
    org_id = user["org_id"]
    now = datetime.now(timezone.utc).isoformat()
    
    # Validate modules
    invalid_modules = [m for m in data.enabled_modules if m not in MOBILE_MODULES]
    if invalid_modules:
        raise HTTPException(status_code=400, detail=f"Invalid modules: {invalid_modules}")
    
    await db.org_mobile_settings.update_one(
        {"org_id": org_id},
        {"$set": {
            "org_id": org_id,
            "enabled_modules": data.enabled_modules,
            "updated_at": now,
        }},
        upsert=True
    )
    
    await log_audit(org_id, user["id"], user["email"], "updated", "mobile_settings", org_id, {"enabled_modules": data.enabled_modules})
    
    return await get_org_mobile_settings(org_id)

@api_router.get("/mobile/view-configs")
async def list_mobile_view_configs(user: dict = Depends(require_admin)):
    """List all mobile view configs for the organization (admin only)"""
    org_id = user["org_id"]
    configs = await db.mobile_view_configs.find({"org_id": org_id}, {"_id": 0}).to_list(1000)
    
    # Include defaults for roles/modules not customized
    all_configs = {}
    for role in ROLES:
        role_defaults = DEFAULT_MOBILE_CONFIGS.get(role, {})
        for module in MOBILE_MODULES:
            key = f"{role}:{module}"
            # Check if custom config exists
            custom = next((c for c in configs if c["role"] == role and c["module_code"] == module), None)
            if custom:
                all_configs[key] = {**custom, "is_custom": True}
            else:
                # Use default
                module_config = role_defaults.get("configs", {}).get(module, {})
                module_fields = MOBILE_FIELDS.get(module, {})
                all_configs[key] = {
                    "org_id": org_id,
                    "role": role,
                    "module_code": module,
                    "list_fields": module_config.get("listFields", module_fields.get("list", [])),
                    "detail_fields": module_config.get("detailFields", module_fields.get("detail", [])),
                    "allowed_actions": module_config.get("allowedActions", ["view"]),
                    "default_filters": module_config.get("defaultFilters", {}),
                    "is_custom": False,
                }
    
    return list(all_configs.values())

@api_router.put("/mobile/view-configs")
async def update_mobile_view_config(data: MobileViewConfigUpdate, user: dict = Depends(require_admin)):
    """Update mobile view config for a specific role and module (admin only)"""
    org_id = user["org_id"]
    now = datetime.now(timezone.utc).isoformat()
    
    # Validate role
    if data.role not in ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role: {data.role}")
    
    # Validate module
    if data.module_code not in MOBILE_MODULES:
        raise HTTPException(status_code=400, detail=f"Invalid module: {data.module_code}")
    
    # Validate fields
    valid_list_fields = MOBILE_FIELDS.get(data.module_code, {}).get("list", [])
    valid_detail_fields = MOBILE_FIELDS.get(data.module_code, {}).get("detail", [])
    valid_actions = MOBILE_ACTIONS.get(data.module_code, [])
    
    invalid_list = [f for f in data.list_fields if f not in valid_list_fields]
    invalid_detail = [f for f in data.detail_fields if f not in valid_detail_fields]
    invalid_actions = [a for a in data.allowed_actions if a not in valid_actions]
    
    if invalid_list:
        raise HTTPException(status_code=400, detail=f"Invalid list fields: {invalid_list}")
    if invalid_detail:
        raise HTTPException(status_code=400, detail=f"Invalid detail fields: {invalid_detail}")
    if invalid_actions:
        raise HTTPException(status_code=400, detail=f"Invalid actions: {invalid_actions}")
    
    config = {
        "org_id": org_id,
        "role": data.role,
        "module_code": data.module_code,
        "list_fields": data.list_fields,
        "detail_fields": data.detail_fields,
        "allowed_actions": data.allowed_actions,
        "default_filters": data.default_filters,
        "updated_at": now,
    }
    
    await db.mobile_view_configs.update_one(
        {"org_id": org_id, "role": data.role, "module_code": data.module_code},
        {"$set": config},
        upsert=True
    )
    
    await log_audit(org_id, user["id"], user["email"], "updated", "mobile_view_config", f"{data.role}:{data.module_code}", config)
    
    return config

@api_router.delete("/mobile/view-configs/{role}/{module_code}")
async def reset_mobile_view_config(role: str, module_code: str, user: dict = Depends(require_admin)):
    """Reset mobile view config to defaults for a specific role and module"""
    org_id = user["org_id"]
    
    result = await db.mobile_view_configs.delete_one({
        "org_id": org_id,
        "role": role,
        "module_code": module_code,
    })
    
    if result.deleted_count > 0:
        await log_audit(org_id, user["id"], user["email"], "reset", "mobile_view_config", f"{role}:{module_code}", {})
    
    # Return the default config
    return await get_mobile_view_config(org_id, role, module_code)

# ── Media (Photos) Routes ────────────────────────────────────────

ALLOWED_MEDIA_TYPES = ["image/jpeg", "image/png", "image/webp", "image/heic"]
MAX_MEDIA_SIZE_MB = 10
MEDIA_CONTEXT_TYPES = ["workReport", "delivery", "machine", "attendance", "profile", "message"]

@api_router.post("/media/upload")
async def upload_media(
    file: UploadFile = File(...),
    context_type: str = Form(None),
    context_id: str = Form(None),
    user: dict = Depends(get_current_user)
):
    """Upload a media file (photo)"""
    org_id = user["org_id"]
    
    # Validate file type
    if file.content_type not in ALLOWED_MEDIA_TYPES:
        raise HTTPException(status_code=400, detail={
            "error_code": "INVALID_FILE_TYPE",
            "message": f"File type not allowed. Allowed: {ALLOWED_MEDIA_TYPES}",
        })
    
    # Read file content
    content = await file.read()
    file_size = len(content)
    
    # Validate file size
    if file_size > MAX_MEDIA_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail={
            "error_code": "FILE_TOO_LARGE",
            "message": f"File size exceeds {MAX_MEDIA_SIZE_MB}MB limit",
        })
    
    # Generate unique filename
    ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    media_id = str(uuid.uuid4())
    filename = f"{media_id}.{ext}"
    
    # Store file (for now, using local storage - in production, use S3/GCS)
    upload_dir = "/app/backend/uploads"
    os.makedirs(upload_dir, exist_ok=True)
    file_path = f"{upload_dir}/{filename}"
    
    with open(file_path, "wb") as f:
        f.write(content)
    
    # Generate URL (relative for local, absolute for cloud storage)
    file_url = f"/api/media/file/{filename}"
    
    now = datetime.now(timezone.utc).isoformat()
    
    media = {
        "id": media_id,
        "org_id": org_id,
        "owner_user_id": user["id"],
        "filename": file.filename,
        "stored_filename": filename,
        "url": file_url,
        "content_type": file.content_type,
        "file_size": file_size,
        "context_type": context_type,
        "context_id": context_id,
        "created_at": now,
    }
    
    await db.media_files.insert_one(media)
    
    return {
        "id": media_id,
        "url": file_url,
        "filename": file.filename,
        "file_size": file_size,
        "context_type": context_type,
        "context_id": context_id,
    }

@api_router.post("/media/link")
async def link_media(data: MediaLinkRequest, user: dict = Depends(get_current_user)):
    """Link an existing media file to a context"""
    org_id = user["org_id"]
    
    # Validate context type
    if data.context_type not in MEDIA_CONTEXT_TYPES:
        raise HTTPException(status_code=400, detail={
            "error_code": "INVALID_CONTEXT_TYPE",
            "message": f"Invalid context type. Allowed: {MEDIA_CONTEXT_TYPES}",
        })
    
    # Find media file
    media = await db.media_files.find_one({"id": data.media_id, "org_id": org_id}, {"_id": 0})
    if not media:
        raise HTTPException(status_code=404, detail="Media file not found")
    
    # Check ownership or admin
    if media["owner_user_id"] != user["id"] and user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Not authorized to link this media")
    
    # Update media with context
    now = datetime.now(timezone.utc).isoformat()
    await db.media_files.update_one(
        {"id": data.media_id},
        {"$set": {
            "context_type": data.context_type,
            "context_id": data.context_id,
            "linked_at": now,
        }}
    )
    
    return {
        "id": data.media_id,
        "context_type": data.context_type,
        "context_id": data.context_id,
        "linked": True,
    }

@api_router.get("/media/{media_id}")
async def get_media(media_id: str, user: dict = Depends(get_current_user)):
    """Get media file metadata"""
    org_id = user["org_id"]
    
    media = await db.media_files.find_one({"id": media_id, "org_id": org_id}, {"_id": 0})
    if not media:
        raise HTTPException(status_code=404, detail="Media file not found")
    
    # Check access: owner, admin, or context-based access
    is_owner = media["owner_user_id"] == user["id"]
    is_admin = user["role"] in ["Admin", "Owner"]
    
    # TODO: Add context-based access check (e.g., if user has access to the work report)
    has_context_access = True  # Placeholder
    
    if not (is_owner or is_admin or has_context_access):
        raise HTTPException(status_code=403, detail="Not authorized to view this media")
    
    # Enrich with owner name
    owner = await db.users.find_one({"id": media["owner_user_id"]}, {"_id": 0, "first_name": 1, "last_name": 1})
    media["owner_user_name"] = f"{owner.get('first_name', '')} {owner.get('last_name', '')}".strip() if owner else ""
    
    return media

@api_router.get("/media/file/{filename}")
async def serve_media_file(filename: str, user: dict = Depends(get_current_user)):
    """Serve media file content"""
    from fastapi.responses import FileResponse
    
    file_path = f"/app/backend/uploads/{filename}"
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    # Get media metadata to check access
    media = await db.media_files.find_one({"stored_filename": filename, "org_id": user["org_id"]}, {"_id": 0})
    if not media:
        raise HTTPException(status_code=404, detail="Media not found or access denied")
    
    return FileResponse(file_path, media_type=media.get("content_type", "application/octet-stream"))

@api_router.get("/media")
async def list_media(
    context_type: Optional[str] = None,
    context_id: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    """List media files for the organization, optionally filtered by context"""
    org_id = user["org_id"]
    
    query = {"org_id": org_id}
    if context_type:
        query["context_type"] = context_type
    if context_id:
        query["context_id"] = context_id
    
    # Non-admin users only see their own media unless filtering by context
    if user["role"] not in ["Admin", "Owner", "SiteManager"] and not (context_type and context_id):
        query["owner_user_id"] = user["id"]
    
    media_list = await db.media_files.find(query, {"_id": 0}).sort("created_at", -1).to_list(100)
    
    return media_list

# ── Misc Routes ──────────────────────────────────────────────────
# MOVED to app/routes/health.py - importing router
from app.routes.health import router as health_router
api_router.include_router(health_router)

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
