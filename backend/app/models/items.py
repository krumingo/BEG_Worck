"""
Pydantic models - Items/Materials (Inventory items).
"""
from pydantic import BaseModel
from typing import Optional, List

ITEM_CATEGORIES = ["Materials", "Tools", "Equipment", "Consumables", "Services", "Other"]

class ItemCreate(BaseModel):
    sku: str
    name: str
    unit: str = "бр."
    category: str = "Materials"
    brand: Optional[str] = None
    description: Optional[str] = None
    default_price: Optional[float] = None
    min_stock: Optional[float] = None
    is_active: bool = True

class ItemUpdate(BaseModel):
    name: Optional[str] = None
    unit: Optional[str] = None
    category: Optional[str] = None
    brand: Optional[str] = None
    description: Optional[str] = None
    default_price: Optional[float] = None
    min_stock: Optional[float] = None
    is_active: Optional[bool] = None
