"""
Health and misc routes - /api/health, /api/roles, /api/modules, /api/subscription
"""
from fastapi import APIRouter, Depends

router = APIRouter(tags=["misc"])

# These will be set by server.py when including the router
ROLES = None
MODULES = None
SUBSCRIPTION_PLANS = None
db = None
get_current_user = None

def init_dependencies(roles, modules, plans, database, auth_dep):
    """Initialize module dependencies from server.py"""
    global ROLES, MODULES, SUBSCRIPTION_PLANS, db, get_current_user
    ROLES = roles
    MODULES = modules
    SUBSCRIPTION_PLANS = plans
    db = database
    get_current_user = auth_dep

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
async def get_subscription(user: dict = Depends(lambda: get_current_user)):
    sub = await db.subscriptions.find_one({"org_id": user["org_id"]}, {"_id": 0})
    if sub:
        plan = SUBSCRIPTION_PLANS.get(sub.get("plan_id", "free"), SUBSCRIPTION_PLANS["free"])
        sub["plan_name"] = plan["name"]
        sub["plan_price"] = plan["price"]
        sub["allowed_modules"] = plan["allowed_modules"]
        sub["limits"] = plan["limits"]
    return sub
