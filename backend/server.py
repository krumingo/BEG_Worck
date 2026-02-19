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

# Import billing router - includes plans, config, signup, checkout, webhook, subscription, usage
from app.routes.billing import router as billing_router
api_router.include_router(billing_router)

# ── Mobile Integration Routes ────────────────────────────────────
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
