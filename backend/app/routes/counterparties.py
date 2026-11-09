"""
Routes - Counterparties (Suppliers and Clients) with pagination and filters.
"""
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request
from typing import Any, Dict, Optional
from datetime import datetime, timezone
import uuid
import re

from app.db import db
from app.tenancy.data_access import TenantData
from app.deps.auth import get_current_user
from app.deps.modules import require_m5
from app.utils.audit import log_audit
from ..models.finance import CounterpartyCreate, CounterpartyUpdate
from app.services import counterparty_rules as cr
from app.services import master_records as mr
from app.services.master_write import (audit, conflict, dq_issue, forbidden, kw, once_in_tx,
                                       require_key)

router = APIRouter(tags=["Counterparties"])


def _tenant(user: dict) -> TenantData:
    """W0-03E-A1: the session user's tenant view of the legacy database."""
    return TenantData.for_user(db, user)


def finance_permission(user: dict) -> bool:
    """Check if user has finance access"""
    return user["role"] in ["Admin", "Owner", "Accountant"]


def parse_filters(filters: Optional[str]) -> dict:
    """
    Parse filter string like 'name.contains=test,type.in=supplier|client,active.bool=true'
    Supports operators: contains, equals, in, bool, min, max, from, to
    """
    if not filters:
        return {}
    result = {}
    for part in filters.split(","):
        if "=" in part:
            key, value = part.split("=", 1)
            result[key] = value
    return result


def build_mongo_query(org_id: str, filters: dict, base_query: dict = None) -> dict:
    """Build MongoDB query from parsed filters with full operator support"""
    query = base_query or {"org_id": org_id}
    
    for key, value in filters.items():
        if "." in key:
            field, op = key.rsplit(".", 1)
        else:
            field, op = key, "equals"
        
        if op == "contains":
            query[field] = {"$regex": re.escape(value), "$options": "i"}
        elif op == "equals":
            query[field] = value
        elif op == "in":
            query[field] = {"$in": value.split("|")}
        elif op == "bool":
            query[field] = value.lower() == "true"
        elif op == "min":
            if field not in query:
                query[field] = {}
            query[field]["$gte"] = float(value)
        elif op == "max":
            if field not in query:
                query[field] = {}
            query[field]["$lte"] = float(value)
        elif op == "from":
            if field not in query:
                query[field] = {}
            query[field]["$gte"] = value
        elif op == "to":
            if field not in query:
                query[field] = {}
            query[field]["$lte"] = value
    
    return query


# ── Counterparties CRUD ────────────────────────────────────────────
# CP-01 (R48.4–R48.6): create/update only by Accountant/Admin/Owner, Idempotency-Key (428),
# one transaction + CAS + canonical AuditEvent; never deleted — inactive / archived instead;
# a duplicate ЕИК → 409 EIK_ALREADY_EXISTS (+ DQ); an ЕИК change needs a second person.

EIK_ALREADY_EXISTS = "EIK_ALREADY_EXISTS"


async def _eik_owner(tenant, eik: str, exclude_id: Optional[str] = None, session=None):
    """The counterparty OR subcontractor of this tenant that already has this ЕИК (FG-229)."""
    found = await mr.eik_holder(tenant, eik, exclude=("counterparties", exclude_id), session=session)
    return found[1] if found else None


async def _claim_eik(tenant, session, eik: str) -> None:
    await mr.claim_eik(tenant, session, eik)


async def _with_duplicate_dq(tenant, user, eik: str, attempted_for: Optional[str], work):
    """Run ``work()``; an EIK_ALREADY_EXISTS refusal leaves a DQ row written OUTSIDE the
    aborted transaction, so it survives (FLOW-033 L94). A replay of a completed key never
    reaches the check — once_in_tx answers it first."""
    try:
        return await work()
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        if exc.status_code == 409 and detail.get("error_code") == EIK_ALREADY_EXISTS:
            other = await _eik_owner(tenant, eik, attempted_for)
            await dq_issue(tenant, None, code="DUPLICATE_EIK", severity="critical",
                           entity_type="counterparty", entity_id=other["id"] if other else None,
                           message="Опит за втори контрагент със същия ЕИК",
                           data={"eik": eik, "attempted_for": attempted_for}, created_by=user["id"])
        raise


