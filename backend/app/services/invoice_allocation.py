"""
WH-FIX-01 Addendum A2 / A3 — FG-155 and Р44 (FLOW-020 L73/L200, FLOW-009 L84,
FLOW-033 L33/L101/L106, FLOW-026 L21, FLOW-008 L90/L126, FLOW-006).

The allocation STATE of a supplier (Received) invoice line is derived from
its source — the line's ``allocations[]`` (or the deprecated single
allocation for the whole line) — never stored as a second truth:

  * ``allocated`` (final)          — Σ allocated qty = the invoiced qty;
  * ``pending_allocation`` (interim, „чака разпределение") — anything less.

The final state ALWAYS needs 100 % (``require_full_allocation`` is True for
the final status and cannot be configured off; the tenant setting of the same
name still only decides whether an interim partial allocation may be SAVED).
The unallocated remainder is in no official result and is never defaulted to
any destination.

Р44 (Крум, 08.11.2026): a payment (FLOW-006) of a supplier invoice that has a
line without final allocation → 409 INVOICE_NOT_FULLY_ALLOCATED, nothing
written — every payment path (quick-pay, allocate, partial).

DQ + alarm: ONE deduplicated DQ issue „фактура без обект или разпределение"
and ONE alarm „фактура/ред без окончателно разпределение" per invoice, listed
under „фактури за разпределяне" with drill-down to the lines. Owner: the
Accountant; deadline per tenant (``allocation_dq_deadline_days``, default 3
days); after it the issue escalates to the Owner (alarm severity raised).
Rows are never deleted: a fully allocated invoice RESOLVES its issue / alarm.

Debt (canon open — not programmed): Approval for an allocation to overhead;
where the pending item is shown (project vs company); a value tolerance for
amount-only lines. The issue / alarm rows live in ``dq_issues`` /
``alarm_events`` until the canonical DQ runtime (Wave 0) exists.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

ALLOCATED = "allocated"
PENDING = "pending_allocation"
QTY_EPS = 0.0001

INVOICE_NOT_FULLY_ALLOCATED = "INVOICE_NOT_FULLY_ALLOCATED"
DQ_TYPE = "INVOICE_WITHOUT_ALLOCATION"
DQ_TITLE = "фактура без обект или разпределение"
ALARM_RULE = "INVOICE_NOT_FULLY_ALLOCATED"
ALARM_TITLE = "фактура/ред без окончателно разпределение"
DQ_OWNER_ROLE = "accountant"
DQ_ESCALATE_ROLE = "owner"
DEFAULT_DEADLINE_DAYS = 3
DEADLINE_SETTING = "allocation_dq_deadline_days"


def _f(v) -> Optional[float]:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def line_allocation_state(line: Dict[str, Any]) -> Dict[str, Any]:
    """{status, qty, allocated, unallocated} of one invoice line."""
    from app.services.canonical_material_cost import effective_allocations
    allocs = effective_allocations(line or {})
    qty = _f((line or {}).get("qty"))
    if allocs and any(a["qty"] is None for a in allocs):
        # the deprecated single allocation names the whole line
        return {"status": ALLOCATED, "qty": qty, "allocated": qty, "unallocated": 0.0}
    allocated = round(sum(a["qty"] or 0 for a in allocs), 4)
    if qty is None or qty <= 0:
        status = ALLOCATED if allocs else PENDING
        return {"status": status, "qty": qty, "allocated": allocated, "unallocated": 0.0}
    unallocated = round(max(0.0, qty - allocated), 4)
    status = ALLOCATED if abs(qty - allocated) <= QTY_EPS else PENDING
    return {"status": status, "qty": qty, "allocated": allocated, "unallocated": unallocated}


async def invoice_allocation_state(tenant, invoice_id: str, *, session=None) -> Dict[str, Any]:
    """{status, pending_lines} of an invoice from its lines."""
    pending: List[dict] = []
    count = 0
    async for line in tenant.invoice_lines.find(
            {"invoice_id": invoice_id},
            {"_id": 0, "id": 1, "line_no": 1, "description": 1, "unit": 1, "qty": 1,
             "line_total_ex_vat": 1, "allocations": 1, "allocation_type": 1,
             "allocation_ref_id": 1}, session=session):
        count += 1
        st = line_allocation_state(line)
        if st["status"] != ALLOCATED:
            pending.append({"line_id": line.get("id"), "line_no": line.get("line_no"),
                            "description": line.get("description"), "unit": line.get("unit"),
                            "qty": st["qty"], "allocated_qty": st["allocated"],
                            "unallocated_qty": st["unallocated"],
                            "allocations": line.get("allocations") or []})
    if count == 0:
        # FG-200: an invoice made in the finance UI keeps its lines EMBEDDED
        # (`invoices.lines[]`); a line's destination there is its
        # `allocations[]` or its `project_id` (the whole line).
        inv = await tenant.invoices.find_one({"id": invoice_id}, {"_id": 0, "lines": 1},
                                             session=session)
        for i, el in enumerate((inv or {}).get("lines") or []):
            if not isinstance(el, dict):
                continue
            count += 1
            st = line_allocation_state(embedded_as_line(el))
            if st["status"] != ALLOCATED:
                pending.append({"line_id": el.get("id") or f"embedded-{i}", "embedded": True,
                                "line_no": el.get("sort_order", i), "description": el.get("description"),
                                "unit": el.get("unit"), "qty": st["qty"],
                                "allocated_qty": st["allocated"],
                                "unallocated_qty": st["unallocated"],
                                "allocations": el.get("allocations") or []})
    return {"status": PENDING if pending else ALLOCATED, "pending_lines": pending,
            "line_count": count}


def embedded_as_line(el: dict) -> dict:
    """An embedded invoice line read with the invoice-line rule."""
    allocs = el.get("allocations") or []
    if not allocs and el.get("project_id"):
        allocs = [{"type": "project", "ref_id": el["project_id"], "qty": None}]
    return {"qty": el.get("qty"), "allocations": allocs}


def is_supplier_invoice(invoice: Optional[dict]) -> bool:
    return bool(invoice) and invoice.get("direction") == "Received"


# ─────────────── A4 / Р45 — header-level allocation (oracle Q002) ───────────────
# The allocation unit is the invoice LINE (FLOW-020 L54/L73). A header
# allocation is not final (A4 #9 „Само заглавен флаг ≠ окончателно"): with ONE
# destination the system writes it explicitly on every line (AuditEvent, same
# transaction); a split / percentage header stays „чака разпределение".
HEADER_NOTE = "от заглавието на фактурата (Р45)"


def header_destinations(invoice: Optional[dict]) -> List[dict]:
    """The header's destinations: ``allocations[]``; for a SUPPLIER invoice
    without it, its header ``project_id`` (FG-200 — the finance UI's one
    destination field) counts as one header destination."""
    inv = invoice or {}
    dests = [a for a in (inv.get("allocations") or [])
             if isinstance(a, dict) and a.get("type") and (a.get("ref_id") or a.get("refId"))]
    if not dests and inv.get("direction") == "Received" and inv.get("project_id"):
        dests = [{"type": "project", "ref_id": inv["project_id"]}]
    return dests


def stamp_embedded_lines(invoice: dict) -> List[dict]:
    """FG-200 / A4 #9 — write the ONE header destination on every embedded
    line that has none (in place); returns [{line_id, before, after}] for the
    AuditEvents the caller records in the same transaction."""
    dest = single_header_destination(invoice)
    if dest is None:
        return []
    changes = []
    for el in invoice.get("lines") or []:
        if not isinstance(el, dict) or el.get("allocations") or el.get("project_id"):
            continue
        after = [{"type": dest["type"], "ref_id": dest["ref_id"], "qty": el.get("qty"),
                  "note": HEADER_NOTE}]
        el["allocations"] = after
        if dest["type"] == "project":
            el["project_id"] = dest["ref_id"]
        changes.append({"line_id": el.get("id"), "before": [], "after": after})
    return changes


def single_header_destination(invoice: Optional[dict]) -> Optional[dict]:
    """The one header destination (no percentage / split), else None."""
    dests = header_destinations(invoice)
    if len(dests) != 1:
        return None
    d = dests[0]
    if d.get("percent") is not None or d.get("amount") is not None:
        return None
    return {"type": d["type"], "ref_id": d.get("ref_id") or d.get("refId")}


async def invoice_final_state(tenant, invoice: dict, *, session=None) -> Dict[str, Any]:
    """The invoice's state: pending when a line is pending, or when it carries a
    header allocation that no line carries yet (A4 #8/#9: never dropped)."""
    state = await invoice_allocation_state(tenant, invoice["id"], session=session)
    if state["status"] == ALLOCATED and header_destinations(invoice) and not state["line_count"]:
        state = {**state, "status": PENDING}
    return state


async def apply_header_destination(tenant, user: dict, invoice: dict, *, session=None) -> int:
    """A4 #9 — write the single header destination on every line without an
    allocation (qty = the line's qty), each with an AuditEvent, in the caller's
    transaction. Idempotent: allocated lines are never touched. → lines written."""
    dest = single_header_destination(invoice)
    if dest is None:
        return 0
    written = 0
    if not await tenant.invoice_lines.find_one({"invoice_id": invoice["id"]}, {"_id": 0, "id": 1},
                                               session=session):
        # FG-200: embedded lines (finance UI invoice) — stamped in the document.
        doc = await tenant.invoices.find_one({"id": invoice["id"]}, {"_id": 0},
                                             session=session)
        if not doc:
            return 0
        changes = stamp_embedded_lines(doc)
        if changes:
            for ch in changes:
                await audit_allocation_change(tenant, user, ch["line_id"] or invoice["id"],
                                              ch["before"], ch["after"], session=session,
                                              reason="Р45: заглавната дестинация е записана на реда")
            await tenant.invoices.update_one({"id": invoice["id"]}, {"$set": {
                "lines": doc["lines"], "updated_at": datetime.now(timezone.utc).isoformat()}},
                session=session)
        return len(changes)
    rows = [ln async for ln in tenant.invoice_lines.find(
        {"invoice_id": invoice["id"]},
        {"_id": 0, "id": 1, "qty": 1, "allocations": 1, "allocation_type": 1,
         "allocation_ref_id": 1}, session=session)]
    for ln in rows:
        if ln.get("allocations") or (ln.get("allocation_type") and ln.get("allocation_ref_id")):
            continue
        qty = _f(ln.get("qty"))
        alloc = [{"type": dest["type"], "ref_id": dest["ref_id"],
                  "qty": qty if qty is not None else 0, "note": HEADER_NOTE}]
        await audit_allocation_change(tenant, user, ln["id"], [], alloc, session=session,
                                      reason="Р45: заглавната дестинация е записана на реда")
        await tenant.invoice_lines.update_one(
            {"id": ln["id"]},
            {"$set": {"allocations": alloc, "qty_allocated": qty or 0, "qty_unallocated": 0,
                      "is_fully_allocated": True,
                      "updated_at": datetime.now(timezone.utc).isoformat()}},
            session=session)
        written += 1
    return written


def split_percentages(total: float, qty: Optional[float], percents: List[float]) -> List[dict]:
    """A4 #10 — a percentage is only an input aid: converted AT ONCE into an
    exact amount (and qty share) per allocation with cumulative rounding, so
    Σ amount = the line value and Σ qty = the line qty."""
    out, cum_pct, done_amt, done_qty = [], 0.0, 0.0, 0.0
    for pct in percents:
        cum_pct += pct
        amt = round(round(total * cum_pct / 100.0, 2) - done_amt, 2)
        q = None if qty is None else round(round(qty * cum_pct / 100.0, 4) - done_qty, 4)
        out.append({"amount": amt, "qty": q})
        done_amt = round(done_amt + amt, 2)
        done_qty = round(done_qty + (q or 0), 4)
    return out


async def migrate_header_allocations(tenant, org_id: str, actor: dict, *, dry_run: bool = True,
                                     now: Optional[datetime] = None) -> Dict[str, Any]:
    """A4 #11 — legacy header-allocated invoices of ONE tenant (idempotent):
    one destination → written on every line (AuditEvent, one transaction per
    invoice); a split / percentage → „чака разпределение" + the DQ issue to the
    Accountant. Never deletes. Rollback = the reverse correction by the
    AuditEvents (before = [] on each line). ``dry_run`` reports only."""
    from app.services.invoice_line_lock import run_transaction
    from app.audit.store import ensure_chain_index
    report = {"tenant": org_id, "dry_run": dry_run, "written": [], "pending": [], "skipped": []}
    if not dry_run:
        await ensure_chain_index(tenant._db)          # pylint: disable=protected-access
    invs = [i async for i in tenant.invoices.find(
        {"org_id": org_id, "status": {"$ne": "Cancelled"},
         "$or": [{"allocations.0": {"$exists": True}},
                 {"direction": "Received", "project_id": {"$nin": [None, ""]}}]},
        {"_id": 0, "id": 1, "invoice_no": 1, "allocations": 1, "direction": 1,
         "project_id": 1, "total": 1, "status": 1})]
    for inv in invs:
        state = await invoice_final_state(tenant, inv)
        if state["status"] == ALLOCATED:
            report["skipped"].append(inv["id"])
            continue
        if single_header_destination(inv) is not None and state["pending_lines"]:
            if dry_run:
                report["written"].append({"invoice_id": inv["id"], "lines": sorted(
                    p["line_id"] for p in state["pending_lines"])})
                continue
            box: Dict[str, int] = {}

            async def _body(session, inv=inv, box=box):
                box["n"] = await apply_header_destination(tenant, actor, inv, session=session)
                await refresh_invoice_dq(tenant, inv["id"], actor=actor, session=session,
                                         now=now)
            await run_transaction(tenant, _body)
            report["written"].append({"invoice_id": inv["id"], "lines_written": box.get("n", 0)})
        else:
            report["pending"].append(inv["id"])
            if not dry_run:
                async def _open(session, inv=inv, state=state):
                    await sync_invoice_issue(tenant, org_id, inv, state, now=now, actor=actor,
                                             session=session)
                await run_transaction(tenant, _open)
    return report


async def ensure_payable(tenant, invoice: dict, *, session=None) -> None:
    """Р44 — 409 before anything is written when a supplier invoice has a line
    without final (100 %) allocation."""
    if not is_supplier_invoice(invoice):
        return
    state = await invoice_final_state(tenant, invoice, session=session)
    if state["status"] != ALLOCATED:
        raise HTTPException(status_code=409, detail={
            "error_code": INVOICE_NOT_FULLY_ALLOCATED, "invoice_id": invoice["id"],
            "pending_lines": [{"line_id": p["line_id"], "unallocated_qty": p["unallocated_qty"]}
                              for p in state["pending_lines"]],
            "message": "Фактурата има ред без окончателно разпределение — плащането не е записано"})


async def deadline_days(tenant) -> int:
    org = await tenant.own_organization({"_id": 0, DEADLINE_SETTING: 1}) or {}
    try:
        days = int(org.get(DEADLINE_SETTING) or DEFAULT_DEADLINE_DAYS)
    except (TypeError, ValueError):
        days = DEFAULT_DEADLINE_DAYS
    return days if days > 0 else DEFAULT_DEADLINE_DAYS


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _escalation(opened_at: Optional[str], days: int, now: datetime) -> Dict[str, Any]:
    """Computed at READ time (FG-201): overdue = opened + deadline < now."""
    try:
        opened = datetime.fromisoformat(opened_at) if opened_at else None
    except ValueError:
        opened = None
    if opened is None:
        return {"due_at": None, "escalated": False, "escalated_to_role": None,
                "severity": "warning"}
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=timezone.utc)
    due = opened + timedelta(days=days)
    esc = now > due
    return {"due_at": _iso(due), "escalated": esc,
            "escalated_to_role": DQ_ESCALATE_ROLE if esc else None,
            "severity": "high" if esc else "warning"}


