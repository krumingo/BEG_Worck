"""
Routes - Billing & Subscription (M10) Endpoints.

IMPORTANT: Constants (SUBSCRIPTION_PLANS, MODULES, etc.) are temporarily imported from server.py.
After Stage 1.2 is complete, move them to app/core/billing_constants.py

R0-01 (AUD-009 / AUD-045, FLOW-050):
* The Stripe webhook fails closed: no ``STRIPE_WEBHOOK_SECRET`` -> 503 and no
  write; the signature is always verified by ``stripe.Webhook.construct_event``.
* The tenant of a webhook event is resolved from a record BEG_Work wrote itself
  (``billing_checkout_sessions`` for a checkout, ``subscriptions`` for a Stripe
  subscription id) and cross-checked against the event's customer and
  ``metadata.org_id``. Any mismatch writes nothing and logs a security event.
* Every processed event id is claimed once in ``billing_webhook_events``
  (unique index), so a replayed event is a 200 no-op.
* Mock billing runs only when ``app.core.stripe_config.billing_mode()`` says so
  (``BILLING_PROVIDER=mock`` and ``ENV`` development/test). Outside mock the
  plan changes only from a verified webhook; checkout and the portal are
  Owner/Admin only.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Optional
from datetime import datetime, timezone, timedelta
import logging
import uuid
import os
import stripe
from pymongo.errors import DuplicateKeyError

from app.core.stripe_config import (
    STRIPE_API_KEY, BILLING_MODE_MOCK, BILLING_MODE_STRIPE, BILLING_MODE_UNCONFIGURED,
    billing_mode, stripe_webhook_secret,
)

from app.db import db
from app.deps.auth import get_current_user, require_admin, require_platform_admin, hash_password, create_token
from app.deps.modules import SUBSCRIPTION_PLANS, LIMIT_WARNING_THRESHOLD
from app.utils.audit import log_audit, log_security_event
from app.constants import MODULES
from app.models.billing import OrgSignupRequest, CreateCheckoutRequest
from app.tenancy.data_access import TenantData, resolve_owner_by_unique_key


def _tenant(user: dict) -> TenantData:
    """The request's tenant — from the server-loaded session user only (W0-03E-A2C)."""
    return TenantData.for_user(db, user)

router = APIRouter(tags=["Billing"])
logger = logging.getLogger("server")

# Configure Stripe
stripe.api_key = STRIPE_API_KEY
# APP_BASE_URL is required for Stripe redirects - must be set in environment
APP_BASE_URL = os.environ.get("APP_BASE_URL", "")

BILLING_NOT_CONFIGURED = "Billing is not configured. The plan was not changed. Contact the administrator."


async def _ensure_billing_indexes():
    """The unique keys the webhook relies on (idempotent; cheap when present).

    ``stripe_event_id`` makes a replay a duplicate-key no-op; ``stripe_session_id``
    makes the checkout record resolve exactly one tenant.
    """
    await db.billing_webhook_events.create_index("stripe_event_id", unique=True)
    await db.billing_checkout_sessions.create_index("stripe_session_id", unique=True)


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
async def get_billing_config(user: dict = Depends(require_platform_admin)):
    """
    Get billing system configuration - used by frontend to show correct UI.
    
    SECURITY: This endpoint is restricted to platform administrators only.
    Contains sensitive Stripe configuration status.
    """
    mode = billing_mode()
    return {
        "billing_mode": mode,
        "billing_configured": mode != BILLING_MODE_UNCONFIGURED,
        "stripe_mock_mode": mode == BILLING_MODE_MOCK,
        "stripe_configured": mode == BILLING_MODE_STRIPE,
        "required_env_vars": [
            {"name": "STRIPE_API_KEY", "configured": bool(os.environ.get("STRIPE_API_KEY")) and os.environ.get("STRIPE_API_KEY") != "sk_test_emergent"},
            {"name": "STRIPE_PRICE_ID_PRO", "configured": bool(os.environ.get("STRIPE_PRICE_ID_PRO"))},
            {"name": "STRIPE_PRICE_ID_ENTERPRISE", "configured": bool(os.environ.get("STRIPE_PRICE_ID_ENTERPRISE"))},
            {"name": "STRIPE_WEBHOOK_SECRET", "configured": bool(stripe_webhook_secret())},
        ]
    }


