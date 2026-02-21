"""
Routes - Invoice Lines (separate collection for detailed tracking and allocation).
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, List
from datetime import datetime, timezone
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import require_m5
from app.utils.audit import log_audit
from ..models.invoice_lines import (
    ALLOCATION_TYPES,
    InvoiceLineCreate, InvoiceLineUpdate, 
    InvoiceLineBulkCreate, InvoiceLineAllocationUpdate
)

router = APIRouter(tags=["InvoiceLines"])


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


async def recalculate_invoice_totals(invoice_id: str, org_id: str):
    """Recalculate invoice totals from its lines"""
    lines = await db.invoice_lines.find({"invoice_id": invoice_id, "org_id": org_id}).to_list(1000)
    
    subtotal = sum(l.get("line_total_ex_vat", 0) for l in lines)
    vat_total = sum(l.get("vat_amount", 0) for l in lines)
    total = round(subtotal + vat_total, 2)
    
    invoice = await db.invoices.find_one({"id": invoice_id})
    paid_amount = invoice.get("paid_amount", 0) if invoice else 0
    
    await db.invoices.update_one({"id": invoice_id}, {"$set": {
        "subtotal": round(subtotal, 2),
        "vat_amount": round(vat_total, 2),
        "total": total,
        "remaining_amount": max(0, round(total - paid_amount, 2)),
        "lines_count": len(lines),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }})


# ── Invoice Lines CRUD ─────────────────────────────────────────────

@router.get("/invoice-lines")
async def list_invoice_lines(
    user: dict = Depends(require_m5),
    invoice_id: Optional[str] = None,
    allocation_type: Optional[str] = None,
    allocation_ref_id: Optional[str] = None,
    purchased_by: Optional[str] = None,
):
    """List invoice lines with filters"""
    if not invoice_id and not allocation_ref_id:
        raise HTTPException(status_code=400, detail="Must specify invoice_id or allocation_ref_id")
    
    query = {"org_id": user["org_id"]}
    
    if invoice_id:
        query["invoice_id"] = invoice_id
    if allocation_type:
        query["allocation_type"] = allocation_type
    if allocation_ref_id:
        query["allocation_ref_id"] = allocation_ref_id
    if purchased_by:
        query["purchased_by_user_id"] = purchased_by
    
    lines = await db.invoice_lines.find(query, {"_id": 0}).sort("line_no", 1).to_list(1000)
    
    # Enrich with names
    for line in lines:
        if line.get("purchased_by_user_id"):
            buyer = await db.users.find_one({"id": line["purchased_by_user_id"]}, {"_id": 0, "first_name": 1, "last_name": 1})
            line["purchased_by_name"] = f"{buyer['first_name']} {buyer['last_name']}" if buyer else ""
        
        if line.get("allocation_type") == "project" and line.get("allocation_ref_id"):
            proj = await db.projects.find_one({"id": line["allocation_ref_id"]}, {"_id": 0, "code": 1, "name": 1})
            line["allocation_name"] = f"{proj['code']} - {proj['name']}" if proj else ""
        elif line.get("allocation_type") == "warehouse" and line.get("allocation_ref_id"):
            wh = await db.warehouses.find_one({"id": line["allocation_ref_id"]}, {"_id": 0, "code": 1, "name": 1})
            line["allocation_name"] = f"{wh['code']} - {wh['name']}" if wh else ""
        elif line.get("allocation_type") == "person" and line.get("allocation_ref_id"):
            person = await db.persons.find_one({"id": line["allocation_ref_id"]}, {"_id": 0, "first_name": 1, "last_name": 1})
            line["allocation_name"] = f"{person['first_name']} {person['last_name']}" if person else ""
    
    return lines


@router.post("/invoice-lines", status_code=201)
async def create_invoice_line(data: InvoiceLineCreate, user: dict = Depends(require_m5)):
    """Create a single invoice line"""
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    # Verify invoice exists
    invoice = await db.invoices.find_one({"id": data.invoice_id, "org_id": user["org_id"]})
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    if invoice["status"] not in ["Draft"]:
        raise HTTPException(status_code=400, detail="Can only add lines to Draft invoices")
    
    # Validate allocation if provided
    if data.allocation_type and data.allocation_ref_id:
        if data.allocation_type == "project":
            ref = await db.projects.find_one({"id": data.allocation_ref_id, "org_id": user["org_id"]})
            if not ref:
                raise HTTPException(status_code=404, detail="Project not found")
        elif data.allocation_type == "warehouse":
            ref = await db.warehouses.find_one({"id": data.allocation_ref_id, "org_id": user["org_id"]})
            if not ref:
                raise HTTPException(status_code=404, detail="Warehouse not found")
        elif data.allocation_type == "person":
            ref = await db.persons.find_one({"id": data.allocation_ref_id, "org_id": user["org_id"]})
            if not ref:
                raise HTTPException(status_code=404, detail="Person not found")
    
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
        "allocation_type": data.allocation_type,
        "allocation_ref_id": data.allocation_ref_id,
        "cost_category": data.cost_category,
        "scan_line_ref": data.scan_line_ref.model_dump() if data.scan_line_ref else None,
        "notes": data.notes,
        "created_at": now,
        "updated_at": now,
    }
    line = compute_line_totals(line)
    
    await db.invoice_lines.insert_one(line)
    
    # Recalculate invoice totals
    await recalculate_invoice_totals(data.invoice_id, user["org_id"])
    
    return {k: v for k, v in line.items() if k != "_id"}


@router.post("/invoice-lines/bulk", status_code=201)
async def create_invoice_lines_bulk(data: InvoiceLineBulkCreate, user: dict = Depends(require_m5)):
    """Create multiple invoice lines at once"""
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    if not data.lines:
        raise HTTPException(status_code=400, detail="No lines provided")
    
    # All lines must be for the same invoice
    invoice_ids = set(l.invoice_id for l in data.lines)
    if len(invoice_ids) > 1:
        raise HTTPException(status_code=400, detail="All lines must be for the same invoice")
    
    invoice_id = data.lines[0].invoice_id
    invoice = await db.invoices.find_one({"id": invoice_id, "org_id": user["org_id"]})
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    if invoice["status"] not in ["Draft"]:
        raise HTTPException(status_code=400, detail="Can only add lines to Draft invoices")
    
    now = datetime.now(timezone.utc).isoformat()
    created_lines = []
    
    for line_data in data.lines:
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
            "allocation_type": line_data.allocation_type,
            "allocation_ref_id": line_data.allocation_ref_id,
            "cost_category": line_data.cost_category,
            "scan_line_ref": line_data.scan_line_ref.model_dump() if line_data.scan_line_ref else None,
            "notes": line_data.notes,
            "created_at": now,
            "updated_at": now,
        }
        line = compute_line_totals(line)
        created_lines.append(line)
    
    if created_lines:
        await db.invoice_lines.insert_many(created_lines)
        await recalculate_invoice_totals(invoice_id, user["org_id"])
    
    return {"ok": True, "count": len(created_lines), "lines": [{k: v for k, v in l.items() if k != "_id"} for l in created_lines]}


@router.get("/invoice-lines/{line_id}")
async def get_invoice_line(line_id: str, user: dict = Depends(require_m5)):
    """Get invoice line details"""
    line = await db.invoice_lines.find_one({"id": line_id, "org_id": user["org_id"]}, {"_id": 0})
    if not line:
        raise HTTPException(status_code=404, detail="Invoice line not found")
    
    # Enrich
    if line.get("purchased_by_user_id"):
        buyer = await db.users.find_one({"id": line["purchased_by_user_id"]}, {"_id": 0, "first_name": 1, "last_name": 1})
        line["purchased_by_name"] = f"{buyer['first_name']} {buyer['last_name']}" if buyer else ""
    
    if line.get("scan_line_ref") and line["scan_line_ref"].get("scan_doc_id"):
        scan_doc = await db.scan_docs.find_one({"id": line["scan_line_ref"]["scan_doc_id"]}, {"_id": 0, "file_url": 1, "original_filename": 1})
        line["scan_doc"] = scan_doc if scan_doc else None
    
    return line


@router.put("/invoice-lines/{line_id}")
async def update_invoice_line(line_id: str, data: InvoiceLineUpdate, user: dict = Depends(require_m5)):
    """Update invoice line"""
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    line = await db.invoice_lines.find_one({"id": line_id, "org_id": user["org_id"]})
    if not line:
        raise HTTPException(status_code=404, detail="Invoice line not found")
    
    # Check invoice status
    invoice = await db.invoices.find_one({"id": line["invoice_id"]})
    if invoice and invoice["status"] not in ["Draft"]:
        raise HTTPException(status_code=400, detail="Can only edit lines of Draft invoices")
    
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    
    # Handle scan_line_ref
    if "scan_line_ref" in update and update["scan_line_ref"]:
        update["scan_line_ref"] = update["scan_line_ref"].model_dump() if hasattr(update["scan_line_ref"], "model_dump") else update["scan_line_ref"]
    
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    # Merge and recompute
    merged = {**line, **update}
    merged = compute_line_totals(merged)
    
    await db.invoice_lines.update_one({"id": line_id}, {"$set": {
        **update,
        "line_total_ex_vat": merged["line_total_ex_vat"],
        "vat_amount": merged["vat_amount"],
        "line_total_inc_vat": merged["line_total_inc_vat"],
    }})
    
    # Recalculate invoice
    await recalculate_invoice_totals(line["invoice_id"], user["org_id"])
    
    return await db.invoice_lines.find_one({"id": line_id}, {"_id": 0})


@router.put("/invoice-lines/{line_id}/allocate")
async def allocate_invoice_line(line_id: str, data: InvoiceLineAllocationUpdate, user: dict = Depends(require_m5)):
    """Update allocation for an invoice line"""
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    line = await db.invoice_lines.find_one({"id": line_id, "org_id": user["org_id"]})
    if not line:
        raise HTTPException(status_code=404, detail="Invoice line not found")
    
    # Validate reference exists
    if data.allocation_type == "project":
        ref = await db.projects.find_one({"id": data.allocation_ref_id, "org_id": user["org_id"]})
        if not ref:
            raise HTTPException(status_code=404, detail="Project not found")
    elif data.allocation_type == "warehouse":
        ref = await db.warehouses.find_one({"id": data.allocation_ref_id, "org_id": user["org_id"]})
        if not ref:
            raise HTTPException(status_code=404, detail="Warehouse not found")
    elif data.allocation_type == "person":
        ref = await db.persons.find_one({"id": data.allocation_ref_id, "org_id": user["org_id"]})
        if not ref:
            raise HTTPException(status_code=404, detail="Person not found")
    
    await db.invoice_lines.update_one({"id": line_id}, {"$set": {
        "allocation_type": data.allocation_type,
        "allocation_ref_id": data.allocation_ref_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }})
    
    await log_audit(user["org_id"], user["id"], user["email"], "invoice_line_allocated", "invoice_line", line_id,
                    {"allocation_type": data.allocation_type, "allocation_ref_id": data.allocation_ref_id})
    
    return await db.invoice_lines.find_one({"id": line_id}, {"_id": 0})


@router.delete("/invoice-lines/{line_id}")
async def delete_invoice_line(line_id: str, user: dict = Depends(require_m5)):
    """Delete invoice line"""
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    line = await db.invoice_lines.find_one({"id": line_id, "org_id": user["org_id"]})
    if not line:
        raise HTTPException(status_code=404, detail="Invoice line not found")
    
    # Check invoice status
    invoice = await db.invoices.find_one({"id": line["invoice_id"]})
    if invoice and invoice["status"] not in ["Draft"]:
        raise HTTPException(status_code=400, detail="Can only delete lines of Draft invoices")
    
    invoice_id = line["invoice_id"]
    await db.invoice_lines.delete_one({"id": line_id})
    
    # Recalculate invoice
    await recalculate_invoice_totals(invoice_id, user["org_id"])
    
    return {"ok": True}


# ── Allocation Reports ─────────────────────────────────────────────

@router.get("/invoice-lines/by-project/{project_id}")
async def get_lines_by_project(project_id: str, user: dict = Depends(require_m5)):
    """Get all invoice lines allocated to a specific project"""
    lines = await db.invoice_lines.find({
        "org_id": user["org_id"],
        "allocation_type": "project",
        "allocation_ref_id": project_id
    }, {"_id": 0}).to_list(1000)
    
    # Calculate totals
    total_ex_vat = sum(l.get("line_total_ex_vat", 0) for l in lines)
    total_vat = sum(l.get("vat_amount", 0) for l in lines)
    total_inc_vat = sum(l.get("line_total_inc_vat", 0) for l in lines)
    
    # Enrich with invoice info
    for line in lines:
        invoice = await db.invoices.find_one({"id": line["invoice_id"]}, {"_id": 0, "invoice_no": 1, "issue_date": 1, "direction": 1})
        if invoice:
            line["invoice_no"] = invoice["invoice_no"]
            line["invoice_date"] = invoice["issue_date"]
            line["invoice_direction"] = invoice["direction"]
    
    return {
        "project_id": project_id,
        "lines": lines,
        "count": len(lines),
        "total_ex_vat": round(total_ex_vat, 2),
        "total_vat": round(total_vat, 2),
        "total_inc_vat": round(total_inc_vat, 2),
    }


@router.get("/invoice-lines/by-warehouse/{warehouse_id}")
async def get_lines_by_warehouse(warehouse_id: str, user: dict = Depends(require_m5)):
    """Get all invoice lines allocated to a specific warehouse"""
    lines = await db.invoice_lines.find({
        "org_id": user["org_id"],
        "allocation_type": "warehouse",
        "allocation_ref_id": warehouse_id
    }, {"_id": 0}).to_list(1000)
    
    total_ex_vat = sum(l.get("line_total_ex_vat", 0) for l in lines)
    total_vat = sum(l.get("vat_amount", 0) for l in lines)
    total_inc_vat = sum(l.get("line_total_inc_vat", 0) for l in lines)
    
    for line in lines:
        invoice = await db.invoices.find_one({"id": line["invoice_id"]}, {"_id": 0, "invoice_no": 1, "issue_date": 1, "direction": 1})
        if invoice:
            line["invoice_no"] = invoice["invoice_no"]
            line["invoice_date"] = invoice["issue_date"]
            line["invoice_direction"] = invoice["direction"]
    
    return {
        "warehouse_id": warehouse_id,
        "lines": lines,
        "count": len(lines),
        "total_ex_vat": round(total_ex_vat, 2),
        "total_vat": round(total_vat, 2),
        "total_inc_vat": round(total_inc_vat, 2),
    }


@router.get("/invoice-lines/by-purchaser/{user_id}")
async def get_lines_by_purchaser(user_id: str, user: dict = Depends(require_m5)):
    """Get all invoice lines purchased by a specific user (driver/employee)"""
    lines = await db.invoice_lines.find({
        "org_id": user["org_id"],
        "purchased_by_user_id": user_id
    }, {"_id": 0}).to_list(1000)
    
    total_ex_vat = sum(l.get("line_total_ex_vat", 0) for l in lines)
    total_vat = sum(l.get("vat_amount", 0) for l in lines)
    total_inc_vat = sum(l.get("line_total_inc_vat", 0) for l in lines)
    
    # Get purchaser name
    purchaser = await db.users.find_one({"id": user_id}, {"_id": 0, "first_name": 1, "last_name": 1})
    purchaser_name = f"{purchaser['first_name']} {purchaser['last_name']}" if purchaser else ""
    
    for line in lines:
        invoice = await db.invoices.find_one({"id": line["invoice_id"]}, {"_id": 0, "invoice_no": 1, "issue_date": 1, "direction": 1})
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
        "total_inc_vat": round(total_inc_vat, 2),
    }


@router.get("/invoice-lines/enums")
async def get_invoice_line_enums():
    """Get available enum values"""
    return {
        "allocation_types": ALLOCATION_TYPES,
        "cost_categories": ["Materials", "Labor", "Subcontract", "Other"],
    }