async def _dq_event(tenant, actor: Optional[dict], action: str, invoice_id: str,
                    diff: dict, *, session=None) -> None:
    from app.audit.envelope import (
        ACTOR_HUMAN, ACTOR_SYSTEM, RETENTION_R1_CRITICAL_BUSINESS, build_event,
    )
    from app.audit.store import record_event
    actor = actor or {}
    event = build_event(
        tenant_id=tenant.org_id,
        actor_type=ACTOR_HUMAN if actor.get("id") else ACTOR_SYSTEM,
        actor_id=actor.get("id") or "system", action=action, source_flow="FLOW-033",
        retention_class=RETENTION_R1_CRITICAL_BUSINESS, entity_type="dq_issue",
        entity_id=f"dq-invoice-allocation-{invoice_id}", structured_diff=diff,
        effective_role_assignments=[actor.get("role") or ""], source_channel="api")
    await record_event(tenant._db, event, session=session)   # pylint: disable=protected-access


async def sync_invoice_issue(tenant, org_id: str, invoice: dict, state: Dict[str, Any], *,
                             now: Optional[datetime] = None, days: Optional[int] = None,
                             actor: Optional[dict] = None, session=None) -> Optional[dict]:
    """FG-201 — called by the WRITES (invoice / line / allocation / migration),
    never by a read: opens the ONE DQ issue + alarm of a pending invoice, or
    resolves them when it is final, each with an AuditEvent in the caller's
    transaction. Deterministic ids → deduplicated; nothing is deleted. The
    deadline / escalation is NOT stored — it is computed when read."""
    now = now or datetime.now(timezone.utc)
    issue_id = f"dq-invoice-allocation-{invoice['id']}"
    alarm_id = f"alarm-invoice-allocation-{invoice['id']}"
    existing = await tenant.dq_issues.find_one({"id": issue_id}, {"_id": 0}, session=session)
    is_open = bool(existing) and existing.get("status") == "open"
    if state["status"] == ALLOCATED:
        if is_open:
            await tenant.dq_issues.update_one(
                {"id": issue_id}, {"$set": {"status": "resolved", "resolved_at": _iso(now)}},
                session=session)
            await tenant.alarm_events.update_one(
                {"id": alarm_id}, {"$set": {"status": "resolved", "resolved_at": _iso(now),
                                            "resolve_notes": "invoice fully allocated"}},
                session=session)
            await _dq_event(tenant, actor, "dq.invoice_allocation.resolved", invoice["id"],
                            {"status": {"before": "open", "after": "resolved"}}, session=session)
        return None
    pending = [{"line_id": p["line_id"], "unallocated_qty": p["unallocated_qty"]}
               for p in state["pending_lines"]]
    if is_open:
        if existing.get("pending_lines") != pending:
            await tenant.dq_issues.update_one(
                {"id": issue_id}, {"$set": {"pending_lines": pending, "updated_at": _iso(now)}},
                session=session)
        return {**existing, "pending_lines": pending}
    days = days or await deadline_days(tenant)
    issue = {
        "id": issue_id, "org_id": org_id, "type": DQ_TYPE, "title": DQ_TITLE,
        "entity_type": "invoice", "entity_id": invoice["id"],
        "invoice_no": invoice.get("invoice_no"), "status": "open",
        "owner_role": DQ_OWNER_ROLE, "opened_at": _iso(now), "deadline_days": days,
        "pending_lines": pending, "updated_at": _iso(now),
    }
    await tenant.dq_issues.update_one({"id": issue_id}, {"$set": issue}, upsert=True,
                                      session=session)
    await tenant.alarm_events.update_one({"id": alarm_id}, {"$set": {
        "id": alarm_id, "org_id": org_id, "rule_id": ALARM_RULE, "rule_name": ALARM_TITLE,
        "type": "data_quality", "severity": "warning", "status": "active",
        "triggered_at": _iso(now),
        "message": f"{ALARM_TITLE}: {invoice.get('invoice_no') or invoice['id']}",
        "context": {"entity_id": invoice["id"], "entity_type": "invoice",
                    "dq_issue_id": issue_id, "details": {"pending_lines": pending}},
        "acknowledged_by": None, "acknowledged_at": None, "resolved_by": None,
        "resolved_at": None, "resolve_notes": None}}, upsert=True, session=session)
    await _dq_event(tenant, actor, "dq.invoice_allocation.opened", invoice["id"],
                    {"status": {"before": existing.get("status") if existing else None,
                                "after": "open"},
                     "owner_role": DQ_OWNER_ROLE, "pending_lines": pending}, session=session)
    return issue


