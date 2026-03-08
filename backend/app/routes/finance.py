"""
Routes - Finance (M5) Endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from datetime import datetime, timezone
import uuid

from app.db import db
from app.deps.auth import get_current_user, get_user_project_ids
from app.deps.modules import require_m5, enforce_limit
from app.utils.audit import log_audit
from ..models.finance import (
    ACCOUNT_TYPES, INVOICE_DIRECTIONS, INVOICE_STATUSES,
    PAYMENT_DIRECTIONS, COST_CATEGORIES,
    FinancialAccountCreate, FinancialAccountUpdate,
    InvoiceCreate, InvoiceUpdate, InvoiceLinesUpdate,
    PaymentCreate, AllocatePaymentRequest
)

router = APIRouter(tags=["Finance"])

# ── Helpers ────────────────────────────────────────────────────────

def finance_permission(user: dict) -> bool:
    """Check if user has finance access"""
    return user["role"] in ["Admin", "Owner", "Accountant"]


def compute_invoice_line(line: dict) -> dict:
    """Compute line total"""
    qty = line.get("qty", 1) or 1
    unit_price = line.get("unit_price", 0) or 0
    line["line_total"] = round(qty * unit_price, 2)
    return line


def compute_invoice_totals(invoice: dict) -> dict:
    """Compute invoice subtotal, vat, total"""
    lines = invoice.get("lines", [])
    subtotal = sum(l.get("line_total", 0) for l in lines)
    vat_percent = invoice.get("vat_percent", 0) or 0
    vat_amount = round(subtotal * vat_percent / 100, 2)
    total = round(subtotal + vat_amount, 2)
    invoice["subtotal"] = round(subtotal, 2)
    invoice["vat_amount"] = vat_amount
    invoice["total"] = total
    return invoice


async def update_invoice_status(invoice_id: str, org_id: str):
    """Auto-update invoice status based on allocations and due date"""
    invoice = await db.invoices.find_one({"id": invoice_id, "org_id": org_id})
    if not invoice or invoice["status"] == "Cancelled":
        return
    
    # Calculate paid amount from allocations
    allocations = await db.payment_allocations.find({"invoice_id": invoice_id}).to_list(100)
    paid_amount = sum(a.get("amount_allocated", 0) for a in allocations)
    remaining = round(invoice["total"] - paid_amount, 2)
    
    # Determine status
    if remaining <= 0:
        new_status = "Paid"
    elif paid_amount > 0:
        new_status = "PartiallyPaid"
    elif invoice["status"] in ["Sent", "PartiallyPaid", "Overdue"] and invoice.get("due_date"):
        # When all payments removed, go back to Sent or Overdue based on due date
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if invoice["due_date"] < today:
            new_status = "Overdue"
        else:
            new_status = "Sent"
    else:
        new_status = invoice["status"]
    
    await db.invoices.update_one({"id": invoice_id}, {"$set": {
        "paid_amount": round(paid_amount, 2),
        "remaining_amount": max(0, remaining),
        "status": new_status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }})


# ══════════════════════════════════════════════════════════════════════════════
# INVOICE NUMBERING SYSTEM
# ══════════════════════════════════════════════════════════════════════════════

async def get_invoice_settings(org_id: str) -> dict:
    """Get or create invoice numbering settings for organization"""
    settings = await db.invoice_settings.find_one({"org_id": org_id})
    if not settings:
        # Create default settings
        settings = {
            "org_id": org_id,
            "issued_auto_numbering": True,
            "issued_prefix": "INV",
            "issued_next_number": 1,
            "issued_starting_number": 1,
            "received_auto_numbering": False,  # Usually manually entered
            "received_prefix": "BILL",
            "received_next_number": 1,
            "received_starting_number": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.invoice_settings.insert_one(settings)
    # Remove _id before returning
    if "_id" in settings:
        del settings["_id"]
    return settings


async def get_next_invoice_no(org_id: str, direction: str) -> str:
    """Generate sequential invoice number with atomic increment"""
    settings = await get_invoice_settings(org_id)
    
    if direction == "Issued":
        if not settings.get("issued_auto_numbering", True):
            return ""  # Manual numbering
        prefix = settings.get("issued_prefix", "INV")
        number_field = "issued_next_number"
    else:
        if not settings.get("received_auto_numbering", False):
            return ""  # Manual numbering for bills
        prefix = settings.get("received_prefix", "BILL")
        number_field = "received_next_number"
    
    # Atomic increment to prevent race conditions
    result = await db.invoice_settings.find_one_and_update(
        {"org_id": org_id},
        {"$inc": {number_field: 1}, "$set": {"updated_at": datetime.now(timezone.utc).isoformat()}},
        return_document=False  # Return the document BEFORE update
    )
    
    current_number = result.get(number_field, 1)
    return f"{prefix}-{current_number:04d}"


async def validate_invoice_no_unique(org_id: str, invoice_no: str, exclude_id: str = None) -> bool:
    """Check if invoice number is unique within organization"""
    query = {"org_id": org_id, "invoice_no": invoice_no}
    if exclude_id:
        query["id"] = {"$ne": exclude_id}
    existing = await db.invoices.find_one(query)
    return existing is None


async def get_safe_starting_number(org_id: str, direction: str, requested_start: int) -> int:
    """Get safe starting number that won't conflict with existing invoices"""
    prefix = "INV" if direction == "Issued" else "BILL"
    
    # Find the highest existing number
    highest = await db.invoices.find_one(
        {"org_id": org_id, "direction": direction, "invoice_no": {"$regex": f"^{prefix}-"}},
        {"_id": 0, "invoice_no": 1},
        sort=[("invoice_no", -1)]
    )
    
    max_existing = 0
    if highest and highest.get("invoice_no"):
        try:
            parts = highest["invoice_no"].split("-")
            max_existing = int(parts[-1])
        except:
            pass
    
    return max(requested_start, max_existing + 1)


