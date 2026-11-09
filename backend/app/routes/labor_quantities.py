"""
Routes — LAB-02 (R33, Krum 07.11.2026): quantity entry + approval and the piece rate per SMR.

Canon: FLOW-028 (akord = APPROVED quantity × agreed piece rate), FLOW-019 (DOWNTIME apart),
CLAUDE.md §7/§8, R29 (money writes need an Idempotency-Key), R31 (SiteManager sees no
piece rate), R36 (who corrects a report), FG-64 / FG-72 (price and quantity only from records
the worker cannot write; an approval binds to report + version + entry).

* GET  /labor-terms?project_id=          — finance roles: pay type + piece rate per SMR package
* PUT  /labor-terms/{package_id}          — finance roles, Idempotency-Key, version + history
                                            + AuditEvent; never touches an approved quantity
                                            (an approval snapshots the terms it was given)
* PUT  /labor-quantities/entry            — the author enters the made quantity on their line
                                            (R36: own draft / returned; approvers any report)
* GET  /labor-quantities/pending?project_id= — approver: lines waiting for a quantity decision
* POST /labor-quantities/approve          — approver ≠ worker, Idempotency-Key, bound to
                                            (report, version, entry); re-approval voids the
                                            previous record (kept) — AuditEvent
* POST /labor-quantities/classify         — approver: LABOR / DOWNTIME / DOWNTIME_UNCLASSIFIED
                                            with a reason (FLOW-019), Idempotency-Key, AuditEvent

No hard delete anywhere: replaced records are marked ``void`` / kept in history.
"""
import math
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from app.db import db
from app.deps.auth import can_manage_project, get_current_user
from app.services.labor_cost import approval_key, void_labor_approvals
from app.services.report_corrections import (CORRECTOR, audit_report_correction, authorize_report_edit,
                                             correction_fields, refuse_if_in_payroll, reopen_effects,
                                             self_approval_ids)
from app.tenancy.data_access import TenantData

router = APIRouter(tags=["Labor quantities (LAB-02)"])

FINANCE_ROLES = ("Owner", "Admin", "Accountant")
PAY_TYPES = ("Akord", "Hourly", "Daily", "Monthly")
COST_TYPES = ("LABOR", "DOWNTIME", "DOWNTIME_UNCLASSIFIED")
REPORT_DECIDABLE = ("SUBMITTED", "APPROVED")


# LAB-02-B (audit LAB02-1): at most ONE active decision per line — (tenant, report, entry,
# version) is unique among the approved quantity records and among the active
# classifications. Concurrent approvals with different keys: one wins, the others get 409.
LINE_KEY = [("org_id", 1), ("report_id", 1), ("entry_id", 1), ("report_version", 1)]
LABOR_INDEXES = (
    ("labor_quantity_approvals", LINE_KEY,
     {"unique": True, "partialFilterExpression": {"status": "approved"}, "name": "one_approved_per_line"}),
    ("labor_line_classifications", LINE_KEY,
     {"unique": True, "partialFilterExpression": {"status": "active"}, "name": "one_active_per_line"}),
    # LAB-02-D (F-75-01): one history row per (tenant, package, version) — two concurrent
    # piece-rate changes can never both become the same version
    ("labor_terms_history", [("org_id", 1), ("package_id", 1), ("version", 1)],
     {"unique": True, "name": "one_terms_version_per_package"}),
)
_indexed = set()


async def ensure_labor_indexes(raw_db) -> int:
    """Create the unique partial indexes (startup; and lazily before the first decision in a
    database that missed startup). Idempotent."""
    key = (id(raw_db), raw_db.name)
    if key in _indexed:
        return 0
    for coll, keys, opts in LABOR_INDEXES:
        await raw_db[coll].create_index(keys, **opts)
    _indexed.add(key)
    return len(LABOR_INDEXES)


