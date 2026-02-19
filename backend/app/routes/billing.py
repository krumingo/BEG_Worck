"""
Routes - Billing & Subscription (M10) Endpoints.

IMPORTANT: Constants (SUBSCRIPTION_PLANS, MODULES, etc.) are temporarily imported from server.py.
After Stage 1.2 is complete, move them to app/core/billing_constants.py
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Optional
from datetime import datetime, timezone, timedelta
import uuid
import os
import stripe

# Temporary imports from server.py - move to core/billing_constants.py after refactor
from server import (
    SUBSCRIPTION_PLANS, MODULES, STRIPE_API_KEY, STRIPE_MOCK_MODE,
    LIMIT_WARNING_THRESHOLD, hash_password, create_token
)

from app.shared import db, get_current_user, log_audit
from app.models.billing import OrgSignupRequest, CreateCheckoutRequest

router = APIRouter(tags=["Billing"])

# Configure Stripe
stripe.api_key = STRIPE_API_KEY
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "https://beg-work-refactor.preview.emergentagent.com")


# ── Public Endpoints ───────────────────────────────────────────────

@router.get("/billing/plans")
async def list_billing_plans():
    """Public endpoint - list available plans"""
    return [
        {
            "id": plan_id,
            "name": plan["name"],
            "price": plan["price"],
            "allowed_modules": plan["allowed_modules"],
            "module_names": [MODULES[m]["name"] for m in plan["allowed_modules"] if m in MODULES],
            "limits": plan["limits"],
            "trial_days": plan.get("trial_days", 0),
            "description": plan.get("description", ""),
        }
        for plan_id, plan in SUBSCRIPTION_PLANS.items()
    ]


@router.get("/billing/config")
async def get_billing_config():
    """Get billing system configuration - used by frontend to show correct UI"""
    return {
        "stripe_mock_mode": STRIPE_MOCK_MODE,
        "stripe_configured": not STRIPE_MOCK_MODE,
        "required_env_vars": [
            {"name": "STRIPE_API_KEY", "configured": bool(os.environ.get("STRIPE_API_KEY")) and os.environ.get("STRIPE_API_KEY") != "sk_test_emergent"},
            {"name": "STRIPE_PRICE_ID_PRO", "configured": bool(os.environ.get("STRIPE_PRICE_ID_PRO"))},
            {"name": "STRIPE_PRICE_ID_ENTERPRISE", "configured": bool(os.environ.get("STRIPE_PRICE_ID_ENTERPRISE"))},
            {"name": "STRIPE_WEBHOOK_SECRET", "configured": bool(os.environ.get("STRIPE_WEBHOOK_SECRET"))},
        ]
    }


@router.post("/billing/signup")
async def signup_organization(data: OrgSignupRequest):
    """Public endpoint - create new organization with owner"""
    # Check if email already exists
    existing = await db.users.find_one({"email": data.owner_email.lower()})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    now = datetime.now(timezone.utc).isoformat()
    org_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    
    # Parse owner name into first_name and last_name
    name_parts = data.owner_name.strip().split(" ", 1)
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else ""
    
    # Create organization
    org = {
        "id": org_id,
        "name": data.org_name,
        "slug": data.org_name.lower().replace(" ", "-").replace("_", "-")[:50],
        "email": data.owner_email.lower(),
        "phone": "",
        "address": "",
        "logo_url": "",
        "vat_percent": 20.0,
        "attendance_start": "06:00",
        "attendance_end": "10:00",
        "work_report_deadline": "18:30",
        "max_reminders_per_day": 2,
        "escalation_after_days": 2,
        "org_timezone": "Europe/Sofia",
        "created_at": now,
        "updated_at": now,
    }
    await db.organizations.insert_one(org)
    
    # Create owner user
    user = {
        "id": user_id,
        "org_id": org_id,
        "email": data.owner_email.lower(),
        "password_hash": hash_password(data.password),
        "first_name": first_name,
        "last_name": last_name,
        "role": "Owner",
        "phone": "",
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    await db.users.insert_one(user)
    
    # Create subscription with free trial
    trial_ends = datetime.now(timezone.utc) + timedelta(days=SUBSCRIPTION_PLANS["free"]["trial_days"])
    subscription = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "plan_id": "free",
        "status": "trialing",
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
        "current_period_start": now,
        "current_period_end": trial_ends.isoformat(),
        "trial_ends_at": trial_ends.isoformat(),
        "created_at": now,
        "updated_at": now,
    }
    await db.subscriptions.insert_one(subscription)
    
    # Create default feature flags based on free plan
    free_modules = SUBSCRIPTION_PLANS["free"]["allowed_modules"]
    for mod_code in MODULES.keys():
        flag = {
            "id": str(uuid.uuid4()),
            "org_id": org_id,
            "module_code": mod_code,
            "module_name": MODULES[mod_code]["name"],
            "description": MODULES[mod_code]["description"],
            "enabled": mod_code in free_modules,
            "updated_at": now,
            "updated_by": user_id,
        }
        await db.feature_flags.insert_one(flag)
    
    # Create token for auto-login
    token = create_token({"user_id": user_id, "org_id": org_id, "role": "Owner"})
    
    await log_audit(org_id, user_id, data.owner_email, "signup", "organization", org_id, {"name": data.org_name})
    
    return {
        "token": token,
        "user": {
            "id": user_id,
            "first_name": first_name,
            "last_name": last_name,
            "email": data.owner_email.lower(),
            "role": "Owner",
            "org_id": org_id,
        },
        "organization": {
            "id": org_id,
            "name": data.org_name,
        },
        "subscription": {
            "plan_id": "free",
            "status": "trialing",
            "trial_ends_at": trial_ends.isoformat(),
            "days_remaining": SUBSCRIPTION_PLANS["free"]["trial_days"],
        }
    }


# ── Checkout & Portal ──────────────────────────────────────────────

@router.post("/billing/create-checkout-session")
async def create_checkout_session(data: CreateCheckoutRequest, user: dict = Depends(get_current_user)):
    """Create Stripe checkout session for plan upgrade"""
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin or Owner can manage billing")
    
    plan = SUBSCRIPTION_PLANS.get(data.plan_id)
    if not plan:
        raise HTTPException(status_code=400, detail="Invalid plan")
    
    if data.plan_id == "free":
        raise HTTPException(status_code=400, detail="Cannot checkout for free plan")
    
    org_id = user["org_id"]
    sub = await db.subscriptions.find_one({"org_id": org_id}, {"_id": 0})
    
    # MOCK MODE: Simulate successful checkout without real Stripe
    if STRIPE_MOCK_MODE:
        now = datetime.now(timezone.utc)
        mock_session_id = f"mock_cs_{str(uuid.uuid4())[:8]}"
        
        # Update subscription directly in mock mode
        period_end = now + timedelta(days=30)
        await db.subscriptions.update_one(
            {"org_id": org_id},
            {"$set": {
                "plan_id": data.plan_id,
                "status": "active",
                "stripe_customer_id": f"mock_cus_{org_id[:8]}",
                "stripe_subscription_id": f"mock_sub_{str(uuid.uuid4())[:8]}",
                "trial_ends_at": None,
                "current_period_start": now.isoformat(),
                "current_period_end": period_end.isoformat(),
                "updated_at": now.isoformat(),
            }}
        )
        
        # Update feature flags based on new plan
        allowed_modules = plan.get("allowed_modules", [])
        for mod_code in MODULES.keys():
            await db.feature_flags.update_one(
                {"org_id": org_id, "module_code": mod_code},
                {"$set": {"enabled": mod_code in allowed_modules}}
            )
        
        await log_audit(org_id, user["id"], user["email"], "checkout_mock", "billing", mock_session_id, {"plan_id": data.plan_id})
        
        return {
            "mock_mode": True,
            "checkout_url": f"{data.origin_url}/billing/success?session_id={mock_session_id}&mock=true",
            "session_id": mock_session_id,
            "message": "STRIPE_MOCK_MODE active. Subscription upgraded directly without payment.",
        }
    
    # REAL STRIPE MODE
    if not plan.get("stripe_price_id"):
        raise HTTPException(status_code=400, detail="This plan is not available for purchase (no Stripe price configured)")
    
    # Get or create Stripe customer
    customer_id = sub.get("stripe_customer_id") if sub else None
    if not customer_id:
        org = await db.organizations.find_one({"id": org_id}, {"_id": 0})
        try:
            customer = stripe.Customer.create(
                email=user["email"],
                name=org.get("name", ""),
                metadata={"org_id": org_id}
            )
            customer_id = customer.id
            await db.subscriptions.update_one(
                {"org_id": org_id},
                {"$set": {"stripe_customer_id": customer_id, "updated_at": datetime.now(timezone.utc).isoformat()}}
            )
        except stripe.error.StripeError as e:
            raise HTTPException(status_code=500, detail=f"Stripe error: {str(e)}")
    
    # Create checkout session
    success_url = f"{data.origin_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{data.origin_url}/billing/cancel"
    
    try:
        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[{
                "price": plan["stripe_price_id"],
                "quantity": 1,
            }],
            mode="subscription",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "org_id": org_id,
                "plan_id": data.plan_id,
            }
        )
        
        await log_audit(org_id, user["id"], user["email"], "checkout_started", "billing", session.id, {"plan_id": data.plan_id})
        
        return {"checkout_url": session.url, "session_id": session.id, "mock_mode": False}
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=500, detail=f"Stripe error: {str(e)}")


@router.post("/billing/create-portal-session")
async def create_portal_session(user: dict = Depends(get_current_user)):
    """Create Stripe customer portal session"""
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin or Owner can manage billing")
    
    sub = await db.subscriptions.find_one({"org_id": user["org_id"]}, {"_id": 0})
    
    # MOCK MODE
    if STRIPE_MOCK_MODE:
        return {
            "mock_mode": True,
            "portal_url": None,
            "message": "STRIPE_MOCK_MODE active. Customer portal not available. Manage subscription in app settings.",
        }
    
    if not sub or not sub.get("stripe_customer_id"):
        raise HTTPException(status_code=400, detail="No billing information found")
    
    try:
        session = stripe.billing_portal.Session.create(
            customer=sub["stripe_customer_id"],
            return_url=f"{APP_BASE_URL}/settings",
        )
        return {"portal_url": session.url, "mock_mode": False}
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=500, detail=f"Stripe error: {str(e)}")


# ── Webhook ────────────────────────────────────────────────────────

@router.post("/billing/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events"""
    import logging
    logger = logging.getLogger("server")
    
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    
    # Verify webhook signature in production
    if STRIPE_WEBHOOK_SECRET:
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid payload")
        except stripe.error.SignatureVerificationError:
            raise HTTPException(status_code=400, detail="Invalid signature")
    else:
        # Development mode - parse without verification
        import json
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON payload")
    
    event_type = event.get("type", "")
    data = event.get("data", {}).get("object", {})
    
    now = datetime.now(timezone.utc).isoformat()
    logger.info(f"Stripe webhook received: {event_type}")
    
    if event_type == "checkout.session.completed":
        org_id = data.get("metadata", {}).get("org_id")
        plan_id = data.get("metadata", {}).get("plan_id")
        customer_id = data.get("customer")
        subscription_id = data.get("subscription")
        
        if org_id and plan_id:
            plan = SUBSCRIPTION_PLANS.get(plan_id, {})
            await db.subscriptions.update_one(
                {"org_id": org_id},
                {"$set": {
                    "plan_id": plan_id,
                    "status": "active",
                    "stripe_customer_id": customer_id,
                    "stripe_subscription_id": subscription_id,
                    "trial_ends_at": None,
                    "updated_at": now,
                }}
            )
            # Update feature flags based on plan
            allowed_modules = plan.get("allowed_modules", [])
            for mod_code in MODULES.keys():
                await db.feature_flags.update_one(
                    {"org_id": org_id, "module_code": mod_code},
                    {"$set": {"enabled": mod_code in allowed_modules}}
                )
            logger.info(f"Subscription activated for org {org_id} with plan {plan_id}")
    
    elif event_type == "customer.subscription.updated":
        subscription_id = data.get("id")
        status = data.get("status")
        period_start = data.get("current_period_start")
        period_end = data.get("current_period_end")
        
        sub = await db.subscriptions.find_one({"stripe_subscription_id": subscription_id}, {"_id": 0})
        if sub:
            update_data = {"status": status, "updated_at": now}
            if period_start:
                update_data["current_period_start"] = datetime.fromtimestamp(period_start, tz=timezone.utc).isoformat()
            if period_end:
                update_data["current_period_end"] = datetime.fromtimestamp(period_end, tz=timezone.utc).isoformat()
            
            await db.subscriptions.update_one({"stripe_subscription_id": subscription_id}, {"$set": update_data})
            logger.info(f"Subscription {subscription_id} updated to status {status}")
    
    elif event_type == "customer.subscription.deleted":
        subscription_id = data.get("id")
        sub = await db.subscriptions.find_one({"stripe_subscription_id": subscription_id}, {"_id": 0})
        if sub:
            # Downgrade to free plan
            free_modules = SUBSCRIPTION_PLANS["free"]["allowed_modules"]
            await db.subscriptions.update_one(
                {"stripe_subscription_id": subscription_id},
                {"$set": {
                    "plan_id": "free",
                    "status": "canceled",
                    "stripe_subscription_id": None,
                    "updated_at": now,
                }}
            )
            for mod_code in MODULES.keys():
                await db.feature_flags.update_one(
                    {"org_id": sub["org_id"], "module_code": mod_code},
                    {"$set": {"enabled": mod_code in free_modules}}
                )
            logger.info(f"Subscription {subscription_id} canceled, downgraded to free")
    
    elif event_type == "invoice.payment_succeeded":
        subscription_id = data.get("subscription")
        if subscription_id:
            sub = await db.subscriptions.find_one({"stripe_subscription_id": subscription_id}, {"_id": 0})
            if sub and sub.get("status") == "past_due":
                await db.subscriptions.update_one(
                    {"stripe_subscription_id": subscription_id},
                    {"$set": {"status": "active", "updated_at": now}}
                )
                logger.info(f"Payment succeeded, subscription {subscription_id} reactivated")
    
    elif event_type == "invoice.payment_failed":
        subscription_id = data.get("subscription")
        if subscription_id:
            sub = await db.subscriptions.find_one({"stripe_subscription_id": subscription_id}, {"_id": 0})
            if sub:
                await db.subscriptions.update_one(
                    {"stripe_subscription_id": subscription_id},
                    {"$set": {"status": "past_due", "updated_at": now}}
                )
                logger.info(f"Payment failed, subscription {subscription_id} marked as past_due")
    
    return {"status": "received"}


