"""
CP-01 §1 — FLOW-006 blocking: a payment to a counterparty is EXECUTED only to a bank
account in status ``verified`` (FLOW-010 §8.1 L250/L254, FLOW-025 L187, R48.1/R48.2).

``check_payment_target`` is called by every path that executes an outgoing payment to a
counterparty — manual payment / advance (``POST /finance/payments``), invoice quick-pay
(``POST /finance/invoices/{id}/payments``) and subcontractor payment
(``POST /subcontractor-payments``) — BEFORE anything is written. It returns the account
stamp to put on the payment row (``bank_account_id`` + masked IBAN) or raises.

Rules (no flag, role or Approval unlocks them — FLOW-025 L187):

1. ``bank_account_id`` named → it must be this tenant's, of this counterparty, ``verified``
   → else 409 BANK_ACCOUNT_NOT_VERIFIED, nothing written.
2. the invoice carries an IBAN (free text, FG-175) → it must equal a ``verified`` account of
   the invoice's counterparty → else a critical DQ row (L254) + 409 BANK_ACCOUNT_NOT_VERIFIED.
3. the counterparty has a ``verified`` account → the payment goes to it (a pending change
   never receives money before its double approval).
4. the counterparty has only unverified accounts → 409 BANK_ACCOUNT_NOT_VERIFIED.
5. legacy — no account named, none registered, or no counterparty identified —
   ``BANK_ACCOUNT_GUARD_MODE``: off = log only, shadow = DQ row + metric, enforce = 409.

Cash to a counterparty (R50.1): only with a receipt ``file_id`` + the recipient's name, and
blocked (409 PAYEE_BLOCKED_PENDING_IBAN) while the counterparty has an unverified IBAN. Incoming payments are not checked. A verified IBAN is NOT an
approval of the payment (FLOW-010 L296): every other payment rule still applies.
"""
import logging
from typing import Any, Dict, Optional

from fastapi import HTTPException

from app.services import counterparty_rules as cr
from app.services.master_write import dq_issue

logger = logging.getLogger(__name__)

BANK_ACCOUNT_NOT_VERIFIED = "BANK_ACCOUNT_NOT_VERIFIED"
COUNTERPARTY_NOT_SELECTABLE = "COUNTERPARTY_NOT_SELECTABLE"
PARTY_COLLECTIONS = {"counterparty": "counterparties", "subcontractor": "subcontractors"}

#: shadow-mode metric (process-local counter; the DQ row is the durable trace)
METRICS: Dict[str, int] = {"legacy_unverified_payments": 0}


def _refuse(reason: str, message: str, **extra) -> HTTPException:
    return HTTPException(status_code=409, detail=dict({
        "error_code": BANK_ACCOUNT_NOT_VERIFIED, "reason": reason, "message": message}, **extra))


def _stamp(account: Dict[str, Any]) -> Dict[str, Any]:
    return {"bank_account_id": account["id"], "bank_account_iban_masked": cr.mask_iban(account.get("iban"))}


PAYEE_BLOCKED_PENDING_IBAN = "PAYEE_BLOCKED_PENDING_IBAN"
CASH_RECEIPT_REQUIRED = "CASH_RECEIPT_REQUIRED"


async def payee_by_eik(tenant, eik: Any):
    e = cr.normalize_eik(eik)
    if not e:
        return None, None
    return await resolve_invoice_party(tenant, {"counterparty_eik": e})


COUNTERPARTY_REQUIRED = "COUNTERPARTY_REQUIRED"


def _receipt_id(receipt_file_id) -> str:
    fid = receipt_file_id.strip() if isinstance(receipt_file_id, str) else ""
    if not fid or "://" in fid or "/" in fid or "\\" in fid:
        return ""
    return fid


