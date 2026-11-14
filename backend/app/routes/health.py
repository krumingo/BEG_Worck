"""
Health and misc routes - /api/health, /api/version, /api/roles, /api/modules, /api/subscription
"""
from fastapi import APIRouter, Depends, Request

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import SUBSCRIPTION_PLANS
from app.constants import ROLES, MODULES
from app.core.build_info import current_version
from app.tenancy.data_access import TenantData


def _tenant(user: dict) -> TenantData:
    """The request's tenant — from the server-loaded session user only (W0-03E-A2C)."""
    return TenantData.for_user(db, user)

router = APIRouter(tags=["misc"])

@router.get("/health")
async def health():
    # FG-642: a boolean only (no login here); the details are on GET /api/sync/ops/alarms
    from app.services.offline_sync import is_degraded
    return {"status": "ok", "degraded": True} if is_degraded() else {"status": "ok"}

@router.get("/version")
async def version():
    """RC-01: build identity, no authentication. Allowlisted keys only (no secrets)."""
    return current_version()

@router.get("/roles")
async def list_roles():
    return ROLES

@router.get("/modules")
async def list_modules():
    return MODULES

@router.get("/subscription")
async def get_subscription(request: Request, user: dict = Depends(get_current_user)):
    tenant = _tenant(user)
    sub = await tenant.subscriptions.find_one({"org_id": user["org_id"]}, {"_id": 0})
    if sub:
        plan = SUBSCRIPTION_PLANS.get(sub.get("plan_id", "free"), SUBSCRIPTION_PLANS["free"])
        sub["plan_name"] = plan["name"]
        sub["plan_price"] = plan["price"]
        sub["allowed_modules"] = plan["allowed_modules"]
        sub["limits"] = plan["limits"]
    # SEC-02-B (R20, FLOW-050): the plan price — Owner/Admin only.
    from app.permissions.money_write import money_values_visible
    from app.permissions.finance_read import SUBSCRIPTION_PRICE_READ, SUBSCRIPTION_PRICE_FIELDS
    if sub and not await money_values_visible(request, user, action=SUBSCRIPTION_PRICE_READ,
                                              roles=("Owner", "Admin")):
        sub = {k: v for k, v in sub.items() if k not in SUBSCRIPTION_PRICE_FIELDS}
    return sub