# ── Subscription Info ──────────────────────────────────────────────

@router.get("/billing/subscription")
async def get_billing_subscription(user: dict = Depends(get_current_user)):
    """Get current subscription details with plan info and trial status"""
    sub = await db.subscriptions.find_one({"org_id": user["org_id"]}, {"_id": 0})
    if not sub:
        return None
    
    plan = SUBSCRIPTION_PLANS.get(sub.get("plan_id", "free"), SUBSCRIPTION_PLANS["free"])
    now = datetime.now(timezone.utc)
    
    # Calculate trial status
    trial_ends_at = sub.get("trial_ends_at")
    is_trial_active = False
    trial_days_remaining = 0
    trial_expired = False
    
    if trial_ends_at and sub.get("status") == "trialing":
        trial_end_dt = datetime.fromisoformat(trial_ends_at.replace("Z", "+00:00"))
        if now < trial_end_dt:
            is_trial_active = True
            trial_days_remaining = (trial_end_dt - now).days
        else:
            trial_expired = True
            # Auto-update status to past_due if trial expired
            await db.subscriptions.update_one(
                {"org_id": user["org_id"]},
                {"$set": {"status": "past_due", "updated_at": now.isoformat()}}
            )
            sub["status"] = "past_due"
    
    return {
        **sub,
        "plan": {
            "id": sub.get("plan_id", "free"),
            "name": plan["name"],
            "price": plan["price"],
            "allowed_modules": plan["allowed_modules"],
            "limits": plan["limits"],
            "description": plan.get("description", ""),
        },
        "trial_active": is_trial_active,
        "trial_days_remaining": trial_days_remaining,
        "trial_expired": trial_expired,
        "stripe_mock_mode": STRIPE_MOCK_MODE,
    }


