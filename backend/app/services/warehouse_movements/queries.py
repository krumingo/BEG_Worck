"""
Read-only stock / history views over the canonical ledger.

Nothing in this module writes. All queries are tenant-scoped and bounded
by business volume rather than by an arbitrary 1000-row cap (FLOW-009
"Complete projections; response pagination must not truncate calculations").

Completeness and freshness are exposed on every response so UI can mark
a view as stale rather than silently show a truncated number.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from app.services.warehouse_movements.envelope import (
    LocationKey,
    LocationType,
    MovementState,
)
from app.services.warehouse_movements.fifo import (
    free_balance,
    layers_at,
)

MOVEMENTS_COLLECTION = "warehouse_transactions"


async def stock_at(
    tenant_collection,
    *,
    tenant_id: str,
    item_id: str,
    location: LocationKey,
    session=None,
) -> Dict[str, Any]:
    """Free balance + layers for one bucket; complete."""
    bal = await free_balance(
        tenant_collection,
        tenant_id=tenant_id, item_id=item_id,
        location=location, session=session,
    )
    layers = await layers_at(
        tenant_collection,
        tenant_id=tenant_id, item_id=item_id,
        location=location, session=session,
    )
    total_value = sum(
        ((l.quantity * l.unit_value) for l in layers), Decimal("0")
    ).quantize(Decimal("0.0001"))
    return {
        "tenant_id": tenant_id,
        "item_id": item_id,
        "location": location.to_dict(),
        "quantity": str(bal),
        "total_value": str(total_value),
        "layer_count": len(layers),
        "layers": [l.to_dict() for l in layers],
        "fresh_at": datetime.now(timezone.utc).isoformat(),
        "truncated": False,
    }


async def item_balance_by_location(
    tenant_collection,
    *,
    tenant_id: str,
    item_id: str,
    session=None,
) -> List[Dict[str, Any]]:
    """All buckets holding this item, with free balance each. Complete."""
    # One pass over all movements for this item; buckets are built in memory.
    cursor = tenant_collection.find({
        "tenant_id": tenant_id,
        "item_id": item_id,
    }, {
        "source": 1, "destination": 1, "quantity": 1,
        "layer_allocations": 1, "action": 1, "_id": 0,
    }, session=session)

    balances: Dict[Tuple[str, str, str], Decimal] = defaultdict(lambda: Decimal("0"))
    async for doc in cursor:
        dest = doc.get("destination")
        src = doc.get("source")
        qty = Decimal(str(doc.get("quantity", "0")))
        if dest:
            key = (dest["location_type"], dest["location_id"], dest.get("state", "free"))
            balances[key] += qty
        if src and doc.get("layer_allocations"):
            # Source side consumed by this outbound: sum its allocation quantities
            total_out = sum(
                (Decimal(str(a["quantity"])) for a in doc["layer_allocations"]),
                Decimal("0"),
            )
            key = (src["location_type"], src["location_id"], src.get("state", "free"))
            balances[key] -= total_out
        elif src and not dest:
            # Pure outbound without allocations (should not happen for ledger
            # rows written by the canonical service; included for defensive
            # reads on historical rows)
            key = (src["location_type"], src["location_id"], src.get("state", "free"))
            balances[key] -= qty

    return [
        {
            "location_type": lt,
            "location_id": lid,
            "state": st,
            "quantity": str(q),
        }
        for (lt, lid, st), q in sorted(balances.items())
        if q != 0
    ]


async def movement_history(
    tenant_collection,
    *,
    tenant_id: str,
    item_id: Optional[str] = None,
    location_type: Optional[str] = None,
    location_id: Optional[str] = None,
    project_id: Optional[str] = None,
    since_iso: Optional[str] = None,
    until_iso: Optional[str] = None,
    limit: int = 500,
    cursor_after: Optional[str] = None,
    session=None,
) -> Dict[str, Any]:
    """Paginated history ordered by stable canonical sequence (C09).

    `cursor_after` is a `ledger_sequence` integer-as-string; a legacy
    `recorded_at` ISO is also accepted so pre-TASK-5C rows participate.
    The endpoint IS paginated but does NOT cap a projection — the stock
    projection uses `item_balance_by_location`, which iterates fully.
    """
    q: Dict[str, Any] = {"tenant_id": tenant_id}
    if item_id:
        q["item_id"] = item_id
    if project_id:
        q["project_id"] = project_id
    if location_type and location_id:
        q["$or"] = [
            {"source.location_type": location_type, "source.location_id": location_id},
            {"destination.location_type": location_type, "destination.location_id": location_id},
        ]
    time_q: Dict[str, Any] = {}
    if since_iso:
        time_q["$gte"] = since_iso
    if until_iso:
        time_q["$lte"] = until_iso
    if time_q:
        q["recorded_at"] = time_q

    # Try numeric sequence cursor first (stable across ties).
    if cursor_after:
        try:
            seq = int(cursor_after)
            q["ledger_sequence"] = {"$gt": seq}
        except ValueError:
            # Legacy fallback — timestamp cursor.
            q.setdefault("recorded_at", {})["$gt"] = cursor_after

    cursor = tenant_collection.find(q, {"_id": 0}, session=session) \
        .sort([("ledger_sequence", 1), ("recorded_at", 1), ("movement_id", 1)]) \
        .limit(limit + 1)
    rows = [doc async for doc in cursor]
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]
    next_cursor = None
    if rows and has_more:
        last_seq = rows[-1].get("ledger_sequence")
        if last_seq is not None:
            next_cursor = str(last_seq)
        else:
            next_cursor = rows[-1].get("recorded_at")

    return {
        "tenant_id": tenant_id,
        "rows": rows,
        "has_more": has_more,
        "next_cursor_after": next_cursor,
        "fresh_at": datetime.now(timezone.utc).isoformat(),
        "source": "canonical_warehouse_transactions_ledger",
        "completeness": "page",
    }


async def integrity_warnings(
    tenant_collection,
    *,
    tenant_id: str,
    session=None,
    quarantine_aging_hours: int = 24 * 7,
    in_transit_aging_hours: int = 48,
) -> Dict[str, Any]:
    """FLOW-009 integrity alarms off the canonical ledger (C09 expansion).

    Covered (minimum per contract §10 and FLOW-009):
      * NEGATIVE_STOCK — defensive; fires only on projection skew.
      * LEGACY_IDENTITY_MISSING — pre-TASK-5C rows without item_id/unit.
      * UNRESOLVED_IN_TRANSIT_AGING — dispatches without acceptance
        after `in_transit_aging_hours`.
      * QUARANTINE_AGING — items held in quarantine beyond
        `quarantine_aging_hours` without a release movement.
    """
    now = datetime.now(timezone.utc)
    warnings: List[Dict[str, Any]] = []

    # Negative balances
    item_ids = await tenant_collection.distinct(
        "item_id", {"tenant_id": tenant_id}, session=session,
    )
    for item_id in item_ids:
        if not item_id:
            continue
        balances = await item_balance_by_location(
            tenant_collection, tenant_id=tenant_id,
            item_id=item_id, session=session,
        )
        for b in balances:
            if Decimal(b["quantity"]) < 0:
                warnings.append({
                    "code": "NEGATIVE_STOCK",
                    "item_id": item_id,
                    "location": {"type": b["location_type"],
                                 "id": b["location_id"], "state": b["state"]},
                    "quantity": b["quantity"],
                })

    missing_identity = await tenant_collection.count_documents(
        {"tenant_id": tenant_id,
         "$or": [{"item_id": None}, {"item_id": ""},
                 {"unit": None}, {"unit": ""}]},
        session=session,
    )
    if missing_identity:
        warnings.append({
            "code": "LEGACY_IDENTITY_MISSING",
            "count": missing_identity,
            "note": "historical rows pre-TASK-5C; canonical writer refuses these",
        })

    # Unresolved in-transit aging — dispatches older than N hours whose
    # accepted qty < dispatched qty.
    aged_dispatch_cutoff = (now.timestamp() - in_transit_aging_hours * 3600)
    async for d in tenant_collection.find({
        "tenant_id": tenant_id,
        "action": "dispatch_warehouse_to_project",
    }, {"movement_id": 1, "quantity": 1, "recorded_at": 1,
         "project_id": 1, "item_id": 1, "_id": 0}, session=session):
        try:
            dt = datetime.fromisoformat(d["recorded_at"]).timestamp()
        except Exception:
            continue
        if dt > aged_dispatch_cutoff:
            continue
        # Sum acceptances.
        acc_cursor = tenant_collection.find({
            "tenant_id": tenant_id,
            "dispatch_movement_id": d["movement_id"],
            "action": "accept_project_delivery",
        }, {"accepted_quantity": 1, "quantity": 1, "_id": 0}, session=session)
        accepted = Decimal("0")
        async for a in acc_cursor:
            accepted += Decimal(str(a.get("accepted_quantity") or a.get("quantity") or "0"))
        if accepted < Decimal(str(d.get("quantity") or "0")):
            warnings.append({
                "code": "UNRESOLVED_IN_TRANSIT_AGING",
                "dispatch_movement_id": d["movement_id"],
                "dispatched_quantity": str(d.get("quantity")),
                "accepted_quantity": str(accepted),
                "unresolved_quantity": str(Decimal(str(d.get("quantity") or "0")) - accepted),
                "recorded_at": d["recorded_at"],
                "item_id": d.get("item_id"),
                "project_id": d.get("project_id"),
                "age_hours_at_least": in_transit_aging_hours,
            })

    # Quarantine aging — rows that entered quarantine over N hours ago
    # without a release destination movement.
    quarantine_cutoff = (now.timestamp() - quarantine_aging_hours * 3600)
    async for q in tenant_collection.find({
        "tenant_id": tenant_id,
        "action": "quarantine_entry",
    }, {"movement_id": 1, "item_id": 1, "destination": 1,
         "recorded_at": 1, "quantity": 1, "_id": 0}, session=session):
        try:
            dt = datetime.fromisoformat(q["recorded_at"]).timestamp()
        except Exception:
            continue
        if dt > quarantine_cutoff:
            continue
        # Is there any release?
        released = await tenant_collection.find_one({
            "tenant_id": tenant_id,
            "action": "quarantine_release",
            "source.location_id": (q.get("destination") or {}).get("location_id"),
            "item_id": q.get("item_id"),
            "recorded_at": {"$gt": q["recorded_at"]},
        }, {"_id": 1}, session=session)
        if not released:
            warnings.append({
                "code": "QUARANTINE_AGING",
                "quarantine_movement_id": q["movement_id"],
                "item_id": q.get("item_id"),
                "quantity": str(q.get("quantity")),
                "location": q.get("destination"),
                "recorded_at": q["recorded_at"],
                "age_hours_at_least": quarantine_aging_hours,
            })

    return {
        "tenant_id": tenant_id,
        "warnings": warnings,
        "fresh_at": now.isoformat(),
        "source": "canonical_warehouse_transactions_ledger",
        "completeness": "full_tenant_scan",
    }