async def refresh_invoice_dq(tenant, invoice_id: str, *, actor: Optional[dict] = None,
                             session=None, now: Optional[datetime] = None) -> None:
    """The write-side hook: re-evaluate one invoice after a write touched it."""
    inv = await tenant.invoices.find_one(
        {"id": invoice_id}, {"_id": 0, "id": 1, "invoice_no": 1, "direction": 1,
                             "allocations": 1, "project_id": 1, "status": 1}, session=session)
    if not inv or inv.get("status") == "Cancelled":
        return
    if inv.get("direction") != "Received" and not header_destinations(inv):
        return
    state = await invoice_final_state(tenant, inv, session=session)
    await sync_invoice_issue(tenant, tenant.org_id, inv, state, actor=actor, session=session,
                             now=now)


async def invoices_to_allocate(tenant, org_id: str, *, now: Optional[datetime] = None) -> List[dict]:
    """„фактури за разпределяне" — READ ONLY (FG-201): every non-cancelled
    supplier invoice with a line in the interim state, and every invoice with
    a header allocation no line carries yet (A4 #8), drill-down to the lines,
    with its DQ issue (stored by the writes) and the escalation computed now
    (opened + deadline < now → Owner). A pending invoice whose issue was never
    written (legacy data) shows a computed issue from its created_at."""
    now = now or datetime.now(timezone.utc)
    days = await deadline_days(tenant)
    out = []
    async for inv in tenant.invoices.find(
            {"org_id": org_id, "status": {"$ne": "Cancelled"},
             "$or": [{"direction": "Received"}, {"allocations.0": {"$exists": True}}]},
            {"_id": 0, "id": 1, "invoice_no": 1, "issue_date": 1, "counterparty_name": 1,
             "total": 1, "status": 1, "direction": 1, "allocations": 1, "project_id": 1,
             "created_at": 1}):
        if inv.get("direction") != "Received" and not header_destinations(inv):
            continue
        state = await invoice_final_state(tenant, inv)
        if state["status"] == ALLOCATED:
            continue
        stored = await tenant.dq_issues.find_one(
            {"id": f"dq-invoice-allocation-{inv['id']}", "status": "open"}, {"_id": 0})
        issue = stored or {"id": None, "type": DQ_TYPE, "title": DQ_TITLE, "status": "open",
                           "owner_role": DQ_OWNER_ROLE, "opened_at": inv.get("created_at"),
                           "deadline_days": days, "stored": False}
        issue = {**issue, "deadline_days": days,
                 **_escalation(issue.get("opened_at"), days, now)}
        dests = header_destinations(inv)
        inv.pop("allocations", None)
        out.append({**inv, "allocation_status": state["status"], "header_destinations": dests,
                    "pending_lines": state["pending_lines"], "dq_issue": issue})
    return out


async def audit_allocation_change(tenant, user: dict, line_id: str, before: list, after: list,
                                  *, session=None, reason: Optional[str] = None) -> None:
    """A2 #4 — an allocation change is a correction in the source with a
    canonical AuditEvent (in the caller's transaction when it has one)."""
    from app.audit.envelope import ACTOR_HUMAN, RETENTION_R1_CRITICAL_BUSINESS, build_event
    from app.audit.store import record_event
    event = build_event(
        tenant_id=user["org_id"], actor_type=ACTOR_HUMAN, actor_id=user["id"],
        action="finance.invoice_line.allocation_corrected", source_flow="FLOW-020",
        retention_class=RETENTION_R1_CRITICAL_BUSINESS, entity_type="invoice_line",
        entity_id=line_id, structured_diff={"allocations": {"before": before, "after": after}},
        reason=reason,
        effective_role_assignments=[user.get("role") or ""], source_channel="api")
    await record_event(tenant._db, event, session=session)   # pylint: disable=protected-access
