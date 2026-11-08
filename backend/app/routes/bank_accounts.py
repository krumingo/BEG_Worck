"""
CP-01 §1 — VerifiedBankAccount register (FLOW-010 §3.3, §8; FLOW-025 L146; R48.1, R48.2).

    GET  /counterparties/{id}/bank-accounts     list (Owner / Admin / Accountant)
    GET  /subcontractors/{id}/bank-accounts
    POST /counterparties/{id}/bank-accounts     register an IBAN → „за проверка“
    POST /subcontractors/{id}/bank-accounts
    POST /bank-accounts/{id}/verify             2 independent sources, by an Owner/Accountant
                                                who did not enter it (R48.1)
    POST /bank-accounts/{id}/approve-change     a change: two different Owner/Accountant
                                                approvals of the exact version (FLOW-025 L146)
    POST /bank-accounts/{id}/reject             → „отказана“

A first IBAN is active once verified (R48.1: no separate approval). A CHANGE (the party
already has a verified account) stays „за проверка“ after the verification until the
second approval; then, in the same transaction, it becomes „проверена“ and the old one
„заменена“, and the Owner and the Accountant are notified at once (R48.2). Every write:
Idempotency-Key (428), one transaction with a compare-and-set on ``version``, a canonical
AuditEvent with the IBAN masked.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException

from app.db import db
from app.deps.auth import get_current_user
from app.services import counterparty_rules as cr
from app.services.master_write import (audit, conflict, dq_issue, forbidden, kw, notify_roles,
                                       once_in_tx, require_key, unprocessable)
from app.tenancy.data_access import TenantData

router = APIRouter(tags=["Bank accounts"])

PARTY_COLLECTIONS = {"counterparty": "counterparties", "subcontractor": "subcontractors"}


def _tenant(user: dict) -> TenantData:
    return TenantData.for_user(db, user)


async def full_iban_allowed(user: dict) -> bool:
    """See ``counterparty_rules.full_iban_allowed`` (Q005 / D5)."""
    return await cr.full_iban_allowed(user)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_ids(value: Any) -> List[str]:
    """Evidence is a list of File Registry ``file_id``s — never a provider URL or path."""
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise unprocessable("EVIDENCE_NOT_FILE_ID", "Доказателствата са file_id от File Registry")
    for v in value:
        if "://" in v or "/" in v or "\\" in v:
            raise unprocessable("EVIDENCE_NOT_FILE_ID",
                                "Доказателството трябва да е file_id, не URL/път")
    return [v.strip() for v in value]


def _version(body: Dict[str, Any]) -> int:
    v = body.get("version")
    if not isinstance(v, int) or isinstance(v, bool):
        raise unprocessable("VERSION_REQUIRED", "Посочете версията на записа (version)")
    return v


def _reason(body: Dict[str, Any], required: bool = True) -> Optional[str]:
    from app.services.money_amount import check_reason
    r = body.get("reason")
    r = r.strip() if isinstance(r, str) else ""
    if not r:
        if required:
            raise HTTPException(status_code=400, detail={"error_code": "REASON_REQUIRED",
                                                         "message": "Посочете причина"})
        return None
    check_reason(r)
    return r


def _audit_view(acc: Dict[str, Any]) -> Dict[str, Any]:
    return {"party_type": acc.get("party_type"), "counterparty_id": acc.get("counterparty_id"),
            "iban_masked": cr.mask_iban(acc.get("iban")), "status": acc.get("status"),
            "version": acc.get("version"), "is_change": acc.get("is_change")}


async def _party(tenant, party_type: str, party_id: str, session=None) -> Dict[str, Any]:
    doc = await tenant.collection(PARTY_COLLECTIONS[party_type]).get(party_id, {"_id": 0}, **kw(session))
    if doc is None:
        raise HTTPException(status_code=404, detail="Counterparty not found")
    return doc


async def _cas(tenant, session, acc: Dict[str, Any], update: Dict[str, Any]) -> None:
    """Compare-and-set on the exact version the caller saw."""
    res = await tenant.verified_bank_accounts.update_one(
        {"id": acc["id"], "version": acc["version"]},
        {"$set": dict(update, version=acc["version"] + 1, updated_at=_now())}, **kw(session))
    if res.matched_count != 1:
        raise conflict("VERSION_CONFLICT", "Записът е променен междувременно — презаредете")


# ── reads ────────────────────────────────────────────────────────────────────
async def _list(party_type: str, party_id: str, user: dict):
    if not cr.can_write_master(user):
        raise forbidden()
    tenant = _tenant(user)
    await _party(tenant, party_type, party_id)
    rows = await tenant.verified_bank_accounts.find(
        {"party_type": party_type, "counterparty_id": party_id}, {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    full = await full_iban_allowed(user)
    return [cr.public_bank_account(r, full) for r in rows]


@router.get("/counterparties/{party_id}/bank-accounts")
async def list_counterparty_bank_accounts(party_id: str, user: dict = Depends(get_current_user)):
    return await _list("counterparty", party_id, user)


@router.get("/subcontractors/{party_id}/bank-accounts")
async def list_subcontractor_bank_accounts(party_id: str, user: dict = Depends(get_current_user)):
    return await _list("subcontractor", party_id, user)


# ── register ─────────────────────────────────────────────────────────────────
async def _register(party_type: str, party_id: str, body: Dict[str, Any], user: dict,
                    idem: Optional[str]):
    if not cr.can_write_master(user):
        raise forbidden()
    key = require_key(idem)
    body = body if isinstance(body, dict) else {}
    iban = cr.normalize_iban(body.get("iban"))
    if not cr.iban_is_valid(iban):
        raise unprocessable("IBAN_INVALID", "Невалиден IBAN (проверка mod-97)")
    evidence = _file_ids(body.get("evidence_file_ids"))
    tenant = _tenant(user)
    full = await full_iban_allowed(user)

    async def tx(session):
        party = await _party(tenant, party_type, party_id, session)
        if cr.lifecycle_of(party, PARTY_COLLECTIONS[party_type]) == cr.LIFECYCLE_ARCHIVED:
            raise conflict("COUNTERPARTY_ARCHIVED", "Архивиран контрагент е само за четене")
        existing = await tenant.verified_bank_accounts.find(
            {"party_type": party_type, "counterparty_id": party_id}, {"_id": 0}, **kw(session)
        ).to_list(100)
        if any(a.get("iban") == iban and a.get("status") in (cr.BA_PENDING, cr.BA_VERIFIED)
               for a in existing):
            raise conflict("BANK_ACCOUNT_EXISTS", "Този IBAN вече е регистриран за контрагента")
        current = [a for a in existing if a.get("status") == cr.BA_VERIFIED]
        now = _now()
        acc = {
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, "beg-bank-account:%s:%s" % (user["org_id"], key))),
            "org_id": user["org_id"], "party_type": party_type, "counterparty_id": party_id,
            "iban": iban, "bic": body.get("bic"), "bank_name": body.get("bank_name"),
            "holder": body.get("holder"), "currency": body.get("currency") or "EUR",
            "status": cr.BA_PENDING, "is_change": bool(current),
            "replaces_account_id": current[0]["id"] if current else None,
            "evidence_file_ids": evidence, "note": body.get("note"),
            "entered_by": user["id"], "entered_at": now, "verification": None, "approvals": [],
            "version": 1, "created_at": now, "updated_at": now,
        }
        await tenant.verified_bank_accounts.insert_one(dict(acc), **kw(session))
        await audit(db, session, user, "bank_account.registered", entity_type="bank_account",
                    entity_id=acc["id"], diff=_audit_view(acc), key=key, related_file_ids=evidence,
                    entity_version="1")
        if acc["is_change"]:
            await dq_issue(tenant, session, code="BANK_ACCOUNT_CHANGE", severity="critical",
                           entity_type=party_type, entity_id=party_id,
                           message="Смяна на банкова сметка — чака проверка и двойно одобрение",
                           data={"bank_account_id": acc["id"], "iban_masked": cr.mask_iban(iban)},
                           created_by=user["id"])
            await notify_roles(tenant, session, roles=cr.BANK_ACCOUNT_VERIFY_ROLES,
                               ntype="bank_account_change",
                               title="Смяна на банкова сметка на контрагент",
                               message="Нов IBAN %s чака проверка и двойно одобрение" % cr.mask_iban(iban),
                               data={"bank_account_id": acc["id"], "party_type": party_type,
                                     "counterparty_id": party_id})
        acc.pop("_id", None)
        return cr.public_bank_account(acc, full)

    return await once_in_tx(db, user, key, "bank_account.register",
                            {"party": [party_type, party_id], "body": body}, tx)


@router.post("/counterparties/{party_id}/bank-accounts", status_code=201)
async def register_counterparty_bank_account(party_id: str, body: Dict[str, Any] = Body(default={}),
                                             user: dict = Depends(get_current_user),
                                             idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    return await _register("counterparty", party_id, body, user, idempotency_key)


@router.post("/subcontractors/{party_id}/bank-accounts", status_code=201)
async def register_subcontractor_bank_account(party_id: str, body: Dict[str, Any] = Body(default={}),
                                              user: dict = Depends(get_current_user),
                                              idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    return await _register("subcontractor", party_id, body, user, idempotency_key)


# ── verify ───────────────────────────────────────────────────────────────────
async def _activate(tenant, session, user, acc: Dict[str, Any], key: str, approval_id: Optional[str]):
    """The account becomes the one current verified account; any other → „заменена“."""
    others = await tenant.verified_bank_accounts.find(
        {"party_type": acc["party_type"], "counterparty_id": acc["counterparty_id"],
         "status": cr.BA_VERIFIED, "id": {"$ne": acc["id"]}}, {"_id": 0}, **kw(session)).to_list(10)
    now = _now()
    for old in others:
        await _cas(tenant, session, old, {"status": cr.BA_REPLACED, "replaced_by_account_id": acc["id"],
                                          "replaced_at": now})
        await audit(db, session, user, "bank_account.replaced", entity_type="bank_account",
                    entity_id=old["id"], key=key, approval_id=approval_id,
                    diff={"status": {"before": cr.BA_VERIFIED, "after": cr.BA_REPLACED},
                          "iban_masked": cr.mask_iban(old.get("iban")),
                          "replaced_by_account_id": acc["id"]})
    return others


@router.post("/bank-accounts/{account_id}/verify")
async def verify_bank_account(account_id: str, body: Dict[str, Any] = Body(default={}),
                              user: dict = Depends(get_current_user),
                              idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    if not cr.can_verify_bank_account(user):
        raise forbidden("Банкова сметка се проверява от Счетоводител или Собственик")
    key = require_key(idempotency_key)
    body = body if isinstance(body, dict) else {}
    version = _version(body)
    err = cr.check_sources(body.get("sources"))
    if err:
        raise unprocessable(err, "Нужни са два независими източника (FLOW-010 §8.2); телефон/имейл "
                                 "не може да е само от същата фактура")
    confirmed_by = body.get("counterparty_confirmed_by")
    if not isinstance(confirmed_by, str) or not confirmed_by.strip():
        raise unprocessable("COUNTERPARTY_CONFIRMATION_REQUIRED",
                            "Посочете кой е потвърдил от страна на контрагента")
    evidence = _file_ids(body.get("evidence_file_ids"))
    sources = [{"kind": s["kind"], "description": s["description"].strip(),
                "source_origin": s["source_origin"]} for s in body["sources"]]
    tenant = _tenant(user)
    full = await full_iban_allowed(user)

    async def tx(session):
        acc = await tenant.verified_bank_accounts.get(account_id, {"_id": 0}, **kw(session))
        if acc is None:
            raise HTTPException(status_code=404, detail="Bank account not found")
        if acc.get("status") != cr.BA_PENDING or acc.get("verification"):
            raise conflict("BANK_ACCOUNT_NOT_PENDING", "Сметката не чака проверка",
                           status=acc.get("status"))
        if acc.get("version") != version:
            raise conflict("VERSION_CONFLICT", "Записът е променен междувременно — презаредете")
        if acc.get("entered_by") == user["id"]:
            raise conflict("SAME_PERSON_VERIFICATION",
                           "Проверява човек, различен от въвелия IBAN-а (Р48.1)")
        now = _now()
        verification = {"verified_by": user["id"], "verified_role": user.get("role"),
                        "verified_at": now, "sources": sources,
                        "counterparty_confirmed_by": confirmed_by.strip(),
                        "evidence_file_ids": evidence}
        current = await tenant.verified_bank_accounts.count(
            {"party_type": acc["party_type"], "counterparty_id": acc["counterparty_id"],
             "status": cr.BA_VERIFIED, "id": {"$ne": acc["id"]}}, **kw(session))
        is_change = bool(current)
        update = {"verification": verification, "is_change": is_change}
        if not is_change:
            update.update(status=cr.BA_VERIFIED, verified_at=now, verified_by=user["id"])
        await _cas(tenant, session, acc, update)
        await audit(db, session, user, "bank_account.verified", entity_type="bank_account",
                    entity_id=acc["id"], key=key, related_file_ids=evidence,
                    entity_version=str(version),
                    diff={**_audit_view(acc), "status": {"before": cr.BA_PENDING,
                                                         "after": update.get("status", cr.BA_PENDING)},
                          "sources": [{"kind": s["kind"], "source_origin": s["source_origin"]}
                                      for s in sources],
                          "awaiting_double_approval": is_change})
        out = await tenant.verified_bank_accounts.get(acc["id"], {"_id": 0}, **kw(session))
        return cr.public_bank_account(out, full)

    return await once_in_tx(db, user, key, "bank_account.verify",
                            {"id": account_id, "body": body}, tx)


# ── double approval of a change ──────────────────────────────────────────────
@router.post("/bank-accounts/{account_id}/approve-change")
async def approve_bank_account_change(account_id: str, body: Dict[str, Any] = Body(default={}),
                                      user: dict = Depends(get_current_user),
                                      idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    if not cr.can_verify_bank_account(user):
        raise forbidden("Смяна на IBAN се одобрява от Счетоводител или Собственик")
    key = require_key(idempotency_key)
    body = body if isinstance(body, dict) else {}
    version = _version(body)
    tenant = _tenant(user)
    full = await full_iban_allowed(user)

    async def tx(session):
        acc = await tenant.verified_bank_accounts.get(account_id, {"_id": 0}, **kw(session))
        if acc is None:
            raise HTTPException(status_code=404, detail="Bank account not found")
        if acc.get("status") != cr.BA_PENDING or not acc.get("is_change"):
            raise conflict("NOT_A_PENDING_CHANGE", "Сметката не е смяна, която чака одобрение")
        if not acc.get("verification"):
            raise conflict("VERIFICATION_REQUIRED", "Първо проверка с два източника, после одобрение")
        if acc.get("version") != version:
            raise conflict("VERSION_CONFLICT", "Одобрението сочи към стара версия — презаредете")
        approvals = list(acc.get("approvals") or [])
        # R50.2: the entrant never approves; the verifier may be approver 1; approver 2 is a
        # different person — at least three different people for a change of IBAN.
        if acc.get("entered_by") == user["id"]:
            raise conflict("SAME_PERSON_APPROVAL",
                           "Въвелият новия IBAN не може да го одобрява (Р50.2)")
        if any(a.get("approver_id") == user["id"] for a in approvals):
            raise conflict("SAME_PERSON_APPROVAL",
                           "Вече сте одобрили тази смяна — вторият одобряващ е различен човек (Р50.2)")
        now = _now()
        approval = {"approval_id": "apr_" + uuid.uuid4().hex, "approver_id": user["id"],
                    "role": user.get("role"), "at": now, "version": version}
        approvals.append(approval)
        update: Dict[str, Any] = {"approvals": approvals}
        activated = len(approvals) >= 2
        if activated:
            update.update(status=cr.BA_VERIFIED, verified_at=now, activated_at=now)
        await _cas(tenant, session, acc, update)
        await audit(db, session, user, "bank_account.change_approved", entity_type="bank_account",
                    entity_id=acc["id"], key=key, approval_id=approval["approval_id"],
                    entity_version=str(version),
                    diff={**_audit_view(acc), "approval_no": len(approvals),
                          "activated": activated})
        replaced = []
        if activated:
            replaced = await _activate(tenant, session, user, acc, key, approval["approval_id"])
            await notify_roles(tenant, session, roles=cr.BANK_ACCOUNT_VERIFY_ROLES,
                               ntype="bank_account_changed",
                               title="Банковата сметка на контрагент е сменена",
                               message="Активна сметка: %s (старата е заменена)" % cr.mask_iban(acc["iban"]),
                               data={"bank_account_id": acc["id"],
                                     "replaced": [o["id"] for o in replaced]})
        out = await tenant.verified_bank_accounts.get(acc["id"], {"_id": 0}, **kw(session))
        res = cr.public_bank_account(out, full)
        res["replaced_account_ids"] = [o["id"] for o in replaced]
        return res

    return await once_in_tx(db, user, key, "bank_account.approve_change",
                            {"id": account_id, "body": body}, tx)


@router.post("/bank-accounts/{account_id}/reject")
async def reject_bank_account(account_id: str, body: Dict[str, Any] = Body(default={}),
                              user: dict = Depends(get_current_user),
                              idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    if not cr.can_verify_bank_account(user):
        raise forbidden()
    key = require_key(idempotency_key)
    body = body if isinstance(body, dict) else {}
    reason = _reason(body)
    version = _version(body)
    tenant = _tenant(user)
    full = await full_iban_allowed(user)

    async def tx(session):
        acc = await tenant.verified_bank_accounts.get(account_id, {"_id": 0}, **kw(session))
        if acc is None:
            raise HTTPException(status_code=404, detail="Bank account not found")
        if acc.get("status") != cr.BA_PENDING:
            raise conflict("BANK_ACCOUNT_NOT_PENDING", "Само сметка „за проверка“ може да се откаже")
        if acc.get("version") != version:
            raise conflict("VERSION_CONFLICT", "Записът е променен междувременно — презаредете")
        await _cas(tenant, session, acc, {"status": cr.BA_REJECTED, "rejected_by": user["id"],
                                          "rejected_at": _now(), "rejection_reason": reason})
        await audit(db, session, user, "bank_account.rejected", entity_type="bank_account",
                    entity_id=acc["id"], key=key, reason=reason, entity_version=str(version),
                    diff={**_audit_view(acc), "status": {"before": cr.BA_PENDING,
                                                         "after": cr.BA_REJECTED}})
        out = await tenant.verified_bank_accounts.get(acc["id"], {"_id": 0}, **kw(session))
        return cr.public_bank_account(out, full)

    return await once_in_tx(db, user, key, "bank_account.reject",
                            {"id": account_id, "body": body}, tx)
