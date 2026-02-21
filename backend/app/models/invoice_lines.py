"""
Pydantic models - Invoice Lines (separate collection for detailed tracking).
Supports multi-allocation: split quantities across multiple projects/warehouses/clients.
"""
from pydantic import BaseModel, field_validator
from typing import Optional, List, Literal

ALLOCATION_TYPES = ["project", "warehouse", "client"]

class ScanLineRefInput(BaseModel):
    """Reference to specific line in scanned document"""
    scan_doc_id: str
    page: int = 1
    line_no: Optional[int] = None


class AllocationItem(BaseModel):
    """Single allocation of quantity to a project/warehouse/client"""
    type: Literal["project", "warehouse", "client"]
    ref_id: str
    qty: float
    note: Optional[str] = None
    
    @field_validator('qty')
    @classmethod
    def qty_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError('qty must be positive')
        return v


class InvoiceLineCreate(BaseModel):
    invoice_id: str
    line_no: int
    description: str
    unit: Optional[str] = None
    qty: float = 1.0  # This is qty_purchased
    unit_price: float = 0.0
    vat_percent: float = 20.0
    
    # Who purchased this item (driver/employee)
    purchased_by_user_id: Optional[str] = None
    
    # DEPRECATED: Single allocation (kept for backward compatibility)
    allocation_type: Optional[Literal["project", "warehouse", "client"]] = None
    allocation_ref_id: Optional[str] = None
    
    # NEW: Multi-allocation support
    allocations: Optional[List[AllocationItem]] = None
    
    # Cost tracking
    cost_category: Optional[str] = None  # Materials, Labor, Subcontract, Other
    
    # Scan reference
    scan_line_ref: Optional[ScanLineRefInput] = None
    
    notes: Optional[str] = None


class InvoiceLineUpdate(BaseModel):
    description: Optional[str] = None
    unit: Optional[str] = None
    qty: Optional[float] = None
    unit_price: Optional[float] = None
    vat_percent: Optional[float] = None
    purchased_by_user_id: Optional[str] = None
    # DEPRECATED fields (kept for backward compatibility)
    allocation_type: Optional[Literal["project", "warehouse", "client"]] = None
    allocation_ref_id: Optional[str] = None
    # NEW: Multi-allocation
    allocations: Optional[List[AllocationItem]] = None
    cost_category: Optional[str] = None
    scan_line_ref: Optional[ScanLineRefInput] = None
    notes: Optional[str] = None


class InvoiceLineBulkCreate(BaseModel):
    """Create multiple lines at once"""
    lines: List[InvoiceLineCreate]


class InvoiceLineAllocationsUpdate(BaseModel):
    """Update allocations for a line - replaces all existing allocations"""
    allocations: List[AllocationItem]


# DEPRECATED: Keep for backward compatibility
class InvoiceLineAllocationUpdate(BaseModel):
    """DEPRECATED: Use InvoiceLineAllocationsUpdate instead"""
    allocation_type: Literal["project", "warehouse", "client"]
    allocation_ref_id: str
