"""
Pydantic models - Mobile.
"""
from pydantic import BaseModel
from typing import List

MOBILE_MODULES = [
    "attendance",
    "workReports",
    "deliveries",
    "machines",
    "messages",
    "media",
    "profile",
]

MOBILE_ACTIONS = {
    "attendance": ["view", "clockIn", "clockOut", "viewHistory"],
    "workReports": ["view", "create", "edit", "submit", "addNote", "uploadPhoto"],
    "deliveries": ["view", "create", "updateStatus", "addNote", "uploadPhoto", "viewHistory"],
    "machines": ["view", "assignSelf", "releaseSelf", "reportIssue", "uploadPhoto"],
    "messages": ["view", "send", "viewHistory"],
    "media": ["view", "upload", "delete"],
    "profile": ["view", "edit"],
}

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
    context_type: str
    context_id: str

class MediaLinkRequest(BaseModel):
    context_type: str
    context_id: str
    media_id: str
