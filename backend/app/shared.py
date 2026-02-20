"""
Shared dependencies and globals for routes.

DEPRECATED: This module re-exports from app/deps and app/db.
Import directly from those modules instead.

Migration guide:
  from app.shared import get_current_user  ->  from app.deps import get_current_user
  from app.shared import db                ->  from app.db import db
"""

# Re-export database
from app.db import db, client, mongo_url, db_name

# Re-export auth dependencies
from app.deps.auth import (
    hash_password,
    verify_password, 
    create_token,
    get_current_user,
    require_admin,
    require_platform_admin,
    get_user_project_ids,
    can_access_project,
    can_manage_project,
    JWT_SECRET,
    JWT_ALGORITHM,
    security,
    pwd_context,
)

# Re-export module dependencies
from app.deps.modules import (
    SUBSCRIPTION_PLANS,
    LIMIT_WARNING_THRESHOLD,
    SUBSCRIPTION_STATUSES,
    check_module_access_for_org,
    require_module,
    require_m2,
    require_m4,
    require_m5,
    require_m9,
    get_plan_limits,
    enforce_limit,
)

# Re-export media ACL
from app.deps.media_acl import (
    MEDIA_CONTEXT_TYPES,
    check_media_access,
    check_context_access,
    enforce_media_access,
    enforce_context_access,
    log_security_event,
)

# Constants (kept here for backward compat)
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


async def log_audit(org_id: str, user_id: str, user_email: str, action: str, 
                    entity_type: str, entity_id: str = None, changes: dict = None):
    """
    Log an audit entry to the database.
    """
    from datetime import datetime, timezone
    import uuid
    
    entry = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "user_id": user_id,
        "user_email": user_email,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "changes": changes,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await db.audit_logs.insert_one(entry)
