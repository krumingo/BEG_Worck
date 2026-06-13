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
