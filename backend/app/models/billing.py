"""
Pydantic models - Billing (M10).
"""
from pydantic import BaseModel
from typing import Optional

class OrgSignupRequest(BaseModel):
    org_name: str
    owner_name: str
    owner_email: str
    password: str

class CreateCheckoutRequest(BaseModel):
    plan_id: str
    origin_url: str

class SubscriptionUpdate(BaseModel):
    plan_id: Optional[str] = None
    status: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    current_period_start: Optional[str] = None
    current_period_end: Optional[str] = None
    trial_ends_at: Optional[str] = None
