"""
Routes - Subcontractor Performance Tracking v1.
Additive layer — does NOT modify subcontractor core flows.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.services.subcontractor_performance import build_subcontractor_performance

router = APIRouter(tags=["Subcontractor Performance"])


class PerformanceCreate(BaseModel):
    subcontractor_id: str
    project_id: str
    package_id: Optional[str] = None
    promised_start_date: Optional[str] = None
    promised_end_date: Optional[str] = None
    actual_start_date: Optional[str] = None
    actual_end_date: Optional[str] = None
    promised_amount: Optional[float] = None
    actual_paid_amount: Optional[float] = None
    quality_score: Optional[int] = None
    rework_flag: bool = False
    notes: Optional[str] = None


class PerformanceUpdate(BaseModel):
    actual_start_date: Optional[str] = None
    actual_end_date: Optional[str] = None
    actual_paid_amount: Optional[float] = None
    quality_score: Optional[int] = None
    rework_flag: Optional[bool] = None
    notes: Optional[str] = None


@router.get("/subcontractor-performance")
async def get_performance(
    project_id: Optional[str] = None,
    subcontractor_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    return await build_subcontractor_performance(user["org_id"], project_id, subcontractor_id)


@router.get("/subcontractor-performance/compact")
async def get_compact(
    project_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    full = await build_subcontractor_performance(user["org_id"], project_id)
    items = full["items"]
    return {
        "summary": full["summary"],
        "top_delays": sorted([i for i in items if i.get("status") == "delayed"], key=lambda x: x.get("actual_end_date", ""), reverse=True)[:5],
        "top_over_budget": sorted([i for i in items if i.get("status") in ("over_budget", "mixed")], key=lambda x: x.get("variance_amount", 0), reverse=True)[:5],
    }


@router.post("/subcontractor-performance", status_code=201)
async def create_performance(data: PerformanceCreate, user: dict = Depends(get_current_user)):
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        **data.model_dump(),
        "status": "unknown",
        "created_by": user["id"],
        "created_at": now,
        "updated_at": now,
    }
    await db.subcontractor_performance.insert_one(doc)
    return {k: v for k, v in doc.items() if k != "_id"}


@router.put("/subcontractor-performance/{record_id}")
async def update_performance(record_id: str, data: PerformanceUpdate, user: dict = Depends(get_current_user)):
    doc = await db.subcontractor_performance.find_one({"id": record_id, "org_id": user["org_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Record not found")
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.subcontractor_performance.update_one({"id": record_id}, {"$set": update})
    return await db.subcontractor_performance.find_one({"id": record_id}, {"_id": 0})


@router.get("/subcontractor-performance/log")
async def get_log(
    project_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    query = {"org_id": user["org_id"]}
    if project_id:
        query["project_id"] = project_id
    items = await db.subcontractor_performance.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"items": items, "total": len(items)}
