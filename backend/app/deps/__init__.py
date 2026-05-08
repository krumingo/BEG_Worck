"""
Dependencies package - auth, modules, permissions, media ACL.
"""
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
)

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

from app.deps.media_acl import (
    MEDIA_CONTEXT_TYPES,
    check_media_access,
    check_context_access,
    enforce_media_access,
    enforce_context_access,
    log_security_event,
)
