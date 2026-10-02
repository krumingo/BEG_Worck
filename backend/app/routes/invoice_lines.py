"""
Routes - Invoice Lines (separate collection for detailed tracking and allocation).
Supports multi-allocation: split quantities across multiple projects/warehouses/clients.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, List
from datetime import datetime, timezone
import uuid

from app.db import db
from app.tenancy.data_access import TenantData
from app.deps.auth import get_current_user
from app.deps.modules import require_m5
from app.utils.audit import log_audit
from ..models.invoice_lines import (
    ALLOCATION_TYPES,
    AllocationItem,
    InvoiceLineCreate, InvoiceLineUpdate, 
    InvoiceLineBulkCreate, InvoiceLineAllocationsUpdate,
    InvoiceLineAllocationUpdate  # DEPRECATED
)

router = APIRouter(tags=["InvoiceLines"])


def _tenant(user: dict) -> TenantData:
    """The request's tenant — from the server-loaded session user only.

    W0-03E-A2C: every read, enrichment and write below goes through this view, so
    the tenant predicate is part of the query rather than something a later line
    has to remember. The W0-03E-A2B review found this module resolving buyers,
    projects, warehouses, persons and companies by bare ``id`` and updating
    invoices and lines by bare ``id`` after a scoped read — with colliding ids
    that returned and modified ANOTHER tenant's financial records.
    """
    return TenantData.for_user(db, user)


def finance_permission(user: dict) -> bool:
    """Check if user has finance access"""
    return user["role"] in ["Admin", "Owner", "Accountant"]


def compute_line_totals(line: dict) -> dict:
    """Compute line totals including VAT"""
    qty = line.get("qty", 1) or 1
    unit_price = line.get("unit_price", 0) or 0
    vat_percent = line.get("vat_percent", 20) or 0
    
    line_total_ex_vat = round(qty * unit_price, 2)
    vat_amount = round(line_total_ex_vat * vat_percent / 100, 2)
    line_total_inc_vat = round(line_total_ex_vat + vat_amount, 2)
    
    line["line_total_ex_vat"] = line_total_ex_vat
    line["vat_amount"] = vat_amount
    line["line_total_inc_vat"] = line_total_inc_vat
    
    return line


def normalize_allocations(line: dict) -> dict:
    """
    Backward compatibility: Convert old allocation_type/allocation_ref_id to allocations[]
    """
    if line.get("allocations"):
        # Already has new format
        return line
    
    # Check for deprecated fields
    if line.get("allocation_type") and line.get("allocation_ref_id"):
        # Convert to new format
        line["allocations"] = [{
            "type": line["allocation_type"],
            "ref_id": line["allocation_ref_id"],
            "qty": line.get("qty", 1),
            "note": None
        }]
    else:
        line["allocations"] = []
    
    return line


def normalize_allocation_keys(alloc: dict) -> dict:
    """
    Normalize allocation keys: accept both refId (camelCase) and ref_id (snake_case).
    Always return ref_id only.
    """
    if isinstance(alloc, dict):
        # If refId exists but ref_id doesn't, copy it
        if 'refId' in alloc and 'ref_id' not in alloc:
            alloc['ref_id'] = alloc['refId']
        # Remove refId to ensure clean response
        alloc.pop('refId', None)
    return alloc


def normalize_allocations_list(allocations: list) -> list:
    """Normalize all allocations in a list"""
    return [normalize_allocation_keys(a) for a in allocations] if allocations else []


def compute_allocation_stats(line: dict) -> dict:
    """Compute allocation statistics for a line"""
    # First normalize allocations
    if line.get("allocations"):
        line["allocations"] = normalize_allocations_list(line["allocations"])
    
    allocations = line.get("allocations", [])
    qty_purchased = line.get("qty", 0)
    qty_allocated = sum(a.get("qty", 0) for a in allocations)
    qty_unallocated = max(0, qty_purchased - qty_allocated)
    
    line["qty_purchased"] = qty_purchased
    line["qty_allocated"] = round(qty_allocated, 4)
    line["qty_unallocated"] = round(qty_unallocated, 4)
    line["is_fully_allocated"] = qty_unallocated <= 0.0001  # Float tolerance
    
    return line


async def validate_allocation_refs(tenant: TenantData, allocations: List[dict]):
    """Validate that all allocation references exist IN THIS TENANT.

    A ref that exists only in another tenant is "not found" here, so an
    allocation can never point across the boundary.
    """
    for alloc in allocations:
        alloc_type = alloc.get("type")
        ref_id = alloc.get("ref_id")
        
        if alloc_type == "project":
            ref = await tenant.projects.get(ref_id)
            if not ref:
                raise HTTPException(status_code=404, detail=f"Project {ref_id} not found")
        elif alloc_type == "warehouse":
            ref = await tenant.warehouses.get(ref_id)
            if not ref:
                raise HTTPException(status_code=404, detail=f"Warehouse {ref_id} not found")
        elif alloc_type == "client":
            # Check in persons or companies
            ref = await tenant.persons.get(ref_id)
            if not ref:
                ref = await tenant.companies.get(ref_id)
            if not ref:
                raise HTTPException(status_code=404, detail=f"Client {ref_id} not found")


async def get_org_require_full_allocation(tenant: TenantData) -> bool:
    """Get THIS tenant's requireFullAllocation setting (its own organization row)."""
    org = await tenant.own_organization({"_id": 0, "require_full_allocation": 1})
    return org.get("require_full_allocation", False) if org else False


