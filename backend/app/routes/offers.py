"""
Routes - Offers / BOQ (M2) Endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Header
from fastapi.responses import StreamingResponse
from typing import Optional
from datetime import datetime, timezone
import uuid
import io
import logging

logger = logging.getLogger(__name__)

from app.db import db
from app.deps.auth import get_current_user
from app.permissions.money_write import require_finance_read, strip_money_for_non_finance
from app.tenancy.data_access import (
    TenantData, assigned_project_ids, is_project_member, resolve_review_token,
)
from app.deps.modules import require_m2
from app.utils.audit import log_audit
from ..models.offers import (
    OFFER_STATUSES, OFFER_UNITS,
    OfferCreate, OfferUpdate, OfferLinesUpdate, OfferReject, OfferAccept, OfferCancel,
    ActivityCatalogCreate, ActivityCatalogUpdate
)

router = APIRouter(tags=["Offers / BOQ"])

# ── Helpers ────────────────────────────────────────────────────────

def _tenant(user: dict) -> TenantData:
    """W0-03E-A1: the session user's tenant view — every record below is read through it."""
    return TenantData.for_user(db, user)


async def can_access_project(user: dict, project_id: str) -> bool:
    """``deps.auth.can_access_project`` semantics, team row honoured only for a
    project of the caller's own tenant (W0-03E-A1)."""
    if user["role"] in ["Admin", "Owner"]:
        return True
    return await is_project_member(_tenant(user), user, project_id)


async def can_manage_project(user: dict, project_id: str) -> bool:
    """``deps.auth.can_manage_project`` semantics, tenant-bound like :func:`can_access_project`."""
    if user["role"] in ["Admin", "Owner"]:
        return True
    if user["role"] == "SiteManager":
        return await is_project_member(_tenant(user), user, project_id, role_in_project="SiteManager")
    return False


async def get_next_offer_no(tenant: TenantData) -> str:
    """Generate sequential offer number like OFF-0001"""
    last = await tenant.offers.find_one(
        {},
        {"_id": 0, "offer_no": 1},
        sort=[("created_at", -1)]
    )
    if last and last.get("offer_no"):
        try:
            num = int(last["offer_no"].split("-")[1]) + 1
        except (ValueError, TypeError) as e:
            logger.warning(f"offers.py parse error: {e}")
            num = 1
    else:
        num = 1
    return f"OFF-{num:04d}"


def compute_offer_line(line: dict) -> dict:
    """Compute line totals"""
    qty = line.get("qty", 0)
    material = line.get("material_unit_cost", 0)
    labor = line.get("labor_unit_cost", 0)
    line["line_material_cost"] = round(qty * material, 2)
    line["line_labor_cost"] = round(qty * labor, 2)
    line["line_total"] = round(line["line_material_cost"] + line["line_labor_cost"], 2)
    return line


def compute_offer_totals(offer: dict) -> dict:
    """Compute offer subtotal, vat, total"""
    lines = offer.get("lines", [])
    subtotal = sum(l.get("line_total", 0) for l in lines)
    vat_percent = offer.get("vat_percent", 0)
    vat_amount = round(subtotal * vat_percent / 100, 2)
    total = round(subtotal + vat_amount, 2)
    offer["subtotal"] = round(subtotal, 2)
    offer["vat_amount"] = vat_amount
    offer["total"] = total
    return offer


async def can_edit_offer(user: dict, offer: dict) -> bool:
    """Check if user can edit offer (must be Draft and have project access)"""
    if offer["status"] != "Draft":
        return False
    return await can_manage_project(user, offer["project_id"])


# ── OFF-01: versions, acceptance, cancellation (FLOW-003, FG-129/FG-130) ──
#
# * A new version supersedes the old one in the SAME transaction as the insert of the
#   new one (``superseded_by``, who, when); the old review link is revoked — kept, never
#   deleted. One conditional write on ``superseded_by: None`` decides the winner, so two
#   new versions of one offer, or a new version and an acceptance, never both succeed.
# * /accept and the public /respond accept only the CURRENT version; the check is the
#   filter of the write itself, inside the transaction that also writes the AuditEvent.
# * A sent offer is never deleted: it is cancelled (status + reason + AuditEvent).
# * Every one of these writes needs an Idempotency-Key (R29 — a contractual action).

STATUS_SUPERSEDED = "Superseded"
STATUS_CANCELLED = "Cancelled"
# Addendum A §2 (FLOW-003 „След приемане … само при ново възлагане/анекс“, FLOW-005): an
# accepted offer gets no new version — the change is an additional offer / annex.
VERSIONABLE_STATUSES = ("Draft", "Sent", "Rejected")
CANCELLABLE_STATUSES = ("Sent", "Rejected", "NeedsRevision")
OFFER_VERSION_SUPERSEDED = "OFFER_VERSION_SUPERSEDED"
OFFER_IN_USE = "OFFER_IN_USE"
PUBLIC_SUPERSEDED_TEXT = ("Тази версия на офертата е заменена с по-нова и вече не може да бъде "
                          "одобрена. Моля, свържете се с изпълнителя за актуалната версия.")
PUBLIC_NOT_OPEN_TEXT = "Тази оферта вече не е активна. Моля, свържете се с изпълнителя."


def _conflict(error_code: str, message: str) -> HTTPException:
    return HTTPException(status_code=409, detail={"error_code": error_code, "message": message})


def _superseded_error() -> HTTPException:
    return _conflict(OFFER_VERSION_SUPERSEDED, PUBLIC_SUPERSEDED_TEXT)


def _is_superseded(offer: dict) -> bool:
    return offer.get("status") == STATUS_SUPERSEDED or bool(offer.get("superseded_by"))


def _link_closed(offer: dict) -> bool:
    return offer.get("review_token_status") == "revoked" or offer.get("status") == STATUS_CANCELLED


def _revoke_link(offer: dict, reason: str, now: str) -> dict:
    """The fields that close the offer's review link (the token itself is kept)."""
    if not offer.get("review_token") or offer.get("review_token_status") == "revoked":
        return {}
    return {"review_token_status": "revoked", "review_token_revoked_at": now,
            "review_token_revoked_reason": reason}


async def _draft_was_used(tenant: TenantData, offer: dict) -> bool:
    """A draft that was ever sent, or that is a new version of a sent offer, is a used
    record (FG-130): it is never deleted."""
    if offer.get("sent_at") or offer.get("review_token") or offer.get("parent_offer_id") \
            or offer.get("superseded_by"):
        return True
    return bool(await tenant.offer_events.find_one(
        {"offer_id": offer["id"], "event_type": "sent"}, {"_id": 0, "id": 1}))


async def _check_evidence_file(tenant: TenantData, offer: dict, file_id: str) -> None:
    """Addendum A §3 (CLAUDE.md §2.6): the evidence of an acceptance is a file of THIS tenant,
    linked to this offer's project or not linked yet — otherwise 422, nothing written.
    The store is ``media_files``: the canonical File Registry (W0-06) is not built yet
    (debt D-OFF01-12)."""
    media = await tenant.media_files.get(file_id, {"_id": 0, "id": 1, "context_type": 1,
                                                   "context_id": 1})
    if not media:
        raise HTTPException(status_code=422, detail={
            "error_code": "EVIDENCE_FILE_NOT_FOUND",
            "message": "Файлът-доказателство не е намерен в тази фирма"})
    ctype, cid = media.get("context_type"), media.get("context_id")
    if cid and not (ctype == "project" and cid == offer.get("project_id")):
        raise HTTPException(status_code=422, detail={
            "error_code": "EVIDENCE_FILE_NOT_LINKABLE",
            "message": "Файлът-доказателство е свързан с друг запис"})


# OFF79-03: every write to a draft carries "still an unsent draft" in its own filter, so a
# read-then-write can never race /send (the loser gets 409, nothing written).
DRAFT_FILTER = {"status": "Draft", "sent_at": None, "superseded_by": None}


def _draft_lost() -> HTTPException:
    return _conflict(OFFER_IN_USE, "Офертата вече е изпратена или променена — презаредете")


async def _has_newer_version(tenant: TenantData, offer: dict, session=None) -> bool:
    """FG-135: a version that has a newer version (a child) in its family is replaced, even
    when a legacy row (linked before OFF-01) was never marked superseded. Read only — the
    legacy rows are not migrated."""
    kw = {} if session is None else {"session": session}
    return bool(await tenant.offers.find_one({"parent_offer_id": offer["id"]},
                                             {"_id": 0, "id": 1}, **kw))


