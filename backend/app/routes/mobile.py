"""
Routes - Mobile Integration Endpoints.

IMPORTANT: Constants (MOBILE_MODULES, MOBILE_ACTIONS, etc.) are temporarily imported from server.py.
After Stage 1.2 is complete, move them to app/core/mobile_constants.py
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import List
from datetime import datetime, timezone

# Temporary imports from server.py - move to core/mobile_constants.py after refactor
from server import (
    MOBILE_MODULES, MOBILE_ACTIONS, MOBILE_FIELDS, DEFAULT_MOBILE_CONFIGS, ROLES
)

from app.shared import db, get_current_user, require_admin, log_audit
from app.models.mobile import MobileSettingsUpdate, MobileViewConfigUpdate

router = APIRouter(tags=["Mobile"])


# ── Helpers ────────────────────────────────────────────────────────

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


async def check_mobile_action(org_id: str, role: str, module_code: str, action: str) -> tuple:
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


# ── Routes ─────────────────────────────────────────────────────────

@router.get("/mobile/bootstrap")
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


@router.get("/mobile/settings")
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


@router.put("/mobile/settings")
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


@router.get("/mobile/view-configs")
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


@router.put("/mobile/view-configs")
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


@router.delete("/mobile/view-configs/{role}/{module_code}")
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
