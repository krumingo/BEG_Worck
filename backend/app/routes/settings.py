"""
Settings routes — per-organization configuration.

P0-2A: Adds payroll_week setting (first day of payroll week).
For construction companies that pay on Friday, work from previous Sat/Sun
must enter the current Friday payment cycle, so default first_day=6 (Saturday).
Other companies may prefer first_day=1 (Monday).
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.deps.auth import get_current_user
from app.db import db

router = APIRouter()


class PayrollWeekSettings(BaseModel):
    """
    first_day: 0=Sunday, 1=Monday, 2=Tuesday, ..., 6=Saturday
    Matches JavaScript Date.getDay() convention.
    Default for BEG_Work: 6 (Saturday).
    """
    first_day: int = Field(ge=0, le=6)


# ── GET payroll-week settings ─────────────────────────────────────
@router.get("/settings/payroll-week")
async def get_payroll_week(user: dict = Depends(get_current_user)):
    """Return current organization's payroll week first_day. Default: 6 (Saturday)."""
    org = await db.organizations.find_one(
        {"id": user["org_id"]},
        {"_id": 0, "payroll_week": 1}
    )
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    payroll_week = org.get("payroll_week") or {}
    return {
        "first_day": payroll_week.get("first_day", 6),  # default Saturday
        "updated_at": payroll_week.get("updated_at"),
    }


# ── PUT payroll-week settings ─────────────────────────────────────
@router.put("/settings/payroll-week")
async def update_payroll_week(
    data: PayrollWeekSettings,
    user: dict = Depends(get_current_user),
):
    """
    Update organization's payroll week first_day. Admin/Owner only.
    Stored in organizations.payroll_week.first_day.
    """
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner can change payroll week")

    payroll_week = {
        "first_day": data.first_day,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": user["id"],
    }

    result = await db.organizations.update_one(
        {"id": user["org_id"]},
        {"$set": {"payroll_week": payroll_week}}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Organization not found")

    return {
        "first_day": payroll_week["first_day"],
        "updated_at": payroll_week["updated_at"],
    }


# ── Asset intake roles (кой може да заскладява) ───────────────────
class AssetIntakeRoles(BaseModel):
    technician: bool = False
    site_manager: bool = False


@router.get("/settings/asset-intake-roles")
async def get_asset_intake_roles(user: dict = Depends(get_current_user)):
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0, "asset_intake_roles": 1})
    roles = (org or {}).get("asset_intake_roles") or {}
    return {"technician": bool(roles.get("technician")), "site_manager": bool(roles.get("site_manager"))}


@router.put("/settings/asset-intake-roles")
async def update_asset_intake_roles(data: AssetIntakeRoles, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner can change this")
    await db.organizations.update_one(
        {"id": user["org_id"]},
        {"$set": {"asset_intake_roles": {"technician": data.technician, "site_manager": data.site_manager}}},
    )
    return {"technician": data.technician, "site_manager": data.site_manager}


# ── Workers see own pay (self-view toggle) ─────────────────────────
class WorkersSeePay(BaseModel):
    enabled: bool = False


@router.get("/settings/workers-see-pay")
async def get_workers_see_pay(user: dict = Depends(get_current_user)):
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0, "workers_see_pay": 1})
    return {"enabled": bool((org or {}).get("workers_see_pay"))}


@router.put("/settings/workers-see-pay")
async def update_workers_see_pay(data: WorkersSeePay, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner can change this")
    await db.organizations.update_one(
        {"id": user["org_id"]},
        {"$set": {"workers_see_pay": data.enabled}},
    )
    return {"enabled": data.enabled}


@router.get("/my-pay-summary")
async def my_pay_summary(user: dict = Depends(get_current_user)):
    """Worker self-view: owed (unpaid slips' period net) + payment history.
    Gated by the org 'workers_see_pay' setting; always own-scoped."""
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0, "workers_see_pay": 1})
    if not bool((org or {}).get("workers_see_pay")):
        raise HTTPException(status_code=403, detail="Disabled")
    slips = await db.payment_slips.find(
        {"org_id": user["org_id"], "employee_id": user["id"], "archived": {"$ne": True}},
        {"_id": 0},
    ).sort("created_at", -1).to_list(200)
    owed = 0.0
    out = []
    for s in slips:
        net_period = round(
            float(s.get("earned_amount") or 0)
            + float(s.get("bonuses_amount") or 0)
            - float(s.get("deductions_amount") or 0), 2
        )
        s["net_period"] = net_period
        if (s.get("status") or "") != "paid":
            owed += net_period
        out.append(s)
    return {"enabled": True, "currency": "EUR", "owed": round(owed, 2), "slips": out}
