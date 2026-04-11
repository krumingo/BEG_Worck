"""
Service - Resource & Cost Model.
Handles: Direct/Overhead/Hybrid personnel, Subcontractor Company/Crew,
Overhead Pools, Allocation Rules, Insurance treatment.

See /app/memory/RESOURCE_MODEL.md for business documentation.
"""
from app.db import db

# ── Constants ──────────────────────────────────────────────────────

RESOURCE_TYPES = ["direct", "overhead", "hybrid"]

SUBCONTRACTOR_TYPES = ["company", "crew"]

OVERHEAD_POOLS = ["administration", "base_warehouse", "transport", "general"]

ALLOCATION_RULES = [
    "by_hours", "by_person_days", "by_km", "by_deliveries",
    "by_materials", "by_revenue", "equal_split", "manual_percent",
]

INSURANCE_MODES = ["follows_worker", "overhead_pool", "mixed"]

DEFAULT_BURDEN_WEIGHTS = {
    "own_labor": 1.00,
    "subcontractor_company": 0.30,
    "subcontractor_crew": 0.60,
    "mixed_execution": 0.60,
}

DEFAULT_INSURANCE_RATE = 0.328  # ~32.8% employer social contributions (BG typical)


# ── Config Management ──────────────────────────────────────────────

async def get_resource_config(org_id: str) -> dict:
    """Get org-level resource & cost model config."""
    doc = await db.resource_model_config.find_one(
        {"org_id": org_id}, {"_id": 0}
    )
    if doc:
        return doc
    # Return defaults
    return {
        "org_id": org_id,
        "burden_weights": DEFAULT_BURDEN_WEIGHTS,
        "insurance_rate": DEFAULT_INSURANCE_RATE,
        "overhead_pools": OVERHEAD_POOLS,
        "allocation_rules": ALLOCATION_RULES,
        "is_default": True,
    }