async def recalculate_invoice_totals(tenant: TenantData, invoice_id: str):
    """Recalculate THIS tenant's invoice totals from its own lines.

    Both the invoice read and the invoice write carry the tenant predicate. The
    write filter in particular: a scoped read of the lines said nothing about
    which tenant's invoice ``{"id": invoice_id}`` alone would have updated.
    """
    lines = await tenant.invoice_lines.find({"invoice_id": invoice_id}).to_list(1000)
    
    subtotal = sum(l.get("line_total_ex_vat", 0) for l in lines)
    vat_total = sum(l.get("vat_amount", 0) for l in lines)
    total = round(subtotal + vat_total, 2)
    
    invoice = await tenant.invoices.get(invoice_id)
    paid_amount = invoice.get("paid_amount", 0) if invoice else 0
    
    await tenant.invoices.update_one({"id": invoice_id}, {"$set": {
        "subtotal": round(subtotal, 2),
        "vat_amount": round(vat_total, 2),
        "total": total,
        "remaining_amount": max(0, round(total - paid_amount, 2)),
        "lines_count": len(lines),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }})


async def enrich_line_with_names(tenant: TenantData, line: dict) -> dict:
    """Enrich line with human-readable names, resolved IN THIS TENANT only.

    A name that exists only in another tenant resolves to ``""`` (absent), never
    to that tenant's value — this is the enrichment leak the A2B review
    reproduced for buyer, project, warehouse, person and company.
    """
    if line.get("purchased_by_user_id"):
        buyer = await tenant.users.get(line["purchased_by_user_id"],
                                       {"_id": 0, "first_name": 1, "last_name": 1})
        line["purchased_by_name"] = f"{buyer['first_name']} {buyer['last_name']}" if buyer else ""
    
    # Enrich allocations
    allocations = line.get("allocations", [])
    for alloc in allocations:
        alloc_type = alloc.get("type")
        ref_id = alloc.get("ref_id")
        
        if alloc_type == "project":
            ref = await tenant.projects.get(ref_id, {"_id": 0, "code": 1, "name": 1})
            alloc["ref_name"] = f"{ref['code']} - {ref['name']}" if ref else ""
        elif alloc_type == "warehouse":
            ref = await tenant.warehouses.get(ref_id, {"_id": 0, "code": 1, "name": 1})
            alloc["ref_name"] = f"{ref['code']} - {ref['name']}" if ref else ""
        elif alloc_type == "client":
            ref = await tenant.persons.get(ref_id, {"_id": 0, "first_name": 1, "last_name": 1})
            if ref:
                alloc["ref_name"] = f"{ref['first_name']} {ref['last_name']}"
            else:
                ref = await tenant.companies.get(ref_id, {"_id": 0, "name": 1})
                alloc["ref_name"] = ref["name"] if ref else ""
    
    return line


# ── Invoice Lines CRUD ─────────────────────────────────────────────

