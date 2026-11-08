"""
Routes — INV-CN-01: credit / debit notes, refunds and offsets (FLOW-006 §Корекции).

Package ``docs/architecture/tasks/INV-CN-01_CREDIT_DEBIT_NOTES.md``; decisions Р49
(+ Р47); oracle Q004. The rules live in ``app/services/invoice_corrections.py``.

Every write: finance role (Owner / Admin / Accountant) → Idempotency-Key (428 without,
R29) → one MongoDB transaction (auth_tx.run_in_transaction) with a CAS on every document
it decides on → canonical AuditEvent in that transaction (record_event with the session).
An approval is by the Owner, a different person from the author, on the exact version.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException

from app.deps.modules import require_m5
from app.routes import finance as fin
from app.services import invoice_corrections as ic
from app.services.invoice_state import STATUS_CHANGED, claim_invoice
from app.services.money_amount import check_reason, positive_amount

router = APIRouter(tags=["Finance"])

APPROVER_ROLES = ("Owner",)        # Р49.4: the Owner approves (FLOW-034)


def _guard(user: dict) -> None:
    if not fin.finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")


def _approver(user: dict) -> None:
    if user.get("role") not in APPROVER_ROLES:
        raise HTTPException(status_code=403, detail={
            "error_code": ic.APPROVER_ROLE_REQUIRED, "message": "Одобрява само Собственикът"})


def _reason(body: dict) -> str:
    raw = body.get("reason")
    reason = raw.strip() if isinstance(raw, str) else ""
    if not reason:
        raise HTTPException(status_code=400, detail={
            "error_code": "REASON_REQUIRED", "message": "Посочете причина"})
    check_reason(reason)
    return reason


def _version(body: dict) -> int:
    v = body.get("version")
    if isinstance(v, bool) or not isinstance(v, int):
        raise HTTPException(status_code=422, detail={
            "error_code": ic.VERSION_MISMATCH, "message": "Посочете версията, която одобрявате"})
    return v


def _stable_id(prefix: str, org_id: str, key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "beg-%s:%s:%s" % (prefix, org_id, key)))


def _correctable(invoice: Optional[dict]) -> dict:
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.get("status") in (ic.DRAFT, ic.CANCELLED):
        raise ic.conflict(ic.INVOICE_NOT_CORRECTABLE,
                          "Чернова се поправя директно; анулирана фактура не се коригира",
                          status=invoice.get("status"))
    return invoice


async def _prepare(user: dict):
    """Indexes + the shared number counter, created OUTSIDE the transaction."""
    tenant = fin._tenant(user)
    settings = await fin.get_invoice_settings(user["org_id"])
    prefix = ic.number_prefix(settings)
    await ic.ensure_indexes(fin.db)
    await ic.seed_number_counter(tenant, prefix, settings)
    return tenant, prefix


async def _claim(tenant, invoice_id: str, session) -> dict:
    current = await claim_invoice(tenant, invoice_id, session=session,
                                  forbidden=(ic.DRAFT, ic.CANCELLED),
                                  code=ic.INVOICE_NOT_CORRECTABLE)
    if current is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return current


def _public(doc: Optional[dict]) -> Optional[dict]:
    return {k: v for k, v in doc.items() if k != "_id"} if doc else doc


# ═════════════════════════════════════════════════════════════ notes
@router.post("/finance/credit-notes", status_code=201)
async def create_note(body: dict = Body(...), user: dict = Depends(require_m5),
                      idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """Create a credit / debit note to an issued invoice.

    * outgoing (to a client): a DRAFT for the Owner's approval — no number yet (Р49.4);
    * incoming (from a supplier): REGISTERED by the Accountant with the supplier's number,
      linked with the credit the invoice awaits (Р47, Р49.8); a duplicate → 409."""
    _guard(user)
    key = fin._require_key(idempotency_key)
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Invalid body")
    kind = body.get("kind")
    if kind not in (ic.KIND_CREDIT, ic.KIND_DEBIT):
        raise ic.unprocessable(ic.NOTE_INVALID, "kind: credit или debit")
    reason = _reason(body)
    invoice_id = body.get("original_invoice_id")
    if not isinstance(invoice_id, str) or not invoice_id:
        raise ic.unprocessable(ic.NOTE_INVALID, "original_invoice_id е задължително")
    file_id = body.get("file_id")
    if file_id is not None and not isinstance(file_id, str):
        raise ic.unprocessable(ic.NOTE_INVALID, "file_id: идентификатор от File Registry")

    async def work():
        from app.services.auth_tx import run_in_transaction
        tenant, prefix = await _prepare(user)
        invoice = _correctable(await tenant.invoices.get(invoice_id, {"_id": 0}))
        direction = ic.OUTGOING if invoice.get("direction") == "Issued" else ic.INCOMING
        lines = await ic.build_note_lines(tenant, invoice, body.get("lines"))
        totals = ic.note_totals(lines)
        basis = None
        if kind == ic.KIND_DEBIT and direction == ic.OUTGOING:
            basis = await _debit_basis(tenant, invoice, body.get("basis"))
        number = None
        supplier_key = None
        if direction == ic.INCOMING:
            number = (body.get("number") or "").strip() if isinstance(body.get("number"), str) else ""
            if not number:
                raise ic.unprocessable(ic.NOTE_INVALID, "Номерът на известието от доставчика е задължителен")
            supplier_key = ((invoice.get("counterparty_eik") or "").strip()
                            or (invoice.get("counterparty_name") or "").strip().lower())
        note_id = _stable_id("credit-debit-note", user["org_id"], key)
        now = ic.now_iso()
        doc = {
            "id": note_id, "org_id": user["org_id"], "kind": kind, "direction": direction,
            "number": number, "supplier_key": supplier_key,
            "original_invoice_id": invoice_id, "original_invoice_no": invoice.get("invoice_no"),
            "project_id": invoice.get("project_id"), "act_id": invoice.get("act_id"),
            "counterparty_name": invoice.get("counterparty_name"),
            "counterparty_eik": invoice.get("counterparty_eik"),
            "currency": invoice.get("currency", "EUR"),
            "lines": lines, **totals, "reason": reason, "file_id": file_id, "basis": basis,
            "version": 1, "applied": False, "created_by": user["id"], "created_at": now,
            "updated_at": now,
        }
        if direction == ic.OUTGOING:
            doc.update({"status": ic.NOTE_PENDING, "issue_date": None})
        else:
            doc.update({"status": ic.NOTE_REGISTERED,
                        "issue_date": body.get("issue_date") if isinstance(body.get("issue_date"), str)
                        else now[:10]})

        async def tx_body(session):
            if direction == ic.INCOMING:
                await _claim(tenant, invoice_id, session)
                dup = await tenant.credit_debit_notes.find_one(
                    {"direction": ic.INCOMING, "supplier_key": supplier_key, "number": number},
                    {"_id": 0, "id": 1}, session=session)
                if dup:
                    raise ic.conflict(ic.DUPLICATE_CREDIT_NOTE,
                                      "Известие с този номер от този доставчик вече е регистрирано",
                                      number=number, existing_id=dup["id"])
            current = await tenant.invoices.get(invoice_id, session=session)
            if kind == ic.KIND_CREDIT:
                await ic.check_credit_cap(tenant, current, lines, session=session)
            row = dict(doc)
            if direction == ic.INCOMING:
                link = ({"applied": True, "expected": None, "matched": None}
                        if kind != ic.KIND_CREDIT else
                        await ic.match_expected_credit(tenant, invoice_id, totals["gross"], note_id,
                                                       session=session))
                row.update({"applied": link["applied"], "expected_link": link})
            await tenant.credit_debit_notes.insert_one(row, session=session)
            if row["applied"]:
                await fin.update_invoice_status(tenant, invoice_id, session=session)
            await fin._audit_tx(user, "finance.%s_note.%s" % (kind, "registered"
                                if direction == ic.INCOMING else "drafted"),
                                "finance.%s_note" % kind, note_id, reason,
                                {"original_invoice_id": invoice_id, "direction": direction,
                                 "net": totals["net"], "vat": totals["vat"], "gross": totals["gross"],
                                 "status": row["status"], "applied": row["applied"]},
                                key, session)
        await fin._tx(run_in_transaction, tx_body)
        return _public(await tenant.credit_debit_notes.find_one({"id": note_id}, {"_id": 0}))

    return await fin._once(user, key, "finance.credit_debit_note.create", {"body": body}, work)


async def _debit_basis(tenant, invoice: dict, basis) -> dict:
    """Р49 default (FLOW-005 L98): a debit note to a client raises the amount owed only
    on an approved basis — an approved act of the same project. D3: there is no annex
    model in main, so an act is the only basis accepted."""
    if not isinstance(basis, dict) or basis.get("type") != "act" or not isinstance(basis.get("id"), str):
        raise ic.unprocessable(ic.DEBIT_NOTE_BASIS_REQUIRED,
                               "Дебитното известие изисква основание — одобрен акт")
    act = await tenant.client_acts.find_one({"id": basis["id"]}, {"_id": 0})
    if not act or act.get("status") != "Accepted" or act.get("project_id") != invoice.get("project_id"):
        raise ic.unprocessable(ic.DEBIT_NOTE_BASIS_REQUIRED,
                               "Основанието трябва да е одобрен акт от същия обект", basis=basis)
    return {"type": "act", "id": act["id"], "act_number": act.get("act_number")}


@router.post("/finance/credit-notes/{note_id}/approve")
async def approve_note(note_id: str, body: dict = Body(...), user: dict = Depends(require_m5),
                       idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """Р49.4 / CLAUDE.md §8: the Owner — not the author — approves the EXACT version of an
    outgoing note. Only then the note gets its number (shared sequence) and changes the
    open receivable; the contract value is never touched."""
    _guard(user)
    _approver(user)
    key = fin._require_key(idempotency_key)
    version = _version(body if isinstance(body, dict) else {})

    async def work():
        from app.services.auth_tx import run_in_transaction
        tenant, prefix = await _prepare(user)

        async def tx_body(session):
            note = await tenant.credit_debit_notes.find_one({"id": note_id}, {"_id": 0},
                                                            session=session)
            if note is None:
                raise HTTPException(status_code=404, detail="Note not found")
            if note.get("direction") != ic.OUTGOING or note.get("status") != ic.NOTE_PENDING:
                raise ic.conflict(ic.NOT_PENDING, "Известието не чака одобрение",
                                  status=note.get("status"))
            if note.get("version") != version:
                raise ic.conflict(ic.VERSION_MISMATCH, "Одобрява се точна версия — версията е друга",
                                  version=note.get("version"))
            if note.get("created_by") == user["id"]:
                raise ic.conflict(ic.SAME_PERSON_APPROVAL,
                                  "Издателят не може да одобри своето известие — нужен е друг човек")
            invoice = await _claim(tenant, note["original_invoice_id"], session)
            if note["kind"] == ic.KIND_CREDIT:
                await ic.check_credit_cap(tenant, invoice, note["lines"], session=session)
            elif (note.get("basis") or {}).get("type") == "act":
                act = await ic.claim_act(tenant, note["basis"]["id"], session=session)
                ic.check_act_approved(act)
                await ic.check_act_cap(tenant, act, ic.cents(note["net"]), session=session)
            number = await ic.take_number(tenant, prefix, session=session)
            at = ic.now_iso()
            res = await tenant.credit_debit_notes.update_one(
                {"id": note_id, "status": ic.NOTE_PENDING, "version": version},
                {"$set": {"status": ic.NOTE_APPROVED, "applied": True, "number": number,
                          "issue_date": at[:10], "approved_by": user["id"], "approved_at": at,
                          "approval": {"version": version, "approved_by": user["id"], "at": at,
                                       "evidence": {"lines": note["lines"], "gross": note["gross"]}},
                          "updated_at": at}}, session=session)
            if res.matched_count != 1:
                raise ic.conflict(ic.NOT_PENDING, "Известието вече е одобрено")
            await fin.update_invoice_status(tenant, note["original_invoice_id"], session=session)
            await fin._audit_tx(user, "finance.%s_note.approved" % note["kind"],
                                "finance.%s_note" % note["kind"], note_id, note.get("reason") or "",
                                {"status": {"before": ic.NOTE_PENDING, "after": ic.NOTE_APPROVED},
                                 "number": number, "version": version,
                                 "original_invoice_id": note["original_invoice_id"],
                                 "gross": note["gross"], "author": note.get("created_by")},
                                key, session)
        await fin._tx(run_in_transaction, tx_body)
        return _public(await tenant.credit_debit_notes.find_one({"id": note_id}, {"_id": 0}))

    return await fin._once(user, key, "finance.credit_debit_note.approve",
                           {"note_id": note_id, "version": version}, work)


@router.get("/finance/credit-notes")
async def list_notes(invoice_id: Optional[str] = None, user: dict = Depends(require_m5)):
    _guard(user)
    flt = {"original_invoice_id": invoice_id} if invoice_id else {}
    return await fin._tenant(user).credit_debit_notes.find(flt, {"_id": 0}).sort(
        "created_at", -1).to_list(500)


@router.get("/finance/credit-notes/{note_id}")
async def get_note(note_id: str, user: dict = Depends(require_m5)):
    _guard(user)
    note = await fin._tenant(user).credit_debit_notes.find_one({"id": note_id}, {"_id": 0})
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.get("/finance/invoices/{invoice_id}/corrections")
async def invoice_corrections(invoice_id: str, user: dict = Depends(require_m5)):
    """Read-only: the notes, offsets and refunds of an invoice, credited per line, the
    open amount / credit balance, and (Р49.8) the credit the invoice awaits with its
    14-day escalation to the Owner — computed here, nothing written."""
    _guard(user)
    tenant = fin._tenant(user)
    invoice = await tenant.invoices.get(invoice_id, {"_id": 0})
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    notes = await tenant.credit_debit_notes.find({"original_invoice_id": invoice_id},
                                                 {"_id": 0}).sort("created_at", 1).to_list(500)
    credited = await ic.credited_by_line(tenant, invoice_id)
    offsets = await tenant.invoice_offsets.find(
        {"$or": [{"source_invoice_id": invoice_id}, {"target_invoice_id": invoice_id}]},
        {"_id": 0}).to_list(500)
    expected = await tenant.expected_credit_notes.find({"invoice_id": invoice_id},
                                                       {"_id": 0}).to_list(500)
    now = datetime.now(timezone.utc)
    for row in expected:
        row.update(ic.expected_escalation(row, now))
    open_ = await ic.current_open(tenant, invoice)
    return {
        "invoice_id": invoice_id, "status": invoice.get("status"),
        "total": invoice.get("total"), "remaining_amount": ic.money(max(open_, 0)),
        "credit_balance": ic.money(max(-open_, 0)),
        "credited_by_line": {k: ic.money(v) for k, v in credited.items()},
        "notes": notes, "offsets": offsets, "expected_credit_notes": expected,
    }


# ═════════════════════════════════════════════════════════════ refund (Р49.6 а)
@router.post("/finance/invoices/{invoice_id}/refund", status_code=201)
async def refund_credit_balance(invoice_id: str, body: dict = Body(...),
                                user: dict = Depends(require_m5),
                                idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """Р49.6 (а): the Accountant returns a credit balance — a real payment in the ONE
    Payment ledger (FLOW-006 ``finance_payments``), never above the balance."""
    _guard(user)
    key = fin._require_key(idempotency_key)
    body = body if isinstance(body, dict) else {}
    amount = positive_amount(body.get("amount"))
    reason = _reason(body)

    async def work():
        from app.services.auth_tx import run_in_transaction
        tenant = fin._tenant(user)
        invoice = _correctable(await tenant.invoices.get(invoice_id, {"_id": 0}))
        method = body.get("method") or "BankTransfer"
        account_id = await fin._resolve_payment_account(tenant, method, body.get("account_id"))
        if not await tenant.financial_accounts.get(account_id):
            raise HTTPException(status_code=404, detail="Сметката не е намерена")
        payment_id = _stable_id("invoice-refund:" + invoice_id, user["org_id"], key)

        async def tx_body(session):
            current = await _claim(tenant, invoice_id, session)
            balance = -(await ic.current_open(tenant, current, session=session))
            if ic.cents(amount) > balance:
                raise ic.conflict(ic.REFUND_EXCEEDS_BALANCE, "Сумата надвишава кредитното салдо",
                                  credit_balance=ic.money(max(balance, 0)))
            at = ic.now_iso()
            await tenant.finance_payments.update_one({"id": payment_id}, {"$setOnInsert": {
                "id": payment_id, "org_id": user["org_id"],
                "direction": "Outflow" if current.get("direction") == "Issued" else "Inflow",
                "amount": ic.money(ic.cents(amount)), "currency": current.get("currency", "EUR"),
                "date": body.get("date") if isinstance(body.get("date"), str) else at[:10],
                "method": method, "account_id": account_id,
                "counterparty_name": current.get("counterparty_name", ""),
                "reference": current.get("invoice_no"), "project_id": current.get("project_id"),
                "note": "Връщане на кредитно салдо по ф-ра %s: %s" % (current.get("invoice_no"), reason),
                "refund_invoice_id": invoice_id, "created_by": user["id"],
                "created_at": at, "updated_at": at}}, upsert=True, session=session)
            await fin.update_invoice_status(tenant, invoice_id, session=session)
            await fin._audit_tx(user, "finance.invoice.credit_balance_refunded", "finance.payment",
                                payment_id, reason, {"invoice_id": invoice_id, "amount": amount,
                                                     "credit_balance_before": ic.money(balance)},
                                key, session)
        await fin._tx(run_in_transaction, tx_body)
        return {"ok": True, "payment_id": payment_id,
                "invoice": await tenant.invoices.get(invoice_id, {"_id": 0})}

    return await fin._once(user, key, "finance.invoice.refund", {"invoice_id": invoice_id, "body": body},
                           work)


# ═════════════════════════════════════════════════════════════ offset (Р49.6 б)
@router.post("/finance/offsets", status_code=201)
async def create_offset(body: dict = Body(...), user: dict = Depends(require_m5),
                        idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """Р49.6 (б) / FLOW-010 L354-360: an explicit offset of a credit balance against an
    open amount, with both sources, only within the same contract (else 409
    OFFSET_ACROSS_CONTRACTS, FLOW-010 L389). It waits for a second approval: the tenant
    threshold for a "large" offset is not decided (D4), so EVERY offset needs one."""
    _guard(user)
    key = fin._require_key(idempotency_key)
    body = body if isinstance(body, dict) else {}
    amount = positive_amount(body.get("amount"))
    reason = _reason(body)
    src_id, tgt_id = body.get("source_invoice_id"), body.get("target_invoice_id")
    if not isinstance(src_id, str) or not isinstance(tgt_id, str) or src_id == tgt_id:
        raise ic.unprocessable(ic.NOTE_INVALID, "Посочете две различни фактури")

    async def work():
        from app.services.auth_tx import run_in_transaction
        tenant = fin._tenant(user)
        await ic.ensure_indexes(fin.db)
        src = _correctable(await tenant.invoices.get(src_id, {"_id": 0}))
        tgt = _correctable(await tenant.invoices.get(tgt_id, {"_id": 0}))
        if ic.contract_key(src) is None or ic.contract_key(src) != ic.contract_key(tgt):
            raise ic.conflict(ic.OFFSET_ACROSS_CONTRACTS,
                              "Прихващане се прави само в рамките на един и същ договор")
        offset_id = _stable_id("invoice-offset", user["org_id"], key)

        async def tx_body(session):
            await _check_offset(tenant, src_id, tgt_id, amount, session)
            at = ic.now_iso()
            await tenant.invoice_offsets.insert_one({
                "id": offset_id, "org_id": user["org_id"], "source_invoice_id": src_id,
                "target_invoice_id": tgt_id, "amount": ic.money(ic.cents(amount)), "reason": reason,
                "status": ic.OFFSET_PENDING, "version": 1, "contract_scope": list(ic.contract_key(src)),
                "created_by": user["id"], "created_at": at, "updated_at": at}, session=session)
            await fin._audit_tx(user, "finance.offset.requested", "finance.offset", offset_id, reason,
                                {"source_invoice_id": src_id, "target_invoice_id": tgt_id,
                                 "amount": amount, "status": ic.OFFSET_PENDING}, key, session)
        await fin._tx(run_in_transaction, tx_body)
        return await tenant.invoice_offsets.find_one({"id": offset_id}, {"_id": 0})

    return await fin._once(user, key, "finance.offset.create", {"body": body}, work)


async def _check_offset(tenant, src_id: str, tgt_id: str, amount, session) -> None:
    src = await _claim(tenant, src_id, session)
    tgt = await _claim(tenant, tgt_id, session)
    balance = -(await ic.current_open(tenant, src, session=session))
    open_tgt = await ic.current_open(tenant, tgt, session=session)
    if ic.cents(amount) > balance or ic.cents(amount) > open_tgt:
        raise ic.conflict(ic.OFFSET_EXCEEDS_BALANCE,
                          "Сумата надвишава кредитното салдо или остатъка за плащане",
                          credit_balance=ic.money(max(balance, 0)),
                          target_remaining=ic.money(max(open_tgt, 0)))


@router.post("/finance/offsets/{offset_id}/approve")
async def approve_offset(offset_id: str, body: dict = Body(...), user: dict = Depends(require_m5),
                         idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """The second approval of an offset (FLOW-034 L72): the Owner, not the author, the
    exact version; both invoices are re-checked in the same transaction."""
    _guard(user)
    _approver(user)
    key = fin._require_key(idempotency_key)
    version = _version(body if isinstance(body, dict) else {})

    async def work():
        from app.services.auth_tx import run_in_transaction
        tenant = fin._tenant(user)

        async def tx_body(session):
            off = await tenant.invoice_offsets.find_one({"id": offset_id}, {"_id": 0}, session=session)
            if off is None:
                raise HTTPException(status_code=404, detail="Offset not found")
            if off.get("status") != ic.OFFSET_PENDING:
                raise ic.conflict(ic.NOT_PENDING, "Прихващането не чака одобрение")
            if off.get("version") != version:
                raise ic.conflict(ic.VERSION_MISMATCH, "Одобрява се точна версия — версията е друга")
            if off.get("created_by") == user["id"]:
                raise ic.conflict(ic.SAME_PERSON_APPROVAL,
                                  "Авторът не може да одобри своето прихващане — нужен е друг човек")
            await _check_offset(tenant, off["source_invoice_id"], off["target_invoice_id"],
                                off["amount"], session)
            at = ic.now_iso()
            await tenant.invoice_offsets.update_one(
                {"id": offset_id, "status": ic.OFFSET_PENDING, "version": version},
                {"$set": {"status": ic.OFFSET_APPROVED, "approved_by": user["id"], "approved_at": at,
                          "approval": {"version": version, "approved_by": user["id"], "at": at},
                          "updated_at": at}}, session=session)
            for inv in (off["source_invoice_id"], off["target_invoice_id"]):
                await fin.update_invoice_status(tenant, inv, session=session)
            await fin._audit_tx(user, "finance.offset.approved", "finance.offset", offset_id,
                                off.get("reason") or "",
                                {"status": {"before": ic.OFFSET_PENDING, "after": ic.OFFSET_APPROVED},
                                 "amount": off["amount"], "version": version,
                                 "author": off.get("created_by")}, key, session)
        await fin._tx(run_in_transaction, tx_body)
        return await tenant.invoice_offsets.find_one({"id": offset_id}, {"_id": 0})

    return await fin._once(user, key, "finance.offset.approve",
                           {"offset_id": offset_id, "version": version}, work)


@router.get("/finance/offsets")
async def list_offsets(user: dict = Depends(require_m5)):
    _guard(user)
    return await fin._tenant(user).invoice_offsets.find({}, {"_id": 0}).sort(
        "created_at", -1).to_list(500)
