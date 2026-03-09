"""
Routes - Material Requests + Supplier Invoice Intake + Warehouse Posting.
Foundation layer for procurement flow.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from typing import Optional, List
from datetime import datetime, timezone
from pydantic import BaseModel
import uuid, os, shutil

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import require_m2
from app.utils.audit import log_audit

router = APIRouter(tags=["Procurement"])

UPLOAD_DIR = "/app/backend/uploads"


# ── Pydantic Models ────────────────────────────────────────────────

class MaterialRequestLineInput(BaseModel):
    material_name: str
    category: Optional[str] = None
    qty_requested: float = 1
    unit: str = "бр"
    dimension_spec: Optional[str] = None
    notes: Optional[str] = None
    linked_offer_line_id: Optional[str] = None

class MaterialRequestCreate(BaseModel):
    project_id: str
    source_offer_id: Optional[str] = None
    source_offer_type: Optional[str] = None  # main / extra
    stage_name: Optional[str] = None
    needed_date: Optional[str] = None
    notes: Optional[str] = None
    lines: List[MaterialRequestLineInput] = []

class SupplierInvoiceCreate(BaseModel):
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = None
    project_id: Optional[str] = None
    linked_request_id: Optional[str] = None
    invoice_number: str
    invoice_date: str
    purchased_by: Optional[str] = None
    notes: Optional[str] = None

class InvoiceLineInput(BaseModel):
    material_name: str
    qty: float = 1
    unit: str = "бр"
    dimension_spec: Optional[str] = None
    unit_price: float = 0
    discount_percent: float = 0
    total_price: Optional[float] = None
    project_id: Optional[str] = None
    linked_request_id: Optional[str] = None
    linked_offer_id: Optional[str] = None
    notes: Optional[str] = None


# ── Material Requests CRUD ─────────────────────────────────────────

async def get_next_request_number(org_id: str) -> str:
    last = await db.material_requests.find_one(
        {"org_id": org_id}, {"_id": 0, "request_number": 1},
        sort=[("created_at", -1)]
    )
    num = 1
    if last and last.get("request_number"):
        try: num = int(last["request_number"].split("-")[1]) + 1
        except: pass
    return f"MR-{num:04d}"


@router.post("/material-requests", status_code=201)
async def create_material_request(data: MaterialRequestCreate, user: dict = Depends(require_m2)):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    project = await db.projects.find_one({"id": data.project_id, "org_id": user["org_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    now = datetime.now(timezone.utc).isoformat()
    req_no = await get_next_request_number(user["org_id"])
    
    lines = []
    for i, line in enumerate(data.lines):
        lines.append({
            "id": str(uuid.uuid4()),
            "material_name": line.material_name,
            "category": line.category,
            "qty_requested": line.qty_requested,
            "qty_fulfilled": 0,
            "unit": line.unit,
            "dimension_spec": line.dimension_spec,
            "notes": line.notes,
            "linked_offer_line_id": line.linked_offer_line_id,
            "sort_order": i,
        })
    
    req = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "project_id": data.project_id,
        "source_offer_id": data.source_offer_id,
        "source_offer_type": data.source_offer_type,
        "stage_name": data.stage_name,
        "request_number": req_no,
        "status": "draft",
        "needed_date": data.needed_date,
        "notes": data.notes,
        "lines": lines,
        "created_at": now,
        "updated_at": now,
        "created_by": user["id"],
    }
    await db.material_requests.insert_one(req)
    return {k: v for k, v in req.items() if k != "_id"}


@router.get("/material-requests")
async def list_material_requests(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    user: dict = Depends(require_m2),
):
    query = {"org_id": user["org_id"]}
    if project_id: query["project_id"] = project_id
    if status: query["status"] = status
    
    reqs = await db.material_requests.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    for r in reqs:
        p = await db.projects.find_one({"id": r["project_id"]}, {"_id": 0, "code": 1, "name": 1})
        r["project_code"] = p["code"] if p else ""
        r["project_name"] = p["name"] if p else ""
    return reqs


@router.get("/material-requests/{req_id}")
async def get_material_request(req_id: str, user: dict = Depends(require_m2)):
    req = await db.material_requests.find_one({"id": req_id, "org_id": user["org_id"]}, {"_id": 0})
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    return req


@router.put("/material-requests/{req_id}")
async def update_material_request(req_id: str, data: dict, user: dict = Depends(require_m2)):
    req = await db.material_requests.find_one({"id": req_id, "org_id": user["org_id"]})
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    
    allowed = ["stage_name", "needed_date", "notes", "status", "lines"]
    update = {k: v for k, v in data.items() if k in allowed and v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.material_requests.update_one({"id": req_id}, {"$set": update})
    return await db.material_requests.find_one({"id": req_id}, {"_id": 0})


@router.post("/material-requests/{req_id}/submit")
async def submit_material_request(req_id: str, user: dict = Depends(require_m2)):
    req = await db.material_requests.find_one({"id": req_id, "org_id": user["org_id"]})
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req["status"] != "draft":
        raise HTTPException(status_code=400, detail="Only draft requests can be submitted")
    
    now = datetime.now(timezone.utc).isoformat()
    await db.material_requests.update_one({"id": req_id}, {"$set": {
        "status": "submitted", "submitted_at": now, "updated_at": now,
    }})
    return await db.material_requests.find_one({"id": req_id}, {"_id": 0})


@router.delete("/material-requests/{req_id}")
async def delete_material_request(req_id: str, user: dict = Depends(require_m2)):
    req = await db.material_requests.find_one({"id": req_id, "org_id": user["org_id"]})
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req["status"] != "draft":
        raise HTTPException(status_code=400, detail="Only draft requests can be deleted")
    await db.material_requests.delete_one({"id": req_id})
    return {"ok": True}


# ── Generate Material Request from Offer ───────────────────────────

@router.post("/material-requests/from-offer/{offer_id}", status_code=201)
async def create_request_from_offer(offer_id: str, data: dict, user: dict = Depends(require_m2)):
    """Generate material request from offer's suggested materials"""
    offer = await db.offers.find_one({"id": offer_id, "org_id": user["org_id"]})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    
    now = datetime.now(timezone.utc).isoformat()
    req_no = await get_next_request_number(user["org_id"])
    
    # Gather materials from offer lines + extra work drafts
    lines = []
    for i, ol in enumerate(offer.get("lines", [])):
        lines.append({
            "id": str(uuid.uuid4()),
            "material_name": ol.get("activity_name", ""),
            "category": ol.get("activity_type", ""),
            "qty_requested": ol.get("qty", 1),
            "qty_fulfilled": 0,
            "unit": ol.get("unit", "бр"),
            "dimension_spec": None,
            "notes": ol.get("note", ""),
            "linked_offer_line_id": ol.get("id"),
            "sort_order": i,
        })
    
    # Also check for suggested materials from extra work drafts
    if offer.get("source_batch_id"):
        drafts = await db.extra_work_drafts.find(
            {"group_batch_id": offer["source_batch_id"]},
            {"_id": 0, "suggested_materials": 1, "title": 1}
        ).to_list(50)
        for draft in drafts:
            for mat in (draft.get("suggested_materials") or []):
                lines.append({
                    "id": str(uuid.uuid4()),
                    "material_name": mat.get("name", ""),
                    "category": mat.get("category", ""),
                    "qty_requested": mat.get("estimated_qty") or 1,
                    "qty_fulfilled": 0,
                    "unit": mat.get("unit", "бр"),
                    "dimension_spec": None,
                    "notes": f"От AI checklist: {draft.get('title', '')}",
                    "linked_offer_line_id": None,
                    "sort_order": len(lines),
                })
    
    req = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "project_id": offer["project_id"],
        "source_offer_id": offer_id,
        "source_offer_type": offer.get("offer_type", "main"),
        "stage_name": data.get("stage_name", ""),
        "request_number": req_no,
        "status": "draft",
        "needed_date": data.get("needed_date"),
        "notes": data.get("notes", f"Заявка от оферта {offer.get('offer_no', '')}"),
        "lines": lines,
        "created_at": now,
        "updated_at": now,
        "created_by": user["id"],
    }
    await db.material_requests.insert_one(req)
    return {k: v for k, v in req.items() if k != "_id"}


