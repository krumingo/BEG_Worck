"""
Health and misc routes - /api/health, /api/roles, /api/modules, /api/subscription
"""
from fastapi import APIRouter, Depends

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import SUBSCRIPTION_PLANS
from app.constants import ROLES, MODULES

router = APIRouter(tags=["misc"])

@router.get("/health")
async def health():
    return {"status": "ok"}

@router.get("/roles")
async def list_roles():
    return ROLES

@router.get("/modules")
async def list_modules():
    return MODULES

@router.get("/subscription")
async def get_subscription(user: dict = Depends(get_current_user)):
    sub = await db.subscriptions.find_one({"org_id": user["org_id"]}, {"_id": 0})
    if sub:
        plan = SUBSCRIPTION_PLANS.get(sub.get("plan_id", "free"), SUBSCRIPTION_PLANS["free"])
        sub["plan_name"] = plan["name"]
        sub["plan_price"] = plan["price"]
        sub["allowed_modules"] = plan["allowed_modules"]
        sub["limits"] = plan["limits"]
    return sub
