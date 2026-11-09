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

import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
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
        if direction == ic.INCOMING and user.get("role") != "Accountant":
            # Р55(2) / FG-250: a supplier note is registered by the Accountant
            raise HTTPException(status_code=403, detail={
                "error_code": "REGISTRAR_ROLE_REQUIRED",
                "message": "Входящо известие регистрира Счетоводителят"})
        lines = await ic.build_note_lines(tenant, invoice, body.get("lines"))
        totals = ic.note_totals(lines)
        basis = None
        if kind == ic.KIND_DEBIT and direction == ic.OUTGOING:
            basis = await _debit_basis(tenant, invoice, body.get("basis"))
        elif kind == ic.KIND_DEBIT:
            basis = _supplier_debit_basis(body.get("basis"), file_id)      # Р51(2)
        link_ids = body.get("expected_credit_note_ids")
        if kind == ic.KIND_CREDIT and direction == ic.INCOMING:
            await ic.check_expected_link(tenant, invoice_id, link_ids)       # FG-220 (fail fast)
        elif link_ids is not None:
            raise ic.unprocessable(ic.EXPECTED_LINK_INVALID,
                                   "expected_credit_note_ids е само за входящо кредитно известие")
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
        elif kind == ic.KIND_DEBIT:
            # Р51(2): a supplier debit note raises the payable only after the Owner approves
            doc.update({"status": ic.NOTE_PENDING,
                        "issue_date": body.get("issue_date") if isinstance(body.get("issue_date"), str)
                        else now[:10]})
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
            if direction == ic.INCOMING and kind == ic.KIND_CREDIT:
                rows = await ic.check_expected_link(tenant, invoice_id, link_ids, session=session)
                link = await ic.match_expected_credit(tenant, invoice_id, totals["gross"], note_id,
                                                      rows, session=session)
                row.update({"applied": link["applied"], "expected_link": link})
            await tenant.credit_debit_notes.insert_one(row, session=session)
            if row["applied"]:
                await fin.update_invoice_status(tenant, invoice_id, session=session)
            await fin._audit_tx(user, "finance.%s_note.%s" % (kind, "registered"
                                if row["status"] == ic.NOTE_REGISTERED else "drafted"),
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


SUPPLIER_DEBIT_BASES = ("order", "additional_delivery", "annex")


def _supplier_debit_basis(basis, file_id) -> dict:
    """Р51(2): a supplier debit note needs its basis — the order, an additional delivery or
    an annex (reference) — and the document (``file_id``) → otherwise 422."""
    if (not isinstance(basis, dict) or basis.get("type") not in SUPPLIER_DEBIT_BASES
            or not isinstance(basis.get("ref"), str) or not basis["ref"].strip()
            or not isinstance(file_id, str) or not file_id.strip()):
        raise ic.unprocessable(ic.DEBIT_NOTE_BASIS_REQUIRED,
                               "Входящото дебитно известие изисква основание (поръчка, допълнителна "
                               "доставка или анекс) и документ (file_id)",
                               allowed=list(SUPPLIER_DEBIT_BASES))
    return {"type": basis["type"], "ref": basis["ref"].strip()}


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
            if note.get("status") != ic.NOTE_PENDING:
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
            # an outgoing note gets OUR next number; a supplier note keeps the supplier's
            number = (await ic.take_number(tenant, prefix, session=session)
                      if note.get("direction") == ic.OUTGOING else note.get("number"))
            at = ic.now_iso()
            res = await tenant.credit_debit_notes.update_one(
                {"id": note_id, "status": ic.NOTE_PENDING, "version": version},
                {"$set": {"status": ic.NOTE_APPROVED, "applied": True, "number": number,
                          "issue_date": (at[:10] if note.get("direction") == ic.OUTGOING
                                         else note.get("issue_date")),
                          "approved_by": user["id"], "approved_at": at,
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


async def _reject(user: dict, key: str, reason: str, collection: str, row_id: str, label: str):
    """D10: a pending note / offset is rejected by the Owner, or withdrawn by its author,
    with a reason — it never had an effect and keeps none; nothing is deleted."""
    from app.services.auth_tx import run_in_transaction
    tenant = fin._tenant(user)
    coll = tenant.credit_debit_notes if collection == "credit_debit_notes" else tenant.invoice_offsets

    async def tx_body(session):
        row = await coll.find_one({"id": row_id}, {"_id": 0}, session=session)
        if row is None:
            raise HTTPException(status_code=404, detail="Not found")
        if row.get("status") != ic.NOTE_PENDING:
            raise ic.conflict(ic.NOT_PENDING, "Не чака одобрение", status=row.get("status"))
        if user.get("role") not in APPROVER_ROLES and row.get("created_by") != user["id"]:
            raise HTTPException(status_code=403, detail={
                "error_code": ic.APPROVER_ROLE_REQUIRED,
                "message": "Отхвърля Собственикът или оттегля авторът"})
        at = ic.now_iso()
        res = await coll.update_one({"id": row_id, "status": ic.NOTE_PENDING}, {"$set": {
            "status": ic.NOTE_REJECTED, "rejected_by": user["id"], "rejected_at": at,
            "reject_reason": reason, "updated_at": at}}, session=session)
        if res.matched_count != 1:
            raise ic.conflict(ic.NOT_PENDING, "Не чака одобрение")
        await fin._audit_tx(user, "finance.%s.rejected" % label, "finance.%s" % label, row_id, reason,
                            {"status": {"before": ic.NOTE_PENDING, "after": ic.NOTE_REJECTED},
                             "author": row.get("created_by")}, key, session)
    await fin._tx(run_in_transaction, tx_body)
    return await coll.find_one({"id": row_id}, {"_id": 0})


@router.post("/finance/credit-notes/{note_id}/reject")
async def reject_note(note_id: str, body: dict = Body(...), user: dict = Depends(require_m5),
                      idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    _guard(user)
    key = fin._require_key(idempotency_key)
    reason = _reason(body if isinstance(body, dict) else {})

    async def work():
        return await _reject(user, key, reason, "credit_debit_notes", note_id, "credit_debit_note")
    return await fin._once(user, key, "finance.credit_debit_note.reject",
                           {"note_id": note_id, "reason": reason}, work)


@router.post("/finance/offsets/{offset_id}/reject")
async def reject_offset(offset_id: str, body: dict = Body(...), user: dict = Depends(require_m5),
                        idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    _guard(user)
    key = fin._require_key(idempotency_key)
    reason = _reason(body if isinstance(body, dict) else {})

    async def work():
        return await _reject(user, key, reason, "invoice_offsets", offset_id, "offset")
    return await fin._once(user, key, "finance.offset.reject",
                           {"offset_id": offset_id, "reason": reason}, work)


@router.post("/finance/credit-notes/{note_id}/accept-difference")
async def accept_difference(note_id: str, body: dict = Body(...), user: dict = Depends(require_m5),
                            idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """Р52(2) / D7: a supplier credit note that differs from the awaited credit stays
    registered and NOT applied (the limit stays) until either a corrected note arrives
    (it closes the DQ) or the OWNER — never the Accountant — accepts the difference with a
    reason. Then the note applies with its REAL amount (payment limit = net received −
    the note), the awaited rows close and a canonical AuditEvent is written."""
    _guard(user)
    _approver(user)
    key = fin._require_key(idempotency_key)
    reason = _reason(body if isinstance(body, dict) else {})

    async def work():
        from app.services.auth_tx import run_in_transaction
        tenant = fin._tenant(user)

        async def tx_body(session):
            note = await tenant.credit_debit_notes.find_one({"id": note_id}, {"_id": 0}, session=session)
            if note is None:
                raise HTTPException(status_code=404, detail="Note not found")
            link = note.get("expected_link") or {}
            if (note.get("direction") != ic.INCOMING or note.get("applied") or link.get("matched") is not False
                    or note.get("superseded_by")):
                raise ic.conflict(ic.NOT_PENDING, "Няма отворена разлика за приемане по това известие")
            if note.get("created_by") == user["id"]:
                # Р55(2) / FG-250: the registrant and the acceptor are two different people
                raise ic.conflict(ic.SAME_PERSON_APPROVAL,
                                  "Регистрирал известието не може да приеме разликата — нужен е друг човек")
            rows = link.get("rows") or []
            await _claim(tenant, note["original_invoice_id"], session)
            open_rows = await tenant.expected_credit_notes.count_documents(
                {"id": {"$in": rows}, "status": "open"}, session=session)
            if open_rows != len(rows):
                raise ic.conflict(ic.NOT_PENDING, "Очакваното известие вече е покрито")
            at = ic.now_iso()
            diff_gross = ic.cents(link.get("expected")) - ic.cents(note.get("gross"))
            # Р58 / FG-265: a warehouse-received line → company cost; other → project (FG-251)
            split = await ic.split_accepted_difference(tenant, note, diff_gross, session=session)
            company_cost = sum((ic.cents(s["net"]) for s in split if s["target"] == ic.COST_TARGET_COMPANY),
                               Decimal(0))
            await tenant.credit_debit_notes.update_one(
                {"id": note_id, "applied": False},
                {"$set": {"applied": True, "difference_accepted": {
                    "by": user["id"], "reason": reason, "at": at,
                    "expected": link.get("expected"), "registered": note.get("gross"),
                    "split": split, "company_cost": ic.money(company_cost),
                    # FG-276/277: the append-only cost journal of this difference
                    "postings": ic.initial_postings(split, at, user["id"], reason)},
                    "updated_at": at}}, session=session)
            await tenant.expected_credit_notes.update_many(
                {"id": {"$in": rows}, "status": "open"},
                {"$set": {"status": "fulfilled_with_difference", "credit_note_id": note_id,
                          "fulfilled_at": at, "dq_task.status": "closed", "dq_task.closed_at": at,
                          "dq_mismatch.status": "accepted_by_owner", "dq_mismatch.closed_at": at}},
                session=session)
            if not await tenant.expected_credit_notes.find_one(
                    {"invoice_id": note["original_invoice_id"], "status": "open"}, {"_id": 0, "id": 1},
                    session=session):
                await tenant.invoices.update_one({"id": note["original_invoice_id"]},
                                                 {"$set": {"awaiting_credit_note": False}}, session=session)
            await fin.update_invoice_status(tenant, note["original_invoice_id"], session=session)
            await fin._audit_tx(user, "finance.credit_note.difference_accepted", "finance.credit_note",
                                note_id, reason, {"expected": link.get("expected"),
                                                  "registered": note.get("gross"), "rows": rows,
                                                  "original_invoice_id": note["original_invoice_id"],
                                                  # Р55(3) / FG-251: the uncredited part stays a
                                                  # cost of the original line's project, dated now
                                                  "difference_gross": ic.money(diff_gross),
                                                  "cost_period": at[:7],
                                                  # Р58: the warehouse part is a company cost
                                                  # (loss on the return); FIFO unchanged
                                                  "split": split,
                                                  "company_cost": ic.money(company_cost)},
                                key, session)
        await fin._tx(run_in_transaction, tx_body)
        return _public(await tenant.credit_debit_notes.find_one({"id": note_id}, {"_id": 0}))

    return await fin._once(user, key, "finance.credit_note.accept_difference",
                           {"note_id": note_id, "reason": reason}, work)


async def _difference_write(user: dict, note_id: str, key: str, action: str, payload: dict, apply):
    """FG-276 / FG-277: one consequential write on an accepted difference — in a transaction
    under the invoice claim, a CAS on the posting journal (append-only), an AuditEvent, the
    Idempotency-Key. ``apply(tenant, note, session)`` returns (pushes, audit_diff, reason, audit_action):
    ``pushes`` maps journal lists (``postings`` / ``proposals`` / ``decisions``) to the entries
    to APPEND; the CAS is on ``journal_version`` (+1 per write)."""
    async def work():
        from app.services.auth_tx import run_in_transaction
        tenant = fin._tenant(user)

        async def tx_body(session):
            note = await tenant.credit_debit_notes.find_one({"id": note_id}, {"_id": 0}, session=session)
            if note is None:
                raise HTTPException(status_code=404, detail="Note not found")
            acc = note.get("difference_accepted") or {}
            if note.get("direction") != ic.INCOMING or acc.get("postings") is None:
                raise ic.conflict(ic.NOT_PENDING, "Няма приета разлика по това известие")
            await _claim(tenant, note["original_invoice_id"], session)
            pushes, diff, reason, audit_action = await apply(tenant, note, session)
            if not isinstance(pushes, dict):
                pushes = {"postings": pushes}
            res = await tenant.credit_debit_notes.update_one(
                {"id": note_id, "difference_accepted.journal_version": acc.get("journal_version")},
                {"$push": {"difference_accepted." + k: {"$each": v} for k, v in pushes.items() if v},
                 "$inc": {"difference_accepted.journal_version": 1},
                 "$set": {"updated_at": ic.now_iso()}}, session=session)
            if res.modified_count != 1:
                raise ic.conflict(ic.NOT_PENDING, "Разликата беше променена — опреснете")
            await fin._audit_tx(user, audit_action or action, "finance.credit_note", note_id, reason,
                                {**diff, **pushes,
                                 "original_invoice_id": note["original_invoice_id"]}, key, session)
        await fin._tx(run_in_transaction, tx_body)
        return _public(await tenant.credit_debit_notes.find_one({"id": note_id}, {"_id": 0}))

    return await fin._once(user, key, action, payload, work)


@router.post("/finance/credit-notes/{note_id}/difference-lines/{line_id}/resolve")
async def resolve_difference_line(note_id: str, line_id: str, body: dict = Body(...),
                                  user: dict = Depends(require_m5),
                                  idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """FG-277: a line of an accepted difference that is booked nowhere (``undetermined`` at
    acceptance, or reversed by the Owner) is decided by a finance user (Р14: Owner / Admin
    / Accountant): ``target = project`` (+ ``project_id``, optional ``package_id`` = the
    SMR) or ``company``. An undetermined line is booked in the ACCEPTANCE period; a line
    re-booked after a reversal, in the current period (the reversal already left the
    acceptance period). The DQ issue closes; an AuditEvent is written."""
    _guard(user)
    key = fin._require_key(idempotency_key)
    body = body if isinstance(body, dict) else {}
    reason = _reason(body)
    target = body.get("target")
    if target not in (ic.COST_TARGET_PROJECT, ic.COST_TARGET_COMPANY):
        raise HTTPException(status_code=422, detail={"error_code": "TARGET_REQUIRED",
                                                     "message": "Изберете обект или фирма"})
    project_id = body.get("project_id") if target == ic.COST_TARGET_PROJECT else None
    package_id = body.get("package_id") if target == ic.COST_TARGET_PROJECT else None

    async def apply(tenant, note, session):
        open_lines = {l["original_line_id"]: l for l in ic.open_difference_lines(note)}
        line = open_lines.get(line_id)
        if line is None:
            raise ic.conflict(ic.NOT_PENDING, "Редът няма неразпределена разлика")
        # a project needs its id — except "back to the line's own allocation" after a
        # reversal of an allocation-based booking (the same destination, Р63)
        if target == ic.COST_TARGET_PROJECT and not project_id and \
                line.get("original_destination") != (ic.COST_TARGET_PROJECT, None, None):
            raise HTTPException(status_code=422, detail={"error_code": "PROJECT_REQUIRED",
                                                         "message": "Изберете обект"})
        if project_id and not await tenant.projects.find_one({"id": project_id}, {"_id": 0, "id": 1},
                                                             session=session):
            raise HTTPException(status_code=422, detail={"error_code": "PROJECT_NOT_FOUND",
                                                         "message": "Няма такъв обект"})
        if package_id and not await tenant.execution_packages.find_one(
                {"id": package_id, "project_id": project_id}, {"_id": 0, "id": 1}, session=session):
            raise HTTPException(status_code=422, detail={"error_code": "PACKAGE_NOT_FOUND",
                                                         "message": "Няма такова СМР в обекта"})
        acc = note["difference_accepted"]
        if line.get("pending_proposal"):
            raise ic.conflict(ic.NOT_PENDING, "По реда има предложение, което чака Собственика")
        at = ic.now_iso()
        if line["state"] == "reversed":
            # Р63 (FG-281): the SAME destination as the reversed booking applies at once;
            # another project / company cost needs the Owner (≠ proposer). Р64 (FG-415): a
            # project that is not Active / Paused needs the Owner EVEN for the same place —
            # its status read here, inside the transaction.
            same = (target, project_id, package_id) == line["original_destination"]
            statuses = await ic.project_statuses(
                tenant, await ic.rebooking_projects(tenant, line_id, target, project_id, session=session),
                session=session)
            closed = ic.any_project_closed(statuses)
            if not same or closed:
                proposal = {"id": "dpr_" + uuid.uuid4().hex[:16], "original_line_id": line_id,
                            "net": line["net"], "target": target, "project_id": project_id,
                            "package_id": package_id, "reason": reason, "by": user["id"], "at": at,
                            "project_statuses": statuses,
                            "why_approval": "other_destination" if not same else "closed_project"}
                return {"proposals": [proposal]}, {"line_id": line_id, "proposal": proposal}, reason, \
                    "finance.credit_note.difference_rebooking_proposed"
        period = acc["at"][:7] if line["state"] == ic.COST_TARGET_UNDETERMINED else at[:7]
        posting = ic._posting(ic.POSTING_RESOLUTION, line_id, ic.cents(line["net"]), target, at,
                              period=period, by=user["id"], reason=reason, project_id=project_id,
                              package_id=package_id, basis="resolved_by_" + (user.get("role") or "").lower())
        await _close_line_dq(tenant, note, line_id, user, at, posting, session)
        return [posting], {"line_id": line_id, "target": target, "project_id": project_id,
                           "package_id": package_id, "cost_period": period, "net": line["net"]}, reason, None

    return await _difference_write(user, note_id, key, "finance.credit_note.difference_line_resolved",
                                   {"note_id": note_id, "line_id": line_id, "target": target,
                                    "project_id": project_id, "package_id": package_id, "reason": reason},
                                   apply)


async def _close_line_dq(tenant, note: dict, line_id: str, user: dict, at: str, posting: dict, session) -> None:
    for kind in (ic.DQ_DIFFERENCE_LINE_UNDETERMINED, ic.DQ_DIFFERENCE_LINE_REVERSED):
        await tenant.dq_issues.update_many(
            {"kind": kind, "entity_id": {"$regex": "^%s:%s(:|$)" % (re.escape(note["id"]), re.escape(line_id))},
             "status": "open"},
            {"$set": {"status": "closed", "closed_at": at, "closed_by": user["id"],
                      "resolution": {"target": posting["target"], "project_id": posting.get("project_id"),
                                     "posting_id": posting["id"]}}},
            session=session)


def _pending_proposal(note: dict, proposal_id: str) -> dict:
    acc = note.get("difference_accepted") or {}
    decided = {d["proposal_id"] for d in acc.get("decisions") or []}
    for p in acc.get("proposals") or []:
        if p["id"] == proposal_id:
            if proposal_id in decided:
                raise ic.conflict(ic.NOT_PENDING, "Предложението вече е решено")
            return p
    raise HTTPException(status_code=404, detail="Proposal not found")


@router.post("/finance/credit-notes/{note_id}/difference-proposals/{proposal_id}/approve")
async def approve_difference_proposal(note_id: str, proposal_id: str, body: dict = Body(default={}),
                                      user: dict = Depends(require_m5),
                                      idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """Р63 (FG-281): the OWNER approves a re-booking proposal after a reversal (another
    project, company cost, or a Completed project). The proposer never approves (403).
    The re-booking is posted in the current period (the reversal already left the
    acceptance period); the line's DQ issue closes; AuditEvent."""
    _guard(user)
    _approver(user)
    key = fin._require_key(idempotency_key)
    body = body if isinstance(body, dict) else {}
    comment = (body.get("reason") or "").strip() or None

    async def apply(tenant, note, session):
        proposal = _pending_proposal(note, proposal_id)
        if proposal["by"] == user["id"]:
            raise HTTPException(status_code=403, detail={
                "error_code": ic.SAME_PERSON_APPROVAL,
                "message": "Предложилият не може да одобри — нужен е друг човек"})
        line = {l["original_line_id"]: l for l in ic.open_difference_lines(note)}.get(proposal["original_line_id"])
        if line is None:
            raise ic.conflict(ic.NOT_PENDING, "Редът вече няма неразпределена разлика")
        at = ic.now_iso()
        # Р64: the project status is read again at the approval, in this transaction
        statuses = await ic.project_statuses(
            tenant, await ic.rebooking_projects(tenant, proposal["original_line_id"], proposal["target"],
                                                proposal.get("project_id"), session=session),
            session=session)
        if any(st is None for st in statuses.values()):
            raise ic.conflict(ic.NOT_PENDING, "Обектът от предложението вече не съществува")
        posting = ic._posting(ic.POSTING_RESOLUTION, proposal["original_line_id"], ic.cents(proposal["net"]),
                              proposal["target"], at, period=at[:7], by=user["id"], reason=proposal["reason"],
                              project_id=proposal.get("project_id"), package_id=proposal.get("package_id"),
                              basis="rebooking_approved_by_owner")
        decision = {"proposal_id": proposal_id, "decision": "approved", "by": user["id"], "at": at,
                    "reason": comment, "posting_id": posting["id"], "project_statuses": statuses}
        await _close_line_dq(tenant, note, proposal["original_line_id"], user, at, posting, session)
        return {"postings": [posting], "decisions": [decision]}, {
            "proposal_id": proposal_id, "proposed_by": proposal["by"], "cost_period": at[:7],
            "project_statuses_at_approval": statuses}, \
            comment or proposal["reason"], None

    return await _difference_write(user, note_id, key, "finance.credit_note.difference_rebooking_approved",
                                   {"note_id": note_id, "proposal_id": proposal_id, "reason": comment},  # FG-416
                                   apply)


@router.post("/finance/credit-notes/{note_id}/difference-proposals/{proposal_id}/reject")
async def reject_difference_proposal(note_id: str, proposal_id: str, body: dict = Body(...),
                                     user: dict = Depends(require_m5),
                                     idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """Р63: the Owner rejects a re-booking proposal, or its proposer withdraws it (reason,
    AuditEvent). The line stays open (its DQ issue too) for a new proposal."""
    _guard(user)
    key = fin._require_key(idempotency_key)
    reason = _reason(body if isinstance(body, dict) else {})

    async def apply(tenant, note, session):
        proposal = _pending_proposal(note, proposal_id)
        if user.get("role") not in APPROVER_ROLES and proposal["by"] != user["id"]:
            raise HTTPException(status_code=403, detail={
                "error_code": ic.APPROVER_ROLE_REQUIRED, "message": "Отхвърля Собственикът или предложилият"})
        decision = {"proposal_id": proposal_id, "decision": "rejected", "by": user["id"],
                    "at": ic.now_iso(), "reason": reason}
        return {"decisions": [decision]}, {"proposal_id": proposal_id}, reason, None

    return await _difference_write(user, note_id, key, "finance.credit_note.difference_rebooking_rejected",
                                   {"note_id": note_id, "proposal_id": proposal_id, "reason": reason}, apply)


@router.post("/finance/credit-notes/{note_id}/reverse-difference")
async def reverse_difference(note_id: str, body: dict = Body(...), user: dict = Depends(require_m5),
                             idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """FG-276: the correction path of an accepted difference. The OWNER, with a reason,
    reverses every line booked now: an APPEND-ONLY reversal posting (−net, same target /
    project) in the period of the reversal — nothing is edited or deleted. Each reversed
    line is then open again (a DQ issue for the Accountant) and is re-booked through the
    FG-277 resolve action. The note itself (the tax document) and the payable are unchanged."""
    _guard(user)
    _approver(user)
    key = fin._require_key(idempotency_key)
    reason = _reason(body if isinstance(body, dict) else {})

    async def apply(tenant, note, session):
        acc = note["difference_accepted"]
        at = ic.now_iso()
        current: dict = {}
        for p in acc["postings"]:
            k = (p["original_line_id"], p["target"], p.get("project_id"), p.get("package_id"))
            current[k] = current.get(k, Decimal(0)) + ic.cents(p.get("net"))
        new = [ic._posting(ic.POSTING_REVERSAL, line, -net, target, at, period=at[:7], by=user["id"],
                           reason=reason, project_id=proj, package_id=pkg, basis="reversal")
               for (line, target, proj, pkg), net in current.items() if net != 0]
        if not new:
            raise ic.conflict(ic.NOT_PENDING, "Няма осчетоводена разлика за сторниране")
        for line in sorted({p["original_line_id"] for p in new}):
            await ic.open_dq_issue(
                tenant, kind=ic.DQ_DIFFERENCE_LINE_REVERSED, entity_type="finance.credit_note_line",
                entity_id="%s:%s:%s" % (note["id"], line, new[0]["id"]),
                title="сторнирана приета разлика: изберете обект или фирма",
                assignee_role="accountant", source="finance.credit_note.reverse_difference", session=session)
        return new, {"reversed_net": ic.money(sum((ic.cents(p["net"]) for p in new), Decimal(0))),
                     "cost_period": at[:7]}, reason, None

    return await _difference_write(user, note_id, key, "finance.credit_note.difference_reversed",
                                   {"note_id": note_id, "reason": reason}, apply)


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


@router.get("/finance/company-costs/accepted-differences")
async def company_cost_of_accepted_differences(period: Optional[str] = None,
                                               user: dict = Depends(require_m5)):
    """Read-only, Р58 / FG-265: the company costs (losses on a return) of accepted credit
    differences on warehouse-received lines, in the period of acceptance — derived from
    the accepted notes (no second ledger). ``period`` = YYYY-MM."""
    _guard(user)
    lines = await ic.company_cost_lines(fin._tenant(user), period)
    total = sum((ic.cents(l["value"]) for l in lines), Decimal(0))
    return {"period": period, "total": ic.money(total), "lines": lines}


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
    # FG-222 / FLOW-010 L355-357: an explicit legal / contractual basis, its document
    # (file_id) and the EXACT source obligations — the two invoices and the approved
    # credit note that created the balance — never free text alone.
    legal_basis, file_id = body.get("legal_basis"), body.get("file_id")
    note_src = body.get("source_credit_note_id")
    if (not isinstance(legal_basis, str) or not legal_basis.strip()
            or not isinstance(file_id, str) or not file_id.strip()
            or not isinstance(note_src, str) or not note_src):
        raise ic.unprocessable(ic.OFFSET_BASIS_REQUIRED,
                               "Прихващането изисква правно основание (legal_basis), документ "
                               "(file_id) и кредитното известие-източник (source_credit_note_id)")

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
            await _check_offset(tenant, src_id, tgt_id, amount, session, note_src, offset_id)
            at = ic.now_iso()
            await tenant.invoice_offsets.insert_one({
                "id": offset_id, "org_id": user["org_id"], "source_invoice_id": src_id,
                "target_invoice_id": tgt_id, "amount": ic.money(ic.cents(amount)), "reason": reason,
                "legal_basis": legal_basis.strip(), "file_id": file_id.strip(),
                "source_credit_note_id": note_src,
                "status": ic.OFFSET_PENDING, "version": 1, "contract_scope": list(ic.contract_key(src)),
                "created_by": user["id"], "created_at": at, "updated_at": at}, session=session)
            await fin._audit_tx(user, "finance.offset.requested", "finance.offset", offset_id, reason,
                                {"source_invoice_id": src_id, "target_invoice_id": tgt_id,
                                 "amount": amount, "status": ic.OFFSET_PENDING}, key, session)
        await fin._tx(run_in_transaction, tx_body)
        return await tenant.invoice_offsets.find_one({"id": offset_id}, {"_id": 0})

    return await fin._once(user, key, "finance.offset.create", {"body": body}, work)


async def _check_offset(tenant, src_id: str, tgt_id: str, amount, session,
                        note_id: Optional[str], offset_id: Optional[str]) -> None:
    src = await _claim(tenant, src_id, session)
    if note_id is not None:
        note = await tenant.credit_debit_notes.find_one(
            {"id": note_id, "original_invoice_id": src_id, "kind": ic.KIND_CREDIT, "applied": True,
             "status": {"$in": [ic.NOTE_APPROVED, ic.NOTE_REGISTERED]}}, {"_id": 0}, session=session)
        if note is None:
            raise ic.unprocessable(ic.OFFSET_BASIS_REQUIRED,
                                   "Източникът трябва да е приложено кредитно известие по фактурата-източник")
        used = Decimal(0)
        async for o in tenant.invoice_offsets.find(
                {"source_credit_note_id": note_id, "status": {"$in": [ic.OFFSET_PENDING, ic.OFFSET_APPROVED]},
                 "id": {"$ne": offset_id}}, {"_id": 0, "amount": 1}, session=session):
            used += ic.cents(o.get("amount"))
        if ic.cents(amount) > ic.cents(note.get("gross")) - used:
            raise ic.conflict(ic.OFFSET_EXCEEDS_BALANCE, "Сумата надвишава неизползваното по известието",
                              note_gross=note.get("gross"), already_offset=ic.money(used))
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
                                off["amount"], session, off.get("source_credit_note_id") or None,
                                offset_id)
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
        off = await tenant.invoice_offsets.find_one({"id": offset_id}, {"_id": 0})
        for inv_id in (off["source_invoice_id"], off["target_invoice_id"]):     # FG-246
            await fin._supersede_cancellation(tenant, user, inv_id, "offset")
        return off

    return await fin._once(user, key, "finance.offset.approve",
                           {"offset_id": offset_id, "version": version}, work)


@router.get("/finance/offsets")
async def list_offsets(user: dict = Depends(require_m5)):
    _guard(user)
    return await fin._tenant(user).invoice_offsets.find({}, {"_id": 0}).sort(
        "created_at", -1).to_list(500)
