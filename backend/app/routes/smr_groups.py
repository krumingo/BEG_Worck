"""
Routes - SMR Groups (Локация → Група → СМР линии).
Triple hierarchy with aggregation.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel
import uuid

from app.db import db
from app.master_data.legacy_adapter import guarded_identity_delete
from app.deps.auth import get_current_user
from app.deps.modules import require_m2
from app.tenancy.data_access import TenantData


def _tenant(user: dict) -> TenantData:
    """The request's tenant — from the server-loaded session user only (W0-03E-A2C)."""
    return TenantData.for_user(db, user)

router = APIRouter(tags=["SMR Groups"])


class GroupCreate(BaseModel):
    location_id: Optional[str] = None
    name: str
    sort_order: int = 0
    color: Optional[str] = None
    report_mode: str = "per_line"
    notes: Optional[str] = None


class GroupUpdate(BaseModel):
    name: Optional[str] = None
    location_id: Optional[str] = None
    sort_order: Optional[int] = None
    color: Optional[str] = None
    report_mode: Optional[str] = None
    notes: Optional[str] = None


class AssignLine(BaseModel):
    line_id: str
    source: str  # smr_analysis | missing_smr | extra_work


class GroupReport(BaseModel):
    mode: str  # per_line | group_total
    line_reports: Optional[list] = None
    total_hours: Optional[float] = None
    total_cost: Optional[float] = None
    notes: Optional[str] = None


# ── Helpers ────────────────────────────────────────────────────────

def _source_collection(source: str):
    if source == "smr_analysis":
        return "smr_analyses"
    elif source == "missing_smr":
        return "missing_smr"
    elif source == "extra_work":
        return "extra_work_drafts"
    return None


async def _get_group_lines(org_id: str, group_id: str) -> list:
    """Fetch all lines assigned to a group from all sources."""
    tenant = TenantData.for_resolved_org(db, org_id)
    lines = []

    # SMR Analysis lines (embedded in analysis.lines[])
    analyses = await tenant.smr_analyses.find(
        {"org_id": org_id, "lines.group_id": group_id}, {"_id": 0}
    ).to_list(100)
    for a in analyses:
        for ln in a.get("lines", []):
            if ln.get("group_id") == group_id:
                lines.append({
                    **ln, "source": "smr_analysis",
                    "source_id": a["id"], "source_name": a.get("name", ""),
                })

    # Missing SMR
    missing = await tenant.missing_smr.find(
        {"org_id": org_id, "group_id": group_id}, {"_id": 0}
    ).to_list(200)
    for m in missing:
        lines.append({
            "line_id": m["id"], "smr_type": m.get("smr_type") or m.get("activity_type", ""),
            "unit": m.get("unit", "m2"), "qty": m.get("qty", 0),
            "final_total": 0, "labor_price_per_unit": 0,
            "material_cost_per_unit": 0, "source": "missing_smr",
            "source_id": m["id"], "status": m.get("status"),
            "group_id": group_id, "location_id": m.get("location_id"),
        })

    # Extra work drafts
    extras = await tenant.extra_work_drafts.find(
        {"org_id": org_id, "group_id": group_id}, {"_id": 0}
    ).to_list(200)
    for e in extras:
        total = (e.get("ai_total_price_per_unit") or 0) * (e.get("qty") or 1)
        lines.append({
            "line_id": e["id"], "smr_type": e.get("title", ""),
            "unit": e.get("unit", "m2"), "qty": e.get("qty", 0),
            "final_total": round(total, 2),
            "labor_price_per_unit": e.get("ai_labor_price_per_unit") or 0,
            "material_cost_per_unit": e.get("ai_material_price_per_unit") or 0,
            "source": "extra_work", "source_id": e["id"],
            "status": e.get("status"), "group_id": group_id,
            "location_id": e.get("location_id"),
        })

    return lines


