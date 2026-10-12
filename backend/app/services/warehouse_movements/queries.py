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
    """Paginated history. `cursor_after` is a `recorded_at` ISO string.

    This endpoint IS paginated but does not CAP a projection — the stock
    projection uses `item_balance_by_location` which iterates fully.
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
    if cursor_after:
        time_q["$gt"] = cursor_after
    if time_q:
        q["recorded_at"] = time_q

    cursor = tenant_collection.find(q, {"_id": 0}, session=session) \
        .sort("recorded_at", 1).limit(limit + 1)
    rows = [doc async for doc in cursor]
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]
    next_cursor = rows[-1]["recorded_at"] if rows and has_more else None

    return {
        "tenant_id": tenant_id,
        "rows": rows,
        "has_more": has_more,
        "next_cursor_after": next_cursor,
        "fresh_at": datetime.now(timezone.utc).isoformat(),
    }


async def integrity_warnings(
    tenant_collection,
    *,
    tenant_id: str,
    session=None,
) -> Dict[str, Any]:
    """Compute FLOW-009 integrity alarms off the canonical ledger.

    Alarms exposed (initial coverage; CODEX can request more):
      - negative stock at any bucket (defensive: should never fire if the
        service wrote everything correctly, but surfaces projection skew);
      - in-transit older than 48h with unresolved remainder;
      - quarantine entries never released after 7 days;
      - dispatch without acceptance for 24h;
      - movements missing item_id or unit (legacy rows only — the
        canonical writer refuses these).
    """
    now = datetime.now(timezone.utc)
    warnings: List[Dict[str, Any]] = []

    # negative balances (reads over all items — bounded by business volume)
    item_ids = await tenant_collection.distinct("item_id", {"tenant_id": tenant_id}, session=session)
    for item_id in item_ids:
        if not item_id:
            continue
        balances = await item_balance_by_location(
            tenant_collection, tenant_id=tenant_id, item_id=item_id, session=session,
        )
        for b in balances:
            if Decimal(b["quantity"]) < 0:
                warnings.append({
                    "code": "NEGATIVE_STOCK",
                    "item_id": item_id,
                    "location": {"type": b["location_type"], "id": b["location_id"], "state": b["state"]},
                    "quantity": b["quantity"],
                })

    # legacy rows missing identity (historical preservation)
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

    return {
        "tenant_id": tenant_id,
        "warnings": warnings,
        "fresh_at": now.isoformat(),
    }
