"""
Service - Alarm Engine. Evaluates rules against live data.
"""
from datetime import datetime, timezone, timedelta
from app.db import db
import uuid


async def evaluate_rule(rule: dict, org_id: str) -> list:
    """Evaluate a single alarm rule and return new AlarmEvents."""
    events = []
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    rule_id = rule["id"]
    cond = rule.get("condition", {})
    metric = cond.get("metric", "")
    op = cond.get("operator", ">")
    threshold = cond.get("threshold", 0)
    cooldown_h = rule.get("cooldown_hours", 24)

    async def _check_cooldown(entity_id=None):
        cutoff = (now - timedelta(hours=cooldown_h)).isoformat()
        q = {"org_id": org_id, "rule_id": rule_id, "status": {"$in": ["active", "acknowledged"]}, "triggered_at": {"$gte": cutoff}}
        if entity_id:
            q["context.entity_id"] = entity_id
        return await db.alarm_events.find_one(q)

    def _compare(value, op, thresh):
        if op == ">": return value > thresh
        if op == "<": return value < thresh
        if op == ">=": return value >= thresh
        if op == "<=": return value <= thresh
        if op == "==": return value == thresh
        if op == "!=": return value != thresh
        return False

    def _make_event(message, entity_id=None, entity_type=None, metric_value=0, site_id=None, site_name=None, details=None):
        return {
            "id": str(uuid.uuid4()), "org_id": org_id, "rule_id": rule_id,
            "rule_name": rule.get("name", ""), "severity": rule.get("severity", "warning"),
            "type": rule.get("type", "custom"),
            "site_id": site_id, "site_name": site_name,
            "triggered_at": now_iso,
            "message": message,
            "context": {"metric_value": metric_value, "threshold": threshold, "entity_id": entity_id, "entity_type": entity_type, "details": details or {}},
            "status": "active",
            "acknowledged_by": None, "acknowledged_at": None,
            "resolved_by": None, "resolved_at": None, "resolve_notes": None,
        }

    rtype = rule.get("type", "custom")

    if rtype == "budget":
        projects = await db.projects.find(
            {"org_id": org_id, "status": {"$in": ["Active", "Draft"]}},
            {"_id": 0, "id": 1, "name": 1},
        ).to_list(100)
        for p in projects:
            pid = p["id"]
            budgets = await db.activity_budgets.find({"org_id": org_id, "project_id": pid}, {"_id": 0, "labor_budget": 1}).to_list(50)
            total_budget = sum(b.get("labor_budget", 0) for b in budgets)
            if total_budget <= 0:
                continue
            sessions = await db.work_sessions.find(
                {"org_id": org_id, "site_id": pid, "ended_at": {"$ne": None}}, {"_id": 0, "labor_cost": 1}
            ).to_list(5000)
            spent = sum(s.get("labor_cost", 0) for s in sessions)
            burn_pct = round(spent / total_budget * 100, 1)

            if not _compare(burn_pct, op, threshold):
                continue

            # Check secondary condition
            sec_metric = cond.get("secondary_metric")
            if sec_metric == "progress_pct":
                pkgs = await db.execution_packages.find(
                    {"org_id": org_id, "project_id": pid}, {"_id": 0, "progress_percent": 1}
                ).to_list(100)
                progress = sum(pk.get("progress_percent", 0) for pk in pkgs) / max(len(pkgs), 1) if pkgs else 0
                sec_op = cond.get("secondary_operator", "<")
                sec_thresh = cond.get("secondary_threshold", 50)
                if not _compare(progress, sec_op, sec_thresh):
                    continue

            if await _check_cooldown(pid):
                continue

            events.append(_make_event(
                f"{p['name']}: бюджет {burn_pct}% изхарчен",
                entity_id=pid, entity_type="project", metric_value=burn_pct,
                site_id=pid, site_name=p["name"],
            ))

    elif rtype == "overtime":
        week_ago = (now - timedelta(days=7)).isoformat()
        pipeline = [
            {"$match": {"org_id": org_id, "ended_at": {"$ne": None}, "is_overtime": True, "started_at": {"$gte": week_ago}}},
            {"$group": {"_id": "$worker_id", "total_ot": {"$sum": "$duration_hours"}, "name": {"$first": "$worker_name"}}},
        ]
        results = await db.work_sessions.aggregate(pipeline).to_list(500)
        for r in results:
            if _compare(r["total_ot"], op, threshold):
                wid = r["_id"]
                if await _check_cooldown(wid):
                    continue
                events.append(_make_event(
                    f"{r.get('name', wid[:8])}: {round(r['total_ot'], 1)}ч извънреден труд/седмица",
                    entity_id=wid, entity_type="worker", metric_value=round(r["total_ot"], 1),
                ))

    elif rtype == "attendance":
        projects = await db.projects.find(
            {"org_id": org_id, "status": "Active"}, {"_id": 0, "id": 1, "name": 1}
        ).to_list(100)
        for p in projects:
            days_back = int(threshold) + 1
            found_workers = False
            for d in range(1, days_back + 1):
                check_date = (now - timedelta(days=d)).strftime("%Y-%m-%d")
                count = await db.work_sessions.count_documents(
                    {"org_id": org_id, "site_id": p["id"], "started_at": {"$gte": f"{check_date}T00:00:00", "$lte": f"{check_date}T23:59:59"}}
                )
                if count > 0:
                    found_workers = True
                    break
            if not found_workers:
                if await _check_cooldown(p["id"]):
                    continue
                events.append(_make_event(
                    f"{p['name']}: без работници > {int(threshold)} дни",
                    entity_id=p["id"], entity_type="project", metric_value=int(threshold),
                    site_id=p["id"], site_name=p["name"],
                ))

    elif rtype == "overhead":
        from app.services.overhead_realtime import compute_realtime_overhead
        current_month = now.strftime("%Y-%m")
        prev_dt = now.replace(day=1) - timedelta(days=1)
        prev_month = prev_dt.strftime("%Y-%m")
        cur = await compute_realtime_overhead(org_id, current_month)
        prev = await compute_realtime_overhead(org_id, prev_month)
        if prev["overhead_per_person_day"] > 0:
            change = round((cur["overhead_per_person_day"] - prev["overhead_per_person_day"]) / prev["overhead_per_person_day"] * 100, 1)
            if _compare(change, op, threshold):
                if not await _check_cooldown("overhead"):
                    events.append(_make_event(
                        f"Режийни +{change}% спрямо миналия месец",
                        entity_id="overhead", entity_type="org", metric_value=change,
                    ))

    elif rtype == "deadline":
        projects = await db.projects.find(
            {"org_id": org_id, "status": "Active", "end_date": {"$ne": None}},
            {"_id": 0, "id": 1, "name": 1, "end_date": 1},
        ).to_list(100)
        for p in projects:
            try:
                ed = datetime.fromisoformat(str(p["end_date"]).replace("Z", "+00:00"))
                days_left = (ed - now).days
                if _compare(days_left, op, threshold):
                    if not await _check_cooldown(p["id"]):
                        events.append(_make_event(
                            f"{p['name']}: {days_left} дни до крайния срок",
                            entity_id=p["id"], entity_type="project", metric_value=days_left,
                            site_id=p["id"], site_name=p["name"],
                        ))
            except (ValueError, TypeError):
                pass

    return events


async def evaluate_all_rules(org_id: str) -> dict:
    """Evaluate all active rules for an org."""
    rules = await db.alarm_rules.find({"org_id": org_id, "is_active": True}, {"_id": 0}).to_list(100)
    all_new = []
    resolved = 0

    for rule in rules:
        new_events = await evaluate_rule(rule, org_id)
        for ev in new_events:
            await db.alarm_events.insert_one(ev)
        all_new.extend(new_events)

        # Auto-resolve
        if rule.get("auto_resolve"):
            if not new_events:
                now_iso = datetime.now(timezone.utc).isoformat()
                result = await db.alarm_events.update_many(
                    {"org_id": org_id, "rule_id": rule["id"], "status": "active"},
                    {"$set": {"status": "resolved", "resolved_at": now_iso, "resolved_by": "auto", "resolve_notes": "Auto-resolved"}},
                )
                resolved += result.modified_count

    return {"new_events": len(all_new), "resolved_events": resolved, "events": [{k: v for k, v in e.items() if k != "_id"} for e in all_new]}
