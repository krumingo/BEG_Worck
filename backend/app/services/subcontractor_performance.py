"""
Service - Subcontractor Performance summary.
Additive analytics layer on top of existing subcontractor data.
"""
from app.db import db


def _compute_status(entry: dict) -> str:
    delayed = False
    over = False
    pe = entry.get("promised_end_date")
    ae = entry.get("actual_end_date")
    if pe and ae and ae > pe:
        delayed = True
    pa = entry.get("promised_amount") or 0
    aa = entry.get("actual_paid_amount") or 0
    if pa > 0 and aa > pa:
        over = True
    if delayed and over:
        return "mixed"
    if delayed:
        return "delayed"
    if over:
        return "over_budget"
    if pe and ae:
        return "on_time"
    return "unknown"


async def build_subcontractor_performance(org_id: str, project_id: str = None, subcontractor_id: str = None) -> dict:
    query = {"org_id": org_id}
    if project_id:
        query["project_id"] = project_id
    if subcontractor_id:
        query["subcontractor_id"] = subcontractor_id

    items = await db.subcontractor_performance.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)

    delayed = 0
    over_budget = 0
    mixed = 0
    on_time = 0
    biggest_delay = None
    biggest_over = None
    scores = []

    for it in items:
        st = _compute_status(it)
        it["status"] = st
        if st == "delayed":
            delayed += 1
        elif st == "over_budget":
            over_budget += 1
        elif st == "mixed":
            mixed += 1
        elif st == "on_time":
            on_time += 1

        # Variance
        pa = it.get("promised_amount") or 0
        aa = it.get("actual_paid_amount") or 0
        it["variance_amount"] = round(aa - pa, 2)

        pe = it.get("promised_end_date", "")
        ae = it.get("actual_end_date", "")
        if pe and ae and ae > pe:
            if not biggest_delay or ae > biggest_delay.get("actual_end_date", ""):
                biggest_delay = it
        if pa > 0 and aa > pa:
            if not biggest_over or (aa - pa) > biggest_over.get("variance_amount", 0):
                biggest_over = it

        qs = it.get("quality_score")
        if qs:
            scores.append(qs)

    subs = set(it.get("subcontractor_id") for it in items if it.get("subcontractor_id"))

    summary = {
        "subcontractors_count": len(subs),
        "total_records": len(items),
        "on_time": on_time,
        "delayed_count": delayed,
        "over_budget_count": over_budget,
        "mixed_count": mixed,
        "biggest_delay": biggest_delay.get("subcontractor_id", "")[:8] if biggest_delay else None,
        "biggest_over_budget": biggest_over.get("subcontractor_id", "")[:8] if biggest_over else None,
        "avg_quality": round(sum(scores) / len(scores), 1) if scores else None,
    }

    return {"summary": summary, "items": items}