@router.get("/billing/check-module/{module_code}")
async def check_module_access(module_code: str, user: dict = Depends(get_current_user)):
    """Check if current subscription allows access to a module - SERVER-SIDE ENFORCEMENT"""
    sub = await db.subscriptions.find_one({"org_id": user["org_id"]}, {"_id": 0})
    if not sub:
        return {"allowed": False, "reason": "No subscription"}
    
    plan = SUBSCRIPTION_PLANS.get(sub.get("plan_id", "free"), SUBSCRIPTION_PLANS["free"])
    
    # Check trial expiration
    status = sub.get("status", "")
    trial_ends_at = sub.get("trial_ends_at")
    
    if status == "trialing" and trial_ends_at:
        now = datetime.now(timezone.utc)
        trial_end_dt = datetime.fromisoformat(trial_ends_at.replace("Z", "+00:00"))
        if now >= trial_end_dt:
            # Trial expired - update status and restrict to free modules
            await db.subscriptions.update_one(
                {"org_id": user["org_id"]},
                {"$set": {"status": "past_due", "updated_at": now.isoformat()}}
            )
            status = "past_due"
    
    # Check if subscription is active or trialing
    if status in ["canceled", "past_due", "incomplete"]:
        # Allow core read-only access for past_due (keeping minimal functionality)
        if module_code == "M0":
            return {"allowed": True, "reason": None, "limited": True}
        return {"allowed": False, "reason": f"Subscription {status}. Please upgrade your plan."}
    
    allowed = module_code in plan["allowed_modules"]
    return {"allowed": allowed, "reason": None if allowed else "Module not in your current plan. Please upgrade."}