@router.get("/invoice-lines")
async def list_invoice_lines(
    user: dict = Depends(require_m5),
    invoice_id: Optional[str] = None,
    allocation_type: Optional[str] = None,
    allocation_ref_id: Optional[str] = None,
    purchased_by: Optional[str] = None,
    unallocated_only: bool = False,
):
    """List invoice lines with filters"""
    tenant = _tenant(user)
    if not invoice_id and not allocation_ref_id and not unallocated_only:
        raise HTTPException(status_code=400, detail="Must specify invoice_id, allocation_ref_id, or unallocated_only")
    
    query = {"org_id": user["org_id"]}
    
    if invoice_id:
        query["invoice_id"] = invoice_id
    if purchased_by:
        query["purchased_by_user_id"] = purchased_by
    
    # For allocation queries, we need to search in allocations[] array
    if allocation_type and allocation_ref_id:
        query["allocations"] = {
            "$elemMatch": {
                "type": allocation_type,
                "ref_id": allocation_ref_id
            }
        }
    
    lines = await tenant.invoice_lines.find(query, {"_id": 0}).sort("line_no", 1).to_list(1000)
    
    # Normalize and compute stats
    result = []
    for line in lines:
        line = normalize_allocations(line)
        line = compute_allocation_stats(line)
        
        # Filter unallocated if requested
        if unallocated_only and line["is_fully_allocated"]:
            continue
        
        await enrich_line_with_names(tenant, line)
        result.append(line)
    
    return result


# ── Static routes (must come before /{line_id}) ─────────────────────

@router.get("/invoice-lines/unallocated")
async def get_unallocated_lines(user: dict = Depends(require_m5)):
    """Get all invoice lines that are not fully allocated"""
    tenant = _tenant(user)
    lines = await tenant.invoice_lines.find(
        {"org_id": user["org_id"], "is_fully_allocated": {"$ne": True}},
        {"_id": 0}
    ).to_list(1000)
    
    result = []
    for line in lines:
        line = normalize_allocations(line)
        line = compute_allocation_stats(line)
        
        # Only include if really not fully allocated
        if not line.get("is_fully_allocated", False):
            invoice = await tenant.invoices.find_one({"id": line["invoice_id"]}, {"_id": 0, "invoice_no": 1, "issue_date": 1})
            if invoice:
                line["invoice_no"] = invoice["invoice_no"]
                line["invoice_date"] = invoice["issue_date"]
            result.append(line)
    
    return {
        "count": len(result),
        "lines": result
    }


@router.get("/invoice-lines/enums")
async def get_invoice_line_enums():
    """Get available enum values"""
    return {
        "allocation_types": ALLOCATION_TYPES,
        "cost_categories": ["Materials", "Labor", "Subcontract", "Other"],
    }


# ── CRUD routes ────────────────────────────────────────────────────

@router.post("/invoice-lines", status_code=201)
async def create_invoice_line(data: InvoiceLineCreate, user: dict = Depends(require_m5)):
    """Create a single invoice line"""
    tenant = _tenant(user)
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    # Verify invoice exists
    invoice = await tenant.invoices.find_one({"id": data.invoice_id, "org_id": user["org_id"]})
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    if invoice["status"] not in ["Draft"]:
        raise HTTPException(status_code=400, detail="Can only add lines to Draft invoices")
    
    # Process allocations
    allocations = []
    if data.allocations:
        # Validate sum of allocated qty
        total_allocated = sum(a.qty for a in data.allocations)
        if total_allocated > data.qty:
            raise HTTPException(status_code=400, detail=f"Allocated qty ({total_allocated}) exceeds purchased qty ({data.qty})")
        
        # Check if full allocation required
        require_full = await get_org_require_full_allocation(tenant)
        if require_full and abs(total_allocated - data.qty) > 0.0001:
            raise HTTPException(status_code=400, detail=f"Full allocation required. Allocated: {total_allocated}, Required: {data.qty}")
        
        # Validate refs
        allocs_dict = [a.model_dump() for a in data.allocations]
        await validate_allocation_refs(tenant, allocs_dict)
        allocations = allocs_dict
    elif data.allocation_type and data.allocation_ref_id:
        # Backward compatibility: convert old format
        await validate_allocation_refs(tenant, [{"type": data.allocation_type, "ref_id": data.allocation_ref_id}])
        allocations = [{
            "type": data.allocation_type,
            "ref_id": data.allocation_ref_id,
            "qty": data.qty,
            "note": None
        }]
    
    now = datetime.now(timezone.utc).isoformat()
    line = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "invoice_id": data.invoice_id,
        "line_no": data.line_no,
        "description": data.description,
        "unit": data.unit,
        "qty": data.qty,
        "unit_price": data.unit_price,
        "vat_percent": data.vat_percent,
        "purchased_by_user_id": data.purchased_by_user_id,
        "allocations": allocations,
        # DEPRECATED fields (kept for queries)
        "allocation_type": data.allocation_type,
        "allocation_ref_id": data.allocation_ref_id,
        "cost_category": data.cost_category,
        "scan_line_ref": data.scan_line_ref.model_dump() if data.scan_line_ref else None,
        "notes": data.notes,
        "created_at": now,
        "updated_at": now,
    }
    line = compute_line_totals(line)
    line = compute_allocation_stats(line)
    
    await tenant.invoice_lines.insert_one(line)
    
    # Recalculate invoice totals
    await recalculate_invoice_totals(tenant, data.invoice_id)
    
    return {k: v for k, v in line.items() if k != "_id"}