# ── Supplier Invoice Intake ────────────────────────────────────────

@router.post("/supplier-invoices", status_code=201)
async def create_supplier_invoice(data: SupplierInvoiceCreate, user: dict = Depends(require_m2)):
    if user["role"] not in ["Admin", "Owner", "SiteManager", "Accountant"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    now = datetime.now(timezone.utc).isoformat()
    inv = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "supplier_id": data.supplier_id,
        "supplier_name": data.supplier_name or "",
        "project_id": data.project_id,
        "linked_request_id": data.linked_request_id,
        "invoice_number": data.invoice_number,
        "invoice_date": data.invoice_date,
        "purchased_by": data.purchased_by or user.get("email", ""),
        "original_file_url": None,
        "original_file_name": None,
        "lines": [],
        "subtotal": 0,
        "vat_amount": 0,
        "total": 0,
        "vat_percent": 20,
        "notes": data.notes,
        "status": "uploaded",
        "created_at": now,
        "updated_at": now,
        "created_by": user["id"],
        "posted_to_warehouse": False,
    }
    await db.supplier_invoices.insert_one(inv)
    return {k: v for k, v in inv.items() if k != "_id"}


@router.post("/supplier-invoices/{inv_id}/upload-file")
async def upload_invoice_file(inv_id: str, file: UploadFile = File(...), user: dict = Depends(require_m2)):
    inv = await db.supplier_invoices.find_one({"id": inv_id, "org_id": user["org_id"]})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    ext = os.path.splitext(file.filename)[1] if file.filename else ".pdf"
    file_id = f"{uuid.uuid4()}{ext}"
    file_path = os.path.join(UPLOAD_DIR, file_id)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    
    file_url = f"/api/media/{file_id}"
    await db.supplier_invoices.update_one({"id": inv_id}, {"$set": {
        "original_file_url": file_url,
        "original_file_name": file.filename,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }})
    return {"ok": True, "file_url": file_url, "file_name": file.filename}


