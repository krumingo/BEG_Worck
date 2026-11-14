"""
Routes - Centralized Alarm System.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Optional
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.services.alarm_engine import evaluate_all_rules
from app.permissions.money_write import strip_money_for_non_finance  # SEC-02-G (FG-111)
from app.permissions.money_write import money_values_visible, money_alarm_exclusion, require_finance_read


async def _band_filter(request: Request, user: dict) -> dict:
    """SEC-02-G (audit SEC71-04; R31): for a caller without the finance right, the money
    alarms of a site whose labor cost comes from fewer than 2 paid workers do not exist —
    not in the list, the ?severity= filter, the counts, the dashboard or one event."""
    if await money_values_visible(request, user):
        return {}
    return await money_alarm_exclusion(user)
from app.tenancy.data_access import TenantData


def _tenant(user: dict) -> TenantData:
    """The request's tenant — from the server-loaded session user only (W0-03E-A2C)."""
    return TenantData.for_user(db, user)

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
@strip_money_for_non_finance   # SEC-02-G (FG-111; R20-5M): money in alarm text / metric
async def list_alarms(
    request: Request,
    severity: Optional[str] = None,
    type: Optional[str] = None,
    site_id: Optional[str] = None,
    status: str = "active",
    page: int = 1,
    page_size: int = 50,
    user: dict = Depends(get_current_user),
):
    from app.utils.pagination import paginate_query
    query = {"org_id": user["org_id"], **await _band_filter(request, user)}
    if status:
        query["status"] = status
    if severity:
        query["severity"] = severity
    if type:
        query["type"] = type
    if site_id:
        query["site_id"] = site_id
    tenant = _tenant(user)
    return await paginate_query(tenant.alarm_events, query, page, page_size, "triggered_at", -1)


@router.get("/alarms/count")
async def alarm_count(request: Request, user: dict = Depends(get_current_user)):
    tenant = _tenant(user)
    org_id = user["org_id"]
    band = await _band_filter(request, user)   # SEC-02-G (SEC71-04)
    critical = await tenant.alarm_events.count_documents({"org_id": org_id, "status": "active", "severity": "critical", **band})
    warning = await tenant.alarm_events.count_documents({"org_id": org_id, "status": "active", "severity": "warning", **band})
    info = await tenant.alarm_events.count_documents({"org_id": org_id, "status": "active", "severity": "info", **band})
    return {"critical": critical, "warning": warning, "info": info, "total": critical + warning + info}