def _vat_clauses(search: str, may_reveal: bool) -> list:
    """FG-510: the VAT part of the counterparty search, on the NORMALISED form."""
    norm = cr.normalize_vat(search) or ""
    if not may_reveal and cr.egn_digits_query(search):
        return []
    out = [{"vat_number": {"$regex": re.escape(search), "$options": "i"}}]
    if norm and norm != search:
        out.append({"vat_number": {"$regex": re.escape(norm), "$options": "i"}})
    return out


async def _masked(user, awaitable):
    """FG-245: a counterparty in a write response shows its legacy IBAN masked as in the readers."""
    return cr.mask_iban_fields(await awaitable, await cr.full_iban_allowed(user))


def _public(cp: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: v for k, v in cp.items() if k != "_id"}
    out["lifecycle_status"] = cr.lifecycle_of(cp, "counterparties")
    return out


@router.get("/counterparties")
async def list_counterparties(
    user: dict = Depends(require_m5),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("name"),
    sort_dir: str = Query("asc"),
    search: Optional[str] = None,
    filters: Optional[str] = None,
    type: Optional[str] = None,
    active_only: bool = True,
    include_archived: bool = False,
):
    """List counterparties with pagination, sorting, and filters (archived hidden — R48.4)"""
    tenant = _tenant(user)
    base_query = {"org_id": user["org_id"]}
    
    if type:
        base_query["type"] = type
    if active_only:
        base_query["active"] = True
    
    # Parse additional filters
    parsed_filters = parse_filters(filters)
    query = build_mongo_query(user["org_id"], parsed_filters, base_query)
    query = mr.hide_archived(query, include_archived)
    
    # Global search
    if search:
        query["$or"] = [
            {"name": {"$regex": re.escape(search), "$options": "i"}},
            {"eik": {"$regex": re.escape(search), "$options": "i"}},
            # FG-482 / FG-510 (R48.3): VAT digits may be an ЕГН (BG + ЕГН, in any spelling of
            # a legacy record) — for any other role than Owner / Accountant a query with a digit
            # run (≥ 4) does not match on vat_number at all (the ЕИК clause still does)
            *_vat_clauses(search, cr.can_reveal_egn(user)),
            {"email": {"$regex": re.escape(search), "$options": "i"}},
            {"phone": {"$regex": re.escape(search), "$options": "i"}},
        ]
    
    # Count total
    total = await tenant.counterparties.count_documents(query)
    
    # Sort
    sort_direction = 1 if sort_dir == "asc" else -1
    
    # Paginate
    skip = (page - 1) * page_size
    counterparties = await tenant.counterparties.find(query, {"_id": 0}).sort(sort_by, sort_direction).skip(skip).limit(page_size).to_list(page_size)
    if search and cr.can_reveal_egn(user):        # R48.3: an ЕГН-digit search is audited
        digits = cr.egn_digits_query(search)
        ids = [cp["id"] for cp in counterparties if digits and cr.vat_is_egn(cp.get("vat_number"))
               and digits in (cr.normalize_vat(cp.get("vat_number")) or "")]
        await mr.audit_egn_search(db, user, search, len(ids), "counterparties.list", ids)
    
    # Add invoice counts
    for cp in counterparties:
        # Count invoices where this is the supplier
        invoice_count = await tenant.invoices.count_documents({
            "org_id": user["org_id"],
            "supplier_counterparty_id": cp["id"]
        })
        cp["invoice_count"] = invoice_count
        cp["lifecycle_status"] = cr.lifecycle_of(cp, "counterparties")
    
    counterparties = cr.mask_iban_fields(counterparties, await cr.full_iban_allowed(user))  # FG-245
    return {
        "items": counterparties,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.post("/counterparties", status_code=201)
async def create_counterparty(data: CounterpartyCreate, user: dict = Depends(require_m5),
                              idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """Create a new counterparty (supplier/client) — Accountant/Admin/Owner only (R48.5)"""
    mr.require_writer(user)
    require_key(idempotency_key)
    tenant = _tenant(user)
    eik_value = cr.normalize_eik(data.eik) if data.eik and data.eik.strip() else None
    if data.eik and data.eik.strip() and not eik_value:
        raise HTTPException(status_code=422, detail={"error_code": "EIK_INVALID",
                                                     "message": "ЕИК съдържа само цифри"})
    counterparty = {
        "name": data.name, "type": data.type,
        "vat_number": cr.normalize_vat(data.vat_number),          # FG-496
        "address": data.address, "phone": data.phone, "email": data.email,
        "contact_person": data.contact_person, "payment_terms_days": data.payment_terms_days,
        "notes": data.notes, "active": True,
    }
    if eik_value:
        counterparty["eik"] = eik_value

    async def check(tenant_, session):
        await _claim_eik(tenant_, session, eik_value)
        if await _eik_owner(tenant_, eik_value, None, session):
            raise conflict(EIK_ALREADY_EXISTS, "Контрагент с този ЕИК вече съществува")

    return await _masked(user, _with_duplicate_dq(tenant, user, eik_value, None, lambda: mr.create(
        db, user, idempotency_key, collection="counterparties", doc=counterparty,
        fingerprint=data.model_dump(), check=check, result=_public)))


@router.post("/counterparties/{counterparty_id}/vat/reveal")
async def reveal_counterparty_vat(counterparty_id: str, user: dict = Depends(require_m5),
                                  idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """FG-483 (R48.3): the full BG + ЕГН VAT number of a counterparty — Owner / Accountant,
    AuditEvent ``counterparty.vat_egn.revealed`` before the value is returned."""
    return await mr.reveal_vat_egn(db, user, idempotency_key, collection="counterparties",
                                   record_id=counterparty_id, entity_type="counterparty")


@router.get("/counterparties/{counterparty_id}")
async def get_counterparty(counterparty_id: str, user: dict = Depends(require_m5)):
    """Get counterparty details"""
    tenant = _tenant(user)
    counterparty = await tenant.counterparties.find_one(
        {"id": counterparty_id, "org_id": user["org_id"]},
        {"_id": 0}
    )
    if not counterparty:
        raise HTTPException(status_code=404, detail="Counterparty not found")
    
    # Get related invoices summary
    invoices = await tenant.invoices.find(
        {"org_id": user["org_id"], "supplier_counterparty_id": counterparty_id},
        {"_id": 0, "id": 1, "invoice_no": 1, "total": 1, "status": 1, "issue_date": 1}
    ).sort("issue_date", -1).to_list(20)
    
    counterparty["recent_invoices"] = invoices
    counterparty["total_invoiced"] = sum(inv.get("total", 0) for inv in invoices)
    counterparty["lifecycle_status"] = cr.lifecycle_of(counterparty, "counterparties")
    
    return cr.mask_iban_fields(counterparty, await cr.full_iban_allowed(user))   # FG-245


@router.put("/counterparties/{counterparty_id}")
async def update_counterparty(counterparty_id: str, data: CounterpartyUpdate, user: dict = Depends(require_m5),
                              idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """Update counterparty. An ЕИК change is not applied here: it waits for a second person
    (R48.6) — ``eik_change_reason`` is required, ``POST …/eik-change/approve`` applies it."""
    mr.require_writer(user)
    require_key(idempotency_key)
    tenant = _tenant(user)
    counterparty = await tenant.counterparties.get(counterparty_id, {"_id": 0})
    if not counterparty:
        raise HTTPException(status_code=404, detail="Counterparty not found")

    raw = data.model_dump()
    expected_version = raw.pop("version", None)
    eik_reason = raw.pop("eik_change_reason", None)
    if raw.get("active") is not None and raw["active"] != (
            cr.lifecycle_of(counterparty, "counterparties") == cr.LIFECYCLE_ACTIVE):
        raise HTTPException(status_code=422, detail={
            "error_code": "USE_LIFECYCLE_ROUTE",
            "message": "Активност се сменя с …/deactivate или …/reactivate (с причина)"})
    raw.pop("active", None)
    new_eik = cr.normalize_eik(raw.pop("eik", None)) if data.eik else ""
    old_eik = cr.normalize_eik(counterparty.get("eik"))
    changes = {k: v for k, v in raw.items() if v is not None}
    if "vat_number" in changes:                                   # FG-496
        changes["vat_number"] = cr.normalize_vat(changes["vat_number"])
    # FG-429: the form shows a BG + ЕГН VAT number masked — sending it back keeps the stored one
    changes = {k: v for k, v in cr.keep_stored_if_masked(changes, counterparty,
                                                          keys=("vat_number", "iban")).items()
               if not (k in ("vat_number", "iban") and v == counterparty.get(k))}
    eik_request = None
    if new_eik and new_eik != old_eik:
        if old_eik:
            reason = eik_reason.strip() if isinstance(eik_reason, str) else ""
            if not reason:
                raise HTTPException(status_code=400, detail={
                    "error_code": "REASON_REQUIRED",
                    "message": "Смяна на ЕИК изисква причина (eik_change_reason) и одобрение от втори човек"})
            from app.services.money_amount import check_reason
            check_reason(reason)
            eik_request = {"request_id": "eikreq_" + uuid.uuid4().hex, "old_eik": old_eik,
                           "new_eik": new_eik, "reason": reason, "requested_by": user["id"],
                           "requested_at": datetime.now(timezone.utc).isoformat()}
            changes["eik_change_request"] = eik_request
        else:
            changes["eik"] = new_eik           # the first ЕИК of a record is not a change

    async def check(tenant_, session, before):
        if expected_version is not None and before.get("version") != expected_version:
            raise conflict("VERSION_CONFLICT", "Записът е променен междувременно — презаредете")
        if new_eik and new_eik != old_eik:
            await _claim_eik(tenant_, session, new_eik)
            if await _eik_owner(tenant_, new_eik, counterparty_id, session):
                raise conflict(EIK_ALREADY_EXISTS, "Контрагент с този ЕИК вече съществува")

    def result(after):
        out = _public(after)
        out["eik_change_pending"] = bool(eik_request)
        return out

    return await _masked(user, _with_duplicate_dq(tenant, user, new_eik, counterparty_id, lambda: mr.update(
        db, user, idempotency_key, collection="counterparties", record_id=counterparty_id,
        changes=changes, fingerprint={"id": counterparty_id, "body": data.model_dump()},
        check=check, result=result,
        action_name="eik_change_requested" if eik_request else "updated",
        reason=eik_request["reason"] if eik_request else None)))


async def _eik_decision(counterparty_id: str, body: Dict[str, Any], user: dict,
                        idempotency_key: Optional[str], approve: bool):
    mr.require_writer(user)
    key = require_key(idempotency_key)
    body = body if isinstance(body, dict) else {}
    tenant = _tenant(user)
    cp0 = await tenant.counterparties.get(counterparty_id, {"_id": 0})
    if not cp0:
        raise HTTPException(status_code=404, detail="Counterparty not found")
    req0 = cp0.get("eik_change_request") or {}

    async def tx(session):
        cp = await tenant.counterparties.get(counterparty_id, {"_id": 0}, **kw(session))
        req = cp.get("eik_change_request") if cp else None
        if not req:
            raise conflict("NO_PENDING_EIK_CHANGE", "Няма чакаща смяна на ЕИК")
        if body.get("request_id") != req["request_id"]:
            raise conflict("VERSION_CONFLICT", "Решението сочи към друга заявка за смяна (request_id)")
        if req["requested_by"] == user["id"]:
            raise conflict("SAME_PERSON_APPROVAL", "Смяна на ЕИК се одобрява от втори човек (Р48.6)")
        now = datetime.now(timezone.utc).isoformat()
        version = mr.next_version(cp)
        approval_id = "apr_" + uuid.uuid4().hex
        changes: Dict[str, Any] = {"updated_at": now, "version": version,
                                   "eik_change_history": list(cp.get("eik_change_history") or []) + [
                                       dict(req, decided_by=user["id"], decided_at=now,
                                            decision="approved" if approve else "rejected",
                                            approval_id=approval_id)]}
        if approve:
            await _claim_eik(tenant, session, req["new_eik"])
            if await _eik_owner(tenant, req["new_eik"], counterparty_id, session):
                raise conflict(EIK_ALREADY_EXISTS, "Контрагент с този ЕИК вече съществува")
            changes["eik"] = req["new_eik"]
        res = await tenant.counterparties.update_one(
            mr.cas_filter(cp), {"$set": changes, "$unset": {"eik_change_request": ""}}, **kw(session))
        if res.matched_count != 1:
            raise conflict("VERSION_CONFLICT", "Записът е променен междувременно — презаредете")
        await audit(db, session, user, "counterparty.eik_change_%s" % ("approved" if approve else "rejected"),
                    entity_type="counterparty", entity_id=counterparty_id, key=key,
                    approval_id=approval_id, reason=req["reason"], entity_version=str(version),
                    diff={"eik": {"before": req["old_eik"],
                                  "after": req["new_eik"] if approve else req["old_eik"]},
                          "requested_by": req["requested_by"]})
        after = await tenant.counterparties.get(counterparty_id, {"_id": 0}, **kw(session))
        return _public(after)

    return await _masked(user, _with_duplicate_dq(tenant, user, req0.get("new_eik") or "", counterparty_id, lambda: once_in_tx(
        db, user, key, "counterparty.eik_change.%s" % ("approve" if approve else "reject"),
        {"id": counterparty_id, "body": body}, tx)))


@router.post("/counterparties/{counterparty_id}/eik-change/approve")
async def approve_eik_change(counterparty_id: str, body: Dict[str, Any] = Body(default={}),
                             user: dict = Depends(require_m5),
                             idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    return await _eik_decision(counterparty_id, body, user, idempotency_key, True)


@router.post("/counterparties/{counterparty_id}/eik-change/reject")
async def reject_eik_change(counterparty_id: str, body: Dict[str, Any] = Body(default={}),
                            user: dict = Depends(require_m5),
                            idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    return await _eik_decision(counterparty_id, body, user, idempotency_key, False)


@router.delete("/counterparties/{counterparty_id}")
async def delete_counterparty(counterparty_id: str, request: Request,
                              user: dict = Depends(require_m5)):
    """R48.4: a counterparty is never deleted → 409 COUNTERPARTY_NO_DELETE, nothing written."""
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    counterparty = await _tenant(user).counterparties.get(counterparty_id, {"_id": 0, "id": 1})
    if not counterparty:
        raise HTTPException(status_code=404, detail="Counterparty not found")
    raise mr.no_delete("counterparties")


async def _lifecycle(counterparty_id, action, body, user, idempotency_key):
    """deactivate / reactivate / archive (R48.4) — reason + AuditEvent."""
    return await mr.lifecycle(db, user, idempotency_key, collection="counterparties",
                              record_id=counterparty_id, action=action, body=body)


@router.post("/counterparties/{counterparty_id}/deactivate")
async def deactivate_counterparty(counterparty_id: str, body: Dict[str, Any] = Body(default={}),
                                  user: dict = Depends(require_m5),
                                  idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    return await _lifecycle(counterparty_id, "deactivate", body, user, idempotency_key)


@router.post("/counterparties/{counterparty_id}/reactivate")
async def reactivate_counterparty(counterparty_id: str, body: Dict[str, Any] = Body(default={}),
                                  user: dict = Depends(require_m5),
                                  idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    return await _lifecycle(counterparty_id, "reactivate", body, user, idempotency_key)


@router.post("/counterparties/{counterparty_id}/archive")
async def archive_counterparty(counterparty_id: str, body: Dict[str, Any] = Body(default={}),
                               user: dict = Depends(require_m5),
                               idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    return await _lifecycle(counterparty_id, "archive", body, user, idempotency_key)


@router.get("/counterparties/enums/types")
async def get_counterparty_types():
    """Get available counterparty types"""
    return {"types": ["supplier", "client", "both", "person"]}


# ── Counterparty-Client Linking ────────────────────────────────────────────────
# CP-01: a link is an update of the counterparty — same rules (R48.5, R29, AuditEvent).

async def _selectable_client(tenant, client_id: str, session=None):
    client = await tenant.clients.find_one({"id": client_id}, {"_id": 0}, **kw(session))
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    if not cr.is_selectable(client, "clients"):
        raise HTTPException(status_code=422, detail={
            "error_code": "COUNTERPARTY_NOT_SELECTABLE",
            "message": "Клиентът е неактивен или архивиран"})
    return client


@router.post("/counterparties/{counterparty_id}/link-client")
async def link_counterparty_to_client(counterparty_id: str, data: dict, user: dict = Depends(require_m5),
                                      idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """Link a counterparty (type=person) to a client record"""
    mr.require_writer(user)
    require_key(idempotency_key)
    client_id = data.get("client_id") if isinstance(data, dict) else None
    if not client_id or not isinstance(client_id, str):
        raise HTTPException(status_code=400, detail="client_id is required")

    async def check(tenant, session, before):
        await _selectable_client(tenant, client_id, session)

    await mr.update(db, user, idempotency_key, collection="counterparties", record_id=counterparty_id,
                    changes={"client_id": client_id}, check=check, action_name="client_linked",
                    fingerprint={"id": counterparty_id, "client_id": client_id})
    return {"ok": True, "client_id": client_id}


@router.delete("/counterparties/{counterparty_id}/unlink-client")
async def unlink_counterparty_from_client(counterparty_id: str, user: dict = Depends(require_m5),
                                          idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """Unlink a counterparty from its client record (the counterparty itself stays)"""
    mr.require_writer(user)
    require_key(idempotency_key)
    await mr.update(db, user, idempotency_key, collection="counterparties", record_id=counterparty_id,
                    changes={}, unset={"client_id": ""}, action_name="client_unlinked",
                    fingerprint={"id": counterparty_id, "unlink": True})
    return {"ok": True}


@router.post("/counterparties/{counterparty_id}/auto-link-client")
async def auto_link_counterparty_to_client(counterparty_id: str, user: dict = Depends(require_m5),
                                           idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """Auto-find or create client from counterparty phone and link them — one transaction"""
    mr.require_writer(user)
    key = require_key(idempotency_key)
    tenant = _tenant(user)
    counterparty = await tenant.counterparties.find_one({"id": counterparty_id}, {"_id": 0})
    if not counterparty:
        raise HTTPException(status_code=404, detail="Counterparty not found")
    phone = counterparty.get("phone")
    if not phone:
        raise HTTPException(status_code=400, detail="Counterparty has no phone number")
    if phone.startswith("+"):
        phone_normalized = "+" + re.sub(r"[^0-9]", "", phone[1:])
    else:
        phone_normalized = re.sub(r"[^0-9]", "", phone)

    async def tx(session):
        cp = await tenant.counterparties.get(counterparty_id, {"_id": 0}, **kw(session))
        if cr.lifecycle_of(cp, "counterparties") == cr.LIFECYCLE_ARCHIVED:
            raise conflict(mr.COUNTERPARTY_ARCHIVED, "Архивираният запис е само за четене")
        existing_client = await tenant.clients.find_one({"phone_normalized": phone_normalized},
                                                        {"_id": 0}, **kw(session))
        now = datetime.now(timezone.utc).isoformat()
        created = False
        if existing_client:
            client_id = existing_client["id"]
        else:
            name_parts = (cp.get("name") or "").split(" ", 1)
            client_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "beg-clients:%s:%s" % (user["org_id"], key)))
            new_client = {
                "id": client_id, "org_id": user["org_id"],
                "first_name": name_parts[0] if name_parts else "",
                "last_name": name_parts[1] if len(name_parts) > 1 else "",
                "phone": phone, "phone_normalized": phone_normalized,
                "email": cp.get("email"), "address": cp.get("address"),
                "notes": f"Създаден от контрагент: {cp.get('name')}",
                "is_active": True, "lifecycle_status": cr.LIFECYCLE_ACTIVE, "version": 1,
                "created_by": user["id"], "created_at": now, "updated_at": now,
            }
            await tenant.clients.insert_one(dict(new_client), **kw(session))
            await audit(db, session, user, "client.created", entity_type="client", entity_id=client_id,
                        key=key, entity_version="1", diff=mr.diff("clients", None, new_client))
            created = True
        version = mr.next_version(cp)
        res = await tenant.counterparties.update_one(
            mr.cas_filter(cp), {"$set": {"client_id": client_id, "updated_at": now, "version": version}},
            **kw(session))
        if res.matched_count != 1:
            raise conflict("VERSION_CONFLICT", "Записът е променен междувременно — презаредете")
        await audit(db, session, user, "counterparty.client_linked", entity_type="counterparty",
                    entity_id=counterparty_id, key=key, entity_version=str(version),
                    diff={"client_id": {"before": cp.get("client_id"), "after": client_id}})
        return {"ok": True, "client_id": client_id, "created": created}

    return await once_in_tx(db, user, key, "counterparty.auto_link_client", {"id": counterparty_id}, tx)