# ── Invoice Settings Endpoints ─────────────────────────────────────────────────

@router.get("/finance/invoice-settings")
async def get_settings(user: dict = Depends(require_m5)):
    """Get invoice numbering settings"""
    if user["role"] not in ["Admin", "Owner", "Accountant"]:
        raise HTTPException(status_code=403, detail="Нямате права за достъп до настройките")
    
    settings = await get_invoice_settings(user["org_id"])
    
    # Also return current highest invoice numbers for reference
    issued_highest = await db.invoices.find_one(
        {"org_id": user["org_id"], "direction": "Issued"},
        {"_id": 0, "invoice_no": 1},
        sort=[("created_at", -1)]
    )
    received_highest = await db.invoices.find_one(
        {"org_id": user["org_id"], "direction": "Received"},
        {"_id": 0, "invoice_no": 1},
        sort=[("created_at", -1)]
    )
    
    return {
        **settings,
        "issued_last_used": issued_highest.get("invoice_no") if issued_highest else None,
        "received_last_used": received_highest.get("invoice_no") if received_highest else None,
    }


@router.put("/finance/invoice-settings")
async def update_settings(data: dict, user: dict = Depends(require_m5)):
    """Update invoice numbering settings (Admin only)"""
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Само администратори могат да променят настройките")
    
    org_id = user["org_id"]
    
    # Validate and get safe numbers if changing starting/next numbers
    update = {"updated_at": datetime.now(timezone.utc).isoformat()}
    
    if "issued_auto_numbering" in data:
        update["issued_auto_numbering"] = bool(data["issued_auto_numbering"])
    
    if "issued_prefix" in data:
        prefix = str(data["issued_prefix"]).strip().upper()
        if prefix:
            update["issued_prefix"] = prefix
    
    if "issued_next_number" in data:
        requested = int(data["issued_next_number"])
        safe_number = await get_safe_starting_number(org_id, "Issued", requested)
        update["issued_next_number"] = safe_number
        if safe_number != requested:
            # Return warning in response
            pass
    
    if "issued_starting_number" in data:
        update["issued_starting_number"] = int(data["issued_starting_number"])
    
    if "received_auto_numbering" in data:
        update["received_auto_numbering"] = bool(data["received_auto_numbering"])
    
    if "received_prefix" in data:
        prefix = str(data["received_prefix"]).strip().upper()
        if prefix:
            update["received_prefix"] = prefix
    
    if "received_next_number" in data:
        requested = int(data["received_next_number"])
        safe_number = await get_safe_starting_number(org_id, "Received", requested)
        update["received_next_number"] = safe_number
    
    await db.invoice_settings.update_one(
        {"org_id": org_id},
        {"$set": update},
        upsert=True
    )
    
    return await get_settings(user)


@router.get("/finance/next-invoice-number")
async def get_next_number(
    direction: str = "Issued",
    user: dict = Depends(require_m5)
):
    """Preview next invoice number without reserving it"""
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    settings = await get_invoice_settings(user["org_id"])
    
    if direction == "Issued":
        if not settings.get("issued_auto_numbering", True):
            return {"auto_numbering": False, "next_number": None}
        prefix = settings.get("issued_prefix", "INV")
        next_num = settings.get("issued_next_number", 1)
    else:
        if not settings.get("received_auto_numbering", False):
            return {"auto_numbering": False, "next_number": None}
        prefix = settings.get("received_prefix", "BILL")
        next_num = settings.get("received_next_number", 1)
    
    return {
        "auto_numbering": True,
        "next_number": f"{prefix}-{next_num:04d}",
        "prefix": prefix,
        "number": next_num,
    }


# ── Financial Accounts ─────────────────────────────────────────────

