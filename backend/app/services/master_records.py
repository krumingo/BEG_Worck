"""
CP-01 §2–§3 — writes of counterparties, clients, companies, persons and subcontractors.

* never a hard delete (R48.4, FLOW-010 §12 L391, FLOW-032 L105, CLAUDE.md §2.9): the old
  DELETE routes answer 409 COUNTERPARTY_NO_DELETE; instead „неактивен“ (Accountant /
  Admin / Owner, reversible) and „архивиран“ (Admin / Owner; hidden, read-only), each with
  a reason and an AuditEvent;
* create / update only by Accountant / Admin / Owner (R48.5) — everyone else 403;
* every write: Idempotency-Key (R29, 428), one transaction, compare-and-set on ``version``,
  canonical AuditEvent (record_event with the session); ЕГН / IBAN masked in the event.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from fastapi import HTTPException

from app.services import counterparty_rules as cr
from app.services.master_write import (audit, conflict, forbidden, kw, once_in_tx,
                                       require_key)
from app.tenancy.data_access import TenantData

COUNTERPARTY_NO_DELETE = "COUNTERPARTY_NO_DELETE"
COUNTERPARTY_ARCHIVED = "COUNTERPARTY_ARCHIVED"

#: collection → (entity type of the AuditEvent, URL prefix of the lifecycle routes)
ENTITIES = {
    "counterparties": ("counterparty", "/counterparties"),
    "clients": ("client", "/clients"),
    "companies": ("company", "/companies"),
    "persons": ("person", "/persons"),
    "subcontractors": ("subcontractor", "/subcontractors"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def no_delete(collection: str) -> HTTPException:
    """R48.4 — the old DELETE route: nothing is deleted, the answer names the alternatives."""
    prefix = ENTITIES[collection][1]
    return HTTPException(status_code=409, detail={
        "error_code": COUNTERPARTY_NO_DELETE,
        "message": "Контрагент/клиент/фирма/лице никога не се изтрива. Използвайте "
                   "„неактивен“ или „архивиран“ (с причина).",
        "alternatives": {"deactivate": "POST %s/{id}/deactivate" % prefix,
                         "archive": "POST %s/{id}/archive" % prefix}})


def safe_view(collection: str, doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The record as it may appear in an AuditEvent / log: ЕГН and IBAN masked."""
    out = {k: v for k, v in (doc or {}).items() if k not in ("_id",)}
    if out.get("egn"):
        out["egn"] = cr.mask_egn(out["egn"])
    for f in ("iban", "bank_iban"):
        if out.get(f):
            out[f] = cr.mask_iban(out[f])
    return out


def diff(collection: str, before: Optional[Dict[str, Any]], after: Dict[str, Any]) -> Dict[str, Any]:
    # FG-266: an AuditEvent never holds a full ЕГН / possible ЕГН / IBAN
    b = cr.mask_for_log(safe_view(collection, before))
    a = cr.mask_for_log(safe_view(collection, after))
    skip = {"updated_at", "version", "created_at"}
    keys = sorted((set(b) | set(a)) - skip)
    return {k: {"before": b.get(k), "after": a.get(k)} for k in keys if b.get(k) != a.get(k)}


