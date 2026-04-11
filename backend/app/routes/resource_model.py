"""
Routes - Resource & Cost Model configuration + preview.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from pydantic import BaseModel

from app.db import db
from app.deps.auth import get_current_user
from app.services.resource_model import (
    get_resource_config, save_resource_config,
    classify_worker, classify_subcontractor_type,
    compute_worker_cost_breakdown, compute_subcontractor_burden,
    RESOURCE_TYPES, SUBCONTRACTOR_TYPES, OVERHEAD_POOLS,
    ALLOCATION_RULES, INSURANCE_MODES, DEFAULT_BURDEN_WEIGHTS,
)

router = APIRouter(tags=["Resource Model"])


class ConfigUpdate(BaseModel):
    burden_weights: Optional[dict] = None
    insurance_rate: Optional[float] = None
    overhead_pools: Optional[list] = None


class WorkerCostRequest(BaseModel):
    worker_id: str
    hours: float
    hourly_rate: float
    project_hours: Optional[float] = None
    total_hours: Optional[float] = None


class SubBurdenRequest(BaseModel):
    sub_type: str
    invoice_amount: float


# ── Config ─────────────────────────────────────────────────────────

@router.get("/resource-model/config")
async def get_config(user: dict = Depends(get_current_user)):
    return await get_resource_config(user["org_id"])


@router.put("/resource-model/config")
async def update_config(data: ConfigUpdate, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    return await save_resource_config(user["org_id"], updates, user["id"])


@router.get("/resource-model/enums")
async def get_enums(user: dict = Depends(get_current_user)):
    return {
        "resource_types": RESOURCE_TYPES,
        "subcontractor_types": SUBCONTRACTOR_TYPES,
        "overhead_pools": OVERHEAD_POOLS,
        "allocation_rules": ALLOCATION_RULES,
        "insurance_modes": INSURANCE_MODES,
        "default_burden_weights": DEFAULT_BURDEN_WEIGHTS,
    }


# ── Classification ─────────────────────────────────────────────────

@router.get("/resource-model/classify-worker/{worker_id}")
async def classify_worker_endpoint(worker_id: str, user: dict = Depends(get_current_user)):
    return await classify_worker(user["org_id"], worker_id)


@router.get("/resource-model/classify-subcontractor/{sub_type}")
async def classify_sub(sub_type: str, user: dict = Depends(get_current_user)):
    if sub_type not in SUBCONTRACTOR_TYPES:
        raise HTTPException(status_code=400, detail=f"Valid types: {SUBCONTRACTOR_TYPES}")
    return classify_subcontractor_type(sub_type)


# ── Cost Preview ───────────────────────────────────────────────────

@router.post("/resource-model/worker-cost-preview")
async def worker_cost_preview(data: WorkerCostRequest, user: dict = Depends(get_current_user)):
    return await compute_worker_cost_breakdown(
        user["org_id"], data.worker_id, data.hours, data.hourly_rate,
        data.project_hours, data.total_hours,
    )


@router.post("/resource-model/subcontractor-burden-preview")
async def sub_burden_preview(data: SubBurdenRequest, user: dict = Depends(get_current_user)):
    config = await get_resource_config(user["org_id"])
    return compute_subcontractor_burden(data.sub_type, data.invoice_amount, config)