@router.post("/billing/signup")
async def signup_organization(data: OrgSignupRequest):
    """Public endpoint - create new organization with owner"""
    # W0-03E-A2B: the canonical tenant onboarding path. It generates the tenant
    # id server-side, writes the organization and the owner stamped with it,
    # and registers the tenant (registry + membership + owner assignment), so a
    # new company is never invisible to the Tenant Guard and never mistaken for
    # the legacy BEG installation by the one-time backfill rule.
    from app.tenancy import registry as tenant_registry_mod
    from app.tenancy.onboarding import OnboardingRefused, onboard_tenant

    now = datetime.now(timezone.utc).isoformat()

    # Parse owner name into first_name and last_name
    name_parts = data.owner_name.strip().split(" ", 1)
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    try:
        created = await onboard_tenant(
            db, tenant_registry_mod.system_db, org_name=data.org_name,
            owner_email=data.owner_email, owner_password_hash=hash_password(data.password),
            owner_first_name=first_name, owner_last_name=last_name, owner_role="Owner",
            organization_extra={
                "attendance_start": "06:00", "attendance_end": "10:00",
                "work_report_deadline": "18:30", "max_reminders_per_day": 2,
                "escalation_after_days": 2})
    except OnboardingRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    org_id = created["tenant"]["id"]
    user_id = created["owner"]["id"]

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
async def create_checkout_session(data: CreateCheckoutRequest, user: dict = Depends(require_admin)):
    """
    Create Stripe checkout session for plan upgrade.

    Owner/Admin only (R0-01). Outside mock this only creates the Stripe
    session; the plan changes when the signed webhook confirms it.
    """
    tenant = _tenant(user)

    plan = SUBSCRIPTION_PLANS.get(data.plan_id)
    if not plan:
        raise HTTPException(status_code=400, detail="Invalid plan")

    if data.plan_id == "free":
        raise HTTPException(status_code=400, detail="Cannot checkout for free plan")

    mode = billing_mode()
    if mode == BILLING_MODE_UNCONFIGURED:
        logger.warning("Checkout refused: billing is not configured (no Stripe config, mock not allowed)")
        raise HTTPException(status_code=503, detail=BILLING_NOT_CONFIGURED)

    org_id = user["org_id"]
    sub = await tenant.subscriptions.find_one({"org_id": org_id}, {"_id": 0})

    # MOCK MODE (BILLING_PROVIDER=mock in ENV development/test only):
    # simulate a successful checkout without real Stripe
    if mode == BILLING_MODE_MOCK:
        now = datetime.now(timezone.utc)
        mock_session_id = f"mock_cs_{str(uuid.uuid4())[:8]}"
        
        # Update subscription directly in mock mode
        period_end = now + timedelta(days=30)
        await tenant.subscriptions.update_one(
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
            await tenant.feature_flags.update_one(
                {"org_id": org_id, "module_code": mod_code},
                {"$set": {"enabled": mod_code in allowed_modules}}
            )
        
        await log_audit(org_id, user["id"], user["email"], "checkout_mock", "billing", mock_session_id, {"plan_id": data.plan_id})
        
        return {
            "mock_mode": True,
            "checkout_url": f"{data.origin_url}/billing/success?session_id={mock_session_id}&mock=true",
            "session_id": mock_session_id,
            "message": "Mock billing active (BILLING_PROVIDER=mock). Subscription upgraded directly without payment.",
        }
    
    # REAL STRIPE MODE
    if not plan.get("stripe_price_id"):
        raise HTTPException(status_code=400, detail="This plan is not available for purchase (no Stripe price configured)")
    
    # Get or create Stripe customer
    customer_id = sub.get("stripe_customer_id") if sub else None
    if not customer_id:
        org = await tenant.own_organization({"_id": 0})
        try:
            customer = stripe.Customer.create(
                email=user["email"],
                name=org.get("name", ""),
                metadata={"org_id": org_id}
            )
            customer_id = customer.id
            await tenant.subscriptions.update_one(
                {"org_id": org_id},
                {"$set": {"stripe_customer_id": customer_id, "updated_at": datetime.now(timezone.utc).isoformat()}}
            )
        except stripe.error.StripeError as e:
            raise HTTPException(status_code=500, detail=f"Stripe error: {str(e)}")
    
    # Validate origin_url for security
    if not data.origin_url or not data.origin_url.startswith(("https://", "http://localhost")):
        raise HTTPException(status_code=400, detail="Invalid or missing origin_url")
    
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
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=500, detail=f"Stripe error: {str(e)}")

    # R0-01: the BEG_Work-side record the webhook resolves the tenant from.
    # metadata.org_id above is only a cross-check, never the source.
    await _ensure_billing_indexes()
    await tenant.billing_checkout_sessions.insert_one({
        "id": str(uuid.uuid4()),
        "stripe_session_id": session.id,
        "stripe_customer_id": customer_id,
        "plan_id": data.plan_id,
        "status": "open",
        "created_by": user["id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    await log_audit(org_id, user["id"], user["email"], "checkout_started", "billing", session.id, {"plan_id": data.plan_id})

    return {"checkout_url": session.url, "session_id": session.id, "mock_mode": False}


@router.post("/billing/create-portal-session")
async def create_portal_session(user: dict = Depends(require_admin)):
    """
    Create Stripe customer portal session.

    Owner/Admin only (R0-01).
    """
    tenant = _tenant(user)

    mode = billing_mode()
    if mode == BILLING_MODE_UNCONFIGURED:
        raise HTTPException(status_code=503, detail=BILLING_NOT_CONFIGURED)

    sub = await tenant.subscriptions.find_one({"org_id": user["org_id"]}, {"_id": 0})

    # MOCK MODE
    if mode == BILLING_MODE_MOCK:
        return {
            "mock_mode": True,
            "portal_url": None,
            "message": "Mock billing active. Customer portal not available. Manage subscription in app settings.",
        }
    
    if not sub or not sub.get("stripe_customer_id"):
        raise HTTPException(status_code=400, detail="No billing information found")
    
    # Ensure APP_BASE_URL is configured for production
    if not APP_BASE_URL:
        raise HTTPException(status_code=500, detail="APP_BASE_URL not configured. Contact administrator.")
    
    try:
        session = stripe.billing_portal.Session.create(
            customer=sub["stripe_customer_id"],
            return_url=f"{APP_BASE_URL}/settings",
        )
        return {"portal_url": session.url, "mock_mode": False}
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=500, detail=f"Stripe error: {str(e)}")


# ── Webhook ────────────────────────────────────────────────────────

def _webhook_security_event(reason: str, event_id: str, event_type: str, org_id: str = None):
    """A refused webhook event. Ids and the reason only — never the payload."""
    log_security_event("BILLING_WEBHOOK_REJECTED", None, {
        "action": event_type, "reason": reason,
        "context_type": "stripe_event", "context_id": event_id,
        "target_context_type": "org", "target_context_id": org_id,
    })


async def _resolve_checkout_completed(event_id: str, event_type: str, obj):
    """``checkout.session.completed`` -> the tenant whose OWN checkout record it is.

    The session id must match a ``billing_checkout_sessions`` row BEG_Work wrote
    at checkout. That row fixes the tenant, the customer and the plan; the
    event's ``customer``, ``metadata.org_id`` and ``metadata.plan_id`` must agree
    with it, or nothing is written.
    """
    session_id = obj.get("id")
    customer_id = obj.get("customer")
    metadata = obj.get("metadata") or {}
    tenant, record = await resolve_owner_by_unique_key(
        db, "billing_checkout_sessions", "stripe_session_id", session_id, {"_id": 0})
    if record is None:
        _webhook_security_event("no BEG_Work checkout record for this session", event_id, event_type)
        return None, None

    plan_id = record.get("plan_id")
    reasons = []
    if metadata.get("org_id") != tenant.org_id:
        reasons.append("metadata.org_id does not match the checkout record")
    if not customer_id or customer_id != record.get("stripe_customer_id"):
        reasons.append("customer does not match the checkout record")
    if metadata.get("plan_id") not in (None, plan_id):
        reasons.append("metadata.plan_id does not match the checkout record")
    if plan_id not in SUBSCRIPTION_PLANS or plan_id == "free":
        reasons.append("checkout record has no purchasable plan")
    sub = await tenant.subscriptions.find_one({"org_id": tenant.org_id}, {"_id": 0})
    if not sub:
        reasons.append("tenant has no subscription row")
    elif sub.get("stripe_customer_id") not in (None, customer_id):
        reasons.append("customer does not match the tenant's subscription")
    if reasons:
        _webhook_security_event("; ".join(reasons), event_id, event_type, tenant.org_id)
        return None, None
    return tenant, {"session_id": session_id, "plan_id": plan_id, "customer_id": customer_id,
                    "subscription_id": obj.get("subscription")}


async def _resolve_by_subscription(event_id: str, event_type: str, subscription_id, customer_id):
    """A Stripe subscription id -> the ONE tenant whose subscription row carries it,
    and only if the event's customer is that row's customer."""
    tenant, sub = await resolve_owner_by_unique_key(
        db, "subscriptions", "stripe_subscription_id", subscription_id, {"_id": 0})
    if sub is None:
        _webhook_security_event("subscription id resolves to no single tenant", event_id, event_type)
        return None, None
    if not customer_id or customer_id != sub.get("stripe_customer_id"):
        _webhook_security_event("customer does not match the tenant's subscription",
                                event_id, event_type, tenant.org_id)
        return None, None
    return tenant, {"subscription_id": subscription_id, "sub": sub}


async def _resolve_subscription_object(event_id, event_type, obj):
    return await _resolve_by_subscription(event_id, event_type, obj.get("id"), obj.get("customer"))


async def _resolve_invoice_object(event_id, event_type, obj):
    return await _resolve_by_subscription(event_id, event_type, obj.get("subscription"), obj.get("customer"))


async def _apply_checkout_completed(tenant: TenantData, ctx: dict, obj, now: str):
    plan = SUBSCRIPTION_PLANS[ctx["plan_id"]]
    await tenant.subscriptions.update_one(
        {"org_id": tenant.org_id},
        {"$set": {
            "plan_id": ctx["plan_id"],
            "status": "active",
            "stripe_customer_id": ctx["customer_id"],
            "stripe_subscription_id": ctx["subscription_id"],
            "trial_ends_at": None,
            "updated_at": now,
        }}
    )
    # Update feature flags based on plan
    allowed_modules = plan.get("allowed_modules", [])
    for mod_code in MODULES.keys():
        await tenant.feature_flags.update_one(
            {"org_id": tenant.org_id, "module_code": mod_code},
            {"$set": {"enabled": mod_code in allowed_modules}}
        )
    await tenant.billing_checkout_sessions.update_one(
        {"stripe_session_id": ctx["session_id"]},
        {"$set": {"status": "completed", "completed_at": now}})
    logger.info(f"Subscription activated for org {tenant.org_id} with plan {ctx['plan_id']}")


async def _apply_subscription_updated(tenant: TenantData, ctx: dict, obj, now: str):
    subscription_id = ctx["subscription_id"]
    status = obj.get("status")
    period_start = obj.get("current_period_start")
    period_end = obj.get("current_period_end")
    update_data = {"status": status, "updated_at": now}
    if period_start:
        update_data["current_period_start"] = datetime.fromtimestamp(period_start, tz=timezone.utc).isoformat()
    if period_end:
        update_data["current_period_end"] = datetime.fromtimestamp(period_end, tz=timezone.utc).isoformat()
    await tenant.subscriptions.update_one(
        {"stripe_subscription_id": subscription_id}, {"$set": update_data})
    logger.info(f"Subscription {subscription_id} updated to status {status}")


async def _apply_subscription_deleted(tenant: TenantData, ctx: dict, obj, now: str):
    subscription_id = ctx["subscription_id"]
    # Downgrade to free plan
    free_modules = SUBSCRIPTION_PLANS["free"]["allowed_modules"]
    await tenant.subscriptions.update_one(
        {"stripe_subscription_id": subscription_id},
        {"$set": {
            "plan_id": "free",
            "status": "canceled",
            "stripe_subscription_id": None,
            "updated_at": now,
        }}
    )
    for mod_code in MODULES.keys():
        await tenant.feature_flags.update_one(
            {"module_code": mod_code},
            {"$set": {"enabled": mod_code in free_modules}}
        )
    logger.info(f"Subscription {subscription_id} canceled, downgraded to free")


async def _apply_payment_succeeded(tenant: TenantData, ctx: dict, obj, now: str):
    subscription_id = ctx["subscription_id"]
    if ctx["sub"].get("status") == "past_due":
        await tenant.subscriptions.update_one(
            {"stripe_subscription_id": subscription_id},
            {"$set": {"status": "active", "updated_at": now}}
        )
        logger.info(f"Payment succeeded, subscription {subscription_id} reactivated")


async def _apply_payment_failed(tenant: TenantData, ctx: dict, obj, now: str):
    subscription_id = ctx["subscription_id"]
    await tenant.subscriptions.update_one(
        {"stripe_subscription_id": subscription_id},
        {"$set": {"status": "past_due", "updated_at": now}}
    )
    logger.info(f"Payment failed, subscription {subscription_id} marked as past_due")


#: event type -> (tenant resolver, effect). Any other type is acknowledged, unwritten.
_WEBHOOK_HANDLERS = {
    "checkout.session.completed": (_resolve_checkout_completed, _apply_checkout_completed),
    "customer.subscription.updated": (_resolve_subscription_object, _apply_subscription_updated),
    "customer.subscription.deleted": (_resolve_subscription_object, _apply_subscription_deleted),
    "invoice.payment_succeeded": (_resolve_invoice_object, _apply_payment_succeeded),
    "invoice.payment_failed": (_resolve_invoice_object, _apply_payment_failed),
}


async def _claim_event(tenant: TenantData, event_id: str, event_type: str, now: str) -> bool:
    """Claim a Stripe event id once. False = already processed (or in progress).

    The unique index on ``stripe_event_id`` decides, so two concurrent deliveries
    of one event cannot both pass. An attempt that failed half-way is marked
    ``failed`` and may be re-claimed by Stripe's next retry.
    """
    await _ensure_billing_indexes()
    try:
        await tenant.billing_webhook_events.insert_one({
            "id": str(uuid.uuid4()),
            "stripe_event_id": event_id,
            "event_type": event_type,
            "status": "processing",
            "attempts": 1,
            "received_at": now,
        })
        return True
    except DuplicateKeyError:
        pass
    reclaimed = await tenant.billing_webhook_events.find_one_and_update(
        {"stripe_event_id": event_id, "status": "failed"},
        {"$set": {"status": "processing", "received_at": now}, "$inc": {"attempts": 1}})
    return reclaimed is not None


@router.post("/billing/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events — signed, tenant-resolved server-side, once."""
    secret = stripe_webhook_secret()
    if not secret:
        logger.warning("Stripe webhook refused: STRIPE_WEBHOOK_SECRET is not configured")
        raise HTTPException(status_code=503, detail="Billing webhook is not configured")
    
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing signature")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    event_id = event.get("id")
    event_type = event.get("type") or ""
    obj = (event.get("data") or {}).get("object") or {}
    if not isinstance(event_id, str) or not event_id:
        raise HTTPException(status_code=400, detail="Invalid payload")
    logger.info(f"Stripe webhook received: {event_type} {event_id}")
    
    handler = _WEBHOOK_HANDLERS.get(event_type)
    if handler is None:
        return {"status": "ignored"}
    resolve, apply = handler
    
    tenant, ctx = await resolve(event_id, event_type, obj)
    if tenant is None:
        # Refused (already security-logged). 2xx so Stripe does not retry a
        # forged or foreign event forever; nothing was written.
        return {"status": "rejected"}
    
    now = datetime.now(timezone.utc).isoformat()
    if not await _claim_event(tenant, event_id, event_type, now):
        logger.info(f"Stripe webhook {event_id} already processed; no-op")
        return {"status": "duplicate"}
    
    try:
        await apply(tenant, ctx, obj, now)
    except Exception:
        logger.exception(f"Stripe webhook {event_id} ({event_type}) failed")
        await tenant.billing_webhook_events.update_one(
            {"stripe_event_id": event_id},
            {"$set": {"status": "failed", "failed_at": datetime.now(timezone.utc).isoformat()}})
        raise HTTPException(status_code=500, detail="Webhook processing failed")
    
    await tenant.billing_webhook_events.update_one(
        {"stripe_event_id": event_id},
        {"$set": {"status": "processed", "processed_at": datetime.now(timezone.utc).isoformat()}})
    return {"status": "received"}


# ── Subscription Info ──────────────────────────────────────────────

@router.get("/billing/subscription")
async def get_billing_subscription(user: dict = Depends(get_current_user)):
    """Get current subscription details with plan info and trial status"""
    tenant = _tenant(user)
    sub = await tenant.subscriptions.find_one({"org_id": user["org_id"]}, {"_id": 0})
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
            await tenant.subscriptions.update_one(
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
        "stripe_mock_mode": billing_mode() == BILLING_MODE_MOCK,
    }


@router.get("/billing/check-module/{module_code}")
async def check_module_access(module_code: str, user: dict = Depends(get_current_user)):
    """Check if current subscription allows access to a module - SERVER-SIDE ENFORCEMENT"""
    tenant = _tenant(user)
    sub = await tenant.subscriptions.find_one({"org_id": user["org_id"]}, {"_id": 0})
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
            await tenant.subscriptions.update_one(
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
    tenant = TenantData.for_resolved_org(db, org_id)
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    # Count users
    users_count = await tenant.users.count_documents({"org_id": org_id, "is_active": True})
    
    # Count projects (active only)
    projects_count = await tenant.projects.count_documents({"org_id": org_id, "status": {"$ne": "Archived"}})
    
    # Count invoices created this month
    invoices_count = await tenant.invoices.count_documents({
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
    tenant = TenantData.for_resolved_org(db, org_id)
    sub = await tenant.subscriptions.find_one({"org_id": org_id}, {"_id": 0})
    if not sub:
        return {"allowed": False, "error_code": "NO_SUBSCRIPTION", "current": 0, "limit": 0, "warning": False}
    
    plan = SUBSCRIPTION_PLANS.get(sub.get("plan_id", "free"), SUBSCRIPTION_PLANS["free"])
    limits = plan.get("limits", {})
    
    # Map resource to limit key and count function
    resource_map = {
        "users": ("users", lambda: tenant.users.count_documents({"org_id": org_id, "is_active": True})),
        "projects": ("projects", lambda: tenant.projects.count_documents({"org_id": org_id, "status": {"$ne": "Archived"}})),
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
        current = await tenant.invoices.count_documents({
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
    tenant = _tenant(user)
    org_id = user["org_id"]
    
    sub = await tenant.subscriptions.find_one({"org_id": org_id}, {"_id": 0})
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