async def _family_guard(tenant: TenantData, offer: dict, session) -> None:
    """Legacy pairs (linked before OFF-01, the older one never marked superseded): no version
    is accepted while another version of the same family is Accepted → 409
    OFFER_FAMILY_ALREADY_ACCEPTED. The family is the ``parent_offer_id`` chain. A write to
    the family's root makes two concurrent acceptances of one family conflict, so the
    check-then-accept inside the transaction cannot be skewed."""
    proj = {"_id": 0, "id": 1, "parent_offer_id": 1, "status": 1}
    root, seen = offer, {offer["id"]}
    for _ in range(100):                       # walk up to the root
        pid = root.get("parent_offer_id")
        if not pid or pid in seen:
            break
        parent = await tenant.offers.get(pid, proj, session=session)
        if not parent:
            break
        seen.add(pid)
        root = parent
    family, frontier = {root["id"]: root}, [root["id"]]
    while frontier and len(family) < 500:      # and down to every version
        kids = await tenant.offers.find({"parent_offer_id": {"$in": frontier}}, proj,
                                        session=session).to_list(500)
        frontier = [k["id"] for k in kids if k["id"] not in family]
        family.update({k["id"]: k for k in kids})
    await tenant.offers.update_one({"id": root["id"]}, {"$inc": {"family_accept_guard": 1}},
                                   session=session)
    if any(k.get("parent_offer_id") == offer["id"] for k in family.values()):
        raise _superseded_error()                   # FG-135: it has a newer version
    if any(v.get("status") == "Accepted" for k, v in family.items() if k != offer["id"]):
        raise _conflict("OFFER_FAMILY_ALREADY_ACCEPTED",
                        "Друга версия на тази оферта вече е одобрена. Моля, свържете се с изпълнителя.")


def _exact(value) -> "Decimal":
    """A stored number as the decimal the user entered (``repr`` of a float is its shortest
    round-trip form: 7.345 → Decimal('7.345'), never 7.34499999…)."""
    from decimal import Decimal
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value or 0))


def client_unit_price(line: dict) -> "Decimal":
    """Codex F-79-01: the combined contract unit price — the EXACT sum of the internal
    components, never rounded (12.345 stays 12.345, so 100 × it is the line value 1234.50)."""
    return _exact(line.get("material_unit_cost", 0)) + _exact(line.get("labor_unit_cost", 0))


def price_text(value: "Decimal") -> str:
    """At least 2 decimals and as many more as the exact price has (trailing zeros trimmed):
    12.345 → "12.345", 0.3 → "0.30", 100 → "100.00"."""
    text = format(value, "f")
    whole, _, frac = text.partition(".")
    frac = frac.rstrip("0")
    return "%s.%s" % (whole, frac.ljust(2, "0"))


def qty_text(qty) -> str:
    """The exact quantity for the client document, at least 1 decimal (the PDF's old style):
    2.25 → "2.25" (it was "2.2"), 100 → "100.0"."""
    text = format(_exact(qty), "f")
    whole, _, frac = text.partition(".")
    return "%s.%s" % (whole, frac.rstrip("0").ljust(1, "0"))


def client_line(line: dict) -> dict:
    """R43 (Krum, 07.11.2026; FLOW-003, FLOW-010): what a CLIENT sees of an offer line — the
    combined unit price, quantity and value. The material/labour split is internal.
    F-79-01: the price is exact (``unit_price`` number + ``unit_price_text`` for display);
    the stored line value is shown as it was sent, never re-fitted to a rounded price."""
    from decimal import Decimal
    qty = line.get("qty", 0) or 0
    unit = client_unit_price(line)
    total = line.get("line_total")
    if total is None:
        total = float((_exact(qty) * unit).quantize(Decimal("0.01")))
    return {"id": line.get("id"), "activity_name": line.get("activity_name"),
            "unit": line.get("unit"), "qty": qty, "unit_price": float(unit),
            "unit_price_text": price_text(unit), "line_total": total,
            "note": line.get("note"), "sort_order": line.get("sort_order")}


def _state_changed() -> HTTPException:
    """FG-144: the loser of a status-transition race → 409, never a silent overwrite."""
    return _conflict("OFFER_STATE_CHANGED",
                     "Офертата беше променена от друга заявка — презаредете и опитайте отново")


def _require_key(header: Optional[str]) -> str:
    """R29: the PAY-01 rule, reused — no key → 428 before anything is written."""
    from app.routes.finance import _require_key as require_key
    return require_key(header)


async def _once(org_id: str, key: str, action: str, fingerprint: dict, work):
    """The PAY-01 W0-04 idempotency wrapper, reused (one result per tenant/action/key)."""
    from app.routes.finance import _once as once
    return await once({"org_id": org_id}, key, action, fingerprint, work)


from app.services.offer_txn import MAX_TXN_ATTEMPTS, ensure_offer_collections  # OFF79-05


async def _in_transaction(body):
    """``auth_tx.run_in_transaction``; a deployment without transactions → 503, nothing
    written. The collections are ensured first (OFF79-05), and an error the server labels
    TransientTransactionError that escaped the driver's own retry is retried, bounded."""
    from pymongo.errors import PyMongoError
    from app.services.auth_tx import TransactionsUnavailable, run_in_transaction, transactions_supported
    unavailable = HTTPException(status_code=503, detail={
        "error_code": "TRANSACTIONS_UNAVAILABLE",
        "message": "Записът изисква транзакция, а базата не я поддържа — нищо не е записано"})
    if not await transactions_supported(db):
        raise unavailable
    await ensure_offer_collections(db)
    for attempt in range(MAX_TXN_ATTEMPTS):
        try:
            return await run_in_transaction(db, body)
        except TransactionsUnavailable:
            raise unavailable
        except PyMongoError as exc:
            if exc.has_error_label("TransientTransactionError") and attempt < MAX_TXN_ATTEMPTS - 1:
                continue
            raise


async def _offer_event(session, *, tenant_id: str, actor_type: str, actor_id: str, action: str,
                       offer: dict, diff: dict, idem_key: str, reason: Optional[str] = None,
                       roles=None, channel: str = "api", endpoint: Optional[str] = None,
                       file_ids=None) -> None:
    """Canonical W0-04 AuditEvent of an offer decision, in the business transaction."""
    from app.audit.envelope import RETENTION_R1_CRITICAL_BUSINESS, build_event
    from app.audit.store import record_event
    event = build_event(
        tenant_id=tenant_id, actor_type=actor_type, actor_id=actor_id, action=action,
        source_flow="FLOW-003", retention_class=RETENTION_R1_CRITICAL_BUSINESS,
        entity_type="offer", entity_id=offer["id"], entity_version=str(offer.get("version", 1)),
        scope_type="project", scope_id=offer.get("project_id"),
        structured_diff=diff, reason=reason, source_channel=channel, tool_or_endpoint=endpoint,
        idempotency_key=idem_key, related_file_ids=file_ids or None,
        effective_role_assignments=roles,
    )
    await record_event(db, event, session=session)


# ── Offer CRUD ─────────────────────────────────────────────────────

@router.post("/offers", status_code=201)
async def create_offer(data: OfferCreate, user: dict = Depends(require_m2)):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    project = await _tenant(user).projects.get(data.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not await can_manage_project(user, data.project_id):
        raise HTTPException(status_code=403, detail="Not authorized for this project")
    
    now = datetime.now(timezone.utc).isoformat()
    offer_no = await get_next_offer_no(_tenant(user))
    
    lines = []
    for i, line in enumerate(data.lines):
        l = {
            "id": str(uuid.uuid4()),
            "activity_code": line.activity_code,
            "activity_name": line.activity_name,
            "unit": line.unit,
            "qty": line.qty,
            "material_unit_cost": line.material_unit_cost,
            "labor_unit_cost": line.labor_unit_cost,
            "labor_hours_per_unit": line.labor_hours_per_unit,
            "note": line.note,
            "sort_order": line.sort_order or i,
            "activity_type": line.activity_type or "Общо",
            "activity_subtype": line.activity_subtype or "",
        }
        lines.append(compute_offer_line(l))
    
    offer = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "project_id": data.project_id,
        "offer_no": offer_no,
        "title": data.title,
        "status": "Draft",
        "version": 1,
        "parent_offer_id": None,
        "currency": data.currency,
        "vat_percent": data.vat_percent,
        "lines": lines,
        "notes": data.notes,
        "created_at": now,
        "updated_at": now,
        "sent_at": None,
        "accepted_at": None,
    }
    offer = compute_offer_totals(offer)
    
    await _tenant(user).offers.insert_one(offer)
    await log_audit(user["org_id"], user["id"], user["email"], "offer_created", "offer", offer["id"], 
                    {"offer_no": offer_no, "title": data.title, "project_id": data.project_id})
    
    return {k: v for k, v in offer.items() if k != "_id"}


@router.get("/offers")
@strip_money_for_non_finance   # SEC-02-A (R20-5M, D1)
async def list_offers(
    user: dict = Depends(require_m2),
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
):
    tenant = _tenant(user)
    query = {}
    
    if project_id:
        if not await can_access_project(user, project_id):
            raise HTTPException(status_code=403, detail="Access denied to project")
        query["project_id"] = project_id
    elif user["role"] not in ["Admin", "Owner", "Accountant"]:
        # Limit to assigned projects
        assigned = await assigned_project_ids(tenant, user)
        query["project_id"] = {"$in": assigned}
    
    if status:
        query["status"] = status
    
    offers = await tenant.offers.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    
    if search:
        s = search.lower()
        offers = [o for o in offers if s in o.get("offer_no", "").lower() or s in o.get("title", "").lower()]
    
    # Enrich with project info — the caller's tenant only (W0-03E-R1/A1)
    projects_by_id = await tenant.projects.get_many(
        (o.get("project_id") for o in offers), {"_id": 0, "code": 1, "name": 1})
    for o in offers:
        p = projects_by_id.get(o.get("project_id"))
        o["project_code"] = p.get("code", "") if p else ""
        o["project_name"] = p.get("name", "") if p else ""
        o["line_count"] = len(o.get("lines", []))
    
    return offers


