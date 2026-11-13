"""
INV-CN-01 — invoices locked at issue; cancellation; credit / debit notes (FLOW-006).

Package: ``docs/architecture/tasks/INV-CN-01_CREDIT_DEBIT_NOTES.md`` (branch
``claude/happy-meitner-bmcnel`` @ 344c197). Decision Р49 (+ Р47 for the incoming
side), oracle Q004. Canon: FLOW-006 §Корекции (L62, L70-80, L92), FLOW-025 DOC-03
L101 / DOC-06 L144, FLOW-004 L96-104, FLOW-005 L98, FLOW-010 L352-360/L389,
FLOW-034 L68/L72, CLAUDE.md §2.9, §7, §8.

This module holds the RULES (pure money arithmetic + the DB reads/writes every
route shares). The HTTP surface is ``app/routes/invoice_corrections.py``; the
invoice routes in ``app/routes/finance.py`` call the lock / numbering / open
balance helpers below.

Source of truth:
  * the invoice document keeps its own amounts for ever (``total`` is never
    rewritten after issue — Р49.2);
  * a credit / debit note is its OWN immutable document in
    ``credit_debit_notes`` (FLOW-025 L144) that points at the original invoice
    and its lines;
  * the invoice carries only DERIVED sums (``credited_amount`` …), recomputed
    from the source rows inside the same transaction (``recompute_invoice``);
  * real money (refund) is a ``finance_payments`` row (FLOW-006, one ledger);
    an offset is an explicit ``invoice_offsets`` record with both sources.
"""
from __future__ import annotations

import re
import uuid

from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, Iterable, List, Optional

from fastapi import HTTPException

# ── error codes (package §1–§4) ───────────────────────────────────────────────
INVOICE_LOCKED = "INVOICE_LOCKED"
INVOICE_NUMBERED = "INVOICE_NUMBERED"
INVOICE_NOT_ISSUED = "INVOICE_NOT_ISSUED"
USE_CREDIT_NOTE = "USE_CREDIT_NOTE"
CREDIT_EXCEEDS_INVOICED = "CREDIT_EXCEEDS_INVOICED"
DEBIT_NOTE_BASIS_REQUIRED = "DEBIT_NOTE_BASIS_REQUIRED"
SAME_PERSON_APPROVAL = "SAME_PERSON_APPROVAL"
APPROVER_ROLE_REQUIRED = "APPROVER_ROLE_REQUIRED"
VERSION_MISMATCH = "VERSION_MISMATCH"
NOT_PENDING = "NOT_PENDING_APPROVAL"
ACT_OVER_INVOICED = "ACT_OVER_INVOICED"
ACT_NOT_APPROVED = "ACT_NOT_APPROVED"
OFFSET_ACROSS_CONTRACTS = "OFFSET_ACROSS_CONTRACTS"
OFFSET_EXCEEDS_BALANCE = "OFFSET_EXCEEDS_BALANCE"
REFUND_EXCEEDS_BALANCE = "REFUND_EXCEEDS_BALANCE"
DUPLICATE_CREDIT_NOTE = "DUPLICATE_CREDIT_NOTE"
NOTE_INVALID = "NOTE_INVALID"
INVOICE_NOT_CORRECTABLE = "INVOICE_NOT_CORRECTABLE"
USE_CORRECTION = "USE_CORRECTION"
SUPPLIER_TAX_ID_REQUIRED = "SUPPLIER_TAX_ID_REQUIRED"


def supplier_tax_id_refusal(invoice: dict):
    """Р55(1) / FG-249: an incoming invoice names its supplier by ЕИК, or — a foreign
    supplier — by its tax number; otherwise 422 (nothing written)."""
    inv = invoice or {}
    eik = (inv.get("counterparty_eik") or "").strip()
    foreign = (inv.get("counterparty_foreign_tax_no") or "").strip() if isinstance(
        inv.get("counterparty_foreign_tax_no"), str) else ""
    if eik or foreign:
        return None
    return unprocessable(SUPPLIER_TAX_ID_REQUIRED,
                         "ЕИК на доставчика е задължителен (за чуждестранен доставчик — данъчният му номер)")
CANCELLATION_PENDING = "CANCELLATION_PENDING"
DEBIT_NOTE_NOT_APPROVED = "DEBIT_NOTE_NOT_APPROVED"
OFFSET_BASIS_REQUIRED = "OFFSET_BASIS_REQUIRED"
DUE_DATE_REASON_REQUIRED = "DUE_DATE_REASON_REQUIRED"

# ── statuses ──────────────────────────────────────────────────────────────────
# Р49.1: Draft → Issued (number; locked) → Sent → PartiallyPaid / Paid ; Cancelled
DRAFT, ISSUED, SENT, CANCELLED = "Draft", "Issued", "Sent", "Cancelled"
NOTE_PENDING = "pending_approval"     # outgoing: created by the Accountant, no number yet
NOTE_APPROVED = "approved"            # outgoing: approved by the Owner, numbered
NOTE_REGISTERED = "registered"        # incoming: registered by the Accountant
NOTE_REJECTED = "rejected"            # D10: rejected by the Owner / withdrawn by the author
OFFSET_PENDING, OFFSET_APPROVED = "pending_approval", "approved"

KIND_CREDIT, KIND_DEBIT = "credit", "debit"
OUTGOING, INCOMING = "outgoing", "incoming"

# Р49.1 / package §1: after issue, an edit of amount / lines / VAT / counterparty
# (and of the number, the dates of the tax event, the project the revenue goes to)
# is refused. Only these two non-money fields stay editable on an issued invoice.
EDITABLE_AFTER_ISSUE = frozenset({"notes", "due_date"})

# Р49.8: the supplier credit note a receipt reversal awaits — escalated to the
# Owner after this many days (computed on read, nothing written by a GET).
EXPECTED_CREDIT_ESCALATION_DAYS = 14
# Р49.8: "съвпадение до стотинка"
#: FG-219: "до стотинка" = EXACT equality after rounding to whole cents (difference 0.00).
MATCH_TOLERANCE = Decimal("0.00")

NUMBER_COUNTER = "invoice_document_number"   # one shared sequence: invoices + notes (Р49.3)
CORRECTION_ACTOR_SOURCE = "FLOW-006"

CENT = Decimal("0.01")


def cents(value) -> Decimal:
    """Whole cents, half-up (a float never reaches a comparison un-rounded)."""
    if isinstance(value, Decimal):
        return value.quantize(CENT, ROUND_HALF_UP)
    return Decimal(str(value or 0)).quantize(CENT, ROUND_HALF_UP)


def money(value: Decimal) -> float:
    return float(cents(value))


def conflict(code: str, message: str, **extra) -> HTTPException:
    return HTTPException(status_code=409, detail={"error_code": code, "message": message, **extra})


def unprocessable(code: str, message: str, **extra) -> HTTPException:
    return HTTPException(status_code=422, detail={"error_code": code, "message": message, **extra})


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════ §1 lock
def is_locked(invoice: dict) -> bool:
    """Р49.1: only a Draft is editable. Every other status is an official document.
    Addendum A / Р49(1): a LEGACY outgoing draft that already carries a number (numbered
    at creation before INV-CN-01) is treated as issued — locked — even before the
    migration (``invoice_corrections_migration``) gives it the status Issued."""
    inv = invoice or {}
    if inv.get("status") != DRAFT:
        return True
    return is_legacy_numbered_draft(inv)


def same_line_money(current_lines: list, new_lines: list) -> bool:
    """WH-FIX-01 merge (Р45 + Р49.1): do the new lines carry EXACTLY the money content of
    the current ones (same count, description, unit, quantity, unit price, cost category)?
    Then only their destination differs — the one change a locked supplier invoice allows."""
    if len(current_lines) != len(new_lines):
        return False

    def _get(line, k):
        return line.get(k) if isinstance(line, dict) else getattr(line, k, None)

    for cur, new in zip(current_lines, new_lines):
        for k in ("description", "unit", "cost_category"):
            if (_get(cur, k) or None) != (_get(new, k) or None):
                return False
        for k in ("qty", "unit_price"):
            if cents(_get(cur, k) or 0) != cents(_get(new, k) or 0):
                return False
    return True


def is_legacy_numbered_draft(invoice: dict) -> bool:
    inv = invoice or {}
    return (inv.get("status") == DRAFT and inv.get("direction") == "Issued"
            and isinstance(inv.get("invoice_no"), str) and bool(inv.get("invoice_no").strip()))


def locked_refusal(invoice: dict, fields: Optional[Iterable[str]] = None) -> HTTPException:
    return conflict(INVOICE_LOCKED,
                    "Фактурата е издадена и е заключена — сумата, редовете, ДДС и контрагентът "
                    "не се променят. Корекция само с кредитно/дебитно известие.",
                    invoice_id=(invoice or {}).get("id"), status=(invoice or {}).get("status"),
                    fields=sorted(fields or ()))


def locked_fields(update: Dict) -> List[str]:
    return sorted(k for k in update if k not in EDITABLE_AFTER_ISSUE and k != "updated_at")


# ═══════════════════════════════════════════════════════════════ numbering
def number_prefix(settings: dict) -> str:
    return (settings or {}).get("issued_prefix") or "INV"


def format_number(prefix: str, value: int) -> str:
    return f"{prefix}-{value:04d}"


def parse_number(prefix: str, number) -> int:
    if not isinstance(number, str) or not number.startswith(prefix + "-"):
        return 0
    try:
        return int(number[len(prefix) + 1:].lstrip("0") or "0")
    except ValueError:
        return 0


def number_counter_id(org_id: str) -> str:
    """INV84-N2: the ONE shared counter document has a deterministic ``_id`` — an upsert on
    it is unique by itself, so two concurrent first uses never create two counters (the
    ``inv_cn_01_number_counter_unique`` index is only a second guard)."""
    return "number_counter:%s:%s" % (org_id, NUMBER_COUNTER)