def cas_filter(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Compare-and-set on the version the write read (records from before CP-01 have none)."""
    v = doc.get("version")
    return {"id": doc["id"], "version": v} if v is not None else \
        {"id": doc["id"], "version": {"$exists": False}}


def next_version(doc: Dict[str, Any]) -> int:
    return int(doc.get("version") or 0) + 1


#: Addendum A / D2 (R50, FLOW-032 L99/L109): every other role PROPOSES through the existing
#: Master Data pending queue („За мапване“) — no new model; the office maps it.
PROPOSE_PATH = {"method": "POST", "path": "/api/master-data/pending",
                "action": "master_data.pending.propose"}


def require_writer(user) -> None:
    if not cr.can_write_master(user):
        raise HTTPException(status_code=403, detail={
            "error_code": "FORBIDDEN",
            "message": "Контрагенти/клиенти/фирми/лица се създават и редактират само от "
                       "Счетоводител, Админ или Собственик (Р48). Предложете нов запис "
                       "„За мапване“.",
            "propose": PROPOSE_PATH})


def _tenant(db, user) -> TenantData:
    return TenantData.for_user(db, user)


async def create(db, user, idem: Optional[str], *, collection: str, doc: Dict[str, Any],
                 fingerprint: Any, check: Optional[Callable[[Any, Any], Awaitable[None]]] = None,
                 result: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
                 reason: Optional[str] = None) -> Dict[str, Any]:
    """Insert ``doc`` (its ``id`` is derived from the key, so a replay never adds a second)."""
    require_writer(user)
    key = require_key(idem)
    entity_type = ENTITIES[collection][0]
    tenant = _tenant(db, user)
    action = "%s.create" % entity_type

    async def tx(session):
        if check is not None:
            await check(tenant, session)
        now = _now()
        row = dict(doc)
        row.setdefault("id", str(uuid.uuid5(uuid.NAMESPACE_URL, "beg-%s:%s:%s" % (
            collection, user["org_id"], key))))
        row["org_id"] = user["org_id"]
        row.setdefault("created_at", now)
        row["updated_at"] = now
        row["version"] = 1
        row["lifecycle_status"] = cr.LIFECYCLE_ACTIVE
        row["created_by"] = user["id"]
        await tenant.collection(collection).insert_one(dict(row), **kw(session))
        await audit(db, session, user, "%s.created" % entity_type, entity_type=entity_type,
                    entity_id=row["id"], key=key, entity_version="1", reason=reason,
                    diff=diff(collection, None, row))
        row.pop("_id", None)
        return result(row) if result else row

    return await once_in_tx(db, user, key, action, fingerprint, tx)


async def update(db, user, idem: Optional[str], *, collection: str, record_id: str,
                 changes: Dict[str, Any], fingerprint: Any,
                 check: Optional[Callable[[Any, Any, Dict[str, Any]], Awaitable[None]]] = None,
                 result: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
                 action_name: str = "updated", reason: Optional[str] = None,
                 unset: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """CAS update of one record; an archived record is read-only (409)."""
    require_writer(user)
    key = require_key(idem)
    entity_type = ENTITIES[collection][0]
    tenant = _tenant(db, user)
    coll = tenant.collection(collection)

    async def tx(session):
        before = await coll.get(record_id, {"_id": 0}, **kw(session))
        if before is None:
            raise HTTPException(status_code=404, detail="Not found")
        if cr.lifecycle_of(before, collection) == cr.LIFECYCLE_ARCHIVED:
            raise conflict(COUNTERPARTY_ARCHIVED, "Архивираният запис е само за четене")
        if check is not None:
            await check(tenant, session, before)
        version = next_version(before)
        upd: Dict[str, Any] = {"$set": dict(changes, updated_at=_now(), version=version,
                                            updated_by=user["id"])}
        if unset:
            upd["$unset"] = unset
        res = await coll.update_one(cas_filter(before), upd, **kw(session))
        if res.matched_count != 1:
            raise conflict("VERSION_CONFLICT", "Записът е променен междувременно — презаредете")
        after = await coll.get(record_id, {"_id": 0}, **kw(session))
        await audit(db, session, user, "%s.%s" % (entity_type, action_name),
                    entity_type=entity_type, entity_id=record_id, key=key, reason=reason,
                    entity_version=str(version), diff=diff(collection, before, after))
        return result(after) if result else after

    return await once_in_tx(db, user, key, "%s.%s" % (entity_type, action_name),
                            fingerprint, tx)


LIFECYCLE_ACTIONS = ("deactivate", "reactivate", "archive")


async def lifecycle(db, user, idem: Optional[str], *, collection: str, record_id: str,
                    action: str, body: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """deactivate: active → inactive (Accountant/Admin/Owner);
    reactivate: inactive → active (Accountant/Admin/Owner), archived → active (Admin/Owner);
    archive: active|inactive → archived (Admin/Owner). A reason is required."""
    from app.services.money_amount import check_reason
    if action not in LIFECYCLE_ACTIONS:
        raise HTTPException(status_code=404, detail="Not found")
    if action == "archive" and not cr.can_archive(user):
        raise forbidden("Архивира само Админ или Собственик (Р48.4)")
    if action in ("deactivate", "reactivate") and not cr.can_deactivate(user):
        raise forbidden("Деактивира/връща Счетоводител, Админ или Собственик (Р48.4)")
    key = require_key(idem)
    body = body if isinstance(body, dict) else {}
    reason = body.get("reason")
    reason = reason.strip() if isinstance(reason, str) else ""
    if not reason:
        raise HTTPException(status_code=400, detail={"error_code": "REASON_REQUIRED",
                                                     "message": "Посочете причина"})
    check_reason(reason)
    entity_type = ENTITIES[collection][0]
    tenant = _tenant(db, user)
    coll = tenant.collection(collection)
    flag = cr.ACTIVE_FLAG[collection]

    async def tx(session):
        doc = await coll.get(record_id, {"_id": 0}, **kw(session))
        if doc is None:
            raise HTTPException(status_code=404, detail="Not found")
        current = cr.lifecycle_of(doc, collection)
        if action == "deactivate":
            allowed, target = (cr.LIFECYCLE_ACTIVE,), cr.LIFECYCLE_INACTIVE
        elif action == "archive":
            allowed, target = (cr.LIFECYCLE_ACTIVE, cr.LIFECYCLE_INACTIVE), cr.LIFECYCLE_ARCHIVED
        else:
            allowed, target = (cr.LIFECYCLE_INACTIVE, cr.LIFECYCLE_ARCHIVED), cr.LIFECYCLE_ACTIVE
            if current == cr.LIFECYCLE_ARCHIVED and not cr.can_archive(user):
                raise forbidden("Архивиран запис връща само Админ или Собственик")
        if current not in allowed:
            raise conflict("LIFECYCLE_TRANSITION_INVALID",
                           "Записът е „%s“ — действието не е приложимо" % cr.LIFECYCLE_LABELS[current],
                           lifecycle_status=current)
        now = _now()
        version = next_version(doc)
        changes = {"lifecycle_status": target, flag: target == cr.LIFECYCLE_ACTIVE,
                   "archived": target == cr.LIFECYCLE_ARCHIVED, "lifecycle_reason": reason,
                   "lifecycle_changed_by": user["id"], "lifecycle_changed_at": now,
                   "updated_at": now, "version": version}
        res = await coll.update_one(cas_filter(doc), {"$set": changes}, **kw(session))
        if res.matched_count != 1:
            raise conflict("VERSION_CONFLICT", "Записът е променен междувременно — презаредете")
        if action == "reactivate" and current == cr.LIFECYCLE_ARCHIVED and \
                collection in ("counterparties", "subcontractors"):
            await _reverify_bank_accounts(db, tenant, session, user, collection, record_id, key)
        past = {"deactivate": "deactivated", "reactivate": "reactivated", "archive": "archived"}[action]
        await audit(db, session, user, "%s.%s" % (entity_type, past), entity_type=entity_type,
                    entity_id=record_id, key=key, reason=reason, entity_version=str(version),
                    diff={"lifecycle_status": {"before": current, "after": target}})
        return {"ok": True, "id": record_id, "lifecycle_status": target,
                "lifecycle_label": cr.LIFECYCLE_LABELS[target], "version": version}

    return await once_in_tx(db, user, key, "%s.%s" % (entity_type, action),
                            {"id": record_id, "reason": reason}, tx)


async def _reverify_bank_accounts(db, tenant, session, user, collection, record_id, key):
    """R50.3: a counterparty back from the archive does not get its old IBAN back as valid —
    every verified account of it returns to „за проверка“ (a fresh 2-source verification by
    an Owner/Accountant who did not enter it), in the same transaction, each with an event."""
    party_type = "counterparty" if collection == "counterparties" else "subcontractor"
    accounts = await tenant.verified_bank_accounts.find(
        # FG-243: every live account — verified, or pending with a verification / approvals
        # collected before the archive — starts again from „за проверка“ with nothing carried
        {"party_type": party_type, "counterparty_id": record_id,
         "status": {"$in": [cr.BA_VERIFIED, cr.BA_PENDING]}},
        {"_id": 0}, **kw(session)).to_list(50)
    now = _now()
    for acc in accounts:
        res = await tenant.verified_bank_accounts.update_one(
            {"id": acc["id"], "version": acc.get("version")},
            {"$set": {"status": cr.BA_PENDING, "verification": None, "approvals": [],
                      "is_change": False, "replaces_account_id": None,
                      "reverification_reason": "unarchived",
                      "previous_verification": acc.get("verification"),
                      "version": int(acc.get("version") or 0) + 1, "updated_at": now}},
            **kw(session))
        if res.matched_count != 1:
            raise conflict("VERSION_CONFLICT", "Банкова сметка е променена междувременно")
        await audit(db, session, user, "bank_account.reverification_required",
                    entity_type="bank_account", entity_id=acc["id"], key=key,
                    reason="контрагентът е върнат от архив (Р50.3)",
                    diff={"status": {"before": acc.get("status"), "after": cr.BA_PENDING},
                          "verification_cleared": bool(acc.get("verification")),
                          "approvals_cleared": len(acc.get("approvals") or []),
                          "iban_masked": cr.mask_iban(acc.get("iban"))})


#: FG-229 (R48.6, FLOW-010 §12 L379-380): one organisation = one ЕИК across the counterparty
#: roles — a subcontractor is a counterparty role, so the two collections share one check.
EIK_COLLECTIONS = ("counterparties", "subcontractors")


async def eik_holder(tenant, eik: str, *, exclude: Optional[tuple] = None, session=None):
    """(collection, record) already holding this ЕИК (normalised) in this tenant, or None."""
    if not eik:
        return None
    for coll in EIK_COLLECTIONS:
        for doc in await tenant.collection(coll).find(
                {"eik": {"$exists": True, "$nin": [None, ""]}}, {"_id": 0, "id": 1, "eik": 1, "name": 1},
                **kw(session)).to_list(10000):
            if cr.normalize_eik(doc.get("eik")) == eik and (coll, doc["id"]) != exclude:
                return coll, doc
    return None


async def claim_eik(tenant, session, eik: str) -> None:
    """Two concurrent writes of the same ЕИК (in either collection) write the same claim row
    in their transactions, so one conflicts, is retried and then sees the other's record."""
    if eik:
        await tenant.counterparty_eik_claims.update_one(
            {"id": "eik:" + eik}, {"$set": {"touched_at": _now()}}, upsert=True, **kw(session))


def hide_archived(query: Dict[str, Any], include_archived: bool = False) -> Dict[str, Any]:
    """Lists hide archived records unless asked (R48.4: „скрит“)."""
    if not include_archived:
        query = dict(query)
        query["lifecycle_status"] = {"$ne": cr.LIFECYCLE_ARCHIVED}
    return query



async def reveal_vat_egn(db, user, idem: Optional[str], *, collection: str, record_id: str,
                         entity_type: str) -> Dict[str, Any]:
    """FG-482 / FG-483 (R48.3): the full BG + ЕГН VAT number of a company / counterparty —
    Owner / Accountant only; every reveal is an AuditEvent ``<entity>.vat_egn.revealed``
    (who, when, whose, the masked value) committed before the value is returned. A record
    whose VAT number is not a BG + ЕГН has nothing to reveal (404)."""
    if not cr.can_reveal_egn(user):
        raise forbidden("Пълното ЕГН (и ДДС номер BG + ЕГН) се вижда само от Собственик и "
                        "Счетоводител (Р48.3)")
    tenant = TenantData.for_user(db, user)
    key = idem.strip() if isinstance(idem, str) and idem.strip() else "reveal-" + uuid.uuid4().hex

    async def tx(session):
        doc = await tenant.collection(collection).find_one(
            {"id": record_id}, {"_id": 0, "id": 1, "vat_number": 1}, **kw(session))
        if not doc:
            raise HTTPException(status_code=404, detail="Записът не е намерен")
        vat = doc.get("vat_number")
        if not cr.vat_is_egn(vat):
            raise HTTPException(status_code=404, detail={
                "error_code": "NO_EGN_TO_REVEAL",
                "message": "ДДС номерът не е BG + ЕГН — няма какво да се разкрие"})
        await audit(db, session, user, "%s.vat_egn.revealed" % entity_type,
                    entity_type=entity_type, entity_id=record_id, key=key,
                    diff={"vat_masked": cr.mask_vat(vat), "revealed_by": user["id"],
                          "role": user.get("role")})
        return vat

    from app.services.master_write import run_tx
    vat = await run_tx(db, tx)
    return {"id": record_id, "vat_number": vat, "revealed": True}
