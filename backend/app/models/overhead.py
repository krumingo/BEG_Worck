"""
Pydantic models - Overhead (M9).
"""
from pydantic import BaseModel
from typing import Optional

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