def number_counter_filter(org_id: str) -> dict:
    return {"_id": number_counter_id(org_id)}


async def seed_number_counter(tenant, prefix: str, settings: dict) -> None:
    """Create the shared per-tenant counter ONCE (outside any transaction), above every
    number already used by an issued invoice or an outgoing note of this tenant — so the
    first number it gives can never repeat a legacy one. Idempotent; a concurrent
    creator wins and this is a no-op."""
    from pymongo.errors import DuplicateKeyError
    flt = number_counter_filter(tenant.org_id)
    if await tenant.org_counters.find_one(flt, {"_id": 0, "value": 1}):
        return
    highest = 0
    async for legacy in tenant.org_counters.find(            # an earlier, filter-keyed counter
            {"counter_type": NUMBER_COUNTER, "_id": {"$ne": flt["_id"]}}, {"_id": 0, "value": 1}):
        highest = max(highest, int(legacy.get("value") or 0))
    async for row in tenant.invoices.find(
            {"direction": "Issued", "invoice_no": {"$regex": "^%s-" % prefix}},
            {"_id": 0, "invoice_no": 1}):
        highest = max(highest, parse_number(prefix, row.get("invoice_no")))
    async for row in tenant.credit_debit_notes.find(
            {"direction": OUTGOING, "number": {"$regex": "^%s-" % prefix}}, {"_id": 0, "number": 1}):
        highest = max(highest, parse_number(prefix, row.get("number")))
    configured = int((settings or {}).get("issued_next_number") or 1) - 1
    try:
        await tenant.org_counters.update_one(
            flt, {"$setOnInsert": {"value": max(highest, configured), "prefix": prefix,
                                   "counter_type": NUMBER_COUNTER, "created_at": now_iso()}},
            upsert=True)
    except DuplicateKeyError:
        pass


MAX_NUMBER_SKIPS = 10000


def number_series_lock_id(org_id: str) -> str:
    return "number_series_lock:%s" % org_id


async def ensure_number_series_lock(tenant) -> None:
    """OUTSIDE the transaction: create the series lock document (idempotent)."""
    from pymongo.errors import DuplicateKeyError
    try:
        await tenant.org_counters.update_one(
            {"_id": number_series_lock_id(tenant.org_id)},
            {"$setOnInsert": {"name": "number_series_lock", "value": 0}}, upsert=True)
    except DuplicateKeyError:
        pass


async def lock_number_series(tenant, *, session) -> None:
    """INV84-N2: IN the transaction of every OUR number decision that does not go through
    the counter (a manual / legacy number at issue): two concurrent decisions write the
    same document → WriteConflict → the loser re-runs and sees the committed number — the
    duplicate check never depends on the unique index alone."""
    await tenant.org_counters.update_one(
        {"_id": number_series_lock_id(tenant.org_id)}, {"$inc": {"value": 1}}, session=session)


def supplier_note_lock_id(org_id: str, key: str, number: str) -> str:
    return "supplier_note_lock:%s:%s:%s" % (org_id, key, number)


async def ensure_supplier_note_lock(tenant, key: str, number: str) -> None:
    from pymongo.errors import DuplicateKeyError
    try:
        await tenant.org_counters.update_one(
            {"_id": supplier_note_lock_id(tenant.org_id, key, number)},
            {"$setOnInsert": {"name": "supplier_note_lock", "value": 0}}, upsert=True)
    except DuplicateKeyError:
        pass


async def lock_supplier_note_number(tenant, key: str, number: str, *, session) -> None:
    """INV84-N2: a supplier note's (supplier, number) duplicate check is serialised by this
    document — two notes with the same number on two DIFFERENT invoices of one supplier
    claim different invoices, so without it only the unique index would stop them."""
    await tenant.org_counters.update_one(
        {"_id": supplier_note_lock_id(tenant.org_id, key, number)}, {"$inc": {"value": 1}},
        session=session)


def supplier_key(invoice: dict) -> Optional[str]:
    """Р53(1): the supplier identity of an incoming invoice / note — the ЕИК, else (Р55(1))
    a foreign supplier's tax number, else the counterparty record, else the normalised
    name (legacy rows only — Р55(1) makes the ЕИК / tax number mandatory)."""
    inv = invoice or {}
    eik = (inv.get("counterparty_eik") or "").strip()
    if eik:
        return "eik:" + eik
    foreign = (inv.get("counterparty_foreign_tax_no") or "").strip().upper() if isinstance(
        inv.get("counterparty_foreign_tax_no"), str) else ""
    if foreign:
        return "tax:" + foreign
    cp = (inv.get("supplier_counterparty_id") or "").strip() if isinstance(
        inv.get("supplier_counterparty_id"), str) else ""
    if cp:
        return "cp:" + cp
    name = " ".join((inv.get("counterparty_name") or "").lower().split())
    return ("name:" + name) if name else None


async def supplier_number_taken(tenant, invoice: dict, number: str, *, exclude_invoice_id=None,
                                session=None) -> bool:
    """Р53(1): the same supplier + number already exists. FG-248: a LEGACY row written
    before the ``supplier_key`` backfill is matched by its ЕИК or counterparty record too,
    so a duplicate cannot be created before the migration (and break its apply)."""
    key = supplier_key(invoice)
    alternatives = [{"supplier_key": key}]
    eik = (invoice.get("counterparty_eik") or "").strip()
    cp = invoice.get("supplier_counterparty_id") if isinstance(invoice.get("supplier_counterparty_id"), str) else ""
    legacy = {"supplier_key": {"$exists": False}}
    foreign = (invoice.get("counterparty_foreign_tax_no") or "").strip() if isinstance(
        invoice.get("counterparty_foreign_tax_no"), str) else ""
    if eik:
        alternatives.append({**legacy, "counterparty_eik": eik})
    elif foreign:
        alternatives.append({**legacy, "counterparty_foreign_tax_no": {
            "$regex": "^\\s*%s\\s*$" % re.escape(foreign), "$options": "i"}})
    elif cp:
        alternatives.append({**legacy, "counterparty_eik": {"$in": [None, ""]}, "supplier_counterparty_id": cp})
    elif key and key.startswith("name:"):
        alternatives.append({**legacy, "counterparty_eik": {"$in": [None, ""]},
                             "counterparty_name": {"$regex": "^\\s*%s\\s*$" % re.escape(key[5:]),
                                                   "$options": "i"}})
    flt = {"direction": "Received", "invoice_no": number, "$or": alternatives}
    if exclude_invoice_id:
        flt["id"] = {"$ne": exclude_invoice_id}
    return bool(await tenant.invoices.find_one(flt, {"_id": 0, "id": 1}, session=session))


# ── FG-264: one supplier + number is decided under ONE lock document ─────────────
def supplier_lock_id(org_id: str, invoice: dict, number: str) -> str:
    return "supplier_invoice_lock:%s:%s:%s" % (org_id, supplier_key(invoice) or "-", number)


async def ensure_supplier_lock(tenant, invoice: dict, number: str) -> None:
    """Create the lock document OUTSIDE any transaction (idempotent; deterministic _id)."""
    from pymongo.errors import DuplicateKeyError
    try:
        await tenant.org_counters.update_one(
            {"_id": supplier_lock_id(tenant.org_id, invoice, number)},
            {"$setOnInsert": {"counter_type": "supplier_invoice_lock", "value": 0}}, upsert=True)
    except DuplicateKeyError:
        pass


async def lock_supplier_number(tenant, invoice: dict, number: str, *, session) -> None:
    """FG-264: write the (supplier, number) lock document in the caller's transaction —
    two creates / edits of the same supplier + number write-conflict and are serialised,
    so the duplicate check that follows always sees the committed row, with or without
    the unique index (which a legacy database only gets from the migration)."""
    await tenant.org_counters.update_one(
        {"_id": supplier_lock_id(tenant.org_id, invoice, number)}, {"$inc": {"value": 1}},
        session=session)


# ── FG-249 / FG-465: ONE canonical data-quality issue schema ─────────────────────────
# The SAME dq_issues / alarm_events shape as #81 (sync_invoice_issue) and #82
# (sync_credit_note_issue): ``type``, ``title``, ``entity_type`` / ``entity_id``,
# ``status`` open → resolved, ``owner_role``, ``opened_at`` / ``resolved_at``, one alarm per
# issue, an AuditEvent per transition in the caller's transaction; deterministic ids.
DQ_SUPPLIER_TAX_ID_MISSING = "SUPPLIER_TAX_ID_MISSING"
DQ_CREDIT_NOTE_DIFFERENCE = "CREDIT_NOTE_DIFFERENCE"
DQ_DIFFERENCE_LINE_UNDETERMINED = "ACCEPTED_DIFFERENCE_LINE_UNDETERMINED"
DQ_DIFFERENCE_LINE_REVERSED = "ACCEPTED_DIFFERENCE_LINE_REVERSED"
DQ_TITLES = {
    DQ_SUPPLIER_TAX_ID_MISSING: "липсва ЕИК / данъчен номер на доставчика",
    DQ_CREDIT_NOTE_DIFFERENCE: "разлика в кредитно известие",
    DQ_DIFFERENCE_LINE_UNDETERMINED: "приета разлика: не може да се определи склад или обект за реда",
    DQ_DIFFERENCE_LINE_REVERSED: "сторнирана приета разлика: изберете обект или фирма",
    "INDEX_NOT_BUILT": "индекс на базата не е изграден (стари данни) — пазят го други проверки; нужна е миграция",
}


def _dq_slug(dq_type: str) -> str:
    return dq_type.lower().replace("_", "-")


