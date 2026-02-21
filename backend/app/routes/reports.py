"""
Routes - Reports (Prices, Turnover, etc.)
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from datetime import datetime, timezone
import re

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import require_m5

router = APIRouter(tags=["Reports"])


# ── Prices (Purchase History) ─────────────────────────────────────

@router.get("/prices")
async def get_price_history(
    user: dict = Depends(require_m5),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("created_at"),
    sort_dir: str = Query("desc"),
    search: Optional[str] = None,
    item_id: Optional[str] = None,
    supplier_id: Optional[str] = None,
    project_id: Optional[str] = None,
    warehouse_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """
    Get purchase price history from invoice lines.
    Shows item prices from different suppliers over time.
    """
    # Build pipeline
    pipeline = [
        {"$match": {"org_id": user["org_id"]}},
    ]
    
    # Filter by allocation
    if project_id:
        pipeline.append({"$match": {"allocations": {"$elemMatch": {"type": "project", "ref_id": project_id}}}})
    if warehouse_id:
        pipeline.append({"$match": {"allocations": {"$elemMatch": {"type": "warehouse", "ref_id": warehouse_id}}}})
    
    # Lookup invoice for supplier and date
    pipeline.append({
        "$lookup": {
            "from": "invoices",
            "localField": "invoice_id",
            "foreignField": "id",
            "as": "invoice"
        }
    })
    pipeline.append({"$unwind": {"path": "$invoice", "preserveNullAndEmptyArrays": True}})
    
    # Filter by supplier
    if supplier_id:
        pipeline.append({"$match": {"invoice.supplier_counterparty_id": supplier_id}})
    
    # Filter by date
    if date_from:
        pipeline.append({"$match": {"invoice.issue_date": {"$gte": date_from}}})
    if date_to:
        pipeline.append({"$match": {"invoice.issue_date": {"$lte": date_to}}})
    
    # Search by description
    if search:
        pipeline.append({"$match": {"description": {"$regex": search, "$options": "i"}}})
    
    # Project fields
    pipeline.append({
        "$project": {
            "_id": 0,
            "line_id": "$id",
            "invoice_id": 1,
            "invoice_no": "$invoice.invoice_no",
            "invoice_date": "$invoice.issue_date",
            "supplier_id": "$invoice.supplier_counterparty_id",
            "description": 1,
            "unit": 1,
            "qty": 1,
            "unit_price": 1,
            "line_total_ex_vat": 1,
            "vat_amount": 1,
            "line_total_inc_vat": 1,
            "purchased_by_user_id": 1,
            "allocations": 1,
            "cost_category": 1,
            "created_at": 1,
        }
    })
    
    # Count total (separate pipeline)
    count_pipeline = pipeline.copy()
    count_pipeline.append({"$count": "total"})
    count_result = await db.invoice_lines.aggregate(count_pipeline).to_list(1)
    total = count_result[0]["total"] if count_result else 0
    
    # Sort
    sort_direction = 1 if sort_dir == "asc" else -1
    pipeline.append({"$sort": {sort_by: sort_direction}})
    
    # Paginate
    skip = (page - 1) * page_size
    pipeline.append({"$skip": skip})
    pipeline.append({"$limit": page_size})
    
    items = await db.invoice_lines.aggregate(pipeline).to_list(page_size)
    
    # Enrich with names
    for item in items:
        # Supplier name
        if item.get("supplier_id"):
            supplier = await db.counterparties.find_one(
                {"id": item["supplier_id"]}, {"_id": 0, "name": 1}
            )
            item["supplier_name"] = supplier["name"] if supplier else ""
        
        # Purchaser name
        if item.get("purchased_by_user_id"):
            purchaser = await db.users.find_one(
                {"id": item["purchased_by_user_id"]}, {"_id": 0, "first_name": 1, "last_name": 1}
            )
            item["purchased_by_name"] = f"{purchaser['first_name']} {purchaser['last_name']}" if purchaser else ""
        
        # Allocations summary
        allocations = item.get("allocations", [])
        alloc_summary = []
        for a in allocations[:3]:  # Limit to 3
            if a.get("type") == "project":
                proj = await db.projects.find_one({"id": a.get("ref_id")}, {"_id": 0, "code": 1})
                alloc_summary.append(f"P:{proj['code'] if proj else '?'}:{a.get('qty')}")
            elif a.get("type") == "warehouse":
                wh = await db.warehouses.find_one({"id": a.get("ref_id")}, {"_id": 0, "code": 1})
                alloc_summary.append(f"W:{wh['code'] if wh else '?'}:{a.get('qty')}")
        item["allocation_summary"] = ", ".join(alloc_summary)
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


# ── Turnover by Counterparty ─────────────────────────────────────

@router.get("/reports/turnover-by-counterparty")
async def get_turnover_by_counterparty(
    user: dict = Depends(require_m5),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("sum_total"),
    sort_dir: str = Query("desc"),
    counterparty_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    type: str = Query("purchases"),  # purchases, sales, all
):
    """
    Get turnover aggregated by counterparty.
    Purchases = received invoices (supplier invoices)
    Sales = issued invoices (client invoices)
    """
    # Build match stage
    match_stage = {"org_id": user["org_id"]}
    
    if type == "purchases":
        match_stage["direction"] = "Received"
    elif type == "sales":
        match_stage["direction"] = "Issued"
    
    if counterparty_id:
        match_stage["supplier_counterparty_id"] = counterparty_id
    
    if date_from:
        match_stage["issue_date"] = match_stage.get("issue_date", {})
        match_stage["issue_date"]["$gte"] = date_from
    if date_to:
        match_stage["issue_date"] = match_stage.get("issue_date", {})
        match_stage["issue_date"]["$lte"] = date_to
    
    # Aggregation pipeline
    pipeline = [
        {"$match": match_stage},
        {
            "$group": {
                "_id": "$supplier_counterparty_id",
                "count_invoices": {"$sum": 1},
                "sum_subtotal": {"$sum": "$subtotal"},
                "sum_vat": {"$sum": "$vat_amount"},
                "sum_total": {"$sum": "$total"},
                "sum_paid": {"$sum": "$paid_amount"},
                "sum_remaining": {"$sum": "$remaining_amount"},
                "first_invoice_date": {"$min": "$issue_date"},
                "last_invoice_date": {"$max": "$issue_date"},
            }
        },
    ]
    
    # Count total (before pagination)
    count_pipeline = pipeline.copy()
    count_pipeline.append({"$count": "total"})
    count_result = await db.invoices.aggregate(count_pipeline).to_list(1)
    total = count_result[0]["total"] if count_result else 0
    
    # Sort
    sort_direction = 1 if sort_dir == "asc" else -1
    pipeline.append({"$sort": {sort_by: sort_direction}})
    
    # Paginate
    skip = (page - 1) * page_size
    pipeline.append({"$skip": skip})
    pipeline.append({"$limit": page_size})
    
    results = await db.invoices.aggregate(pipeline).to_list(page_size)
    
    # Enrich with counterparty names
    items = []
    for r in results:
        counterparty_id = r["_id"]
        counterparty = None
        if counterparty_id:
            counterparty = await db.counterparties.find_one(
                {"id": counterparty_id}, {"_id": 0, "id": 1, "name": 1, "eik": 1, "type": 1}
            )
        
        items.append({
            "counterparty_id": counterparty_id,
            "counterparty_name": counterparty["name"] if counterparty else "(Неизвестен)",
            "counterparty_eik": counterparty.get("eik") if counterparty else None,
            "counterparty_type": counterparty.get("type") if counterparty else None,
            "count_invoices": r["count_invoices"],
            "sum_subtotal": round(r["sum_subtotal"] or 0, 2),
            "sum_vat": round(r["sum_vat"] or 0, 2),
            "sum_total": round(r["sum_total"] or 0, 2),
            "sum_paid": round(r["sum_paid"] or 0, 2),
            "sum_remaining": round(r["sum_remaining"] or 0, 2),
            "first_invoice_date": r["first_invoice_date"],
            "last_invoice_date": r["last_invoice_date"],
        })
    
    # Calculate grand totals
    totals_pipeline = [
        {"$match": match_stage},
        {
            "$group": {
                "_id": None,
                "total_invoices": {"$sum": 1},
                "total_subtotal": {"$sum": "$subtotal"},
                "total_vat": {"$sum": "$vat_amount"},
                "total_amount": {"$sum": "$total"},
                "total_paid": {"$sum": "$paid_amount"},
                "total_remaining": {"$sum": "$remaining_amount"},
            }
        }
    ]
    totals_result = await db.invoices.aggregate(totals_pipeline).to_list(1)
    grand_totals = totals_result[0] if totals_result else {}
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "grand_totals": {
            "total_invoices": grand_totals.get("total_invoices", 0),
            "total_subtotal": round(grand_totals.get("total_subtotal", 0), 2),
            "total_vat": round(grand_totals.get("total_vat", 0), 2),
            "total_amount": round(grand_totals.get("total_amount", 0), 2),
            "total_paid": round(grand_totals.get("total_paid", 0), 2),
            "total_remaining": round(grand_totals.get("total_remaining", 0), 2),
        },
        "filters": {
            "type": type,
            "date_from": date_from,
            "date_to": date_to,
            "counterparty_id": counterparty_id,
        }
    }


@router.get("/reports/turnover-by-counterparty/{counterparty_id}/invoices")
async def get_counterparty_invoices(
    counterparty_id: str,
    user: dict = Depends(require_m5),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    type: str = Query("purchases"),
):
    """Drill-down: Get invoices for a specific counterparty"""
    query = {
        "org_id": user["org_id"],
        "supplier_counterparty_id": counterparty_id,
    }
    
    if type == "purchases":
        query["direction"] = "Received"
    elif type == "sales":
        query["direction"] = "Issued"
    
    if date_from:
        query["issue_date"] = query.get("issue_date", {})
        query["issue_date"]["$gte"] = date_from
    if date_to:
        query["issue_date"] = query.get("issue_date", {})
        query["issue_date"]["$lte"] = date_to
    
    total = await db.invoices.count_documents(query)
    
    skip = (page - 1) * page_size
    invoices = await db.invoices.find(query, {"_id": 0}).sort("issue_date", -1).skip(skip).limit(page_size).to_list(page_size)
    
    # Get counterparty name
    counterparty = await db.counterparties.find_one({"id": counterparty_id}, {"_id": 0, "name": 1})
    
    return {
        "counterparty_id": counterparty_id,
        "counterparty_name": counterparty["name"] if counterparty else "(Неизвестен)",
        "items": invoices,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }
