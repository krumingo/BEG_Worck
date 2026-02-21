"""
Pydantic models - Warehouses (Inventory locations).
"""
from pydantic import BaseModel
from typing import Optional, List, Literal

WAREHOUSE_TYPES = ["central", "project", "vehicle", "person"]

class WarehouseCreate(BaseModel):
    code: str
    name: str
    type: Literal["central", "project", "vehicle", "person"] = "central"
    project_id: Optional[str] = None  # Required if type="project"
    vehicle_id: Optional[str] = None  # Required if type="vehicle"
    person_id: Optional[str] = None   # Required if type="person"
    address: Optional[str] = None
    notes: Optional[str] = None
    active: bool = True

class WarehouseUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[Literal["central", "project", "vehicle", "person"]] = None
    project_id: Optional[str] = None
    vehicle_id: Optional[str] = None
    person_id: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    active: Optional[bool] = None