CASH_RECEIPT_NOT_REGISTERED = "CASH_RECEIPT_NOT_REGISTERED"
CASH_RECEIPT_TYPE_NOT_ALLOWED = "CASH_RECEIPT_TYPE_NOT_ALLOWED"
#: R71: a receipt is a photo or a PDF (R72 — OCR into lines — is a separate future task)
_RECEIPT_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".gif", ".bmp",
                       ".tif", ".tiff", ".pdf")


def _receipt_type_ok(doc: Dict[str, Any]) -> bool:
    ctype = str(doc.get("content_type") or "").strip().lower()
    if ctype:
        return ctype.startswith("image/") or ctype == "application/pdf"
    name = str(doc.get("filename") or doc.get("stored_filename") or "").strip().lower()
    return name.endswith(_RECEIPT_EXTENSIONS)


#: the payment records that carry a receipt ``file_id`` (FG-425)
_RECEIPT_HOLDERS = ("finance_payments", "subcontractor_payments")


async def receipt_references(tenant, file_id: str) -> list:
    """FG-425: the payment rows that rest on ``file_id`` as their cash receipt."""
    refs = []
    for coll in _RECEIPT_HOLDERS:
        rows = await tenant.collection(coll).find({"cash_receipt_file_id": file_id},
                                                  {"_id": 0, "id": 1}).to_list(20)
        refs += ["%s:%s" % (coll, r.get("id")) for r in rows]
    return refs
#: a file record in one of these states is not evidence any more
_INACTIVE_FILE_STATES = frozenset({"deleted", "archived", "quarantined", "rejected", "superseded"})


async def _require_registered_receipt(tenant, fid: str) -> str:
    """FG-290: the receipt ``file_id`` must be a file record of THIS tenant, in an active
    state — an invented id, another tenant's file or a deleted one → 422, nothing written.

    W0-06 (File Registry, FLOW-016) is NOT STARTED (Gate Matrix); until it lands the
    tenant's file records are the legacy ``media_files`` (TenantData scopes the read to the
    active tenant). D10: switch this lookup to the File Registry when W0-06 lands."""
    doc = await tenant.media_files.get(fid, {"_id": 0, "id": 1, "status": 1, "deleted_at": 1,
                                             "is_deleted": 1, "content_type": 1, "filename": 1,
                                             "stored_filename": 1})
    state = str((doc or {}).get("status") or "").strip().lower()
    if not doc or state in _INACTIVE_FILE_STATES or doc.get("deleted_at") or doc.get("is_deleted"):
        raise HTTPException(status_code=422, detail={
            "error_code": CASH_RECEIPT_NOT_REGISTERED,
            "message": "Касовият бон / разписката трябва да е качен файл на тази фирма "
                       "(file_id от регистъра на файловете), в активно състояние (FG-290)"})
    if not _receipt_type_ok(doc):
        raise HTTPException(status_code=422, detail={
            "error_code": CASH_RECEIPT_TYPE_NOT_ALLOWED,
            "message": "Разписката / касовият бон трябва да е снимка или PDF (Р71)"})
    return fid


