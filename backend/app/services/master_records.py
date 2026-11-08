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
    b, a = safe_view(collection, before), safe_view(collection, after)
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


def require_writer(user) -> None:
    if not cr.can_write_master(user):
        raise forbidden("Контрагенти/клиенти/фирми/лица се създават и редактират само от "
                        "Счетоводител, Админ или Собственик (Р48)")


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
        past = {"deactivate": "deactivated", "reactivate": "reactivated", "archive": "archived"}[action]
        await audit(db, session, user, "%s.%s" % (entity_type, past), entity_type=entity_type,
                    entity_id=record_id, key=key, reason=reason, entity_version=str(version),
                    diff={"lifecycle_status": {"before": current, "after": target}})
        return {"ok": True, "id": record_id, "lifecycle_status": target,
                "lifecycle_label": cr.LIFECYCLE_LABELS[target], "version": version}

    return await once_in_tx(db, user, key, "%s.%s" % (entity_type, action),
                            {"id": record_id, "reason": reason}, tx)


def hide_archived(query: Dict[str, Any], include_archived: bool = False) -> Dict[str, Any]:
    """Lists hide archived records unless asked (R48.4: „скрит“)."""
    if not include_archived:
        query = dict(query)
        query["lifecycle_status"] = {"$ne": cr.LIFECYCLE_ARCHIVED}
    return query
