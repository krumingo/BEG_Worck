"""
Pydantic models - Core (Auth, Users, Org).
"""
from pydantic import BaseModel
from typing import Optional, List

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


# --- W0-02 Permission Service (FLOW-002) ----------------------------------
class RoleAssignmentCreate(BaseModel):
    user_id: str
    role_id: str
    scope_type: str = "company"          # company | project | object | module
    scope_id: Optional[str] = None
    module: Optional[str] = None         # M0..M9; None = all modules
    permissions: List[str] = []          # explicit override; [] = inherit from role
    max_amount: Optional[float] = None   # FLOW-002 scope "сума"; None = no limit
    valid_from: Optional[str] = None     # None => now at write time
    valid_to: Optional[str] = None       # None => open-ended

class RoleAssignmentUpdate(BaseModel):
    permissions: Optional[List[str]] = None
    module: Optional[str] = None
    max_amount: Optional[float] = None
    valid_to: Optional[str] = None
    status: Optional[str] = None         # "revoked" to withdraw

class RoleAssignmentOut(RoleAssignmentCreate):
    id: str
    status: str
    created_by: Optional[str] = None
    approved_by: Optional[str] = None