@router.get("/offers/{offer_id}")
@strip_money_for_non_finance   # SEC-02-A (R20-5M, D1)
async def get_offer(offer_id: str, user: dict = Depends(require_m2)):
    offer = await _tenant(user).offers.get(offer_id, {"_id": 0})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if not await can_access_project(user, offer["project_id"]):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Enrich
    p = await _tenant(user).projects.get(offer.get("project_id"), {"_id": 0, "code": 1, "name": 1})
    offer["project_code"] = p.get("code", "") if p else ""
    offer["project_name"] = p.get("name", "") if p else ""
    
    return offer


@router.put("/offers/{offer_id}")
@strip_money_for_non_finance   # SEC-02-E (R20-5M, sweep)
async def update_offer(offer_id: str, data: OfferUpdate, user: dict = Depends(require_m2)):
    offer = await _tenant(user).offers.get(offer_id)
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if not await can_edit_offer(user, offer):
        raise HTTPException(status_code=403, detail="Can only edit Draft offers you manage")
    
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    # OFF79-04: the totals are derived BEFORE the write, from the lines as read, and written
    # with the header in ONE CAS on the draft as read (Draft filter + updated_at). Before,
    # the VAT and the totals were two writes and a /send in between sent a VAT 9 offer at
    # the VAT 20 total. A lost race → 409, nothing written.
    merged = compute_offer_totals({**{k: v for k, v in offer.items() if k != "_id"}, **update})
    update.update({"subtotal": merged["subtotal"], "vat_amount": merged["vat_amount"],
                   "total": merged["total"]})
    won = await _tenant(user).offers.update_one(
        {"id": offer_id, **DRAFT_FILTER, "updated_at": offer.get("updated_at")}, {"$set": update})
    if won.matched_count != 1:
        raise _draft_lost()
    
    await log_audit(user["org_id"], user["id"], user["email"], "offer_updated", "offer", offer_id, update)
    return await _tenant(user).offers.get(offer_id, {"_id": 0})


@router.put("/offers/{offer_id}/lines")
async def update_offer_lines(offer_id: str, data: OfferLinesUpdate, user: dict = Depends(require_m2)):
    offer = await _tenant(user).offers.get(offer_id)
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if not await can_edit_offer(user, offer):
        raise HTTPException(status_code=403, detail="Can only edit Draft offers you manage")
    
    lines = []
    for i, line in enumerate(data.lines):
        l = {
            "id": str(uuid.uuid4()),
            "activity_code": line.activity_code,
            "activity_name": line.activity_name,
            "unit": line.unit,
            "qty": line.qty,
            "material_unit_cost": line.material_unit_cost,
            "labor_unit_cost": line.labor_unit_cost,
            "labor_hours_per_unit": line.labor_hours_per_unit,
            "note": line.note,
            "sort_order": line.sort_order or i,
            "activity_type": line.activity_type or "Общо",
            "activity_subtype": line.activity_subtype or "",
        }
        lines.append(compute_offer_line(l))
    
    now = datetime.now(timezone.utc).isoformat()
    updated = {
        "lines": lines,
        "updated_at": now,
    }
    
    # Compute totals
    offer["lines"] = lines
    offer["vat_percent"] = offer.get("vat_percent", 0)
    offer = compute_offer_totals(offer)
    updated["subtotal"] = offer["subtotal"]
    updated["vat_amount"] = offer["vat_amount"]
    updated["total"] = offer["total"]
    
    # OFF79-04: the totals come from these lines and the VAT as read — one CAS on that draft
    won = await _tenant(user).offers.update_one(
        {"id": offer_id, **DRAFT_FILTER, "updated_at": offer.get("updated_at")}, {"$set": updated})
    if won.matched_count != 1:
        raise _draft_lost()
    await log_audit(user["org_id"], user["id"], user["email"], "offer_lines_updated", "offer", offer_id, 
                    {"line_count": len(lines)})
    
    return await _tenant(user).offers.get(offer_id, {"_id": 0})


