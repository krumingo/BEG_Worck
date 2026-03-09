"""
Routes - AI Calibration Analytics + Learning Loop.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from datetime import datetime, timezone
import uuid
import logging

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import require_m2

logger = logging.getLogger(__name__)

router = APIRouter(tags=["AI Calibration"])

MIN_SAMPLES_FOR_SUGGESTION = 5
MIN_SAMPLES_FOR_CALIBRATION = 10
OUTLIER_THRESHOLD_PERCENT = 200  # Ignore edits > 200% delta


# ── Notification Trigger ───────────────────────────────────────────

async def check_and_notify_calibration_ready(org_id: str, activity_type: str, activity_subtype: str, city: str, small_qty: bool):
    """Check if a calibration group just reached 'ready' threshold and notify admins"""
    try:
        # Count samples for this group
        match = {
            "org_id": org_id,
            "normalized_activity_type": activity_type,
            "normalized_activity_subtype": activity_subtype,
            "city": city,
            "small_qty_flag": small_qty,
        }
        count = await db.ai_calibration_events.count_documents(match)
        
        if count < MIN_SAMPLES_FOR_CALIBRATION:
            return  # Not ready yet
        
        # Check if already approved
        existing_cal = await db.ai_calibrations.find_one({
            "org_id": org_id, "activity_type": activity_type,
            "activity_subtype": activity_subtype, "city": city,
            "small_qty": small_qty, "status": "approved",
        })
        if existing_cal:
            return  # Already approved, no need to notify
        
        # Anti-duplicate: check if we already sent a notification for this key
        notif_key = f"cal_ready|{activity_type}|{activity_subtype}|{city}|{small_qty}"
        existing_notif = await db.notifications.find_one({
            "org_id": org_id,
            "type": "ai_calibration_ready",
            "data.calibration_key": notif_key,
            "data.resolved": {"$ne": True},
        })
        if existing_notif:
            return  # Already notified, not yet resolved
        
        # Build notification message
        parts = [activity_type]
        if activity_subtype:
            parts[0] = f"{activity_type}/{activity_subtype}"
        if city:
            parts.append(city)
        if small_qty:
            parts.append("малко количество")
        label = ", ".join(parts)
        
        # Get all Admin users in this org
        admins = await db.users.find(
            {"org_id": org_id, "role": {"$in": ["Admin", "Owner"]}, "active": {"$ne": False}},
            {"_id": 0, "id": 1}
        ).to_list(20)
        
        now = datetime.now(timezone.utc).isoformat()
        for admin in admins:
            notif = {
                "id": str(uuid.uuid4()),
                "org_id": org_id,
                "user_id": admin["id"],
                "type": "ai_calibration_ready",
                "title": "AI Калибрация готова за одобрение",
                "message": f"{label} ({count} случая) — готово за калибрация",
                "data": {
                    "calibration_key": notif_key,
                    "activity_type": activity_type,
                    "activity_subtype": activity_subtype,
                    "city": city,
                    "small_qty": small_qty,
                    "sample_count": count,
                    "resolved": False,
                },
                "is_read": False,
                "created_at": now,
            }
            await db.notifications.insert_one(notif)
        
        logger.info(f"Calibration ready notification sent: {label} ({count} samples) to {len(admins)} admins")
    except Exception as e:
        logger.warning(f"Failed to check/send calibration notification: {e}")


# ── Record AI Edit Event ───────────────────────────────────────────

@router.post("/ai-calibration/record-edit")
async def record_ai_edit(data: dict, user: dict = Depends(require_m2)):
    """Record when a user accepts/edits an AI-proposed price"""
    now = datetime.now(timezone.utc).isoformat()
    
    ai_total = float(data.get("ai_total_price_per_unit", 0))
    final_total = float(data.get("final_total_price_per_unit", 0))
    was_edited = abs(ai_total - final_total) > 0.01 if ai_total > 0 else False
    delta_pct = round(((final_total - ai_total) / ai_total) * 100, 1) if ai_total > 0 else 0
    
    # Skip outliers
    if abs(delta_pct) > OUTLIER_THRESHOLD_PERCENT:
        return {"ok": True, "skipped": True, "reason": "outlier"}
    
    event = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "created_at": now,
        "created_by": user["id"],
        "ai_provider_used": data.get("ai_provider_used", "unknown"),
        "ai_confidence": float(data.get("ai_confidence", 0)),
        "ai_material_price_per_unit": float(data.get("ai_material_price_per_unit", 0)),
        "ai_labor_price_per_unit": float(data.get("ai_labor_price_per_unit", 0)),
        "ai_total_price_per_unit": ai_total,
        "ai_small_qty_adjustment": float(data.get("ai_small_qty_adjustment", 0)),
        "final_material_price": float(data.get("final_material_price_per_unit", 0)),
        "final_labor_price": float(data.get("final_labor_price_per_unit", 0)),
        "final_total_price": final_total,
        "was_manually_edited": was_edited,
        "edit_delta_percent": delta_pct,
        "city": data.get("city"),
        "project_id": data.get("project_id"),
        "offer_id": data.get("offer_id"),
        "draft_id": data.get("draft_id"),
        "source_type": data.get("source_type", "extra_work"),
        "normalized_activity_type": data.get("normalized_activity_type"),
        "normalized_activity_subtype": data.get("normalized_activity_subtype"),
        "unit": data.get("unit"),
        "qty": float(data.get("qty", 0)),
        "small_qty_flag": bool(data.get("small_qty_flag", False)),
    }
    
    await db.ai_calibration_events.insert_one(event)
    
    # Check if any calibration group just became ready
    await check_and_notify_calibration_ready(
        user["org_id"],
        data.get("normalized_activity_type"),
        data.get("normalized_activity_subtype"),
        data.get("city"),
        bool(data.get("small_qty_flag", False)),
    )
    
    return {"ok": True, "event_id": event["id"], "was_edited": was_edited, "delta_percent": delta_pct}


# ── Analytics Overview ─────────────────────────────────────────────

@router.get("/ai-calibration/overview")
async def get_calibration_overview(user: dict = Depends(require_m2)):
    """Get overview stats for AI calibration"""
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    
    org_id = user["org_id"]
    
    total = await db.ai_calibration_events.count_documents({"org_id": org_id})
    edited = await db.ai_calibration_events.count_documents({"org_id": org_id, "was_manually_edited": True})
    accepted = total - edited
    
    # Average delta
    pipeline = [
        {"$match": {"org_id": org_id, "was_manually_edited": True}},
        {"$group": {
            "_id": None,
            "avg_delta": {"$avg": "$edit_delta_percent"},
            "median_values": {"$push": "$edit_delta_percent"},
        }}
    ]
    agg = await db.ai_calibration_events.aggregate(pipeline).to_list(1)
    avg_delta = round(agg[0]["avg_delta"], 1) if agg else 0
    
    # Top corrected categories
    cat_pipeline = [
        {"$match": {"org_id": org_id, "was_manually_edited": True}},
        {"$group": {
            "_id": "$normalized_activity_type",
            "count": {"$sum": 1},
            "avg_delta": {"$avg": "$edit_delta_percent"},
        }},
        {"$sort": {"count": -1}},
        {"$limit": 5},
    ]
    top_cats = await db.ai_calibration_events.aggregate(cat_pipeline).to_list(5)
    
    return {
        "total_proposals": total,
        "accepted_unchanged": accepted,
        "manually_edited": edited,
        "acceptance_rate": round((accepted / total * 100), 1) if total > 0 else 0,
        "avg_edit_delta_percent": avg_delta,
        "top_corrected_categories": [
            {"category": c["_id"] or "Общо", "count": c["count"], "avg_delta": round(c["avg_delta"], 1)}
            for c in top_cats
        ],
    }


# ── Category Breakdown ─────────────────────────────────────────────

@router.get("/ai-calibration/categories")
async def get_calibration_categories(
    city: Optional[str] = None,
    source_type: Optional[str] = None,
    user: dict = Depends(require_m2),
):
    """Get calibration data broken down by category"""
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    
    org_id = user["org_id"]
    match = {"org_id": org_id}
    if city:
        match["city"] = city
    if source_type:
        match["source_type"] = source_type
    
    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": {
                "type": "$normalized_activity_type",
                "subtype": "$normalized_activity_subtype",
                "city": "$city",
                "small_qty": "$small_qty_flag",
            },
            "sample_count": {"$sum": 1},
            "edited_count": {"$sum": {"$cond": ["$was_manually_edited", 1, 0]}},
            "avg_delta": {"$avg": "$edit_delta_percent"},
            "avg_ai_total": {"$avg": "$ai_total_price_per_unit"},
            "avg_final_total": {"$avg": "$final_total_price"},
            "deltas": {"$push": "$edit_delta_percent"},
        }},
        {"$sort": {"sample_count": -1}},
    ]
    
    results = await db.ai_calibration_events.aggregate(pipeline).to_list(100)
    
    # Load approved calibrations
    approved_cals = {}
    cals = await db.ai_calibrations.find({"org_id": org_id, "status": "approved"}, {"_id": 0}).to_list(100)
    for c in cals:
        key = f"{c.get('activity_type')}|{c.get('activity_subtype')}|{c.get('city')}|{c.get('small_qty')}"
        approved_cals[key] = c
    
    categories = []
    for r in results:
        g = r["_id"]
        key = f"{g.get('type')}|{g.get('subtype')}|{g.get('city')}|{g.get('small_qty')}"
        
        # Compute median from deltas (trimmed - remove top/bottom 10%)
        deltas = sorted([d for d in r.get("deltas", []) if d is not None])
        if len(deltas) >= 4:
            trim = max(1, len(deltas) // 10)
            trimmed = deltas[trim:-trim]
            median_delta = trimmed[len(trimmed) // 2] if trimmed else 0
        elif deltas:
            median_delta = deltas[len(deltas) // 2]
        else:
            median_delta = 0
        
        sc = r["sample_count"]
        if sc >= MIN_SAMPLES_FOR_CALIBRATION:
            cal_status = "ready"
        elif sc >= MIN_SAMPLES_FOR_SUGGESTION:
            cal_status = "suggested"
        else:
            cal_status = "observation"
        
        # Check if already approved
        approved = approved_cals.get(key)
        if approved:
            cal_status = "approved"
        
        suggested_factor = round(1 + (median_delta / 100), 3) if median_delta != 0 else 1.0
        
        categories.append({
            "activity_type": g.get("type") or "Общо",
            "activity_subtype": g.get("subtype") or "",
            "city": g.get("city"),
            "small_qty": g.get("small_qty", False),
            "sample_count": sc,
            "edited_count": r["edited_count"],
            "avg_delta_percent": round(r["avg_delta"] or 0, 1),
            "median_delta_percent": round(median_delta, 1),
            "avg_ai_price": round(r["avg_ai_total"] or 0, 2),
            "avg_final_price": round(r["avg_final_total"] or 0, 2),
            "suggested_factor": suggested_factor,
            "calibration_status": cal_status,
            "approved_factor": approved["factor"] if approved else None,
        })
    
    return categories


# ── Approve / Manage Calibration ───────────────────────────────────

@router.post("/ai-calibration/approve")
async def approve_calibration(data: dict, user: dict = Depends(require_m2)):
    """Approve a suggested calibration factor (Admin only)"""
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    
    now = datetime.now(timezone.utc).isoformat()
    
    cal = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "activity_type": data.get("activity_type"),
        "activity_subtype": data.get("activity_subtype"),
        "city": data.get("city"),
        "small_qty": data.get("small_qty", False),
        "factor": float(data.get("factor", 1.0)),
        "status": "approved",
        "approved_by": user["id"],
        "approved_at": now,
        "sample_count": int(data.get("sample_count", 0)),
        "avg_delta": float(data.get("avg_delta", 0)),
        "created_at": now,
    }
    
    # Upsert - replace existing calibration for same key
    await db.ai_calibrations.update_one(
        {
            "org_id": user["org_id"],
            "activity_type": cal["activity_type"],
            "activity_subtype": cal["activity_subtype"],
            "city": cal["city"],
            "small_qty": cal["small_qty"],
        },
        {"$set": cal},
        upsert=True,
    )
    
    # Resolve related notifications
    notif_key = f"cal_ready|{cal['activity_type']}|{cal['activity_subtype']}|{cal['city']}|{cal['small_qty']}"
    await db.notifications.update_many(
        {"org_id": user["org_id"], "type": "ai_calibration_ready", "data.calibration_key": notif_key},
        {"$set": {"is_read": True, "data.resolved": True}}
    )
    
    return {"ok": True, "calibration": cal}


@router.delete("/ai-calibration/{cal_id}")
async def revoke_calibration(cal_id: str, user: dict = Depends(require_m2)):
    """Revoke an approved calibration"""
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    
    result = await db.ai_calibrations.delete_one({"id": cal_id, "org_id": user["org_id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Calibration not found")
    return {"ok": True}


@router.get("/ai-calibration/approved")
async def list_approved_calibrations(user: dict = Depends(require_m2)):
    """List all approved calibrations"""
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    
    cals = await db.ai_calibrations.find(
        {"org_id": user["org_id"], "status": "approved"},
        {"_id": 0}
    ).sort("approved_at", -1).to_list(100)
    return cals


# ── Get Calibration Factor for AI Proposal ─────────────────────────

async def get_calibration_factor(org_id: str, activity_type: str, activity_subtype: str, city: str = None, small_qty: bool = False) -> dict:
    """Look up approved calibration factor for a specific category"""
    # Try exact match first
    cal = await db.ai_calibrations.find_one({
        "org_id": org_id,
        "activity_type": activity_type,
        "activity_subtype": activity_subtype,
        "city": city,
        "small_qty": small_qty,
        "status": "approved",
    }, {"_id": 0})
    
    if cal:
        return {"factor": cal["factor"], "source": "exact_match", "sample_count": cal.get("sample_count", 0)}
    
    # Try without city
    cal = await db.ai_calibrations.find_one({
        "org_id": org_id,
        "activity_type": activity_type,
        "activity_subtype": activity_subtype,
        "city": None,
        "small_qty": small_qty,
        "status": "approved",
    }, {"_id": 0})
    
    if cal:
        return {"factor": cal["factor"], "source": "category_match", "sample_count": cal.get("sample_count", 0)}
    
    # No calibration found
    return {"factor": 1.0, "source": None, "sample_count": 0}
