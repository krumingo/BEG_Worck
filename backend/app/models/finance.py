"""
Pydantic models - Finance (M5).
"""
from pydantic import BaseModel
from typing import Optional, List

ACCOUNT_TYPES = ["Cash", "Bank"]
INVOICE_DIRECTIONS = ["Issued", "Received"]
INVOICE_STATUSES = ["Draft", "Sent", "PartiallyPaid", "Paid", "Overdue", "Cancelled"]
PAYMENT_DIRECTIONS = ["Inflow", "Outflow"]
COST_CATEGORIES = ["Materials", "Labor", "Subcontract", "Other"]


# ── Counterparty (Supplier/Client) ─────────────────────────────────
class CounterpartyCreate(BaseModel):
    name: str
    type: str = "supplier"  # supplier, client, both
    eik: Optional[str] = None  # Bulgarian company ID
    vat_number: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    contact_person: Optional[str] = None
    payment_terms_days: int = 30
    notes: Optional[str] = None
    active: bool = True

class CounterpartyUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    eik: Optional[str] = None
    vat_number: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    contact_person: Optional[str] = None
    payment_terms_days: Optional[int] = None
    notes: Optional[str] = None
    active: Optional[bool] = None

class FinancialAccountCreate(BaseModel):
    name: str
    type: str = "Cash"
    currency: str = "EUR"
    opening_balance: float = 0
    active: bool = True

class FinancialAccountUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    opening_balance: Optional[float] = None
    active: Optional[bool] = None

class InvoiceLineInput(BaseModel):
    description: str
    unit: Optional[str] = None
    qty: float = 1
    unit_price: float = 0
    project_id: Optional[str] = None
    cost_category: Optional[str] = None

class InvoiceCreate(BaseModel):
    direction: str
    invoice_no: str
    project_id: Optional[str] = None
    counterparty_name: Optional[str] = None
    supplier_counterparty_id: Optional[str] = None  # Reference to counterparties collection
    scan_doc_id: Optional[str] = None  # Reference to scanned document
    issue_date: str
    due_date: str
    currency: str = "EUR"
    vat_percent: float = 20.0
    notes: Optional[str] = None
    lines: List[InvoiceLineInput] = []

class InvoiceUpdate(BaseModel):
    invoice_no: Optional[str] = None
    counterparty_name: Optional[str] = None
    project_id: Optional[str] = None
    issue_date: Optional[str] = None
    due_date: Optional[str] = None
    vat_percent: Optional[float] = None
    notes: Optional[str] = None

class InvoiceLinesUpdate(BaseModel):
    lines: List[InvoiceLineInput]

class PaymentCreate(BaseModel):
    direction: str
    amount: float
    currency: str = "EUR"
    date: str
    method: str = "Cash"
    account_id: str
    counterparty_name: Optional[str] = None
    reference: Optional[str] = None
    note: Optional[str] = None

class AllocationInput(BaseModel):
    invoice_id: str
    amount: float

class AllocatePaymentRequest(BaseModel):
    allocations: List[AllocationInput]
