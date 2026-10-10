"""
LIVE-OPS-01 / TASK 5A — read-only LIVE-OPS Control Center projection.

Frozen contract: ``LIVE_OPS_TECHNICAL_CONTRACT.md`` v6-contract-freeze.

What this module is:

* ONE ``GET`` endpoint that reads the existing collections (material requests,
  warehouses, the legacy ``warehouse_transactions`` ledger, asset units, custody,
  repairs, and the canonical ``audit_events`` store) and returns a projection for
  the desktop control screen.
* Every operational read goes through ``TenantData.for_user`` (D-15): the tenant
  is the org of the server-loaded session user, never a request parameter.

What this module is NOT (contract §0, TASK 5A prohibitions):

* no write of any kind — no insert/update/delete/replace/upsert, no index build,
  no idempotency claim, no AuditEvent append;
* no new model, collection or canonical store; the response is computed on
  every request and stored nowhere;
* no Permission Service or AuditEvent writer change; no migration.

Honesty rules taken from the contract and applied here:

* LO-I-011 — the stock projection reads the COMPLETE ledger (no ``to_list(N)``
  cap). Only the RESPONSE lists are paged, and every paged list says so.
* §4.4 / LO-I-005 — the baseline ledger keys material by free text and stores
  client-entered prices, so totals are returned with ``trust = "untrusted"`` and
  the reasons, never as trusted figures.
* LO-I-012 / FLOW-011 — an accepted custodian and a pending handover are two
  different facts and are returned in two different fields.
* §2.9 — the activity preview reads only canonical ``audit_events``. Legacy
  ``audit_logs`` is never read here, so it can never be promoted to canonical.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import SUBSCRIPTION_PLANS
from app.tenancy.data_access import TenantData

logger = logging.getLogger(__name__)

router = APIRouter(tags=["LiveOps"])

#: Same roles as the frontend ``AdminRoute`` guard that serves ``/live-ops``.
#: This is a legacy role-list READ guard, not a Permission Service decision;
#: the projection reports that gap itself (``PERMISSION_READINESS``).
READ_ROLES = ("Admin", "Owner", "SiteManager", "Accountant")

#: Response page sizes. They bound the LISTS only; every count is computed over
#: the complete data set and each list reports ``total`` and ``truncated``.
REQUEST_LIST_LIMIT = 50
ASSET_LIST_LIMIT = 100
STOCK_ITEMS_PER_WAREHOUSE = 200
AUDIT_PREVIEW_LIMIT = 20

#: Above this many movements the legacy ``/inventory`` screen is known to
#: under-count (its stock helper reads ``to_list(1000)``).
LEGACY_STOCK_READ_CAP = 1000

#: Entity types a canonical LIVE-OPS AuditEvent would carry.
LIVE_OPS_AUDIT_ENTITY_TYPES = (
    "material_request", "warehouse", "warehouse_transaction",
    "asset_unit", "asset_custody", "asset_repair",
)

# ── Labels (Bulgarian, read-only presentation of existing values) ────────────

REQUEST_STATUS_LABELS = {
    "draft": "Чернова",
    "submitted": "Подадена — чака решение",
    "fulfilled": "Маркирана „изпълнена“ (legacy)",
}
#: Statuses the merged code writes that leave a request still open.
OPEN_REQUEST_STATUSES = ("draft", "submitted")

WAREHOUSE_TYPE_LABELS = {
    "central": "Централен склад",
    "project": "Обектов склад",
    "vehicle": "Склад в превозно средство",
    "person": "Склад при служител",
    "main": "Основен склад (legacy „main“)",
}

LOCATION_TYPE_LABELS = {
    "warehouse": "Склад",
    "project": "Обект",
    "employee": "Служител",
}

#: Operational indicator (Issue #52 UX v2), derived from status + location.
INDICATORS = {
    "in_warehouse": {"label": "В склад", "color": "green"},
    "on_project": {"label": "На обект", "color": "yellow"},
    "with_person": {"label": "При човек", "color": "blue"},
    "in_repair": {"label": "В ремонт", "color": "orange"},
    "written_off": {"label": "Бракуван / отписан", "color": "black"},
    "unknown": {"label": "Неизвестно състояние", "color": "gray"},
}

CUSTODY_ACTIVE = ("given", "accepted")


# ── Read-only module gate ────────────────────────────────────────────────────

def _m2_decision(sub: Optional[Dict[str, Any]], now: datetime) -> Optional[str]:
    """The M2 access outcome of ``check_module_access_for_org``, evaluated purely.

    Same plan table, same statuses, same messages. The one difference is the
    expired trial: the shared helper PERSISTS ``trialing -> past_due``; here the
    expiry is only evaluated, so a GET never writes. ``None`` means allowed.
    """
    if not sub:
        return "No subscription"
    plan = SUBSCRIPTION_PLANS.get(sub.get("plan_id", "free"), SUBSCRIPTION_PLANS["free"])
    status = sub.get("status", "")
    trial_ends_at = sub.get("trial_ends_at")
    if status == "trialing" and trial_ends_at:
        try:
            if now >= datetime.fromisoformat(trial_ends_at.replace("Z", "+00:00")):
                status = "past_due"          # evaluated, never stored
        except (ValueError, TypeError, AttributeError):
            pass
    if status in ("canceled", "past_due", "incomplete"):
        return f"Subscription {status}. Please upgrade your plan."
    if "M2" not in plan["allowed_modules"]:
        return "Module not in your current plan"
    return None


async def require_m2_read_only(user: dict = Depends(get_current_user)) -> dict:
    """M2 gate for this GET: the access outcome of ``require_m2`` without its write."""
    sub = await TenantData.for_user(db, user).subscriptions.find_one(
        {"org_id": user["org_id"]}, {"_id": 0})
    reason = _m2_decision(sub, datetime.now(timezone.utc))
    if reason:
        raise HTTPException(status_code=403, detail=reason)
    return user


def _assert_single_tenant_path(user: Dict[str, Any]) -> str:
    """The ONE tenant id this projection reads, operational and audit alike.

    The operational reads are bound to ``user.org_id`` (``TenantData.for_user``).
    A session whose ``active_tenant_id`` names a different tenant cannot be
    served safely by that legacy path, so the request fails closed instead of
    showing one tenant's stock next to another tenant's audit.
    """
    org_id = user.get("org_id")
    active = user.get("active_tenant_id")
    if not org_id or (active and active != org_id):
        raise HTTPException(status_code=409, detail={
            "error_code": "LIVE_OPS_TENANT_PATH_MISMATCH",
            "message": "Активната фирма на сесията не съвпада с фирмата на данните. "
                       "Контролният център не показва смесени данни."})
    return org_id


# ── Small helpers ────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _person_name(u: Optional[Dict[str, Any]]) -> Optional[str]:
    if not u:
        return None
    return (u.get("name")
            or f"{u.get('first_name', '') or ''} {u.get('last_name', '') or ''}".strip()
            or None)


def _parse_day(value: Any) -> Optional[date]:
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _max_iso(values: Iterable[Any]) -> Optional[str]:
    vals = [v for v in values if isinstance(v, str) and v]
    return max(vals) if vals else None


def _warning(code: str, severity: str, title: str, detail: str,
             count: Optional[int] = None, link: Optional[str] = None) -> Dict[str, Any]:
    return {"code": code, "severity": severity, "title": title, "detail": detail,
            "count": count, "link": link}


def _section_error(name: str, exc: Exception) -> Dict[str, Any]:
    # The exception text is logged server-side only; the screen gets a plain,
    # honest message instead of internals.
    logger.exception("live-ops section %s failed", name)
    return {"status": "error",
            "message": "Секцията не можа да бъде заредена. Данните НЕ са показани, "
                       "вместо да се покажат непълни."}


async def _all(cursor) -> List[Dict[str, Any]]:
    """Every document of a cursor — deliberately no length cap (LO-I-011)."""
    return await cursor.to_list(None)


# ── Requests ─────────────────────────────────────────────────────────────────

async def _requests_section(tenant: TenantData, today: date) -> Dict[str, Any]:
    reqs = await _all(tenant.material_requests.find(
        {}, {"_id": 0, "id": 1, "request_number": 1, "project_id": 1, "status": 1,
             "needed_date": 1, "created_at": 1, "updated_at": 1, "lines": 1,
             "stage_name": 1}))
    projects = await tenant.projects.get_many(
        [r.get("project_id") for r in reqs], {"_id": 0, "id": 1, "name": 1, "code": 1})

    by_status: Dict[str, int] = {}
    open_count = pending_count = overdue_count = no_date_open = 0
    fulfilled_legacy = 0
    free_text_lines = 0
    unknown_statuses: Dict[str, int] = {}
    rows = []
    for r in reqs:
        status = r.get("status") or "unknown"
        by_status[status] = by_status.get(status, 0) + 1
        if status not in REQUEST_STATUS_LABELS:
            unknown_statuses[status] = unknown_statuses.get(status, 0) + 1
        is_open = status in OPEN_REQUEST_STATUSES
        needed = _parse_day(r.get("needed_date"))
        overdue = bool(is_open and needed and needed < today)
        if is_open:
            open_count += 1
            if needed is None:
                no_date_open += 1
        if status == "submitted":
            pending_count += 1
        if status == "fulfilled":
            fulfilled_legacy += 1
        if overdue:
            overdue_count += 1
        lines = r.get("lines") or []
        free_text_lines += sum(1 for ln in lines if not ln.get("item_id"))
        if is_open:
            proj = projects.get(r.get("project_id"))
            rows.append({
                "id": r.get("id"),
                "request_number": r.get("request_number"),
                "status": status,
                "status_label": REQUEST_STATUS_LABELS.get(status, f"Непознат статус „{status}“"),
                "project_id": r.get("project_id"),
                "project_name": (proj or {}).get("name"),
                "project_code": (proj or {}).get("code"),
                "needed_date": r.get("needed_date"),
                "overdue": overdue,
                "lines_count": len(lines),
                "created_at": r.get("created_at"),
                "link": "/procurement",
            })

    # Overdue first, then the nearest need date, then requests with no date.
    rows.sort(key=lambda x: (not x["overdue"], x["needed_date"] is None,
                             x["needed_date"] or "", x["created_at"] or ""))
    return {
        "status": "ok",
        "source": "material_requests (legacy заявки, пълно четене)",
        "generated_at": _now_iso(),
        "last_change_at": _max_iso(r.get("updated_at") or r.get("created_at") for r in reqs),
        "total": len(reqs),
        "counts": {
            "open": open_count,
            "pending": pending_count,
            "overdue": overdue_count,
            "open_without_needed_date": no_date_open,
            "fulfilled_legacy": fulfilled_legacy,
            "by_status": by_status,
        },
        # The merged code never updates qty_fulfilled and has no delivery /
        # acceptance writer for request lines, so "partial" is not derivable.
        "partial": {
            "derivable": False,
            "value": None,
            "reason": "Частичното изпълнение не се записва: текущият код не обновява "
                      "изпълненото количество по редовете на заявката.",
        },
        "overdue_rule": "Отворена заявка (чернова/подадена) с „нужна до“ преди днес.",
        "unknown_statuses": unknown_statuses,
        "free_text_lines": free_text_lines,
        "items": rows[:REQUEST_LIST_LIMIT],
        "items_total": len(rows),
        "items_truncated": len(rows) > REQUEST_LIST_LIMIT,
        "link": "/procurement",
    }


# ── Warehouses + stock ───────────────────────────────────────────────────────

def _warehouse_label(wh: Dict[str, Any]) -> str:
    """Human-readable name first (owner decision 6 / LO-I-007)."""
    name = (wh.get("name") or "").strip()
    return name or "Склад без име"


def _line_qty(line: Dict[str, Any]) -> float:
    # Same field precedence as the legacy stock helper the screens use today.
    return float(line.get("qty_received", 0) or line.get("qty_issued", 0)
                 or line.get("qty_returned", 0) or 0)


async def _warehouses_section(tenant: TenantData) -> Dict[str, Any]:
    warehouses = await _all(tenant.warehouses.find(
        {}, {"_id": 0, "id": 1, "name": 1, "code": 1, "type": 1, "active": 1,
             "project_id": 1, "address": 1}))
    txns = await _all(tenant.warehouse_transactions.find(
        {}, {"_id": 0, "id": 1, "type": 1, "warehouse_id": 1, "lines": 1, "created_at": 1}))
    batch_count = await tenant.warehouse_batches.count_documents({})
    # Contract §2.5.1: legacy parallel material writers. Counted only — they are
    # NEVER added to the totals below, which stay warehouse_transactions-only.
    legacy_parallel = {
        "project_material_ops": await tenant.project_material_ops.count_documents({}),
        "material_consumption_log": await tenant.material_consumption_log.count_documents({}),
    }

    by_id = {w.get("id"): w for w in warehouses if w.get("id")}
    stock: Dict[Any, Dict[str, Dict[str, Any]]] = {}
    no_warehouse_txns = 0
    unknown_warehouse_txns = 0
    unknown_type_txns = 0
    free_text_lines = 0
    zero_value_returns = 0
    for t in txns:
        wid = t.get("warehouse_id")
        if not wid:
            no_warehouse_txns += 1
            continue
        if wid not in by_id:
            unknown_warehouse_txns += 1
        ttype = t.get("type")
        sign = {"intake": 1, "issue": -1, "return": 1}.get(ttype)
        if sign is None:
            unknown_type_txns += 1
            continue
        bucket = stock.setdefault(wid, {})
        for line in t.get("lines") or []:
            if not line.get("item_id"):
                free_text_lines += 1
            name = line.get("material_name", "") or ""
            unit = line.get("unit", "") or ""
            key = f"{name}|{unit}"
            row = bucket.setdefault(key, {"material_name": name, "unit": unit,
                                          "qty": 0.0, "value": 0.0})
            row["qty"] += sign * _line_qty(line)
            row["value"] += sign * float(line.get("total_price", 0) or 0)
            if ttype == "return" and not line.get("total_price"):
                zero_value_returns += 1

    negative_rows = 0
    out = []
    for wh in sorted(warehouses, key=lambda w: (_warehouse_label(w).lower(), w.get("code") or "")):
        rows = list(stock.get(wh.get("id"), {}).values())
        negative = [r for r in rows if r["qty"] < -0.001]
        negative_rows += len(negative)
        positive = sorted((r for r in rows if r["qty"] > 0.001),
                          key=lambda r: r["material_name"].lower())
        out.append({
            "id": wh.get("id"),
            "label": _warehouse_label(wh),
            "name": wh.get("name"),
            "code": wh.get("code"),
            "type": wh.get("type"),
            "type_label": WAREHOUSE_TYPE_LABELS.get(wh.get("type"), "Непознат тип склад"),
            "active": wh.get("active", True),
            "is_legacy_main": wh.get("type") == "main",
            "stock_positions": len(positive),
            "negative_positions": len(negative),
            "stock_value_unverified": round(sum(r["value"] for r in positive), 2),
            "items": [{"material_name": r["material_name"], "unit": r["unit"],
                       "qty": round(r["qty"], 3), "value_unverified": round(r["value"], 2)}
                      for r in positive[:STOCK_ITEMS_PER_WAREHOUSE]],
            "items_total": len(positive),
            "items_truncated": len(positive) > STOCK_ITEMS_PER_WAREHOUSE,
        })

    trust_reasons = [
        "Материалите в склада се разпознават по свободен текст (име|мярка), не по Master артикул.",
        "Стойността идва от въведени цени в изписването, не от FIFO по партиди.",
    ]
    unprojectable = no_warehouse_txns + unknown_warehouse_txns + unknown_type_txns
    if unprojectable:
        trust_reasons.append(
            f"{unprojectable} движения не могат да се отразят в наличностите "
            f"(без склад: {no_warehouse_txns}, непознат склад: {unknown_warehouse_txns}, "
            f"непознат вид: {unknown_type_txns}). Проекцията е непълна.")
    if any(legacy_parallel.values()):
        trust_reasons.append(
            "Има паралелни legacy материални записи (project_material_ops / "
            "material_consumption_log), които не са включени в наличностите.")
    if batch_count:
        trust_reasons.append(
            f"Има {batch_count} записа в warehouse_batches, които не са равнени с движенията.")
    if negative_rows:
        trust_reasons.append("Има отрицателни наличности.")
    if zero_value_returns:
        trust_reasons.append("Връщанията се записват без стойност.")

    return {
        "status": "ok",
        "source": "warehouse_transactions (legacy регистър, пълно четене без лимит)",
        "generated_at": _now_iso(),
        "last_movement_at": _max_iso(t.get("created_at") for t in txns),
        "movement_count": len(txns),
        # Every movement was READ; "complete" also requires that every one could
        # be projected. A skipped movement makes the projection incomplete.
        "complete": unprojectable == 0,
        "unprojectable_movements": unprojectable,
        "trust": "untrusted",
        "trust_reasons": trust_reasons,
        "warehouses": out,
        "legacy_main_count": sum(1 for w in warehouses if w.get("type") == "main"),
        "inactive_count": sum(1 for w in warehouses if w.get("active") is False),
        "diagnostics": {
            "movements_without_warehouse": no_warehouse_txns,
            "movements_unknown_warehouse": unknown_warehouse_txns,
            "movements_unknown_type": unknown_type_txns,
            "free_text_lines": free_text_lines,
            "negative_positions": negative_rows,
            "batch_projection_rows": batch_count,
            "unprojectable_movements": unprojectable,
            "legacy_parallel_sources": legacy_parallel,
            "zero_value_return_lines": zero_value_returns,
        },
        "link": "/data/warehouses",
    }


# ── Assets ───────────────────────────────────────────────────────────────────

def _indicator(status: Optional[str], location_type: Optional[str], open_repair: bool) -> str:
    if status == "written_off":
        return "written_off"
    if status == "repair" or open_repair:
        return "in_repair"
    if location_type == "warehouse":
        return "in_warehouse"
    if location_type == "project":
        return "on_project"
    if location_type == "employee":
        return "with_person"
    return "unknown"


async def _assets_section(tenant: TenantData) -> Dict[str, Any]:
    units = await _all(tenant.asset_units.find(
        {}, {"_id": 0, "id": 1, "item_id": 1, "qr_id": 1, "serial_no": 1, "inventory_no": 1,
             "status": 1, "location_type": 1, "location_id": 1, "is_active": 1}))
    custody = await _all(tenant.asset_custody.find(
        {"status": {"$in": list(CUSTODY_ACTIVE)}},
        {"_id": 0, "id": 1, "unit_id": 1, "status": 1, "custodian_user_id": 1,
         "given_by_user_id": 1, "given_at": 1, "accepted_at": 1}))
    repairs = await _all(tenant.asset_repairs.find(
        {"status": "in_repair"},
        {"_id": 0, "id": 1, "unit_id": 1, "service": 1, "issue": 1, "sent_at": 1,
         "created_at": 1}))

    items = await tenant.asset_items.get_many(
        [u.get("item_id") for u in units], {"_id": 0, "id": 1, "name": 1, "type": 1})
    wh_ids = [u.get("location_id") for u in units if u.get("location_type") == "warehouse"]
    pr_ids = [u.get("location_id") for u in units if u.get("location_type") == "project"]
    user_ids = [u.get("location_id") for u in units if u.get("location_type") == "employee"]
    user_ids += [c.get("custodian_user_id") for c in custody]
    user_ids += [c.get("given_by_user_id") for c in custody]
    warehouses = await tenant.warehouses.get_many(wh_ids, {"_id": 0, "id": 1, "name": 1, "code": 1})
    projects = await tenant.projects.get_many(pr_ids, {"_id": 0, "id": 1, "name": 1, "code": 1})
    users = await tenant.users.get_many(
        user_ids, {"_id": 0, "id": 1, "name": 1, "first_name": 1, "last_name": 1})

    accepted_by_unit: Dict[str, List[Dict[str, Any]]] = {}
    pending_by_unit: Dict[str, List[Dict[str, Any]]] = {}
    for c in custody:
        target = accepted_by_unit if c.get("status") == "accepted" else pending_by_unit
        target.setdefault(c.get("unit_id"), []).append(c)
    repair_by_unit = {r.get("unit_id"): r for r in repairs}

    def location(u):
        ltype, lid = u.get("location_type"), u.get("location_id")
        name = None
        if ltype == "warehouse":
            name = _warehouse_label(warehouses[lid]) if lid in warehouses else None
        elif ltype == "project":
            name = (projects.get(lid) or {}).get("name")
        elif ltype == "employee":
            name = _person_name(users.get(lid))
        return {
            "type": ltype,
            "type_label": LOCATION_TYPE_LABELS.get(ltype, "Без локация" if not ltype else "Непознат тип"),
            "name": name,
            "resolved": bool(name),
        }

    counts = {k: 0 for k in INDICATORS}
    unresolved_location = multi_active = pending_total = 0
    rows = []
    for u in units:
        uid = u.get("id")
        repair = repair_by_unit.get(uid)
        ind = _indicator(u.get("status"), u.get("location_type"), bool(repair))
        counts[ind] += 1
        loc = location(u)
        if not loc["resolved"] and ind != "written_off":
            unresolved_location += 1
        accepted = accepted_by_unit.get(uid, [])
        pending = pending_by_unit.get(uid, [])
        if len(accepted) + len(pending) > 1:
            multi_active += 1
        pending_total += len(pending)
        acc = accepted[0] if accepted else None
        pen = pending[0] if pending else None
        item = items.get(u.get("item_id")) or {}
        rows.append({
            "id": uid,
            "name": item.get("name") or "Актив без артикул",
            "item_type": item.get("type"),
            "qr_id": u.get("qr_id"),
            "serial_no": u.get("serial_no"),
            "inventory_no": u.get("inventory_no"),
            "status": u.get("status"),
            "indicator": ind,
            "indicator_label": INDICATORS[ind]["label"],
            "location": loc,
            # Accepted responsibility and a pending handover are separate facts.
            "accepted_custodian": ({
                "name": _person_name(users.get(acc.get("custodian_user_id"))) or "Неизвестен потребител",
                "since": acc.get("accepted_at") or acc.get("given_at"),
            } if acc else None),
            "pending_handover": ({
                "to_name": _person_name(users.get(pen.get("custodian_user_id"))) or "Неизвестен потребител",
                "from_name": _person_name(users.get(pen.get("given_by_user_id"))),
                "since": pen.get("given_at"),
            } if pen else None),
            "repair": ({
                "service": repair.get("service"),
                "issue": repair.get("issue"),
                "since": repair.get("sent_at") or repair.get("created_at"),
            } if repair else None),
            "multiple_active_custody": len(accepted) + len(pending) > 1,
            "link": f"/assets/units/{uid}" if uid else "/assets/units",
        })

    priority = {"in_repair": 0, "unknown": 1, "with_person": 3, "on_project": 3,
                "in_warehouse": 4, "written_off": 5}
    rows.sort(key=lambda r: (0 if r["pending_handover"] else 1,
                             priority.get(r["indicator"], 9), r["name"].lower()))
    return {
        "status": "ok",
        "source": "asset_units + asset_custody + asset_repairs (пълно четене)",
        "generated_at": _now_iso(),
        "total": len(units),
        "counts": counts,
        "pending_handovers": pending_total,
        "accepted_custody": sum(len(v) for v in accepted_by_unit.values()),
        "open_repairs": len(repairs),
        "unresolved_location": unresolved_location,
        "multiple_active_custody": multi_active,
        "overdue": {
            "supported": False,
            "value": None,
            "reason": "Текущите данни нямат срок за връщане, затова просрочие не може да се изчисли.",
        },
        "legacy_handover_note": (
            "При текущия legacy поток създаването на предаване затваря предишния отговорник. "
            "Докато предаването чака приемане, приет отговорник не е записан."),
        "items": rows[:ASSET_LIST_LIMIT],
        "items_total": len(rows),
        "items_truncated": len(rows) > ASSET_LIST_LIMIT,
        "link": "/assets/units",
    }


# ── Canonical audit preview ──────────────────────────────────────────────────

async def _audit_path_ok(tenant_id: str, operational_db) -> Optional[str]:
    """``None`` when this tenant's canonical events live in the SAME database the
    operational projection reads; otherwise the fail-closed reason.

    off/shadow: the canonical store writes into the legacy database
    (``LegacyCompatContext.db()``) — the same handle as the operational reads.
    enforce: it writes into the registry-resolved tenant database; it is read
    only if that IS the operational database. No other database is opened.
    """
    from app.permissions.deps import current_mode
    from app.tenancy import registry

    if current_mode() != "enforce":
        return None
    tenant = await registry.get_tenant(tenant_id)
    if not tenant:
        return "Фирмата не е в регистъра; каноничният журнал не може да бъде намерен."
    if registry.resolve_database_name(tenant) != operational_db.name:
        return ("Каноничният журнал на фирмата е в друга база от операционните данни; "
                "не се смесват източници.")
    return None


async def _audit_section(tenant_id: str) -> Dict[str, Any]:
    base = {
        "source": "audit_events (каноничен AuditEvent, FLOW-040)",
        "generated_at": _now_iso(),
        "legacy_audit_used": False,
        "tenant_id": tenant_id,
    }
    refused = await _audit_path_ok(tenant_id, db)
    if refused:
        return {**base, "status": "unavailable", "events": [], "fail_closed": True,
                "message": "Каноничен AuditEvent не е наличен: " + refused}
    events = await db.audit_events.find(
        {"tenant_id": tenant_id, "entity_type": {"$in": list(LIVE_OPS_AUDIT_ENTITY_TYPES)}},
        {"_id": 0, "event_id": 1, "occurred_at": 1, "action": 1, "entity_type": 1,
         "entity_id": 1, "actor_type": 1, "actor_id": 1, "result": 1, "source_flow": 1,
         "sequence": 1},
    ).sort("sequence", -1).to_list(AUDIT_PREVIEW_LIMIT)
    if not events:
        return {**base, "status": "unavailable", "events": [],
                "message": "Каноничен AuditEvent не е наличен за записите в склад, заявки и "
                           "активи. Legacy журналът не се показва като каноничен."}
    return {**base, "status": "available", "events": events,
            "events_truncated": len(events) >= AUDIT_PREVIEW_LIMIT}


# ── Integrity warnings ───────────────────────────────────────────────────────

def _integrity(requests: Dict[str, Any], stock: Dict[str, Any], assets: Dict[str, Any],
               audit: Dict[str, Any]) -> List[Dict[str, Any]]:
    from app.permissions.deps import current_mode

    out: List[Dict[str, Any]] = []
    mode = current_mode()
    if mode != "enforce":
        out.append(_warning(
            "PERMISSION_READINESS", "warning", "Правата не са под Permission Service",
            f"PERMISSION_SERVICE_MODE={mode}. Действията в склад, заявки и активи още се "
            "пазят само от legacy списъци с роли. Този екран е само за четене."))
    if audit.get("status") != "available":
        out.append(_warning(
            "AUDIT_READINESS", "warning", "Няма каноничен AuditEvent за LIVE-OPS",
            "Записите в склад, заявки и активи още не пишат каноничен AuditEvent."))

    if stock.get("status") == "ok":
        d = stock["diagnostics"]
        if stock["legacy_main_count"]:
            out.append(_warning(
                "LEGACY_MAIN_WAREHOUSE", "warning", "Открит legacy склад тип „main“",
                "Каноничният тип е „central“. Складовете тип „main“ чакат инвентаризация и "
                "одобрена миграция; нищо не се мигрира от този екран.",
                stock["legacy_main_count"], "/data/warehouses"))
        if d["free_text_lines"]:
            out.append(_warning(
                "FREE_TEXT_MATERIAL", "warning", "Материали без Master артикул (складови движения)",
                "Редове от складови движения разпознават материала само по име и мярка.",
                d["free_text_lines"], "/data/master-data"))
        if d["batch_projection_rows"] or d["unprojectable_movements"]:
            out.append(_warning(
                "STOCK_UNRECONCILED", "critical", "Наличностите не са равнени",
                f"Партиди (warehouse_batches) без равнение: {d['batch_projection_rows']}. "
                f"Движения, които не могат да се отразят (без склад, непознат склад или "
                f"непознат вид): {d['unprojectable_movements']}.",
                d["batch_projection_rows"] + d["unprojectable_movements"], "/inventory"))
        lp = d["legacy_parallel_sources"]
        if any(lp.values()):
            out.append(_warning(
                "LEGACY_PARALLEL_STOCK_SOURCE", "critical", "Паралелен legacy източник на материали",
                f"project_material_ops: {lp['project_material_ops']}, material_consumption_log: "
                f"{lp['material_consumption_log']}. Тези записи не са включени в наличностите и "
                "не са равнени с регистъра.",
                sum(lp.values()), "/inventory"))
        if d["negative_positions"]:
            out.append(_warning(
                "NEGATIVE_STOCK", "critical", "Отрицателни наличности",
                "Изчисленото количество е под нула за някои материали.",
                d["negative_positions"], "/inventory"))
        out.append(_warning(
            "STOCK_VALUE_UNVERIFIED", "warning", "Стойността на склада не е проверена",
            "Сумите са от legacy цени без FIFO и не се показват като доверени."))
        if stock["movement_count"] > LEGACY_STOCK_READ_CAP:
            out.append(_warning(
                "LEGACY_STOCK_TRUNCATED", "critical", "Старият екран „Наличности“ е непълен",
                f"Има {stock['movement_count']} движения, а старият екран чете най-много "
                f"{LEGACY_STOCK_READ_CAP}. Този център чете всички.",
                stock["movement_count"], "/inventory"))

    if requests.get("status") == "ok":
        if requests["free_text_lines"]:
            out.append(_warning(
                "FREE_TEXT_MATERIAL_REQUESTS", "warning", "Материали без Master артикул (заявки)",
                "Редове от заявки разпознават материала само по име.",
                requests["free_text_lines"], "/procurement"))
        if requests["counts"]["fulfilled_legacy"]:
            out.append(_warning(
                "REQUEST_FULFILLED_BY_INVOICE", "info", "„Изпълнена“ идва от фактура",
                "Legacy статусът „изпълнена“ се поставя при осчетоводяване на фактура, не от "
                "приети количества.", requests["counts"]["fulfilled_legacy"], "/procurement"))
        if requests["unknown_statuses"]:
            out.append(_warning(
                "REQUEST_UNKNOWN_STATUS", "warning", "Заявки с непознат статус",
                "Статусът не е от познатите стойности и не се брои като отворен.",
                sum(requests["unknown_statuses"].values()), "/procurement"))

    if assets.get("status") == "ok":
        if assets["pending_handovers"]:
            out.append(_warning(
                "PENDING_CUSTODY", "warning", "Предавания чакат приемане",
                "Отговорността не е приета. " + assets["legacy_handover_note"],
                assets["pending_handovers"], "/assets/units"))
        if assets["multiple_active_custody"]:
            out.append(_warning(
                "MULTIPLE_ACTIVE_CUSTODY", "critical", "Актив с повече от един активен държател",
                "Има активи с повече от един активен запис за отговорност.",
                assets["multiple_active_custody"], "/assets/units"))
        if assets["unresolved_location"]:
            out.append(_warning(
                "ASSET_LOCATION_UNRESOLVED", "warning", "Активи без разпозната локация",
                "Локацията липсва или не може да се намери в тази фирма.",
                assets["unresolved_location"], "/assets/units"))

    for name, section in (("Заявки", requests), ("Склад", stock), ("Активи", assets)):
        if section.get("status") == "error":
            out.append(_warning(
                "SECTION_UNAVAILABLE", "critical", f"Секция „{name}“ не е заредена",
                "Данните не са показани, за да не изглеждат пълни."))
    return out


# ── Endpoint ─────────────────────────────────────────────────────────────────

@router.get("/live-ops/control-center")
async def live_ops_control_center(user: dict = Depends(require_m2_read_only)):
    """Read-only LIVE-OPS projection. There is no write endpoint in this module."""
    if user.get("role") not in READ_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    tenant_id = _assert_single_tenant_path(user)
    tenant = TenantData.for_user(db, user)     # bound to user.org_id == tenant_id
    today = datetime.now(timezone.utc).date()

    async def guarded(name, coro):
        try:
            return await coro
        except HTTPException:
            raise
        except Exception as exc:  # one broken section must not hide the others
            return _section_error(name, exc)

    requests = await guarded("requests", _requests_section(tenant, today))
    stock = await guarded("warehouses", _warehouses_section(tenant))
    assets = await guarded("assets", _assets_section(tenant))
    audit = await guarded("audit", _audit_section(tenant_id))
    return {
        "read_only": True,
        "generated_at": _now_iso(),
        "contract": "LIVE-OPS-01 v6-contract-freeze",
        "requests": requests,
        "warehouses": stock,
        "assets": assets,
        "audit": audit,
        "integrity": _integrity(requests, stock, assets, audit),
    }
