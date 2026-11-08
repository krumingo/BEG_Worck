"""
Routes - Invoice Lines (separate collection for detailed tracking and allocation).
Supports multi-allocation: split quantities across multiple projects/warehouses/clients.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, List
from datetime import datetime, timezone
import uuid

from app.db import db
from app.services.invoice_line_lock import (
    InvoiceLineAllocationLocked, run_transaction, write_unless_linked,
)
from app.services.invoice_state import NOT_DRAFT, STATUS_CHANGED, claim_invoice

# WHFIX81-06 — an invoice with money paid on it is an official record: its
# allocation changes only as a correction (reason, version, AuditEvent).
ALLOCATION_CORRECTION_REQUIRED = "ALLOCATION_CORRECTION_REQUIRED"
PAID_STATUSES = ("Paid", "PartiallyPaid")
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


# 5C-C26l Addendum L — FG-109: the fields a linked line is costed by.
# Addendum M — FG-124: EVERY allocation input, the deprecated single
# allocation (allocation_type / allocation_ref_id) included — it is still
# read as the line's allocation when allocations[] is empty
# (canonical_material_cost.effective_allocations / normalize_allocations).
LOCKED_WHEN_LINKED = ("allocations", "allocation_type", "allocation_ref_id",
                      "qty", "unit", "unit_price")


# Codex F-55-C26-04: the inputs the derived money / allocation fields
# (line totals, VAT, qty_allocated / qty_unallocated / is_fully_allocated)
# are computed from. A PUT without any of them is metadata only.
DERIVED_INPUTS = LOCKED_WHEN_LINKED + ("vat_percent",)


async def _unless_linked(tenant: TenantData, line_id: str, write, *,
                         refuse_if_linked: bool = True) -> None:
    """FG-109 (D-04): once a canonical warehouse movement links the line, its
    allocation / qty / unit / price are locked — 409, nothing written.
    Decided in one transaction under the per-line lock the canonical
    receipts take (``app.services.invoice_line_lock``); ``write`` reads the
    current row in that transaction (F-55-C26-04)."""
    try:
        await write_unless_linked(tenant, line_id, write,
                                  refuse_if_linked=refuse_if_linked)
    except InvoiceLineAllocationLocked as exc:
        raise HTTPException(status_code=409, detail=exc.detail())


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
    # WH-FIX-01 A2 (FG-155): final only at 100 %; otherwise the interim
    # „чака разпределение" (the same rule as services.invoice_allocation).
    line["allocation_status"] = "allocated" if line["is_fully_allocated"] else "pending_allocation"
    
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


async def _apply_header(tenant: TenantData, user: dict, invoice_id: str, session) -> None:
    """A4 #9 (Р45): an invoice with ONE header destination gets it written
    explicitly on every new unallocated line, with an AuditEvent, in the same
    transaction as the line write."""
    from app.services.invoice_allocation import apply_header_destination
    invoice = await tenant.invoices.find_one({"id": invoice_id},
                                             {"_id": 0, "id": 1, "allocations": 1,
                                              "direction": 1, "project_id": 1},
                                             session=session)
    if invoice:
        await apply_header_destination(tenant, user, invoice, session=session)


async def _refresh_dq(tenant: TenantData, user: dict, invoice_id: str, session) -> None:
    """FG-201: the DQ issue / alarm of the invoice are opened / resolved by the
    WRITE (AuditEvent, same transaction) — the list GET never writes."""
    from app.services.invoice_allocation import refresh_invoice_dq
    await refresh_invoice_dq(tenant, invoice_id, actor=user, session=session)


async def get_org_require_full_allocation(tenant: TenantData) -> bool:
    """Get THIS tenant's requireFullAllocation setting (its own organization row)."""
    org = await tenant.own_organization({"_id": 0, "require_full_allocation": 1})
    return org.get("require_full_allocation", False) if org else False


