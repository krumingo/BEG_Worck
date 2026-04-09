"""
Routes - Material Waste Tracking v1.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.services.material_waste import build_material_waste_summary

router = APIRouter(tags=["Material Waste"])


class WasteEntryCreate(BaseModel):
    material_name: str
    item_id: Optional[str] = None
    activity_type: Optional[str] = None
    smr_type: Optional[str] = None
    location_id: Optional[str] = None
    qty: float
    unit: str = "бр"
    waste_type: str = "damaged"
    notes: Optional[str] = None
    date: Optional[str] = None


@router.get("/projects/{project_id}/material-waste")
async def get_material_waste(
    project_id: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    return await build_material_waste_summary(user["org_id"], project_id, date_from, date_to)


@router.get("/projects/{project_id}/material-waste/compact")
async def get_compact_waste(project_id: str, user: dict = Depends(get_current_user)):
    full = await build_material_waste_summary(user["org_id"], project_id)
    materials = full["materials"]
    return {
        "summary": full["summary"],
        "top_overuse": sorted([m for m in materials if m["status"] == "overuse"], key=lambda x: x["variance_vs_planned"], reverse=True)[:5],
        "top_waste": sorted(materials, key=lambda x: x["wasted_qty"], reverse=True)[:5],
    }


@router.post("/projects/{project_id}/material-waste", status_code=201)
async def create_waste_entry(project_id: str, data: WasteEntryCreate, user: dict = Depends(get_current_user)):
    now = datetime.now(timezone.utc).isoformat()
    entry = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "project_id": project_id,
        "material_name": data.material_name,
        "item_id": data.item_id,
        "activity_type": data.activity_type,
        "smr_type": data.smr_type,
        "location_id": data.location_id,
        "qty": data.qty,
        "unit": data.unit,
        "waste_type": data.waste_type,
        "notes": data.notes,
        "date": data.date or now[:10],
        "created_by": user["id"],
        "created_at": now,
        "updated_at": now,
    }
    await db.material_waste_entries.insert_one(entry)
    return {k: v for k, v in entry.items() if k != "_id"}


@router.get("/projects/{project_id}/material-waste/log")
async def get_waste_log(project_id: str, user: dict = Depends(get_current_user)):
    items = await db.material_waste_entries.find(
        {"org_id": user["org_id"], "project_id": project_id}, {"_id": 0}
    ).sort("date", -1).to_list(200)
    return {"items": items, "total": len(items)}
