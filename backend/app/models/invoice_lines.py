"""
Pydantic models - Invoice Lines (separate collection for detailed tracking).
"""
from pydantic import BaseModel
from typing import Optional, List, Literal

ALLOCATION_TYPES = ["project", "warehouse", "person"]

class ScanLineRefInput(BaseModel):
    """Reference to specific line in scanned document"""
    scan_doc_id: str
    page: int = 1
    line_no: Optional[int] = None

class InvoiceLineCreate(BaseModel):
    invoice_id: str
    line_no: int
    description: str
    unit: Optional[str] = None
    qty: float = 1.0
    unit_price: float = 0.0
    vat_percent: float = 20.0
    
    # Who purchased this item (driver/employee)
    purchased_by_user_id: Optional[str] = None
    
    # Allocation: where does this line go?
    allocation_type: Optional[Literal["project", "warehouse", "person"]] = None
    allocation_ref_id: Optional[str] = None  # project_id, warehouse_id, or person_id
    
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
    allocation_type: Optional[Literal["project", "warehouse", "person"]] = None
    allocation_ref_id: Optional[str] = None
    cost_category: Optional[str] = None
    scan_line_ref: Optional[ScanLineRefInput] = None
    notes: Optional[str] = None

class InvoiceLineBulkCreate(BaseModel):
    """Create multiple lines at once"""
    lines: List[InvoiceLineCreate]

class InvoiceLineAllocationUpdate(BaseModel):
    """Update allocation for a line"""
    allocation_type: Literal["project", "warehouse", "person"]
    allocation_ref_id: str
