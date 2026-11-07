"""
Service — LAB-01-D (FG-66): FLOW-028 payroll corrections as records, not a row field.

When what was already paid to a person exceeds the (re-priced) payable amount of a Pay
Run row, the row shows remaining 0 and a ``correction_item``; this service turns that
item into a real record:

* ``payroll_corrections`` — one record per (pay run, employee), idempotent by
  ``idempotency_key``; status ``pending_approval``. It is NEVER applied automatically:
  no deduction, no reversal, no payment is created from it (CLAUDE.md §7/§8).
* Approval: the canonical DQ/Approval runtime (W0-07) is NOT STARTED
  (IMPLEMENTATION_GATE_MATRIX). The record is therefore routed to Approval as
  ``approval_status = awaiting_approval_runtime`` and a DQ alert is raised in
  ``dq_alerts`` (code PAYROLL_CORRECTION_PENDING_APPROVAL). When W0-07 exists, its
  Approval points at the record's exact ``version``.
* AuditEvent: every create / change / supersede writes one canonical W0-04 AuditEvent
  (FLOW-040, retention R1 critical business, source FLOW-028).
* A later edit of the run that changes the amount bumps the record's ``version``; an
  edit that removes the overpayment marks it ``superseded`` (never deleted).
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.tenancy.data_access import TenantData

SOURCE_FLOW = "FLOW-028"
STATUS_PENDING = "pending_approval"
STATUS_SUPERSEDED = "superseded"
# LAB-01-D-C01: only these may be re-priced by a later run edit; an approved / applied /
# rejected correction is never touched (a new difference raises a DQ alert instead).
REOPENABLE = (STATUS_PENDING, STATUS_SUPERSEDED)
DQ_CODE_LOCKED = "PAYROLL_CORRECTION_CHANGED_AFTER_DECISION"
APPROVAL_AWAITING_RUNTIME = "awaiting_approval_runtime"  # W0-07 not started
DQ_CODE = "PAYROLL_CORRECTION_PENDING_APPROVAL"


def correction_id(org_id: str, run_id: str, employee_id: str) -> str:
    """Deterministic id of the one correction of (tenant, run, employee)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"beg-work:payroll-correction:{org_id}:{run_id}:{employee_id}"))


def _key(run_id: str, employee_id: str) -> str:
    return f"pay_run:{run_id}:employee:{employee_id}"


async def _audit(raw_db, *, org_id: str, actor_id: str, action: str, record: dict,
                 diff: Optional[dict], reason: str):
    from app.audit.envelope import build_event, RETENTION_R1_CRITICAL_BUSINESS
    from app.audit.store import record_event
    event = build_event(
        tenant_id=org_id, actor_type="human", actor_id=actor_id or "system",
        action=action, source_flow=SOURCE_FLOW, retention_class=RETENTION_R1_CRITICAL_BUSINESS,
        entity_type="payroll_correction", entity_id=record["id"],
        entity_version=str(record.get("version", 1)),
        scope_type="pay_run", scope_id=record.get("pay_run_id"),
        structured_diff=diff, reason=reason, idempotency_key=record.get("idempotency_key"),
        tool_or_endpoint="pay_runs")
    return await record_event(raw_db, event)


async def _raise_dq(tenant: TenantData, org_id: str, record: dict, now: str):
    """One open DQ alert per correction (idempotent); refreshed on a new version."""
    await tenant.dq_alerts.update_one(
        {"org_id": org_id, "entity_type": "payroll_correction", "entity_id": record["id"]},
        {"$set": {
            "org_id": org_id, "code": DQ_CODE, "severity": "high", "status": "open",
            "entity_type": "payroll_correction", "entity_id": record["id"],
            "entity_version": record["version"], "employee_id": record["employee_id"],
            "pay_run_id": record["pay_run_id"], "amount": record["amount"],
            "message": ("Корекция по FLOW-028 чака одобрение: платено с "
                        f"{record['amount']} EUR повече от заработеното. Не се прилага автоматично "
                        "(Approval runtime W0-07 не е стартиран)."),
            "updated_at": now,
        }, "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": now}},
        upsert=True)


