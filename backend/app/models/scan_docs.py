"""
Pydantic models - Scan Documents (scanned invoices/receipts).
"""
from pydantic import BaseModel
from typing import Optional, List

class ScanDocCreate(BaseModel):
    file_url: str  # URL to the uploaded file (from media service)
    media_id: Optional[str] = None  # Reference to media collection
    original_filename: Optional[str] = None
    pages_count: int = 1
    notes: Optional[str] = None
    linked_invoice_id: Optional[str] = None  # Can be linked later

class ScanDocUpdate(BaseModel):
    notes: Optional[str] = None
    pages_count: Optional[int] = None
    linked_invoice_id: Optional[str] = None

class ScanLineRef(BaseModel):
    """Reference to specific line in scanned document"""
    scan_doc_id: str
    page: int = 1
    line_no: Optional[int] = None
    bbox: Optional[List[float]] = None  # [x1, y1, x2, y2] bounding box for OCR
