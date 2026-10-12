"""
Routes — Warehouse Batches (FIFO).
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone

from app.db import db
from app.deps.auth import get_current_user
from app.services.fifo_service import (
    add_batch, consume_fifo, get_current_stock, get_stock_value,
    InsufficientStockError,
)
from app.tenancy.data_access import TenantData
# LIVE-OPS-01 / TASK 5C — Legacy warehouse writer fail-close guard.
# `warehouse_batches` is a PROJECTION-ONLY collection; direct writes are
# retired. Reads below remain operational.
from app.services.warehouse_movements.legacy_inventory import (
    refuse_if_disabled as _refuse_legacy_warehouse_writer,
)
from app.services.warehouse_movements.errors import (
    LegacyWriterRetiredError as _LegacyWriterRetiredError,
)


def _tenant(user: dict) -> TenantData:
    """The request's tenant — from the server-loaded session user only (W0-03E-A2C)."""
    return TenantData.for_user(db, user)


def _guard_legacy_warehouse_writer(route_id: str, canonical_action: str) -> None:
    """Raise HTTP 410 Gone unless `LEGACY_WAREHOUSE_WRITERS_ENABLED` is set."""
    try:
        _refuse_legacy_warehouse_writer(route_id, canonical_action)
    except _LegacyWriterRetiredError as exc:
        raise HTTPException(
            status_code=410,
            detail={
                "error_code": exc.error_code,
                "message": exc.message,
                "context": exc.context,
                "canonical_endpoint": "POST /api/warehouse/canonical/movements",
            },
        ) from exc

router = APIRouter(tags=["Warehouse Batches"])


class BatchCreate(BaseModel):
    item_id: str
    warehouse_id: str
    qty: float
    unit_cost: float
    source_type: str = "purchase"
    supplier_id: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    currency: str = "BGN"
    expires_at: Optional[str] = None
    notes: Optional[str] = None


class ConsumeRequest(BaseModel):
    item_id: str
    warehouse_id: str
    qty: float


# ── List batches ──

@router.get("/warehouse/batches")
async def list_batches(
    item_id: str = "", warehouse_id: str = "", status: str = "",
    page: int = 1, page_size: int = 50,
    user: dict = Depends(get_current_user),
):
    tenant = _tenant(user)
    org_id = user["org_id"]
    query = {"org_id": org_id}
    if item_id:
        query["item_id"] = item_id
    if warehouse_id:
        query["warehouse_id"] = warehouse_id
    if status:
        query["status"] = status
    else:
        query["status"] = {"$ne": "depleted"}

    total = await tenant.warehouse_batches.count_documents(query)
    batches = await tenant.warehouse_batches.find(query, {"_id": 0}).sort(
        "received_at", 1
    ).skip((page - 1) * page_size).limit(page_size).to_list(page_size)

    return {"items": batches, "total": total, "page": page}


@router.get("/warehouse/batches/{batch_id}")
async def get_batch(batch_id: str, user: dict = Depends(get_current_user)):
    tenant = _tenant(user)
    batch = await tenant.warehouse_batches.find_one(
        {"id": batch_id, "org_id": user["org_id"]}, {"_id": 0}
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return batch


# ── Item stock & batches ──

@router.get("/warehouse/items/{item_id}/stock-summary")
async def item_stock_summary(item_id: str, warehouse_id: str = "", user: dict = Depends(get_current_user)):
    return await get_current_stock(user["org_id"], item_id, warehouse_id or None)


@router.get("/warehouse/items/{item_id}/batches")
async def item_batches(item_id: str, user: dict = Depends(get_current_user)):
    tenant = _tenant(user)
    batches = await tenant.warehouse_batches.find(
        {"org_id": user["org_id"], "item_id": item_id, "status": {"$in": ["active", "blocked"]}},
        {"_id": 0},
    ).sort("received_at", 1).to_list(200)
    return {"batches": batches, "total": len(batches)}


# ── Create batch ──

@router.post("/warehouse/batches", status_code=201)
async def create_batch(data: BatchCreate, user: dict = Depends(get_current_user)):
    """LIVE-OPS-01 / TASK 5C — **RETIRED** (v6 §12.1).
    ``warehouse_batches`` is a projector over the canonical ledger;
    supplier receipts land as canonical ``receive_from_supplier``.
    """
    _guard_legacy_warehouse_writer(
        "warehouse_batches.create_batch", "receive_from_supplier",
    )
    raise HTTPException(status_code=410, detail={
        "error_code": "LEGACY_WRITER_RETIRED",
        "canonical_endpoint": "POST /api/warehouse/canonical/movements",
    })


# ── Consume (FIFO) ──

@router.post("/warehouse/consume")
async def consume_stock(data: ConsumeRequest, user: dict = Depends(get_current_user)):
    """LIVE-OPS-01 / TASK 5C — **RETIRED** (v6 §12.1).
    Replaced by canonical ``consume_to_smr``.
    """
    _guard_legacy_warehouse_writer(
        "warehouse_batches.consume", "consume_to_smr",
    )
    raise HTTPException(status_code=410, detail={
        "error_code": "LEGACY_WRITER_RETIRED",
        "canonical_endpoint": "POST /api/warehouse/canonical/movements",
    })


# ── Block/unblock batch ──

@router.put("/warehouse/batches/{batch_id}/block")
async def block_batch(batch_id: str, user: dict = Depends(get_current_user)):
    """LIVE-OPS-01 / TASK 5C — **RETIRED** (v6 §12.1).
    Replaced by canonical ``quarantine_entry``.
    """
    _guard_legacy_warehouse_writer(
        "warehouse_batches.block", "quarantine_entry",
    )
    raise HTTPException(status_code=410, detail={
        "error_code": "LEGACY_WRITER_RETIRED",
        "canonical_endpoint": "POST /api/warehouse/canonical/movements",
    })


# ── Warehouse total value ──

@router.get("/warehouse/value")
async def warehouse_value(warehouse_id: str = "", user: dict = Depends(get_current_user)):
    tenant = _tenant(user)
    if not warehouse_id:
        # All warehouses
        warehouses = await tenant.warehouses.find({"org_id": user["org_id"]}, {"_id": 0, "id": 1, "name": 1}).to_list(50)
        results = []
        grand_total = 0
        for wh in warehouses:
            val = await get_stock_value(user["org_id"], wh["id"])
            results.append({"warehouse_id": wh["id"], "name": wh["name"], **val})
            grand_total += val["total_value"]
        return {"warehouses": results, "grand_total": round(grand_total, 2)}
    return await get_stock_value(user["org_id"], warehouse_id)