async def _insert_decision(collection, rec: dict):
    """Insert the one active decision of a line; a concurrent winner → 409, nothing written."""
    try:
        await collection.insert_one(dict(rec))
    except Exception as exc:
        if type(exc).__name__ == "DuplicateKeyError" or "duplicate key" in str(exc).lower():
            raise HTTPException(status_code=409, detail=(
                "За този ред току-що беше записано друго решение — презаредете и проверете"))
        raise


def _tenant(user: dict) -> TenantData:
    """The request's tenant — from the server-loaded session user only (W0-03E-A2C)."""
    return TenantData.for_user(db, user)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _finite(value, what: str, minimum: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(status_code=422, detail=f"{what}: трябва да е число")
    if not math.isfinite(number) or number < minimum:
        raise HTTPException(status_code=422, detail=f"{what}: трябва да е число ≥ {minimum}")
    return round(number, 4)


async def _audit(user: dict, *, action: str, entity_type: str, entity_id: str, version,
                 before: Optional[dict], after: Optional[dict], reason: str, endpoint: str,
                 idempotency_key: Optional[str] = None, session=None):
    from app.audit.envelope import build_event, RETENTION_R1_CRITICAL_BUSINESS
    from app.audit.store import record_event
    event = build_event(
        tenant_id=user["org_id"], actor_type="human", actor_id=user["id"], action=action,
        source_flow="FLOW-028", retention_class=RETENTION_R1_CRITICAL_BUSINESS,
        entity_type=entity_type, entity_id=entity_id, entity_version=str(version),
        structured_diff={"before": before, "after": after}, reason=reason,
        tool_or_endpoint=endpoint, idempotency_key=idempotency_key)
    return await record_event(db, event, session=session)


async def _run_tx(body):
    """LAB-02-D: ONE MongoDB transaction (auth_tx.run_in_transaction). A deployment without
    transactions is refused (503, nothing written) — no non-transactional path. (The DB-free
    tests replace this function explicitly: tests/test_lab_02_quantity_approval.py.)"""
    from app.services.auth_tx import TransactionsUnavailable, run_in_transaction
    try:
        return await run_in_transaction(db, body)
    except TransactionsUnavailable:
        raise HTTPException(status_code=503, detail=(
            "Базата данни не поддържа транзакции — промяната не е изпълнена"))


async def _idempotent(user: dict, key: Optional[str], action: str, payload: dict, perform, replay):
    """R29: a money/approval write runs once per Idempotency-Key (W0-04 registry)."""
    from app.audit.idempotency import (
        IDEMPOTENCY_COMPLETED, IDEMPOTENCY_DUPLICATE, IDEMPOTENCY_STARTED, IdempotencyConflict,
        begin_idempotent, complete_idempotent, fail_idempotent, request_fingerprint)
    from app.audit import idempotency as _idem
    k = (key or "").strip()
    if not k:
        raise HTTPException(status_code=428, detail="Липсва ключ за еднократност (Idempotency-Key) — презаредете и опитайте пак")
    if len(k) > 200:
        raise HTTPException(status_code=400, detail="Ключът за еднократност е твърде дълъг (до 200 знака)")
    unprotected = getattr(_idem, "IdempotencyUnprotected", None)
    try:
        state = await begin_idempotent(db, tenant_id=user["org_id"], key=k, action=action,
                                       request_fingerprint=request_fingerprint(payload))
    except IdempotencyConflict:
        raise HTTPException(status_code=409, detail="Този ключ за еднократност вече е използван за друга заявка")
    except Exception as exc:
        if unprotected is not None and isinstance(exc, unprotected):
            raise HTTPException(status_code=503, detail="Регистърът за еднократност не е защитен — нищо не е записано")
        raise
    if state.get("status") == IDEMPOTENCY_DUPLICATE:
        if state.get("prior_status") == IDEMPOTENCY_COMPLETED and state.get("result_reference"):
            found = await replay(state["result_reference"])
            if found is not None:
                return dict(found, idempotent_replay=True)
        raise HTTPException(status_code=409, detail="Същата заявка още се обработва — изчакайте")
    if state.get("status") != IDEMPOTENCY_STARTED:
        # audit RETAKE-1 (defence in depth): only an explicit STARTED reservation writes
        raise HTTPException(status_code=409, detail="Същата заявка още се обработва — изчакайте")
    try:
        result, ref = await perform(k)
    except HTTPException as exc:
        await fail_idempotent(db, tenant_id=user["org_id"], key=k, action=action,
                              error_code=f"http_{exc.status_code}")
        raise
    except Exception as exc:
        await fail_idempotent(db, tenant_id=user["org_id"], key=k, action=action,
                              error_code=type(exc).__name__)
        raise
    await complete_idempotent(db, tenant_id=user["org_id"], key=k, action=action, result_reference=ref)
    return result


# ═══════════════════════════════════════════════════════════════ the report line
async def _locate(tenant: TenantData, org_id: str, report_id: str, entry_id: Optional[str]):
    """(report doc, line view) for an old-style entry or a new-style flat report."""
    doc = await tenant.employee_daily_reports.find_one({"id": report_id, "org_id": org_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Отчетът не е намерен")
    status = (doc.get("approval_status") or doc.get("status") or "").upper()
    version = int(doc.get("report_version") or 0)
    if doc.get("day_entries") is not None and doc.get("employee_id"):
        entry = next((e for e in doc.get("day_entries") or [] if e.get("id") == entry_id), None)
        if not entry_id or entry is None:
            raise HTTPException(status_code=404, detail="Редът от отчета не е намерен")
        line = {"worker_id": doc.get("employee_id"), "project_id": entry.get("project_id"),
                "date": doc.get("report_date"), "hours": entry.get("hours_worked"),
                "quantity": entry.get("quantity"), "smr_type": entry.get("work_description") or "",
                "execution_package_id": entry.get("execution_package_id")}
    else:
        if entry_id:
            raise HTTPException(status_code=404, detail="Този отчет няма редове")
        line = {"worker_id": doc.get("worker_id"), "project_id": doc.get("project_id"),
                "date": doc.get("date"), "hours": doc.get("hours"), "quantity": doc.get("quantity"),
                "smr_type": doc.get("smr_type") or "", "execution_package_id": doc.get("execution_package_id")}
    line.update({"report_id": report_id, "entry_id": entry_id or None, "report_version": version,
                 "status": status})
    return doc, line


APPROVER_ROLES = ("Admin", "Owner", "SiteManager")


def _require_approver_role(user: dict):
    """First gate (before key / body checks): only approver roles get any further."""
    if user.get("role") not in APPROVER_ROLES:
        raise HTTPException(status_code=403, detail="Одобрява само Админ, Собственик или ръководителят на обекта")


async def _require_approver(user: dict, line: dict, doc: Optional[dict] = None):
    """Admin, Owner or the SiteManager of the line's project — never the worker himself, nor
    anyone who authored or corrected the report (LAB-01-I four-eyes, CLAUDE §8)."""
    if user.get("id") == line.get("worker_id") or user.get("id") in self_approval_ids(doc or {}):
        raise HTTPException(status_code=403, detail=(
            "Не можете да одобрите или класифицирате работа, която сте отчели или поправили — одобрява друг"))
    if user.get("role") in ("Admin", "Owner"):
        return
    if user.get("role") == "SiteManager" and line.get("project_id") and \
            await can_manage_project(user, line["project_id"]):
        return
    raise HTTPException(status_code=403, detail="Одобрява само Админ, Собственик или ръководителят на обекта")


# ═══════════════════════════════════════════════════════════════ 1. piece rate per SMR
class LaborTermsInput(BaseModel):
    labor_pay_type: Optional[str] = None
    labor_piece_rate: Optional[float] = None
    reason: str = ""


@router.get("/labor-terms")
async def list_labor_terms(project_id: str, user: dict = Depends(get_current_user)):
    if user.get("role") not in FINANCE_ROLES:
        raise HTTPException(status_code=403, detail="Акордните цени виждат само финансовите роли")
    tenant = _tenant(user)
    pkgs = await tenant.execution_packages.find(
        {"org_id": user["org_id"], "project_id": project_id},
        {"_id": 0, "id": 1, "project_id": 1, "activity_name": 1, "unit": 1, "qty": 1,
         "labor_pay_type": 1, "labor_piece_rate": 1, "labor_terms_version": 1,
         "labor_terms_updated_at": 1, "labor_terms_updated_by": 1}).to_list(500)
    return {"project_id": project_id, "items": pkgs}


async def _written_terms(tenant: TenantData, org_id: str, package_id: str, version) -> Optional[dict]:
    """FG-464: the answer of PUT /labor-terms (and of its replay) is the version THIS request
    wrote — its history row — never the package's current terms, which a later change may
    already have moved on."""
    pkg = await tenant.execution_packages.find_one({"org_id": org_id, "id": package_id}, {"_id": 0})
    if pkg is None or version is None:
        return pkg
    hist = await tenant.labor_terms_history.find_one(
        {"org_id": org_id, "package_id": package_id, "version": version}, {"_id": 0})
    if hist is None:
        return None
    return {**pkg, **(hist.get("after") or {}), "labor_terms_version": version,
            "labor_terms_updated_at": hist.get("changed_at"),
            "labor_terms_updated_by": hist.get("changed_by"),
            "written_version": version, "current_version": pkg.get("labor_terms_version")}


@router.put("/labor-terms/{package_id}")
async def set_labor_terms(package_id: str, data: LaborTermsInput, user: dict = Depends(get_current_user),
                          idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key")):
    if user.get("role") not in FINANCE_ROLES:
        raise HTTPException(status_code=403, detail="Акордна цена задават само Собственик, Админ или Счетоводител")
    pay_type = (data.labor_pay_type or "").strip() or None
    if pay_type is not None and pay_type not in PAY_TYPES:
        raise HTTPException(status_code=422, detail="Невалиден тип заплащане")
    rate = None if data.labor_piece_rate is None else _finite(data.labor_piece_rate, "labor_piece_rate")
    if pay_type == "Akord" and not rate:
        raise HTTPException(status_code=422, detail="За акорд е нужна акордна цена > 0")
    tenant = _tenant(user)
    org_id = user["org_id"]

    async def perform(key):
        if not await tenant.execution_packages.find_one({"org_id": org_id, "id": package_id}, {"_id": 0, "id": 1}):
            raise HTTPException(status_code=404, detail="СМР пакетът не е намерен")
        await ensure_labor_indexes(db)   # indexes cannot be created inside a transaction
        after = {"labor_pay_type": pay_type, "labor_piece_rate": rate}

        async def body(session):
            # LAB-02-D (F-75-01): ONE transaction — read the committed terms, take version+1 by a
            # compare-and-set on the package's current version, write the history row and the
            # chained AuditEvent. The driver retries the body on a write conflict, so a
            # concurrent change gets the NEXT version against the committed one (1, 2, … in the
            # real order); a lost compare-and-set without a retry is 409, nothing written.
            pkg = await tenant.execution_packages.find_one(
                {"org_id": org_id, "id": package_id}, {"_id": 0}, session=session)
            if not pkg:
                raise HTTPException(status_code=404, detail="СМР пакетът не е намерен")
            current = pkg.get("labor_terms_version")
            before = {"labor_pay_type": pkg.get("labor_pay_type"), "labor_piece_rate": pkg.get("labor_piece_rate")}
            version = int(current or 0) + 1
            now = _now()
            version_filter = ({"labor_terms_version": current} if current
                              else {"labor_terms_version": {"$in": [None, 0]}})
            res = await tenant.execution_packages.update_one(
                {"org_id": org_id, "id": package_id, **version_filter},
                {"$set": {**after, "labor_terms_version": version, "labor_terms_updated_at": now,
                          "labor_terms_updated_by": user["id"]}}, session=session)
            if not getattr(res, "modified_count", 0):
                raise HTTPException(status_code=409, detail=(
                    "Акордната цена току-що беше променена от друг човек — презаредете и опитайте пак"))
            hist = {"id": str(uuid.uuid4()), "org_id": org_id, "package_id": package_id,
                    "project_id": pkg.get("project_id"), "version": version, "before": before, "after": after,
                    "reason": data.reason, "changed_by": user["id"], "changed_at": now}
            try:
                await tenant.labor_terms_history.insert_one(dict(hist), session=session)
            except Exception as exc:
                if type(exc).__name__ == "DuplicateKeyError" or "duplicate key" in str(exc).lower():
                    raise HTTPException(status_code=409, detail=(
                        "Акордната цена току-що беше променена от друг човек — презаредете и опитайте пак"))
                raise
            await _audit(user, action="labor_terms.set", entity_type="execution_package", entity_id=package_id,
                         version=version, before=before, after=after,
                         reason=data.reason or "piece rate / pay type of the SMR (LAB-02)",
                         endpoint="PUT /labor-terms/{id}", idempotency_key=key, session=session)
            return version

        version = await _run_tx(body)
        return await _written_terms(tenant, org_id, package_id, version), f"{package_id}:{version}"

    async def replay(ref):
        pkg_id, _, ver = ref.rpartition(":")
        return await _written_terms(tenant, org_id, pkg_id, int(ver) if ver.isdigit() else None)

    return await _idempotent(user, idempotency_key, "labor_terms.set",
                             {"package_id": package_id, **data.model_dump()}, perform, replay)


# ═══════════════════════════════════════════════════════════════ 2. quantity entry
class QuantityEntryInput(BaseModel):
    report_id: str
    entry_id: Optional[str] = None
    quantity: Optional[float] = None


@router.put("/labor-quantities/entry")
async def enter_quantity(data: QuantityEntryInput, user: dict = Depends(get_current_user)):
    """The made quantity on a report line (R36: the author on own draft / returned report,
    an approver on any). A change bumps the version and voids the approvals."""
    tenant = _tenant(user)
    org_id = user["org_id"]
    qty = None if data.quantity is None else _finite(data.quantity, "quantity")
    doc, line = await _locate(tenant, org_id, data.report_id, data.entry_id)
    if doc.get("day_entries") is not None and doc.get("employee_id"):
        author_ids, statuses = (doc.get("employee_id"), doc.get("created_by")), ("DRAFT", "REJECTED")
    else:
        author_ids, statuses = (doc.get("submitted_by"), doc.get("worker_id")), ("Draft", "Rejected")
    mode = await authorize_report_edit(user, doc, projects=[line["project_id"]],
                                       author_ids=author_ids, author_statuses=statuses,
                                       tenant=tenant)  # LAB-01-J: pay-run lines lock it
    now = _now()
    await void_labor_approvals(tenant, org_id, data.report_id, user["id"],
                               "quantity_corrected" if mode == CORRECTOR else "quantity_entered")
    # LAB-01-I: a corrected APPROVED report goes back to SUBMITTED (four-eyes re-approval)
    extra, add = correction_fields(doc, user, mode, now)
    push = {"$addToSet": add} if add else {}
    if data.entry_id:
        await tenant.employee_daily_reports.update_one(
            {"org_id": org_id, "id": data.report_id, "day_entries.id": data.entry_id},
            {"$set": {"day_entries.$.quantity": qty, "updated_at": now, **extra}, **push})
    else:
        await tenant.employee_daily_reports.update_one(
            {"org_id": org_id, "id": data.report_id},
            {"$set": {"quantity": qty, "updated_at": now, **extra}, **push})
    await reopen_effects(tenant, org_id, doc, user, now)
    await audit_report_correction(db, user=user, mode=mode, report=doc,
                                  before={"quantity": line.get("quantity"), "entry_id": data.entry_id},
                                  after={"quantity": qty, "entry_id": data.entry_id},
                                  endpoint="PUT /labor-quantities/entry")
    _, fresh = await _locate(tenant, org_id, data.report_id, data.entry_id)
    return fresh


# ═══════════════════════════════════════════════════════════════ 3. pending list
@router.get("/labor-quantities/pending")
async def pending_quantities(project_id: str, user: dict = Depends(get_current_user)):
    """Lines of the project waiting for a quantity decision (approver view). A SiteManager
    sees quantity, unit and SMR — no piece rate (R31)."""
    if user.get("role") not in ("Admin", "Owner") and not (
            user.get("role") == "SiteManager" and await can_manage_project(user, project_id)):
        raise HTTPException(status_code=403, detail="Само Админ, Собственик или ръководителят на обекта")
    from app.services.report_normalizer import fetch_normalized_report_lines
    tenant = _tenant(user)
    org_id = user["org_id"]
    lines = []
    for status in REPORT_DECIDABLE:
        lines += await fetch_normalized_report_lines(org_id=org_id, project_id=project_id, status_filter=status)
    lines = [ln for ln in lines if ln.get("project_id") == project_id]
    report_ids = sorted({ln.get("report_doc_id") for ln in lines if ln.get("report_doc_id")})
    approvals = await tenant.labor_quantity_approvals.find(
        {"org_id": org_id, "report_id": {"$in": report_ids}, "status": "approved"}, {"_id": 0}).to_list(5000)
    by_key = {approval_key(a.get("report_id"), a.get("entry_id"), a.get("report_version")): a for a in approvals}
    pkgs = await tenant.execution_packages.find(
        {"org_id": org_id, "project_id": project_id},
        {"_id": 0, "id": 1, "activity_name": 1, "unit": 1}).to_list(500)
    users = await tenant.users.find({"org_id": org_id}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1}).to_list(2000)
    names = {u["id"]: f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() for u in users}
    finance = user.get("role") in FINANCE_ROLES
    items = []
    for ln in sorted(lines, key=lambda x: (x.get("date") or "", x.get("worker_id") or "")):
        key = approval_key(ln.get("report_doc_id"), ln.get("entry_id"), ln.get("report_version"))
        appr = by_key.get(key)
        item = {
            "report_id": ln.get("report_doc_id"), "entry_id": ln.get("entry_id"),
            "report_version": ln.get("report_version"), "report_status": ln.get("status"),
            "date": ln.get("date"), "worker_id": ln.get("worker_id"),
            "worker_name": ln.get("worker_name") or names.get(ln.get("worker_id"), ""),
            "smr_type": ln.get("smr_type"), "hours": ln.get("hours"), "quantity": ln.get("quantity"),
            "suggested_package_id": ln.get("execution_package_id"),
            "approval": None if not appr else {
                "id": appr.get("id"), "approved_quantity": appr.get("approved_quantity"), "unit": appr.get("unit"),
                "execution_package_id": appr.get("execution_package_id"),
                "approved_by": appr.get("approved_by"), "approved_at": appr.get("approved_at"),
                **({"piece_rate": appr.get("piece_rate")} if finance else {})},
            "state": "approved" if appr else ("waiting" if ln.get("quantity") else "no_quantity"),
        }
        items.append(item)
    return {"project_id": project_id, "packages": pkgs, "items": items,
            "waiting": sum(1 for i in items if i["state"] == "waiting")}


# ═══════════════════════════════════════════════════════════════ 4. approve
class QuantityApprovalInput(BaseModel):
    report_id: str
    entry_id: Optional[str] = None
    report_version: int
    approved_quantity: float
    execution_package_id: str
    note: str = ""
    # LAB-02-C (FG-101): a correction names the active approval it replaces (compare-and-set);
    # without it a line that is already approved is 409 ALREADY_APPROVED.
    replaces_approval_id: Optional[str] = None


@router.post("/labor-quantities/approve")
async def approve_quantity(data: QuantityApprovalInput, user: dict = Depends(get_current_user),
                           idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key")):
    _require_approver_role(user)
    tenant = _tenant(user)
    org_id = user["org_id"]
    qty = _finite(data.approved_quantity, "approved_quantity")

    async def perform(key):
        doc, line = await _locate(tenant, org_id, data.report_id, data.entry_id)
        await _require_approver(user, line, doc)
        await refuse_if_in_payroll(tenant, org_id, doc)  # LAB-02-B (FG-93): paid → 409
        if line["status"] not in REPORT_DECIDABLE:
            raise HTTPException(status_code=409, detail="Количество се одобрява само по подаден или одобрен отчет")
        if int(data.report_version) != line["report_version"]:
            raise HTTPException(status_code=409, detail=(
                f"Отчетът е променен (версия {line['report_version']}, не {data.report_version}) — презаредете"))
        pkg = await tenant.execution_packages.find_one({"org_id": org_id, "id": data.execution_package_id}, {"_id": 0})
        if not pkg or pkg.get("project_id") != line["project_id"]:
            raise HTTPException(status_code=422, detail="СМР пакетът трябва да е от обекта на реда")
        now = _now()
        k = approval_key(data.report_id, data.entry_id, line["report_version"])
        prev = await tenant.labor_quantity_approvals.find(
            {"org_id": org_id, "report_id": data.report_id, "status": "approved"}, {"_id": 0}).to_list(100)
        prev = [p for p in prev if approval_key(p.get("report_id"), p.get("entry_id"), p.get("report_version")) == k]
        # LAB-02-C (FG-101): a second approver of the same version does not silently replace
        # the first; a correction must name the active record it replaces.
        if prev and data.replaces_approval_id not in {p["id"] for p in prev}:
            raise HTTPException(status_code=409, detail={
                "code": "ALREADY_APPROVED", "approval_id": prev[-1]["id"],
                "message": ("Количеството по този ред вече е одобрено — презаредете; "
                            "за промяна използвайте „Коригирай одобрението“")})
        if not prev and data.replaces_approval_id:
            raise HTTPException(status_code=409, detail=(
                "Одобрението, което коригирате, вече не е активно — презаредете"))
        for p in prev:  # a correction of the decision: the old record is kept, marked void
            res = await tenant.labor_quantity_approvals.update_one(
                {"org_id": org_id, "id": p["id"], "status": "approved"},
                {"$set": {"status": "void", "voided_at": now, "voided_by": user["id"], "void_reason": "re-approved"}})
            if not res.modified_count:  # another correction won the race
                raise HTTPException(status_code=409, detail=(
                    "Одобрението току-що беше променено от друг човек — презаредете"))
        rec = {
            "id": str(uuid.uuid4()), "org_id": org_id, "report_id": data.report_id,
            "entry_id": data.entry_id or None, "report_version": line["report_version"],
            "worker_id": line["worker_id"], "project_id": line["project_id"], "date": line["date"],
            "entered_quantity": line.get("quantity"), "approved_quantity": qty,
            "unit": pkg.get("unit") or "", "execution_package_id": pkg["id"],
            # the SMR terms at the moment of approval — a later price change does not touch it
            "labor_pay_type": pkg.get("labor_pay_type"), "piece_rate": pkg.get("labor_piece_rate"),
            "labor_terms_version": pkg.get("labor_terms_version") or 0,
            "status": "approved", "approved_by": user["id"], "approved_at": now, "note": data.note,
            "replaces": [p["id"] for p in prev], "idempotency_key": key,
        }
        await ensure_labor_indexes(db)
        await _insert_decision(tenant.labor_quantity_approvals, rec)
        await _audit(user, action="labor_quantity.corrected" if prev else "labor_quantity.approved",
                     entity_type="labor_quantity_approval", entity_id=rec["id"], version=line["report_version"],
                     before={"approved_quantity": prev[-1].get("approved_quantity")} if prev else None,
                     after={"approved_quantity": qty, "unit": rec["unit"], "execution_package_id": pkg["id"],
                            "entered_quantity": line.get("quantity")},
                     reason=data.note or "quantity approval (LAB-02)",
                     endpoint="POST /labor-quantities/approve", idempotency_key=key)
        rec.pop("_id", None)
        return rec, rec["id"]

    async def replay(ref):
        return await tenant.labor_quantity_approvals.find_one({"org_id": org_id, "id": ref}, {"_id": 0})

    return await _idempotent(user, idempotency_key, "labor_quantity.approve", data.model_dump(), perform, replay)


# ═══════════════════════════════════════════════════════════════ 5. DOWNTIME classification
class ClassifyInput(BaseModel):
    report_id: str
    entry_id: Optional[str] = None
    report_version: int
    cost_type: str
    reason: str = ""
    responsible_party: Optional[str] = None


@router.post("/labor-quantities/classify")
async def classify_line(data: ClassifyInput, user: dict = Depends(get_current_user),
                        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key")):
    _require_approver_role(user)
    tenant = _tenant(user)
    org_id = user["org_id"]
    cost_type = (data.cost_type or "").strip().upper()
    if cost_type not in COST_TYPES:
        raise HTTPException(status_code=422, detail="Невалиден вид разход")
    if cost_type != "LABOR" and not data.reason.strip():
        raise HTTPException(status_code=422, detail="Престоят изисква причина")

    async def perform(key):
        doc, line = await _locate(tenant, org_id, data.report_id, data.entry_id)
        await _require_approver(user, line, doc)
        await refuse_if_in_payroll(tenant, org_id, doc)  # LAB-02-B (FG-93): paid → 409
        if line["status"] not in REPORT_DECIDABLE:  # LAB-02-B (FG-94): no draft lines
            raise HTTPException(status_code=409, detail="Класифицира се само подаден или одобрен ред")
        if int(data.report_version) != line["report_version"]:
            raise HTTPException(status_code=409, detail=(
                f"Отчетът е променен (версия {line['report_version']}, не {data.report_version}) — презаредете"))
        now = _now()
        k = approval_key(data.report_id, data.entry_id, line["report_version"])
        prev = await tenant.labor_line_classifications.find(
            {"org_id": org_id, "report_id": data.report_id, "status": "active"}, {"_id": 0}).to_list(100)
        prev = [p for p in prev if approval_key(p.get("report_id"), p.get("entry_id"), p.get("report_version")) == k]
        for p in prev:
            await tenant.labor_line_classifications.update_one(
                {"org_id": org_id, "id": p["id"], "status": "active"},
                {"$set": {"status": "void", "voided_at": now, "voided_by": user["id"], "void_reason": "reclassified"}})
        rec = {"id": str(uuid.uuid4()), "org_id": org_id, "report_id": data.report_id,
               "entry_id": data.entry_id or None, "report_version": line["report_version"],
               "worker_id": line["worker_id"], "project_id": line["project_id"], "date": line["date"],
               "hours": line.get("hours"), "cost_type": cost_type, "reason": data.reason,
               "responsible_party": data.responsible_party, "status": "active",
               "classified_by": user["id"], "classified_at": now, "replaces": [p["id"] for p in prev],
               "idempotency_key": key}
        await ensure_labor_indexes(db)
        await _insert_decision(tenant.labor_line_classifications, rec)
        await _audit(user, action="labor_line.classified", entity_type="labor_line_classification",
                     entity_id=rec["id"], version=line["report_version"],
                     before={"cost_type": prev[-1].get("cost_type")} if prev else None,
                     after={"cost_type": cost_type, "reason": data.reason,
                            "responsible_party": data.responsible_party},
                     reason=data.reason or "line classification (LAB-02)",
                     endpoint="POST /labor-quantities/classify", idempotency_key=key)
        rec.pop("_id", None)
        return rec, rec["id"]

    async def replay(ref):
        return await tenant.labor_line_classifications.find_one({"org_id": org_id, "id": ref}, {"_id": 0})

    return await _idempotent(user, idempotency_key, "labor_line.classify", data.model_dump(), perform, replay)