def _compute_summary(lines: list) -> dict:
    total_cost = 0
    total_labor = 0
    total_material = 0
    by_unit = {}
    for ln in lines:
        ft = ln.get("final_total") or 0
        total_cost += ft
        qty = ln.get("qty") or 0
        unit = ln.get("unit", "m2")
        lpu = ln.get("labor_price_per_unit") or 0
        mpu = ln.get("material_cost_per_unit") or 0
        total_labor += lpu * qty
        total_material += mpu * qty
        by_unit[unit] = round(by_unit.get(unit, 0) + qty, 2)
    return {
        "total_cost": round(total_cost, 2),
        "total_labor": round(total_labor, 2),
        "total_material": round(total_material, 2),
        "lines_count": len(lines),
        "by_unit": by_unit,
    }


# ── CRUD ───────────────────────────────────────────────────────────

@router.post("/projects/{project_id}/smr-groups", status_code=201)
async def create_group(project_id: str, data: GroupCreate, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    project = await tenant.projects.find_one({"id": project_id, "org_id": user["org_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if data.location_id:
        loc = await tenant.location_nodes.find_one({"id": data.location_id, "org_id": user["org_id"]})
        if not loc:
            raise HTTPException(status_code=404, detail="Location not found")

    now = datetime.now(timezone.utc).isoformat()
    group = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "project_id": project_id,
        "location_id": data.location_id,
        "name": data.name,
        "sort_order": data.sort_order,
        "color": data.color,
        "report_mode": data.report_mode,
        "notes": data.notes,
        "created_at": now,
        "updated_at": now,
        "created_by": user["id"],
    }
    await tenant.smr_groups.insert_one(group)
    return {k: v for k, v in group.items() if k != "_id"}


@router.get("/projects/{project_id}/smr-groups")
async def list_groups(
    project_id: str,
    location_id: Optional[str] = None,
    user: dict = Depends(require_m2),
):
    tenant = _tenant(user)
    query = {"org_id": user["org_id"], "project_id": project_id}
    if location_id:
        query["location_id"] = location_id
    groups = await tenant.smr_groups.find(query, {"_id": 0}).sort("sort_order", 1).to_list(200)

    # Attach summary to each group
    for g in groups:
        lines = await _get_group_lines(user["org_id"], g["id"])
        g["summary"] = _compute_summary(lines)

    return {"items": groups, "total": len(groups)}


@router.get("/projects/{project_id}/smr-groups/tree")
async def get_groups_tree(project_id: str, user: dict = Depends(require_m2)):
    """Full tree: Location → Group → SMR lines."""
    tenant = _tenant(user)
    org_id = user["org_id"]

    # Get all locations for project
    locations = await tenant.location_nodes.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0}
    ).to_list(500)
    loc_map = {loc["id"]: loc for loc in locations}

    # Get all groups for project
    groups = await tenant.smr_groups.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0}
    ).sort("sort_order", 1).to_list(500)

    # Build tree by location
    tree = {}
    ungrouped_groups = []

    for g in groups:
        lines = await _get_group_lines(org_id, g["id"])
        summary = _compute_summary(lines)
        group_entry = {**g, "lines": lines, "summary": summary}

        lid = g.get("location_id")
        if lid and lid in loc_map:
            if lid not in tree:
                tree[lid] = {"location": loc_map[lid], "groups": []}
            tree[lid]["groups"].append(group_entry)
        else:
            ungrouped_groups.append(group_entry)

    result = list(tree.values())
    # Sort locations by name
    result.sort(key=lambda x: x["location"].get("name", ""))

    if ungrouped_groups:
        result.append({
            "location": {"id": None, "name": "Без локация", "type": "none"},
            "groups": ungrouped_groups,
        })

    # Grand totals
    all_lines = []
    for node in result:
        for g in node["groups"]:
            all_lines.extend(g["lines"])
    grand = _compute_summary(all_lines)

    return {"tree": result, "grand_total": grand}