async def sync_run_corrections(tenant: TenantData, raw_db, org_id: str, run: dict,
                               actor_id: str) -> list:
    """Create / update / supersede the correction records of ``run`` (after it is written).
    Returns the records touched. Never changes a payment."""
    now = datetime.now(timezone.utc).isoformat()
    run_id = run["id"]
    touched = []
    seen = set()
    for row in run.get("employee_rows") or []:
        eid = row.get("employee_id")
        item = row.get("correction_item")
        if not eid or not item:
            continue
        seen.add(eid)
        key = _key(run_id, eid)
        existing = await tenant.payroll_corrections.find_one(
            {"org_id": org_id, "idempotency_key": key}, {"_id": 0})
        fields = {
            "amount": round(float(item.get("amount") or 0), 2),
            "gross_payable": item.get("gross_payable"),
            "previously_paid": item.get("previously_paid"),
            "paid_now": item.get("paid_now"),
            "reason": item.get("reason"),
        }
        if existing is None:
            record = {
                "id": item.get("correction_id") or correction_id(org_id, run_id, eid),
                "org_id": org_id, "idempotency_key": key, "type": "FLOW028_CORRECTION",
                "employee_id": eid, "pay_run_id": run_id, "pay_run_number": run.get("number"),
                "period_start": run.get("period_start"), "period_end": run.get("period_end"),
                **fields,
                "status": STATUS_PENDING, "approval_status": APPROVAL_AWAITING_RUNTIME,
                "approval_id": None, "applied": False, "version": 1,
                "created_by": actor_id, "created_at": now, "updated_at": now,
            }
            await tenant.payroll_corrections.insert_one(dict(record))
            await _audit(raw_db, org_id=org_id, actor_id=actor_id, action="payroll.correction.created",
                         record=record, diff={"after": fields},
                         reason="previously paid exceeds the re-priced earned amount (LAB-01)")
        elif existing.get("status") == STATUS_PENDING and existing.get("amount") == fields["amount"]:
            record = existing  # idempotent: same run, same employee, same amount
        elif existing.get("status") not in REOPENABLE or existing.get("applied"):
            # decided (approved / applied / rejected …): never rewritten. A new difference is
            # surfaced for a human, not merged into the decided record.
            if existing.get("amount") != fields["amount"]:
                await tenant.dq_alerts.update_one(
                    {"org_id": org_id, "entity_type": "payroll_correction", "entity_id": existing["id"],
                     "code": DQ_CODE_LOCKED},
                    {"$set": {"org_id": org_id, "code": DQ_CODE_LOCKED, "severity": "high",
                              "status": "open", "entity_type": "payroll_correction",
                              "entity_id": existing["id"], "entity_version": existing.get("version"),
                              "employee_id": eid, "pay_run_id": run_id,
                              "decided_amount": existing.get("amount"), "new_amount": fields["amount"],
                              "message": "Корекцията вече е решена; новата разлика чака човек.",
                              "updated_at": now},
                     "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": now}},
                    upsert=True)
            continue
        else:
            before = {k: existing.get(k) for k in fields}
            record = dict(existing, **fields, status=STATUS_PENDING,
                          approval_status=APPROVAL_AWAITING_RUNTIME, approval_id=None,
                          version=int(existing.get("version") or 1) + 1, updated_at=now)
            res = await tenant.payroll_corrections.update_one(
                {"org_id": org_id, "idempotency_key": key, "status": {"$in": list(REOPENABLE)},
                 "applied": {"$ne": True}},
                {"$set": {k: record[k] for k in (*fields, "status", "approval_status", "approval_id",
                                                 "version", "updated_at")}})
            if getattr(res, "matched_count", 1) == 0:
                continue  # decided between the read and the write — left untouched
            await _audit(raw_db, org_id=org_id, actor_id=actor_id, action="payroll.correction.updated",
                         record=record, diff={"before": before, "after": fields},
                         reason="pay run edited; correction amount changed")
        await _raise_dq(tenant, org_id, record, now)
        touched.append(record)

    # a pending correction whose overpayment disappeared on this run → superseded (kept)
    stale = await tenant.payroll_corrections.find(
        {"org_id": org_id, "pay_run_id": run_id, "status": STATUS_PENDING}, {"_id": 0}).to_list(500)
    for rec in stale:
        if rec.get("employee_id") in seen:
            continue
        rec = dict(rec, status=STATUS_SUPERSEDED, version=int(rec.get("version") or 1) + 1, updated_at=now)
        res = await tenant.payroll_corrections.update_one(
            {"org_id": org_id, "id": rec["id"], "status": STATUS_PENDING, "applied": {"$ne": True}},
            {"$set": {"status": STATUS_SUPERSEDED, "version": rec["version"], "updated_at": now}})
        if getattr(res, "matched_count", 1) == 0:
            continue
        await tenant.dq_alerts.update_one(
            {"org_id": org_id, "entity_type": "payroll_correction", "entity_id": rec["id"]},
            {"$set": {"status": "resolved", "resolution": "superseded", "updated_at": now}})
        await _audit(raw_db, org_id=org_id, actor_id=actor_id, action="payroll.correction.superseded",
                     record=rec, diff={"before": {"status": STATUS_PENDING}, "after": {"status": STATUS_SUPERSEDED}},
                     reason="pay run edited; the overpayment is no longer there")
        touched.append(rec)
    return touched
