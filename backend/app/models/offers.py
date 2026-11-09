"""
Pydantic models - Offers / BOQ (M2).
"""
from pydantic import BaseModel, Field
from typing import Literal, Optional, List

# OFF-01: "Superseded" — a version replaced by a newer one (never accepted afterwards);
# "Cancelled" — a sent offer withdrawn instead of deleted (CLAUDE.md §2.9).
OFFER_STATUSES = ["Draft", "Sent", "Accepted", "Rejected", "NeedsRevision", "Archived",
                  "Superseded", "Cancelled"]
OFFER_UNITS = ["m2", "m", "pcs", "hours", "lot", "kg", "l"]

class OfferLineInput(BaseModel):
    activity_code: Optional[str] = None
    activity_name: str
    unit: str = "pcs"
    qty: float = 1
    material_unit_cost: float = 0
    labor_unit_cost: float = 0
    labor_hours_per_unit: Optional[float] = None
    note: Optional[str] = None
    sort_order: int = 0
    # Activity type/subtype for budget tracking
    activity_type: str = "Общо"
    activity_subtype: str = ""

class OfferCreate(BaseModel):
    project_id: str
    title: str
    currency: str = "EUR"
    vat_percent: float = 20.0
    notes: str = ""
    lines: List[OfferLineInput] = []

class OfferUpdate(BaseModel):
    title: Optional[str] = None
    currency: Optional[str] = None
    vat_percent: Optional[float] = None
    notes: Optional[str] = None

class OfferLinesUpdate(BaseModel):
    lines: List[OfferLineInput]

class OfferReject(BaseModel):
    reason: Optional[str] = None

# OFF-01 / FLOW-003 „Interim Approval Receipt“: the carrier of an internal acceptance.
# "internal_unspecified" is what the plain „Приеми“ button records (no carrier named).
OFFER_APPROVAL_METHODS = ("signed_pdf", "verified_email", "internal_unspecified")


class OfferAccept(BaseModel):
    approval_method: Literal["signed_pdf", "verified_email", "internal_unspecified"] = \
        "internal_unspecified"
    evidence_file_id: Optional[str] = Field(None, max_length=200)
    note: Optional[str] = Field(None, max_length=500)


class OfferCancel(BaseModel):
    reason: Optional[str] = None

class ActivityCatalogCreate(BaseModel):
    project_id: str
    code: Optional[str] = None
    name: str
    default_unit: str = "pcs"
    default_material_unit_cost: float = 0
    default_labor_unit_cost: float = 0
    default_labor_hours_per_unit: Optional[float] = None
    active: bool = True

class ActivityCatalogUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    default_unit: Optional[str] = None
    default_material_unit_cost: Optional[float] = None
    default_labor_unit_cost: Optional[float] = None
    default_labor_hours_per_unit: Optional[float] = None
    active: Optional[bool] = None