# ── Usage Tracking ─────────────────────────────────────────────────

async def compute_org_usage(org_id: str) -> dict:
    """Compute current usage counts for an organization"""
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    # Count users
    users_count = await db.users.count_documents({"org_id": org_id, "is_active": True})
    
    # Count projects (active only)
    projects_count = await db.projects.count_documents({"org_id": org_id, "status": {"$ne": "Archived"}})
    
    # Count invoices created this month
    invoices_count = await db.invoices.count_documents({
        "org_id": org_id,
        "created_at": {"$gte": month_start.isoformat()}
    })
    
    # Storage placeholder (would need actual file storage tracking)
    storage_used_mb = 0
    
    return {
        "users_count": users_count,
        "projects_count": projects_count,
        "invoices_count_monthly": invoices_count,
        "storage_used_mb": storage_used_mb,
        "computed_at": now.isoformat(),
        "month_start": month_start.isoformat(),
    }


async def check_limit(org_id: str, resource: str, increment: int = 1) -> dict:
    """Check if adding `increment` items would exceed the plan limit."""
    sub = await db.subscriptions.find_one({"org_id": org_id}, {"_id": 0})
    if not sub:
        return {"allowed": False, "error_code": "NO_SUBSCRIPTION", "current": 0, "limit": 0, "warning": False}
    
    plan = SUBSCRIPTION_PLANS.get(sub.get("plan_id", "free"), SUBSCRIPTION_PLANS["free"])
    limits = plan.get("limits", {})
    
    # Map resource to limit key and count function
    resource_map = {
        "users": ("users", lambda: db.users.count_documents({"org_id": org_id, "is_active": True})),
        "projects": ("projects", lambda: db.projects.count_documents({"org_id": org_id, "status": {"$ne": "Archived"}})),
        "invoices": ("monthly_invoices", None),
    }
    
    if resource not in resource_map:
        return {"allowed": True, "error_code": None, "current": 0, "limit": 0, "warning": False}
    
    limit_key, count_fn = resource_map[resource]
    limit = limits.get(limit_key, -1)
    
    # Get current count
    if resource == "invoices":
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        current = await db.invoices.count_documents({
            "org_id": org_id,
            "created_at": {"$gte": month_start.isoformat()}
        })
    else:
        current = await count_fn()
    
    # Check limit
    would_exceed = (current + increment) > limit
    warning = (current / limit) >= LIMIT_WARNING_THRESHOLD if limit > 0 else False
    
    error_code = None
    if would_exceed:
        error_code = f"LIMIT_{resource.upper()}_EXCEEDED"
    
    return {
        "allowed": not would_exceed,
        "error_code": error_code,
        "current": current,
        "limit": limit,
        "warning": warning,
        "percent": round((current / limit) * 100, 1) if limit > 0 else 0,
    }