@router.post("/invoice-lines/bulk", status_code=201)
async def create_invoice_lines_bulk(data: InvoiceLineBulkCreate, user: dict = Depends(require_m5)):
    """Create multiple invoice lines at once"""
    tenant = _tenant(user)
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    if not data.lines:
        raise HTTPException(status_code=400, detail="No lines provided")
    
    # All lines must be for the same invoice
    invoice_ids = set(l.invoice_id for l in data.lines)
    if len(invoice_ids) > 1:
        raise HTTPException(status_code=400, detail="All lines must be for the same invoice")
    
    invoice_id = data.lines[0].invoice_id
    invoice = await tenant.invoices.find_one({"id": invoice_id, "org_id": user["org_id"]})
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    if invoice["status"] not in ["Draft"]:
        raise HTTPException(status_code=400, detail="Can only add lines to Draft invoices")
    
    require_full = await get_org_require_full_allocation(tenant)
    now = datetime.now(timezone.utc).isoformat()
    created_lines = []
    
    for line_data in data.lines:
        # Process allocations
        allocations = []
        if line_data.allocations:
            total_allocated = sum(a.qty for a in line_data.allocations)
            if total_allocated > line_data.qty:
                raise HTTPException(status_code=400, detail=f"Line {line_data.line_no}: Allocated qty ({total_allocated}) exceeds purchased qty ({line_data.qty})")
            
            if require_full and abs(total_allocated - line_data.qty) > 0.0001:
                raise HTTPException(status_code=400, detail=f"Line {line_data.line_no}: Full allocation required")
            
            allocs_dict = [a.model_dump() for a in line_data.allocations]
            await validate_allocation_refs(tenant, allocs_dict)
            allocations = allocs_dict
        elif line_data.allocation_type and line_data.allocation_ref_id:
            await validate_allocation_refs(tenant, [{"type": line_data.allocation_type, "ref_id": line_data.allocation_ref_id}])
            allocations = [{
                "type": line_data.allocation_type,
                "ref_id": line_data.allocation_ref_id,
                "qty": line_data.qty,
                "note": None
            }]
        
        line = {
            "id": str(uuid.uuid4()),
            "org_id": user["org_id"],
            "invoice_id": line_data.invoice_id,
            "line_no": line_data.line_no,
            "description": line_data.description,
            "unit": line_data.unit,
            "qty": line_data.qty,
            "unit_price": line_data.unit_price,
            "vat_percent": line_data.vat_percent,
            "purchased_by_user_id": line_data.purchased_by_user_id,
            "allocations": allocations,
            "allocation_type": line_data.allocation_type,
            "allocation_ref_id": line_data.allocation_ref_id,
            "cost_category": line_data.cost_category,
            "scan_line_ref": line_data.scan_line_ref.model_dump() if line_data.scan_line_ref else None,
            "notes": line_data.notes,
            "created_at": now,
            "updated_at": now,
        }
        line = compute_line_totals(line)
        line = compute_allocation_stats(line)
        created_lines.append(line)
    
    if created_lines:
        await tenant.invoice_lines.insert_many(created_lines)
        await recalculate_invoice_totals(tenant, invoice_id)
    
    return {"ok": True, "count": len(created_lines), "lines": [{k: v for k, v in l.items() if k != "_id"} for l in created_lines]}