async def recalculate_invoice_totals(tenant: TenantData, invoice_id: str, *, session=None):
    """Recalculate THIS tenant's invoice totals from its own lines.

    Both the invoice read and the invoice write carry the tenant predicate. The
    write filter in particular: a scoped read of the lines said nothing about
    which tenant's invoice ``{"id": invoice_id}`` alone would have updated.

    5C-C26l (debt after Codex F-55-C26-04): the lines, the paid amount and the
    header write are ONE transaction. Two recalculations of the same invoice
    (concurrent edits of different lines) both write the invoice document, so
    MongoDB aborts one with a WriteConflict and ``with_transaction`` re-runs it
    against the committed lines — the stored header total is always Σ lines,
    never a total computed from a line set read before another edit.

    Addendum N (FG-140): the line writers call it with their ``session`` —
    the line write and the header write are one transaction that claimed the
    invoice as Draft (``claim_invoice``); the header write itself carries
    ``status: Draft`` as a condition.
    """
    async def _body(session):
        lines = await tenant.invoice_lines.find({"invoice_id": invoice_id},
                                                session=session).to_list(1000)
        subtotal = sum(l.get("line_total_ex_vat", 0) for l in lines)
        vat_total = sum(l.get("vat_amount", 0) for l in lines)
        total = round(subtotal + vat_total, 2)
        invoice = await tenant.invoices.get(invoice_id, session=session)
        paid_amount = (invoice or {}).get("paid_amount", 0) or 0
        # FG-140: only a Draft invoice's header is recomputed from its lines.
        await tenant.invoices.update_one({"id": invoice_id, "status": "Draft"}, {"$set": {
            "subtotal": round(subtotal, 2),
            "vat_amount": round(vat_total, 2),
            "total": total,
            "remaining_amount": max(0, round(total - paid_amount, 2)),
            "lines_count": len(lines),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }}, session=session)
    if session is not None:
        await _body(session)          # inside the caller's (claimed) transaction
    else:
        await run_transaction(tenant, _body)


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


@router.get("/invoice-lines/invoices-to-allocate")
async def get_invoices_to_allocate(user: dict = Depends(require_m5)):
    """WH-FIX-01 A2/A3 (FG-155, Р44) — „фактури за разпределяне": every
    supplier invoice with a line in the interim state „чака разпределение",
    drill-down to the lines, with its DQ issue (owner Accountant, deadline,
    escalation to Owner) and alarm. Finance roles only (Р14 / Р20)."""
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    from app.services.invoice_allocation import invoices_to_allocate
    items = await invoices_to_allocate(_tenant(user), user["org_id"])
    return {"count": len(items), "invoices": items}