@router.get("/finance/accounts")
async def list_accounts(user: dict = Depends(require_m5)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    accounts = await db.financial_accounts.find(
        {"org_id": user["org_id"]},
        {"_id": 0}
    ).sort("name", 1).to_list(100)
    
    # Calculate current balance for each account
    for acc in accounts:
        inflows = await db.finance_payments.aggregate([
            {"$match": {"org_id": user["org_id"], "account_id": acc["id"], "direction": "Inflow"}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
        ]).to_list(1)
        outflows = await db.finance_payments.aggregate([
            {"$match": {"org_id": user["org_id"], "account_id": acc["id"], "direction": "Outflow"}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
        ]).to_list(1)
        inflow_total = inflows[0]["total"] if inflows else 0
        outflow_total = outflows[0]["total"] if outflows else 0
        acc["current_balance"] = round(acc.get("opening_balance", 0) + inflow_total - outflow_total, 2)
    
    return accounts


@router.post("/finance/accounts", status_code=201)
async def create_account(data: FinancialAccountCreate, user: dict = Depends(require_m5)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    now = datetime.now(timezone.utc).isoformat()
    account = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "name": data.name,
        "type": data.type,
        "currency": data.currency,
        "opening_balance": data.opening_balance,
        "active": data.active,
        "created_at": now,
        "updated_at": now,
    }
    await db.financial_accounts.insert_one(account)
    await log_audit(user["org_id"], user["id"], user["email"], "account_created", "account", account["id"],
                    {"name": data.name, "type": data.type})
    return {k: v for k, v in account.items() if k != "_id"}


@router.put("/finance/accounts/{account_id}")
async def update_account(account_id: str, data: FinancialAccountUpdate, user: dict = Depends(require_m5)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    account = await db.financial_accounts.find_one({"id": account_id, "org_id": user["org_id"]})
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    await db.financial_accounts.update_one({"id": account_id}, {"$set": update})
    return await db.financial_accounts.find_one({"id": account_id}, {"_id": 0})


@router.delete("/finance/accounts/{account_id}")
async def delete_account(account_id: str, user: dict = Depends(require_m5)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    # Check if any payments use this account
    payment_count = await db.finance_payments.count_documents({"account_id": account_id})
    if payment_count > 0:
        raise HTTPException(status_code=400, detail="Cannot delete account with existing payments")
    
    await db.financial_accounts.delete_one({"id": account_id, "org_id": user["org_id"]})
    return {"ok": True}


# ── Invoices ───────────────────────────────────────────────────────

@router.get("/finance/invoices")
async def list_invoices(
    user: dict = Depends(require_m5),
    direction: Optional[str] = None,
    status: Optional[str] = None,
    project_id: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
):
    if not finance_permission(user):
        # SiteManager can see project-linked invoices only
        if user["role"] == "SiteManager":
            assigned = await get_user_project_ids(user["id"])
            if not assigned:
                return []
            project_id = project_id or {"$in": assigned}
        else:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    query = {"org_id": user["org_id"]}
    if direction:
        query["direction"] = direction
    if status:
        query["status"] = status
    if project_id:
        if isinstance(project_id, dict):
            query["project_id"] = project_id
        else:
            query["project_id"] = project_id
    if from_date:
        query["issue_date"] = {"$gte": from_date}
    if to_date:
        query.setdefault("issue_date", {})["$lte"] = to_date
    
    invoices = await db.invoices.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    
    # Check for overdue
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for inv in invoices:
        if inv["status"] in ["Sent", "PartiallyPaid"] and inv.get("due_date", "") < today:
            inv["is_overdue"] = True
        else:
            inv["is_overdue"] = False
        # Enrich with project code
        if inv.get("project_id"):
            p = await db.projects.find_one({"id": inv["project_id"]}, {"_id": 0, "code": 1, "name": 1})
            inv["project_code"] = p["code"] if p else ""
            inv["project_name"] = p["name"] if p else ""
    
    return invoices


@router.post("/finance/invoices", status_code=201)
async def create_invoice(data: InvoiceCreate, user: dict = Depends(require_m5)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    # Enforce invoice limit (monthly)
    await enforce_limit(user["org_id"], "invoices")
    
    org_id = user["org_id"]
    
    # Generate or validate invoice number
    invoice_no = data.invoice_no
    if not invoice_no or invoice_no.strip() == "":
        # Auto-generate number
        invoice_no = await get_next_invoice_no(org_id, data.direction)
        if not invoice_no:
            raise HTTPException(status_code=400, detail="Номерът на фактурата е задължителен")
    else:
        # Check uniqueness for provided number
        if not await validate_invoice_no_unique(org_id, invoice_no):
            raise HTTPException(status_code=400, detail=f"Фактура с номер {invoice_no} вече съществува")
    
    now = datetime.now(timezone.utc).isoformat()
    
    # Process lines
    lines = []
    for i, line in enumerate(data.lines):
        l = {
            "id": str(uuid.uuid4()),
            "description": line.description,
            "unit": line.unit,
            "qty": line.qty,
            "unit_price": line.unit_price,
            "sort_order": i,
        }
        lines.append(compute_invoice_line(l))
    
    invoice = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "direction": data.direction,
        "invoice_no": invoice_no,  # Use the generated/validated number
        "status": "Draft",
        "project_id": data.project_id,
        "counterparty_name": data.counterparty_name,
        "counterparty_eik": data.counterparty_eik,
        "counterparty_vat_no": data.counterparty_vat_no,
        "counterparty_address": data.counterparty_address,
        "counterparty_mol": data.counterparty_mol,
        "counterparty_email": data.counterparty_email,
        "counterparty_phone": data.counterparty_phone,
        "issue_date": data.issue_date,
        "due_date": data.due_date,
        "currency": data.currency,
        "vat_percent": data.vat_percent,
        "lines": lines,
        "notes": data.notes,
        "paid_amount": 0,
        "remaining_amount": 0,
        "created_at": now,
        "updated_at": now,
    }
    invoice = compute_invoice_totals(invoice)
    invoice["remaining_amount"] = invoice["total"]
    
    await db.invoices.insert_one(invoice)
    await log_audit(user["org_id"], user["id"], user["email"], "invoice_created", "invoice", invoice["id"],
                    {"invoice_no": data.invoice_no, "direction": data.direction})
    
    return {k: v for k, v in invoice.items() if k != "_id"}


@router.get("/finance/invoices/{invoice_id}")
async def get_invoice(invoice_id: str, user: dict = Depends(require_m5)):
    invoice = await db.invoices.find_one({"id": invoice_id, "org_id": user["org_id"]}, {"_id": 0})
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    # Permission check
    if not finance_permission(user):
        if user["role"] == "SiteManager":
            assigned = await get_user_project_ids(user["id"])
            if invoice.get("project_id") not in assigned:
                raise HTTPException(status_code=403, detail="Access denied")
        else:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    # Enrich with project
    if invoice.get("project_id"):
        p = await db.projects.find_one({"id": invoice["project_id"]}, {"_id": 0, "code": 1, "name": 1})
        invoice["project_code"] = p["code"] if p else ""
        invoice["project_name"] = p["name"] if p else ""
    
    # Get allocations
    allocations = await db.payment_allocations.find(
        {"invoice_id": invoice_id},
        {"_id": 0}
    ).to_list(100)
    for alloc in allocations:
        payment = await db.finance_payments.find_one({"id": alloc["payment_id"]}, {"_id": 0, "date": 1, "reference": 1, "method": 1})
        if payment:
            alloc["payment_date"] = payment.get("date")
            alloc["payment_reference"] = payment.get("reference")
            alloc["payment_method"] = payment.get("method")
    invoice["allocations"] = allocations
    
    return invoice


@router.put("/finance/invoices/{invoice_id}")
async def update_invoice(invoice_id: str, data: InvoiceUpdate, user: dict = Depends(require_m5)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    invoice = await db.invoices.find_one({"id": invoice_id, "org_id": user["org_id"]})
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice["status"] not in ["Draft"]:
        raise HTTPException(status_code=400, detail="Can only edit Draft invoices")
    
    # Check invoice_no uniqueness if changed
    if data.invoice_no and data.invoice_no != invoice["invoice_no"]:
        existing = await db.invoices.find_one({
            "org_id": user["org_id"],
            "direction": invoice["direction"],
            "invoice_no": data.invoice_no,
            "id": {"$ne": invoice_id},
        })
        if existing:
            raise HTTPException(status_code=400, detail="Invoice number already exists")
    
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    await db.invoices.update_one({"id": invoice_id}, {"$set": update})
    
    # Recompute if vat changed
    if "vat_percent" in update:
        updated = await db.invoices.find_one({"id": invoice_id})
        updated = compute_invoice_totals({k: v for k, v in updated.items() if k != "_id"})
        await db.invoices.update_one({"id": invoice_id}, {"$set": {
            "subtotal": updated["subtotal"],
            "vat_amount": updated["vat_amount"],
            "total": updated["total"],
            "remaining_amount": updated["total"],
        }})
    
    return await db.invoices.find_one({"id": invoice_id}, {"_id": 0})


@router.put("/finance/invoices/{invoice_id}/lines")
async def update_invoice_lines(invoice_id: str, data: InvoiceLinesUpdate, user: dict = Depends(require_m5)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    invoice = await db.invoices.find_one({"id": invoice_id, "org_id": user["org_id"]})
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice["status"] not in ["Draft"]:
        raise HTTPException(status_code=400, detail="Can only edit Draft invoice lines")
    
    lines = []
    for i, line in enumerate(data.lines):
        l = {
            "id": str(uuid.uuid4()),
            "description": line.description,
            "unit": line.unit,
            "qty": line.qty,
            "unit_price": line.unit_price,
            "project_id": line.project_id,
            "cost_category": line.cost_category,
            "sort_order": i,
        }
        lines.append(compute_invoice_line(l))
    
    now = datetime.now(timezone.utc).isoformat()
    invoice["lines"] = lines
    invoice = compute_invoice_totals(invoice)
    
    await db.invoices.update_one({"id": invoice_id}, {"$set": {
        "lines": lines,
        "subtotal": invoice["subtotal"],
        "vat_amount": invoice["vat_amount"],
        "total": invoice["total"],
        "remaining_amount": invoice["total"] - invoice.get("paid_amount", 0),
        "updated_at": now,
    }})
    
    return await db.invoices.find_one({"id": invoice_id}, {"_id": 0})


@router.post("/finance/invoices/{invoice_id}/send")
async def send_invoice(invoice_id: str, user: dict = Depends(require_m5)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    invoice = await db.invoices.find_one({"id": invoice_id, "org_id": user["org_id"]})
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice["status"] != "Draft":
        raise HTTPException(status_code=400, detail="Only Draft invoices can be sent")
    if len(invoice.get("lines", [])) == 0:
        raise HTTPException(status_code=400, detail="Invoice must have at least one line")
    
    now = datetime.now(timezone.utc).isoformat()
    
    # Check if already overdue
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    new_status = "Overdue" if invoice.get("due_date", "") < today else "Sent"
    
    await db.invoices.update_one({"id": invoice_id}, {"$set": {
        "status": new_status,
        "sent_at": now,
        "updated_at": now,
    }})
    
    await log_audit(user["org_id"], user["id"], user["email"], "invoice_sent", "invoice", invoice_id,
                    {"invoice_no": invoice["invoice_no"]})
    
    return await db.invoices.find_one({"id": invoice_id}, {"_id": 0})


@router.post("/finance/invoices/{invoice_id}/cancel")
async def cancel_invoice(invoice_id: str, user: dict = Depends(require_m5)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    invoice = await db.invoices.find_one({"id": invoice_id, "org_id": user["org_id"]})
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice["status"] == "Paid":
        raise HTTPException(status_code=400, detail="Cannot cancel paid invoices")
    
    # Check for allocations
    alloc_count = await db.payment_allocations.count_documents({"invoice_id": invoice_id})
    if alloc_count > 0:
        raise HTTPException(status_code=400, detail="Cannot cancel invoice with payment allocations")
    
    now = datetime.now(timezone.utc).isoformat()
    await db.invoices.update_one({"id": invoice_id}, {"$set": {
        "status": "Cancelled",
        "updated_at": now,
    }})
    
    await log_audit(user["org_id"], user["id"], user["email"], "invoice_cancelled", "invoice", invoice_id,
                    {"invoice_no": invoice["invoice_no"]})
    
    return await db.invoices.find_one({"id": invoice_id}, {"_id": 0})


@router.delete("/finance/invoices/{invoice_id}")
async def delete_invoice(invoice_id: str, user: dict = Depends(require_m5)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    invoice = await db.invoices.find_one({"id": invoice_id, "org_id": user["org_id"]})
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice["status"] != "Draft":
        raise HTTPException(status_code=400, detail="Can only delete Draft invoices")
    
    await db.invoices.delete_one({"id": invoice_id})
    return {"ok": True}


# ── Invoice Direct Payments ────────────────────────────────────────

@router.get("/finance/invoices/{invoice_id}/payments")
async def list_invoice_payments(invoice_id: str, user: dict = Depends(require_m5)):
    """List all payments allocated to this invoice"""
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    invoice = await db.invoices.find_one({"id": invoice_id, "org_id": user["org_id"]})
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    allocations = await db.payment_allocations.find(
        {"invoice_id": invoice_id},
        {"_id": 0}
    ).sort("allocated_at", -1).to_list(100)
    
    result = []
    for alloc in allocations:
        payment = await db.finance_payments.find_one(
            {"id": alloc["payment_id"]},
            {"_id": 0}
        )
        if payment:
            acc = await db.financial_accounts.find_one(
                {"id": payment.get("account_id")},
                {"_id": 0, "name": 1, "type": 1}
            )
            result.append({
                "id": alloc["id"],
                "payment_id": payment["id"],
                "amount": alloc["amount_allocated"],
                "date": payment.get("date"),
                "method": payment.get("method"),
                "reference": payment.get("reference"),
                "note": payment.get("note"),
                "account_name": acc["name"] if acc else "",
                "account_type": acc["type"] if acc else "",
                "allocated_at": alloc.get("allocated_at"),
            })
    
    return result


@router.post("/finance/invoices/{invoice_id}/payments", status_code=201)
async def add_invoice_payment(invoice_id: str, data: dict, user: dict = Depends(require_m5)):
    """Quick-pay: create a payment and allocate it to this invoice in one step"""
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    org_id = user["org_id"]
    invoice = await db.invoices.find_one({"id": invoice_id, "org_id": org_id})
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    if invoice["status"] in ["Draft", "Cancelled"]:
        raise HTTPException(status_code=400, detail="Не може да се добави плащане към чернова или анулирана фактура")
    
    amount = float(data.get("amount", 0))
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Сумата трябва да е положителна")
    
    remaining = invoice.get("remaining_amount", invoice["total"])
    if amount > remaining + 0.01:  # small tolerance for rounding
        raise HTTPException(status_code=400, detail=f"Сумата надвишава остатъка ({remaining})")
    
    account_id = data.get("account_id")
    if not account_id:
        raise HTTPException(status_code=400, detail="Сметката е задължителна")
    
    account = await db.financial_accounts.find_one({"id": account_id, "org_id": org_id})
    if not account:
        raise HTTPException(status_code=404, detail="Сметката не е намерена")
    
    payment_direction = "Inflow" if invoice["direction"] == "Issued" else "Outflow"
    payment_date = data.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    method = data.get("method", "BankTransfer")
    reference = data.get("reference", "")
    note = data.get("note", "")
    
    now = datetime.now(timezone.utc).isoformat()
    
    # Create payment
    payment = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "direction": payment_direction,
        "amount": amount,
        "currency": invoice.get("currency", "EUR"),
        "date": payment_date,
        "method": method,
        "account_id": account_id,
        "counterparty_name": invoice.get("counterparty_name", ""),
        "reference": reference,
        "note": note or f"Плащане по ф-ра {invoice.get('invoice_no', '')}",
        "created_at": now,
        "updated_at": now,
    }
    await db.finance_payments.insert_one(payment)
    
    # Create allocation
    allocation = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "payment_id": payment["id"],
        "invoice_id": invoice_id,
        "amount_allocated": amount,
        "allocated_at": now,
    }
    await db.payment_allocations.insert_one(allocation)
    
    # Update invoice status
    await update_invoice_status(invoice_id, org_id)
    
    await log_audit(org_id, user["id"], user["email"], "invoice_payment_added", "invoice", invoice_id,
                    {"amount": amount, "payment_id": payment["id"]})
    
    # Return updated invoice
    updated_invoice = await db.invoices.find_one({"id": invoice_id}, {"_id": 0})
    return {
        "ok": True,
        "payment_id": payment["id"],
        "allocation_id": allocation["id"],
        "amount": amount,
        "invoice": updated_invoice,
    }


@router.delete("/finance/invoices/{invoice_id}/payments/{allocation_id}")
async def remove_invoice_payment(invoice_id: str, allocation_id: str, user: dict = Depends(require_m5)):
    """Remove a payment allocation from an invoice"""
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    org_id = user["org_id"]
    invoice = await db.invoices.find_one({"id": invoice_id, "org_id": org_id})
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    if invoice["status"] == "Cancelled":
        raise HTTPException(status_code=400, detail="Не може да се премахне плащане от анулирана фактура")
    
    alloc = await db.payment_allocations.find_one({"id": allocation_id, "invoice_id": invoice_id})
    if not alloc:
        raise HTTPException(status_code=404, detail="Разпределението не е намерено")
    
    # Delete the allocation
    await db.payment_allocations.delete_one({"id": allocation_id})
    
    # Check if the payment has any remaining allocations, if not delete it too
    remaining_allocs = await db.payment_allocations.count_documents({"payment_id": alloc["payment_id"]})
    if remaining_allocs == 0:
        await db.finance_payments.delete_one({"id": alloc["payment_id"]})
    
    # Update invoice status
    await update_invoice_status(invoice_id, org_id)
    
    await log_audit(org_id, user["id"], user["email"], "invoice_payment_removed", "invoice", invoice_id,
                    {"allocation_id": allocation_id})
    
    return {"ok": True}


# ── Payments ───────────────────────────────────────────────────────

@router.get("/finance/payments")
async def list_payments(
    user: dict = Depends(require_m5),
    account_id: Optional[str] = None,
    direction: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    query = {"org_id": user["org_id"]}
    if account_id:
        query["account_id"] = account_id
    if direction:
        query["direction"] = direction
    if from_date:
        query["date"] = {"$gte": from_date}
    if to_date:
        query.setdefault("date", {})["$lte"] = to_date
    
    payments = await db.finance_payments.find(query, {"_id": 0}).sort("date", -1).to_list(500)
    
    # Enrich with account name and allocation info
    for pay in payments:
        acc = await db.financial_accounts.find_one({"id": pay["account_id"]}, {"_id": 0, "name": 1, "type": 1})
        pay["account_name"] = acc["name"] if acc else "Unknown"
        pay["account_type"] = acc["type"] if acc else ""
        
        # Get allocations
        allocations = await db.payment_allocations.find({"payment_id": pay["id"]}, {"_id": 0}).to_list(100)
        allocated = sum(a.get("amount_allocated", 0) for a in allocations)
        pay["allocated_amount"] = round(allocated, 2)
        pay["unallocated_amount"] = round(pay["amount"] - allocated, 2)
        pay["allocation_count"] = len(allocations)
    
    return payments


@router.post("/finance/payments", status_code=201)
async def create_payment(data: PaymentCreate, user: dict = Depends(require_m5)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    # Verify account exists
    account = await db.financial_accounts.find_one({"id": data.account_id, "org_id": user["org_id"]})
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    now = datetime.now(timezone.utc).isoformat()
    payment = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "direction": data.direction,
        "amount": data.amount,
        "currency": data.currency,
        "date": data.date,
        "method": data.method,
        "account_id": data.account_id,
        "counterparty_name": data.counterparty_name,
        "reference": data.reference,
        "note": data.note,
        "created_at": now,
        "updated_at": now,
    }
    await db.finance_payments.insert_one(payment)
    
    await log_audit(user["org_id"], user["id"], user["email"], "payment_created", "payment", payment["id"],
                    {"amount": data.amount, "direction": data.direction, "account_id": data.account_id})
    
    return {k: v for k, v in payment.items() if k != "_id"}


@router.get("/finance/payments/{payment_id}")
async def get_payment(payment_id: str, user: dict = Depends(require_m5)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    payment = await db.finance_payments.find_one({"id": payment_id, "org_id": user["org_id"]}, {"_id": 0})
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    
    # Enrich
    acc = await db.financial_accounts.find_one({"id": payment["account_id"]}, {"_id": 0, "name": 1, "type": 1})
    payment["account_name"] = acc["name"] if acc else "Unknown"
    
    # Get allocations
    allocations = await db.payment_allocations.find({"payment_id": payment_id}, {"_id": 0}).to_list(100)
    for alloc in allocations:
        inv = await db.invoices.find_one({"id": alloc["invoice_id"]}, {"_id": 0, "invoice_no": 1, "direction": 1, "total": 1})
        if inv:
            alloc["invoice_no"] = inv["invoice_no"]
            alloc["invoice_direction"] = inv["direction"]
            alloc["invoice_total"] = inv["total"]
    payment["allocations"] = allocations
    
    allocated = sum(a.get("amount_allocated", 0) for a in allocations)
    payment["allocated_amount"] = round(allocated, 2)
    payment["unallocated_amount"] = round(payment["amount"] - allocated, 2)
    
    return payment


@router.post("/finance/payments/{payment_id}/allocate")
async def allocate_payment(payment_id: str, data: AllocatePaymentRequest, user: dict = Depends(require_m5)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    payment = await db.finance_payments.find_one({"id": payment_id, "org_id": user["org_id"]})
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    
    # Get current allocations
    existing_allocs = await db.payment_allocations.find({"payment_id": payment_id}).to_list(100)
    current_allocated = sum(a.get("amount_allocated", 0) for a in existing_allocs)
    available = payment["amount"] - current_allocated
    
    now = datetime.now(timezone.utc).isoformat()
    results = []
    
    for alloc in data.allocations:
        if alloc.amount <= 0:
            continue
        
        # Check payment has enough available
        if alloc.amount > available:
            raise HTTPException(status_code=400, detail=f"Allocation exceeds available payment amount ({available})")
        
        # Check invoice exists and has remaining
        invoice = await db.invoices.find_one({"id": alloc.invoice_id, "org_id": user["org_id"]})
        if not invoice:
            raise HTTPException(status_code=404, detail=f"Invoice {alloc.invoice_id} not found")
        if invoice["status"] == "Cancelled":
            raise HTTPException(status_code=400, detail="Cannot allocate to cancelled invoice")
        
        remaining = invoice.get("remaining_amount", invoice["total"])
        if alloc.amount > remaining:
            raise HTTPException(status_code=400, detail=f"Allocation exceeds invoice remaining ({remaining})")
        
        # Check direction match
        expected_dir = "Inflow" if invoice["direction"] == "Issued" else "Outflow"
        if payment["direction"] != expected_dir:
            raise HTTPException(status_code=400, detail="Payment direction doesn't match invoice type")
        
        # Create allocation
        allocation = {
            "id": str(uuid.uuid4()),
            "org_id": user["org_id"],
            "payment_id": payment_id,
            "invoice_id": alloc.invoice_id,
            "amount_allocated": alloc.amount,
            "allocated_at": now,
        }
        await db.payment_allocations.insert_one(allocation)
        results.append({k: v for k, v in allocation.items() if k != "_id"})
        
        available -= alloc.amount
        
        # Update invoice status
        await update_invoice_status(alloc.invoice_id, user["org_id"])
    
    await log_audit(user["org_id"], user["id"], user["email"], "payment_allocated", "payment", payment_id,
                    {"allocations": len(results)})
    
    return {"ok": True, "allocations": results}


@router.delete("/finance/payments/{payment_id}")
async def delete_payment(payment_id: str, user: dict = Depends(require_m5)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    payment = await db.finance_payments.find_one({"id": payment_id, "org_id": user["org_id"]})
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    
    # Check for allocations
    alloc_count = await db.payment_allocations.count_documents({"payment_id": payment_id})
    if alloc_count > 0:
        raise HTTPException(status_code=400, detail="Cannot delete payment with allocations")
    
    await db.finance_payments.delete_one({"id": payment_id})
    return {"ok": True}


# ── Finance Stats ──────────────────────────────────────────────────

@router.get("/finance/stats")
async def get_finance_stats(user: dict = Depends(require_m5)):
    if not finance_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    org_id = user["org_id"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    # Receivables (Issued invoices not fully paid)
    receivables = await db.invoices.aggregate([
        {"$match": {"org_id": org_id, "direction": "Issued", "status": {"$nin": ["Draft", "Cancelled", "Paid"]}}},
        {"$group": {"_id": None, "total": {"$sum": "$remaining_amount"}, "count": {"$sum": 1}}}
    ]).to_list(1)
    
    # Overdue receivables
    overdue_recv = await db.invoices.aggregate([
        {"$match": {"org_id": org_id, "direction": "Issued", "status": {"$nin": ["Draft", "Cancelled", "Paid"]}, "due_date": {"$lt": today}}},
        {"$group": {"_id": None, "total": {"$sum": "$remaining_amount"}, "count": {"$sum": 1}}}
    ]).to_list(1)
    
    # Payables (Received invoices not fully paid)
    payables = await db.invoices.aggregate([
        {"$match": {"org_id": org_id, "direction": "Received", "status": {"$nin": ["Draft", "Cancelled", "Paid"]}}},
        {"$group": {"_id": None, "total": {"$sum": "$remaining_amount"}, "count": {"$sum": 1}}}
    ]).to_list(1)
    
    # Overdue payables
    overdue_pay = await db.invoices.aggregate([
        {"$match": {"org_id": org_id, "direction": "Received", "status": {"$nin": ["Draft", "Cancelled", "Paid"]}, "due_date": {"$lt": today}}},
        {"$group": {"_id": None, "total": {"$sum": "$remaining_amount"}, "count": {"$sum": 1}}}
    ]).to_list(1)
    
    # Account balances
    accounts = await db.financial_accounts.find({"org_id": org_id, "active": True}, {"_id": 0}).to_list(100)
    cash_balance = 0
    bank_balance = 0
    for acc in accounts:
        inflows = await db.finance_payments.aggregate([
            {"$match": {"org_id": org_id, "account_id": acc["id"], "direction": "Inflow"}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
        ]).to_list(1)
        outflows = await db.finance_payments.aggregate([
            {"$match": {"org_id": org_id, "account_id": acc["id"], "direction": "Outflow"}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
        ]).to_list(1)
        balance = acc.get("opening_balance", 0) + (inflows[0]["total"] if inflows else 0) - (outflows[0]["total"] if outflows else 0)
        if acc["type"] == "Cash":
            cash_balance += balance
        else:
            bank_balance += balance
    
    return {
        "receivables_total": round(receivables[0]["total"], 2) if receivables else 0,
        "receivables_count": receivables[0]["count"] if receivables else 0,
        "receivables_overdue": round(overdue_recv[0]["total"], 2) if overdue_recv else 0,
        "receivables_overdue_count": overdue_recv[0]["count"] if overdue_recv else 0,
        "payables_total": round(payables[0]["total"], 2) if payables else 0,
        "payables_count": payables[0]["count"] if payables else 0,
        "payables_overdue": round(overdue_pay[0]["total"], 2) if overdue_pay else 0,
        "payables_overdue_count": overdue_pay[0]["count"] if overdue_pay else 0,
        "cash_balance": round(cash_balance, 2),
        "bank_balance": round(bank_balance, 2),
    }


@router.get("/finance/enums")
async def get_finance_enums():
    return {
        "account_types": ACCOUNT_TYPES,
        "invoice_directions": INVOICE_DIRECTIONS,
        "invoice_statuses": INVOICE_STATUSES,
        "payment_directions": PAYMENT_DIRECTIONS,
        "cost_categories": COST_CATEGORIES,
    }