@router.get("/invoice-lines/{line_id}")
async def get_invoice_line(line_id: str, user: dict = Depends(require_m5)):
    """Get invoice line details"""
    tenant = _tenant(user)
    line = await tenant.invoice_lines.find_one({"id": line_id, "org_id": user["org_id"]}, {"_id": 0})
    if not line:
        raise HTTPException(status_code=404, detail="Invoice line not found")
    
    line = normalize_allocations(line)
    line = compute_allocation_stats(line)
    await enrich_line_with_names(tenant, line)
    
    # Get invoice info
    invoice = await tenant.invoices.find_one({"id": line["invoice_id"]}, {"_id": 0, "invoice_no": 1, "direction": 1, "status": 1})
    if invoice:
        line["invoice_no"] = invoice["invoice_no"]
        line["invoice_direction"] = invoice["direction"]
        line["invoice_status"] = invoice["status"]
    
    return line


@router.put("/invoice-lines/{line_id}")
async def update_invoice_line(line_id: str, data: InvoiceLineUpdate, user: dict = Depends(require_m5)):
    """Update invoice line"""
    tenant = _tenant(user)
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    line = await tenant.invoice_lines.find_one({"id": line_id, "org_id": user["org_id"]})
    if not line:
        raise HTTPException(status_code=404, detail="Invoice line not found")
    
    # Check invoice status
    invoice = await tenant.invoices.find_one({"id": line["invoice_id"]})
    if invoice and invoice["status"] not in ["Draft"]:
        raise HTTPException(status_code=400, detail="Can only edit lines of Draft invoices")
    
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    
    # Handle allocations update
    if "allocations" in update and update["allocations"]:
        qty = update.get("qty", line.get("qty", 1))
        allocs = update["allocations"]
        total_allocated = sum(a["qty"] for a in allocs)
        
        if total_allocated > qty:
            raise HTTPException(status_code=400, detail=f"Allocated qty ({total_allocated}) exceeds purchased qty ({qty})")
        
        require_full = await get_org_require_full_allocation(tenant)
        if require_full and abs(total_allocated - qty) > 0.0001:
            raise HTTPException(status_code=400, detail=f"Full allocation required. Allocated: {total_allocated}, Required: {qty}")
        
        await validate_allocation_refs(tenant, allocs)
        update["allocations"] = [a if isinstance(a, dict) else a.model_dump() for a in allocs]
    
    # Handle scan_line_ref
    if "scan_line_ref" in update and update["scan_line_ref"]:
        update["scan_line_ref"] = update["scan_line_ref"] if isinstance(update["scan_line_ref"], dict) else update["scan_line_ref"].model_dump()
    
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    # Merge and recompute
    merged = {**line, **update}
    merged = compute_line_totals(merged)
    merged = compute_allocation_stats(merged)
    
    await tenant.invoice_lines.update_one({"id": line_id}, {"$set": {
        **update,
        "line_total_ex_vat": merged["line_total_ex_vat"],
        "vat_amount": merged["vat_amount"],
        "line_total_inc_vat": merged["line_total_inc_vat"],
        "qty_allocated": merged.get("qty_allocated", 0),
        "qty_unallocated": merged.get("qty_unallocated", 0),
        "is_fully_allocated": merged.get("is_fully_allocated", False),
    }})
    
    # Recalculate invoice
    await recalculate_invoice_totals(tenant, line["invoice_id"])
    
    result = await tenant.invoice_lines.find_one({"id": line_id}, {"_id": 0})
    result = normalize_allocations(result)
    result = compute_allocation_stats(result)
    return result