def dq_issue_id(dq_type: str, entity_id: str) -> str:
    return "dq-%s-%s" % (_dq_slug(dq_type), entity_id)


async def open_dq_issue(tenant, *, dq_type: str, entity_type: str, entity_id: str,
                        details: Optional[dict] = None, actor: Optional[dict] = None,
                        session=None) -> bool:
    """Open ONE issue + its alarm per (type, entity) — the #81 / #82 schema. A re-run while
    it is open changes nothing. Returns True when it was opened now."""
    from app.services.invoice_allocation import DQ_OWNER_ROLE, _dq_event
    issue_id, alarm_id = dq_issue_id(dq_type, entity_id), "alarm-%s-%s" % (_dq_slug(dq_type), entity_id)
    existing = await tenant.dq_issues.find_one({"id": issue_id}, {"_id": 0}, session=session)
    if existing and existing.get("status") == "open":
        return False
    at, title = now_iso(), DQ_TITLES.get(dq_type, dq_type)
    await tenant.dq_issues.update_one({"id": issue_id}, {"$set": {
        "id": issue_id, "org_id": tenant.org_id, "type": dq_type, "title": title,
        "entity_type": entity_type, "entity_id": entity_id, "status": "open",
        "owner_role": DQ_OWNER_ROLE, "opened_at": at, "resolved_at": None,
        "details": details or {}, "updated_at": at}}, upsert=True, session=session)
    await tenant.alarm_events.update_one({"id": alarm_id}, {"$set": {
        "id": alarm_id, "org_id": tenant.org_id, "rule_id": dq_type, "rule_name": title,
        "type": "data_quality", "severity": "warning", "status": "active", "triggered_at": at,
        "message": "%s: %s" % (title, entity_id),
        "context": {"entity_id": entity_id, "entity_type": entity_type, "dq_issue_id": issue_id,
                    "details": details or {}},
        "acknowledged_by": None, "acknowledged_at": None, "resolved_by": None,
        "resolved_at": None, "resolve_notes": None}}, upsert=True, session=session)
    await _dq_event(tenant, actor, "dq.%s.opened" % dq_type.lower(), entity_id,
                    {"status": {"before": (existing or {}).get("status"), "after": "open"},
                     "owner_role": DQ_OWNER_ROLE, "details": details or {}},
                    session=session, entity_id=issue_id)
    return True


async def resolve_dq_issue(tenant, *, dq_type: str, entity_id: str, notes: str,
                           resolution: Optional[dict] = None, actor: Optional[dict] = None,
                           session=None) -> bool:
    """Resolve the open issue + alarm (never deleted); AuditEvent. False when none is open."""
    from app.services.invoice_allocation import _dq_event
    issue_id, alarm_id = dq_issue_id(dq_type, entity_id), "alarm-%s-%s" % (_dq_slug(dq_type), entity_id)
    at = now_iso()
    res = await tenant.dq_issues.update_one(
        {"id": issue_id, "status": "open"},
        {"$set": {"status": "resolved", "resolved_at": at, "resolution": resolution or {},
                  "updated_at": at}}, session=session)
    if not res.modified_count:
        return False
    await tenant.alarm_events.update_one(
        {"id": alarm_id}, {"$set": {"status": "resolved", "resolved_at": at,
                                    "resolved_by": (actor or {}).get("id"), "resolve_notes": notes}},
        session=session)
    await _dq_event(tenant, actor, "dq.%s.resolved" % dq_type.lower(), entity_id,
                    {"status": {"before": "open", "after": "resolved"}, "resolution": resolution or {}},
                    session=session, entity_id=issue_id)
    return True


async def sync_awaited_credit_issue(tenant, invoice_id: str, *, actor: Optional[dict] = None,
                                    session=None) -> None:
    """FG-465: the Р47 issue „очаква кредитно известие“ of #82 follows the open
    expected_credit_notes — resolved when the registration closes the last one. The
    helper is #82's own ``invoice_allocation.sync_credit_note_issue`` (carried here
    verbatim until #82 merges — whichever merges second keeps ONE copy)."""
    from app.services.invoice_allocation import sync_credit_note_issue
    await sync_credit_note_issue(tenant, invoice_id, actor=actor, session=session)


async def number_taken(tenant, number: str, *, session=None, exclude_invoice_id=None) -> bool:
    """Is ``number`` already used by an OUR document (outgoing invoice or outgoing note)?
    Supplier numbers (incoming invoices / notes) are another series and never count."""
    flt = {"direction": "Issued", "invoice_no": number}
    if exclude_invoice_id:
        flt["id"] = {"$ne": exclude_invoice_id}
    if await tenant.invoices.find_one(flt, {"_id": 0, "id": 1}, session=session):
        return True
    return bool(await tenant.credit_debit_notes.find_one(
        {"direction": OUTGOING, "number": number}, {"_id": 0, "id": 1}, session=session))


async def take_number(tenant, prefix: str, *, session) -> str:
    """Р49.3: the next number of the ONE sequence shared by invoices and notes. An atomic
    ``$inc`` in the caller's transaction: two concurrent takers get two numbers; an
    aborted transaction gives its number back (no gap, no duplicate).

    FG-218: a number already used (a manual number typed inside the auto series) is
    SKIPPED, inside the same transaction — the series can never block for good."""
    from pymongo import ReturnDocument
    for _ in range(MAX_NUMBER_SKIPS):
        doc = await tenant.org_counters.find_one_and_update(
            number_counter_filter(tenant.org_id),
            {"$inc": {"value": 1}}, return_document=ReturnDocument.AFTER, session=session)
        number = format_number(prefix, int(doc["value"]))
        if not await number_taken(tenant, number, session=session):
            return number
    raise conflict("INVOICE_NUMBER_SERIES_EXHAUSTED",
                   "Не е намерен свободен номер в поредицата — проверете настройките")


# ═══════════════════════════════════════════════════════════════ open balance
DERIVED = ("credited_amount", "debited_amount", "offset_in_amount", "offset_out_amount",
           "refunded_amount")


def adjusted_total(invoice: dict) -> Decimal:
    """What the counterparty owes on the invoice before payments: the invoice's own total
    (never rewritten) − approved credit + approved debit − offsets received + offsets
    given + refunds paid out (Р49.6). Read from the derived sums recomputed in the same
    transaction that changed a source row."""
    inv = invoice or {}
    return (cents(inv.get("total")) - cents(inv.get("credited_amount"))
            + cents(inv.get("debited_amount")) - cents(inv.get("offset_in_amount"))
            + cents(inv.get("offset_out_amount")) + cents(inv.get("refunded_amount")))


def applied_note_filter(invoice_id: str) -> dict:
    return {"original_invoice_id": invoice_id, "status": {"$in": [NOTE_APPROVED, NOTE_REGISTERED]},
            "applied": True}


async def derived_sums(tenant, invoice_id: str, *, session=None) -> Dict[str, float]:
    """The derived sums of one invoice, from the source rows (never incremented)."""
    from app.services.payment_state import active_payments
    credited = debited = Decimal(0)
    async for n in tenant.credit_debit_notes.find(applied_note_filter(invoice_id), {"_id": 0},
                                                  session=session):
        if n.get("kind") == KIND_CREDIT:
            credited += cents(n.get("gross"))
        else:
            debited += cents(n.get("gross"))
    off_in = off_out = Decimal(0)
    async for o in tenant.invoice_offsets.find(
            {"status": OFFSET_APPROVED, "$or": [{"target_invoice_id": invoice_id},
                                                {"source_invoice_id": invoice_id}]},
            {"_id": 0}, session=session):
        if o.get("target_invoice_id") == invoice_id:
            off_in += cents(o.get("amount"))
        if o.get("source_invoice_id") == invoice_id:
            off_out += cents(o.get("amount"))
    refunded = Decimal(0)
    async for p in tenant.finance_payments.find(active_payments({"refund_invoice_id": invoice_id}),
                                                {"_id": 0, "amount": 1}, session=session):
        refunded += cents(p.get("amount"))
    return {"credited_amount": money(credited), "debited_amount": money(debited),
            "offset_in_amount": money(off_in), "offset_out_amount": money(off_out),
            "refunded_amount": money(refunded)}


def open_amounts(invoice: dict, paid) -> Dict[str, float]:
    """remaining (what is still owed on the invoice) and credit_balance (what the tenant
    owes back after a credit on a paid invoice, Р49.6). Never netted automatically."""
    open_ = adjusted_total(invoice) - cents(paid)
    return {"remaining_amount": money(max(open_, Decimal(0))),
            "credit_balance": money(max(-open_, Decimal(0)))}


# ═══════════════════════════════════════════════════════════════ note lines
def _line_index(invoice: dict) -> Dict[str, dict]:
    return {l.get("id"): l for l in (invoice.get("lines") or []) if l.get("id")}