async def _check_cash(tenant, accounts, party_type, party_id, receipt_file_id, recipient_name,
                      payee_named: bool = False):
    """Cash out — R59 (Krum, 08.11.2026, FG-268) + R50.1:
    * to a company or person: ONLY with a counterparty chosen from the list
      (``counterparty_id``); a name or ЕИК alone → 422 COUNTERPARTY_REQUIRED (the Accountant
      creates the counterparty first). Then a receipt / cash document (``file_id``) with the
      recipient's name, and while the counterparty has an unverified IBAN → 409 (R50.1);
    * a small expense with no counterparty (fuel, a shop): only with a till receipt
      (``cash_receipt_file_id``) — recorded as an expense with no payee."""
    if not party_id and payee_named:
        raise HTTPException(status_code=422, detail={
            "error_code": COUNTERPARTY_REQUIRED,
            "message": "Плащане в брой към фирма или лице — само с контрагент от списъка "
                       "(counterparty_id); ако липсва, Счетоводителят първо го създава (Р59)"})
    if not party_id:
        fid = _receipt_id(receipt_file_id)
        if not fid:
            raise HTTPException(status_code=422, detail={
                "error_code": CASH_RECEIPT_REQUIRED,
                "message": "Дребен разход без контрагент — само с касов бон "
                           "(cash_receipt_file_id) (Р59)"})
        await _require_registered_receipt(tenant, fid)
        return {"cash_receipt_file_id": fid, "cash_expense_without_payee": True}
    pending = await accounts.count({"party_type": party_type, "counterparty_id": party_id,
                                    "status": cr.BA_PENDING})
    if pending:
        raise HTTPException(status_code=409, detail={
            "error_code": PAYEE_BLOCKED_PENDING_IBAN,
            "message": "Получателят има непроверен (нов/сменен) IBAN — плащането, и в брой, е "
                       "спряно до проверката (Р50.1)"})
    fid = _receipt_id(receipt_file_id)
    name = recipient_name.strip() if isinstance(recipient_name, str) else ""
    if not fid or not name:
        raise HTTPException(status_code=422, detail={
            "error_code": CASH_RECEIPT_REQUIRED,
            "message": "Плащане в брой към контрагент — само срещу разписка/касов документ "
                       "(cash_receipt_file_id) с име на получателя (cash_recipient_name)"})
    await _require_registered_receipt(tenant, fid)
    return {"cash_receipt_file_id": fid, "cash_recipient_name": name}


def is_cash_account(account: Optional[Dict[str, Any]]) -> bool:
    """FG-225: the account decides — a Cash (Каса) account is cash, anything else is bank."""
    t = str((account or {}).get("type") or (account or {}).get("account_type") or "").strip().lower()
    return t in ("cash", "каса")


async def check_allocation(tenant, user: Dict[str, Any], payment: Dict[str, Any],
                           invoice: Dict[str, Any], *, path: str = "/finance/payments/{id}/allocate"):
    """FG-225 (a): allocating an EXISTING outgoing payment to a received invoice is a payment
    to that invoice's counterparty — the same rules, against what the payment really did:
    a payment of another counterparty → 409; a bank payment must have gone to a verified
    account of THIS counterparty (and match the invoice IBAN); a cash payment needs its
    receipt and is blocked while the counterparty's IBAN is unverified."""
    if payment.get("direction") != "Outflow" or invoice.get("direction") == "Issued":
        return None
    party_type, party_id = await resolve_invoice_party(tenant, invoice)
    if payment.get("counterparty_id") and party_id and payment["counterparty_id"] != party_id:
        raise _refuse("PAYEE_MISMATCH", "Плащането е към друг контрагент — не се разпределя по "
                                        "тази фактура")
    account = await tenant.financial_accounts.get(payment.get("account_id"), {"_id": 0})
    return await check_payment_target(
        tenant, user, direction="Outflow", method=payment.get("method"),
        account=account or {"type": "Bank"}, party_type=party_type, party_id=party_id,
        bank_account_id=payment.get("bank_account_id"),
        invoice_iban=invoice.get("counterparty_iban"),
        cash_receipt_file_id=payment.get("cash_receipt_file_id"),
        cash_recipient_name=payment.get("cash_recipient_name"),
        payee_name=payment.get("counterparty_name") or invoice.get("counterparty_name"),
        payee_eik=invoice.get("counterparty_eik"), auto_resolve=False, path=path)


async def resolve_invoice_party(tenant, invoice: Dict[str, Any]):
    """(party_type, party_id) of a received invoice: its ``supplier_counterparty_id``, else the
    counterparty with the invoice's ЕИК. (None, None) when neither identifies one."""
    cp_id = invoice.get("supplier_counterparty_id") or invoice.get("counterparty_id")
    if cp_id:
        return "counterparty", cp_id
    eik = cr.normalize_eik(invoice.get("counterparty_eik"))
    if eik:
        for cp in await tenant.counterparties.find({"eik": {"$exists": True}},
                                                   {"_id": 0, "id": 1, "eik": 1}).to_list(5000):
            if cr.normalize_eik(cp.get("eik")) == eik:
                return "counterparty", cp["id"]
    return None, None


