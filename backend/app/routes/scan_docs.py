"""
Routes - Scan Documents (scanned invoices/receipts).
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from typing import Optional
from datetime import datetime, timezone
import uuid
import os
import logging

logger = logging.getLogger(__name__)

from app.db import db
from app.deps.auth import get_current_user
from app.utils.audit import log_audit
from ..models.scan_docs import ScanDocCreate, ScanDocUpdate

router = APIRouter(tags=["ScanDocs"])


def scan_permission(user: dict) -> bool:
    """Check if user can manage scan documents"""
    return user["role"] in ["Admin", "Owner", "Accountant", "SiteManager", "Driver", "Technician"]


# ── Scan Documents CRUD ────────────────────────────────────────────

@router.get("/scan-docs")
async def list_scan_docs(
    user: dict = Depends(get_current_user),
    linked_invoice_id: Optional[str] = None,
    unlinked_only: bool = False,
    uploaded_by: Optional[str] = None,
):
    """List scan documents"""
    if not scan_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    query = {"org_id": user["org_id"]}
    
    if linked_invoice_id:
        query["linked_invoice_id"] = linked_invoice_id
    if unlinked_only:
        query["linked_invoice_id"] = None
    if uploaded_by:
        query["uploaded_by_user_id"] = uploaded_by
    
    docs = await db.scan_docs.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    
    # Enrich with uploader name
    for doc in docs:
        if doc.get("uploaded_by_user_id"):
            uploader = await db.users.find_one({"id": doc["uploaded_by_user_id"]}, {"_id": 0, "first_name": 1, "last_name": 1})
            doc["uploaded_by_name"] = f"{uploader['first_name']} {uploader['last_name']}" if uploader else ""
        if doc.get("linked_invoice_id"):
            invoice = await db.invoices.find_one({"id": doc["linked_invoice_id"]}, {"_id": 0, "invoice_no": 1})
            doc["linked_invoice_no"] = invoice["invoice_no"] if invoice else ""
    
    return docs


@router.post("/scan-docs", status_code=201)
async def create_scan_doc(data: ScanDocCreate, user: dict = Depends(get_current_user)):
    """Create scan document record (after file is uploaded via media API)"""
    if not scan_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "file_url": data.file_url,
        "media_id": data.media_id,
        "original_filename": data.original_filename,
        "pages_count": data.pages_count,
        "notes": data.notes,
        "linked_invoice_id": data.linked_invoice_id,
        "uploaded_by_user_id": user["id"],
        "created_at": now,
        "updated_at": now,
    }
    
    await db.scan_docs.insert_one(doc)
    await log_audit(user["org_id"], user["id"], user["email"], "scan_doc_created", "scan_doc", doc["id"],
                    {"filename": data.original_filename})
    
    return {k: v for k, v in doc.items() if k != "_id"}


@router.get("/scan-docs/{doc_id}")
async def get_scan_doc(doc_id: str, user: dict = Depends(get_current_user)):
    """Get scan document details"""
    doc = await db.scan_docs.find_one({"id": doc_id, "org_id": user["org_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Scan document not found")
    
    # Enrich
    if doc.get("uploaded_by_user_id"):
        uploader = await db.users.find_one({"id": doc["uploaded_by_user_id"]}, {"_id": 0, "first_name": 1, "last_name": 1})
        doc["uploaded_by_name"] = f"{uploader['first_name']} {uploader['last_name']}" if uploader else ""
    if doc.get("linked_invoice_id"):
        invoice = await db.invoices.find_one({"id": doc["linked_invoice_id"]}, {"_id": 0, "invoice_no": 1, "direction": 1, "total": 1})
        doc["linked_invoice"] = invoice if invoice else None
    
    return doc


@router.put("/scan-docs/{doc_id}")
async def update_scan_doc(doc_id: str, data: ScanDocUpdate, user: dict = Depends(get_current_user)):
    """Update scan document"""
    if not scan_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    doc = await db.scan_docs.find_one({"id": doc_id, "org_id": user["org_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Scan document not found")
    
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    await db.scan_docs.update_one({"id": doc_id}, {"$set": update})
    return await db.scan_docs.find_one({"id": doc_id}, {"_id": 0})


@router.post("/scan-docs/{doc_id}/link/{invoice_id}")
async def link_scan_to_invoice(doc_id: str, invoice_id: str, user: dict = Depends(get_current_user)):
    """Link a scan document to an invoice"""
    if not scan_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    doc = await db.scan_docs.find_one({"id": doc_id, "org_id": user["org_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Scan document not found")
    
    invoice = await db.invoices.find_one({"id": invoice_id, "org_id": user["org_id"]})
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    now = datetime.now(timezone.utc).isoformat()
    
    # Update scan doc
    await db.scan_docs.update_one({"id": doc_id}, {"$set": {
        "linked_invoice_id": invoice_id,
        "updated_at": now
    }})
    
    # Update invoice
    await db.invoices.update_one({"id": invoice_id}, {"$set": {
        "scan_doc_id": doc_id,
        "updated_at": now
    }})
    
    await log_audit(user["org_id"], user["id"], user["email"], "scan_doc_linked", "scan_doc", doc_id,
                    {"invoice_id": invoice_id, "invoice_no": invoice["invoice_no"]})
    
    return {"ok": True, "scan_doc_id": doc_id, "invoice_id": invoice_id}


@router.post("/scan-docs/{doc_id}/unlink")
async def unlink_scan_from_invoice(doc_id: str, user: dict = Depends(get_current_user)):
    """Unlink a scan document from its invoice"""
    if not scan_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    doc = await db.scan_docs.find_one({"id": doc_id, "org_id": user["org_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Scan document not found")
    
    if not doc.get("linked_invoice_id"):
        raise HTTPException(status_code=400, detail="Scan document is not linked to any invoice")
    
    invoice_id = doc["linked_invoice_id"]
    now = datetime.now(timezone.utc).isoformat()
    
    # Update scan doc
    await db.scan_docs.update_one({"id": doc_id}, {"$set": {
        "linked_invoice_id": None,
        "updated_at": now
    }})
    
    # Update invoice
    await db.invoices.update_one({"id": invoice_id}, {"$set": {
        "scan_doc_id": None,
        "updated_at": now
    }})
    
    return {"ok": True}


@router.delete("/scan-docs/{doc_id}")
async def delete_scan_doc(doc_id: str, user: dict = Depends(get_current_user)):
    """Delete scan document"""
    if not scan_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    doc = await db.scan_docs.find_one({"id": doc_id, "org_id": user["org_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Scan document not found")
    
    # Unlink from invoice if linked
    if doc.get("linked_invoice_id"):
        await db.invoices.update_one(
            {"id": doc["linked_invoice_id"]},
            {"$set": {"scan_doc_id": None, "updated_at": datetime.now(timezone.utc).isoformat()}}
        )
    
    await db.scan_docs.delete_one({"id": doc_id})
    
    # Delete the physical file from storage
    file_path = doc.get("file_path") or doc.get("url") or doc.get("storage_path")
    if file_path:
        try:
            full_path = os.path.join("uploads", file_path) if not os.path.isabs(file_path) else file_path
            if os.path.exists(full_path):
                os.remove(full_path)
                logger.info(f"Deleted file: {full_path}")
        except OSError as e:
            logger.warning(f"Could not delete file {file_path}: {e}")
    
    return {"ok": True}