async def enforce_limit(org_id: str, resource: str, increment: int = 1):
    """Enforce limit - raises HTTPException if limit exceeded"""
    result = await check_limit(org_id, resource, increment)
    if not result["allowed"]:
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": result["error_code"],
                "current": result["current"],
                "limit": result["limit"],
                "message": f"Plan limit exceeded for {resource}. Current: {result['current']}, Limit: {result['limit']}",
            }
        )
    return result


@router.get("/billing/usage")
async def get_billing_usage(user: dict = Depends(get_current_user)):
    """Get current usage vs plan limits with percentages and warnings"""
    org_id = user["org_id"]
    
    sub = await db.subscriptions.find_one({"org_id": org_id}, {"_id": 0})
    if not sub:
        raise HTTPException(status_code=404, detail="No subscription found")
    
    plan = SUBSCRIPTION_PLANS.get(sub.get("plan_id", "free"), SUBSCRIPTION_PLANS["free"])
    limits = plan.get("limits", {})
    
    # Compute current usage
    usage = await compute_org_usage(org_id)
    
    # Build usage breakdown with limits and warnings
    usage_items = []
    
    for key, limit_key, label in [
        ("users_count", "users", "users"),
        ("projects_count", "projects", "projects"),
        ("invoices_count_monthly", "monthly_invoices", "invoices"),
        ("storage_used_mb", "storage_mb", "storage"),
    ]:
        current = usage.get(key, 0)
        limit = limits.get(limit_key, 0)
        percent = round((current / limit) * 100, 1) if limit > 0 else 0
        warning = percent >= (LIMIT_WARNING_THRESHOLD * 100)
        exceeded = current >= limit
        
        usage_items.append({
            "resource": label,
            "current": current,
            "limit": limit,
            "percent": percent,
            "warning": warning,
            "exceeded": exceeded,
            "unit": "MB" if label == "storage" else "",
        })
    
    return {
        "plan_id": sub.get("plan_id", "free"),
        "plan_name": plan["name"],
        "usage": usage_items,
        "computed_at": usage["computed_at"],
        "month_start": usage["month_start"],
        "warning_threshold": LIMIT_WARNING_THRESHOLD * 100,
    }
