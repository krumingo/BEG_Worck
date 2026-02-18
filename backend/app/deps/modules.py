"""
Module access and subscription dependencies.
"""
from fastapi import Depends, HTTPException
from datetime import datetime, timezone
import os

from app.db import db
from app.deps.auth import get_current_user

# Subscription Plans Configuration
SUBSCRIPTION_PLANS = {
    "free": {
        "name": "Free Trial",
        "price": 0,
        "stripe_price_id": None,
        "allowed_modules": ["M0", "M1", "M3"],
        "limits": {
            "users": 3,
            "projects": 2,
            "monthly_invoices": 5,
            "storage_mb": 100
        },
        "trial_days": 14,
        "description": "14-day trial with basic features",
    },
    "pro": {
        "name": "Professional",
        "price": 49.00,
        "stripe_price_id": os.environ.get("STRIPE_PRICE_ID_PRO"),
        "allowed_modules": ["M0", "M1", "M2", "M3", "M4", "M5", "M9"],
        "limits": {
            "users": 20,
            "projects": 50,
            "monthly_invoices": 500,
            "storage_mb": 2000
        },
        "trial_days": 0,
        "description": "Full access to all features",
    },
    "enterprise": {
        "name": "Enterprise",
        "price": 149.00,
        "stripe_price_id": os.environ.get("STRIPE_PRICE_ID_ENTERPRISE"),
        "allowed_modules": ["M0", "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9"],
        "limits": {
            "users": 100,
            "projects": 500,
            "monthly_invoices": 5000,
            "storage_mb": 20000
        },
        "trial_days": 0,
        "description": "Unlimited users and premium support",
        "support_priority": "priority",
        "custom_integrations": True,
    }
}

LIMIT_WARNING_THRESHOLD = 0.8
SUBSCRIPTION_STATUSES = ["trialing", "active", "past_due", "canceled", "incomplete"]

async def check_module_access_for_org(org_id: str, module_code: str) -> tuple:
    """Check if an organization has access to a module based on their subscription."""
    sub = await db.subscriptions.find_one({"org_id": org_id}, {"_id": 0})
    if not sub:
        return False, "No subscription"
    
    plan = SUBSCRIPTION_PLANS.get(sub.get("plan_id", "free"), SUBSCRIPTION_PLANS["free"])
    status = sub.get("status", "")
    trial_ends_at = sub.get("trial_ends_at")
    
    if status == "trialing" and trial_ends_at:
        now = datetime.now(timezone.utc)
        try:
            trial_end_dt = datetime.fromisoformat(trial_ends_at.replace("Z", "+00:00"))
            if now >= trial_end_dt:
                await db.subscriptions.update_one(
                    {"org_id": org_id},
                    {"$set": {"status": "past_due", "updated_at": now.isoformat()}}
                )
                status = "past_due"
        except (ValueError, TypeError):
            pass
    
    if status in ["canceled", "past_due", "incomplete"]:
        if module_code == "M0":
            return True, None
        return False, f"Subscription {status}. Please upgrade your plan."
    
    allowed = module_code in plan["allowed_modules"]
    return allowed, None if allowed else "Module not in your current plan"

async def require_module(module_code: str, user: dict) -> dict:
    """Enforce module access for a user's organization."""
    allowed, reason = await check_module_access_for_org(user["org_id"], module_code)
    if not allowed:
        raise HTTPException(status_code=403, detail=reason or f"Module {module_code} not available")
    return user

async def require_m2(user: dict = Depends(get_current_user)):
    return await require_module("M2", user)

async def require_m4(user: dict = Depends(get_current_user)):
    return await require_module("M4", user)

async def require_m5(user: dict = Depends(get_current_user)):
    return await require_module("M5", user)

async def require_m9(user: dict = Depends(get_current_user)):
    return await require_module("M9", user)

async def get_plan_limits(org_id: str) -> dict:
    """Get the limits for an organization's current plan."""
    sub = await db.subscriptions.find_one({"org_id": org_id}, {"_id": 0})
    if not sub:
        return SUBSCRIPTION_PLANS["free"]["limits"]
    plan = SUBSCRIPTION_PLANS.get(sub.get("plan_id", "free"), SUBSCRIPTION_PLANS["free"])
    return plan.get("limits", SUBSCRIPTION_PLANS["free"]["limits"])

async def enforce_limit(org_id: str, resource_type: str):
    """Enforce usage limits for creating resources."""
    limits = await get_plan_limits(org_id)
    
    if resource_type == "users":
        count = await db.users.count_documents({"org_id": org_id})
        limit = limits.get("users", 3)
        if count >= limit:
            raise HTTPException(
                status_code=403,
                detail={"code": "LIMIT_USERS_EXCEEDED", "message": f"User limit ({limit}) reached. Please upgrade your plan."}
            )
    elif resource_type == "projects":
        count = await db.projects.count_documents({"org_id": org_id})
        limit = limits.get("projects", 2)
        if count >= limit:
            raise HTTPException(
                status_code=403,
                detail={"code": "LIMIT_PROJECTS_EXCEEDED", "message": f"Project limit ({limit}) reached. Please upgrade your plan."}
            )
    elif resource_type == "invoices":
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        count = await db.invoices.count_documents({"org_id": org_id, "created_at": {"$gte": month_start}})
        limit = limits.get("monthly_invoices", 5)
        if count >= limit:
            raise HTTPException(
                status_code=403,
                detail={"code": "LIMIT_INVOICES_EXCEEDED", "message": f"Monthly invoice limit ({limit}) reached. Please upgrade your plan."}
            )
