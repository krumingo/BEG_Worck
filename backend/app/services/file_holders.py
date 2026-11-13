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
    if want is None or "audit_event" in want:
        for fn in _FINDERS:
            uses += await fn(tenant, org_id, media, refs, session)
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