@router.get("/invoice-lines/{line_id}/allocation-versions")
async def get_allocation_versions(line_id: str, user: dict = Depends(require_m5)):
    """WHFIX81-06 — the previous allocations of a line (corrections of a paid
    invoice), oldest first, and the current one. Finance roles only."""
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    tenant = _tenant(user)
    line = await tenant.invoice_lines.find_one({"id": line_id},
                                               {"_id": 0, "allocations": 1, "allocation_version": 1})
    if not line:
        raise HTTPException(status_code=404, detail="Invoice line not found")
    versions = await tenant.invoice_line_allocation_versions.find(
        {"invoice_line_id": line_id}, {"_id": 0}).sort("version", 1).to_list(None)
    return {"line_id": line_id, "versions": versions,
            "current": {"version": line.get("allocation_version") or 0,
                        "allocations": line.get("allocations") or []}}


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
    
    # FG-140: the Draft status is decided in the transaction (CAS on the
    # invoice); the line and the header totals are written in it.
    async def _body(session):
        await claim_invoice(tenant, data.invoice_id, session=session, allowed=("Draft",),
                            code=NOT_DRAFT)
        await tenant.invoice_lines.insert_one(dict(line), session=session)
        await _apply_header(tenant, user, data.invoice_id, session)
        await recalculate_invoice_totals(tenant, data.invoice_id, session=session)
        await _refresh_dq(tenant, user, data.invoice_id, session)
    from app.audit.store import ensure_chain_index
    await ensure_chain_index(tenant._db)
    await run_transaction(tenant, _body)
    line = await tenant.invoice_lines.find_one({"id": line["id"]}, {"_id": 0}) or line
    
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
        async def _body(session):                                  # FG-140
            await claim_invoice(tenant, invoice_id, session=session, allowed=("Draft",),
                                code=NOT_DRAFT)
            await tenant.invoice_lines.insert_many([dict(l) for l in created_lines],
                                                   session=session)
            await _apply_header(tenant, user, invoice_id, session)
            await recalculate_invoice_totals(tenant, invoice_id, session=session)
            await _refresh_dq(tenant, user, invoice_id, session)
        from app.audit.store import ensure_chain_index
        await ensure_chain_index(tenant._db)
        await run_transaction(tenant, _body)
    
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

    # Handle scan_line_ref
    if "scan_line_ref" in update and update["scan_line_ref"]:
        update["scan_line_ref"] = update["scan_line_ref"] if isinstance(update["scan_line_ref"], dict) else update["scan_line_ref"].model_dump()

    update["updated_at"] = datetime.now(timezone.utc).isoformat()

    if not any(k in update for k in DERIVED_INPUTS):
        # Codex F-55-C26-04: a metadata-only PUT writes ONLY the fields it
        # was sent (+ updated_at) — never the derived money / allocation
        # fields, which a concurrent writer may have changed since the read.
        async def _meta(session):
            # FG-140: Draft decided in the transaction (CAS on the invoice).
            await claim_invoice(tenant, line["invoice_id"], session=session,
                                allowed=("Draft",), code=NOT_DRAFT)
            await tenant.invoice_lines.update_one({"id": line_id}, {"$set": update},
                                                  session=session)
        await run_transaction(tenant, _meta)
    else:
        if "allocations" in update and update["allocations"]:
            update["allocations"] = [a if isinstance(a, dict) else a.model_dump()
                                     for a in update["allocations"]]
            await validate_allocation_refs(tenant, update["allocations"])
        require_full = await get_org_require_full_allocation(tenant)

        async def _write(session):
            # F-55-C26-04: read, validate, compute and write in ONE
            # transaction under the per-line lock — from the CURRENT row.
            # FG-140: the invoice is claimed as Draft in the same transaction
            # and the header totals are written in it.
            await claim_invoice(tenant, line["invoice_id"], session=session,
                                allowed=("Draft",), code=NOT_DRAFT)
            current = await tenant.invoice_lines.find_one({"id": line_id}, {"_id": 0},
                                                          session=session)
            if not current:
                raise HTTPException(status_code=404, detail="Invoice line not found")
            if "allocations" in update and update["allocations"]:
                qty = update.get("qty", current.get("qty", 1))
                total_allocated = sum(a["qty"] for a in update["allocations"])
                if total_allocated > qty:
                    raise HTTPException(status_code=400, detail=f"Allocated qty ({total_allocated}) exceeds purchased qty ({qty})")
                if require_full and abs(total_allocated - qty) > 0.0001:
                    raise HTTPException(status_code=400, detail=f"Full allocation required. Allocated: {total_allocated}, Required: {qty}")
            if "allocations" in update:
                from app.services.invoice_allocation import audit_allocation_change
                await audit_allocation_change(tenant, user, line_id,
                                              current.get("allocations") or [],
                                              update["allocations"] or [], session=session)
            merged = compute_allocation_stats(compute_line_totals({**current, **update}))
            patch = {
                **update,
                "line_total_ex_vat": merged["line_total_ex_vat"],
                "vat_amount": merged["vat_amount"],
                "line_total_inc_vat": merged["line_total_inc_vat"],
                "qty_allocated": merged.get("qty_allocated", 0),
                "qty_unallocated": merged.get("qty_unallocated", 0),
                "is_fully_allocated": merged.get("is_fully_allocated", False),
            }
            await tenant.invoice_lines.update_one({"id": line_id}, {"$set": patch},
                                                  session=session)
            await recalculate_invoice_totals(tenant, line["invoice_id"], session=session)
            await _refresh_dq(tenant, user, line["invoice_id"], session)
        # FG-109 / FG-124: the costing inputs are refused (409) on a linked
        # line; vat_percent alone is not costing but still derives totals.
        from app.audit.store import ensure_chain_index
        await ensure_chain_index(tenant._db)  # WH-FIX-01 A2 #4: record_event runs in the tx
        await _unless_linked(tenant, line_id, _write,
                             refuse_if_linked=any(k in update for k in LOCKED_WHEN_LINKED))

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
    
    # Validate allocations
    allocs = [a.model_dump() for a in data.allocations]
    # A4 #10 (Р45): a percentage is converted AT ONCE into an exact amount and
    # qty share of THIS line (cumulative rounding: Σ amount = the line value,
    # Σ qty = the line qty); the stored allocation carries the amount / qty.
    pct_items = [a for a in allocs if a.get("percent") is not None]
    if pct_items and len(pct_items) != len(allocs):
        raise HTTPException(status_code=422, detail={
            "error_code": "ALLOCATION_MIXED_INPUT",
            "message": "use either quantities or percentages for one line"})
    if pct_items:
        from app.services.invoice_allocation import split_percentages
        total = float(line.get("line_total_ex_vat") or
                      float(line.get("qty") or 0) * float(line.get("unit_price") or 0))
        parts = split_percentages(total, float(line.get("qty") or 0) or None,
                                  [a["percent"] for a in allocs])
        for a, part in zip(allocs, parts):
            a["input_percent"] = a.pop("percent")
            a["amount"] = part["amount"]
            a["qty"] = part["qty"]
    else:
        for a in allocs:
            a.pop("percent", None)
    total_allocated = round(sum(a["qty"] or 0 for a in allocs), 4)

    # Check if full allocation required
    require_full = await get_org_require_full_allocation(tenant)

    # Validate all refs exist
    await validate_allocation_refs(tenant, allocs)

    now = datetime.now(timezone.utc).isoformat()

    reason = (data.correction_reason or "").strip()
    if reason:
        from app.services.money_amount import check_reason
        check_reason(reason)              # ≤ 500 chars, no control / invisible chars → 400

    async def _write(session):
        # WHFIX81-06: the invoice is CLAIMED in this transaction — a CAS write on
        # its document that honours the PAY-01 payment row lock (INVOICE_BUSY
        # while a payment is being written), so a payment and a reallocation of
        # the same invoice are serialized and each sees the other's result.
        inv = await claim_invoice(tenant, line["invoice_id"], session=session,
                                  forbidden=("Cancelled",), code=STATUS_CHANGED)
        paid = bool(inv) and (inv.get("status") in PAID_STATUSES
                              or float(inv.get("paid_amount") or 0) > 0)
        if paid and not reason:
            raise HTTPException(status_code=409, detail={
                "error_code": ALLOCATION_CORRECTION_REQUIRED, "invoice_id": line["invoice_id"],
                "message": "Фактурата е платена — разпределението се променя само с корекция "
                           "(посочете причина)."})
        # Codex F-55-C26-04: the purchased qty is read in the lock
        # transaction, not from the row read before it.
        current = await tenant.invoice_lines.find_one({"id": line_id}, {"_id": 0, "qty": 1},
                                                      session=session)
        if not current:
            raise HTTPException(status_code=404, detail="Invoice line not found")
        qty_purchased = current.get("qty", 0)
        if total_allocated > qty_purchased:
            raise HTTPException(
                status_code=400,
                detail=f"Total allocated qty ({total_allocated}) exceeds purchased qty ({qty_purchased})"
            )
        if require_full and abs(total_allocated - qty_purchased) > 0.0001:
            raise HTTPException(
                status_code=400,
                detail=f"Full allocation required by organization settings. Allocated: {total_allocated}, Required: {qty_purchased}. Unallocated: {qty_purchased - total_allocated}"
            )
        # WH-FIX-01 A2 #4 — the allocation change is a correction with a
        # canonical AuditEvent in the same transaction.
        before = await tenant.invoice_lines.find_one(
            {"id": line_id}, {"_id": 0, "allocations": 1, "allocation_version": 1},
            session=session)
        from app.services.invoice_allocation import audit_allocation_change
        version = int((before or {}).get("allocation_version") or 0) + 1
        if paid:
            # WHFIX81-06: a correction keeps the previous version READABLE
            # (append-only `invoice_line_allocation_versions`).
            await tenant.invoice_line_allocation_versions.insert_one({
                "id": f"{line_id}:v{version - 1}", "org_id": user["org_id"],
                "invoice_id": line["invoice_id"], "invoice_line_id": line_id,
                "version": version - 1, "allocations": (before or {}).get("allocations") or [],
                "superseded_at": now, "superseded_by": user["id"], "reason": reason},
                session=session)
        await audit_allocation_change(tenant, user, line_id, (before or {}).get("allocations") or [],
                                      allocs, session=session,
                                      reason=reason or None)
        await tenant.invoice_lines.update_one({"id": line_id}, {"$set": {
            "allocation_version": version,
            "allocations": allocs,
            "qty_allocated": round(total_allocated, 4),
            "qty_unallocated": round(qty_purchased - total_allocated, 4),
            "is_fully_allocated": abs(total_allocated - qty_purchased) <= 0.0001,
            "updated_at": now,
        }}, session=session)
        await _refresh_dq(tenant, user, line["invoice_id"], session)
    from app.audit.store import ensure_chain_index
    await ensure_chain_index(tenant._db)     # WH-FIX-01 A2 #4: record_event runs in the tx
    await _unless_linked(tenant, line_id, _write)                # FG-109

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

    async def _write(session):
        # FG-140: Draft decided in the transaction; header written in it.
        await claim_invoice(tenant, invoice_id, session=session, allowed=("Draft",),
                            code=NOT_DRAFT)
        await tenant.invoice_lines.delete_one({"id": line_id}, session=session)
        await recalculate_invoice_totals(tenant, invoice_id, session=session)
        await _refresh_dq(tenant, user, invoice_id, session)
    from app.audit.store import ensure_chain_index
    await ensure_chain_index(tenant._db)
    await _unless_linked(tenant, line_id, _write)    # FG-109: a linked line is never deleted
    
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
