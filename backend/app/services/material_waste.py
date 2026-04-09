"""
Service - Material Waste Summary.
Aggregates planned/requested/delivered/issued/returned/waste per material per project.
"""
from app.db import db


def _status(issued, planned):
    if planned <= 0:
        return "ok"
    pct = issued / planned * 100
    if pct > 110:
        return "overuse"
    if pct > 100:
        return "warning"
    return "ok"


async def build_material_waste_summary(org_id: str, project_id: str, date_from: str = None, date_to: str = None) -> dict:
    mats = {}  # keyed by material_name

    def _get(name):
        n = name.strip() if name else "Неизвестен"
        if n not in mats:
            mats[n] = {"planned": 0, "requested": 0, "delivered": 0, "issued": 0, "returned": 0, "wasted": 0, "unit": ""}
        return mats[n]

    # ── A. Planned (from smr_analyses materials) ────────────────
    analyses = await db.smr_analyses.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0, "lines": 1}
    ).to_list(50)
    for a in analyses:
        for ln in a.get("lines", []):
            if not ln.get("is_active", True):
                continue
            qty = ln.get("qty", 0) or 0
            for m in ln.get("materials", []):
                e = _get(m.get("name", ""))
                qpu = m.get("qty_per_unit", 0) or 0
                e["planned"] += round(qpu * qty, 2)
                if m.get("unit"):
                    e["unit"] = m["unit"]

    # ── B. Requested (from material_requests) ───────────────────
    reqs = await db.material_requests.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0, "lines": 1}
    ).to_list(200)
    for r in reqs:
        for ln in r.get("lines", []):
            e = _get(ln.get("material_name", ""))
            e["requested"] += ln.get("qty_requested", 0) or 0
            if ln.get("unit"):
                e["unit"] = ln["unit"]

    # ── C. Delivered (warehouse receipts) ───────────────────────
    receipts = await db.warehouse_transactions.find(
        {"org_id": org_id, "project_id": project_id, "type": "receipt"}, {"_id": 0, "lines": 1}
    ).to_list(200)
    for t in receipts:
        for ln in t.get("lines", []):
            e = _get(ln.get("material_name", ""))
            e["delivered"] += float(ln.get("qty_received", 0) or ln.get("qty_issued", 0) or 0)

    # ── D. Issued (warehouse issues to project) ─────────────────
    issues = await db.warehouse_transactions.find(
        {"org_id": org_id, "project_id": project_id, "type": "issue"}, {"_id": 0, "lines": 1}
    ).to_list(500)
    for t in issues:
        for ln in t.get("lines", []):
            e = _get(ln.get("material_name", ""))
            e["issued"] += float(ln.get("qty_issued", 0) or 0)
            if ln.get("unit"):
                e["unit"] = ln["unit"]

    # ── E. Returns ──────────────────────────────────────────────
    returns = await db.warehouse_transactions.find(
        {"org_id": org_id, "project_id": project_id, "type": "return"}, {"_id": 0, "lines": 1}
    ).to_list(100)
    for t in returns:
        for ln in t.get("lines", []):
            e = _get(ln.get("material_name", ""))
            e["returned"] += float(ln.get("qty_issued", 0) or ln.get("qty_returned", 0) or 0)

    # ── F. Waste entries ────────────────────────────────────────
    wq = {"org_id": org_id, "project_id": project_id}
    if date_from:
        wq.setdefault("date", {})["$gte"] = date_from
    if date_to:
        wq.setdefault("date", {})["$lte"] = date_to
    wastes = await db.material_waste_entries.find(wq, {"_id": 0}).to_list(500)
    for w in wastes:
        e = _get(w.get("material_name", ""))
        e["wasted"] += w.get("qty", 0) or 0

    # ── Build result ────────────────────────────────────────────
    materials = []
    total_waste = 0
    overuse_count = 0
    biggest_overuse = None
    biggest_waste = None

    for name, d in sorted(mats.items()):
        net_used = round(d["issued"] - d["returned"], 2)
        variance = round(net_used - d["planned"], 2) if d["planned"] > 0 else 0
        variance_pct = round(variance / d["planned"] * 100, 1) if d["planned"] > 0 else 0
        st = _status(net_used, d["planned"])

        entry = {
            "material_name": name, "unit": d["unit"],
            "planned_qty": round(d["planned"], 2),
            "requested_qty": round(d["requested"], 2),
            "delivered_qty": round(d["delivered"], 2),
            "issued_qty": round(d["issued"], 2),
            "returned_qty": round(d["returned"], 2),
            "wasted_qty": round(d["wasted"], 2),
            "net_used_qty": round(net_used, 2),
            "variance_vs_planned": variance,
            "variance_pct": variance_pct,
            "status": st,
        }
        materials.append(entry)
        total_waste += d["wasted"]
        if st == "overuse":
            overuse_count += 1
        if not biggest_overuse or variance > biggest_overuse.get("variance_vs_planned", 0):
            biggest_overuse = entry
        if not biggest_waste or d["wasted"] > biggest_waste.get("wasted_qty", 0):
            biggest_waste = entry

    summary = {
        "materials_count": len(materials),
        "total_waste_items": len(wastes),
        "total_waste_qty": round(total_waste, 2),
        "overuse_count": overuse_count,
        "biggest_overuse": biggest_overuse["material_name"] if biggest_overuse and biggest_overuse.get("variance_vs_planned", 0) > 0 else None,
        "biggest_waste": biggest_waste["material_name"] if biggest_waste and biggest_waste.get("wasted_qty", 0) > 0 else None,
    }

    return {"summary": summary, "materials": materials}