@router.put("/smr-groups/{group_id}")
async def update_group(group_id: str, data: GroupUpdate, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    group = await tenant.smr_groups.find_one({"id": group_id, "org_id": user["org_id"]})
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await tenant.smr_groups.update_one({"id": group_id, "org_id": user["org_id"]}, {"$set": update})
    return await tenant.smr_groups.find_one({"id": group_id, "org_id": user["org_id"]}, {"_id": 0})


@router.delete("/smr-groups/{group_id}")
async def delete_group(group_id: str, request: Request, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    group = await tenant.smr_groups.find_one({"id": group_id, "org_id": user["org_id"]})
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    # W0-03E: decided BEFORE the lines are unassigned — in enforce a group that
    # is in use or migrated is refused, and nothing is touched.
    done = await guarded_identity_delete(user, request, db, collection="smr_groups",
                                         legacy_id=group_id)
    if done is not None:
        return done
    # Unassign all lines (clear group_id) — lines keep existing
    org = user["org_id"]
    await tenant.missing_smr.update_many({"group_id": group_id, "org_id": org}, {"$unset": {"group_id": ""}})
    await tenant.extra_work_drafts.update_many({"group_id": group_id, "org_id": org},
                                           {"$unset": {"group_id": ""}})
    # For smr_analyses, need to update embedded lines
    analyses = await tenant.smr_analyses.find(
        {"org_id": user["org_id"], "lines.group_id": group_id}
    ).to_list(100)
    for a in analyses:
        lines = a.get("lines", [])
        for ln in lines:
            if ln.get("group_id") == group_id:
                ln.pop("group_id", None)
        await tenant.smr_analyses.update_one({"id": a["id"], "org_id": org}, {"$set": {"lines": lines}})

    await tenant.smr_groups.delete_one({"id": group_id, "org_id": org})
    return {"ok": True}


# ── Assign / Unassign Lines ────────────────────────────────────────

@router.post("/smr-groups/{group_id}/assign-line")
async def assign_line(group_id: str, data: AssignLine, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    group = await tenant.smr_groups.find_one({"id": group_id, "org_id": user["org_id"]})
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    now = datetime.now(timezone.utc).isoformat()

    if data.source == "missing_smr":
        r = await tenant.missing_smr.update_one(
            {"id": data.line_id, "org_id": user["org_id"]},
            {"$set": {"group_id": group_id, "updated_at": now}},
        )
        if r.matched_count == 0:
            raise HTTPException(status_code=404, detail="Line not found")

    elif data.source == "extra_work":
        r = await tenant.extra_work_drafts.update_one(
            {"id": data.line_id, "org_id": user["org_id"]},
            {"$set": {"group_id": group_id, "updated_at": now}},
        )
        if r.matched_count == 0:
            raise HTTPException(status_code=404, detail="Line not found")

    elif data.source == "smr_analysis":
        # line_id is the line_id inside an analysis
        found = False
        analyses = await tenant.smr_analyses.find(
            {"org_id": user["org_id"], "lines.line_id": data.line_id}
        ).to_list(10)
        for a in analyses:
            for ln in a.get("lines", []):
                if ln["line_id"] == data.line_id:
                    ln["group_id"] = group_id
                    found = True
            await tenant.smr_analyses.update_one(
                {"id": a["id"]}, {"$set": {"lines": a["lines"], "updated_at": now}}
            )
        if not found:
            raise HTTPException(status_code=404, detail="Line not found")
    else:
        raise HTTPException(status_code=400, detail="Invalid source")

    return {"ok": True, "group_id": group_id, "line_id": data.line_id}


@router.post("/smr-groups/{group_id}/unassign-line")
async def unassign_line(group_id: str, data: AssignLine, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    group = await tenant.smr_groups.find_one({"id": group_id, "org_id": user["org_id"]})
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    now = datetime.now(timezone.utc).isoformat()

    if data.source == "missing_smr":
        await tenant.missing_smr.update_one(
            {"id": data.line_id, "org_id": user["org_id"]},
            {"$unset": {"group_id": ""}, "$set": {"updated_at": now}},
        )
    elif data.source == "extra_work":
        await tenant.extra_work_drafts.update_one(
            {"id": data.line_id, "org_id": user["org_id"]},
            {"$unset": {"group_id": ""}, "$set": {"updated_at": now}},
        )
    elif data.source == "smr_analysis":
        analyses = await tenant.smr_analyses.find(
            {"org_id": user["org_id"], "lines.line_id": data.line_id}
        ).to_list(10)
        for a in analyses:
            for ln in a.get("lines", []):
                if ln["line_id"] == data.line_id:
                    ln.pop("group_id", None)
            await tenant.smr_analyses.update_one(
                {"id": a["id"]}, {"$set": {"lines": a["lines"], "updated_at": now}}
            )

    return {"ok": True}


# ── Lines & Summary ────────────────────────────────────────────────

@router.get("/smr-groups/{group_id}/lines")
async def get_group_lines(group_id: str, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    group = await tenant.smr_groups.find_one({"id": group_id, "org_id": user["org_id"]}, {"_id": 0})
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    lines = await _get_group_lines(user["org_id"], group_id)
    return {"group": group, "lines": lines, "total": len(lines)}


@router.get("/smr-groups/{group_id}/summary")
async def get_group_summary(group_id: str, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    group = await tenant.smr_groups.find_one({"id": group_id, "org_id": user["org_id"]}, {"_id": 0})
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    lines = await _get_group_lines(user["org_id"], group_id)
    return {**_compute_summary(lines), "group_id": group_id, "group_name": group["name"]}


# ── Reverse Lookup by SMR Type ─────────────────────────────────────

@router.get("/projects/{project_id}/smr-by-type")
async def smr_by_type(project_id: str, smr_type: str, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    org_id = user["org_id"]
    results = []

    # Search in smr_analyses
    analyses = await tenant.smr_analyses.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0}
    ).to_list(100)
    for a in analyses:
        for ln in a.get("lines", []):
            if smr_type.lower() in (ln.get("smr_type") or "").lower():
                results.append({
                    "source": "smr_analysis", "line_id": ln.get("line_id"),
                    "smr_type": ln.get("smr_type"), "qty": ln.get("qty"),
                    "unit": ln.get("unit"), "total": ln.get("final_total", 0),
                    "group_id": ln.get("group_id"), "location_id": ln.get("location_id"),
                })

    # Search in missing_smr
    missing = await tenant.missing_smr.find(
        {"org_id": org_id, "project_id": project_id,
         "$or": [
             {"smr_type": {"$regex": smr_type, "$options": "i"}},
             {"activity_type": {"$regex": smr_type, "$options": "i"}},
         ]}, {"_id": 0}
    ).to_list(200)
    for m in missing:
        results.append({
            "source": "missing_smr", "line_id": m["id"],
            "smr_type": m.get("smr_type") or m.get("activity_type"),
            "qty": m.get("qty"), "unit": m.get("unit"), "total": 0,
            "group_id": m.get("group_id"), "location_id": m.get("location_id"),
        })

    # Enrich with group/location names
    group_ids = set(r["group_id"] for r in results if r.get("group_id"))
    loc_ids = set(r["location_id"] for r in results if r.get("location_id"))
    groups = {}
    locs = {}
    if group_ids:
        gs = await tenant.smr_groups.find({"id": {"$in": list(group_ids)}}, {"_id": 0, "id": 1, "name": 1}).to_list(100)
        groups = {g["id"]: g["name"] for g in gs}
    if loc_ids:
        ls = await tenant.location_nodes.find({"id": {"$in": list(loc_ids)}}, {"_id": 0, "id": 1, "name": 1}).to_list(100)
        locs = {l["id"]: l["name"] for l in ls}
    for r in results:
        r["group_name"] = groups.get(r.get("group_id"), "")
        r["location_name"] = locs.get(r.get("location_id"), "")

    return {"results": results, "total": len(results), "smr_type": smr_type}


# ── Group Report ───────────────────────────────────────────────────

@router.post("/smr-groups/{group_id}/report")
async def submit_group_report(group_id: str, data: GroupReport, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    group = await tenant.smr_groups.find_one({"id": group_id, "org_id": user["org_id"]})
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    now = datetime.now(timezone.utc).isoformat()
    report = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "group_id": group_id,
        "project_id": group["project_id"],
        "mode": data.mode,
        "reported_by": user["id"],
        "reported_at": now,
        "notes": data.notes,
    }

    if data.mode == "per_line" and data.line_reports:
        report["line_reports"] = data.line_reports
        report["total_hours"] = sum(lr.get("hours", 0) for lr in data.line_reports)
        report["total_cost"] = sum(lr.get("cost", 0) for lr in data.line_reports)
    elif data.mode == "group_total":
        report["total_hours"] = data.total_hours or 0
        report["total_cost"] = data.total_cost or 0
        report["line_reports"] = []

    await tenant.smr_group_reports.insert_one(report)
    return {k: v for k, v in report.items() if k != "_id"}
