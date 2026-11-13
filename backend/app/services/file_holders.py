"""
MEDIA-SEC-01 (FG-576 / FG-577 / FG-579) — ONE registry of the records that rest on a file.

A "holder" is a record that points at a ``media_files`` row (by its id, its stored name or
its ``/api/media/...`` URL). A file with a holder is evidence: it is never retired without
the Owner's approval (R83(2)), and never hard-deleted (CLAUDE.md §2 rule 9).

* ``HOLDERS`` — every known holder, declared once: (kind, collection, fields). New holders
  are added here — or, for a module that owns its own lookup (CP-01 #83
  ``bank_account_guard.receipt_references``), with :func:`register_finder`, so that module's
  function and this registry answer the same question from the same declaration.
* :func:`find_holders` — every holder of a file in ONE tenant (empty → the file is unused).
* :func:`uses_version` — a stable hash of the holders: the retire request stores it and
  the approval compares it (FG-577, CLAUDE.md §8 "exact version").
* :func:`claim` — the CAS touch every reference WRITER does on the file's row BEFORE it
  writes its reference (FG-579): it refuses a retired file or one with a pending retire
  request (409), and bumps ``ref_version``. The retire paths compare-and-set on
  ``ref_version``, so a retire and a new reference can never both commit.

Readers stay tenant-bound: org-keyed collections go through ``TenantData``; the audit chain
(keyed by ``tenant_id``) only through ``app.audit.store``.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence

from fastapi import HTTPException

MEDIA_RETIRED = "retired"


@dataclass(frozen=True)
class Holder:
    kind: str                 # what the record is (shown to Owner/Admin in a 409)
    collection: str           # an org-keyed tenant collection
    fields: Sequence[str]     # where the reference sits ("a.b" reaches lists of sub-docs)


#: the holders of a file — FG-542 / FG-556 / FG-576. Field names are the REAL ones written
#: by the code (no guessed names).
HOLDERS: List[Holder] = [
    Holder("missing_smr", "missing_smr",
           ("attachments.media_id", "attachments.url",
            "client_approval.signature_media_id", "signature_media_id")),
    Holder("work_report", "work_reports",
           ("photos", "photos.media_id", "photos.id", "photos.url")),
    Holder("extra_work_draft", "extra_work_drafts",
           ("photos", "photos.media_id", "photos.id", "photos.url")),
    Holder("pending_expense", "pending_expenses", ("media_id", "media_url")),
    # FG-576: the offer acceptance evidence (offers.py accept → approval.evidence_file_id)
    Holder("offer_acceptance", "offers", ("approval.evidence_file_id",)),
    # FG-576: a canonical warehouse movement's attached documents (envelope.file_ids)
    Holder("warehouse_movement", "warehouse_transactions", ("file_ids",)),
    # FG-576: a payment's cash receipt — the field CP-01 (#83) writes (cash_receipt_file_id)
    Holder("payment_receipt", "finance_payments", ("cash_receipt_file_id",)),
    Holder("subcontractor_payment_receipt", "subcontractor_payments", ("cash_receipt_file_id",)),
    Holder("scan_doc", "scan_docs", ("media_id",)),
    Holder("ocr_intake", "ocr_invoice_intake", ("media_id",)),
    Holder("current_avatar", "users", ("avatar_url",)),
]

#: kinds whose rows are receipts of a payment — the set CP-01 #83's receipt_references reads
RECEIPT_KINDS = frozenset({"payment_receipt", "subcontractor_payment_receipt"})

Finder = Callable[[Any, str, Dict[str, Any], List[str], Any], Awaitable[List[Dict[str, Any]]]]
_FINDERS: List[Finder] = []


def register_finder(fn: Finder) -> Finder:
    """A module that owns a lookup of its own plugs it in here (one registry, many finders).
    ``fn(tenant, org_id, media, refs, session) -> [{"kind", "id"}, ...]``."""
    if fn not in _FINDERS:
        _FINDERS.append(fn)
    return fn


def references_of(media: Dict[str, Any]) -> List[str]:
    """Every way a record names this file: its id, its stored name and its two URLs."""
    media_id, stored = media.get("id"), media.get("stored_filename")
    refs = [x for x in (media_id, stored) if isinstance(x, str) and x]
    if isinstance(stored, str) and stored:
        refs += ["/api/media/file/%s" % stored, "/api/media/avatar/%s" % stored]
    return refs


async def _audit_finder(tenant, org_id, media, refs, session):
    """FG-576: an AuditEvent that names the file in ``related_file_ids``."""
    from app.audit.store import event_with_related_file
    from app.db import db
    ev = await event_with_related_file(db, tenant_id=org_id, file_refs=refs, session=session)
    return [{"kind": "audit_event", "id": ev.get("event_id")}] if ev else []


register_finder(_audit_finder)


async def find_holders(tenant, org_id: str, media: Dict[str, Any], session=None,
                       kinds: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
    """Every holder of ``media`` in this tenant (one row per kind is enough to block).

    The file's OWN link (``context_type`` / ``context_id``) is a holder too — except an
    avatar's own profile link (R83(3)): only being someone's CURRENT avatar holds it."""
    want = set(kinds) if kinds is not None else None
    refs = references_of(media)
    uses: List[Dict[str, Any]] = []
    own_profile = bool(media.get("avatar")) and media.get("context_type") == "profile"
    if (want is None or "link" in want) and (media.get("context_type") or media.get("context_id")) \
            and not own_profile:
        uses.append({"kind": "link", "context_type": media.get("context_type"),
                     "id": media.get("context_id")})
    # FG-588 condition 2: a pending holder (a movement that is being written) is a holder
    if want is None or "pending_link" in want:
        for m in media.get("pending_holders") or []:
            uses.append({"kind": "pending_link", "id": m.get("id"), "label": PENDING_LABEL,
                         "route": m.get("route")})
    if not refs:
        return uses
    for h in HOLDERS:
        if want is not None and h.kind not in want:
            continue
        flt = {"org_id": org_id, "$or": [{f: {"$in": refs}} for f in h.fields]}
        row = await tenant.collection(h.collection).find_one(flt, {"_id": 0, "id": 1},
                                                             session=session)
        if row:
            uses.append({"kind": h.kind, "id": row.get("id")})
    # FG-590(b): every registered finder runs for every query; its rows are filtered by kind
    # like the declared holders (a finder may answer several kinds, e.g. #83's receipts)
    for fn in _FINDERS:
        for u in await fn(tenant, org_id, media, refs, session):
            if want is None or u.get("kind") in want:
                uses.append(u)
    return uses


def uses_version(uses: List[Dict[str, Any]]) -> str:
    """A stable fingerprint of the holders (order-free) — the request's exact version."""
    norm = sorted(json.dumps(u, sort_keys=True, default=str) for u in uses)
    return hashlib.sha256(json.dumps(norm).encode("utf-8")).hexdigest()


