"""
Routes - Location Tree (Обектова йерархия).
Hierarchical location structure: project → building → floor → room → zone → element.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, List
from datetime import datetime, timezone
from pydantic import BaseModel
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import require_m2

router = APIRouter(tags=["Locations"])

VALID_TYPES = ["building", "floor", "room", "zone", "element"]


# ── Pydantic Models ────────────────────────────────────────────────

class LocationCreate(BaseModel):
    parent_id: Optional[str] = None
    type: str
    name: str
    code: Optional[str] = None
    sort_order: Optional[int] = 0
    area_m2: Optional[float] = None
    description: Optional[str] = None


class LocationUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    sort_order: Optional[int] = None
    type: Optional[str] = None
    area_m2: Optional[float] = None
    description: Optional[str] = None


# ── Helpers ────────────────────────────────────────────────────────

def build_tree(nodes: list, parent_id: Optional[str] = None) -> list:
    """Build nested tree from flat list of nodes."""
    children = [n for n in nodes if n.get("parent_id") == parent_id]
    children.sort(key=lambda x: (x.get("sort_order", 0), x.get("name", "")))
    for child in children:
        child["children"] = build_tree(nodes, child["id"])
    return children


# ── CRUD ───────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/locations")
async def get_location_tree(project_id: str, user: dict = Depends(require_m2)):
    """Get the full location tree for a project (nested JSON)."""
    project = await db.projects.find_one(
        {"id": project_id, "org_id": user["org_id"]}, {"_id": 0, "id": 1}
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    nodes = await db.location_nodes.find(
        {"project_id": project_id, "org_id": user["org_id"]}, {"_id": 0}
    ).to_list(1000)

    tree = build_tree(nodes, None)
    return {"tree": tree, "total": len(nodes)}


@router.post("/projects/{project_id}/locations", status_code=201)
async def create_location(
    project_id: str, data: LocationCreate, user: dict = Depends(require_m2)
):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    project = await db.projects.find_one(
        {"id": project_id, "org_id": user["org_id"]}, {"_id": 0, "id": 1, "name": 1}
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if data.type not in VALID_TYPES:
        raise HTTPException(
            status_code=400, detail=f"Invalid type. Valid: {VALID_TYPES}"
        )

    # Validate parent exists if provided
    if data.parent_id:
        parent = await db.location_nodes.find_one(
            {"id": data.parent_id, "project_id": project_id, "org_id": user["org_id"]}
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Parent node not found")

    now = datetime.now(timezone.utc).isoformat()
    node = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "project_id": project_id,
        "parent_id": data.parent_id,
        "type": data.type,
        "name": data.name,
        "code": data.code,
        "sort_order": data.sort_order or 0,
        "metadata": {
            "area_m2": data.area_m2,
            "description": data.description,
            "photos": [],
        },
        "created_at": now,
        "updated_at": now,
        "created_by": user["id"],
    }
    await db.location_nodes.insert_one(node)
    return {k: v for k, v in node.items() if k != "_id"}


@router.get("/locations/{node_id}")
async def get_location(node_id: str, user: dict = Depends(require_m2)):
    node = await db.location_nodes.find_one(
        {"id": node_id, "org_id": user["org_id"]}, {"_id": 0}
    )
    if not node:
        raise HTTPException(status_code=404, detail="Location not found")
    return node


@router.put("/locations/{node_id}")
async def update_location(
    node_id: str, data: LocationUpdate, user: dict = Depends(require_m2)
):
    node = await db.location_nodes.find_one(
        {"id": node_id, "org_id": user["org_id"]}
    )
    if not node:
        raise HTTPException(status_code=404, detail="Location not found")

    update = {}
    for k, v in data.model_dump().items():
        if v is not None:
            if k in ("area_m2", "description"):
                update[f"metadata.{k}"] = v
            else:
                if k == "type" and v not in VALID_TYPES:
                    raise HTTPException(
                        status_code=400, detail=f"Invalid type. Valid: {VALID_TYPES}"
                    )
                update[k] = v
    update["updated_at"] = datetime.now(timezone.utc).isoformat()

    await db.location_nodes.update_one({"id": node_id}, {"$set": update})
    return await db.location_nodes.find_one({"id": node_id}, {"_id": 0})


@router.delete("/locations/{node_id}")
async def delete_location(node_id: str, user: dict = Depends(require_m2)):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    node = await db.location_nodes.find_one(
        {"id": node_id, "org_id": user["org_id"]}
    )
    if not node:
        raise HTTPException(status_code=404, detail="Location not found")

    # Block delete if has children
    children_count = await db.location_nodes.count_documents(
        {"parent_id": node_id, "org_id": user["org_id"]}
    )
    if children_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete: node has {children_count} child node(s). Delete children first.",
        )

    # Block delete if linked SMR exist
    smr_count = await db.missing_smr.count_documents(
        {"org_id": user["org_id"], "location_id": node_id}
    )
    ew_count = await db.extra_work_drafts.count_documents(
        {"org_id": user["org_id"], "location_id": node_id}
    )
    if smr_count + ew_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete: {smr_count + ew_count} linked SMR record(s) exist.",
        )

    await db.location_nodes.delete_one({"id": node_id})
    return {"ok": True}


# ── Children ───────────────────────────────────────────────────────

@router.get("/locations/{node_id}/children")
async def get_children(node_id: str, user: dict = Depends(require_m2)):
    children = (
        await db.location_nodes.find(
            {"parent_id": node_id, "org_id": user["org_id"]}, {"_id": 0}
        )
        .sort("sort_order", 1)
        .to_list(500)
    )
    return {"children": children, "total": len(children)}


# ── SMR at Location ───────────────────────────────────────────────

@router.get("/locations/{node_id}/smr")
async def get_location_smr(node_id: str, user: dict = Depends(require_m2)):
    """Get all SMR records linked to this location (missing_smr + extra_work_drafts)."""
    org_id = user["org_id"]

    node = await db.location_nodes.find_one(
        {"id": node_id, "org_id": org_id}, {"_id": 0}
    )
    if not node:
        raise HTTPException(status_code=404, detail="Location not found")

    # Collect this node's ID + all descendant IDs
    all_ids = [node_id]
    stack = [node_id]
    while stack:
        parent = stack.pop()
        kids = await db.location_nodes.find(
            {"parent_id": parent, "org_id": org_id}, {"_id": 0, "id": 1}
        ).to_list(500)
        for k in kids:
            all_ids.append(k["id"])
            stack.append(k["id"])

    # Query missing_smr by location_id
    missing = await db.missing_smr.find(
        {"org_id": org_id, "location_id": {"$in": all_ids}}, {"_id": 0}
    ).to_list(500)

    # Query extra_work_drafts by location_id
    extras = await db.extra_work_drafts.find(
        {"org_id": org_id, "location_id": {"$in": all_ids}}, {"_id": 0}
    ).to_list(500)

    # Also query by text fields (floor/room matching for legacy data)
    type_name_map = {n["type"]: n["name"] for n in [node]}
    floor_name = node.get("name") if node.get("type") == "floor" else None
    room_name = node.get("name") if node.get("type") == "room" else None

    text_missing = []
    text_extras = []
    if floor_name or room_name:
        text_q = {"org_id": org_id, "project_id": node["project_id"]}
        if floor_name:
            text_q["floor"] = floor_name
        if room_name:
            text_q["room"] = room_name
        text_missing = await db.missing_smr.find(
            {**text_q, "location_id": {"$exists": False}}, {"_id": 0}
        ).to_list(200)
        ew_text_q = {"org_id": org_id, "project_id": node["project_id"]}
        if floor_name:
            ew_text_q["location_floor"] = floor_name
        if room_name:
            ew_text_q["location_room"] = room_name
        text_extras = await db.extra_work_drafts.find(
            {**ew_text_q, "location_id": {"$exists": False}}, {"_id": 0}
        ).to_list(200)

    # Deduplicate
    seen_ids = set()
    all_missing = []
    for m in missing + text_missing:
        if m["id"] not in seen_ids:
            seen_ids.add(m["id"])
            all_missing.append(m)
    seen_ids2 = set()
    all_extras = []
    for e in extras + text_extras:
        if e["id"] not in seen_ids2:
            seen_ids2.add(e["id"])
            all_extras.append(e)

    return {
        "location": node,
        "missing_smr": all_missing,
        "extra_works": all_extras,
        "total": len(all_missing) + len(all_extras),
    }


# ── Reverse Lookup ─────────────────────────────────────────────────

@router.get("/projects/{project_id}/smr-reverse-lookup")
async def smr_reverse_lookup(
    project_id: str,
    activity_type: Optional[str] = None,
    smr_type: Optional[str] = None,
    user: dict = Depends(require_m2),
):
    """Reverse lookup: find all locations where a given SMR type exists."""
    org_id = user["org_id"]

    project = await db.projects.find_one(
        {"id": project_id, "org_id": org_id}, {"_id": 0, "id": 1}
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not activity_type and not smr_type:
        raise HTTPException(
            status_code=400, detail="Provide activity_type or smr_type"
        )

    # Build query for missing_smr
    ms_query = {"org_id": org_id, "project_id": project_id}
    if activity_type:
        ms_query["activity_type"] = {"$regex": activity_type, "$options": "i"}
    if smr_type:
        ms_query["smr_type"] = {"$regex": smr_type, "$options": "i"}

    missing_items = await db.missing_smr.find(ms_query, {"_id": 0}).to_list(500)

    # Build query for extra_work_drafts
    ew_query = {"org_id": org_id, "project_id": project_id}
    if activity_type:
        ew_query["normalized_activity_type"] = {
            "$regex": activity_type,
            "$options": "i",
        }
    if smr_type:
        ew_query["title"] = {"$regex": smr_type, "$options": "i"}

    extra_items = await db.extra_work_drafts.find(ew_query, {"_id": 0}).to_list(500)

    # Collect location_ids from results
    location_ids = set()
    for item in missing_items + extra_items:
        lid = item.get("location_id")
        if lid:
            location_ids.add(lid)

    # Fetch location nodes
    locations = {}
    if location_ids:
        nodes = await db.location_nodes.find(
            {"id": {"$in": list(location_ids)}, "org_id": org_id}, {"_id": 0}
        ).to_list(500)
        locations = {n["id"]: n for n in nodes}

    # Build result grouped by location
    results = []
    for item in missing_items:
        lid = item.get("location_id")
        loc = locations.get(lid) if lid else None
        loc_parts = []
        if item.get("floor"):
            loc_parts.append(f"Ет.{item['floor']}")
        if item.get("room"):
            loc_parts.append(item["room"])
        if item.get("zone"):
            loc_parts.append(item["zone"])
        results.append({
            "source": "missing_smr",
            "id": item["id"],
            "smr_type": item.get("smr_type"),
            "activity_type": item.get("activity_type"),
            "qty": item.get("qty"),
            "unit": item.get("unit"),
            "status": item.get("status"),
            "location_id": lid,
            "location_name": loc["name"] if loc else ", ".join(loc_parts) or "-",
            "location_type": loc["type"] if loc else None,
            "floor": item.get("floor"),
            "room": item.get("room"),
        })

    for item in extra_items:
        lid = item.get("location_id")
        loc = locations.get(lid) if lid else None
        loc_parts = []
        if item.get("location_floor"):
            loc_parts.append(f"Ет.{item['location_floor']}")
        if item.get("location_room"):
            loc_parts.append(item["location_room"])
        results.append({
            "source": "extra_work",
            "id": item["id"],
            "smr_type": item.get("title"),
            "activity_type": item.get("normalized_activity_type"),
            "qty": item.get("qty"),
            "unit": item.get("unit"),
            "status": item.get("status"),
            "location_id": lid,
            "location_name": loc["name"] if loc else ", ".join(loc_parts) or "-",
            "location_type": loc["type"] if loc else None,
            "floor": item.get("location_floor"),
            "room": item.get("location_room"),
        })

    return {"query": {"activity_type": activity_type, "smr_type": smr_type}, "results": results, "total": len(results)}
