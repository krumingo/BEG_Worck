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
from app.permissions.money_write import require_money_write, strip_money_for_non_finance
from app.utils.audit import log_audit
from app.tenancy.data_access import TenantData


def _tenant(user: dict) -> TenantData:
    """The request's tenant — from the server-loaded session user only (W0-03E-A2C)."""
    return TenantData.for_user(db, user)

router = APIRouter(tags=["Offer Versions"])


def _refuse_if_used(offer: dict, draft_was_used: bool) -> None:
    """OFF-01 Addendum A §1 (OFF79-01): restore rewrites the offer's lines and totals in
    place, and a version delete removes a snapshot for good. Both are allowed only on a draft
    that was never sent — the same rule as DELETE /offers/{id}. Anything else → 409."""
    if offer.get("status") != "Draft" or draft_was_used:
        raise HTTPException(status_code=409, detail={
            "error_code": "OFFER_IN_USE",
            "message": "Изпратена или използвана оферта не се променя и версиите ѝ не се "
                       "изтриват — направете нова версия"})


async def _draft_was_used(tenant: TenantData, offer: dict) -> bool:
    from app.routes.offers import _draft_was_used as used
    return await used(tenant, offer)


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
    subtotal = sum(line.get("line_total", 0) for line in lines)
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
    tenant = TenantData.for_resolved_org(db, org_id)
    last = await tenant.offer_versions.find_one(
        {"org_id": org_id, "offer_id": offer_id},
        {"_id": 0, "version_number": 1},
        sort=[("version_number", -1)]
    )
    return (last["version_number"] + 1) if last else 1


@router.get("/offers/{offer_id}/versions")
@strip_money_for_non_finance   # SEC-02-A (R20-5M, D1)
async def list_offer_versions(offer_id: str, user: dict = Depends(get_current_user)):
    """List all versions for an offer (latest first)."""
    tenant = _tenant(user)
    offer = await tenant.offers.find_one({"id": offer_id, "org_id": user["org_id"]})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    
    if not await can_manage_project(user, offer["project_id"]):
        raise HTTPException(status_code=403, detail="Access denied")
    
    versions = await tenant.offer_versions.find(
        {"org_id": user["org_id"], "offer_id": offer_id},
        {"_id": 0, "snapshot_json": 0}  # Exclude large snapshot in list
    ).sort("version_number", -1).to_list(100)
    
    # Enrich with user names
    for v in versions:
        if v.get("created_by"):
            u = await tenant.users.find_one({"id": v["created_by"]}, {"_id": 0, "first_name": 1, "last_name": 1})
            v["created_by_name"] = f"{u['first_name']} {u['last_name']}" if u else "Unknown"
        else:
            v["created_by_name"] = ""
    
    return {"items": versions, "total": len(versions)}


@router.post("/offers/{offer_id}/versions", status_code=201)
@strip_money_for_non_finance   # OFF-02 FG-350 (R20): a write answers like the read
async def create_offer_version(offer_id: str, data: VersionCreate,
                               _r67: dict = Depends(require_money_write(
                                   "offers.offer_snapshot.create", module="M2", resource_type="offer")),  # OFF-02 R67: Owner/Admin/Accountant only
                               user: dict = Depends(get_current_user)):
    """Create a new version (snapshot) of the current offer state."""
    tenant = _tenant(user)
    # OFF-02 R67: the role is the route's gate (Owner / Admin / Accountant)
    
    offer = await tenant.offers.find_one({"id": offer_id, "org_id": user["org_id"]})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    
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
    
    await tenant.offer_versions.insert_one(version)
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
@strip_money_for_non_finance   # SEC-02-A (R20-5M, D1)
async def get_offer_version(offer_id: str, version_number: int, user: dict = Depends(get_current_user)):
    """Get a specific version snapshot for preview."""
    tenant = _tenant(user)
    offer = await tenant.offers.find_one({"id": offer_id, "org_id": user["org_id"]})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    
    if not await can_manage_project(user, offer["project_id"]):
        raise HTTPException(status_code=403, detail="Access denied")
    
    version = await tenant.offer_versions.find_one(
        {"org_id": user["org_id"], "offer_id": offer_id, "version_number": version_number},
        {"_id": 0}
    )
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    
    # Enrich with creator name
    if version.get("created_by"):
        u = await tenant.users.find_one({"id": version["created_by"]}, {"_id": 0, "first_name": 1, "last_name": 1})
        version["created_by_name"] = f"{u['first_name']} {u['last_name']}" if u else "Unknown"
    
    return version


