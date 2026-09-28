"""
W0-03E — adapters that let the legacy routes run through a staged migration.

Four things, each behind ``MASTER_DATA_MODE``:

  * **old-id resolution** (``resolve_legacy``): a legacy ``(collection, id)`` of
    the resolved tenant -> its reverse-reference row -> the Master record it was
    mapped to -> through any merge redirect -> the canonical record. Both
    directions must agree (the row names the record, the record carries the
    ``legacy_ref`` back, with this tenant's ``org_id``); anything else is refused,
    never guessed. A caller-supplied ``org_id`` that is not the tenant's is a
    refusal (D-15);
  * **read annotation** (``annotate``): a legacy read or export keeps every old
    field and id and, in ``enforce`` only, gains ``master_ref``;
  * **identity delete guard** (``guarded_identity_delete``): the seven
    delete-by-id identity paths plus the warehouse and asset deletions. The
    delete itself is always scoped by ``org_id``. In ``enforce`` an identity that
    is in use or accounted for by the migration is never hard-deleted — it is
    archived where the legacy document has an archive flag, and refused where it
    has none;
  * **advances** (§4.5, Krum 20.09.2026): in ``enforce`` a new advance needs an
    official Master Person; ``guest_name`` alone is refused with a machine reason
    code. Existing advances are not touched; ``advance_mapping_report`` lists the
    ``guest_name`` ones for a person to map, read-only, proposing and never mapping.

``off`` is inert everywhere: no read of Master Data, no audit, the legacy
response unchanged. ``shadow`` never blocks and never writes; it logs what
``enforce`` would do.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.master_data import legacy_plan as lp
from app.master_data import legacy_sources as ls
from app.master_data.deps import (
    MODE_ENFORCE,
    MODE_OFF,
    MODE_SHADOW,
    MasterDataConfigError,
    current_mode,
    require_tenant_context,
    resolve_mode,
)
from app.master_data.models import ENTITY_PERSON, STATUS_ACTIVE
from app.master_data.normalize import normalize_name
from app.master_data.service import SOURCE_FLOW, MasterDataRefused

logger = logging.getLogger(__name__)

ACTION_LEGACY_DELETE = "master_data.legacy.delete"

REASON_IN_USE = "IDENTITY_IN_USE"
REASON_MASTER_OWNED = "MASTER_OWNED"
REASON_ADVANCE_PERSON = "ADVANCE_REQUIRES_MASTER_PERSON"
REASON_ADVANCE_MISMATCH = "ADVANCE_PERSON_MISMATCH"


class LegacyOrgMismatch(MasterDataRefused):
    """A legacy org_id that is not the one the resolved tenant maps to."""


class LegacyReferenceInconsistent(MasterDataRefused):
    """The reverse reference and the Master record disagree — refused, not guessed."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _http(status: int, detail: Any):
    from fastapi import HTTPException
    return HTTPException(status_code=status, detail=detail)


def _mode_or_503() -> str:
    try:
        return current_mode()
    except MasterDataConfigError as exc:
        raise _http(503, str(exc))


async def context_for(user: Optional[Dict[str, Any]]):
    """The server-side tenant context of a legacy request — the W0-01 guard, no other."""
    from app.master_data.intake_hooks import _context_for
    return await _context_for(user)


# ========================================================== old-id resolution
async def _resolve_row(db, tenant_id: str, org_id: str, collection: str,
                       legacy_id: str) -> Optional[Dict[str, Any]]:
    from app.master_data.merge import _chain
    row = await db[lp.REFS_COLLECTION].find_one(
        {"_id": lp.ref_row_id(tenant_id, collection, legacy_id), "tenant_id": tenant_id},
        {"_id": 0})
    if row is None or row.get("status") not in lp.LIVE_REF_STATUSES:
        return None
    if row.get("org_id") != org_id or row.get("collection") != collection \
            or row.get("legacy_id") != legacy_id:
        raise LegacyReferenceInconsistent(
            "the reverse reference of %s/%s does not belong to this tenant's legacy org"
            % (collection, legacy_id))
    out = {"collection": collection, "legacy_id": legacy_id, "status": row["status"],
           "entity_type": row.get("entity_type"), "entity_id": row.get("entity_id"),
           "canonical_id": None, "redirected": False, "chain": [],
           "reason_code": row.get("reason_code"), "candidates": row.get("candidates") or []}
    if row["status"] != lp.REF_MAPPED:
        return out
    chain = await _chain(db, tenant_id, row["entity_type"], row["entity_id"])
    if not chain:
        raise LegacyReferenceInconsistent("%s/%s is mapped to %s, which is not a %s of this tenant"
                                          % (collection, legacy_id, row["entity_id"], row["entity_type"]))
    back = [r for r in chain[0].get("legacy_refs") or [] if isinstance(r, dict)
            and r.get("collection") == collection and r.get("legacy_id") == legacy_id]
    if not back or any(r.get("org_id") != org_id for r in back):
        raise LegacyReferenceInconsistent(
            "Master %s does not carry %s/%s back with this tenant's org; refusing"
            % (row["entity_id"], collection, legacy_id))
    out.update(canonical_id=chain[-1]["id"], redirected=len(chain) > 1,
               chain=[d["id"] for d in chain], entity=chain[-1])
    return out


