"""
Routes - Material Waste Tracking v1.
"""
from fastapi import APIRouter, Depends, Header, HTTPException
from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel, field_validator
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.permissions.money_write import require_field_cost_write
from app.permissions.money_input import MoneyWrite, money_value, project_in_tenant  # SEC-01-C03
from app.services.money_amount import strict_number  # SEC-01-C03-B (FG-47)
from app.services.material_waste import build_material_waste_summary
from app.tenancy.data_access import TenantData


def _tenant(user: dict) -> TenantData:
    """The request's tenant — from the server-loaded session user only (W0-03E-A2C)."""
    return TenantData.for_user(db, user)

router = APIRouter(tags=["Material Waste"])


class WasteEntryCreate(BaseModel):
    material_name: str
    item_id: Optional[str] = None
    activity_type: Optional[str] = None
    smr_type: Optional[str] = None
    location_id: Optional[str] = None
    qty: float
    unit: str = "бр"

    @field_validator("qty", mode="before")
    @classmethod
    def qty_is_a_number(cls, value):
        """SEC-01-C03-B (FG-47): only a JSON number — refused BEFORE Pydantic coerces "12"/true."""
        return strict_number(value)
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
async def create_waste_entry(
    project_id: str,
    data: WasteEntryCreate,
    user: dict = Depends(require_field_cost_write(
        "material_waste.entry.create", module="M2", resource_type="material_waste_entry",
        project_from="path")),  # SEC-01 + C01 (R16)
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    tenant = _tenant(user)
    qty = money_value(data.qty, "qty")  # SEC-01-C03: finite > 0, else 422 before any write
    await project_in_tenant(tenant, project_id)  # SEC-01-C03-B (FG-29)
    mw = await MoneyWrite.begin(user, "material_waste.entry.create", idempotency_key,
                                {"project_id": project_id, **data.model_dump()})
    if mw.replay_id:
        return await tenant.material_waste_entries.find_one({"id": mw.replay_id}, {"_id": 0})
    now = datetime.now(timezone.utc).isoformat()
    entry = {
        "id": mw.new_id("material_waste_entry"),
        "org_id": user["org_id"],
        "project_id": project_id,
        "material_name": data.material_name,
        "item_id": data.item_id,
        "activity_type": data.activity_type,
        "smr_type": data.smr_type,
        "location_id": data.location_id,
        "qty": qty,
        "unit": data.unit,
        "waste_type": data.waste_type,
        "notes": data.notes,
        "date": data.date or now[:10],
        "created_by": user["id"],
        "created_at": now,
        "updated_at": now,
    }
    async with mw:
        if await mw.needs_insert(tenant.material_waste_entries, entry["id"]):
            await tenant.material_waste_entries.insert_one(entry)
        mw.result_id = entry["id"]
    return {k: v for k, v in entry.items() if k != "_id"}


@router.get("/projects/{project_id}/material-waste/log")
async def get_waste_log(project_id: str, user: dict = Depends(get_current_user)):
    tenant = _tenant(user)
    items = await tenant.material_waste_entries.find(
        {"org_id": user["org_id"], "project_id": project_id}, {"_id": 0}
    ).sort("date", -1).to_list(200)
    return {"items": items, "total": len(items)}