async def save_resource_config(org_id: str, updates: dict, user_id: str) -> dict:
    """Save org-level resource config (upsert)."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    updates["org_id"] = org_id
    updates["updated_at"] = now
    updates["updated_by"] = user_id
    updates.pop("is_default", None)

    existing = await db.resource_model_config.find_one({"org_id": org_id})
    if existing:
        await db.resource_model_config.update_one({"org_id": org_id}, {"$set": updates})
    else:
        import uuid
        updates["id"] = str(uuid.uuid4())
        updates["created_at"] = now
        await db.resource_model_config.insert_one(updates)
    return await db.resource_model_config.find_one({"org_id": org_id}, {"_id": 0})


# ── Resource Classification ────────────────────────────────────────

async def classify_worker(org_id: str, worker_id: str) -> dict:
    """
    Classify a worker as direct/overhead/hybrid based on profile config.
    Returns: {resource_type, overhead_pool, insurance_mode, allocation_rule}
    """
    profile = await db.employee_profiles.find_one(
        {"org_id": org_id, "user_id": worker_id},
        {"_id": 0, "resource_type": 1, "default_overhead_pool": 1,
         "allocation_rule": 1, "insurance_mode": 1, "utilization_target_pct": 1,
         "role": 1, "position": 1},
    )
    if not profile:
        return {
            "resource_type": "direct",
            "overhead_pool": None,
            "insurance_mode": "follows_worker",
            "allocation_rule": "by_hours",
            "utilization_target_pct": 100,
        }
    return {
        "resource_type": profile.get("resource_type", "direct"),
        "overhead_pool": profile.get("default_overhead_pool"),
        "insurance_mode": profile.get("insurance_mode", "follows_worker"),
        "allocation_rule": profile.get("allocation_rule", "by_hours"),
        "utilization_target_pct": profile.get("utilization_target_pct", 100),
    }


def classify_subcontractor_type(sub_type: str) -> dict:
    """
    Get burden/insurance treatment for subcontractor type.
    """
    if sub_type == "crew":
        return {
            "subcontractor_type": "crew",
            "direct_cost_eligible": True,
            "overhead_weight": DEFAULT_BURDEN_WEIGHTS["subcontractor_crew"],
            "insurance_burden": True,
            "admin_burden": True,
            "description": "External crew — carries internal insurance/admin burden",
        }
    return {
        "subcontractor_type": "company",
        "direct_cost_eligible": True,
        "overhead_weight": DEFAULT_BURDEN_WEIGHTS["subcontractor_company"],
        "insurance_burden": False,
        "admin_burden": False,
        "description": "External company — no personal insurance burden",
    }


# ── Cost Breakdown ─────────────────────────────────────────────────

async def compute_worker_cost_breakdown(
    org_id: str, worker_id: str, hours: float, hourly_rate: float,
    project_hours: float = None, total_hours: float = None,
) -> dict:
    """
    Compute full cost breakdown for a worker including insurance and overhead allocation.
    
    For hybrid workers: split between direct (project) and overhead based on hours ratio.
    """
    config = await get_resource_config(org_id)
    classification = await classify_worker(org_id, worker_id)
    insurance_rate = config.get("insurance_rate", DEFAULT_INSURANCE_RATE)

    clean_labor = round(hours * hourly_rate, 2)
    insurance_cost = round(clean_labor * insurance_rate, 2)
    total_with_insurance = round(clean_labor + insurance_cost, 2)

    resource_type = classification["resource_type"]

    if resource_type == "direct":
        return {
            "resource_type": "direct",
            "clean_labor": clean_labor,
            "insurance_cost": insurance_cost,
            "insurance_target": "project",
            "direct_to_project": total_with_insurance,
            "to_overhead_pool": 0,
            "overhead_pool": None,
            "total_cost": total_with_insurance,
        }

    if resource_type == "overhead":
        pool = classification.get("overhead_pool", "general")
        return {
            "resource_type": "overhead",
            "clean_labor": clean_labor,
            "insurance_cost": insurance_cost,
            "insurance_target": "overhead_pool",
            "direct_to_project": 0,
            "to_overhead_pool": total_with_insurance,
            "overhead_pool": pool,
            "total_cost": total_with_insurance,
        }

    # Hybrid — split proportionally
    if project_hours is not None and total_hours and total_hours > 0:
        direct_ratio = project_hours / total_hours
    else:
        target = classification.get("utilization_target_pct", 50) / 100
        direct_ratio = target

    overhead_ratio = 1 - direct_ratio
    pool = classification.get("overhead_pool", "general")

    direct_amount = round(total_with_insurance * direct_ratio, 2)
    overhead_amount = round(total_with_insurance * overhead_ratio, 2)

    return {
        "resource_type": "hybrid",
        "clean_labor": clean_labor,
        "insurance_cost": insurance_cost,
        "insurance_target": "mixed",
        "direct_to_project": direct_amount,
        "to_overhead_pool": overhead_amount,
        "overhead_pool": pool,
        "direct_ratio": round(direct_ratio, 2),
        "overhead_ratio": round(overhead_ratio, 2),
        "total_cost": total_with_insurance,
    }


def compute_subcontractor_burden(sub_type: str, invoice_amount: float, config: dict = None) -> dict:
    """
    Compute overhead burden for a subcontractor invoice.
    """
    weights = (config or {}).get("burden_weights", DEFAULT_BURDEN_WEIGHTS)
    classification = classify_subcontractor_type(sub_type)
    weight = classification["overhead_weight"]

    burden_amount = round(invoice_amount * weight, 2)
    insurance_rate = (config or {}).get("insurance_rate", DEFAULT_INSURANCE_RATE)
    insurance_amount = round(invoice_amount * insurance_rate, 2) if classification["insurance_burden"] else 0

    return {
        "subcontractor_type": sub_type,
        "invoice_amount": invoice_amount,
        "burden_weight": weight,
        "burden_amount": burden_amount,
        "insurance_amount": insurance_amount,
        "total_loaded_cost": round(invoice_amount + burden_amount + insurance_amount, 2),
    }