async def require_selectable_party(tenant, party_type: Optional[str], party_id: Optional[str]):
    """R48.4: an inactive / archived counterparty is not chosen for a new payment → 422."""
    if not party_type or not party_id:
        return None
    coll = PARTY_COLLECTIONS[party_type]
    doc = await tenant.collection(coll).get(party_id, {"_id": 0})
    if doc is None:
        raise HTTPException(status_code=422, detail={
            "error_code": "COUNTERPARTY_NOT_FOUND", "message": "Контрагентът не съществува в тази фирма"})
    if not cr.is_selectable(doc, coll):
        raise HTTPException(status_code=422, detail={
            "error_code": COUNTERPARTY_NOT_SELECTABLE,
            "lifecycle_status": cr.lifecycle_of(doc, coll),
            "message": "Контрагентът е неактивен или архивиран — не може да се избира за нови документи"})
    return doc


async def check_payment_target(tenant, user: Dict[str, Any], *, direction: str, method: Any,
                               party_type: Optional[str], party_id: Optional[str],
                               bank_account_id: Optional[str] = None,
                               invoice_iban: Optional[str] = None,
                               cash_receipt_file_id: Any = None,
                               cash_recipient_name: Any = None,
                               account: Optional[Dict[str, Any]] = None,
                               auto_resolve: bool = True,
                               payee_name: Any = None, payee_eik: Any = None,
                               path: str = "") -> Optional[Dict[str, Any]]:
    """``account`` (FG-225): the cash/bank account the money ACTUALLY leaves. When given, it
    decides the method — a Cash account is cash (receipt + payee block, R50.1), any other is
    a bank transfer (IBAN check) — whatever the request's ``method`` says. ``auto_resolve``:
    with no ``bank_account_id``, route to the payee's one verified account (a new payment);
    False for an existing payment (allocate), whose target cannot be chosen afterwards."""
    if direction != "Outflow":
        return None
    accounts = tenant.verified_bank_accounts
    payee_named = bool((isinstance(payee_name, str) and payee_name.strip()) or cr.normalize_eik(payee_eik))
    eik_resolved = False
    if cr.normalize_eik(payee_eik):
        # FG-268: an ЕИК in the request is always checked — it names the payee
        etype, eid = await payee_by_eik(tenant, payee_eik)
        if eid and party_id and eid != party_id:
            raise _refuse("PAYEE_MISMATCH", "ЕИК в заявката е на друг контрагент")
        if eid and not party_id:
            party_type, party_id = etype, eid
            eik_resolved = True
    # R59: a name is NOT matched to a counterparty any more — cash to a named payee needs a
    # counterparty_id (422). The ЕИК above stays as a defence (mismatch → 409; for a bank
    # transfer it resolves the payee, so the IBAN rules apply).
    if account is not None:
        method = "cash" if is_cash_account(account) else "bank"

    if bank_account_id:
        acc = await accounts.get(bank_account_id, {"_id": 0}) if isinstance(bank_account_id, str) else None
        if acc is None or (party_id and (acc.get("counterparty_id") != party_id
                                         or acc.get("party_type") != party_type)):
            raise _refuse("BANK_ACCOUNT_UNKNOWN",
                          "Банковата сметка не е на този контрагент — плащането не е изпълнено")
        if acc.get("status") != cr.BA_VERIFIED:
            raise _refuse("BANK_ACCOUNT_" + str(acc.get("status") or "unknown").upper(),
                          "Банковата сметка не е проверена (%s) — плащането може да е само чернова"
                          % cr.BA_LABELS.get(acc.get("status"), acc.get("status")),
                          bank_account_status=acc.get("status"))
        if invoice_iban and cr.normalize_iban(invoice_iban) != acc.get("iban"):
            await _iban_mismatch(tenant, user, party_type, party_id, invoice_iban, path)
        return _stamp(acc)

    if invoice_iban:
        iban = cr.normalize_iban(invoice_iban)
        match = None
        if party_id:
            match = await accounts.find_one({"party_type": party_type, "counterparty_id": party_id,
                                             "iban": iban, "status": cr.BA_VERIFIED}, {"_id": 0})
        if match is None:
            await _iban_mismatch(tenant, user, party_type, party_id, iban, path)
        if cr.is_cash_method(method):          # cash: the receipt rule still applies (R50.1)
            return await _check_cash(tenant, accounts, party_type, None if eik_resolved else party_id,
                                     cash_receipt_file_id, cash_recipient_name,
                                     payee_named or bool(party_id))
        if not auto_resolve:
            # an existing payment whose account was never recorded: the money's target is
            # unknown — it cannot be proved to be this verified account (legacy, by mode)
            return await _legacy(tenant, user, party_type, party_id, path)
        return _stamp(match)

    if cr.is_cash_method(method):
        return await _check_cash(tenant, accounts, party_type, None if eik_resolved else party_id,
                                 cash_receipt_file_id, cash_recipient_name, payee_named)

    if party_id:
        verified = await accounts.find({"party_type": party_type, "counterparty_id": party_id,
                                        "status": cr.BA_VERIFIED}, {"_id": 0}).to_list(10)
        if len(verified) == 1 and auto_resolve:
            return _stamp(verified[0])
        if len(verified) > 1:          # never expected: the change flow keeps one current account
            raise _refuse("BANK_ACCOUNT_AMBIGUOUS",
                          "Контрагентът има повече от една проверена сметка — посочете bank_account_id")
        pending = await accounts.count({"party_type": party_type, "counterparty_id": party_id,
                                        "status": cr.BA_PENDING})
        if pending:
            raise _refuse("BANK_ACCOUNT_PENDING",
                          "Сметката на контрагента е „за проверка“ — плащането може да е само чернова")

    return await _legacy(tenant, user, party_type, party_id, path)