@router.post("/offers/{offer_id}/send")
@strip_money_for_non_finance   # SEC-02-E (R20-5M, sweep)
async def send_offer(offer_id: str, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    offer = await _tenant(user).offers.get(offer_id)
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if not await can_manage_project(user, offer["project_id"]):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if offer["status"] not in ["Draft"]:
        raise HTTPException(status_code=400, detail="Only Draft offers can be sent")
    if len(offer.get("lines", [])) == 0:
        raise HTTPException(status_code=400, detail="Offer must have at least one line")
    
    now = datetime.now(timezone.utc).isoformat()
    review_token = offer.get("review_token") or str(uuid.uuid4()).replace("-", "")[:24]
    
    # OFF79-03 / FG-144 sweep: the send is a CAS on the exact draft that was read (status,
    # never sent, not superseded, same updated_at), in ONE transaction with the snapshot of
    # what was sent, the events and the canonical AuditEvent. A restore / edit / delete that
    # slipped in → 409, nothing sent.
    async def body(session):
        won = await tenant.offers.update_one(
            {"id": offer_id, **DRAFT_FILTER, "updated_at": offer.get("updated_at")}, {"$set": {
                "status": "Sent", "sent_at": now, "sent_by": user["id"],
                "review_token": review_token, "updated_at": now,
                # OFF-01: the link is bound to this offer id + this exact version
                "review_token_version": offer.get("version", 1),
            }}, session=session)
        if won.modified_count != 1:
            raise _conflict("OFFER_CHANGED",
                            "Офертата беше променена докато се изпращаше — презаредете и изпратете отново")
        last_ver = await tenant.offer_versions.find_one(
            {"org_id": user["org_id"], "offer_id": offer_id}, sort=[("version_number", -1)],
            session=session)
        version_number = (last_ver["version_number"] + 1) if last_ver else 1
        snapshot = {
            "offer_no": offer.get("offer_no"), "title": offer.get("title"),
            "status": "Sent", "version": offer.get("version"),
            "currency": offer.get("currency"), "vat_percent": offer.get("vat_percent"),
            "notes": offer.get("notes"), "lines": offer.get("lines", []),
            "subtotal": offer.get("subtotal"), "vat_amount": offer.get("vat_amount"),
            "total": offer.get("total"),
        }
        await tenant.offer_versions.insert_one({
            "id": str(uuid.uuid4()), "org_id": user["org_id"],
            "project_id": offer["project_id"], "offer_id": offer_id,
            "version_number": version_number, "created_at": now,
            "created_by": user["id"], "note": "Автоматичен snapshot при изпращане",
            "snapshot_json": snapshot, "is_auto_backup": True,
        }, session=session)
        await tenant.offer_events.insert_one({
            "id": str(uuid.uuid4()), "org_id": user["org_id"],
            "offer_id": offer_id, "event_type": "sent",
            "actor": user["email"], "created_at": now,
            "details": {"sent_by": user["id"]},
        }, session=session)
        await log_audit(user["org_id"], user["id"], user["email"], "offer_sent", "offer", offer_id,
                        {"offer_no": offer["offer_no"]}, db_handle=db, session=session)
        await _offer_event(
            session, tenant_id=user["org_id"], actor_type="human", actor_id=user["id"],
            action="offers.offer.sent", offer=offer, idem_key=None,
            roles=[user.get("role") or ""], endpoint="POST /api/offers/{offer_id}/send",
            diff={"status": {"before": "Draft", "after": "Sent"}, "version": offer.get("version", 1),
                  "total": offer.get("total"), "snapshot_version_number": version_number})

    await _in_transaction(body)

    result = await _tenant(user).offers.get(offer_id, {"_id": 0})
    if not result:                       # FG-136: never a 500 — only a delete could do this
        raise _conflict("OFFER_CHANGED", "Офертата беше изтрита междувременно")
    result["review_url"] = f"/offers/review/{review_token}"
    return result


@router.post("/offers/{offer_id}/accept")
async def accept_offer(offer_id: str, data: Optional[OfferAccept] = None,
                       user: dict = Depends(require_m2),
                       idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """Internal acceptance of the CURRENT version (OFF-01). A superseded version → 409
    OFFER_VERSION_SUPERSEDED; the check is the filter of the write, in the transaction."""
    tenant = _tenant(user)
    offer = await tenant.offers.get(offer_id)
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner can accept offers")
    key = _require_key(idempotency_key)
    data = data or OfferAccept()
    version = offer.get("version", 1)
    # FG-137 (FLOW-003 Interim Approval Receipt): a carrier named is a carrier proven
    if data.approval_method == "signed_pdf" and not data.evidence_file_id:
        raise HTTPException(status_code=422, detail={
            "error_code": "EVIDENCE_FILE_REQUIRED",
            "message": "Подписаният PDF трябва да е приложен като файл"})
    if data.approval_method == "verified_email":
        # needs a verified client address and an e-mail that cites offer id + version; the
        # model for either does not exist yet (debt D-OFF01-14) → never accepted unproven
        raise HTTPException(status_code=422, detail={
            "error_code": "VERIFIED_EMAIL_NOT_SUPPORTED",
            "message": "Одобрение с верифициран имейл още не се поддържа — приложете подписан PDF"})

    async def work():
        # inside the key: a replay of a completed key returns its first result instead
        if _is_superseded(offer) or await _has_newer_version(tenant, offer):
            raise _superseded_error()
        if offer["status"] != "Sent":
            raise HTTPException(status_code=400, detail="Only Sent offers can be accepted")
        if data.evidence_file_id:
            await _check_evidence_file(tenant, offer, data.evidence_file_id)

        async def body(session):
            from pymongo import ReturnDocument
            now = datetime.now(timezone.utc).isoformat()
            await _family_guard(tenant, offer, session)
            approval = {"method": data.approval_method, "channel": "internal",
                        "evidence_file_id": data.evidence_file_id, "note": data.note,
                        "version": version, "accepted_by": user["id"], "accepted_at": now}
            done = await tenant.offers.find_one_and_update(
                {"id": offer_id, "status": "Sent", "superseded_by": None, "version": version},
                {"$set": {"status": "Accepted", "accepted_at": now, "accepted_by": user["id"],
                          "approval": approval, "updated_at": now}},
                projection={"_id": 0}, return_document=ReturnDocument.AFTER, session=session)
            if not done:
                current = await tenant.offers.get(offer_id, {"_id": 0}, session=session) or {}
                if _is_superseded(current):
                    raise _superseded_error()
                raise _state_changed()        # FG-144: loser → 409
            await log_audit(user["org_id"], user["id"], user["email"], "offer_accepted", "offer",
                            offer_id, {"offer_no": offer["offer_no"], "total": offer.get("total", 0),
                                       "version": version},
                            db_handle=db, session=session)
            await _offer_event(
                session, tenant_id=user["org_id"], actor_type="human", actor_id=user["id"],
                action="offers.offer.accepted", offer=done, idem_key=key,
                roles=[user.get("role") or ""], endpoint="POST /api/offers/{offer_id}/accept",
                file_ids=[data.evidence_file_id] if data.evidence_file_id else None,
                diff={"status": {"before": "Sent", "after": "Accepted"}, "version": version,
                      "approval_method": data.approval_method,
                      "evidence_file_id": data.evidence_file_id,
                      "total": done.get("total"), "currency": done.get("currency")})
            return done
        return await _in_transaction(body)

    return await _once(user["org_id"], key, "offers.offer.accept",
                       {"offer_id": offer_id, **data.model_dump()}, work)


@router.post("/offers/{offer_id}/reject")
async def reject_offer(offer_id: str, data: OfferReject, user: dict = Depends(require_m2),
                       idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """Internal rejection of the CURRENT version. FG-144: one transaction — a CAS on
    status Sent + version + not superseded, the canonical AuditEvent with the reason; a
    concurrent client approval (or any other transition) that won → 409."""
    tenant = _tenant(user)
    offer = await tenant.offers.get(offer_id)
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner can reject offers")
    key = _require_key(idempotency_key)
    reason = (data.reason or "").strip() or None
    if reason:
        from app.services.money_amount import check_reason
        check_reason(reason)
    version = offer.get("version", 1)

    async def work():
        if _is_superseded(offer) or await _has_newer_version(tenant, offer):
            raise _superseded_error()
        if offer["status"] != "Sent":
            raise HTTPException(status_code=400, detail="Only Sent offers can be rejected")

        async def body(session):
            from pymongo import ReturnDocument
            if await _has_newer_version(tenant, offer, session):
                raise _superseded_error()
            now = datetime.now(timezone.utc).isoformat()
            done = await tenant.offers.find_one_and_update(
                {"id": offer_id, "status": "Sent", "superseded_by": None, "version": version},
                {"$set": {"status": "Rejected", "reject_reason": reason, "rejected_by": user["id"],
                          "rejected_at": now, "updated_at": now}},
                projection={"_id": 0}, return_document=ReturnDocument.AFTER, session=session)
            if not done:
                raise _state_changed()
            await log_audit(user["org_id"], user["id"], user["email"], "offer_rejected", "offer",
                            offer_id, {"offer_no": offer["offer_no"], "reason": reason},
                            db_handle=db, session=session)
            await _offer_event(
                session, tenant_id=user["org_id"], actor_type="human", actor_id=user["id"],
                action="offers.offer.rejected", offer=done, idem_key=key, reason=reason,
                roles=[user.get("role") or ""], endpoint="POST /api/offers/{offer_id}/reject",
                diff={"status": {"before": "Sent", "after": "Rejected"}, "version": version})
            return done
        return await _in_transaction(body)

    return await _once(user["org_id"], key, "offers.offer.reject",
                       {"offer_id": offer_id, "reason": reason}, work)


@router.post("/offers/{offer_id}/new-version")
async def create_offer_version(offer_id: str, user: dict = Depends(require_m2),
                               idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """A new version (Draft) of a non-draft offer. OFF-01: the old version is superseded
    and its review link revoked in the same transaction as the insert of the new one."""
    tenant = _tenant(user)
    offer = await tenant.offers.get(offer_id)
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if not await can_manage_project(user, offer["project_id"]):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    key = _require_key(idempotency_key)
    seen_status = offer["status"]
    new_version = offer.get("version", 1) + 1

    async def work():
        if _is_superseded(offer) or await _has_newer_version(tenant, offer):
            raise _superseded_error()
        if seen_status == "Accepted":
            raise _conflict("OFFER_ACCEPTED_USE_ANNEX",
                            "Приета оферта не се променя с нова версия — направете допълнителна "
                            "оферта или анекс")
        if seen_status not in VERSIONABLE_STATUSES:
            raise HTTPException(status_code=400, detail="Can only version Draft, Sent or Rejected offers")

        async def body(session):
            now = datetime.now(timezone.utc).isoformat()
            new_id = str(uuid.uuid4())
            # the old version is replaced and any approval on it is void (FLOW-003
            # „invalidation на approval при нова версия“) — never two accepted versions
            mark = {"superseded_by": new_id, "superseded_at": now,
                    "superseded_by_user": user["id"], "updated_at": now,
                    "status": STATUS_SUPERSEDED, "status_before_supersede": seen_status,
                    **_revoke_link(offer, "superseded", now)}
            won = await tenant.offers.update_one(
                # OFF79-04: the same draft/offer as read — the new version copies its lines
                # and totals, so an edit in between must make this CAS fail
                {"id": offer_id, "status": seen_status, "superseded_by": None,
                 "updated_at": offer.get("updated_at")},
                {"$set": mark}, session=session)
            if won.modified_count != 1:
                current = await tenant.offers.get(offer_id, {"_id": 0}, session=session) or {}
                if _is_superseded(current):
                    raise _superseded_error()
                raise _conflict("OFFER_STATE_CHANGED",
                                "Офертата беше променена от друга заявка — презаредете и опитайте отново")
            if await _has_newer_version(tenant, offer, session):
                raise _superseded_error()            # a legacy child: one head per chain
            new_lines = []
            for line in offer.get("lines", []):
                l = {k: v for k, v in line.items() if k != "_id"}
                l["id"] = str(uuid.uuid4())
                new_lines.append(l)
            new_offer = {
                "id": new_id,
                "org_id": user["org_id"],
                "project_id": offer["project_id"],
                "offer_no": offer["offer_no"],  # Keep same offer_no
                "title": offer["title"],
                "status": "Draft",
                "version": new_version,
                "parent_offer_id": offer["id"],
                "currency": offer["currency"],
                "vat_percent": offer["vat_percent"],
                "lines": new_lines,
                "subtotal": offer["subtotal"],
                "vat_amount": offer["vat_amount"],
                "total": offer["total"],
                "notes": offer.get("notes", ""),
                "created_at": now,
                "updated_at": now,
                "sent_at": None,
                "accepted_at": None,
            }
            await tenant.offers.insert_one(new_offer, session=session)
            new_offer.pop("_id", None)
            await log_audit(user["org_id"], user["id"], user["email"], "offer_versioned", "offer",
                            new_id, {"offer_no": offer["offer_no"], "version": new_version,
                                     "from_version": offer.get("version", 1)},
                            db_handle=db, session=session)
            await _offer_event(
                session, tenant_id=user["org_id"], actor_type="human", actor_id=user["id"],
                action="offers.offer.superseded", offer=offer, idem_key=key,
                roles=[user.get("role") or ""], endpoint="POST /api/offers/{offer_id}/new-version",
                diff={"status": {"before": seen_status, "after": STATUS_SUPERSEDED},
                      "superseded_by": new_id, "new_version": new_version,
                      "review_link_revoked": bool(mark.get("review_token_status"))})
            return new_offer
        return await _in_transaction(body)

    return await _once(user["org_id"], key, "offers.offer.new_version", {"offer_id": offer_id}, work)


@router.post("/offers/{offer_id}/cancel")
async def cancel_offer(offer_id: str, data: Optional[OfferCancel] = None,
                       user: dict = Depends(require_m2),
                       idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """OFF-01 (FG-130): a sent offer is withdrawn, never deleted — status Cancelled, the
    reason, who and when, its review link revoked, a canonical AuditEvent."""
    tenant = _tenant(user)
    offer = await tenant.offers.get(offer_id)
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner can cancel offers")
    key = _require_key(idempotency_key)
    reason = ((data.reason if data else None) or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail={
            "error_code": "REASON_REQUIRED", "message": "Посочете причина за анулирането"})
    from app.services.money_amount import check_reason
    check_reason(reason)
    seen_status = offer["status"]

    async def work():
        cancellable = seen_status in CANCELLABLE_STATUSES or (
            seen_status == "Draft" and await _draft_was_used(tenant, offer))
        if _is_superseded(offer) or not cancellable:
            raise _conflict("OFFER_NOT_CANCELLABLE",
                            "Тази оферта не може да бъде анулирана в състояние %s" % seen_status)

        async def body(session):
            from pymongo import ReturnDocument
            now = datetime.now(timezone.utc).isoformat()
            done = await tenant.offers.find_one_and_update(
                {"id": offer_id, "status": seen_status, "superseded_by": None},
                {"$set": {"status": STATUS_CANCELLED, "status_before_cancel": seen_status,
                          "cancel_reason": reason, "cancelled_by": user["id"],
                          "cancelled_at": now, "updated_at": now,
                          **_revoke_link(offer, "cancelled", now)}},
                projection={"_id": 0}, return_document=ReturnDocument.AFTER, session=session)
            if not done:
                raise _conflict("OFFER_NOT_CANCELLABLE",
                                "Офертата беше променена от друга заявка — презаредете")
            await log_audit(user["org_id"], user["id"], user["email"], "offer_cancelled", "offer",
                            offer_id, {"offer_no": offer["offer_no"], "reason": reason},
                            db_handle=db, session=session)
            await _offer_event(
                session, tenant_id=user["org_id"], actor_type="human", actor_id=user["id"],
                action="offers.offer.cancelled", offer=done, idem_key=key, reason=reason,
                roles=[user.get("role") or ""], endpoint="POST /api/offers/{offer_id}/cancel",
                diff={"status": {"before": seen_status, "after": STATUS_CANCELLED},
                      "review_link_revoked": bool(offer.get("review_token"))})
            return done
        return await _in_transaction(body)

    return await _once(user["org_id"], key, "offers.offer.cancel",
                       {"offer_id": offer_id, "reason": reason}, work)


@router.delete("/offers/{offer_id}")
async def delete_offer(offer_id: str, user: dict = Depends(require_m2)):
    """Only a draft that was never sent (and is not a version of a sent offer) is removed.
    OFF-01 (FG-130): anything else → 409 OFFER_IN_USE; cancel it instead."""
    tenant = _tenant(user)
    offer = await tenant.offers.get(offer_id)
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner can delete offers")
    if offer["status"] != "Draft" or await _draft_was_used(tenant, offer):
        raise _conflict(OFFER_IN_USE, "Изпратена или използвана оферта не се изтрива — анулирайте я")
    
    # FG-136: the delete is itself conditional on "an unsent, unlinked draft, as read" — one
    # atomic single-document operation, so a /send that won in between makes it match nothing
    gone = await tenant.offers.delete_one({
        "id": offer_id, **DRAFT_FILTER, "review_token": None, "parent_offer_id": None,
        "updated_at": offer.get("updated_at")})
    if gone.deleted_count != 1:
        raise _conflict(OFFER_IN_USE, "Изпратена или използвана оферта не се изтрива — анулирайте я")
    await log_audit(user["org_id"], user["id"], user["email"], "offer_deleted", "offer", offer_id,
                    {"offer_no": offer["offer_no"]})
    return {"ok": True}


# ── Activity Catalog CRUD ──────────────────────────────────────────

@router.get("/activity-catalog")
async def list_activity_catalog(
    user: dict = Depends(require_m2),
    project_id: Optional[str] = None,
    active_only: bool = True,
):
    query = {}
    if project_id:
        if not await can_access_project(user, project_id):
            raise HTTPException(status_code=403, detail="Access denied")
        query["project_id"] = project_id
    if active_only:
        query["active"] = True
    
    items = await _tenant(user).activity_catalog.find(query, {"_id": 0}).sort("name", 1).to_list(500)
    return items


@router.post("/activity-catalog", status_code=201)
async def create_activity(data: ActivityCatalogCreate, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    project = await _tenant(user).projects.get(data.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not await can_manage_project(user, data.project_id):
        raise HTTPException(status_code=403, detail="Not authorized for this project")
    
    now = datetime.now(timezone.utc).isoformat()
    item = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "project_id": data.project_id,
        "code": data.code,
        "name": data.name,
        "default_unit": data.default_unit,
        "default_material_unit_cost": data.default_material_unit_cost,
        "default_labor_unit_cost": data.default_labor_unit_cost,
        "default_labor_hours_per_unit": data.default_labor_hours_per_unit,
        "active": data.active,
        "created_at": now,
        "updated_at": now,
    }
    await tenant.activity_catalog.insert_one(item)
    return {k: v for k, v in item.items() if k != "_id"}


@router.put("/activity-catalog/{item_id}")
async def update_activity(item_id: str, data: ActivityCatalogUpdate, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    item = await tenant.activity_catalog.find_one({"id": item_id, "org_id": user["org_id"]})
    if not item:
        raise HTTPException(status_code=404, detail="Activity not found")
    if not await can_manage_project(user, item["project_id"]):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    await tenant.activity_catalog.update_one({"id": item_id, "org_id": user["org_id"]}, {"$set": update})
    return await tenant.activity_catalog.find_one({"id": item_id, "org_id": user["org_id"]}, {"_id": 0})


@router.delete("/activity-catalog/{item_id}")
async def delete_activity(item_id: str, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    item = await tenant.activity_catalog.find_one({"id": item_id, "org_id": user["org_id"]})
    if not item:
        raise HTTPException(status_code=404, detail="Activity not found")
    if not await can_manage_project(user, item["project_id"]):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    await tenant.activity_catalog.delete_one({"id": item_id, "org_id": user["org_id"]})
    return {"ok": True}


@router.get("/offer-enums")
async def get_offer_enums():
    return {
        "statuses": OFFER_STATUSES,
        "units": OFFER_UNITS,
    }


# ── Offer Export (PDF + XLSX) ──────────────────────────────────────

UNIT_LABELS_BG = {"m2": "м2", "m": "м", "pcs": "бр", "hours": "часа", "lot": "к-т", "kg": "кг", "l": "л"}
STATUS_LABELS_BG = {"Draft": "Чернова", "Sent": "Изпратена", "Accepted": "Одобрена", "Rejected": "Отказана", "NeedsRevision": "Корекция", "Archived": "Архивирана", "Superseded": "Заменена", "Cancelled": "Анулирана"}

@router.get("/offers/{offer_id}/pdf")
async def export_offer_pdf(
    offer_id: str,
    _sec02: dict = Depends(require_finance_read(
        "finance.offer_document.export", module="M2", resource_type="offer_document")),  # SEC-02 (R20-2): before any read
    user: dict = Depends(require_m2)):
    """Export offer as PDF"""
    offer = await _tenant(user).offers.get(offer_id, {"_id": 0})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    
    org = await _tenant(user).own_organization({"_id": 0})
    # W0-03E-R1: the related project must be the caller's own (org from the
    # authenticated session, never the request). A project_id that resolves only
    # in another org exports no project at all — never that org's code or name.
    project = await _tenant(user).projects.get(
        offer.get("project_id"), {"_id": 0, "code": 1, "name": 1, "address_text": 1})
    
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table as RLTable, TableStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        raise HTTPException(status_code=500, detail="reportlab not installed")
    
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVuBold', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'))
        fn, fb = 'DejaVu', 'DejaVuBold'
    except Exception:
        fn, fb = 'Helvetica', 'Helvetica-Bold'
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=20*mm, bottomMargin=15*mm, leftMargin=15*mm, rightMargin=15*mm)
    styles = getSampleStyleSheet()
    sTitle = ParagraphStyle('T', parent=styles['Title'], fontName=fb, fontSize=16, textColor=colors.HexColor('#333'))
    sH2 = ParagraphStyle('H', parent=styles['Heading2'], fontName=fb, fontSize=11, textColor=colors.HexColor('#555'))
    sN = ParagraphStyle('N', parent=styles['Normal'], fontName=fn, fontSize=9, leading=13)
    sS = ParagraphStyle('S', parent=styles['Normal'], fontName=fn, fontSize=8, textColor=colors.HexColor('#888'))
    sB = ParagraphStyle('B', parent=styles['Normal'], fontName=fb, fontSize=9, leading=13)
    
    is_extra = offer.get("offer_type") == "extra"
    label = "Допълнителна оферта" if is_extra else "Оферта"
    org_name = org.get("name", "") if org else ""
    
    elements = []
    
    # Header
    hdr = [[Paragraph(f"<b>{org_name}</b>", sB), Paragraph(f"<b>{label}</b>", ParagraphStyle('R', parent=sTitle, alignment=2, fontSize=13))],
           [Paragraph(org.get("address", "") if org else "", sS), Paragraph(f"<b>№ {offer.get('offer_no', '')}</b>  v{offer.get('version', 1)}", ParagraphStyle('R', parent=sB, alignment=2, fontSize=13))]]
    ht = RLTable(hdr, colWidths=[300, 230])
    ht.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP'), ('TOPPADDING', (0,0), (-1,-1), 2), ('BOTTOMPADDING', (0,0), (-1,-1), 2)]))
    elements.extend([ht, Spacer(1, 5*mm)])
    
    # Meta
    meta = [f"Дата: {offer.get('created_at', '')[:10]}", f"Статус: {STATUS_LABELS_BG.get(offer.get('status', ''), offer.get('status', ''))}"]
    if project:
        meta.append(f"Обект: {project.get('code', '')} - {project.get('name', '')}")
    elements.extend([Paragraph(" | ".join(meta), sS), Spacer(1, 5*mm)])
    
    if offer.get("title"):
        elements.extend([Paragraph(f"<b>{offer['title']}</b>", sB), Spacer(1, 3*mm)])
    
    # Lines table
    # R43: the offer PDF is the document the client gets — combined unit price only
    cw = [22, 235, 40, 50, 75, 75]
    line_data = [["№", "Описание", "Ед.", "К-во", "Ед. цена", "Общо"]]
    for i, l in enumerate(offer.get("lines", [])):
        cl = client_line(l)
        qty, up, lt = cl["qty"], cl["unit_price_text"], cl["line_total"]   # F-79-01: exact price
        note = ""
        if l.get("note"):
            note = f"\n{l['note']}"
        line_data.append([str(i+1), Paragraph(f"{l.get('activity_name', '')}{note}", sN), UNIT_LABELS_BG.get(l.get("unit", ""), l.get("unit", "")), qty_text(qty), up, f"{lt:.2f}"])
    
    lt = RLTable(line_data, colWidths=cw, repeatRows=1)
    lt.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f0f0f0')),
        ('FONTNAME', (0,0), (-1,0), fb), ('FONTNAME', (0,1), (-1,-1), fn),
        ('FONTSIZE', (0,0), (-1,-1), 8), ('ALIGN', (2,0), (-1,-1), 'RIGHT'), ('ALIGN', (0,0), (1,-1), 'LEFT'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#ccc')),
        ('TOPPADDING', (0,0), (-1,-1), 3), ('BOTTOMPADDING', (0,0), (-1,-1), 3), ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    elements.extend([lt, Spacer(1, 5*mm)])
    
    # Totals
    curr = offer.get("currency", "BGN")
    sub = offer.get("subtotal", 0)
    vp = offer.get("vat_percent", 0)
    va = offer.get("vat_amount", 0)
    tot = offer.get("total", 0)
    td = [["", "", "", "", "Междинна сума:", f"{sub:.2f} {curr}"],
          ["", "", "", "", f"ДДС ({vp}%):", f"{va:.2f} {curr}"],
          ["", "", "", "", "ОБЩО:", f"{tot:.2f} {curr}"]]
    tt = RLTable(td, colWidths=cw)
    tt.setStyle(TableStyle([('FONTNAME', (0,0), (-1,-1), fn), ('FONTNAME', (4,2), (4,2), fb),
        ('FONTSIZE', (0,0), (-1,-1), 9), ('FONTSIZE', (4,2), (5,2), 11),
        ('ALIGN', (4,0), (-1,-1), 'RIGHT'), ('LINEABOVE', (4,2), (-1,2), 1, colors.black),
        ('TOPPADDING', (0,0), (-1,-1), 2), ('BOTTOMPADDING', (0,0), (-1,-1), 2)]))
    elements.append(tt)
    
    if offer.get("notes"):
        elements.extend([Spacer(1, 6*mm), Paragraph("Бележки:", sH2), Paragraph(offer["notes"], sN)])
    
    doc.build(elements)
    buffer.seek(0)
    fn_name = f"offer_{offer.get('offer_no', offer_id)}.pdf"
    return StreamingResponse(buffer, media_type="application/pdf",
                            headers={"Content-Disposition": f'attachment; filename="{fn_name}"'})


@router.get("/offers/{offer_id}/xlsx")
async def export_offer_xlsx(
    offer_id: str,
    _sec02: dict = Depends(require_finance_read(
        "finance.offer_spreadsheet.export", module="M2", resource_type="offer_spreadsheet")),  # SEC-02 (R20-2): before any read
    user: dict = Depends(require_m2)):
    """Export offer as XLSX"""
    offer = await _tenant(user).offers.get(offer_id, {"_id": 0})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    
    org = await _tenant(user).own_organization({"_id": 0})
    # W0-03E-R1: same tenant predicate as the PDF export.
    project = await _tenant(user).projects.get(offer.get("project_id"), {"_id": 0, "code": 1, "name": 1})
    
    import openpyxl
    from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Оферта"
    
    thin = Side(style='thin', color='CCCCCC')
    header_fill = PatternFill(start_color='F0F0F0', end_color='F0F0F0', fill_type='solid')
    bold_font = Font(bold=True, size=11)
    header_font = Font(bold=True, size=9)
    normal_font = Font(size=9)
    
    # Header info
    ws.merge_cells('A1:H1')
    ws['A1'] = org.get("name", "") if org else ""
    ws['A1'].font = Font(bold=True, size=14)
    
    is_extra = offer.get("offer_type") == "extra"
    ws.merge_cells('A2:H2')
    ws['A2'] = f"{'Допълнителна оферта' if is_extra else 'Оферта'} {offer.get('offer_no', '')} v{offer.get('version', 1)}"
    ws['A2'].font = bold_font
    
    ws['A3'] = "Проект:"
    ws['B3'] = f"{project.get('code', '')} - {project.get('name', '')}" if project else ""
    ws['A4'] = "Дата:"
    ws['B4'] = offer.get("created_at", "")[:10]
    ws['C4'] = "Статус:"
    ws['D4'] = STATUS_LABELS_BG.get(offer.get("status", ""), offer.get("status", ""))
    ws['E4'] = "Валута:"
    ws['F4'] = offer.get("currency", "BGN")
    
    # Column headers
    row = 6
    headers = ["№", "Описание / Вид СМР", "Мярка", "Количество", "Цена материал", "Цена труд", "Материал общо", "Общо"]
    for col, h in enumerate(headers, 1):
        c = ws.cell(row=row, column=col, value=h)
        c.font = header_font
        c.fill = header_fill
        c.border = Border(top=thin, bottom=thin, left=thin, right=thin)
        c.alignment = Alignment(horizontal='center')
    
    # Set column widths
    ws.column_dimensions['A'].width = 5
    ws.column_dimensions['B'].width = 40
    ws.column_dimensions['C'].width = 8
    ws.column_dimensions['D'].width = 10
    ws.column_dimensions['E'].width = 14
    ws.column_dimensions['F'].width = 14
    ws.column_dimensions['G'].width = 14
    ws.column_dimensions['H'].width = 14
    
    # Lines
    for i, l in enumerate(offer.get("lines", [])):
        row += 1
        qty = l.get("qty", 0)
        mu = l.get("material_unit_cost", 0)
        lu = l.get("labor_unit_cost", 0)
        lmc = round(qty * mu, 2)
        lt = round(qty * (mu + lu), 2)
        
        desc = l.get("activity_name", "")
        if l.get("note"):
            desc += f" ({l['note']})"
        
        vals = [i+1, desc, UNIT_LABELS_BG.get(l.get("unit", ""), l.get("unit", "")), qty, mu, lu, lmc, lt]
        for col, v in enumerate(vals, 1):
            c = ws.cell(row=row, column=col, value=v)
            c.font = normal_font
            c.border = Border(top=thin, bottom=thin, left=thin, right=thin)
            if col >= 4:
                c.number_format = '#,##0.00'
                c.alignment = Alignment(horizontal='right')
    
    # Totals
    row += 2
    ws.cell(row=row, column=7, value="Междинна сума:").font = bold_font
    ws.cell(row=row, column=8, value=offer.get("subtotal", 0)).font = bold_font
    ws.cell(row=row, column=8).number_format = '#,##0.00'
    row += 1
    ws.cell(row=row, column=7, value=f"ДДС ({offer.get('vat_percent', 0)}%):").font = normal_font
    ws.cell(row=row, column=8, value=offer.get("vat_amount", 0)).number_format = '#,##0.00'
    row += 1
    ws.cell(row=row, column=7, value="ОБЩО:").font = Font(bold=True, size=12)
    ws.cell(row=row, column=8, value=offer.get("total", 0)).font = Font(bold=True, size=12)
    ws.cell(row=row, column=8).number_format = '#,##0.00'
    
    if offer.get("notes"):
        row += 2
        ws.cell(row=row, column=1, value="Бележки:").font = bold_font
        ws.cell(row=row+1, column=1, value=offer["notes"]).font = normal_font
    
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    fn_name = f"offer_{offer.get('offer_no', offer_id)}.xlsx"
    return StreamingResponse(buffer, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            headers={"Content-Disposition": f'attachment; filename="{fn_name}"'})


# ── Offer Import from XLSX ─────────────────────────────────────────

@router.post("/offers/import-preview")
async def import_offer_preview(file: UploadFile = File(...), user: dict = Depends(require_m2)):
    """Parse uploaded XLSX and return preview of lines for review"""
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Поддържат се само .xlsx файлове")
    
    import openpyxl
    
    content = await file.read()
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise HTTPException(status_code=400, detail="Файлът е празен")
    
    # Find header row (look for known column names)
    header_row = None
    header_idx = 0
    known_headers = {"описание", "вид смр", "мярка", "количество", "цена", "материал", "труд", "общо", "description", "unit", "qty", "price"}
    
    for i, row in enumerate(rows[:10]):
        row_lower = [str(c).lower().strip() if c else "" for c in row]
        matches = sum(1 for h in row_lower if any(k in h for k in known_headers))
        if matches >= 2:
            header_row = row
            header_idx = i
            break
    
    if not header_row:
        # Try first row as header
        header_row = rows[0]
        header_idx = 0
    
    # Map columns
    col_map = {}
    UNIT_REVERSE = {"м2": "m2", "м": "m", "бр": "pcs", "часа": "hours", "к-т": "lot", "кг": "kg", "л": "l"}
    
    for ci, cell in enumerate(header_row):
        h = str(cell).lower().strip() if cell else ""
        if any(k in h for k in ["описание", "вид смр", "description", "наименование", "дейност"]):
            col_map["description"] = ci
        elif any(k in h for k in ["мярка", "ед.", "unit"]):
            col_map["unit"] = ci
        elif any(k in h for k in ["количество", "к-во", "qty"]):
            col_map["qty"] = ci
        elif any(k in h for k in ["цена материал", "мат. цена", "material"]):
            col_map["material_price"] = ci
        elif any(k in h for k in ["цена труд", "труд", "labor"]):
            col_map["labor_price"] = ci
        elif any(k in h for k in ["обща цена", "общо", "total", "стойност"]):
            col_map["total"] = ci
        elif any(k in h for k in ["бележк", "note"]):
            col_map["notes"] = ci
        elif any(k in h for k in ["етаж", "floor"]):
            col_map["floor"] = ci
        elif any(k in h for k in ["помещение", "room"]):
            col_map["room"] = ci
        elif any(k in h for k in ["зона", "zone"]):
            col_map["zone"] = ci
    
    # Parse data rows
    lines = []
    warnings = []
    
    for ri, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        if not row or all(c is None or str(c).strip() == "" for c in row):
            continue
        
        desc = str(row[col_map["description"]]).strip() if "description" in col_map and col_map["description"] < len(row) and row[col_map["description"]] else ""
        if not desc:
            continue
        
        unit_raw = str(row[col_map["unit"]]).strip() if "unit" in col_map and col_map["unit"] < len(row) and row[col_map["unit"]] else "pcs"
        unit = UNIT_REVERSE.get(unit_raw.lower(), unit_raw.lower()) if unit_raw else "pcs"
        if unit not in OFFER_UNITS:
            warnings.append(f"Ред {ri}: неразпозната мярка '{unit_raw}'")
            unit = "pcs"
        
        def safe_float(val):
            try: return float(val) if val else 0
            except (ValueError, TypeError): return 0
        
        qty = safe_float(row[col_map["qty"]] if "qty" in col_map and col_map["qty"] < len(row) else 0)
        mat_price = safe_float(row[col_map["material_price"]] if "material_price" in col_map and col_map["material_price"] < len(row) else 0)
        lab_price = safe_float(row[col_map["labor_price"]] if "labor_price" in col_map and col_map["labor_price"] < len(row) else 0)
        total = safe_float(row[col_map["total"]] if "total" in col_map and col_map["total"] < len(row) else 0)
        
        # If only total given, split 50/50
        if total > 0 and mat_price == 0 and lab_price == 0 and qty > 0:
            price_per_unit = total / qty
            mat_price = round(price_per_unit * 0.4, 2)
            lab_price = round(price_per_unit * 0.6, 2)
        
        if qty == 0:
            warnings.append(f"Ред {ri}: количество е 0 за '{desc}'")
        if mat_price == 0 and lab_price == 0:
            warnings.append(f"Ред {ri}: няма цена за '{desc}'")
        
        note = str(row[col_map["notes"]]).strip() if "notes" in col_map and col_map["notes"] < len(row) and row[col_map["notes"]] else ""
        floor = str(row[col_map["floor"]]).strip() if "floor" in col_map and col_map["floor"] < len(row) and row[col_map["floor"]] else ""
        room = str(row[col_map["room"]]).strip() if "room" in col_map and col_map["room"] < len(row) and row[col_map["room"]] else ""
        zone = str(row[col_map["zone"]]).strip() if "zone" in col_map and col_map["zone"] < len(row) and row[col_map["zone"]] else ""
        
        location_parts = [p for p in [floor and f"Ет.{floor}", room, zone] if p]
        if location_parts and note:
            note = f"Локация: {', '.join(location_parts)}; {note}"
        elif location_parts:
            note = f"Локация: {', '.join(location_parts)}"
        
        lines.append({
            "row_number": ri,
            "description": desc,
            "unit": unit,
            "qty": qty,
            "material_price": mat_price,
            "labor_price": lab_price,
            "total": total,
            "note": note,
        })
    
    return {
        "file_name": file.filename,
        "total_rows": len(rows),
        "parsed_lines": len(lines),
        "column_mapping": col_map,
        "headers_found": [str(c) for c in header_row if c],
        "warnings": warnings,
        "lines": lines,
    }


@router.post("/offers/import-confirm", status_code=201)
async def import_offer_confirm(data: dict, user: dict = Depends(require_m2)):
    """Create offer from imported/previewed lines"""
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    project_id = data.get("project_id")
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id required")
    
    project = await _tenant(user).projects.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    import_lines = data.get("lines", [])
    if not import_lines:
        raise HTTPException(status_code=400, detail="No lines to import")
    
    offer_type = data.get("offer_type", "main")
    title = data.get("title", f"Импортирана оферта ({datetime.now().strftime('%d.%m.%Y')})")
    currency = data.get("currency", "BGN")
    vat_percent = float(data.get("vat_percent", 20))
    
    now = datetime.now(timezone.utc).isoformat()
    offer_no = await get_next_offer_no(_tenant(user))
    
    lines = []
    for i, il in enumerate(import_lines):
        qty = float(il.get("qty", 1))
        mu = float(il.get("material_price", 0))
        lu = float(il.get("labor_price", 0))
        l = {
            "id": str(uuid.uuid4()),
            "activity_code": None,
            "activity_name": il.get("description", ""),
            "unit": il.get("unit", "pcs"),
            "qty": qty,
            "material_unit_cost": mu,
            "labor_unit_cost": lu,
            "labor_hours_per_unit": None,
            "line_material_cost": round(qty * mu, 2),
            "line_labor_cost": round(qty * lu, 2),
            "line_total": round(qty * (mu + lu), 2),
            "note": il.get("note", ""),
            "sort_order": i,
            "activity_type": "Общо",
            "activity_subtype": "",
        }
        lines.append(l)
    
    subtotal = sum(l["line_total"] for l in lines)
    vat_amount = round(subtotal * vat_percent / 100, 2)
    total = round(subtotal + vat_amount, 2)
    
    offer = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "project_id": project_id,
        "offer_no": offer_no,
        "title": title,
        "offer_type": offer_type,
        "status": "Draft",
        "version": 1,
        "parent_offer_id": None,
        "currency": currency,
        "vat_percent": vat_percent,
        "lines": lines,
        "subtotal": round(subtotal, 2),
        "vat_amount": vat_amount,
        "total": total,
        "notes": data.get("notes", f"Импортирана от файл: {data.get('file_name', '')}"),
        "created_at": now,
        "updated_at": now,
        "sent_at": None,
        "accepted_at": None,
        "import_source": data.get("file_name"),
    }
    
    await _tenant(user).offers.insert_one(offer)
    await log_audit(user["org_id"], user["id"], user["email"], "offer_imported", "offer", offer["id"],
                    {"offer_no": offer_no, "lines": len(lines), "source": data.get("file_name")})
    # W0-03E: the free-text works and units of an imported offer go to pending
    # mapping only (never an official Master record). A no-op while
    # MASTER_DATA_MODE=off, and unable to raise — the import already succeeded.
    from app.master_data.intake_hooks import observe_excel_offer_lines
    await observe_excel_offer_lines(user, import_lines, source_ref="offer-import:%s" % offer["id"])

    return {k: v for k, v in offer.items() if k != "_id"}


# ── Import Template Download ───────────────────────────────────────

@router.get("/offer-import-template")
async def download_import_template(user: dict = Depends(require_m2)):
    """Download XLSX template for offer import"""
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Оферта"
    
    thin = Side(style='thin', color='CCCCCC')
    hdr_fill = PatternFill(start_color='E8F0FE', end_color='E8F0FE', fill_type='solid')
    hdr_font = Font(bold=True, size=10)
    
    headers = ["Описание / Вид СМР", "Мярка", "Количество", "Цена материал", "Цена труд", "Обща цена", "Бележки", "Етаж", "Помещение", "Зона"]
    for ci, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=ci, value=h)
        c.font = hdr_font
        c.fill = hdr_fill
        c.border = Border(top=thin, bottom=thin, left=thin, right=thin)
    
    ws.column_dimensions['A'].width = 35
    ws.column_dimensions['B'].width = 10
    ws.column_dimensions['C'].width = 12
    ws.column_dimensions['D'].width = 14
    ws.column_dimensions['E'].width = 14
    ws.column_dimensions['F'].width = 14
    ws.column_dimensions['G'].width = 20
    ws.column_dimensions['H'].width = 8
    ws.column_dimensions['I'].width = 15
    ws.column_dimensions['J'].width = 15
    
    # Example rows
    examples = [
        ["Направа на мазилка по стени", "м2", 25, 8.50, 12.00, 512.50, "", "1", "Спалня", "Южна стена"],
        ["Боядисване на стени и тавани", "м2", 40, 4.50, 6.00, 420.00, "2 слоя латекс", "1", "Хол", ""],
        ["Монтаж на ел. ключове/контакти", "бр", 8, 35.00, 25.00, 480.00, "Schneider серия", "", "", ""],
    ]
    for ri, ex in enumerate(examples, 2):
        for ci, v in enumerate(ex, 1):
            c = ws.cell(row=ri, column=ci, value=v)
            c.font = Font(size=9, italic=True, color='888888')
            if ci >= 3 and isinstance(v, (int, float)):
                c.number_format = '#,##0.00'
    
    # Instructions sheet
    ws2 = wb.create_sheet("Инструкции")
    instructions = [
        "ИНСТРУКЦИИ ЗА ИМПОРТ НА ОФЕРТИ",
        "",
        "Задължителни колони:",
        "  - Описание / Вид СМР (текст)",
        "  - Мярка: м2, м, бр, часа, к-т, кг, л",
        "  - Количество (число)",
        "",
        "Поне едно от:",
        "  - Цена материал + Цена труд (числа)",
        "  - ИЛИ Обща цена (число, ще се разпредели 40/60)",
        "",
        "Допълнителни колони (незадължителни):",
        "  - Бележки",
        "  - Етаж, Помещение, Зона (за локация)",
        "",
        "Поддържани мерни единици:",
        "  м2, м, бр, часа, к-т, кг, л",
        "",
        "Формат: .xlsx (Excel 2007+)",
    ]
    for ri, txt in enumerate(instructions, 1):
        ws2.cell(row=ri, column=1, value=txt).font = Font(size=10, bold=(ri == 1))
    ws2.column_dimensions['A'].width = 60
    
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            headers={"Content-Disposition": 'attachment; filename="BEG_Work_Offer_Import_Template.xlsx"'})

@router.get("/offers/review/{review_token}")
async def get_offer_review(review_token: str):
    """Public endpoint - get offer for client review (no auth required)"""
    # W0-03E-A1: no session — the token is the only key. It must resolve to
    # exactly one offer; that offer's own org is the tenant of every read below.
    tenant, offer = await resolve_review_token(db, review_token, {"_id": 0})
    if not offer:
        raise HTTPException(status_code=404, detail="Офертата не е намерена")
    # FG-138: a replaced version or a closed link shows nothing of the offer — a neutral text
    if _is_superseded(offer) or await _has_newer_version(tenant, offer):
        raise HTTPException(status_code=410, detail={
            "error_code": OFFER_VERSION_SUPERSEDED, "message": PUBLIC_SUPERSEDED_TEXT})
    if _link_closed(offer):
        raise HTTPException(status_code=410, detail={
            "error_code": "OFFER_NOT_OPEN", "message": PUBLIC_NOT_OPEN_TEXT})
    
    # Record view event (only first time)
    if offer["status"] == "Sent":
        now = datetime.now(timezone.utc).isoformat()
        # FG-149: a view is not an edit — it never touches updated_at (which every draft /
        # transition CAS compares); it only raises last_viewed_at and counts the view
        await tenant.offers.update_one({"id": offer["id"], "review_token": review_token}, {
            "$max": {"viewed_at": now, "last_viewed_at": now}, "$inc": {"view_count": 1}})
        existing_view = await db.offer_events.find_one({
            "offer_id": offer["id"], "org_id": offer["org_id"], "event_type": "viewed",
        })
        if not existing_view:
            await db.offer_events.insert_one({
                "id": str(uuid.uuid4()), "org_id": offer["org_id"],
                "offer_id": offer["id"], "event_type": "viewed",
                "actor": "client", "created_at": now, "details": {},
            })
    
    # Get project info
    # W0-03E-R1/A1: the project is read only inside the offer's own tenant.
    project = await tenant.projects.get(offer.get("project_id"),
                                        {"_id": 0, "code": 1, "name": 1, "address_text": 1})
    
    # Get org info
    org = await tenant.own_organization({"_id": 0, "name": 1, "phone": 1, "email": 1})
    
    return {
        "offer_no": offer.get("offer_no"),
        "title": offer.get("title"),
        "status": offer.get("status"),
        "version": offer.get("version", 1),
        "offer_type": offer.get("offer_type"),
        "currency": offer.get("currency"),
        "vat_percent": offer.get("vat_percent"),
        "lines": [client_line(l) for l in offer.get("lines", [])],     # R43
        "subtotal": offer.get("subtotal"),
        "vat_amount": offer.get("vat_amount"),
        "total": offer.get("total"),
        "notes": offer.get("notes"),
        "sent_at": offer.get("sent_at"),
        "project_code": project.get("code") if project else "",
        "project_name": project.get("name") if project else "",
        "project_address": project.get("address_text") if project else "",
        "company_name": org.get("name") if org else "",
        "company_phone": org.get("phone") if org else "",
        "company_email": org.get("email") if org else "",
    }


CLIENT_ACTIONS = {
    "approve": ("Accepted", "approved_by_client", "offers.offer.client_approved"),
    "reject": ("Rejected", "rejected_by_client", "offers.offer.client_rejected"),
    "revision": ("NeedsRevision", "revision_requested", "offers.offer.client_revision_requested"),
}


@router.post("/offers/review/{review_token}/respond")
async def respond_to_offer(review_token: str, data: dict,
                           idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """Public endpoint - client responds to offer (no auth required).

    OFF-01: the link is bound to its offer id and exact version; a superseded version or a
    revoked link → 409 with a neutral text. The check is the filter of the write, in the
    transaction that also writes the AuditEvent."""
    tenant, offer = await resolve_review_token(db, review_token)
    if not offer:
        raise HTTPException(status_code=404, detail="Офертата не е намерена")
    key = _require_key(idempotency_key)
    action = data.get("action")  # approve / reject / revision
    comment = data.get("comment", "")
    client_name = data.get("client_name", "")
    version = offer.get("version", 1)

    async def work():
        if _is_superseded(offer) or await _has_newer_version(tenant, offer):
            raise _superseded_error()
        if _link_closed(offer):
            raise _conflict("OFFER_NOT_OPEN", PUBLIC_NOT_OPEN_TEXT)
        if offer["status"] not in ["Sent"]:
            raise HTTPException(status_code=400, detail="Тази оферта вече е обработена")
        if action not in CLIENT_ACTIONS:
            raise HTTPException(status_code=400, detail="Невалидно действие")
        new_status, event_type, canonical = CLIENT_ACTIONS[action]

        async def body(session):
            now = datetime.now(timezone.utc).isoformat()
            if action == "approve":
                await _family_guard(tenant, offer, session)
            elif await _has_newer_version(tenant, offer, session):
                raise _superseded_error()
            update_fields = {"status": new_status, "client_comment": comment,
                             "client_name": client_name, "updated_at": now}
            if action == "approve":
                update_fields.update({"accepted_at": now, "approval": {
                    "method": "magic_link", "channel": "review_link", "version": version,
                    "client_name": client_name, "comment": comment, "accepted_at": now,
                    # FLOW-003 carrier 3 also needs a limited validity and an identity check
                    # (debt D-OFF01-1): only the link itself is verified today.
                    "verification": "link_token_only"}})
            elif action == "reject":
                update_fields["reject_reason"] = comment
            else:
                update_fields["revision_comment"] = comment
            won = await tenant.offers.update_one(
                {"id": offer["id"], "review_token": review_token, "status": "Sent",
                 "superseded_by": None, "version": version,
                 "review_token_status": {"$ne": "revoked"},
                 "$or": [{"review_token_version": {"$exists": False}},
                         {"review_token_version": version}]},
                {"$set": update_fields}, session=session)
            if won.modified_count != 1:
                current = await tenant.offers.get(offer["id"], {"_id": 0}, session=session) or {}
                if _is_superseded(current):
                    raise _superseded_error()
                if _link_closed(current) or current.get("version", version) != version:
                    raise _conflict("OFFER_NOT_OPEN", PUBLIC_NOT_OPEN_TEXT)
                # FG-144: the loser of a race → 409, with the neutral public text
                raise _conflict("OFFER_NOT_OPEN", PUBLIC_NOT_OPEN_TEXT)
            await tenant.offer_events.insert_one({
                "id": str(uuid.uuid4()), "org_id": offer["org_id"],
                "offer_id": offer["id"], "event_type": event_type,
                "actor": client_name or "client", "created_at": now,
                "details": {"comment": comment, "client_name": client_name, "version": version},
            }, session=session)
            await _offer_event(
                session, tenant_id=offer["org_id"], actor_type="external_principal",
                actor_id="offer-review-link:%s" % offer["id"], action=canonical, offer=offer,
                idem_key=key, channel="magic_link",
                endpoint="POST /api/offers/review/{review_token}/respond",
                diff={"status": {"before": "Sent", "after": new_status}, "version": version,
                      "approval_method": "magic_link" if action == "approve" else None,
                      "client_name": client_name, "total": offer.get("total"),
                      "currency": offer.get("currency")})
            return {"ok": True, "status": new_status}
        return await _in_transaction(body)

    return await _once(offer["org_id"], key, "offers.offer.client_respond",
                       {"offer_id": offer["id"], "action": action, "comment": comment,
                        "client_name": client_name}, work)


# ── Offer Events History ───────────────────────────────────────────

@router.get("/offers/{offer_id}/events")
@strip_money_for_non_finance   # SEC-02-A (R20-5M, D1)
async def get_offer_events(offer_id: str, user: dict = Depends(require_m2)):
    """Get event history for an offer"""
    tenant = _tenant(user)
    offer = await _tenant(user).offers.get(offer_id)
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    
    events = await tenant.offer_events.find(
        {"offer_id": offer_id, "org_id": user["org_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    return events
