"""
Routes - Centralized Alarm System.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.services.alarm_engine import evaluate_all_rules

router = APIRouter(tags=["Alarms"])

VALID_SEVERITIES = ["info", "warning", "critical"]
VALID_TYPES = ["budget", "attendance", "procurement", "pricing", "deadline", "overhead", "overtime", "custom"]


class RuleCreate(BaseModel):
    name: str
    type: str = "custom"
    condition: dict
    severity: str = "warning"
    notify_roles: list = []
    cooldown_hours: int = 24
    auto_resolve: bool = False


class RuleUpdate(BaseModel):
    name: Optional[str] = None
    condition: Optional[dict] = None
    severity: Optional[str] = None
    notify_roles: Optional[list] = None
    cooldown_hours: Optional[int] = None
    auto_resolve: Optional[bool] = None


class AcknowledgeRequest(BaseModel):
    notes: Optional[str] = None


# ── Alarm Events ───────────────────────────────────────────────────

@router.get("/alarms")
async def list_alarms(
    severity: Optional[str] = None,
    type: Optional[str] = None,
    site_id: Optional[str] = None,
    status: str = "active",
    user: dict = Depends(get_current_user),
):
    query = {"org_id": user["org_id"]}
    if status:
        query["status"] = status
    if severity:
        query["severity"] = severity
    if type:
        query["type"] = type
    if site_id:
        query["site_id"] = site_id
    items = await db.alarm_events.find(query, {"_id": 0}).sort([("severity", -1), ("triggered_at", -1)]).to_list(200)
    return {"items": items, "total": len(items)}


@router.get("/alarms/count")
async def alarm_count(user: dict = Depends(get_current_user)):
    org_id = user["org_id"]
    critical = await db.alarm_events.count_documents({"org_id": org_id, "status": "active", "severity": "critical"})
    warning = await db.alarm_events.count_documents({"org_id": org_id, "status": "active", "severity": "warning"})
    info = await db.alarm_events.count_documents({"org_id": org_id, "status": "active", "severity": "info"})
    return {"critical": critical, "warning": warning, "info": info, "total": critical + warning + info}


@router.get("/alarms/dashboard")
async def alarm_dashboard(user: dict = Depends(get_current_user)):
    org_id = user["org_id"]
    active = await db.alarm_events.find({"org_id": org_id, "status": "active"}, {"_id": 0}).to_list(500)

    by_severity = {"critical": 0, "warning": 0, "info": 0}
    by_type = {}
    by_site = {}
    for e in active:
        by_severity[e.get("severity", "info")] = by_severity.get(e.get("severity", "info"), 0) + 1
        t = e.get("type", "custom")
        by_type[t] = by_type.get(t, 0) + 1
        sid = e.get("site_id")
        if sid:
            if sid not in by_site:
                by_site[sid] = {"site_id": sid, "name": e.get("site_name", ""), "count": 0}
            by_site[sid]["count"] += 1

    recent = await db.alarm_events.find(
        {"org_id": org_id}, {"_id": 0}
    ).sort("triggered_at", -1).limit(10).to_list(10)

    # 7-day trend
    trend = []
    now = datetime.now(timezone.utc)
    for i in range(6, -1, -1):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        count = await db.alarm_events.count_documents(
            {"org_id": org_id, "triggered_at": {"$gte": f"{d}T00:00:00", "$lte": f"{d}T23:59:59"}}
        )
        trend.append({"date": d, "count": count})

    return {
        "by_severity": by_severity,
        "by_type": by_type,
        "by_site": list(by_site.values()),
        "recent": recent,
        "trend": trend,
    }


@router.get("/alarms/{event_id}")
async def get_alarm(event_id: str, user: dict = Depends(get_current_user)):
    ev = await db.alarm_events.find_one({"id": event_id, "org_id": user["org_id"]}, {"_id": 0})
    if not ev:
        raise HTTPException(status_code=404, detail="Alarm not found")
    return ev


@router.put("/alarms/{event_id}/acknowledge")
async def acknowledge_alarm(event_id: str, data: AcknowledgeRequest, user: dict = Depends(get_current_user)):
    ev = await db.alarm_events.find_one({"id": event_id, "org_id": user["org_id"]})
    if not ev:
        raise HTTPException(status_code=404, detail="Alarm not found")
    now = datetime.now(timezone.utc).isoformat()
    await db.alarm_events.update_one({"id": event_id}, {"$set": {
        "status": "acknowledged", "acknowledged_by": user["id"], "acknowledged_at": now,
    }})
    return await db.alarm_events.find_one({"id": event_id}, {"_id": 0})


@router.put("/alarms/{event_id}/resolve")
async def resolve_alarm(event_id: str, data: AcknowledgeRequest, user: dict = Depends(get_current_user)):
    ev = await db.alarm_events.find_one({"id": event_id, "org_id": user["org_id"]})
    if not ev:
        raise HTTPException(status_code=404, detail="Alarm not found")
    now = datetime.now(timezone.utc).isoformat()
    await db.alarm_events.update_one({"id": event_id}, {"$set": {
        "status": "resolved", "resolved_by": user["id"], "resolved_at": now, "resolve_notes": data.notes,
    }})
    return await db.alarm_events.find_one({"id": event_id}, {"_id": 0})


@router.post("/alarms/evaluate")
async def evaluate_alarms(user: dict = Depends(get_current_user)):
    result = await evaluate_all_rules(user["org_id"])
    return result


# ── Alarm Rules ────────────────────────────────────────────────────

@router.get("/alarm-rules")
async def list_rules(user: dict = Depends(get_current_user)):
    items = await db.alarm_rules.find({"org_id": user["org_id"]}, {"_id": 0}).to_list(100)
    return {"items": items, "total": len(items)}


@router.post("/alarm-rules", status_code=201)
async def create_rule(data: RuleCreate, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    now = datetime.now(timezone.utc).isoformat()
    rule = {
        "id": str(uuid.uuid4()), "org_id": user["org_id"],
        "name": data.name, "type": data.type,
        "condition": data.condition, "severity": data.severity,
        "is_active": True, "notify_roles": data.notify_roles,
        "cooldown_hours": data.cooldown_hours, "auto_resolve": data.auto_resolve,
        "created_at": now, "updated_at": now,
    }
    await db.alarm_rules.insert_one(rule)
    return {k: v for k, v in rule.items() if k != "_id"}


@router.put("/alarm-rules/{rule_id}")
async def update_rule(rule_id: str, data: RuleUpdate, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    rule = await db.alarm_rules.find_one({"id": rule_id, "org_id": user["org_id"]})
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.alarm_rules.update_one({"id": rule_id}, {"$set": update})
    return await db.alarm_rules.find_one({"id": rule_id}, {"_id": 0})


@router.put("/alarm-rules/{rule_id}/toggle")
async def toggle_rule(rule_id: str, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    rule = await db.alarm_rules.find_one({"id": rule_id, "org_id": user["org_id"]})
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    await db.alarm_rules.update_one({"id": rule_id}, {"$set": {"is_active": not rule.get("is_active", True)}})
    return await db.alarm_rules.find_one({"id": rule_id}, {"_id": 0})


@router.delete("/alarm-rules/{rule_id}")
async def delete_rule(rule_id: str, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    await db.alarm_rules.delete_one({"id": rule_id, "org_id": user["org_id"]})
    return {"ok": True}
