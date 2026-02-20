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
    elif invoice["status"] == "Sent" and invoice.get("due_date"):
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


async def get_next_invoice_no(org_id: str, direction: str) -> str:
    """Generate sequential invoice number"""
    prefix = "INV" if direction == "Issued" else "BILL"
    last = await db.invoices.find_one(
        {"org_id": org_id, "direction": direction},
        {"_id": 0, "invoice_no": 1},
        sort=[("created_at", -1)]
    )
    if last and last.get("invoice_no"):
        try:
            parts = last["invoice_no"].split("-")
            num = int(parts[-1]) + 1
        except:
            num = 1
    else:
        num = 1
    return f"{prefix}-{num:04d}"


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
    
    # Check invoice_no uniqueness
    existing = await db.invoices.find_one({
        "org_id": user["org_id"],
        "direction": data.direction,
        "invoice_no": data.invoice_no,
    })
    if existing:
        raise HTTPException(status_code=400, detail="Invoice number already exists")
    
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
            "project_id": line.project_id,
            "cost_category": line.cost_category,
            "sort_order": i,
        }
        lines.append(compute_invoice_line(l))
    
    invoice = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "direction": data.direction,
        "invoice_no": data.invoice_no,
        "status": "Draft",
        "project_id": data.project_id,
        "counterparty_name": data.counterparty_name,
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