@router.post("/invoice-lines/{line_id}/allocate")
async def allocate_invoice_line(line_id: str, data: InvoiceLineAllocationsUpdate, user: dict = Depends(require_m5)):
    """
    Update allocations for an invoice line.
    Replaces ALL existing allocations with the new set.
    Supports splitting qty across multiple projects/warehouses/clients.
    """
    tenant = _tenant(user)
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    line = await tenant.invoice_lines.find_one({"id": line_id, "org_id": user["org_id"]})
    if not line:
        raise HTTPException(status_code=404, detail="Invoice line not found")
    
    qty_purchased = line.get("qty", 0)
    
    # Validate allocations
    allocs = [a.model_dump() for a in data.allocations]
    total_allocated = sum(a["qty"] for a in allocs)
    
    if total_allocated > qty_purchased:
        raise HTTPException(
            status_code=400, 
            detail=f"Total allocated qty ({total_allocated}) exceeds purchased qty ({qty_purchased})"
        )
    
    # Check if full allocation required
    require_full = await get_org_require_full_allocation(tenant)
    if require_full and abs(total_allocated - qty_purchased) > 0.0001:
        raise HTTPException(
            status_code=400, 
            detail=f"Full allocation required by organization settings. Allocated: {total_allocated}, Required: {qty_purchased}. Unallocated: {qty_purchased - total_allocated}"
        )
    
    # Validate all refs exist
    await validate_allocation_refs(tenant, allocs)
    
    now = datetime.now(timezone.utc).isoformat()
    
    await tenant.invoice_lines.update_one({"id": line_id}, {"$set": {
        "allocations": allocs,
        "qty_allocated": round(total_allocated, 4),
        "qty_unallocated": round(qty_purchased - total_allocated, 4),
        "is_fully_allocated": abs(total_allocated - qty_purchased) <= 0.0001,
        "updated_at": now,
    }})
    
    await log_audit(user["org_id"], user["id"], user["email"], "invoice_line_allocated", "invoice_line", line_id,
                    {"allocations_count": len(allocs), "total_allocated": total_allocated})
    
    result = await tenant.invoice_lines.find_one({"id": line_id}, {"_id": 0})
    result = normalize_allocations(result)
    result = compute_allocation_stats(result)
    await enrich_line_with_names(tenant, result)
    
    return result


@router.delete("/invoice-lines/{line_id}")
async def delete_invoice_line(line_id: str, user: dict = Depends(require_m5)):
    """Delete invoice line"""
    tenant = _tenant(user)
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    line = await tenant.invoice_lines.find_one({"id": line_id, "org_id": user["org_id"]})
    if not line:
        raise HTTPException(status_code=404, detail="Invoice line not found")
    
    # Check invoice status
    invoice = await tenant.invoices.find_one({"id": line["invoice_id"]})
    if invoice and invoice["status"] not in ["Draft"]:
        raise HTTPException(status_code=400, detail="Can only delete lines of Draft invoices")
    
    invoice_id = line["invoice_id"]
    await tenant.invoice_lines.delete_one({"id": line_id})
    
    # Recalculate invoice
    await recalculate_invoice_totals(tenant, invoice_id)
    
    return {"ok": True}


# ── Allocation Reports (using aggregation) ─────────────────────────

@router.get("/invoice-lines/by-project/{project_id}")
async def get_lines_by_project(project_id: str, user: dict = Depends(require_m5)):
    """
    Get all invoice line allocations for a specific project.
    Uses aggregation to properly handle multi-allocation.
    """
    tenant = _tenant(user)
    # Verify project exists
    project = await tenant.projects.find_one({"id": project_id, "org_id": user["org_id"]}, {"_id": 0, "code": 1, "name": 1})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Aggregate: unwind allocations, filter by project, compute totals
    pipeline = [
        {"$match": {"org_id": user["org_id"]}},
        {"$unwind": "$allocations"},
        {"$match": {"allocations.type": "project", "allocations.ref_id": project_id}},
        {"$project": {
            "_id": 0,
            "line_id": "$id",
            "invoice_id": 1,
            "line_no": 1,
            "description": 1,
            "unit": 1,
            "unit_price": 1,
            "vat_percent": 1,
            "cost_category": 1,
            "purchased_by_user_id": 1,
            "allocated_qty": "$allocations.qty",
            "allocation_note": "$allocations.note",
            "line_total_ex_vat": 1,
            "created_at": 1,
        }},
        {"$sort": {"created_at": -1}}
    ]
    
    lines = await tenant.invoice_lines.aggregate(pipeline).to_list(1000)
    
    # Calculate totals based on allocated qty proportion
    total_ex_vat = 0
    total_vat = 0
    
    for line in lines:
        # Proportional cost based on allocated qty
        alloc_qty = line.get("allocated_qty", 0)
        unit_price = line.get("unit_price", 0)
        vat_percent = line.get("vat_percent", 0)
        
        line_value = round(alloc_qty * unit_price, 2)
        line_vat = round(line_value * vat_percent / 100, 2)
        
        line["allocated_value_ex_vat"] = line_value
        line["allocated_vat"] = line_vat
        line["allocated_value_inc_vat"] = round(line_value + line_vat, 2)
        
        total_ex_vat += line_value
        total_vat += line_vat
        
        # Get invoice info
        invoice = await tenant.invoices.find_one({"id": line["invoice_id"]}, {"_id": 0, "invoice_no": 1, "issue_date": 1, "direction": 1})
        if invoice:
            line["invoice_no"] = invoice["invoice_no"]
            line["invoice_date"] = invoice["issue_date"]
            line["invoice_direction"] = invoice["direction"]
        
        # Get purchaser name
        if line.get("purchased_by_user_id"):
            buyer = await tenant.users.find_one({"id": line["purchased_by_user_id"]}, {"_id": 0, "first_name": 1, "last_name": 1})
            line["purchased_by_name"] = f"{buyer['first_name']} {buyer['last_name']}" if buyer else ""
    
    return {
        "project_id": project_id,
        "project_code": project["code"],
        "project_name": project["name"],
        "allocations": lines,
        "count": len(lines),
        "total_ex_vat": round(total_ex_vat, 2),
        "total_vat": round(total_vat, 2),
        "total_inc_vat": round(total_ex_vat + total_vat, 2),
    }


