"""
Pydantic models - Invoice Lines (separate collection for detailed tracking).
Supports multi-allocation: split quantities across multiple projects/warehouses/clients.
"""
from pydantic import BaseModel, field_validator, model_validator
from typing import Optional, List, Literal, Any

ALLOCATION_TYPES = ["project", "warehouse", "client"]

class ScanLineRefInput(BaseModel):
    """Reference to specific line in scanned document"""
    scan_doc_id: str
    page: int = 1
    line_no: Optional[int] = None


class AllocationItem(BaseModel):
    """Single allocation of quantity to a project/warehouse/client"""
    type: Literal["project", "warehouse", "client"]
    ref_id: str  # Standard key - snake_case
    qty: float
    note: Optional[str] = None
    
    @model_validator(mode='before')
    @classmethod
    def normalize_ref_id(cls, data: Any) -> Any:
        """Accept both refId (camelCase) and ref_id (snake_case), normalize to ref_id"""
        if isinstance(data, dict):
            # If refId exists but ref_id doesn't, copy it
            if 'refId' in data and 'ref_id' not in data:
                data['ref_id'] = data['refId']
            # Remove refId to ensure only ref_id is used
            if 'refId' in data:
                del data['refId']
        return data
    
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
    # WH-REV-01 / FG-195 + WHFIX81-06: the reason of a correction — the ONE
    # correction field of the allocate route (InvoiceLineAllocationsUpdate).
    correction_reason: Optional[str] = None


class InvoiceLineBulkCreate(BaseModel):
    """Create multiple lines at once"""
    lines: List[InvoiceLineCreate]


class AllocationInputItem(BaseModel):
    """WH-FIX-01 A4 #10 (Р45): an allocation entered as a PERCENTAGE of the line
    (an input aid only) — converted at once into an exact amount / qty share
    per line by the route; the percentage itself is never stored as the rule."""
    type: Literal["project", "warehouse", "client"]
    ref_id: str
    qty: Optional[float] = None
    percent: Optional[float] = None
    note: Optional[str] = None

    @model_validator(mode='before')
    @classmethod
    def normalize_ref_id(cls, data: Any) -> Any:
        if isinstance(data, dict) and 'refId' in data:
            data.setdefault('ref_id', data['refId'])
            del data['refId']
        return data

    @model_validator(mode='after')
    def qty_or_percent(self):
        if (self.qty is None) == (self.percent is None):
            raise ValueError('give exactly one of qty or percent')
        if self.qty is not None and self.qty <= 0:
            raise ValueError('qty must be positive')
        if self.percent is not None and not (0 < self.percent <= 100):
            raise ValueError('percent must be in (0, 100]')
        return self


class InvoiceLineAllocationsUpdate(BaseModel):
    """Update allocations for a line - replaces all existing allocations"""
    allocations: List[AllocationInputItem]
    # WHFIX81-06 (CLAUDE.md §7, FLOW-006 „Корекции"): the allocation of a
    # PAID invoice changes only as a correction — a reason is required.
    correction_reason: Optional[str] = None


# DEPRECATED: Keep for backward compatibility
class InvoiceLineAllocationUpdate(BaseModel):
    """DEPRECATED: Use InvoiceLineAllocationsUpdate instead"""
    allocation_type: Literal["project", "warehouse", "client"]
    allocation_ref_id: str