def redact(uses: List[Dict[str, Any]], user: dict) -> Dict[str, Any]:
    """Pass 46 minor: WHICH records use a file (payment / user ids) is for Owner/Admin."""
    from app.services.media_policy import may_see_usage_detail
    if may_see_usage_detail(user):
        return {"uses": uses, "uses_count": len(uses)}
    return {"uses_count": len(uses), "use_kinds": sorted({u.get("kind") for u in uses})}


def _refuse(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error_code": code, "message": message})


async def claim(tenant, org_id: str, refs: Iterable[Any], session=None) -> List[str]:
    """FG-579 / FG-577: before a writer stores a reference to a file, touch the file's row.

    For every value that names a ``media_files`` row of this tenant (by id or stored name):
    a retired file → 409 ``MEDIA_RETIRED``; a file with a pending retire request → 409
    ``RETIRE_REQUEST_PENDING``; otherwise ``ref_version`` is incremented with a CAS on
    "not retired, no pending request" (a concurrent retire makes it 409 ``MEDIA_CHANGED``).
    A value that names no file of this tenant is left to the writer's own validation.
    Returns the ids of the files claimed."""
    claimed: List[str] = []
    seen = set()
    for ref in refs or []:
        if not isinstance(ref, str) or not ref:
            continue
        name = ref.rsplit("/", 1)[-1] if ref.startswith("/api/media/") else ref
        media = await tenant.media_files.find_one(
            {"org_id": org_id, "$or": [{"id": name}, {"stored_filename": name}]},
            {"_id": 0, "id": 1, "status": 1, "retire_request_pending": 1}, session=session)
        if not media or media["id"] in seen:
            continue
        seen.add(media["id"])
        if media.get("status") == MEDIA_RETIRED:
            raise _refuse(409, "MEDIA_RETIRED", "Файлът е скрит и не може да се използва")
        if media.get("retire_request_pending"):
            raise _refuse(409, "RETIRE_REQUEST_PENDING",
                          "За файла има чакаща заявка за премахване")
        res = await tenant.media_files.update_one(
            {"id": media["id"], "org_id": org_id, "status": {"$ne": MEDIA_RETIRED},
             "retire_request_pending": None},
            {"$inc": {"ref_version": 1}}, session=session)
        if res.matched_count != 1:
            raise _refuse(409, "MEDIA_CHANGED", "Файлът току-що се промени")
        claimed.append(media["id"])
    return claimed


async def claimed_write(tenant, org_id: str, refs: Iterable[Any],
                        write: Callable[[Any], Awaitable[Any]]) -> Any:
    """FG-579: the claim and the writer's reference write in ONE transaction, so the claim's
    write to the file's row and a retire's write to it conflict — one of them aborts (and
    the driver's retry then sees the other's result: a retired file → 409, or a holder →
    the retire refuses). ``write(session)`` must pass ``session`` to its own writes."""
    from app.services.auth_tx import run_in_transaction
    refs = list(refs or [])

    async def body(session):
        await claim(tenant, org_id, refs, session=session)
        return await write(session)

    return await run_in_transaction(tenant._db, body)   # pylint: disable=protected-access


# ══════════════════════════════════════════════════════════════════════════════
# FG-588 (option 4, FLOW Guard pass 47 — 6 conditions): the PENDING-HOLDER marker
# ══════════════════════════════════════════════════════════════════════════════
# A writer whose reference write runs in a transaction it cannot join (the locked
# warehouse service: POST /warehouse/movements, the project write-off, material waste)
# first places a DURABLE marker on the file row — committed before the movement runs.
# Every retire path counts a non-empty ``pending_holders`` as a holder (409), and the
# final retire CAS requires "no pending holders" AND the ref_version it read. After the
# movement commits the marker is confirmed (the movement row is now the holder); if it
# fails the marker is released. A marker left by a crash is released only by
# :func:`release_stale` — after a minimum age and a proof that nothing references the file.
PENDING_LABEL = "в процес на свързване"
NO_PENDING = {"$or": [{"pending_holders": {"$exists": False}}, {"pending_holders": {"$size": 0}}]}


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


async def mark_pending(tenant, org_id: str, refs: Iterable[Any], *, route: str,
                       user_id: str, ref: Optional[str] = None,
                       action: Optional[str] = None) -> List[Dict[str, str]]:
    """Condition 1: ONE conditional update per file — filter "not retired AND no pending
    retire request"; ``$push`` {id, route, user, ref, at} and ``$inc ref_version``. A miss →
    409 and the movement must not run (markers already placed by this call are released).
    Returns ``[{"media_id", "marker_id"}]``; values that name no file are left alone."""
    import uuid as _uuid
    placed: List[Dict[str, str]] = []
    seen = set()
    try:
        for value in refs or []:
            if not isinstance(value, str) or not value:
                continue
            name = value.rsplit("/", 1)[-1] if value.startswith("/api/media/") else value
            media = await tenant.media_files.find_one(
                {"org_id": org_id, "$or": [{"id": name}, {"stored_filename": name}]},
                {"_id": 0, "id": 1, "status": 1, "retire_request_pending": 1})
            if not media or media["id"] in seen:
                continue
            seen.add(media["id"])
            marker = {"id": "ph-" + _uuid.uuid4().hex, "route": route, "user": user_id,
                      "ref": ref, "action": action, "at": _now_iso()}
            # recorded BEFORE the write: a cancel between the write and this line would
            # otherwise leave a marker no rollback knows (pulling an unplaced id is a no-op)
            placed.append({"media_id": media["id"], "marker_id": marker["id"]})
            res = await tenant.media_files.update_one(
                {"id": media["id"], "org_id": org_id, "status": {"$ne": MEDIA_RETIRED},
                 "retire_request_pending": None},
                {"$push": {"pending_holders": marker}, "$inc": {"ref_version": 1}})
            if res.matched_count != 1:
                if media.get("status") == MEDIA_RETIRED:
                    raise _refuse(409, "MEDIA_RETIRED", "Файлът е скрит и не може да се използва")
                raise _refuse(409, "RETIRE_REQUEST_PENDING",
                              "За файла има чакаща заявка за премахване")
    except BaseException:
        # FLOW Guard pass 49: ANY exit — a 409, an error, a CancelledError between two files
        # — rolls back the markers already placed (shielded: the rollback itself survives a
        # second cancel), then re-raises
        import asyncio
        await asyncio.shield(settle_pending(tenant, org_id, placed, confirmed=False))
        raise
    return placed


async def settle_pending(tenant, org_id: str, markers: List[Dict[str, str]], *,
                         confirmed: bool) -> int:
    """Condition 3: confirm (the movement committed — its row now holds the file) or
    release (it failed) — idempotent, keyed by the marker id, a CAS that removes ONLY its
    own entry. Returns how many entries were removed (0 on a repeat)."""
    removed = 0
    for m in markers or []:
        res = await tenant.media_files.update_one(
            {"id": m["media_id"], "org_id": org_id, "pending_holders.id": m["marker_id"]},
            {"$pull": {"pending_holders": {"id": m["marker_id"]}},
             "$set": {"pending_settled_at": _now_iso(),
                      "pending_settled_as": "confirmed" if confirmed else "released"}})
        removed += res.modified_count
    return removed


async def release_stale(tenant, org_id: str, media_id: str, marker_id: str, *, actor: Dict[str, Any],
                        min_age_seconds: int, key: str) -> Dict[str, Any]:
    """Condition 4 + FG-595 / FG-598 — settle a marker that its writer left behind.

    The rule is decided by the marker's OWN ``ref`` (its movement's idempotency key) only —
    other holders stay real holders and every retire path still sees them (orchestrator,
    pass 48):

    * the marker's OWN movement exists — the FULL idempotency scope (R29): this tenant, the
      marker's user as the movement's ``actor_id``, ``idempotency_key == marker.ref`` and,
      when recorded, the marker's action — → LATE-CONFIRMED (its movement committed and the
      writer missed ``settle_pending``). Another user's movement under the same key string
      is NOT own: it never confirms someone else's marker;
    * no such movement AND the marker is older than ``min_age_seconds`` → RELEASED (its
      movement never committed), even when other holders exist;
    * no such movement AND younger → 409 ``PENDING_HOLDER_TOO_RECENT``; nothing changes.

    Never retires. Every outcome — the refusal included — is an AuditEvent with the actor,
    the marker and the proof (FG-598), written inside the ``Idempotency-Key``'s transaction
    (FG-610: a replay answers the same and writes nothing); the settle is a CAS on that
    marker id with a ``ref_version`` bump."""
    from datetime import datetime, timezone
    from app.services import project_lifecycle as lifecycle
    media = await tenant.media_files.find_one({"id": media_id, "org_id": org_id}, {"_id": 0})
    if not media:
        raise _refuse(404, "MEDIA_NOT_FOUND", "Media file not found")
    marker = next((m for m in media.get("pending_holders") or [] if m.get("id") == marker_id), None)
    fingerprint = {"media_id": media_id, "marker_id": marker_id}
    if not marker:
        # a REPLAY of a granted release finds the marker gone: the key returns its stored
        # answer; a fresh key gets "no_such_marker" (nothing written)
        async def nothing(session):
            return {"released": False, "reason": "no_such_marker"}
        return await lifecycle.keyed_transaction(actor, key, "media.file.pending_holder_release",
                                                 fingerprint, nothing)
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(marker["at"])).total_seconds()
    base = {"marker": marker, "age_seconds": int(age)}
    own = []
    if marker.get("ref") and marker.get("user"):
        scope = {"org_id": org_id, "idempotency_key": marker["ref"],
                 "actor_id": marker["user"], "file_ids": {"$in": references_of(media)}}
        if marker.get("action"):
            scope["action"] = marker["action"]
        own = await tenant.warehouse_transactions.find(
            scope, {"_id": 0, "id": 1, "movement_id": 1, "idempotency_key": 1,
                    "actor_id": 1}).to_list(None)
    if own:
        outcome, action = "confirmed_late", "media.file.pending_holder_confirm_late"
    elif age >= min_age_seconds:
        outcome, action = "released", "media.file.pending_holder_release"
    else:
        # FG-610: the refusal's AuditEvent is written INSIDE the keyed transaction and the
        # refusal is the key's stored answer — a replayed key gets the same 409, no new event
        async def refused(session):
            await lifecycle.audit(session, actor, action="media.file.pending_holder_release_refused",
                                  entity_type="media_file", entity_id=media_id,
                                  reason="marker too recent", key=key, source_flow="FLOW-029",
                                  diff=dict(base, refused="too_recent"))
            return {"released": False, "refused": "too_recent", "marker_id": marker_id}
        out = await lifecycle.keyed_transaction(actor, key, "media.file.pending_holder_release",
                                                fingerprint, refused)
        if out.get("refused") == "too_recent":
            raise _refuse(409, "PENDING_HOLDER_TOO_RECENT",
                          "Маркерът е по-нов от минималната възраст за освобождаване")
        return out
    # the proof: the marker's own movements, and the holders that keep the file held
    holders = await find_holders(tenant, org_id, dict(media, pending_holders=[]))
    proof = {"decision": "confirm" if own else "release",
             "own_movements": [m.get("movement_id") or m.get("id") for m in own],
             "own_scope": {"user": marker.get("user"), "ref": marker.get("ref"),
                           "action": marker.get("action")},
             "other_holders": holders,
             "checked": [h.kind for h in HOLDERS] + ["audit_event"]}

    async def work(session):
        res = await tenant.media_files.update_one(
            {"id": media_id, "org_id": org_id, "pending_holders.id": marker_id},
            {"$pull": {"pending_holders": {"id": marker_id}}, "$inc": {"ref_version": 1}},
            session=session)
        if res.modified_count != 1:
            return {"released": False, "reason": "already_settled"}
        await lifecycle.audit(session, actor, action=action, entity_type="media_file",
                              entity_id=media_id, reason="stale pending holder %s" % outcome,
                              key=key, source_flow="FLOW-029", diff=dict(base, proof=proof))
        return {"released": True, "outcome": outcome, "marker_id": marker_id}

    return await lifecycle.keyed_transaction(actor, key, "media.file.pending_holder_release",
                                             fingerprint, work)


async def settle_shielded(tenant, org_id: str, markers, *, confirmed: bool) -> None:
    """FG-595: ``settle_pending`` in a ``finally`` that a client disconnect or a middleware
    cancel cannot skip (``asyncio.shield``: the settle completes even if the request task is
    cancelled while it runs)."""
    import asyncio
    if markers:
        await asyncio.shield(settle_pending(tenant, org_id, markers, confirmed=confirmed))