@router.get("/invoice-lines/by-warehouse/{warehouse_id}")
async def get_lines_by_warehouse(warehouse_id: str, user: dict = Depends(require_m5)):
    """
    Get all invoice line allocations for a specific warehouse.
    Uses aggregation to properly handle multi-allocation.
    """
    tenant = _tenant(user)
    # Verify warehouse exists
    warehouse = await tenant.warehouses.find_one({"id": warehouse_id, "org_id": user["org_id"]}, {"_id": 0, "code": 1, "name": 1})
    if not warehouse:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    
    pipeline = [
        {"$match": {"org_id": user["org_id"]}},
        {"$unwind": "$allocations"},
        {"$match": {"allocations.type": "warehouse", "allocations.ref_id": warehouse_id}},
        {"$project": {
            "_id": 0,
            "line_id": "$id",
            "invoice_id": 1,
            "line_no": 1,
            "description": 1,
            "unit": 1,
            "unit_price": 1,
            "vat_percent": 1,
            "cost_category": 1,
            "purchased_by_user_id": 1,
            "allocated_qty": "$allocations.qty",
            "allocation_note": "$allocations.note",
            "created_at": 1,
        }},
        {"$sort": {"created_at": -1}}
    ]
    
    lines = await tenant.invoice_lines.aggregate(pipeline).to_list(1000)
    
    total_ex_vat = 0
    total_vat = 0
    
    for line in lines:
        alloc_qty = line.get("allocated_qty", 0)
        unit_price = line.get("unit_price", 0)
        vat_percent = line.get("vat_percent", 0)
        
        line_value = round(alloc_qty * unit_price, 2)
        line_vat = round(line_value * vat_percent / 100, 2)
        
        line["allocated_value_ex_vat"] = line_value
        line["allocated_vat"] = line_vat
        line["allocated_value_inc_vat"] = round(line_value + line_vat, 2)
        
        total_ex_vat += line_value
        total_vat += line_vat
        
        invoice = await tenant.invoices.find_one({"id": line["invoice_id"]}, {"_id": 0, "invoice_no": 1, "issue_date": 1, "direction": 1})
        if invoice:
            line["invoice_no"] = invoice["invoice_no"]
            line["invoice_date"] = invoice["issue_date"]
            line["invoice_direction"] = invoice["direction"]
    
    return {
        "warehouse_id": warehouse_id,
        "warehouse_code": warehouse["code"],
        "warehouse_name": warehouse["name"],
        "allocations": lines,
        "count": len(lines),
        "total_ex_vat": round(total_ex_vat, 2),
        "total_vat": round(total_vat, 2),
        "total_inc_vat": round(total_ex_vat + total_vat, 2),
    }