@router.post("/offers/{offer_id}/versions/{version_number}/restore")
@strip_money_for_non_finance   # OFF-02 FG-350 (R20): a write answers like the read
async def restore_offer_version(offer_id: str, version_number: int,
                                _r67: dict = Depends(require_money_write(
                                    "offers.offer_snapshot_restore.execute", module="M2", resource_type="offer")),  # OFF-02 R67: Owner/Admin/Accountant only
                                user: dict = Depends(get_current_user)):
    """
    Restore an offer to a specific version.
    - Creates an automatic backup version BEFORE restore
    - Overwrites current offer with the snapshot data
    """
    tenant = _tenant(user)
    # OFF-02 R67: the role is the route's gate (Owner / Admin / Accountant)
    
    offer = await tenant.offers.find_one({"id": offer_id, "org_id": user["org_id"]})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    
    _refuse_if_used(offer, await _draft_was_used(tenant, offer))
    
    # Get the version to restore
    version = await tenant.offer_versions.find_one(
        {"org_id": user["org_id"], "offer_id": offer_id, "version_number": version_number}
    )
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    
    now = datetime.now(timezone.utc).isoformat()
    
    # Step 1: Restore the snapshot to the current offer (one CAS, below)
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
        computed_lines = [compute_offer_line(line) for line in update_data["lines"]]
        update_data["lines"] = computed_lines
        subtotal = sum(line.get("line_total", 0) for line in computed_lines)
        vat_amount = round(subtotal * update_data.get("vat_percent", 0) / 100, 2)
        update_data["subtotal"] = round(subtotal, 2)
        update_data["vat_amount"] = vat_amount
        update_data["total"] = round(subtotal + vat_amount, 2)
    
    # OFF79-03: the restore is a CAS on the exact unsent draft that was read; a /send (or
    # another write) that slipped in → 409, nothing restored, no backup written.
    won = await tenant.offers.update_one(
        {"id": offer_id, "status": "Draft", "sent_at": None, "superseded_by": None,
         "updated_at": offer.get("updated_at")}, {"$set": update_data})
    if won.modified_count != 1:
        raise HTTPException(status_code=409, detail={
            "error_code": "OFFER_IN_USE",
            "message": "Офертата вече е изпратена или променена — презаредете"})

    # Step 2: the automatic backup of the state as it was before the restore
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
    await tenant.offer_versions.insert_one(backup)
    
    await log_audit(user["org_id"], user["id"], user["email"], "version_restored", "offer", offer_id, {
        "restored_version": version_number,
        "backup_version": backup_version_number,
    })
    
    # Return the updated offer
    updated_offer = await tenant.offers.find_one({"id": offer_id}, {"_id": 0})
    
    return {
        "ok": True,
        "restored_version": version_number,
        "backup_version": backup_version_number,
        "offer": updated_offer,
    }


@router.delete("/offers/{offer_id}/versions/{version_number}")
async def delete_offer_version(offer_id: str, version_number: int,
                               _r67: dict = Depends(require_money_write(
                                   "offers.offer_snapshot.delete", module="M2", resource_type="offer")),  # OFF-02 R67: Owner/Admin/Accountant only
                               user: dict = Depends(get_current_user)):
    """Delete a specific version (admin only, cannot delete if it's the only version)."""
    tenant = _tenant(user)
    # OFF-02 R67: the role is the route's gate (Owner / Admin / Accountant)
    
    offer = await tenant.offers.find_one({"id": offer_id, "org_id": user["org_id"]})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    _refuse_if_used(offer, await _draft_was_used(tenant, offer))
    
    version = await tenant.offer_versions.find_one(
        {"org_id": user["org_id"], "offer_id": offer_id, "version_number": version_number}
    )
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    
    # Don't allow deleting if it's the only version
    count = await tenant.offer_versions.count_documents({"org_id": user["org_id"], "offer_id": offer_id})
    if count <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the only remaining version")
    
    await tenant.offer_versions.delete_one({"id": version["id"]})
    await log_audit(user["org_id"], user["id"], user["email"], "version_deleted", "offer_version", version["id"], {
        "version_number": version_number
    })
    
    return {"ok": True}
