"""
Service — LAB-AKORD-01: the WRITE side of the akord quantity (FLOW-028, Р100, Р96).

Decisions / canon: FLOW-028 ("заработка = одобрено измерено количество × договорена единична
цена труд"; "Без одобрено количество или цена не възниква окончателно задължение";
"двустепенно одобрение"), Р100 (from #73/#75 we take: a line is not paid twice, four-eyes,
P&L = pay run; payment of manual rows R85/R91 is NOT taken), Р96 (labor = the daily report
line; ``labor_entries`` are never paid), CLAUDE.md §7 (correction instead of editing an
official record), §8, §14.

Design note
-----------
* Ported from #75 (``routes/labor_quantities.py`` on claude/lab-02-quantity-approval): the
  record collection ``labor_quantity_approvals`` and its binding to a line (report_id +
  entry_id + report_version), "one approved per line" (here a partial unique index on
  ``approved_slot``), the approver gate (Admin / Owner / the SiteManager of the project),
  four-eyes (``self_approval_ids``), the price snapshot at approval (``piece_rate`` +
  ``labor_terms_version`` from ``execution_packages.labor_piece_rate``), a correction keeps
  the old record (never overwritten), the W0-04 Idempotency-Key registry (R29: no key → 428),
  the per-SMR unit labor price with version + history (``PUT /labor-terms``, finance roles).
* NOT ported: anything that pays ``labor_entries`` / manual rows (R85/R91 → Р96), the
  per-line / per-SMR pay type (the reader takes akord from the worker profile only), the
  DOWNTIME classification, the R77 flags of manual rows, the quantity stored ON the report
  line (here the line is not touched: an approved line is locked, Р100).
* The line: a flat line of the "Отчет на труда" service (``employee_daily_reports`` with
  ``worker_id``), ``report_id`` = the line id, ``entry_id`` None, ``report_version`` = the
  line's (0 today) — exactly the key ``labor_cost_reader.akord_terms`` reads. Old-format
  reports are not written here (step 5 / ОП-2).
* Record life: ``pending`` (entered, waits) → ``approved`` | ``rejected``. A new entry on a
  line with an approved quantity is a CORRECTION: a new pending record (``quantity_version``
  + 1, ``replaces`` = the approved one); the approved one stays valid (the pay run keeps
  using it) until the correction is approved, then it becomes ``superseded`` (kept, with
  ``superseded_by``). A rejection of an approved record (unpaid line) is a revocation: the
  line is blocked again. Nothing is deleted.
* One open decision per line: ``pending_slot`` / ``approved_slot`` (= ``report|entry|ver``)
  exist only while the record is pending / approved; partial unique indexes
  (``offline_sync.UNIQUE_INDEXES``, built at startup) make a concurrent second pending /
  approved record a 409. Without transactions the order is fail-closed: the old approval
  is superseded BEFORE the new one is approved, so a lost race leaves the line blocked
  (0 payable), never paid twice.
* Who enters: the same rule as the labor line (``labor_report_service.check_may_report``):
  the worker for himself, Technician / SiteManager on a project they belong to, office
  roles (Admin, Owner, Accountant) for anyone.
  Who approves / rejects: Admin, Owner, or a SiteManager of the line's project (#75); never
  the worker, the person who entered the quantity, nor an author / corrector of the line.
  Who sets the unit price: Owner, Admin, Accountant (#75 finance roles; R31: SiteManager
  sees no price).
* Payment lock: a line in a pay run (batched) or paid → 409 on enter / approve / reject; the
  correction goes through the pay run reopen / reversal path (``labor_report_service``).
* AuditEvent: ``labor_quantity.entered / correction_entered / approved / corrected /
  rejected`` and ``labor_terms.set`` (FLOW-028, R1) via ``app.audit.store.record_event``.
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from app.db import db
from app.services import labor_report_service as lrs
from app.tenancy import project_team
from app.tenancy.data_access import TenantData

SOURCE_FLOW = "FLOW-028"
AKORD = "Akord"
PENDING, APPROVED, REJECTED, SUPERSEDED = "pending", "approved", "rejected", "superseded"
OFFICE_ROLES = ("Admin", "Owner", "Accountant")
FINANCE_ROLES = ("Owner", "Admin", "Accountant")
APPROVER_ROLES = ("Admin", "Owner", "SiteManager")
LINE_OPEN = ("SUBMITTED", "APPROVED")


def _tenant(user: dict) -> TenantData:
    return TenantData.for_user(db, user)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _err(status: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(status_code=status, detail={"error_code": code, "message": message, **extra})


def _positive(value: Any, what: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise _err(422, "INVALID_NUMBER", "%s: трябва да е число" % what)
    if not math.isfinite(number) or number <= 0:
        raise _err(422, "INVALID_NUMBER", "%s: трябва да е число > 0" % what)
    return round(number, 4)


def slot_of(line: dict) -> str:
    return "%s|%s|%s" % (line["id"], "", int(line.get("report_version") or 0))


def is_finance(user: dict) -> bool:
    return user.get("role") in FINANCE_ROLES


# ═══════════════════════════════════════════════════════════════════ idempotency (R29)
async def idempotent(user: dict, key: Optional[str], action: str, payload: dict, perform, replay):
    """W0-04 registry, same contract as #75 ``_idempotent``: no key → 428; the same key with
    the same body → the first answer (``idempotent_replay``); with another body → 409."""
    from app.audit.idempotency import (
        IDEMPOTENCY_COMPLETED, IDEMPOTENCY_DUPLICATE, IDEMPOTENCY_STARTED, IdempotencyConflict,
        IdempotencyUnprotected, begin_idempotent, complete_idempotent, fail_idempotent,
        request_fingerprint)
    k = (key or "").strip()
    if not k:
        raise _err(428, "IDEMPOTENCY_KEY_REQUIRED",
                   "Липсва ключ за еднократност (Idempotency-Key) — презаредете и опитайте пак")
    if len(k) > 200:
        raise _err(400, "IDEMPOTENCY_KEY_TOO_LONG", "Ключът за еднократност е твърде дълъг (до 200 знака)")
    try:
        state = await begin_idempotent(db, tenant_id=user["org_id"], key=k, action=action,
                                       request_fingerprint=request_fingerprint(payload))
    except IdempotencyConflict:
        raise _err(409, "IDEMPOTENCY_CONFLICT", "Този ключ за еднократност вече е използван за друга заявка")
    except IdempotencyUnprotected:
        raise _err(503, "IDEMPOTENCY_UNPROTECTED", "Регистърът за еднократност не е защитен — нищо не е записано")
    if state.get("status") == IDEMPOTENCY_DUPLICATE:
        if state.get("prior_status") == IDEMPOTENCY_COMPLETED and state.get("result_reference"):
            found = await replay(state["result_reference"])
            if found is not None:
                return dict(found, idempotent_replay=True)
        raise _err(409, "IDEMPOTENCY_IN_PROGRESS", "Същата заявка още се обработва — изчакайте")
    if state.get("status") != IDEMPOTENCY_STARTED:
        raise _err(409, "IDEMPOTENCY_IN_PROGRESS", "Същата заявка още се обработва — изчакайте")
    try:
        result, ref = await perform(k)
    except HTTPException as exc:
        await fail_idempotent(db, tenant_id=user["org_id"], key=k, action=action,
                              error_code="http_%s" % exc.status_code)
        raise
    except Exception as exc:
        await fail_idempotent(db, tenant_id=user["org_id"], key=k, action=action,
                              error_code=type(exc).__name__)
        raise
    await complete_idempotent(db, tenant_id=user["org_id"], key=k, action=action, result_reference=ref)
    return result


async def audit(user: dict, action: str, entity_type: str, entity_id: str, *, version: Any,
                before: Any, after: Any, reason: str, endpoint: str, key: Optional[str],
                project_id: Optional[str] = None) -> None:
    from app.audit.envelope import ACTOR_HUMAN, RETENTION_R1_CRITICAL_BUSINESS, build_event
    from app.audit.store import record_event
    await record_event(db, build_event(
        tenant_id=user["org_id"], actor_type=ACTOR_HUMAN, actor_id=user["id"], action=action,
        source_flow=SOURCE_FLOW, retention_class=RETENTION_R1_CRITICAL_BUSINESS,
        entity_type=entity_type, entity_id=entity_id, entity_version=str(version),
        scope_type="project" if project_id else None, scope_id=project_id,
        structured_diff={"before": before, "after": after}, reason=reason,
        effective_role_assignments=[user.get("role") or ""], source_channel="api",
        tool_or_endpoint=endpoint, idempotency_key=key))


# ═══════════════════════════════════════════════════════════════════ the line
async def load_line(tenant: TenantData, org_id: str, line_id: str) -> dict:
    doc = await tenant.employee_daily_reports.find_one({"org_id": org_id, "id": line_id}, {"_id": 0})
    if not doc:
        raise _err(404, "LABOR_LINE_NOT_FOUND", "Редът от отчета на труда не е намерен")
    if not doc.get("worker_id") or doc.get("day_entries") is not None:
        raise _err(422, "OLD_FORMAT_LINE",
                   "Този отчет е в стария формат — количество се въвежда по ред от „Отчет на труда“")
    return doc


def line_status(doc: dict) -> str:
    return (doc.get("approval_status") or doc.get("status") or "").upper()


async def worker_pay_type(tenant: TenantData, org_id: str, worker_id: str) -> str:
    prof = await tenant.employee_profiles.find_one({"org_id": org_id, "user_id": worker_id},
                                                   {"_id": 0, "pay_type": 1})
    return ((prof or {}).get("pay_type") or "").strip()


async def package_of(tenant: TenantData, org_id: str, package_id: Optional[str], project_id: str) -> Optional[dict]:
    if not package_id:
        return None
    pkg = await tenant.execution_packages.find_one({"org_id": org_id, "id": package_id}, {"_id": 0})
    if not pkg or pkg.get("project_id") != project_id:
        raise _err(422, "PACKAGE_NOT_ON_PROJECT", "СМР пакетът трябва да е от обекта на реда")
    return pkg


async def records_of(tenant: TenantData, org_id: str, line_ids: List[str]) -> List[dict]:
    if not line_ids:
        return []
    rows = await tenant.labor_quantity_approvals.find(
        {"org_id": org_id, "report_id": {"$in": list(line_ids)}}, {"_id": 0}).to_list(len(line_ids) * 20 + 50)
    rows.sort(key=lambda r: (int(r.get("quantity_version") or 0), str(r.get("entered_at") or "")))
    return rows


async def is_project_site_manager(user: dict, project_id: str) -> bool:
    if user.get("role") != "SiteManager" or not project_id:
        return False
    team = project_team.tenant_for(db, user)
    if await project_team.is_member(team, user["id"], project_id):
        return True
    return bool(await _tenant(user).projects.find_one(
        {"org_id": user["org_id"], "id": project_id, "default_site_manager_id": user["id"]}, {"_id": 0, "id": 1}))


def require_approver_role(user: dict) -> None:
    if user.get("role") not in APPROVER_ROLES:
        raise _err(403, "QUANTITY_APPROVER_ONLY",
                   "Количество одобрява/отказва само Админ, Собственик или ръководителят на обекта")


async def require_approver(user: dict, rec: dict, line: dict) -> None:
    """#75 ``_require_approver``: Admin / Owner / SiteManager of the project; four-eyes —
    never the worker, the person who entered the quantity, nor an author / corrector of the line."""
    require_approver_role(user)
    if user["id"] in {rec.get("worker_id"), rec.get("entered_by")} | lrs.self_approval_ids(line):
        raise _err(403, lrs.ERR_SELF,
                   "Не можете да одобрите количество, което сте въвели, отчели или поправили — одобрява друг човек.")
    if user.get("role") in ("Admin", "Owner"):
        return
    if await is_project_site_manager(user, line.get("project_id")):
        return
    raise _err(403, "QUANTITY_APPROVER_ONLY", "Одобрява само ръководителят на този обект, Админ или Собственик")


def _public(rec: Optional[dict], finance: bool) -> Optional[dict]:
    if rec is None:
        return None
    out = {k: v for k, v in rec.items() if k not in ("_id", "pending_slot", "approved_slot", "idempotency_key")}
    if not finance:                                   # R31: no price for non-finance roles
        out.pop("piece_rate", None)
    return out


async def _get(tenant: TenantData, org_id: str, rec_id: str) -> Optional[dict]:
    return await tenant.labor_quantity_approvals.find_one({"org_id": org_id, "id": rec_id}, {"_id": 0})


# ═══════════════════════════════════════════════════════════════════ 1. enter
async def enter_quantity(user: dict, data: dict, key: Optional[str]) -> dict:
    tenant, org_id = _tenant(user), user["org_id"]
    qty = _positive(data.get("quantity"), "Количество")

    async def perform(k):
        line = await load_line(tenant, org_id, data["line_id"])
        await lrs.check_may_report(tenant, user, line["worker_id"], line.get("project_id"))
        lrs.check_not_paid(line)                                      # paid / batched → 409
        if line_status(line) not in LINE_OPEN:
            raise _err(409, "LINE_NOT_SUBMITTED", "Количество се въвежда по подаден или одобрен ред")
        if await worker_pay_type(tenant, org_id, line["worker_id"]) != AKORD:
            raise _err(422, "NOT_AKORD", "Работникът не е на акорд — количество не се въвежда")
        pkg = await package_of(tenant, org_id, data.get("execution_package_id"), line.get("project_id"))
        slot = slot_of(line)
        recs = await records_of(tenant, org_id, [line["id"]])
        recs = [r for r in recs if r.get("slot") == slot]
        pending = [r for r in recs if r.get("status") == PENDING]
        if pending:
            raise _err(409, "QUANTITY_PENDING",
                       "По този ред вече има количество, което чака одобрение — одобрете или откажете го първо.",
                       record_id=pending[-1]["id"])
        current = next((r for r in reversed(recs) if r.get("status") == APPROVED), None)
        version = max([int(r.get("quantity_version") or 0) for r in recs] + [0]) + 1
        now = _now()
        unit = (data.get("unit") or "").strip() or (pkg or {}).get("unit") or (current or {}).get("unit") or ""
        rec = {
            "id": str(uuid.uuid4()), "org_id": org_id, "report_id": line["id"], "entry_id": None,
            "report_version": int(line.get("report_version") or 0), "slot": slot,
            "labor_key": line.get("labor_key"), "worker_id": line["worker_id"],
            "project_id": line.get("project_id"), "date": line.get("date"), "smr_type": line.get("smr_type") or "",
            "quantity_version": version, "entered_quantity": qty, "unit": unit,
            "execution_package_id": (pkg or {}).get("id") or (current or {}).get("execution_package_id"),
            "entered_by": user["id"], "entered_at": now, "note": (data.get("note") or "").strip(),
            "status": PENDING, "pending_slot": slot,
            "replaces": (current or {}).get("id"), "idempotency_key": k,
        }
        try:
            await tenant.labor_quantity_approvals.insert_one(dict(rec))
        except Exception as exc:                                      # the partial unique index
            if "duplicate key" in str(exc).lower() or type(exc).__name__ == "DuplicateKeyError":
                raise _err(409, "QUANTITY_PENDING", "По този ред току-що беше въведено количество — презаредете.")
            raise
        action = "labor_quantity.correction_entered" if current else "labor_quantity.entered"
        await audit(user, action, "labor_quantity_approval", rec["id"], version=version,
                    before={"approved_quantity": current.get("approved_quantity"), "record_id": current["id"]}
                    if current else None,
                    after={"entered_quantity": qty, "unit": unit, "line_id": line["id"], "status": PENDING},
                    reason=rec["note"] or "akord quantity entered (LAB-AKORD-01)",
                    endpoint="POST /labor-quantities", key=k, project_id=line.get("project_id"))
        return _public(rec, is_finance(user)), rec["id"]

    async def replay(ref):
        return _public(await _get(tenant, org_id, ref), is_finance(user))

    return await idempotent(user, key, "labor_quantity.enter", data, perform, replay)


# ═══════════════════════════════════════════════════════════════════ 2. approve
async def approve_quantity(user: dict, rec_id: str, data: dict, key: Optional[str]) -> dict:
    require_approver_role(user)                                      # before the key / any read
    tenant, org_id = _tenant(user), user["org_id"]

    async def perform(k):
        rec = await _get(tenant, org_id, rec_id)
        if not rec:
            raise _err(404, "QUANTITY_NOT_FOUND", "Записът за количество не е намерен")
        line = await load_line(tenant, org_id, rec["report_id"])
        await require_approver(user, rec, line)
        lrs.check_not_paid(line)
        if rec.get("status") != PENDING:
            raise _err(409, "QUANTITY_NOT_PENDING", "Това количество вече е решено (%s) — презаредете" % rec.get("status"),
                       record_status=rec.get("status"))
        if line_status(line) != "APPROVED":
            raise _err(409, "LINE_NOT_APPROVED", "Първо се одобряват часовете на реда, после количеството")
        if rec.get("slot") != slot_of(line):
            raise _err(409, "LINE_CHANGED", "Редът е променен след въвеждането на количеството — въведете го отново")
        pkg = await package_of(tenant, org_id, data.get("execution_package_id") or rec.get("execution_package_id"),
                               line.get("project_id"))
        rate = (pkg or {}).get("labor_piece_rate")
        try:
            rate = float(rate) if rate is not None and float(rate) > 0 else None
        except (TypeError, ValueError):
            rate = None
        now = _now()
        prev = None
        if rec.get("replaces"):
            prev = await _get(tenant, org_id, rec["replaces"])
            res = await tenant.labor_quantity_approvals.update_one(
                {"org_id": org_id, "id": rec["replaces"], "status": APPROVED},
                {"$set": {"status": SUPERSEDED, "superseded_by": rec["id"], "superseded_at": now,
                          "superseded_by_user": user["id"]}, "$unset": {"approved_slot": ""}})
            if not res.modified_count:
                raise _err(409, "QUANTITY_CHANGED", "Одобрението, което се коригира, вече не е активно — презаредете")
        upd = {"status": APPROVED, "approved_quantity": rec["entered_quantity"], "approved_by": user["id"],
               "approved_at": now, "approved_slot": rec["slot"], "approval_note": (data.get("note") or "").strip(),
               "execution_package_id": (pkg or {}).get("id"), "unit": rec.get("unit") or (pkg or {}).get("unit") or "",
               # the agreed unit labor price at the moment of approval (a later change does not touch it)
               "piece_rate": rate, "labor_terms_version": int((pkg or {}).get("labor_terms_version") or 0),
               "labor_pay_type": AKORD, "approve_idempotency_key": k}
        try:
            res = await tenant.labor_quantity_approvals.update_one(
                {"org_id": org_id, "id": rec["id"], "status": PENDING},
                {"$set": upd, "$unset": {"pending_slot": ""}})
            won = bool(res.modified_count)
        except Exception as exc:
            if "duplicate key" not in str(exc).lower() and type(exc).__name__ != "DuplicateKeyError":
                raise
            won = False
        if not won:
            if prev is not None:                                     # give the old one back
                await tenant.labor_quantity_approvals.update_one(
                    {"org_id": org_id, "id": prev["id"], "status": SUPERSEDED, "superseded_by": rec["id"]},
                    {"$set": {"status": APPROVED, "approved_slot": prev.get("slot")},
                     "$unset": {"superseded_by": "", "superseded_at": "", "superseded_by_user": ""}})
            raise _err(409, "QUANTITY_CHANGED", "Количеството току-що беше решено от друг човек — презаредете")
        action = "labor_quantity.corrected" if prev else "labor_quantity.approved"
        await audit(user, action, "labor_quantity_approval", rec["id"], version=rec.get("quantity_version"),
                    before={"approved_quantity": prev.get("approved_quantity"), "record_id": prev["id"]} if prev
                    else {"status": PENDING},
                    after={"status": APPROVED, "approved_quantity": rec["entered_quantity"], "unit": upd["unit"],
                           "piece_rate": rate, "execution_package_id": upd["execution_package_id"],
                           "line_id": line["id"]},
                    reason=upd["approval_note"] or "akord quantity approved (LAB-AKORD-01)",
                    endpoint="POST /labor-quantities/{id}/approve", key=k, project_id=line.get("project_id"))
        return _public(await _get(tenant, org_id, rec["id"]), is_finance(user)), rec["id"]

    async def replay(ref):
        return _public(await _get(tenant, org_id, ref), is_finance(user))

    return await idempotent(user, key, "labor_quantity.approve", {"id": rec_id, **data}, perform, replay)


# ═══════════════════════════════════════════════════════════════════ 3. reject
async def reject_quantity(user: dict, rec_id: str, data: dict, key: Optional[str]) -> dict:
    require_approver_role(user)
    tenant, org_id = _tenant(user), user["org_id"]
    reason = (data.get("reason") or "").strip()
    if not reason:
        raise _err(422, "REASON_REQUIRED", "Отказът изисква причина")

    async def perform(k):
        rec = await _get(tenant, org_id, rec_id)
        if not rec:
            raise _err(404, "QUANTITY_NOT_FOUND", "Записът за количество не е намерен")
        line = await load_line(tenant, org_id, rec["report_id"])
        await require_approver(user, rec, line)
        lrs.check_not_paid(line)                    # a paid approval is reversed via the pay run
        if rec.get("status") not in (PENDING, APPROVED):
            raise _err(409, "QUANTITY_NOT_OPEN", "Това количество вече е %s — презаредете" % rec.get("status"),
                       record_status=rec.get("status"))
        now = _now()
        res = await tenant.labor_quantity_approvals.update_one(
            {"org_id": org_id, "id": rec["id"], "status": rec["status"]},
            {"$set": {"status": REJECTED, "rejected_by": user["id"], "rejected_at": now, "reject_reason": reason,
                      "status_before_reject": rec["status"], "reject_idempotency_key": k},
             "$unset": {"pending_slot": "", "approved_slot": ""}})
        if not res.modified_count:
            raise _err(409, "QUANTITY_CHANGED", "Количеството току-що беше решено от друг човек — презаредете")
        await audit(user, "labor_quantity.rejected", "labor_quantity_approval", rec["id"],
                    version=rec.get("quantity_version"), before={"status": rec["status"]},
                    after={"status": REJECTED, "line_id": line["id"]}, reason=reason,
                    endpoint="POST /labor-quantities/{id}/reject", key=k, project_id=line.get("project_id"))
        return _public(await _get(tenant, org_id, rec["id"]), is_finance(user)), rec["id"]

    async def replay(ref):
        return _public(await _get(tenant, org_id, ref), is_finance(user))

    return await idempotent(user, key, "labor_quantity.reject", {"id": rec_id, **data}, perform, replay)


# ═══════════════════════════════════════════════════════════════════ 4. the screen
async def may_view_project(user: dict, project_id: str) -> bool:
    if user.get("role") in OFFICE_ROLES:
        return True
    if user.get("role") in lrs.FIELD_ROLES and project_id:
        team = project_team.tenant_for(db, user)
        if await project_team.is_member(team, user["id"], project_id):
            return True
        return bool(await _tenant(user).projects.find_one(
            {"org_id": user["org_id"], "id": project_id, "default_site_manager_id": user["id"]}, {"_id": 0, "id": 1}))
    return False


async def list_project(user: dict, project_id: str, date_from: Optional[str], date_to: Optional[str]) -> dict:
    """The akord lines of a project with their quantity state and history (newest first)."""
    tenant, org_id = _tenant(user), user["org_id"]
    own_only = not await may_view_project(user, project_id)
    flt: Dict[str, Any] = {"org_id": org_id, "project_id": project_id, "worker_id": {"$exists": True}}
    if own_only:
        flt["worker_id"] = user["id"]                    # a worker sees only his own lines
    if date_from or date_to:
        flt["date"] = {**({"$gte": date_from} if date_from else {}), **({"$lte": date_to} if date_to else {})}
    lines = await tenant.employee_daily_reports.find(flt, {"_id": 0}).to_list(3000)
    lines = [ln for ln in lines if line_status(ln) in LINE_OPEN]
    workers = sorted({ln["worker_id"] for ln in lines})
    profs = await tenant.employee_profiles.find({"org_id": org_id, "user_id": {"$in": workers}},
                                                {"_id": 0, "user_id": 1, "pay_type": 1}).to_list(len(workers) + 10)
    akord = {p["user_id"] for p in profs if (p.get("pay_type") or "").strip() == AKORD}
    lines = [ln for ln in lines if ln["worker_id"] in akord]
    recs = await records_of(tenant, org_id, [ln["id"] for ln in lines])
    names = await lrs._names(tenant, [ln["worker_id"] for ln in lines] +
                             [r.get(f) for r in recs for f in ("entered_by", "approved_by", "rejected_by")])
    finance = is_finance(user)
    pkg_proj = {"_id": 0, "id": 1, "activity_name": 1, "unit": 1, "labor_terms_version": 1}
    if finance:
        pkg_proj["labor_piece_rate"] = 1
    pkgs = await tenant.execution_packages.find({"org_id": org_id, "project_id": project_id}, pkg_proj).to_list(500)
    items = []
    for ln in sorted(lines, key=lambda x: (x.get("date") or "", x.get("worker_name") or "")):
        slot = slot_of(ln)
        hist = [r for r in recs if r.get("report_id") == ln["id"] and r.get("slot") == slot]
        approved = next((r for r in reversed(hist) if r.get("status") == APPROVED), None)
        pending = next((r for r in reversed(hist) if r.get("status") == PENDING), None)
        last = hist[-1] if hist else None
        state = ("pending" if pending else "approved" if approved
                 else "rejected" if last and last.get("status") == REJECTED else "no_quantity")
        items.append({
            "line_id": ln["id"], "date": ln.get("date"), "worker_id": ln["worker_id"],
            "worker_name": ln.get("worker_name") or names.get(ln["worker_id"], ""),
            "smr_type": ln.get("smr_type") or "", "hours": ln.get("hours"), "line_status": line_status(ln),
            "payroll_status": lrs.payment_lock(ln) or "none", "state": state,
            "approved": _public(approved, finance), "pending": _public(pending, finance),
            "history": [dict(_public(r, finance), entered_by_name=names.get(r.get("entered_by"), ""),
                             approved_by_name=names.get(r.get("approved_by"), ""),
                             rejected_by_name=names.get(r.get("rejected_by"), "")) for r in reversed(hist)],
        })
    return {"project_id": project_id, "packages": pkgs, "items": items, "show_price": finance,
            "can_approve": user.get("role") in ("Admin", "Owner") or await is_project_site_manager(user, project_id),
            "waiting": sum(1 for i in items if i["state"] == "pending")}


# ═══════════════════════════════════════════════════════════════════ 5. the unit price
async def list_terms(user: dict, project_id: str) -> dict:
    if not is_finance(user):
        raise _err(403, "FINANCE_ONLY", "Единичните цени труд виждат само Собственик, Админ и Счетоводител")
    pkgs = await _tenant(user).execution_packages.find(
        {"org_id": user["org_id"], "project_id": project_id},
        {"_id": 0, "id": 1, "project_id": 1, "activity_name": 1, "unit": 1, "labor_piece_rate": 1,
         "labor_terms_version": 1, "labor_terms_updated_at": 1, "labor_terms_updated_by": 1}).to_list(500)
    return {"project_id": project_id, "items": pkgs}


async def set_terms(user: dict, package_id: str, data: dict, key: Optional[str]) -> dict:
    """#75 ``PUT /labor-terms``: the agreed unit labor price of an SMR package — finance roles,
    Idempotency-Key, compare-and-set on ``labor_terms_version``, a history row, AuditEvent.
    An approved quantity keeps the price it was approved with (snapshot)."""
    if not is_finance(user):
        raise _err(403, "FINANCE_ONLY", "Единична цена труд задават само Собственик, Админ или Счетоводител")
    rate = _positive(data.get("labor_piece_rate"), "Единична цена труд")
    reason = (data.get("reason") or "").strip()
    if not reason:
        raise _err(422, "REASON_REQUIRED", "Посочете основание (договор, анекс, споразумение)")
    tenant, org_id = _tenant(user), user["org_id"]

    async def perform(k):
        pkg = await tenant.execution_packages.find_one({"org_id": org_id, "id": package_id}, {"_id": 0})
        if not pkg:
            raise _err(404, "PACKAGE_NOT_FOUND", "СМР пакетът не е намерен")
        current = pkg.get("labor_terms_version")
        version, now = int(current or 0) + 1, _now()
        before = {"labor_piece_rate": pkg.get("labor_piece_rate"), "labor_terms_version": current}
        vflt = {"labor_terms_version": current} if current else {"labor_terms_version": {"$in": [None, 0]}}
        res = await tenant.execution_packages.update_one(
            {"org_id": org_id, "id": package_id, **vflt},
            {"$set": {"labor_piece_rate": rate, "labor_terms_version": version, "labor_terms_updated_at": now,
                      "labor_terms_updated_by": user["id"]}})
        if not res.modified_count:
            raise _err(409, "TERMS_CHANGED", "Цената току-що беше променена от друг човек — презаредете")
        await tenant.labor_terms_history.insert_one({
            "id": str(uuid.uuid4()), "org_id": org_id, "package_id": package_id, "project_id": pkg.get("project_id"),
            "version": version, "before": before, "after": {"labor_piece_rate": rate}, "reason": reason,
            "changed_by": user["id"], "changed_at": now, "idempotency_key": k})
        await audit(user, "labor_terms.set", "execution_package", package_id, version=version, before=before,
                    after={"labor_piece_rate": rate, "labor_terms_version": version}, reason=reason,
                    endpoint="PUT /labor-terms/{id}", key=k, project_id=pkg.get("project_id"))
        return {"id": package_id, "project_id": pkg.get("project_id"), "labor_piece_rate": rate,
                "labor_terms_version": version}, "%s:%s" % (package_id, version)

    async def replay(ref):
        pkg_id, _, ver = ref.rpartition(":")
        hist = await tenant.labor_terms_history.find_one(
            {"org_id": org_id, "package_id": pkg_id, "version": int(ver) if ver.isdigit() else -1}, {"_id": 0})
        if not hist:
            return None
        return {"id": pkg_id, "project_id": hist.get("project_id"),
                "labor_piece_rate": (hist.get("after") or {}).get("labor_piece_rate"), "labor_terms_version": hist["version"]}

    return await idempotent(user, key, "labor_terms.set", {"package_id": package_id, **data}, perform, replay)
