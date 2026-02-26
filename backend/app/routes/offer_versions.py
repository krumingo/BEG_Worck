"""
Routes - Offer Versions (History + Restore)
Allows saving snapshots of offers and restoring them.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone
import uuid

from app.db import db
from app.deps.auth import get_current_user, can_manage_project
from app.utils.audit import log_audit

router = APIRouter(tags=["Offer Versions"])


class VersionCreate(BaseModel):
    note: Optional[str] = None


# Helper to compute offer totals
def compute_offer_line(line: dict) -> dict:
    """Compute line totals"""
    qty = line.get("qty", 0)
    material = line.get("material_unit_cost", 0)
    labor = line.get("labor_unit_cost", 0)
    line["line_material_cost"] = round(qty * material, 2)
    line["line_labor_cost"] = round(qty * labor, 2)
    line["line_total"] = round(line["line_material_cost"] + line["line_labor_cost"], 2)
    return line


def compute_offer_totals(offer: dict) -> dict:
    """Compute offer subtotal, vat, total"""
    lines = offer.get("lines", [])
    subtotal = sum(l.get("line_total", 0) for l in lines)
    vat_percent = offer.get("vat_percent", 0)
    vat_amount = round(subtotal * vat_percent / 100, 2)
    total = round(subtotal + vat_amount, 2)
    offer["subtotal"] = round(subtotal, 2)
    offer["vat_amount"] = vat_amount
    offer["total"] = total
    return offer


async def create_snapshot(offer: dict) -> dict:
    """Create a snapshot of the offer for versioning."""
    snapshot = {
        # Header fields
        "offer_no": offer.get("offer_no"),
        "title": offer.get("title"),
        "status": offer.get("status"),
        "version": offer.get("version"),
        "currency": offer.get("currency"),
        "vat_percent": offer.get("vat_percent"),
        "notes": offer.get("notes"),
        "sent_at": offer.get("sent_at"),
        "accepted_at": offer.get("accepted_at"),
        
        # Totals
        "subtotal": offer.get("subtotal"),
        "vat_amount": offer.get("vat_amount"),
        "total": offer.get("total"),
        
        # Lines (full copy)
        "lines": offer.get("lines", []),
        
        # Metadata
        "created_at": offer.get("created_at"),
        "updated_at": offer.get("updated_at"),
    }
    return snapshot


async def get_next_version_number(org_id: str, offer_id: str) -> int:
    """Get next version number for an offer."""
    last = await db.offer_versions.find_one(
        {"org_id": org_id, "offer_id": offer_id},
        {"_id": 0, "version_number": 1},
        sort=[("version_number", -1)]
    )
    return (last["version_number"] + 1) if last else 1


@router.get("/offers/{offer_id}/versions")
async def list_offer_versions(offer_id: str, user: dict = Depends(get_current_user)):
    """List all versions for an offer (latest first)."""
    offer = await db.offers.find_one({"id": offer_id, "org_id": user["org_id"]})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    
    if not await can_manage_project(user, offer["project_id"]):
        raise HTTPException(status_code=403, detail="Access denied")
    
    versions = await db.offer_versions.find(
        {"org_id": user["org_id"], "offer_id": offer_id},
        {"_id": 0, "snapshot_json": 0}  # Exclude large snapshot in list
    ).sort("version_number", -1).to_list(100)
    
    # Enrich with user names
    for v in versions:
        if v.get("created_by"):
            u = await db.users.find_one({"id": v["created_by"]}, {"_id": 0, "first_name": 1, "last_name": 1})
            v["created_by_name"] = f"{u['first_name']} {u['last_name']}" if u else "Unknown"
        else:
            v["created_by_name"] = ""
    
    return {"items": versions, "total": len(versions)}


@router.post("/offers/{offer_id}/versions", status_code=201)
async def create_offer_version(offer_id: str, data: VersionCreate, user: dict = Depends(get_current_user)):
    """Create a new version (snapshot) of the current offer state."""
    # Check permissions
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions to create versions")
    
    offer = await db.offers.find_one({"id": offer_id, "org_id": user["org_id"]})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    
    if not await can_manage_project(user, offer["project_id"]):
        raise HTTPException(status_code=403, detail="Access denied")
    
    now = datetime.now(timezone.utc).isoformat()
    version_number = await get_next_version_number(user["org_id"], offer_id)
    snapshot = await create_snapshot(offer)
    
    version = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "project_id": offer["project_id"],
        "offer_id": offer_id,
        "version_number": version_number,
        "created_at": now,
        "created_by": user["id"],
        "note": data.note,
        "snapshot_json": snapshot,
        "is_auto_backup": False,
    }
    
    await db.offer_versions.insert_one(version)
    await log_audit(user["org_id"], user["id"], user["email"], "version_created", "offer_version", version["id"], {
        "offer_id": offer_id,
        "version_number": version_number,
        "note": data.note
    })
    
    return {
        "id": version["id"],
        "version_number": version_number,
        "created_at": now,
        "note": data.note,
    }


@router.get("/offers/{offer_id}/versions/{version_number}")
async def get_offer_version(offer_id: str, version_number: int, user: dict = Depends(get_current_user)):
    """Get a specific version snapshot for preview."""
    offer = await db.offers.find_one({"id": offer_id, "org_id": user["org_id"]})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    
    if not await can_manage_project(user, offer["project_id"]):
        raise HTTPException(status_code=403, detail="Access denied")
    
    version = await db.offer_versions.find_one(
        {"org_id": user["org_id"], "offer_id": offer_id, "version_number": version_number},
        {"_id": 0}
    )
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    
    # Enrich with creator name
    if version.get("created_by"):
        u = await db.users.find_one({"id": version["created_by"]}, {"_id": 0, "first_name": 1, "last_name": 1})
        version["created_by_name"] = f"{u['first_name']} {u['last_name']}" if u else "Unknown"
    
    return version


@router.post("/offers/{offer_id}/versions/{version_number}/restore")
async def restore_offer_version(offer_id: str, version_number: int, user: dict = Depends(get_current_user)):
    """
    Restore an offer to a specific version.
    - Creates an automatic backup version BEFORE restore
    - Overwrites current offer with the snapshot data
    """
    # Check permissions
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions to restore versions")
    
    offer = await db.offers.find_one({"id": offer_id, "org_id": user["org_id"]})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    
    if not await can_manage_project(user, offer["project_id"]):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Get the version to restore
    version = await db.offer_versions.find_one(
        {"org_id": user["org_id"], "offer_id": offer_id, "version_number": version_number}
    )
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    
    now = datetime.now(timezone.utc).isoformat()
    
    # Step 1: Create automatic backup of current state BEFORE restore
    backup_version_number = await get_next_version_number(user["org_id"], offer_id)
    backup_snapshot = await create_snapshot(offer)
    
    backup = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "project_id": offer["project_id"],
        "offer_id": offer_id,
        "version_number": backup_version_number,
        "created_at": now,
        "created_by": user["id"],
        "note": f"Автоматичен backup преди възстановяване на v{version_number}",
        "snapshot_json": backup_snapshot,
        "is_auto_backup": True,
    }
    await db.offer_versions.insert_one(backup)
    
    # Step 2: Restore the snapshot to the current offer
    snapshot = version["snapshot_json"]
    
    # Prepare the update
    update_data = {
        "title": snapshot.get("title"),
        "currency": snapshot.get("currency"),
        "vat_percent": snapshot.get("vat_percent"),
        "notes": snapshot.get("notes"),
        "lines": snapshot.get("lines", []),
        "updated_at": now,
    }
    
    # Recompute totals from restored lines
    update_data["subtotal"] = snapshot.get("subtotal", 0)
    update_data["vat_amount"] = snapshot.get("vat_amount", 0)
    update_data["total"] = snapshot.get("total", 0)
    
    # If lines exist, recompute to ensure accuracy
    if update_data["lines"]:
        lines = [compute_offer_line(l) for l in update_data["lines"]]
        update_data["lines"] = lines
        subtotal = sum(l.get("line_total", 0) for l in lines)
        vat_amount = round(subtotal * update_data.get("vat_percent", 0) / 100, 2)
        update_data["subtotal"] = round(subtotal, 2)
        update_data["vat_amount"] = vat_amount
        update_data["total"] = round(subtotal + vat_amount, 2)
    
    await db.offers.update_one({"id": offer_id}, {"$set": update_data})
    
    await log_audit(user["org_id"], user["id"], user["email"], "version_restored", "offer", offer_id, {
        "restored_version": version_number,
        "backup_version": backup_version_number,
    })
    
    # Return the updated offer
    updated_offer = await db.offers.find_one({"id": offer_id}, {"_id": 0})
    
    return {
        "ok": True,
        "restored_version": version_number,
        "backup_version": backup_version_number,
        "offer": updated_offer,
    }


@router.delete("/offers/{offer_id}/versions/{version_number}")
async def delete_offer_version(offer_id: str, version_number: int, user: dict = Depends(get_current_user)):
    """Delete a specific version (admin only, cannot delete if it's the only version)."""
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin can delete versions")
    
    offer = await db.offers.find_one({"id": offer_id, "org_id": user["org_id"]})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    
    version = await db.offer_versions.find_one(
        {"org_id": user["org_id"], "offer_id": offer_id, "version_number": version_number}
    )
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    
    # Don't allow deleting if it's the only version
    count = await db.offer_versions.count_documents({"org_id": user["org_id"], "offer_id": offer_id})
    if count <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the only remaining version")
    
    await db.offer_versions.delete_one({"id": version["id"]})
    await log_audit(user["org_id"], user["id"], user["email"], "version_deleted", "offer_version", version["id"], {
        "version_number": version_number
    })
    
    return {"ok": True}