async def _iban_mismatch(tenant, user, party_type, party_id, iban, path):
    """FG-175 / FLOW-010 L254: a critical DQ row (written outside any transaction, so it
    survives the refusal) + 409. Nothing unlocks it (FLOW-025 L187)."""
    await dq_issue(tenant, None, code="INVOICE_IBAN_MISMATCH", severity="critical",
                   entity_type=party_type or "invoice", entity_id=party_id,
                   message="IBAN във фактурата не съвпада с проверена сметка — плащането е блокирано",
                   data={"iban_masked": cr.mask_iban(iban), "path": path},
                   created_by=user.get("id"))
    raise _refuse("INVOICE_IBAN_MISMATCH",
                  "IBAN във фактурата не съвпада с проверена сметка на контрагента — "
                  "плащането е блокирано до проверка", iban_masked=cr.mask_iban(iban))


async def _legacy(tenant, user, party_type, party_id, path):
    mode = cr.bank_guard_mode()
    if mode == cr.GUARD_ENFORCE:
        raise _refuse("NO_VERIFIED_BANK_ACCOUNT",
                      "Няма проверена банкова сметка на получателя — плащането не е изпълнено")
    if mode == cr.GUARD_SHADOW:
        METRICS["legacy_unverified_payments"] += 1
        await dq_issue(tenant, None, code="PAYMENT_WITHOUT_VERIFIED_ACCOUNT", severity="warning",
                       entity_type=party_type or "payment", entity_id=party_id,
                       message="Плащане без проверена банкова сметка (shadow; enforce би отказал)",
                       data={"path": path}, created_by=user.get("id"))
    logger.info("cp-01 bank guard %s: payment without a verified account (path=%s party=%s)",
                mode, path, party_type or "-")
    return None