@router.get("/alarms/dashboard")
@strip_money_for_non_finance   # SEC-02-G (FG-111; R20-5M): money in alarm text / metric
async def alarm_dashboard(request: Request, user: dict = Depends(get_current_user)):
    tenant = _tenant(user)
    org_id = user["org_id"]
    band = await _band_filter(request, user)   # SEC-02-G (SEC71-04)
    active = await tenant.alarm_events.find({"org_id": org_id, "status": "active", **band}, {"_id": 0}).to_list(500)

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

    recent = await tenant.alarm_events.find(
        {"org_id": org_id, **band}, {"_id": 0}
    ).sort("triggered_at", -1).limit(10).to_list(10)

    # 7-day trend
    trend = []
    now = datetime.now(timezone.utc)
    for i in range(6, -1, -1):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        count = await tenant.alarm_events.count_documents(
            {"org_id": org_id, "triggered_at": {"$gte": f"{d}T00:00:00", "$lte": f"{d}T23:59:59"}, **band}
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
@strip_money_for_non_finance   # SEC-02-G (FG-111; R20-5M): money in alarm text / metric
async def get_alarm(event_id: str, request: Request, user: dict = Depends(get_current_user)):
    tenant = _tenant(user)
    ev = await tenant.alarm_events.find_one({"id": event_id, "org_id": user["org_id"],
                                             **await _band_filter(request, user)}, {"_id": 0})
    if not ev:
        raise HTTPException(status_code=404, detail="Alarm not found")
    return ev


@router.put("/alarms/{event_id}/acknowledge")
@strip_money_for_non_finance   # SEC-02-G (FG-111; R20-5M): money in alarm text / metric
async def acknowledge_alarm(event_id: str, data: AcknowledgeRequest, request: Request,
                    user: dict = Depends(get_current_user)):
    tenant = _tenant(user)
    ev = await tenant.alarm_events.find_one({"id": event_id, "org_id": user["org_id"],
                                             **await _band_filter(request, user)})  # SEC71-04
    if not ev:
        raise HTTPException(status_code=404, detail="Alarm not found")
    now = datetime.now(timezone.utc).isoformat()
    await tenant.alarm_events.update_one({"id": event_id}, {"$set": {
        "status": "acknowledged", "acknowledged_by": user["id"], "acknowledged_at": now,
    }})
    return await tenant.alarm_events.find_one({"id": event_id}, {"_id": 0})


@router.put("/alarms/{event_id}/resolve")
@strip_money_for_non_finance   # SEC-02-G (FG-111; R20-5M): money in alarm text / metric
async def resolve_alarm(event_id: str, data: AcknowledgeRequest, request: Request,
                    user: dict = Depends(get_current_user)):
    tenant = _tenant(user)
    ev = await tenant.alarm_events.find_one({"id": event_id, "org_id": user["org_id"],
                                             **await _band_filter(request, user)})  # SEC71-04
    if not ev:
        raise HTTPException(status_code=404, detail="Alarm not found")
    if ev.get("type") == "labor_correction_required":
        # R77 / FG-533: the alarm closes only when the row was reversed or a correcting row
        # (corrects_entry_id) was approved — never by a click alone
        entry_id = (ev.get("context") or {}).get("entity_id")
        row = await tenant.labor_entries.find_one({"org_id": user["org_id"], "id": entry_id},
                                                  {"_id": 0, "reversed_by_entry_id": 1})
        fixed = bool((row or {}).get("reversed_by_entry_id")) or bool(await tenant.labor_entries.find_one(
            {"org_id": user["org_id"], "corrects_entry_id": entry_id, "approval_status": "approved"},
            {"_id": 0, "id": 1}))
        if not fixed:
            raise HTTPException(status_code=409, detail={
                "code": "CORRECTION_REQUIRED",
                "message": "Алармата се затваря след сторно или одобрен коригиращ ред"})
    now = datetime.now(timezone.utc).isoformat()
    await tenant.alarm_events.update_one({"id": event_id}, {"$set": {
        "status": "resolved", "resolved_by": user["id"], "resolved_at": now, "resolve_notes": data.notes,
    }})
    return await tenant.alarm_events.find_one({"id": event_id}, {"_id": 0})


@router.post("/alarms/evaluate")
async def evaluate_alarms(
    request: Request,
    # SEC-02-G (audit SEC71-05; R20): evaluating every rule (and auto-resolving) answers
    # with counts over EVERY site's money alarms — finance roles only. The only caller is
    # the Alarms page button (no cron). In enforce a denial writes the canonical
    # "permission denied" AuditEvent (who called it).
    _sec02: dict = Depends(require_finance_read(
        "finance.alarm_evaluation.execute", module=None, resource_type="alarm_rules")),
    user: dict = Depends(get_current_user)):
    result = await evaluate_all_rules(user["org_id"])
    if not await money_values_visible(request, user):
        # defence in depth (unreachable for a non-finance role): no counter / list from a
        # money alarm of a single-paid-worker site; resolved_events is not attributable
        from app.permissions.finance_read import MONEY_ALARM_TYPES, strip_money
        from app.permissions.money_write import single_paid_sites
        single = await single_paid_sites(user, [e.get("site_id") for e in result["events"]])
        events = [e for e in result["events"]
                  if not (e.get("type") in MONEY_ALARM_TYPES and e.get("site_id") in single)]
        result = strip_money({"new_events": len(events), "events": events})
    return result


# ── Alarm Rules ────────────────────────────────────────────────────

@router.get("/alarm-rules")
async def list_rules(request: Request, user: dict = Depends(get_current_user)):
    tenant = _tenant(user)
    items = await tenant.alarm_rules.find({"org_id": user["org_id"]}, {"_id": 0}).to_list(100)
    if not await money_values_visible(request, user):
        # SEC-02-G (FG-133): only the known non-money keys of a rule's condition
        from app.permissions.finance_read import safe_alarm_rule
        items = [safe_alarm_rule(r) for r in items]
    return {"items": items, "total": len(items)}


@router.post("/alarm-rules", status_code=201)
async def create_rule(data: RuleCreate, user: dict = Depends(get_current_user)):
    tenant = _tenant(user)
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
    await tenant.alarm_rules.insert_one(rule)
    return {k: v for k, v in rule.items() if k != "_id"}


@router.put("/alarm-rules/{rule_id}")
async def update_rule(rule_id: str, data: RuleUpdate, user: dict = Depends(get_current_user)):
    tenant = _tenant(user)
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    rule = await tenant.alarm_rules.find_one({"id": rule_id, "org_id": user["org_id"]})
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await tenant.alarm_rules.update_one({"id": rule_id}, {"$set": update})
    return await tenant.alarm_rules.find_one({"id": rule_id}, {"_id": 0})


@router.put("/alarm-rules/{rule_id}/toggle")
async def toggle_rule(rule_id: str, user: dict = Depends(get_current_user)):
    tenant = _tenant(user)
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    rule = await tenant.alarm_rules.find_one({"id": rule_id, "org_id": user["org_id"]})
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    await tenant.alarm_rules.update_one({"id": rule_id}, {"$set": {"is_active": not rule.get("is_active", True)}})
    return await tenant.alarm_rules.find_one({"id": rule_id}, {"_id": 0})


@router.delete("/alarm-rules/{rule_id}")
async def delete_rule(rule_id: str, user: dict = Depends(get_current_user)):
    tenant = _tenant(user)
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    await tenant.alarm_rules.delete_one({"id": rule_id, "org_id": user["org_id"]})
    return {"ok": True}