@router.get("/supplier-invoices")
async def list_supplier_invoices(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    user: dict = Depends(require_m2),
):
    query = {"org_id": user["org_id"]}
    if project_id: query["project_id"] = project_id
    if status: query["status"] = status
    
    invs = await db.supplier_invoices.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    for inv in invs:
        if inv.get("project_id"):
            p = await db.projects.find_one({"id": inv["project_id"]}, {"_id": 0, "code": 1})
            inv["project_code"] = p["code"] if p else ""
    return invs


@router.get("/supplier-invoices/{inv_id}")
async def get_supplier_invoice(inv_id: str, user: dict = Depends(require_m2)):
    inv = await db.supplier_invoices.find_one({"id": inv_id, "org_id": user["org_id"]}, {"_id": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return inv


@router.put("/supplier-invoices/{inv_id}")
async def update_supplier_invoice(inv_id: str, data: dict, user: dict = Depends(require_m2)):
    """Update invoice header and lines (review/correction)"""
    inv = await db.supplier_invoices.find_one({"id": inv_id, "org_id": user["org_id"]})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    allowed = ["supplier_id", "supplier_name", "project_id", "linked_request_id",
               "invoice_number", "invoice_date", "purchased_by", "notes",
               "lines", "subtotal", "vat_amount", "total", "vat_percent", "status"]
    update = {k: v for k, v in data.items() if k in allowed}
    
    # Recompute totals if lines provided
    if "lines" in update:
        lines = update["lines"]
        for line in lines:
            if not line.get("id"):
                line["id"] = str(uuid.uuid4())
            qty = float(line.get("qty", 0))
            up = float(line.get("unit_price", 0))
            disc = float(line.get("discount_percent", 0))
            final_up = round(up * (1 - disc / 100), 2)
            line["final_unit_price"] = final_up
            line["total_price"] = round(qty * final_up, 2)
        subtotal = sum(l.get("total_price", 0) for l in lines)
        vat_pct = float(update.get("vat_percent", inv.get("vat_percent", 20)))
        update["subtotal"] = round(subtotal, 2)
        update["vat_amount"] = round(subtotal * vat_pct / 100, 2)
        update["total"] = round(subtotal + update["vat_amount"], 2)
    
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    if "lines" in update and inv["status"] == "uploaded":
        update["status"] = "reviewed"
    
    await db.supplier_invoices.update_one({"id": inv_id}, {"$set": update})
    return await db.supplier_invoices.find_one({"id": inv_id}, {"_id": 0})


# ── Post to Warehouse ──────────────────────────────────────────────

@router.post("/supplier-invoices/{inv_id}/post-to-warehouse", status_code=201)
async def post_invoice_to_warehouse(inv_id: str, user: dict = Depends(require_m2)):
    """Post reviewed supplier invoice lines to Main Warehouse"""
    if user["role"] not in ["Admin", "Owner", "SiteManager", "Warehousekeeper"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    inv = await db.supplier_invoices.find_one({"id": inv_id, "org_id": user["org_id"]})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if inv.get("posted_to_warehouse"):
        raise HTTPException(status_code=400, detail="Already posted to warehouse")
    if not inv.get("lines"):
        raise HTTPException(status_code=400, detail="No lines to post")
    
    # Find or create Main Warehouse
    main_wh = await db.warehouses.find_one({"org_id": user["org_id"], "type": "main"})
    if not main_wh:
        main_wh = {
            "id": str(uuid.uuid4()),
            "org_id": user["org_id"],
            "name": "Основен склад",
            "type": "main",
            "location": "",
            "active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.warehouses.insert_one(main_wh)
    
    now = datetime.now(timezone.utc).isoformat()
    
    # Create warehouse intake transaction
    intake_lines = []
    for line in inv["lines"]:
        intake_lines.append({
            "id": str(uuid.uuid4()),
            "material_name": line.get("material_name", ""),
            "qty_received": float(line.get("qty", 0)),
            "unit": line.get("unit", "бр"),
            "dimension_spec": line.get("dimension_spec"),
            "unit_price": float(line.get("unit_price", 0)),
            "discount_percent": float(line.get("discount_percent", 0)),
            "final_unit_price": float(line.get("final_unit_price", line.get("unit_price", 0))),
            "total_price": float(line.get("total_price", 0)),
            "project_id": line.get("project_id") or inv.get("project_id"),
            "linked_request_id": line.get("linked_request_id") or inv.get("linked_request_id"),
            "linked_offer_id": line.get("linked_offer_id"),
        })
    
    transaction = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "warehouse_id": main_wh["id"],
        "type": "intake",
        "source_type": "supplier_invoice",
        "source_invoice_id": inv_id,
        "supplier_id": inv.get("supplier_id"),
        "supplier_name": inv.get("supplier_name"),
        "invoice_number": inv.get("invoice_number"),
        "invoice_date": inv.get("invoice_date"),
        "digital_invoice_url": inv.get("original_file_url"),
        "project_id": inv.get("project_id"),
        "received_at": now,
        "received_by": user["id"],
        "purchased_by": inv.get("purchased_by"),
        "lines": intake_lines,
        "subtotal": inv.get("subtotal", 0),
        "vat_amount": inv.get("vat_amount", 0),
        "total": inv.get("total", 0),
        "created_at": now,
    }
    await db.warehouse_transactions.insert_one(transaction)
    
    # Update invoice status
    await db.supplier_invoices.update_one({"id": inv_id}, {"$set": {
        "posted_to_warehouse": True,
        "posted_at": now,
        "posted_by": user["id"],
        "warehouse_transaction_id": transaction["id"],
        "status": "posted_to_warehouse",
        "updated_at": now,
    }})
    
    # Update material request fulfillment if linked
    if inv.get("linked_request_id"):
        req = await db.material_requests.find_one({"id": inv["linked_request_id"]})
        if req:
            # Simple: mark as fulfilled
            await db.material_requests.update_one(
                {"id": req["id"]},
                {"$set": {"status": "fulfilled", "updated_at": now}}
            )
    
    await log_audit(user["org_id"], user["id"], user.get("email", ""), "warehouse_intake", "warehouse_transaction", transaction["id"],
                    {"invoice_number": inv.get("invoice_number"), "lines_count": len(intake_lines)})
    
    return {k: v for k, v in transaction.items() if k != "_id"}


# ── Warehouse Transactions List ────────────────────────────────────

@router.get("/warehouse-transactions")
async def list_warehouse_transactions(
    project_id: Optional[str] = None,
    warehouse_id: Optional[str] = None,
    user: dict = Depends(require_m2),
):
    query = {"org_id": user["org_id"]}
    if project_id: query["project_id"] = project_id
    if warehouse_id: query["warehouse_id"] = warehouse_id
    
    txns = await db.warehouse_transactions.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    return txns
