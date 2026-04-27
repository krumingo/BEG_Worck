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

    total = await db.warehouse_batches.count_documents(query)
    batches = await db.warehouse_batches.find(query, {"_id": 0}).sort(
        "received_at", 1
    ).skip((page - 1) * page_size).limit(page_size).to_list(page_size)

    return {"items": batches, "total": total, "page": page}


@router.get("/warehouse/batches/{batch_id}")
async def get_batch(batch_id: str, user: dict = Depends(get_current_user)):
    batch = await db.warehouse_batches.find_one(
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
    batches = await db.warehouse_batches.find(
        {"org_id": user["org_id"], "item_id": item_id, "status": {"$in": ["active", "blocked"]}},
        {"_id": 0},
    ).sort("received_at", 1).to_list(200)
    return {"batches": batches, "total": len(batches)}


# ── Create batch ──

@router.post("/warehouse/batches", status_code=201)
async def create_batch(data: BatchCreate, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner", "Warehousekeeper"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    batch = await add_batch(
        org_id=user["org_id"],
        item_id=data.item_id,
        warehouse_id=data.warehouse_id,
        qty=data.qty,
        unit_cost=data.unit_cost,
        source_type=data.source_type,
        supplier_id=data.supplier_id,
        invoice_number=data.invoice_number,
        invoice_date=data.invoice_date,
        ordered_by=user["id"],
        currency=data.currency,
        expires_at=data.expires_at,
        notes=data.notes,
    )
    return batch


# ── Consume (FIFO) ──

@router.post("/warehouse/consume")
async def consume_stock(data: ConsumeRequest, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner", "Warehousekeeper", "SiteManager", "Technician"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    try:
        rows = await consume_fifo(user["org_id"], data.item_id, data.warehouse_id, data.qty)
        # Log consumption
        await db.material_consumption_log.insert_one({
            "id": str(__import__("uuid").uuid4()),
            "org_id": user["org_id"],
            "item_id": data.item_id,
            "warehouse_id": data.warehouse_id,
            "qty": data.qty,
            "consumption_rows": rows,
            "total_cost": round(sum(r["total_cost"] for r in rows), 2),
            "consumed_by": user["id"],
            "consumed_at": datetime.now(timezone.utc).isoformat(),
        })
        return {"rows": rows, "total_cost": round(sum(r["total_cost"] for r in rows), 2)}
    except InsufficientStockError as e:
        raise HTTPException(status_code=400, detail=f"Недостатъчна наличност: заявени {e.requested}, налични {e.available}")


# ── Block/unblock batch ──

@router.put("/warehouse/batches/{batch_id}/block")
async def block_batch(batch_id: str, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner", "Warehousekeeper"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    batch = await db.warehouse_batches.find_one({"id": batch_id, "org_id": user["org_id"]})
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    new_status = "active" if batch["status"] == "blocked" else "blocked"
    await db.warehouse_batches.update_one(
        {"id": batch_id},
        {"$set": {"status": new_status, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"id": batch_id, "status": new_status}


# ── Warehouse total value ──

@router.get("/warehouse/value")
async def warehouse_value(warehouse_id: str = "", user: dict = Depends(get_current_user)):
    if not warehouse_id:
        # All warehouses
        warehouses = await db.warehouses.find({"org_id": user["org_id"]}, {"_id": 0, "id": 1, "name": 1}).to_list(50)
        results = []
        grand_total = 0
        for wh in warehouses:
            val = await get_stock_value(user["org_id"], wh["id"])
            results.append({"warehouse_id": wh["id"], "name": wh["name"], **val})
            grand_total += val["total_value"]
        return {"warehouses": results, "grand_total": round(grand_total, 2)}
    return await get_stock_value(user["org_id"], warehouse_id)
