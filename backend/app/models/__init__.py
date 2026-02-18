"""
Models package - all Pydantic schemas.
"""
# Core
from app.models.core import (
    LoginRequest, UserCreate, UserUpdate, OrgUpdate, ModuleToggle
)

# Projects
from app.models.projects import (
    PROJECT_STATUSES, PROJECT_TYPES, PROJECT_TEAM_ROLES,
    ProjectCreate, ProjectUpdate, TeamMemberAdd, PhaseCreate, PhaseUpdate
)

# Attendance & Work Reports
from app.models.attendance import (
    ATTENDANCE_STATUSES, REPORT_STATUSES, REMINDER_TYPES, REMINDER_STATUSES,
    AttendanceMarkSelf, AttendanceMarkForUser,
    WorkReportLineInput, WorkReportDraftCreate, WorkReportUpdate, WorkReportReject,
    SendReminderRequest, ExcuseRequest
)

# Offers / BOQ
from app.models.offers import (
    OFFER_STATUSES, OFFER_UNITS,
    OfferLineInput, OfferCreate, OfferUpdate, OfferLinesUpdate, OfferReject,
    ActivityCatalogCreate, ActivityCatalogUpdate
)

# HR / Payroll
from app.models.hr import (
    PAY_TYPES, PAY_SCHEDULES, ADVANCE_TYPES, ADVANCE_STATUSES,
    PAYROLL_STATUSES, PAYSLIP_STATUSES, PAYMENT_METHODS,
    EmployeeProfileCreate, EmployeeProfileUpdate, AdvanceLoanCreate,
    PayrollRunCreate, SetDeductionsRequest, MarkPaidRequest
)

# Finance
from app.models.finance import (
    ACCOUNT_TYPES, INVOICE_DIRECTIONS, INVOICE_STATUSES,
    PAYMENT_DIRECTIONS, COST_CATEGORIES,
    FinancialAccountCreate, FinancialAccountUpdate,
    InvoiceLineInput, InvoiceCreate, InvoiceUpdate, InvoiceLinesUpdate,
    PaymentCreate, AllocationInput, AllocatePaymentRequest
)

# Overhead
from app.models.overhead import (
    OVERHEAD_FREQUENCIES, OVERHEAD_ALLOCATION_TYPES, OVERHEAD_METHODS,
    OverheadCategoryCreate, OverheadCategoryUpdate,
    OverheadCostCreate, OverheadCostUpdate,
    OverheadAssetCreate, OverheadAssetUpdate,
    OverheadSnapshotCompute, OverheadAllocateRequest
)

# Billing
from app.models.billing import (
    OrgSignupRequest, CreateCheckoutRequest, SubscriptionUpdate
)

# Mobile
from app.models.mobile import (
    MOBILE_MODULES, MOBILE_ACTIONS, MOBILE_FIELDS, DEFAULT_MOBILE_CONFIGS,
    MobileSettingsUpdate, MobileViewConfigUpdate, MediaUploadContext, MediaLinkRequest
)