async def resolve_legacy(ctx: Any, *, collection: str, legacy_id: str,
                         org_id: Optional[str] = None, mode: Any = None,
                         repository=None) -> Optional[Dict[str, Any]]:
    """Resolve one old id of this tenant. ``off``/``shadow``: None without a read."""
    effective = resolve_mode(mode)
    if effective in (MODE_OFF, MODE_SHADOW):
        return None
    ctx = require_tenant_context(ctx)
    tenant_org = lp.legacy_org_id(ctx)
    ls.source(collection)
    if not legacy_id or not isinstance(legacy_id, str):
        from app.master_data.models import MasterDataInvalid
        raise MasterDataInvalid("legacy_id is required")
    if org_id is not None and org_id != tenant_org:
        raise LegacyOrgMismatch("org_id %r is not this tenant's legacy org; the tenant is resolved "
                                "server-side and cannot be chosen by the caller" % (org_id,))
    repo = repository if repository is not None else _repository_for(ctx)
    return await _resolve_row(await repo.db(), ctx.tenant_id, tenant_org, collection, legacy_id)


def _repository_for(ctx: Any):
    from app.master_data.repository import MasterDataRepository
    return MasterDataRepository(ctx.tenant_id)


# ============================================================ read annotation
async def annotate(user: Optional[Dict[str, Any]], collection: str,
                   docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Add ``master_ref`` to legacy documents in ``enforce``; otherwise return them
    untouched. Never raises into a legacy read: an annotation is additive."""
    try:
        mode = current_mode()
    except MasterDataConfigError:
        return docs
    if mode != MODE_ENFORCE or not docs:
        return docs
    try:
        ctx = await context_for(user)
        if ctx is None or ctx.org_id != (user or {}).get("org_id"):
            return docs
        db = await ctx.db()
        for doc in docs:
            if not isinstance(doc, dict) or doc.get("org_id") != ctx.org_id or not doc.get("id"):
                continue
            try:
                resolved = await _resolve_row(db, ctx.tenant_id, ctx.org_id, collection, doc["id"])
            except MasterDataRefused as exc:
                doc["master_ref"] = {"status": "inconsistent", "detail": str(exc)}
                continue
            if resolved is None:
                doc["master_ref"] = {"status": "unmigrated"}
                continue
            doc["master_ref"] = {k: resolved.get(k) for k in (
                "status", "entity_type", "entity_id", "canonical_id", "redirected", "reason_code")}
    except Exception as exc:                          # noqa: BLE001 — additive only
        logger.warning("master_data: legacy annotation of %s skipped: %s", collection, exc)
    return docs


# ============================================================== delete guard
async def count_usage(db, org_id: str, collection: str, doc: Dict[str, Any]) -> Dict[str, int]:
    """Stored references to one legacy identity, field by field. Read-only."""
    usage: Dict[str, int] = {}
    for ref in ls.references_to(collection):
        value = doc.get(ref.by_key) if ref.by_key else doc.get("id")
        if not value:
            continue
        query: Dict[str, Any] = {"org_id": org_id, ref.field: value}
        query.update(dict(ref.where))
        n = await db[ref.collection].count_documents(query)
        if n:
            usage["%s.%s" % (ref.collection, ref.field)] = n
    return usage


async def _authorize_delete(request, user) -> None:
    from app.routes.master_data import _authorize
    await _authorize(ACTION_LEGACY_DELETE, request, user, MODE_ENFORCE)


async def _audit_delete(ctx, *, action: str, result: str, collection: str, legacy_id: str,
                        reason: str, diff: Dict[str, Any], error_code: Optional[str] = None,
                        request=None) -> None:
    from app.audit.envelope import ACTOR_HUMAN, RETENTION_R1_CRITICAL_BUSINESS, build_event
    from app.audit.store import record_event
    endpoint = None
    request_id = None
    if request is not None:
        try:
            endpoint = "%s %s" % (request.method, request.url.path)
            request_id = request.headers.get("x-request-id")
        except Exception:                             # noqa: BLE001
            pass
    event = build_event(
        tenant_id=ctx.tenant_id, actor_type=ACTOR_HUMAN, actor_id=ctx.user_id, action=action,
        source_flow=SOURCE_FLOW, retention_class=RETENTION_R1_CRITICAL_BUSINESS, result=result,
        entity_type="legacy.%s" % collection, entity_id=legacy_id, structured_diff=diff,
        reason=reason, error_code=error_code, tool_or_endpoint=endpoint, request_id=request_id,
        correlation_id=request_id)
    await record_event(await ctx.db(), event)


async def guarded_identity_delete(user: Dict[str, Any], request, legacy_db, *, collection: str,
                                  legacy_id: str,
                                  deleted_response: Optional[Dict[str, Any]] = None
                                  ) -> Optional[Dict[str, Any]]:
    """Call right before a legacy route would hard-delete an identity.

    Returns ``None`` when the legacy route may perform its own (org-scoped) hard
    delete — always in ``off``/``shadow``. In ``enforce`` it decides and performs
    the write itself and returns the response: a scoped hard delete of an unused,
    unmigrated identity, or an archive; a used identity without an archive flag
    is refused with 409. Every enforce outcome leaves a canonical AuditEvent.
    """
    mode = _mode_or_503()
    if mode == MODE_OFF:
        return None
    org_id = user.get("org_id")
    doc = await legacy_db[collection].find_one({"id": legacy_id, "org_id": org_id}, {"_id": 0})
    if doc is None:
        raise _http(404, "Not found")
    usage = await count_usage(legacy_db, org_id, collection, doc)
    if mode == MODE_SHADOW:
        logger.info("master_data: shadow delete %s/%s usage=%s — enforce would %s", collection,
                    legacy_id, usage, "archive or refuse" if usage else "check migration ownership")
        return None

    ctx = await context_for(user)
    if ctx is None:
        raise _http(403, {"error_code": "TENANT_NOT_RESOLVED",
                          "message": "no server-side tenant for this session; refusing to delete"})
    if ctx.org_id != org_id or not await ctx.data_path_matches(legacy_db):
        raise _http(409, {"error_code": "TENANT_DATA_PATH_NOT_MIGRATED",
                          "message": "the resolved tenant is not the legacy data this route "
                                     "would delete from; refusing"})
    await _authorize_delete(request, user)
    row = await (await ctx.db())[lp.REFS_COLLECTION].find_one(
        {"_id": lp.ref_row_id(ctx.tenant_id, collection, legacy_id), "tenant_id": ctx.tenant_id},
        {"_id": 0})
    owned = row is not None and row.get("status") in lp.LIVE_REF_STATUSES
    scope = {"id": legacy_id, "org_id": ctx.org_id}
    if usage or owned:
        code = REASON_MASTER_OWNED if owned else REASON_IN_USE
        diff = {"usage": usage, "reverse_reference": row.get("status") if row else None}
        flag = ls.source(collection).active_field
        if flag is None:
            await _audit_delete(ctx, action="master_data.legacy.delete_refused", result="denied",
                                collection=collection, legacy_id=legacy_id, diff=diff,
                                error_code=code, request=request,
                                reason="a used or migrated identity is never hard-deleted (FLOW-032)")
            raise _http(409, {"error_code": code, "usage": usage,
                              "message": "this record is in use or owned by Master Data; it "
                                         "cannot be deleted and has no archive state"})
        now = _now()
        await legacy_db[collection].update_one(scope, {"$set": {
            flag: False, "archived_at": now, "archived_by": ctx.user_id, "updated_at": now}})
        await _audit_delete(ctx, action="master_data.legacy.archived_instead_of_delete",
                            result="success", collection=collection, legacy_id=legacy_id,
                            diff=dict(diff, archived_flag=flag), error_code=code, request=request,
                            reason="hard delete replaced by archive: the identity is in use or "
                                   "owned by Master Data (FLOW-032)")
        return {"ok": True, "soft_deleted": True, "archived": True, "reason": code, "usage": usage}
    await legacy_db[collection].delete_one(scope)
    await _audit_delete(ctx, action="master_data.legacy.deleted", result="success",
                        collection=collection, legacy_id=legacy_id, diff={"usage": {}},
                        request=request, reason="unused, unmigrated legacy identity deleted")
    return deleted_response if deleted_response is not None else {"ok": True}


# ================================================================== advances
async def advance_master_person(user: Dict[str, Any], *, person_id: Optional[str],
                                user_id: Optional[str], guest_name: Optional[str],
                                request=None) -> Optional[Dict[str, Any]]:
    """The official Master Person a NEW advance refers to (§4.5).

    ``off``: None, nothing read. ``shadow``: None, logged. ``enforce``: the
    canonical person, from ``person_id`` or from the mapped legacy user; refused
    (422, machine reason code, denial AuditEvent) otherwise — ``guest_name`` alone
    is never enough and never creates a person.
    """
    mode = _mode_or_503()
    if mode == MODE_OFF:
        return None
    if mode == MODE_SHADOW:
        logger.info("master_data: shadow advance person_id=%s user_id=%s guest=%s — enforce "
                    "requires an official Master Person", bool(person_id), bool(user_id),
                    bool(guest_name))
        return None
    ctx = await context_for(user)
    if ctx is None:
        raise _http(403, {"error_code": "TENANT_NOT_RESOLVED",
                          "message": "no server-side tenant for this session"})
    db = await ctx.db()
    from app.master_data.merge import _chain

    async def refuse(code: str, message: str):
        try:
            await _audit_delete(ctx, action="master_data.advance.create_refused", result="denied",
                                collection="advances", legacy_id=user_id or "new", error_code=code,
                                diff={"person_id": person_id, "user_id": user_id,
                                      "guest_name_given": bool(guest_name)},
                                reason=message, request=request)
        except Exception as exc:                      # noqa: BLE001 — refused either way
            logger.warning("master_data: advance refusal audit failed: %s", exc)
        raise _http(422, {"error_code": code, "message": message})

    from_person = None
    if person_id:
        try:
            chain = await _chain(db, ctx.tenant_id, ENTITY_PERSON, person_id)
        except MasterDataRefused:
            chain = []
        if not chain or chain[-1].get("status") != STATUS_ACTIVE:
            await refuse(REASON_ADVANCE_PERSON, "person_id is not an official active Master "
                                                "Person of this tenant")
        from_person = chain[-1]
    from_user = None
    if user_id:
        try:
            resolved = await _resolve_row(db, ctx.tenant_id, ctx.org_id, "users", user_id)
        except MasterDataRefused:
            resolved = None
        if resolved and resolved.get("canonical_id"):
            from_user = resolved["entity"]
    if from_person and from_user and from_person["id"] != from_user["id"]:
        await refuse(REASON_ADVANCE_MISMATCH, "person_id and the employee's Master Person differ")
    chosen = from_person or from_user
    if chosen is None:
        await refuse(REASON_ADVANCE_PERSON,
                     "a new advance or loan needs an official Master Person (person_id); a "
                     "guest_name is not an identity — create or confirm the person first (§4.5)")
    return {"master_person_id": chosen["id"], "display_name": chosen.get("display_name")}


async def advance_mapping_report(db, *, tenant_id: str, org_id: str) -> Dict[str, Any]:
    """Every existing ``guest_name`` advance, with candidate persons. READ-ONLY.

    Meant for a restored copy. Proposes, never maps: an exact name match is shown
    as a candidate and nothing more; no advance, person or Master record is written.
    """
    advances = await db["advances"].find({"org_id": org_id, "guest_name": {"$nin": [None, ""]}},
                                         {"_id": 0}).to_list(None)
    advances = sorted((a for a in advances if not a.get("user_id")),
                      key=lambda a: str(a.get("id")))
    masters = await db["md_person"].find({"tenant_id": tenant_id, "status": STATUS_ACTIVE},
                                         {"_id": 0}).to_list(None)
    legacy = []
    for name in ("persons", "users"):
        for doc in await db[name].find({"org_id": org_id}, {"_id": 0}).to_list(None):
            legacy.append((name, doc))
    rows = await db[lp.REFS_COLLECTION].find({"tenant_id": tenant_id, "status": lp.REF_MAPPED},
                                             {"_id": 0}).to_list(None)
    mapped = {(r["collection"], r["legacy_id"]): r.get("entity_id") for r in rows}
    out = []
    for adv in advances:
        norm = normalize_name(adv.get("guest_name"))
        cands = []
        for m in masters:
            names = {m.get("normalized_name")} | {a.get("normalized") for a in m.get("aliases") or []
                                                  if isinstance(a, dict)}
            if norm and norm in names:
                cands.append({"entity_id": m["id"], "display_name": m.get("display_name"),
                              "match": "exact_normalized_name"})
        for name, doc in legacy:
            if norm and normalize_name(ls.extract(name, doc).display_name) == norm:
                cands.append({"legacy": [name, doc.get("id")], "mapped_to": mapped.get((name, doc.get("id"))),
                              "match": "exact_normalized_name"})
        out.append({"advance_id": adv.get("id"), "guest_name": adv.get("guest_name"),
                    "type": adv.get("type"), "amount": adv.get("amount"),
                    "remaining_amount": adv.get("remaining_amount"), "status": adv.get("status"),
                    "issued_date": adv.get("issued_date"), "candidates": cands,
                    "decision": "requires_human_mapping"})
    return {"tenant_id": tenant_id, "org_id": org_id, "read_only": True, "auto_mapped": 0,
            "total": len(out), "with_candidates": sum(1 for r in out if r["candidates"]),
            "advances": out}
