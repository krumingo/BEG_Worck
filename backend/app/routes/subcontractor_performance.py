"""
Routes - Subcontractor Performance Tracking v1.
Additive layer — does NOT modify subcontractor core flows.
"""
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from typing import Optional
from pydantic import BaseModel, Field, StrictInt, ValidationError
import json
import uuid

from app.db import db
from app.deps.auth import can_manage_project, get_current_user
from app.permissions.money_write import strip_money_for_non_finance
from app.services import project_lifecycle as lifecycle
from app.services.subcontractor_performance import apply_ledger_paid, build_subcontractor_performance
from app.tenancy.data_access import TenantData


def _tenant(user: dict) -> TenantData:
    """The request's tenant — from the server-loaded session user only (W0-03E-A2C)."""
    return TenantData.for_user(db, user)

router = APIRouter(tags=["Subcontractor Performance"])


class PerformanceCreate(BaseModel):
    subcontractor_id: str
    project_id: str
    package_id: Optional[str] = None
    promised_start_date: Optional[str] = None
    promised_end_date: Optional[str] = None
    actual_start_date: Optional[str] = None
    actual_end_date: Optional[str] = None
    promised_amount: Optional[float] = None
    quality_score: Optional[StrictInt] = Field(None, ge=1, le=5)   # R56(3): an integer 1–5
    rework_flag: bool = False
    notes: Optional[str] = None


class PerformanceUpdate(BaseModel):
    actual_start_date: Optional[str] = None
    actual_end_date: Optional[str] = None
    quality_score: Optional[StrictInt] = Field(None, ge=1, le=5)   # R56(3): an integer 1–5
    rework_flag: Optional[bool] = None
    notes: Optional[str] = None


#: PRJ-01 / R54(2) (FG-240): "paid" is never typed in — it is computed from the ONE Payment
#: ledger (FLOW-006) when the record is read (``services.subcontractor_performance``).
COMPUTED_FIELDS = ("actual_paid_amount",)
#: PRJ-01 / R54(2): the technical manager (SiteManager of the project), Owner and Admin.
WRITER_ROLES = ("Owner", "Admin", "SiteManager")
VERSIONS = "subcontractor_performance_versions"


def _refuse_computed(body: dict) -> None:
    for f in COMPUTED_FIELDS:
        if f in body:
            raise lifecycle.refuse(
                422, "ACTUAL_PAID_IS_COMPUTED",
                "„Платено“ не се въвежда — изчислява се от единния регистър на плащанията "
                "(FLOW-006, Р54)", field=f)


async def _require_writer(user: dict, project_id: str) -> None:
    """Owner/Admin anywhere in the tenant; a SiteManager only on a project he manages."""
    if user.get("role") not in WRITER_ROLES or not await can_manage_project(user, project_id):
        raise HTTPException(status_code=403, detail="Insufficient permissions")


def _version_row(doc: dict, user: dict, now: str, key: str) -> dict:
    snap = {k: v for k, v in doc.items() if k not in ("_id",)}
    return {"id": "%s:v%d" % (doc["id"], doc["version"]), "org_id": doc["org_id"],
            "record_id": doc["id"], "version": doc["version"], "snapshot": snap,
            "written_by": user["id"], "written_at": now, "idempotency_key": key}


