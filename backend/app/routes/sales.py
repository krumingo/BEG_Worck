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


# ── Sales History ──

@router.get("/sales/history")
async def sales_history(
    page: int = 1, page_size: int = 25,
    from_date: str = "", to_date: str = "",
    item_id: str = "", client_id: str = "", project_id: str = "", warehouse_id: str = "",
    has_warning: str = "",
    sort_by: str = "date", sort_dir: str = "desc",
    user: dict = Depends(get_current_user),
):
    org_id = user["org_id"]
    query = {"org_id": org_id}
    if from_date:
        query["created_at"] = {"$gte": from_date}
    if to_date:
        query.setdefault("created_at", {})["$lte"] = to_date + "T23:59:59"
    if item_id:
        query["item_id"] = item_id
    if client_id:
        query["client_id"] = client_id
    if project_id:
        query["project_id"] = project_id
    if warehouse_id:
        query["warehouse_id"] = warehouse_id
    if has_warning == "true":
        query["warning_flag"] = True

    sort_map = {"date": "created_at", "profit": "profit_amount", "margin": "margin_percent"}
    sort_field = sort_map.get(sort_by, "created_at")
    sort_direction = -1 if sort_dir == "desc" else 1

    total_count = await db.sales.count_documents(query)
    sales = await db.sales.find(query, {"_id": 0}).sort(
        sort_field, sort_direction
    ).skip((page - 1) * page_size).limit(page_size).to_list(page_size)

    # Enrich with names
    item_ids = list(set(s.get("item_id") for s in sales if s.get("item_id")))
    items_map = {}
    if item_ids:
        items_list = await db.items.find({"id": {"$in": item_ids}}, {"_id": 0, "id": 1, "name": 1}).to_list(500)
        items_map = {i["id"]: i["name"] for i in items_list}

    wh_ids = list(set(s.get("warehouse_id") for s in sales if s.get("warehouse_id")))
    wh_map = {}
    if wh_ids:
        wh_list = await db.warehouses.find({"id": {"$in": wh_ids}}, {"_id": 0, "id": 1, "name": 1}).to_list(50)
        wh_map = {w["id"]: w["name"] for w in wh_list}

    user_ids = list(set(s.get("sold_by") for s in sales if s.get("sold_by")))
    user_map = {}
    if user_ids:
        users_list = await db.users.find({"id": {"$in": user_ids}}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1}).to_list(50)
        user_map = {u["id"]: f"{u.get('first_name','')} {u.get('last_name','')}".strip() for u in users_list}

    data = []
    for s in sales:
        data.append({
            "sale_id": s["id"],
            "date": s.get("created_at", ""),
            "item_id": s.get("item_id"),
            "item_name": items_map.get(s.get("item_id"), ""),
            "warehouse_name": wh_map.get(s.get("warehouse_id"), ""),
            "client_id": s.get("client_id"),
            "project_id": s.get("project_id"),
            "quantity": s.get("quantity", 0),
            "unit_sale_price": s.get("unit_sale_price", 0),
            "total_sale": s.get("total_sale_amount", 0),
            "total_cost": s.get("cost_at_sale", 0),
            "weighted_avg_cost": s.get("unit_cost_at_sale", 0),
            "profit_amount": s.get("profit_amount", 0),
            "margin_percent": s.get("margin_percent", 0),
            "currency": s.get("currency", "BGN"),
            "warning_flag": s.get("warning_flag", False),
            "warning_reason": s.get("warning_reason", ""),
            "user_name": user_map.get(s.get("sold_by"), ""),
            "fifo_breakdown_count": len(s.get("fifo_allocations", [])),
        })

    # Summary
    all_sales = await db.sales.find(query, {"_id": 0, "total_sale_amount": 1, "cost_at_sale": 1, "profit_amount": 1, "margin_percent": 1, "warning_flag": 1}).to_list(5000)
    total_revenue = round(sum(s.get("total_sale_amount", 0) for s in all_sales), 2)
    total_cost_sum = round(sum(s.get("cost_at_sale", 0) for s in all_sales), 2)
    total_profit = round(sum(s.get("profit_amount", 0) for s in all_sales), 2)
    margins = [s.get("margin_percent", 0) for s in all_sales if s.get("margin_percent") is not None]
    avg_margin = round(sum(margins) / len(margins), 1) if margins else 0
    warnings_count = sum(1 for s in all_sales if s.get("warning_flag"))

    return {
        "data": data,
        "total_count": total_count,
        "page": page,
        "page_size": page_size,
        "summary": {
            "total_revenue": total_revenue,
            "total_cost": total_cost_sum,
            "total_profit": total_profit,
            "avg_margin_percent": avg_margin,
            "warnings_count": warnings_count,
        },
    }


@router.get("/sales/{sale_id}/details")
async def sale_details(sale_id: str, user: dict = Depends(get_current_user)):
    sale = await db.sales.find_one({"id": sale_id, "org_id": user["org_id"]}, {"_id": 0})
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    # Enrich item name
    item = await db.items.find_one({"id": sale.get("item_id")}, {"_id": 0, "name": 1})
    sale["item_name"] = item["name"] if item else ""
    return sale