@router.get("/invoice-lines/by-client/{client_id}")
async def get_lines_by_client(client_id: str, user: dict = Depends(require_m5)):
    """
    Get all invoice line allocations for a specific client (person or company).
    Uses aggregation to properly handle multi-allocation.
    """
    tenant = _tenant(user)
    # Check if client exists (person or company)
    client = await tenant.persons.find_one({"id": client_id, "org_id": user["org_id"]}, {"_id": 0, "first_name": 1, "last_name": 1})
    client_name = f"{client['first_name']} {client['last_name']}" if client else None
    client_type = "person" if client else None
    
    if not client:
        client = await tenant.companies.find_one({"id": client_id, "org_id": user["org_id"]}, {"_id": 0, "name": 1})
        client_name = client["name"] if client else None
        client_type = "company" if client else None
    
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    pipeline = [
        {"$match": {"org_id": user["org_id"]}},
        {"$unwind": "$allocations"},
        {"$match": {"allocations.type": "client", "allocations.ref_id": client_id}},
        {"$project": {
            "_id": 0,
            "line_id": "$id",
            "invoice_id": 1,
            "line_no": 1,
            "description": 1,
            "unit": 1,
            "unit_price": 1,
            "vat_percent": 1,
            "cost_category": 1,
            "purchased_by_user_id": 1,
            "allocated_qty": "$allocations.qty",
            "allocation_note": "$allocations.note",
            "created_at": 1,
        }},
        {"$sort": {"created_at": -1}}
    ]
    
    lines = await tenant.invoice_lines.aggregate(pipeline).to_list(1000)
    
    total_ex_vat = 0
    total_vat = 0
    
    for line in lines:
        alloc_qty = line.get("allocated_qty", 0)
        unit_price = line.get("unit_price", 0)
        vat_percent = line.get("vat_percent", 0)
        
        line_value = round(alloc_qty * unit_price, 2)
        line_vat = round(line_value * vat_percent / 100, 2)
        
        line["allocated_value_ex_vat"] = line_value
        line["allocated_vat"] = line_vat
        line["allocated_value_inc_vat"] = round(line_value + line_vat, 2)
        
        total_ex_vat += line_value
        total_vat += line_vat
        
        invoice = await tenant.invoices.find_one({"id": line["invoice_id"]}, {"_id": 0, "invoice_no": 1, "issue_date": 1, "direction": 1})
        if invoice:
            line["invoice_no"] = invoice["invoice_no"]
            line["invoice_date"] = invoice["issue_date"]
            line["invoice_direction"] = invoice["direction"]
    
    return {
        "client_id": client_id,
        "client_name": client_name,
        "client_type": client_type,
        "allocations": lines,
        "count": len(lines),
        "total_ex_vat": round(total_ex_vat, 2),
        "total_vat": round(total_vat, 2),
        "total_inc_vat": round(total_ex_vat + total_vat, 2),
    }


@router.get("/invoice-lines/by-purchaser/{user_id}")
async def get_lines_by_purchaser(user_id: str, user: dict = Depends(require_m5)):
    """Get all invoice lines purchased by a specific user (driver/employee)"""
    tenant = _tenant(user)
    lines = await tenant.invoice_lines.find({
        "org_id": user["org_id"],
        "purchased_by_user_id": user_id
    }, {"_id": 0}).to_list(1000)
    
    # Get purchaser name
    purchaser = await tenant.users.find_one({"id": user_id}, {"_id": 0, "first_name": 1, "last_name": 1})
    purchaser_name = f"{purchaser['first_name']} {purchaser['last_name']}" if purchaser else ""
    
    total_ex_vat = 0
    total_vat = 0
    
    for line in lines:
        line = normalize_allocations(line)
        line = compute_allocation_stats(line)
        
        total_ex_vat += line.get("line_total_ex_vat", 0)
        total_vat += line.get("vat_amount", 0)
        
        invoice = await tenant.invoices.find_one({"id": line["invoice_id"]}, {"_id": 0, "invoice_no": 1, "issue_date": 1, "direction": 1})
        if invoice:
            line["invoice_no"] = invoice["invoice_no"]
            line["invoice_date"] = invoice["issue_date"]
            line["invoice_direction"] = invoice["direction"]
    
    return {
        "user_id": user_id,
        "purchaser_name": purchaser_name,
        "lines": lines,
        "count": len(lines),
        "total_ex_vat": round(total_ex_vat, 2),
        "total_vat": round(total_vat, 2),
        "total_inc_vat": round(total_ex_vat + total_vat, 2),
    }
