"""
Routes — LAB-AKORD-01: akord quantity on the labor line + the agreed unit labor price
(FLOW-028, Р100, Р96). Logic: ``app.services.labor_quantity_service`` (design note there).

* GET  /labor-quantities?project_id=&date_from=&date_to= — akord lines + quantity state + history
* POST /labor-quantities                    — enter a measured quantity (pending); on an approved
                                              line quantity it is a correction (new version)
* POST /labor-quantities/{id}/approve       — approver ≠ worker ≠ enterer (four-eyes)
* POST /labor-quantities/{id}/reject        — with a reason; the line is blocked again
* GET  /labor-terms?project_id=             — finance roles: unit labor price per SMR package
* PUT  /labor-terms/{package_id}            — finance roles: set the price (version + history)

Every write needs an ``Idempotency-Key`` (R29, 428 without it) and writes an AuditEvent.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel

from app.deps.auth import get_current_user
from app.services import labor_quantity_service as svc

router = APIRouter(tags=["Labor quantities (LAB-AKORD-01)"])


class QuantityEntry(BaseModel):
    line_id: str
    quantity: float
    unit: Optional[str] = None
    execution_package_id: Optional[str] = None
    note: str = ""


class QuantityApproval(BaseModel):
    execution_package_id: Optional[str] = None
    note: str = ""


class QuantityRejection(BaseModel):
    reason: str = ""


class LaborTerms(BaseModel):
    labor_piece_rate: float
    reason: str = ""


@router.get("/labor-quantities")
async def list_quantities(project_id: str, date_from: Optional[str] = None, date_to: Optional[str] = None,
                          user: dict = Depends(get_current_user)):
    return await svc.list_project(user, project_id, date_from, date_to)


@router.post("/labor-quantities")
async def enter_quantity(data: QuantityEntry, user: dict = Depends(get_current_user),
                         idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key")):
    return await svc.enter_quantity(user, data.model_dump(), idempotency_key)


@router.post("/labor-quantities/{record_id}/approve")
async def approve_quantity(record_id: str, data: QuantityApproval, user: dict = Depends(get_current_user),
                           idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key")):
    return await svc.approve_quantity(user, record_id, data.model_dump(), idempotency_key)


@router.post("/labor-quantities/{record_id}/reject")
async def reject_quantity(record_id: str, data: QuantityRejection, user: dict = Depends(get_current_user),
                          idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key")):
    return await svc.reject_quantity(user, record_id, data.model_dump(), idempotency_key)


@router.get("/labor-terms")
async def list_terms(project_id: str, user: dict = Depends(get_current_user)):
    return await svc.list_terms(user, project_id)


@router.put("/labor-terms/{package_id}")
async def set_terms(package_id: str, data: LaborTerms, user: dict = Depends(get_current_user),
                    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key")):
    return await svc.set_terms(user, package_id, data.model_dump(), idempotency_key)