async def resolve_line(tenant, invoice: dict, line_id: str, *, session=None) -> Optional[dict]:
    """The original line a note line points at: an embedded invoice line, or (supplier
    invoices) a row of ``invoice_lines`` of the same invoice. Returns qty / unit price /
    net / VAT rate of the ORIGINAL — the note never trusts a caller's price."""
    line = _line_index(invoice).get(line_id)
    if line is not None:
        qty = Decimal(str(line.get("qty") or 0))
        price = Decimal(str(line.get("unit_price") or 0))
        net = cents(line.get("line_total") if line.get("line_total") is not None else qty * price)
        return {"id": line_id, "qty": qty, "unit_price": price, "net": net,
                "vat_percent": Decimal(str(invoice.get("vat_percent") or 0)),
                "description": line.get("description")}
    row = await tenant.invoice_lines.find_one({"id": line_id, "invoice_id": invoice["id"]},
                                              {"_id": 0}, session=session)
    if row is None:
        return None
    # the supplier line as it was INVOICED (routes/invoice_lines.compute_line): its own
    # net (line_total_ex_vat) and VAT rate (vat_amount / net; a missing vat_percent is the
    # module's default 20 %, the same reading as compute_line)
    qty = Decimal(str(row.get("qty") or 0))
    if row.get("line_total_ex_vat") is not None:
        net = cents(row["line_total_ex_vat"])
    else:
        net = cents(qty * Decimal(str(row.get("unit_price") or 0)))
    price = (Decimal(str(row["unit_price"])) if row.get("unit_price") is not None
             else (net / qty if qty > 0 else Decimal(0)))
    if row.get("vat_amount") is not None and net > 0:
        rate = (Decimal(str(row["vat_amount"])) / net * Decimal(100)).quantize(Decimal("0.0001"))
    else:
        rate = Decimal(str(row.get("vat_percent", 20) or 0))
    return {"id": line_id, "qty": qty, "unit_price": price, "net": net, "vat_percent": rate,
            "description": row.get("description")}