@router.get("/subcontractor-performance")
@strip_money_for_non_finance   # PRJ-01 / FG-255 (R20-5M): the ledger "paid" is money
async def get_performance(
    project_id: Optional[str] = None,
    subcontractor_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    return await build_subcontractor_performance(user["org_id"], project_id, subcontractor_id)


@router.get("/subcontractor-performance/compact")
@strip_money_for_non_finance   # PRJ-01 / FG-255 (R20-5M)
async def get_compact(
    project_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    full = await build_subcontractor_performance(user["org_id"], project_id)
    items = full["items"]
    return {
        "summary": full["summary"],
        "top_delays": sorted([i for i in items if i.get("status") == "delayed"], key=lambda x: x.get("actual_end_date", ""), reverse=True)[:5],
        "top_over_budget": sorted([i for i in items if i.get("status") in ("over_budget", "mixed")], key=lambda x: x.get("variance_amount", 0), reverse=True)[:5],
    }


@router.post("/subcontractor-performance", status_code=201)
async def create_performance(request: Request, body: dict = Body(...),
                             user: dict = Depends(get_current_user),
                             idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """PRJ-01 / R54(2) (FG-240): SiteManager of the project, Owner or Admin; version 1 and
    the canonical AuditEvent in one transaction; Idempotency-Key required (428)."""
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Invalid body")
    _refuse_computed(body)
    try:
        data = PerformanceCreate(**body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=json.loads(exc.json()))
    await _require_writer(user, data.project_id)
    key = lifecycle.require_key(idempotency_key)
    tenant = _tenant(user)
    record_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "beg-sub-perf:%s:%s:%s" % (
        user["org_id"], user["id"], key)))

    async def work(session):
        if not await tenant.projects.get(data.project_id, {"_id": 0, "id": 1}, session=session):
            raise lifecycle.refuse(422, "PROJECT_NOT_FOUND", "Обектът не съществува в тази фирма")
        if not await tenant.subcontractors.get(data.subcontractor_id, {"_id": 0, "id": 1},
                                               session=session):
            raise lifecycle.refuse(422, "SUBCONTRACTOR_NOT_FOUND",
                                   "Подизпълнителят не съществува в тази фирма")
        now = lifecycle.now_iso()
        doc = {
            "id": record_id,
            **data.model_dump(),
            # W0-03E-A2B: after the caller's fields, so nothing can replace the tenant.
            "org_id": user["org_id"],
            "status": "unknown",
            "version": 1,
            "created_by": user["id"],
            "created_at": now,
            "updated_at": now,
        }
        await tenant.subcontractor_performance.insert_one(dict(doc), session=session)
        await tenant.collection(VERSIONS).insert_one(_version_row(doc, user, now, key),
                                                     session=session)
        await lifecycle.audit(session, user, action="subcontractor_performance.create",
                              entity_type="subcontractor_performance", entity_id=record_id,
                              reason=None, key=key, source_flow="FLOW-039",
                              diff={"before": None, "after": {
                                  k: doc.get(k) for k in ("subcontractor_id", "project_id",
                                                          "quality_score", "rework_flag",
                                                          "version")}})
        return doc

    return await lifecycle.keyed_transaction(user, key, "subcontractor_performance.create",
                                             {"body": body}, work)


@router.put("/subcontractor-performance/{record_id}")
async def update_performance(record_id: str, request: Request, body: dict = Body(...),
                             user: dict = Depends(get_current_user),
                             idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """PRJ-01 / R54(2) (FG-240): a new version — the previous one stays in
    ``subcontractor_performance_versions`` — and an AuditEvent, in one transaction."""
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Invalid body")
    _refuse_computed(body)
    try:
        data = PerformanceUpdate(**body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=json.loads(exc.json()))
    tenant = _tenant(user)
    current = await tenant.subcontractor_performance.find_one({"id": record_id}, {"_id": 0})
    if not current:
        raise HTTPException(status_code=404, detail="Record not found")
    await _require_writer(user, current.get("project_id"))
    key = lifecycle.require_key(idempotency_key)
    changes = {k: v for k, v in data.model_dump().items() if v is not None}
    if not changes:
        # PRJ-01 / FG-256: nothing accepted to change → no empty version, no AuditEvent
        raise lifecycle.refuse(422, "NOTHING_TO_UPDATE",
                               "Няма промяна в полетата, които могат да се редактират")

    async def work(session):
        doc = await tenant.subcontractor_performance.find_one({"id": record_id}, {"_id": 0},
                                                              session=session)
        if not doc:
            raise HTTPException(status_code=404, detail="Record not found")
        now = lifecycle.now_iso()
        version = int(doc.get("version") or 1)
        if not doc.get("version"):
            # a legacy record without versions: its current state becomes version 1 first
            await tenant.collection(VERSIONS).insert_one(
                _version_row({**doc, "version": 1}, user, now, key), session=session)
        new = {**doc, **changes, "version": version + 1, "updated_at": now,
               "updated_by": user["id"]}
        res = await tenant.subcontractor_performance.update_one(
            {"id": record_id, "version": doc.get("version")},
            {"$set": {**changes, "version": version + 1, "updated_at": now,
                      "updated_by": user["id"]}}, session=session)
        if res.matched_count != 1:
            raise lifecycle.refuse(409, "VERSION_CHANGED", "Записът току-що се промени")
        await tenant.collection(VERSIONS).insert_one(_version_row(new, user, now, key),
                                                     session=session)
        await lifecycle.audit(session, user, action="subcontractor_performance.update",
                              entity_type="subcontractor_performance", entity_id=record_id,
                              reason=None, key=key, source_flow="FLOW-039",
                              diff={"before": {k: doc.get(k) for k in changes},
                                    "after": changes, "version": version + 1})
        return new

    return await lifecycle.keyed_transaction(user, key, "subcontractor_performance.update",
                                             {"record_id": record_id, "body": body}, work)


@router.get("/subcontractor-performance/log")
@strip_money_for_non_finance   # PRJ-01 / FG-255 (R20-5M)
async def get_log(
    project_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    """PRJ-01 / FG-255: the rating history is read by its writers (R54-2): Owner/Admin, or
    the SiteManager of the named project. Everyone else → 403."""
    if user.get("role") in ("Owner", "Admin"):
        pass
    elif user.get("role") == "SiteManager" and project_id and \
            await can_manage_project(user, project_id):
        pass
    else:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    tenant = _tenant(user)
    query = {"org_id": user["org_id"]}
    if project_id:
        query["project_id"] = project_id
    items = await tenant.subcontractor_performance.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    await apply_ledger_paid(tenant, items)   # PRJ-01 / R54(2): "paid" from the ledger
    return {"items": items, "total": len(items)}
