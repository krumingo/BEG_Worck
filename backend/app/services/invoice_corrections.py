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


async def seed_number_counter(tenant, prefix: str, settings: dict) -> None:
    """Create the shared per-tenant counter ONCE (outside any transaction), above every
    number already used by an issued invoice or an outgoing note of this tenant — so the
    first number it gives can never repeat a legacy one. Idempotent; a concurrent
    creator wins and this is a no-op."""
    from pymongo.errors import DuplicateKeyError
    flt = {"org_id": tenant.org_id, "counter_type": NUMBER_COUNTER}
    if await tenant.org_counters.find_one(flt, {"_id": 0, "value": 1}):
        return
    highest = 0
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
                                   "created_at": now_iso()}}, upsert=True)
    except DuplicateKeyError:
        pass


MAX_NUMBER_SKIPS = 10000


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
            {"org_id": tenant.org_id, "counter_type": NUMBER_COUNTER},
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
    qty = Decimal(str(row.get("qty") or 0))
    price = Decimal(str(row.get("unit_price") or 0))
    return {"id": line_id, "qty": qty, "unit_price": price, "net": cents(qty * price),
            "vat_percent": Decimal(str(row.get("vat_percent") if row.get("vat_percent") is not None
                                       else invoice.get("vat_percent") or 0)),
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
                    {"name": "inv_cn_01_invoice_no_by_direction", "unique": True,
                     "partialFilterExpression": {"invoice_no": {"$gt": ""}}})

PLANNED_INDEXES = (
    INVOICE_NO_INDEX,
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


async def ensure_indexes(database) -> None:
    """Create the planned indexes on the tenant's operational database (once per process
    and database handle). Idempotent: an existing identical index is a no-op."""
    name = repr(database)          # the client + database it names
    if name in _ensured:
        return
    # one explicit call per collection (the A2C guard sees every collection named)
    plan = {}
    for coll, keys, opts in PLANNED_INDEXES:
        plan.setdefault(coll, []).append((keys, opts))
    for keys, opts in plan["invoices"]:
        await database.invoices.create_index(keys, **opts)
    for keys, opts in plan["credit_debit_notes"]:
        await database.credit_debit_notes.create_index(keys, **opts)
    for keys, opts in plan["invoice_offsets"]:
        await database.invoice_offsets.create_index(keys, **opts)
    for keys, opts in plan["org_counters"]:
        await database.org_counters.create_index(keys, **opts)
    _ensured.add(name)


# ═══════════════════════════════════════════════════════════════ shared reads
async def current_open(tenant, invoice: dict, *, session=None) -> Decimal:
    """The invoice's open amount NOW, from the source rows read in ``session``:
    > 0 still owed, < 0 owed back (credit balance)."""
    from app.services.payment_state import active_allocations
    paid = Decimal(0)
    async for a in tenant.payment_allocations.find(active_allocations({"invoice_id": invoice["id"]}),
                                                   {"_id": 0, "amount_allocated": 1}, session=session):
        paid += cents(a.get("amount_allocated"))
    derived = await derived_sums(tenant, invoice["id"], session=session)
    return adjusted_total({**invoice, **derived}) - paid


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
                                session) -> dict:
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
            {"$set": {"status": "fulfilled", "credit_note_id": note_id, "fulfilled_at": at,
                      "dq_task.status": "closed", "dq_task.closed_at": at}}, session=session)
        if res.modified_count != len(ids):
            raise conflict(EXPECTED_LINK_INVALID, "Очакваното известие вече е покрито")
        if not await tenant.expected_credit_notes.find_one(
                {"invoice_id": invoice_id, "status": "open"}, {"_id": 0, "id": 1}, session=session):
            await tenant.invoices.update_one({"id": invoice_id},
                                             {"$set": {"awaiting_credit_note": False}}, session=session)
        return {"applied": True, "expected": money(expected), "matched": True, "rows": ids}
    await tenant.expected_credit_notes.update_many(
        {"id": {"$in": ids}, "invoice_id": invoice_id, "status": "open"},
        {"$set": {"dq_mismatch": {"title": "разлика в кредитно известие", "status": "open",
                                  "credit_note_id": note_id, "expected": money(expected),
                                  "registered": money(cents(gross)), "at": at}}}, session=session)
    return {"applied": False, "expected": money(expected), "matched": False, "rows": ids,
            "dq": "разлика в кредитно известие"}


async def linked_to_warehouse(tenant, invoice: dict, *, session=None) -> bool:
    """Р51(3): is a supplier invoice linked to a warehouse receipt? Any of its
    ``invoice_lines`` rows referenced by a canonical ledger movement."""
    from app.services.invoice_line_lock import first_linked_movement
    async for line in tenant.invoice_lines.find({"invoice_id": invoice["id"]}, {"_id": 0, "id": 1},
                                                session=session):
        if await first_linked_movement(tenant, line["id"], session=session):
            return True
    return False


async def pending_debit(tenant, invoice_id: str, *, session=None) -> Decimal:
    """Р51(2): gross of supplier debit notes registered but not yet approved by the Owner —
    the increase they ask for is NOT payable until approved."""
    total = Decimal(0)
    async for n in tenant.credit_debit_notes.find(
            {"original_invoice_id": invoice_id, "kind": KIND_DEBIT, "status": NOTE_PENDING},
            {"_id": 0, "gross": 1}, session=session):
        total += cents(n.get("gross"))
    return total