def _strict_positive(value, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise unprocessable(NOTE_INVALID, f"{field}: очаква се число", field=field)
    d = Decimal(str(value))
    if not d.is_finite() or d <= 0:
        raise unprocessable(NOTE_INVALID, f"{field}: очаква се положително число", field=field)
    return d


async def build_note_lines(tenant, invoice: dict, raw_lines, *, session=None) -> List[dict]:
    """Р49 default (FLOW-040 L35): every note line points at a line of the original and
    is given EITHER as a quantity (net = qty × the original unit price) OR as a net
    amount. Net, VAT and gross are kept separately, in whole cents (FLOW-006 L62)."""
    if not isinstance(raw_lines, list) or not raw_lines:
        raise unprocessable(NOTE_INVALID, "Известието трябва да има поне един ред към оригинала")
    out, seen = [], set()
    for i, raw in enumerate(raw_lines):
        if not isinstance(raw, dict):
            raise unprocessable(NOTE_INVALID, "Невалиден ред", index=i)
        line_id = raw.get("original_line_id")
        if not isinstance(line_id, str) or not line_id:
            raise unprocessable(NOTE_INVALID, "Редът трябва да сочи ред от оригиналната фактура",
                                index=i)
        if line_id in seen:
            raise unprocessable(NOTE_INVALID, "Един ред от оригинала се посочва веднъж", index=i)
        seen.add(line_id)
        orig = await resolve_line(tenant, invoice, line_id, session=session)
        if orig is None:
            raise unprocessable(NOTE_INVALID, "Редът не е от оригиналната фактура",
                                original_line_id=line_id)
        has_qty, has_amount = raw.get("qty") is not None, raw.get("amount") is not None
        if has_qty == has_amount:
            raise unprocessable(NOTE_INVALID, "Посочете или количество, или сума (не двете)",
                                original_line_id=line_id)
        if has_qty:
            qty = _strict_positive(raw.get("qty"), "lines[%d].qty" % i)
            net = cents(qty * orig["unit_price"])
        else:
            qty = None
            net = cents(_strict_positive(raw.get("amount"), "lines[%d].amount" % i))
        if net <= 0:
            raise unprocessable(NOTE_INVALID, "Сумата на реда е 0", original_line_id=line_id)
        vat = cents(net * orig["vat_percent"] / Decimal(100))
        out.append({"original_line_id": line_id, "description": orig.get("description"),
                    "qty": float(qty) if qty is not None else None,
                    "unit_price": float(orig["unit_price"]),
                    "net": money(net), "vat": money(vat), "gross": money(net + vat)})
    return out


def note_totals(lines: List[dict]) -> Dict[str, float]:
    net = sum((cents(l["net"]) for l in lines), Decimal(0))
    vat = sum((cents(l["vat"]) for l in lines), Decimal(0))
    return {"net": money(net), "vat": money(vat), "gross": money(net + vat)}


async def credited_by_line(tenant, invoice_id: str, *, session=None,
                           exclude_note_id: Optional[str] = None) -> Dict[str, Decimal]:
    """Net already credited per original line by APPLIED credit notes."""
    out: Dict[str, Decimal] = {}
    flt = {**applied_note_filter(invoice_id), "kind": KIND_CREDIT}
    async for n in tenant.credit_debit_notes.find(flt, {"_id": 0}, session=session):
        if exclude_note_id and n.get("id") == exclude_note_id:
            continue
        for l in n.get("lines") or []:
            out[l["original_line_id"]] = out.get(l["original_line_id"], Decimal(0)) + cents(l["net"])
    return out


async def check_credit_cap(tenant, invoice: dict, lines: List[dict], *, session=None,
                           exclude_note_id: Optional[str] = None) -> None:
    """Р49 / package §2: Σ credited per line ≤ invoiced on the line − already credited.
    Run INSIDE the transaction that claimed the invoice, so concurrent credits on the
    same invoice are serialised and the sum read here is the committed one."""
    done = await credited_by_line(tenant, invoice["id"], session=session,
                                  exclude_note_id=exclude_note_id)
    for l in lines:
        orig = await resolve_line(tenant, invoice, l["original_line_id"], session=session)
        invoiced = orig["net"] if orig else Decimal(0)
        left = invoiced - done.get(l["original_line_id"], Decimal(0))
        if cents(l["net"]) > left:
            raise conflict(CREDIT_EXCEEDS_INVOICED,
                           "Кредитираното по реда надвишава фактурираното минус вече кредитираното",
                           original_line_id=l["original_line_id"], invoiced=money(invoiced),
                           already_credited=money(done.get(l["original_line_id"], Decimal(0))),
                           requested=l["net"], available=money(max(left, Decimal(0))))


# ═══════════════════════════════════════════════════════════════ acts (Р49.5)
async def invoiced_on_act(tenant, act_id: str, *, session=None,
                          exclude_invoice_id: Optional[str] = None) -> Decimal:
    """Net invoiced against an act: issued (non-draft, non-cancelled) invoices of the act,
    minus the net of applied credit notes on them, plus the net of applied debit notes
    whose basis is this act. A credit note gives the part back (Р49.5); the act's own
    quantities are never touched here."""
    total = Decimal(0)
    ids = []
    async for inv in tenant.invoices.find(
            {"act_id": act_id, "status": {"$nin": [DRAFT, CANCELLED]}},
            {"_id": 0, "id": 1, "subtotal": 1}, session=session):
        if exclude_invoice_id and inv["id"] == exclude_invoice_id:
            continue
        total += cents(inv.get("subtotal"))
        ids.append(inv["id"])
    if ids:
        async for n in tenant.credit_debit_notes.find(
                {"original_invoice_id": {"$in": ids}, "kind": KIND_CREDIT, "applied": True,
                 "status": {"$in": [NOTE_APPROVED, NOTE_REGISTERED]}},
                {"_id": 0, "net": 1}, session=session):
            total -= cents(n.get("net"))
    async for n in tenant.credit_debit_notes.find(
            {"basis.type": "act", "basis.id": act_id, "kind": KIND_DEBIT, "applied": True,
             "status": NOTE_APPROVED}, {"_id": 0, "net": 1}, session=session):
        total += cents(n.get("net"))
    return total


async def claim_act(tenant, act_id: str, *, session) -> dict:
    """Read the act in the transaction and WRITE it (``$inc invoice_seq``), so two
    transactions invoicing the same act write-conflict and are serialised."""
    act = await tenant.client_acts.find_one({"id": act_id}, {"_id": 0}, session=session)
    if act is None:
        raise unprocessable(ACT_NOT_APPROVED, "Актът не съществува в тази фирма", act_id=act_id)
    await tenant.client_acts.update_one({"id": act_id}, {"$inc": {"invoice_seq": 1}},
                                        session=session)
    return act


def check_act_approved(act: Optional[dict]) -> None:
    """FLOW-025 L124: a client invoice is based on an approved act."""
    if not act or act.get("status") != "Accepted":
        raise unprocessable(ACT_NOT_APPROVED, "Актът не е одобрен — не може да се фактурира по него",
                            act_id=(act or {}).get("id"))


async def check_act_cap(tenant, act: dict, adding_net: Decimal, *, session,
                        exclude_invoice_id: Optional[str] = None) -> None:
    """Р49.5: an act is never invoiced above its value (net) → 409 ACT_OVER_INVOICED."""
    already = await invoiced_on_act(tenant, act["id"], session=session,
                                    exclude_invoice_id=exclude_invoice_id)
    value = cents(act.get("subtotal"))
    if already + cents(adding_net) > value:
        raise conflict(ACT_OVER_INVOICED, "Фактурираното по акта надвишава стойността му",
                       act_id=act["id"], act_value=money(value), already_invoiced=money(already),
                       requested=money(adding_net),
                       available=money(max(value - already, Decimal(0))))


# ═══════════════════════════════════════════════════════════════ contract scope
def contract_key(invoice: dict) -> Optional[tuple]:
    """D2 (debt): there is no contract model on invoices in main. The strictest scope
    available stands for "the same contract": the same direction, the same project AND
    the same counterparty ЕИК, all present. Anything less → not the same contract."""
    inv = invoice or {}
    eik = (inv.get("counterparty_eik") or "").strip()
    if not inv.get("project_id") or not eik:
        return None
    return (inv.get("direction"), inv.get("project_id"), eik)


# ═══════════════════════════════════════════════════════════════ Р47 / Р49.8
def expected_escalation(row: dict, now: Optional[datetime] = None) -> dict:
    """Escalation of an open "очаква кредитно известие" task to the Owner after
    EXPECTED_CREDIT_ESCALATION_DAYS from the reversal — computed on read, never stored."""
    now = now or datetime.now(timezone.utc)
    created = row.get("created_at")
    try:
        at = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return {"due_at": None, "escalate_to_owner": False}
    due = at + timedelta(days=EXPECTED_CREDIT_ESCALATION_DAYS)
    return {"due_at": due.isoformat(),
            "escalate_to_owner": row.get("status") == "open" and now > due}


# ═══════════════════════════════════════════════════════════════ indexes
#: The unique indexes INV-CN-01 relies on, created idempotently before the first
#: transaction that needs them (an index build must not run inside a transaction).
#: Partial filters: only documents that carry the field are constrained, so legacy
#: rows (no ``issued_number``) are never touched or refused.
#: FG-217: the invoice-number index of OUR series and the supplier series, separately
#: (``direction`` in the key), only for documents that carry a non-empty number — a draft
#: has none. Replaces the legacy unique+sparse (org_id, invoice_no) index, which indexes
#: a missing number as null (the second draft → DuplicateKeyError). The legacy index is
#: dropped only by the migration (``invoice_corrections_migration``).
INVOICE_NO_INDEX = ("invoices", [("org_id", 1), ("direction", 1), ("invoice_no", 1)],
                    {"name": "inv_cn_02_outgoing_invoice_no", "unique": True,
                     "partialFilterExpression": {"direction": "Issued", "invoice_no": {"$gt": ""}}})
#: FG-231 / Р53(1): a supplier invoice is a duplicate only for the SAME supplier + number.
SUPPLIER_NO_INDEX = ("invoices", [("org_id", 1), ("supplier_key", 1), ("invoice_no", 1)],
                     {"name": "inv_cn_02_supplier_invoice_no", "unique": True,
                      "partialFilterExpression": {"direction": "Received", "invoice_no": {"$gt": ""}}})
#: index names of earlier versions, replaced by the migration
SUPERSEDED_INDEX_NAMES = ("inv_cn_01_invoice_no_by_direction",)

PLANNED_INDEXES = (
    INVOICE_NO_INDEX,
    SUPPLIER_NO_INDEX,
    ("invoices", [("org_id", 1), ("issued_number", 1)],
     {"name": "inv_cn_01_issued_number_unique", "unique": True,
      "partialFilterExpression": {"issued_number": {"$type": "string"}}}),
    ("credit_debit_notes", [("org_id", 1), ("id", 1)],
     {"name": "inv_cn_01_note_id_unique", "unique": True}),
    ("credit_debit_notes", [("org_id", 1), ("number", 1)],
     {"name": "inv_cn_01_outgoing_number_unique", "unique": True,
      "partialFilterExpression": {"direction": OUTGOING, "number": {"$type": "string"}}}),
    ("credit_debit_notes", [("org_id", 1), ("supplier_key", 1), ("number", 1)],
     {"name": "inv_cn_01_incoming_number_unique", "unique": True,
      "partialFilterExpression": {"direction": INCOMING, "number": {"$type": "string"}}}),
    ("credit_debit_notes", [("org_id", 1), ("original_invoice_id", 1)],
     {"name": "inv_cn_01_note_by_invoice"}),
    ("invoice_offsets", [("org_id", 1), ("id", 1)],
     {"name": "inv_cn_01_offset_id_unique", "unique": True}),
    ("org_counters", [("org_id", 1), ("counter_type", 1)],
     {"name": "inv_cn_01_number_counter_unique", "unique": True,
      "partialFilterExpression": {"counter_type": NUMBER_COUNTER}}),
)

_ensured: set = set()

#: INV84-N2 — what each planned index guards, and the OTHER guard of that invariant (the
#: write path never depends on the unique index alone; a missing index is a DQ issue).
INDEX_GUARDS = {
    "inv_cn_02_outgoing_invoice_no": ("our invoice numbers are unique per tenant",
                                      "counter $inc / series lock in the issue transaction"),
    "inv_cn_02_supplier_invoice_no": ("one supplier invoice per (supplier, number)",
                                      "(supplier, number) lock document (FG-264)"),
    "inv_cn_01_issued_number_unique": ("an issued number is given once",
                                       "counter $inc / series lock in the issue transaction"),
    "inv_cn_01_note_id_unique": ("one note per id", "deterministic id + Idempotency-Key registry"),
    "inv_cn_01_outgoing_number_unique": ("our note numbers are unique (shared series)",
                                         "counter $inc in the approval transaction"),
    "inv_cn_01_incoming_number_unique": ("one supplier note per (supplier, number)",
                                         "(supplier, note number) lock document (INV84-N2)"),
    "inv_cn_01_note_by_invoice": ("read speed only", "—"),
    "inv_cn_01_offset_id_unique": ("one offset per id", "deterministic id + Idempotency-Key registry"),
    "inv_cn_01_number_counter_unique": ("one shared number counter per tenant",
                                        "deterministic counter _id (INV84-N2)"),
}
#: index builds that failed, per database handle: {repr(db): {name: error}}
_index_failures: Dict[str, Dict[str, str]] = {}
DQ_INDEX_NOT_BUILT = "INDEX_NOT_BUILT"
INDEX_RETRY_SECONDS = 600           # a failed build is retried at most every 10 minutes
_retry_at: Dict[str, float] = {}
_recorded: Dict[str, frozenset] = {}


async def ensure_indexes(database) -> None:
    """Create the planned indexes on the tenant's operational database (once per process
    and database handle). Idempotent: an existing identical index is a no-op."""
    import time
    name = repr(database)          # the client + database it names
    if name in _ensured or time.monotonic() < _retry_at.get(name, 0):
        return
    _retry_at[name] = time.monotonic() + INDEX_RETRY_SECONDS
    # one explicit call per collection (the A2C guard sees every collection named)
    plan = {}
    for coll, keys, opts in PLANNED_INDEXES:
        plan.setdefault(coll, []).append((keys, opts))
    # FG-264 / WH-FIX-01 merge: an index build on a write path is NEVER fatal — wherever the
    # existing data refuses a unique build (legacy collisions, or a test double that does not
    # honour partialFilterExpression on a build), the write keeps its own serialised check
    # (counter / lock documents) and the migration (inv_cn_01_migrate.py) builds the index.
    import logging
    log = logging.getLogger(__name__)

    failures = _index_failures.setdefault(name, {})

    def _skip(opts, exc):
        log.warning("INV-CN-01 index %s not built now: %s", opts.get("name"), exc)
        failures[opts.get("name")] = str(exc)[:300]

    for keys, opts in plan["invoices"]:
        try:
            await database.invoices.create_index(keys, **opts)
            failures.pop(opts["name"], None)
        except Exception as exc:                                   # noqa: BLE001
            _skip(opts, exc)
    for keys, opts in plan["credit_debit_notes"]:
        try:
            await database.credit_debit_notes.create_index(keys, **opts)
            failures.pop(opts["name"], None)
        except Exception as exc:                                   # noqa: BLE001
            _skip(opts, exc)
    for keys, opts in plan["invoice_offsets"]:
        try:
            await database.invoice_offsets.create_index(keys, **opts)
            failures.pop(opts["name"], None)
        except Exception as exc:                                   # noqa: BLE001
            _skip(opts, exc)
    for keys, opts in plan["org_counters"]:
        try:
            await database.org_counters.create_index(keys, **opts)
            failures.pop(opts["name"], None)
        except Exception as exc:                                   # noqa: BLE001
            _skip(opts, exc)
    if not failures:
        _ensured.add(name)          # a failed build is retried at the next write (FG-264)


async def record_index_health(tenant, database) -> List[dict]:
    """INV84-N2: every planned index whose build failed on this database → ONE DQ issue +
    alarm (the #81 / #82 schema, visible to the Owner / Admin / Accountant), naming the
    invariant and its other guard; an index built later resolves it. Idempotent."""
    failed = _index_failures.get(repr(database), {})
    key = "%s|%s" % (repr(database), tenant.org_id)
    if _recorded.get(key) == frozenset(failed):
        return [{"index": n} for n in failed]          # nothing changed since the last record
    _recorded[key] = frozenset(failed)
    out = []
    for _coll, _keys, opts in PLANNED_INDEXES:
        index_name = opts["name"]
        invariant, guard = INDEX_GUARDS.get(index_name, ("", ""))
        if index_name in failed:
            await open_dq_issue(tenant, dq_type=DQ_INDEX_NOT_BUILT, entity_type="index",
                                entity_id=index_name,
                                details={"invariant": invariant, "other_guard": guard,
                                         "error": failed[index_name],
                                         "remedy": "scripts/inv_cn_01_migrate.py (dry run → Owner → --apply)"})
            out.append({"index": index_name, "invariant": invariant, "other_guard": guard})
        else:
            await resolve_dq_issue(tenant, dq_type=DQ_INDEX_NOT_BUILT, entity_id=index_name,
                                   notes="index built")
    return out


# ═══════════════════════════════════════════════════════════════ shared reads
async def payable_net(tenant, invoice: dict, *, session=None) -> Decimal:
    """FG-571 — THE payable net of an invoice: its own total after the APPROVED credit /
    debit notes, offsets and refunds (``adjusted_total`` of the derived sums read in
    ``session``), before payments. The one function every check of "how much is owed on
    this invoice" uses — #82's Р47 payment check calls it at merge instead of the raw
    ``invoice.total`` (whichever merges second)."""
    derived = await derived_sums(tenant, invoice["id"], session=session)
    return adjusted_total({**invoice, **derived})


async def payable_until_credit_note(tenant, invoice: dict, *, session=None) -> Decimal:
    """FG-571 / Р47 — what may still be paid (or offset) on a supplier invoice while it
    awaits credit notes: payable net − active payments − the open awaited credit. Not
    clamped (< 0 means nothing may be paid). #82's Р47 check and the Р74 offset check
    both read this."""
    return (await current_open(tenant, invoice, session=session)
            - await awaited_credit(tenant, invoice["id"], session=session))


async def current_open(tenant, invoice: dict, *, session=None) -> Decimal:
    """The invoice's open amount NOW, from the source rows read in ``session``:
    > 0 still owed, < 0 owed back (credit balance)."""
    from app.services.payment_state import active_allocations
    paid = Decimal(0)
    async for a in tenant.payment_allocations.find(active_allocations({"invoice_id": invoice["id"]}),
                                                   {"_id": 0, "amount_allocated": 1}, session=session):
        paid += cents(a.get("amount_allocated"))
    return await payable_net(tenant, invoice, session=session) - paid


INVOICE_AWAITS_CREDIT_NOTE = "INVOICE_AWAITS_CREDIT_NOTE"     # the code #82 (Р47) uses


async def awaited_credit(tenant, invoice_id: str, *, session=None) -> Decimal:
    """Р47 / Р74 (FG-453): the credit a supplier invoice still awaits — Σ of its OPEN
    expected_credit_notes (the same reading as #82's ``finance._awaited_credit``)."""
    total = Decimal(0)
    async for r in tenant.expected_credit_notes.find(
            {"invoice_id": invoice_id, "status": "open"}, {"_id": 0, "amount": 1}, session=session):
        total += cents(r.get("amount"))
    return total


EXPECTED_LINK_REQUIRED = "EXPECTED_CREDIT_LINK_REQUIRED"
EXPECTED_LINK_INVALID = "EXPECTED_CREDIT_LINK_INVALID"


async def check_expected_link(tenant, invoice_id: str, ids, *, session=None) -> List[dict]:
    """FG-220 / Р49.8 „свързва се от Счетоводителя“: the Accountant names the awaited
    credit(s) explicitly (``expected_credit_note_ids``) — the system never links by
    amount. A supplier invoice with an open awaited credit cannot get a credit note
    without the link (422); every named row must be an OPEN row of THIS invoice (422)."""
    open_rows = await tenant.expected_credit_notes.find(
        {"invoice_id": invoice_id, "status": "open"}, {"_id": 0}, session=session).to_list(1000)
    if ids is None:
        if open_rows:
            raise unprocessable(EXPECTED_LINK_REQUIRED,
                                "Фактурата очаква кредитно известие — посочете кое очаквано "
                                "известие се покрива (expected_credit_note_ids)",
                                open=[r.get("id") for r in open_rows])
        return []
    if (not isinstance(ids, list) or not ids or len(set(ids)) != len(ids)
            or not all(isinstance(i, str) and i for i in ids)):
        raise unprocessable(EXPECTED_LINK_INVALID, "expected_credit_note_ids: списък от идентификатори")
    by_id = {r.get("id"): r for r in open_rows}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise unprocessable(EXPECTED_LINK_INVALID,
                            "Очакваното известие не е отворено за тази фактура", ids=missing)
    return [by_id[i] for i in ids]


async def match_expected_credit(tenant, invoice_id: str, gross, note_id: str, rows: List[dict], *,
                                session, actor: Optional[dict] = None) -> dict:
    """Р47 + Р49.8 (FG-219, FG-220): the registered supplier credit note is linked by the
    Accountant with the NAMED awaited rows (``expected_credit_notes`` of PR #82).

      * no row named (nothing awaited) → the note applies (payable reduced);
      * Σ named rows equals the note EXACTLY in whole cents (difference 0.00) → the rows
        are fulfilled, their DQ tasks close, the payment limit is recomputed;
      * any difference (1 cent too) → the rows stay open (the limit stays) and get the
        DQ „разлика в кредитно известие“; the note is registered but NOT applied."""
    if not rows:
        return {"applied": True, "expected": None, "matched": None}
    expected = sum((cents(r.get("amount")) for r in rows), Decimal(0))
    at = now_iso()
    ids = [r["id"] for r in rows]
    if expected - cents(gross) == MATCH_TOLERANCE:
        res = await tenant.expected_credit_notes.update_many(
            {"id": {"$in": ids}, "invoice_id": invoice_id, "status": "open"},
            {"$set": {"status": "fulfilled", "credit_note_id": note_id, "fulfilled_at": at}},
            session=session)
        if res.modified_count != len(ids):
            raise conflict(EXPECTED_LINK_INVALID, "Очакваното известие вече е покрито")
        # Р52(2a): a corrected note resolves the earlier mismatch issue(s); the mismatched
        # note stays registered (never applied) and is marked superseded by this one.
        async for old in tenant.credit_debit_notes.find(
                {"expected_link.rows": {"$in": ids}, "applied": False, "id": {"$ne": note_id}},
                {"_id": 0, "id": 1}, session=session):
            await resolve_dq_issue(tenant, dq_type=DQ_CREDIT_NOTE_DIFFERENCE, entity_id=old["id"],
                                   notes="corrected credit note registered",
                                   resolution={"corrected_by_credit_note_id": note_id},
                                   actor=actor, session=session)
        await tenant.credit_debit_notes.update_many(
            {"expected_link.rows": {"$in": ids}, "applied": False, "id": {"$ne": note_id}},
            {"$set": {"superseded_by": note_id, "updated_at": at}}, session=session)
        if not await tenant.expected_credit_notes.find_one(
                {"invoice_id": invoice_id, "status": "open"}, {"_id": 0, "id": 1}, session=session):
            await tenant.invoices.update_one({"id": invoice_id},
                                             {"$set": {"awaiting_credit_note": False}}, session=session)
        # FG-465: the Р47 issue „очаква кредитно известие“ (#82) follows the open rows
        await sync_awaited_credit_issue(tenant, invoice_id, actor=actor, session=session)
        return {"applied": True, "expected": money(expected), "matched": True, "rows": ids}
    await open_dq_issue(tenant, dq_type=DQ_CREDIT_NOTE_DIFFERENCE, entity_type="finance.credit_note",
                        entity_id=note_id, actor=actor, session=session,
                        details={"invoice_id": invoice_id, "rows": ids, "expected": money(expected),
                                 "registered": money(cents(gross))})
    return {"applied": False, "expected": money(expected), "matched": False, "rows": ids,
            "dq": DQ_TITLES[DQ_CREDIT_NOTE_DIFFERENCE],
            "dq_issue_id": dq_issue_id(DQ_CREDIT_NOTE_DIFFERENCE, note_id)}


async def linked_to_warehouse(tenant, invoice: dict, *, session=None) -> bool:
    """Р51(3) / FG-233: is a supplier invoice linked to a warehouse receipt? A canonical
    ledger movement that names the invoice itself (``invoice_id``, with or without a
    line) or any of its ``invoice_lines`` rows. In a transaction the caller also bumps
    the line locks (``lock_invoice_lines``), so a linked receipt racing the cancel of the
    same line is serialised."""
    from app.services.invoice_line_lock import first_linked_movement
    if await tenant.warehouse_transactions.find_one(
            {"action": {"$exists": True}, "invoice_id": invoice["id"]}, {"_id": 0, "movement_id": 1},
            session=session):
        return True
    async for line in tenant.invoice_lines.find({"invoice_id": invoice["id"]}, {"_id": 0, "id": 1},
                                                session=session):
        if await first_linked_movement(tenant, line["id"], session=session):
            return True
    return False


async def ensure_invoice_line_locks(tenant, invoice: dict) -> None:
    """FG-233, OUTSIDE the transaction: create the per-line lock documents (idempotent)."""
    from app.services.invoice_line_lock import ensure_line_lock
    async for l in tenant.invoice_lines.find({"invoice_id": invoice["id"]}, {"_id": 0, "id": 1}):
        await ensure_line_lock(tenant, l["id"])


async def lock_invoice_lines(tenant, invoice: dict, *, session) -> None:
    """FG-233, INSIDE the transaction: write the per-line lock document of every line of
    the invoice (the same document a linked receipt writes in ITS transaction), so the
    cancel and a receipt of the same line are serialised (WriteConflict → retry)."""
    from app.services.invoice_line_lock import bump_line_lock
    if session is None:
        return
    async for l in tenant.invoice_lines.find({"invoice_id": invoice["id"]}, {"_id": 0, "id": 1},
                                             session=session):
        await bump_line_lock(tenant, l["id"], session=session)


async def pending_debit(tenant, invoice_id: str, *, session=None) -> Decimal:
    """Р51(2): gross of supplier debit notes registered but not yet approved by the Owner —
    the increase they ask for is NOT payable until approved."""
    total = Decimal(0)
    async for n in tenant.credit_debit_notes.find(
            {"original_invoice_id": invoice_id, "kind": KIND_DEBIT, "status": NOTE_PENDING},
            {"_id": 0, "gross": 1}, session=session):
        total += cents(n.get("gross"))
    return total


async def _applied_supplier_notes(tenant):
    async for n in tenant.credit_debit_notes.find(
            {"direction": INCOMING, "applied": True, "status": {"$in": [NOTE_REGISTERED, NOTE_APPROVED]}},
            {"_id": 0}):
        yield n


def _project_share(row: dict, project_id: str) -> Decimal:
    """The share of a supplier invoice line allocated DIRECTLY to the project (Path B
    selection rule, ``effective_allocations``): Σ allocated qty / line qty, else 1."""
    from app.services.canonical_material_cost import effective_allocations
    mine = [a for a in effective_allocations(row) if a.get("type") == "project" and a.get("ref_id") == project_id]
    if not mine:
        return Decimal(0)
    qty = Decimal(str(row.get("qty") or 0))
    if qty > 0 and all(a.get("qty") is not None for a in mine):
        return min(sum((Decimal(str(a["qty"])) for a in mine), Decimal(0)) / qty, Decimal(1))
    return Decimal(1)


async def supplier_note_cost_lines(tenant, project_id: str, counted_by_line: Dict[str, float]) -> List[dict]:
    """Р52(1) / D8, FG-247 — the cost lines of supplier credit / debit notes for ONE
    project, added by ``canonical_material_cost.project_material_cost`` (THE single cost
    source of every reader — P&L, full cost, financial results, SMR reports; D-04).

    * only a note WITHOUT a receipt reversal counts (a note linked to a reversal changes
      the payable only — the reversal already removed the cost);
    * only a line that IS in this project's cost base counts: a supplier invoice line
      allocated directly to the project (Path B), by the project's share; a credit never
      takes more than the line's counted value here (it cannot go below 0); an embedded
      finance-invoice line or a line received into the warehouse is no Path B cost of the
      project → no effect here (the latter's value is the FIFO layer, FLOW-009 — debt);
    * each line is dated by the note's own date → its period (Р49.7)."""
    from app.services.canonical_material_cost import _moment, period_of
    out: List[dict] = []
    remaining = {k: Decimal(str(v)) for k, v in counted_by_line.items()}
    notes = [n async for n in _applied_supplier_notes(tenant)]
    notes.sort(key=lambda n: (str(n.get("issue_date") or ""), str(n.get("created_at") or "")))
    for n in notes:
        if (n.get("expected_link") or {}).get("rows"):
            out.extend(await _accepted_difference_lines(tenant, project_id, n, counted_by_line))
            continue
        credit = n.get("kind") == KIND_CREDIT
        at = _moment(n.get("issue_date") or n.get("created_at"))
        for l in n.get("lines") or []:
            line_id = l.get("original_line_id")
            if line_id not in remaining:
                continue
            row = await tenant.invoice_lines.find_one({"id": line_id}, {"_id": 0})
            share = _project_share(row or {}, project_id)
            if share <= 0:
                continue
            effect = cents(cents(l.get("net")) * share)
            if credit:
                effect = min(effect, max(remaining[line_id], Decimal(0)))
                remaining[line_id] -= effect
                value = -effect
            else:
                remaining[line_id] += effect
                value = effect
            if value == 0:
                continue
            out.append({"source": "supplier_note", "kind": "credit_note" if credit else "debit_note",
                        "waste": False, "value": float(value), "qty": 0.0, "item_id": None,
                        "unit": None, "material_name": l.get("description") or "",
                        "package_id": None, "at": at, "period": period_of(at), "ref": n.get("id"),
                        "invoice_line_id": line_id, "note_number": n.get("number")})
    return out


async def _accepted_difference_lines(tenant, project_id: str, note: dict,
                                     counted_by_line: Dict[str, float]) -> List[dict]:
    """Р55(3) / FG-251: when the Owner ACCEPTED a difference between a supplier credit
    note linked to a receipt reversal and the credit it awaited, the part the supplier
    did not credit stays a cost of the ORIGINAL line's project / SMR, in the period of
    the acceptance. Read from the note's append-only ``difference_accepted.postings``
    (booking at acceptance, FG-277 resolution, FG-276 reversal / re-booking), only the
    ``project`` postings: a direct delivery names its project (FG-269, the whole part);
    a line allocated to projects takes this project's direct share (Path B)."""
    from app.services.canonical_material_cost import _moment
    acc = note.get("difference_accepted") or {}
    postings = acc.get("postings")
    if postings is None:
        return await _legacy_accepted_difference_lines(tenant, project_id, note, counted_by_line)
    descriptions = {l.get("original_line_id"): l.get("description") or "" for l in note.get("lines") or []}
    out: List[dict] = []
    for p in postings:
        if p.get("target") != COST_TARGET_PROJECT:
            continue
        line_id = p["original_line_id"]
        net = cents(p.get("net"))
        if p.get("project_id"):
            if p["project_id"] != project_id:
                continue
            value = net
        else:
            if line_id not in counted_by_line:
                continue                                   # not a line of THIS project
            row = await tenant.invoice_lines.find_one({"id": line_id}, {"_id": 0})
            value = cents(net * _project_share(row or {}, project_id))
        if value == 0:
            continue
        at = _moment(p.get("at"))
        out.append({"source": "supplier_note", "kind": "accepted_difference", "waste": False,
                    "value": float(value), "qty": 0.0, "item_id": None, "unit": None,
                    "material_name": descriptions.get(line_id, ""), "package_id": p.get("package_id"),
                    "at": at, "period": p["period"], "ref": note.get("id"), "invoice_line_id": line_id,
                    "note_number": note.get("number"), "posting": p.get("kind"), "posting_id": p.get("id")})
    return out


async def _legacy_accepted_difference_lines(tenant, project_id: str, note: dict,
                                            counted_by_line: Dict[str, float]) -> List[dict]:
    """A note accepted before the posting journal existed (no ``postings``): FG-251 as it was."""
    from app.services.canonical_material_cost import _moment, period_of
    acc = note.get("difference_accepted") or {}
    if not acc:
        return []
    diff_gross = cents(acc.get("expected")) - cents(acc.get("registered"))
    note_gross, note_net = cents(note.get("gross")), cents(note.get("net"))
    if diff_gross <= 0 or note_gross <= 0 or note_net <= 0:
        return []
    diff_net = cents(diff_gross * note_net / note_gross)
    at = _moment(acc.get("at"))
    out: List[dict] = []
    for l in note.get("lines") or []:
        line_id = l.get("original_line_id")
        if line_id not in counted_by_line:
            continue
        row = await tenant.invoice_lines.find_one({"id": line_id}, {"_id": 0})
        value = cents(diff_net * cents(l.get("net")) / note_net * _project_share(row or {}, project_id))
        if value <= 0:
            continue
        out.append({"source": "supplier_note", "kind": "accepted_difference", "waste": False,
                    "value": float(value), "qty": 0.0, "item_id": None, "unit": None,
                    "material_name": l.get("description") or "", "package_id": None, "at": at,
                    "period": period_of(at), "ref": note.get("id"), "invoice_line_id": line_id,
                    "note_number": note.get("number")})
    return out


COST_TARGET_COMPANY = "company"
COST_TARGET_PROJECT = "project"
COST_TARGET_UNDETERMINED = "undetermined"
# Р64 (D20 / FG-415): a project NOT in one of these statuses (closed technically or
# financially, warranty, archived, cancelled, finished, stopped …) — every Р63 re-booking
# onto it needs the Owner, even to the same place; re-checked at the approval.
OPEN_PROJECT_STATUSES = ("Active", "Paused")


async def rebooking_projects(tenant, line_id: str, target: str, project_id: Optional[str], *,
                             session=None) -> List[str]:
    """The projects a re-booking lands on: the named one, or — "back to the line's own
    allocation" — the projects of the invoice line's allocations."""
    if target != COST_TARGET_PROJECT:
        return []
    if project_id:
        return [project_id]
    from app.services.canonical_material_cost import effective_allocations
    row = await tenant.invoice_lines.find_one(
        {"id": line_id}, {"_id": 0, "allocations": 1, "allocation_type": 1, "allocation_ref_id": 1,
                          "qty": 1}, session=session) or {}
    # INV84-R64-1: EVERY allocation shape (allocations[].ref_id / refId, and the deprecated
    # single allocation_type / allocation_ref_id) — the same reading as the cost source
    return sorted({a["ref_id"] for a in effective_allocations(row)
                   if a.get("type") == "project" and a.get("ref_id")})


async def project_statuses(tenant, project_ids: List[str], *, session=None) -> Dict[str, Optional[str]]:
    out: Dict[str, Optional[str]] = {pid: None for pid in project_ids}
    if project_ids:
        async for p in tenant.projects.find({"id": {"$in": project_ids}}, {"_id": 0, "id": 1, "status": 1},
                                            session=session):
            out[p["id"]] = p.get("status")
    return out


def any_project_closed(statuses: Dict[str, Optional[str]], target: Optional[str] = None) -> bool:
    """Р64: a missing project, or one not Active / Paused, counts as closed. INV84-R64-1:
    fail closed — a PROJECT destination whose project cannot be resolved at all (no named
    project, no readable allocation) counts as closed too, so it is a proposal."""
    if target == COST_TARGET_PROJECT and not statuses:
        return True
    return any(st not in OPEN_PROJECT_STATUSES for st in statuses.values())
POSTING_BOOKING = "booking"            # at the Owner's acceptance (Р55(3) / Р58)
POSTING_RESOLUTION = "resolution"      # FG-277: the Accountant decides an open line
POSTING_REVERSAL = "reversal"          # FG-276: the Owner reverses (append-only)
COMPANY_LOSSES_LABEL = "Фирмени загуби (не се разпределят)"
COMPANY_LOSSES_INCLUDES = ("Приети разлики по кредитни известия на доставчици за стока, приета в склада "
                           "(загуба от връщане, Р58), в периода на приемането. Не са в резултата на "
                           "обектите и не са в базата за разпределение на режийни.")
_RECEIVE_TO_WAREHOUSE = "receive_from_supplier"
_RECEIVE_TO_PROJECT = "receive_from_supplier_to_project"


async def classify_difference_line(tenant, invoice_id: str, line_id: str, *, session=None) -> dict:
    """Р58 / FG-269 / FG-270: where is the accepted difference of ONE invoice line a cost?
    Decided PER LINE by the destination of the line's own canonical receipt(s):

    * every receipt of the line went INTO A WAREHOUSE (``receive_from_supplier``) →
      ``company`` (Р58: loss on the return; FIFO untouched);
    * every receipt of the line was a DIRECT delivery to ONE project
      (``receive_from_supplier_to_project``) → ``project`` of that delivery (Р55(3));
    * receipts of both kinds, or direct deliveries to several projects → ``undetermined``;
    * no receipt of the line: a line allocated to a project (Path B) → ``project`` (FG-251);
      otherwise, if the invoice has a receipt linked ONLY by ``invoice_id`` (no line), the
      line cannot be determined → ``undetermined`` (such a receipt never reclassifies a
      line by itself); with no receipt at all → ``project`` (FG-251, unchanged).

    ``undetermined`` books no cost automatically; the caller opens a DQ."""
    from app.services.warehouse_movements.projections import _project_of
    kinds, projects = set(), set()
    async for r in tenant.warehouse_transactions.find(
            {"invoice_line_id": line_id, "action": {"$in": [_RECEIVE_TO_WAREHOUSE, _RECEIVE_TO_PROJECT]}},
            {"_id": 0, "action": 1, "destination": 1, "project_id": 1}, session=session):
        if r["action"] == _RECEIVE_TO_WAREHOUSE:
            kinds.add(COST_TARGET_COMPANY)
        else:
            kinds.add(COST_TARGET_PROJECT)
            projects.add(_project_of(r.get("destination"), r.get("project_id")) or r.get("project_id"))
    if kinds == {COST_TARGET_COMPANY}:
        return {"target": COST_TARGET_COMPANY, "basis": "warehouse_receipt"}
    if kinds == {COST_TARGET_PROJECT} and len(projects) == 1 and None not in projects:
        return {"target": COST_TARGET_PROJECT, "basis": "direct_delivery", "project_id": projects.pop()}
    if kinds:
        return {"target": COST_TARGET_UNDETERMINED, "basis": "mixed_receipts"}
    from app.services.canonical_material_cost import effective_allocations
    row = await tenant.invoice_lines.find_one(
        {"id": line_id}, {"_id": 0, "allocations": 1, "allocation_type": 1, "allocation_ref_id": 1,
                          "qty": 1}, session=session) or {}
    if any(a.get("type") == "project" for a in effective_allocations(row)):   # INV84-R64-1
        return {"target": COST_TARGET_PROJECT, "basis": "allocation"}
    if await tenant.warehouse_transactions.find_one(
            {"action": {"$in": [_RECEIVE_TO_WAREHOUSE, _RECEIVE_TO_PROJECT]}, "invoice_id": invoice_id,
             "invoice_line_id": {"$in": [None, ""]}}, {"_id": 0, "action": 1}, session=session):
        return {"target": COST_TARGET_UNDETERMINED, "basis": "invoice_level_receipt"}
    return {"target": COST_TARGET_PROJECT, "basis": "no_receipt"}


async def split_accepted_difference(tenant, note: dict, diff_gross: Decimal, *, session=None,
                                    actor: Optional[dict] = None) -> List[dict]:
    """Р55(3) + Р58: split the accepted (uncredited) difference over the note's lines, net
    of VAT by the note's own VAT ratio, and say WHERE each part is a cost — frozen at the
    moment of acceptance (``classify_difference_line``). An ``undetermined`` line opens a
    canonical DQ for the Accountant and is booked nowhere automatically (FG-270)."""
    note_gross, note_net = cents(note.get("gross")), cents(note.get("net"))
    if diff_gross <= 0 or note_gross <= 0 or note_net <= 0:
        return []
    diff_net = cents(diff_gross * note_net / note_gross)
    lines = [l for l in note.get("lines") or [] if cents(l.get("net")) > 0]
    out: List[dict] = []
    left = diff_net
    for i, l in enumerate(lines):
        part = left if i == len(lines) - 1 else cents(diff_net * cents(l.get("net")) / note_net)
        left -= part
        cls = await classify_difference_line(tenant, note["original_invoice_id"], l.get("original_line_id"),
                                             session=session)
        entry = {"original_line_id": l.get("original_line_id"), "net": money(part), **cls}
        if cls["target"] == COST_TARGET_UNDETERMINED:
            await open_dq_issue(
                tenant, dq_type=DQ_DIFFERENCE_LINE_UNDETERMINED, entity_type="finance.credit_note_line",
                entity_id="%s:%s" % (note["id"], l.get("original_line_id")), actor=actor,
                details={"net": entry["net"], "basis": cls.get("basis")}, session=session)
        out.append(entry)
    return out


def _posting(kind: str, line_id: str, net: Decimal, target: str, at: str, *, period: str,
             by: str, reason: Optional[str] = None, project_id: Optional[str] = None,
             package_id: Optional[str] = None, basis: Optional[str] = None) -> dict:
    return {"id": "dp_" + uuid.uuid4().hex[:16], "kind": kind, "original_line_id": line_id,
            "net": money(net), "target": target, "project_id": project_id, "package_id": package_id,
            "basis": basis, "at": at, "period": period, "by": by, "reason": reason}


def initial_postings(split: List[dict], at: str, by: str, reason: str) -> List[dict]:
    """The bookings made at the acceptance: every line whose target is known (company /
    project). An ``undetermined`` line books nothing until FG-277 resolves it."""
    return [_posting(POSTING_BOOKING, s["original_line_id"], cents(s["net"]), s["target"], at,
                     period=at[:7], by=by, reason=reason, project_id=s.get("project_id"),
                     basis=s.get("basis"))
            for s in split if s["target"] in (COST_TARGET_COMPANY, COST_TARGET_PROJECT) and cents(s["net"]) != 0]


def booked_by_line(postings: List[dict]) -> Dict[str, Decimal]:
    """The net currently booked per line (bookings + resolutions − reversals)."""
    out: Dict[str, Decimal] = {}
    for p in postings or []:
        out[p["original_line_id"]] = out.get(p["original_line_id"], Decimal(0)) + cents(p.get("net"))
    return out


def open_difference_lines(note: dict) -> List[dict]:
    """FG-277 / FG-276: the lines of an accepted difference that are booked NOWHERE now —
    ``undetermined`` at acceptance, or reversed by the Owner — with what is to book."""
    acc = note.get("difference_accepted") or {}
    postings = acc.get("postings") or []
    booked = booked_by_line(postings)
    reversed_lines = {p["original_line_id"] for p in postings if p.get("kind") == POSTING_REVERSAL}
    decided = {d["proposal_id"] for d in acc.get("decisions") or []}
    pending = {p["original_line_id"]: p["id"] for p in acc.get("proposals") or [] if p["id"] not in decided}
    last_reversed: Dict[str, dict] = {}
    for p in postings:
        if p.get("kind") == POSTING_REVERSAL:
            last_reversed[p["original_line_id"]] = p
    out = []
    for s in acc.get("split") or []:
        line_id = s["original_line_id"]
        if cents(s.get("net")) <= 0 or booked.get(line_id, Decimal(0)) != 0:
            continue
        if s["target"] == COST_TARGET_UNDETERMINED or line_id in reversed_lines:
            entry = {"original_line_id": line_id, "net": s["net"],
                     "state": "reversed" if line_id in reversed_lines else COST_TARGET_UNDETERMINED,
                     "pending_proposal": pending.get(line_id)}
            if line_id in last_reversed:
                r = last_reversed[line_id]          # Р63: where the reversed booking was
                entry["original_destination"] = (r["target"], r.get("project_id"), r.get("package_id"))
            out.append(entry)
    return out


async def company_cost_lines(tenant, period: Optional[str] = None) -> List[dict]:
    """Р58: the company costs (losses on a return) of accepted differences — the ``company``
    postings of the accepted notes (no second ledger): a booking or an FG-277 resolution is
    +, an FG-276 reversal is −, each in its own posting period."""
    out: List[dict] = []
    async for n in tenant.credit_debit_notes.find(
            {"direction": INCOMING, "difference_accepted.postings.target": COST_TARGET_COMPANY}, {"_id": 0}):
        acc = n["difference_accepted"]
        for p in acc.get("postings") or []:
            if p.get("target") != COST_TARGET_COMPANY or cents(p.get("net")) == 0:
                continue
            if period and p["period"] != period:
                continue
            out.append({"source": "supplier_note", "kind": "accepted_difference_company",
                        "posting": p.get("kind"), "posting_id": p.get("id"),
                        "value": p["net"], "at": p["at"], "period": p["period"], "ref": n.get("id"),
                        "invoice_id": n.get("original_invoice_id"), "invoice_line_id": p["original_line_id"],
                        "note_number": n.get("number"), "reason": p.get("reason") or acc.get("reason")})
    return out


async def company_losses_block(tenant, period: Optional[str] = None) -> dict:
    """Q007 / FG-271: THE one shape of the company-losses line every company-result reader
    returns — same label, same "what it includes" text, same drill-down. FG-278: the
    reader passes the SAME period scope its project sums use (``None`` = cumulative, as
    every project P&L in main is); ``scope`` echoes it so a total never mixes scopes."""
    lines = await company_cost_lines(tenant, period)
    return {"label": COMPANY_LOSSES_LABEL, "includes": COMPANY_LOSSES_INCLUDES,
            "scope": {"period": period, "basis": "period" if period else "cumulative"},
            "amount": money(sum((cents(l["value"]) for l in lines), Decimal(0))), "lines": lines}


async def supplier_note_input_vat(tenant, project_id: str) -> Decimal:
    """FG-247(c): the VAT of supplier credit / debit notes on lines allocated to the
    project, by the same share (credit −, debit +). A note is the TAX document, so this
    holds for a note linked to a receipt reversal too (the reversal itself never changes
    input VAT — ``project_input_vat``)."""
    total = Decimal(0)
    async for n in _applied_supplier_notes(tenant):
        sign = Decimal(-1) if n.get("kind") == KIND_CREDIT else Decimal(1)
        for l in n.get("lines") or []:
            row = await tenant.invoice_lines.find_one({"id": l.get("original_line_id")}, {"_id": 0})
            if row is None:
                continue
            share = _project_share(row, project_id)
            if share > 0:
                total += sign * cents(cents(l.get("vat")) * share)
    return total
