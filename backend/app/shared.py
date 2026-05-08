"""
DEPRECATED: app/shared.py has been dismantled.

All dependencies have been moved to:
- app.db            -> Database connection
- app.deps.auth     -> Authentication (get_current_user, require_admin, etc.)
- app.deps.modules  -> Module access (require_m*, enforce_limit, etc.)
- app.deps.media_acl-> Media ACL (enforce_media_access, etc.)
- app.utils.audit   -> Audit logging (log_audit)
- app.constants     -> Constants (ROLES, MODULES)

Migration guide:
  OLD: from app.shared import db, get_current_user
  NEW: from app.db import db
       from app.deps.auth import get_current_user

This file will raise an error if imported to catch stale imports.
"""

raise ImportError(
    "app.shared is DEPRECATED. "
    "Import from app.deps, app.db, app.utils, or app.constants instead. "
    "See app/shared.py docstring for migration guide."
)
