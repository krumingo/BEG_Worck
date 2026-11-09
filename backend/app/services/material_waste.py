"""
Service - Material Waste Summary.
Aggregates planned/requested/delivered/issued/returned/waste per material per project.

5C-C23 F-15: ``wasted`` = the manual register (``material_waste_entries``)
PLUS the canonical write-offs from the project („фира", Р10), read through the
shared ``canonical_material_cost.project_material_cost`` helper — no second
register. Write-offs are listed in ``writeoffs`` with
``source = warehouse_write_off`` („отписване от склада"); the summary keeps the
manual and write-off counts apart (``manual_waste_*`` / ``writeoff_*``).
"""
from app.db import db
from app.tenancy.data_access import TenantData


# 5C-C23 F-15 — how a canonical write-off is marked on the card.
WRITE_OFF_SOURCE = "warehouse_write_off"
WRITE_OFF_LABEL = "отписване от склада"


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
    tenant = TenantData.for_resolved_org(db, org_id)
    mats = {}  # keyed by material_name

    def _get(name):
        n = name.strip() if name else "Неизвестен"
        if n not in mats:
            mats[n] = {"planned": 0, "requested": 0, "delivered": 0, "issued": 0, "returned": 0,
                       "wasted": 0, "manual_wasted": 0, "writeoff": 0, "unit": ""}
        return mats[n]

    # ── A. Planned (from smr_analyses materials) ────────────────
    analyses = await tenant.smr_analyses.find(
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
    reqs = await tenant.material_requests.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0, "lines": 1}
    ).to_list(200)
    for r in reqs:
        for ln in r.get("lines", []):
            e = _get(ln.get("material_name", ""))
            e["requested"] += ln.get("qty_requested", 0) or 0
            if ln.get("unit"):
                e["unit"] = ln["unit"]

    # ── C. Delivered (warehouse receipts) ───────────────────────
    # CODEX C12.10: no silent cap on canonical ledger reads.
    _cursor_c = tenant.warehouse_transactions.find(
        {"org_id": org_id, "project_id": project_id, "type": "receipt"}, {"_id": 0, "lines": 1}
    )
    async for t in _cursor_c:
        for ln in t.get("lines", []):
            e = _get(ln.get("material_name", ""))
            e["delivered"] += float(ln.get("qty_received", 0) or ln.get("qty_issued", 0) or 0)

    # ── D. Issued (warehouse issues to project) ─────────────────
    _cursor_d = tenant.warehouse_transactions.find(
        {"org_id": org_id, "project_id": project_id, "type": "issue"}, {"_id": 0, "lines": 1}
    )
    async for t in _cursor_d:
        for ln in t.get("lines", []):
            e = _get(ln.get("material_name", ""))
            e["issued"] += float(ln.get("qty_issued", 0) or 0)
            if ln.get("unit"):
                e["unit"] = ln["unit"]

    # ── E. Returns ──────────────────────────────────────────────
    _cursor_e = tenant.warehouse_transactions.find(
        {"org_id": org_id, "project_id": project_id, "type": "return"}, {"_id": 0, "lines": 1}
    )
    async for t in _cursor_e:
        for ln in t.get("lines", []):
            e = _get(ln.get("material_name", ""))
            e["returned"] += float(ln.get("qty_issued", 0) or ln.get("qty_returned", 0) or 0)

    # ── E2. Canonical ledger (WH-FIX-01, FG-190) ─────────────────
    # Canonical rows carry `action` + item / quantity, never the legacy
    # `type` + `lines` read above; the shared trail helper counts them:
    # accepted on / delivered into the project = delivered and issued (Р17),
    # moved away = returned. Write-offs are section G (no double count).
    from app.services.canonical_material_cost import canonical_trail_by_name
    for name, c in (await canonical_trail_by_name(tenant, org_id, project_id)).items():
        e = _get(name)
        e["delivered"] += c["issued_to_project"]
        e["issued"] += c["issued_to_project"]
        e["returned"] += c["returned"]
        if c.get("unit") and not e["unit"]:
            e["unit"] = c["unit"]

    # ── F. Waste entries ────────────────────────────────────────
    wq = {"org_id": org_id, "project_id": project_id}
    if date_from:
        wq.setdefault("date", {})["$gte"] = date_from
    if date_to:
        wq.setdefault("date", {})["$lte"] = date_to
    wastes = await tenant.material_waste_entries.find(wq, {"_id": 0}).to_list(500)
    manual_waste_qty = 0.0
    for w in wastes:
        e = _get(w.get("material_name", ""))
        q = w.get("qty", 0) or 0
        e["wasted"] += q
        e["manual_wasted"] += q
        manual_waste_qty += q

    # ── G. Canonical write-offs („фира", 5C-C23 F-15) ───────────
    # Read through the ONE shared material-cost helper (the same lines every
    # finance report counts) — no second register is written or read. The
    # manual register above stays as it is; write-offs are added beside it
    # and marked ``source = warehouse_write_off`` („отписване от склада").
    from app.services.canonical_material_cost import (
        project_material_cost, waste_lines, WASTE_LABEL)
    cost = await project_material_cost(tenant, org_id, project_id)
    writeoffs = []
    writeoff_qty = 0.0
    writeoff_value = 0.0
    for ln in waste_lines(cost):
        day = ln["at"].strftime("%Y-%m-%d") if ln["at"] else None
        if date_from and (day is None or day < date_from):
            continue
        if date_to and (day is None or day > date_to):
            continue
        e = _get(ln.get("material_name") or "")
        q = float(ln.get("qty") or 0)
        e["wasted"] += q
        e["writeoff"] += q
        if ln.get("unit") and not e["unit"]:
            e["unit"] = ln["unit"]
        writeoff_qty += q
        writeoff_value += float(ln.get("value") or 0)
        writeoffs.append({
            "source": WRITE_OFF_SOURCE, "source_label": WRITE_OFF_LABEL,
            "cost_label": WASTE_LABEL,
            "id": ln.get("ref"), "movement_id": ln.get("movement_id"),
            "material_name": (ln.get("material_name") or "").strip() or "Неизвестен",
            "item_id": ln.get("item_id"), "qty": round(q, 4), "unit": ln.get("unit") or "",
            "value": ln.get("value"), "reason": ln.get("reason"), "date": day,
        })
    writeoffs.sort(key=lambda w: w["date"] or "", reverse=True)

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
            "manual_wasted_qty": round(d["manual_wasted"], 2),
            "written_off_qty": round(d["writeoff"], 4),
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
        # manual register entries + canonical write-offs, each listed once
        "total_waste_items": len(wastes) + len(writeoffs),
        "total_waste_qty": round(total_waste, 2),
        "manual_waste_items": len(wastes),
        "manual_waste_qty": round(manual_waste_qty, 2),
        "writeoff_items": len(writeoffs),
        "writeoff_qty": round(writeoff_qty, 4),
        "writeoff_value": round(writeoff_value, 2),
        "writeoff_label": WRITE_OFF_LABEL,
        "overuse_count": overuse_count,
        "biggest_overuse": biggest_overuse["material_name"] if biggest_overuse and biggest_overuse.get("variance_vs_planned", 0) > 0 else None,
        "biggest_waste": biggest_waste["material_name"] if biggest_waste and biggest_waste.get("wasted_qty", 0) > 0 else None,
    }

    return {"summary": summary, "materials": materials, "writeoffs": writeoffs}
