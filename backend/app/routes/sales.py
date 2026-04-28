"""
Routes — Sales with FIFO consumption, margin protection, historical context.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone, timedelta
import uuid
import hashlib
import logging

from app.db import db
from app.deps.auth import get_current_user
from app.services.fifo_service import consume_fifo, get_current_stock, InsufficientStockError

router = APIRouter(tags=["Sales"])
logger = logging.getLogger(__name__)

DEFAULT_MARGINS = {"low": 20, "medium": 30, "high": 50, "minimum": 15}


# ── Helpers ──

async def _fifo_preview_calc(org_id, item_id, warehouse_id, quantity):
    """Read-only FIFO simulation — does NOT modify DB."""
    batches = await db.warehouse_batches.find(
        {"org_id": org_id, "item_id": item_id, "warehouse_id": warehouse_id,
         "status": "active", "remaining_qty": {"$gt": 0}},
        {"_id": 0},
    ).sort("received_at", 1).to_list(500)

    available = sum(b["remaining_qty"] for b in batches)
    if available < quantity:
        return {
            "available": False,
            "total_qty_in_stock": round(available, 4),
            "shortage": round(quantity - available, 4),
            "fifo_breakdown": [],
            "total_cost": 0, "weighted_avg_cost": 0, "currency": "BGN",
            "snapshot_token": "",
        }

    breakdown = []
    remaining_need = quantity
    token_parts = []

    for b in batches:
        if remaining_need <= 0:
            break
        take = min(b["remaining_qty"], remaining_need)
        breakdown.append({
            "batch_id": b["id"],
            "batch_number": b["batch_number"],
            "qty_taken": round(take, 4),
            "unit_price": b["unit_cost"],
            "line_cost": round(take * b["unit_cost"], 2),
            "supplier": b.get("supplier_id") or "",
            "received_at": (b.get("received_at") or "")[:10],
        })
        token_parts.append(f"{b['id']}:{b['remaining_qty']}")
        remaining_need = round(remaining_need - take, 4)

    total_cost = round(sum(r["line_cost"] for r in breakdown), 2)
    avg_cost = round(total_cost / quantity, 4) if quantity > 0 else 0
    token = hashlib.md5("|".join(sorted(token_parts)).encode()).hexdigest()

    return {
        "available": True,
        "total_qty_in_stock": round(available, 4),
        "fifo_breakdown": breakdown,
        "total_cost": total_cost,
        "weighted_avg_cost": round(avg_cost, 2),
        "currency": "BGN",
        "snapshot_token": token,
    }


async def _get_margins(org_id):
    doc = await db.settings.find_one({"_id": f"sales_margins_{org_id}"})
    if doc:
        return doc.get("margins", DEFAULT_MARGINS)
    return DEFAULT_MARGINS


# ── Endpoints ──

class PreviewRequest(BaseModel):
    item_id: str
    quantity: float
    warehouse_id: str


@router.post("/sales/fifo-preview")
async def fifo_preview(data: PreviewRequest, user: dict = Depends(get_current_user)):
    return await _fifo_preview_calc(user["org_id"], data.item_id, data.warehouse_id, data.quantity)


@router.get("/sales/historical-context")
async def historical_context(item_id: str, months: int = 12, user: dict = Depends(get_current_user)):
    org_id = user["org_id"]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=months * 30)).isoformat()

    sales = await db.sales.find(
        {"org_id": org_id, "item_id": item_id, "created_at": {"$gte": cutoff}},
        {"_id": 0, "unit_sale_price": 1, "quantity": 1, "created_at": 1},
    ).sort("created_at", 1).to_list(500)

    if len(sales) < 3:
        return {"item_id": item_id, "period_months": months, "insufficient_data": True,
                "sales_count": len(sales)}

    prices = [s["unit_sale_price"] for s in sales if s.get("unit_sale_price")]
    if not prices:
        return {"item_id": item_id, "period_months": months, "insufficient_data": True, "sales_count": 0}

    sorted_prices = sorted(prices)
    mid = len(sorted_prices) // 2
    median = sorted_prices[mid] if len(sorted_prices) % 2 else round((sorted_prices[mid - 1] + sorted_prices[mid]) / 2, 2)

    # Simple trend: compare avg of first half vs second half
    half = len(prices) // 2
    if half > 0:
        first_avg = sum(prices[:half]) / half
        second_avg = sum(prices[half:]) / (len(prices) - half)
        if second_avg > first_avg * 1.05:
            trend = "rising"
        elif second_avg < first_avg * 0.95:
            trend = "falling"
        else:
            trend = "stable"
    else:
        trend = "stable"

    last = sales[-1]
    return {
        "item_id": item_id, "period_months": months, "insufficient_data": False,
        "sales_count": len(sales),
        "min_price": round(min(prices), 2),
        "max_price": round(max(prices), 2),
        "avg_price": round(sum(prices) / len(prices), 2),
        "median_price": median,
        "trend": trend,
        "last_sale": {
            "date": (last.get("created_at") or "")[:10],
            "price": last.get("unit_sale_price", 0),
            "quantity": last.get("quantity", 0),
        },
    }


@router.get("/settings/sales-margins")
async def get_sales_margins(user: dict = Depends(get_current_user)):
    return await _get_margins(user["org_id"])


@router.put("/settings/sales-margins")
async def set_sales_margins(data: dict, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    margins = {
        "low": data.get("low", 20),
        "medium": data.get("medium", 30),
        "high": data.get("high", 50),
        "minimum": data.get("minimum", 15),
    }
    await db.settings.update_one(
        {"_id": f"sales_margins_{user['org_id']}"},
        {"$set": {"margins": margins, "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return margins


class CommitRequest(BaseModel):
    item_id: str
    warehouse_id: str
    quantity: float
    unit_sale_price: float
    currency: str = "BGN"
    client_id: Optional[str] = None
    project_id: Optional[str] = None
    snapshot_token: str
    warning_acknowledged: bool = False
    warning_reason: str = ""


@router.post("/sales/commit", status_code=201)
async def commit_sale(data: CommitRequest, user: dict = Depends(get_current_user)):
    org_id = user["org_id"]

    # 1. Re-check: preview again and compare snapshot
    preview = await _fifo_preview_calc(org_id, data.item_id, data.warehouse_id, data.quantity)
    if not preview["available"]:
        raise HTTPException(status_code=400, detail=f"Недостатъчна наличност: налични {preview['total_qty_in_stock']}")
    if preview["snapshot_token"] != data.snapshot_token:
        raise HTTPException(status_code=409, detail="Наличността се промени, презаредете preview-то")

    # 2. Margin protection
    total_cost = preview["total_cost"]
    unit_cost = preview["weighted_avg_cost"]
    margins = await _get_margins(org_id)
    min_margin_pct = margins.get("minimum", 15)

    if data.quantity > 0:
        min_price = round(unit_cost * (1 + min_margin_pct / 100), 2)

        if data.unit_sale_price < unit_cost:
            # Below cost — require ack + reason
            if not data.warning_acknowledged:
                raise HTTPException(status_code=422, detail="Цената е под себестойност. Потвърдете с warning_acknowledged.")
            if len(data.warning_reason.strip()) < 10:
                raise HTTPException(status_code=422, detail="При продажба под себестойност е необходима причина (мин. 10 символа).")
        elif data.unit_sale_price < min_price:
            # Below minimum margin — require ack
            if not data.warning_acknowledged:
                raise HTTPException(status_code=422, detail=f"Цената е под минималния марж ({min_margin_pct}%). Потвърдете с warning_acknowledged.")

    # 3. Consume FIFO
    try:
        consumption = await consume_fifo(org_id, data.item_id, data.warehouse_id, data.quantity)
    except InsufficientStockError as e:
        raise HTTPException(status_code=400, detail=f"Недостатъчна наличност: {e.available}")

    # 4. Create sale record
    now = datetime.now(timezone.utc).isoformat()
    profit = round((data.unit_sale_price * data.quantity) - total_cost, 2)
    margin_pct = round((data.unit_sale_price - unit_cost) / unit_cost * 100, 1) if unit_cost > 0 else 0

    sale = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "item_id": data.item_id,
        "warehouse_id": data.warehouse_id,
        "quantity": data.quantity,
        "unit_sale_price": data.unit_sale_price,
        "total_sale_amount": round(data.unit_sale_price * data.quantity, 2),
        "cost_at_sale": total_cost,
        "unit_cost_at_sale": unit_cost,
        "profit_amount": profit,
        "margin_percent": margin_pct,
        "currency": data.currency,
        "client_id": data.client_id,
        "project_id": data.project_id,
        "fifo_allocations": consumption,
        "warning_flag": data.unit_sale_price < unit_cost,
        "warning_reason": data.warning_reason if data.unit_sale_price < unit_cost else "",
        "sold_by": user["id"],
        "created_at": now,
    }
    await db.sales.insert_one(sale)

    return {
        "sale_id": sale["id"],
        "total_sale": sale["total_sale_amount"],
        "total_cost": total_cost,
        "profit": profit,
        "margin_percent": margin_pct,
    }
