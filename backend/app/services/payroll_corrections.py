"""
Service — FLOW-028 payroll corrections as records (LAB-01-D FG-66 … LAB-01-G F2).

A correction is a RECEIVABLE from a person: an earlier paid Pay Run line paid more than
the LAB-01 earned amount of the days it covered (``allocate_paid_sources`` in
``routes/pay_runs.py``). CLAUDE.md §7: receivables and payables are never netted
automatically — so:

* ``payroll_corrections`` — one record per (employee, paid source line = source pay run),
  key ``overpayment:employee:<id>:source:pay_run:<run id>``, created ONCE with the
  receivable amount, status ``pending_approval``. Any later run (weekly, wider, monthly,
  draft or confirmed) that looks at the same paid line finds the same record
  (``pay_run_ids`` lists those runs) and never changes, supersedes or absorbs it.
  Later earnings are paid in full ("previously paid" counts the line only up to its
  earned).
* Decision: only an explicit, approved decision changes the record. The canonical
  DQ/Approval runtime (W0-07) is NOT STARTED, so the record stays
  ``approval_status = awaiting_approval_runtime`` with an open DQ alert
  (PAYROLL_CORRECTION_PENDING_APPROVAL). Nothing is ever applied automatically: no
  deduction, no reversal, no payment is created from it.
* A recomputation that shows another amount (re-approved reports, …) changes NOTHING on
  the record; it opens a DQ alert (PAYROLL_CORRECTION_RECOMPUTED, or …CHANGED_AFTER_DECISION
  for a decided record) with the old and new amounts for a person to decide.
* AuditEvent: the creation writes one canonical W0-04 AuditEvent (FLOW-040, retention R1,
  source FLOW-028).
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.tenancy.data_access import TenantData

SOURCE_FLOW = "FLOW-028"
STATUS_PENDING = "pending_approval"
APPROVAL_AWAITING_RUNTIME = "awaiting_approval_runtime"  # W0-07 not started
DQ_CODE = "PAYROLL_CORRECTION_PENDING_APPROVAL"
DQ_CODE_RECOMPUTED = "PAYROLL_CORRECTION_RECOMPUTED"
DQ_CODE_LOCKED = "PAYROLL_CORRECTION_CHANGED_AFTER_DECISION"
SOURCE = "paid_pay_run_line"


def _key(employee_id: str, source_pay_run_id: str) -> str:
    """The receivable's paid source: the employee's paid line on one Pay Run."""
    return f"overpayment:employee:{employee_id}:source:pay_run:{source_pay_run_id}"


def correction_id(org_id: str, employee_id: str, source_pay_run_id: str) -> str:
    """Deterministic id of the one correction of (tenant, employee, paid source line)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL,
                          f"beg-work:payroll-correction:{org_id}:{_key(employee_id, source_pay_run_id)}"))


async def _audit(raw_db, *, org_id: str, actor_id: str, action: str, record: dict,
                 diff: Optional[dict], reason: str):
    from app.audit.envelope import build_event, RETENTION_R1_CRITICAL_BUSINESS
    from app.audit.store import record_event
    event = build_event(
        tenant_id=org_id, actor_type="human", actor_id=actor_id or "system",
        action=action, source_flow=SOURCE_FLOW, retention_class=RETENTION_R1_CRITICAL_BUSINESS,
        entity_type="payroll_correction", entity_id=record["id"],
        entity_version=str(record.get("version", 1)),
        scope_type="pay_run", scope_id=record.get("source_pay_run_id"),
        structured_diff=diff, reason=reason, idempotency_key=record.get("idempotency_key"),
        tool_or_endpoint="pay_runs")
    return await record_event(raw_db, event)


async def _alert(tenant: TenantData, org_id: str, code: str, record: dict, now: str, **fields):
    """One open DQ alert per (correction, code); refreshed in place."""
    await tenant.dq_alerts.update_one(
        {"org_id": org_id, "entity_type": "payroll_correction", "entity_id": record["id"], "code": code},
        {"$set": {"org_id": org_id, "code": code, "severity": "high", "status": "open",
                  "entity_type": "payroll_correction", "entity_id": record["id"],
                  "entity_version": record.get("version"), "employee_id": record.get("employee_id"),
                  "source_pay_run_id": record.get("source_pay_run_id"), "amount": record.get("amount"),
                  **fields, "updated_at": now},
         "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": now}},
        upsert=True)


async def sync_run_corrections(tenant: TenantData, raw_db, org_id: str, run: dict,
                               actor_id: str) -> list:
    """Make sure every receivable the rows of ``run`` show has its record (after the run
    is written). Creates missing records; NEVER changes, supersedes or applies one."""
    now = datetime.now(timezone.utc).isoformat()
    run_id = run["id"]
    created = []
    for row in run.get("employee_rows") or []:
        eid = row.get("employee_id")
        if not eid:
            continue
        item = row.get("correction_item") or {}
        sources = item.get("sources") or row.get("previously_paid_sources") or []
        for src in sources:
            spr = src.get("pay_run_id")
            if not spr:
                continue
            amount = round(float(src.get("overpaid") or 0), 2)
            key = _key(eid, spr)
            existing = await tenant.payroll_corrections.find_one(
                {"org_id": org_id, "idempotency_key": key}, {"_id": 0})
            if existing is None:
                if amount <= 0:
                    continue
                record = {
                    "id": correction_id(org_id, eid, spr), "org_id": org_id, "idempotency_key": key,
                    "type": "FLOW028_CORRECTION", "kind": "receivable", "source": SOURCE,
                    "employee_id": eid, "source_pay_run_id": spr,
                    "source_pay_run_number": src.get("pay_run_number"),
                    "source_period_start": src.get("period_start"), "source_period_end": src.get("period_end"),
                    "source_paid": src.get("paid"), "source_earned": src.get("earned_available"),
                    "amount": amount, "pay_run_ids": [run_id],
                    "status": STATUS_PENDING, "approval_status": APPROVAL_AWAITING_RUNTIME,
                    "approval_id": None, "applied": False, "version": 1,
                    "reason": item.get("reason"), "created_by": actor_id, "created_at": now,
                    "updated_at": now,
                }
                await tenant.payroll_corrections.insert_one(dict(record))
                await _audit(raw_db, org_id=org_id, actor_id=actor_id, action="payroll.correction.created",
                             record=record, diff={"after": {"amount": amount, "source_pay_run_id": spr}},
                             reason="paid line exceeds the LAB-01 earned of its days (receivable)")
                await _alert(tenant, org_id, DQ_CODE, record, now, message=(
                    f"Вземане по FLOW-028: платено с {amount} EUR повече от заработеното ({spr}). "
                    "Чака изрично одобрено решение; не се нетира и не се прилага автоматично."))
                created.append(record)
                continue
            # an existing record is never rewritten here — only the runs that saw it are noted
            if run_id not in (existing.get("pay_run_ids") or []):
                await tenant.payroll_corrections.update_one(
                    {"org_id": org_id, "idempotency_key": key}, {"$addToSet": {"pay_run_ids": run_id}})
            if round(float(existing.get("amount") or 0), 2) != amount:
                decided = existing.get("status") != STATUS_PENDING or existing.get("applied")
                await _alert(tenant, org_id, DQ_CODE_LOCKED if decided else DQ_CODE_RECOMPUTED, existing, now,
                             recorded_amount=existing.get("amount"), new_amount=amount, pay_run_id=run_id,
                             message=("Преизчислението дава друга сума за това вземане; записът не е "
                                      "променен — решава човек."))
    return created
