"""
Routes - OCR Invoice Intake v1.
Upload → Extract → Review → Approve cycle.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.services.ocr_invoice import create_ocr_intake
from pathlib import Path

router = APIRouter(tags=["OCR Invoice"])


class ReviewData(BaseModel):
    supplier_name: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    currency: Optional[str] = None
    total_amount: Optional[float] = None
    vat_amount: Optional[float] = None
    subtotal_amount: Optional[float] = None
    notes: Optional[str] = None
    items: Optional[list] = None


class FromMedia(BaseModel):
    media_id: str
    project_id: Optional[str] = None
    supplier_id: Optional[str] = None


class RejectBody(BaseModel):
    reason: str = ""


# ── Upload ─────────────────────────────────────────────────────────

@router.post("/ocr-invoice/upload", status_code=201)
async def upload_invoice(
    file: UploadFile = File(...),
    project_id: str = Form(None),
    supplier_id: str = Form(None),
    user: dict = Depends(get_current_user),
):
    org_id = user["org_id"]
    now = datetime.now(timezone.utc).isoformat()

    # Save file
    content = await file.read()
    ext = file.filename.split(".")[-1] if "." in file.filename else "pdf"
    media_id = str(uuid.uuid4())
    filename = f"{media_id}.{ext}"
    upload_dir = Path("/app/backend/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / filename).write_bytes(content)

    media = {
        "id": media_id, "org_id": org_id, "owner_user_id": user["id"],
        "filename": file.filename, "stored_filename": filename,
        "url": f"/api/media/file/{filename}",
        "content_type": file.content_type or "application/octet-stream",
        "file_size": len(content), "context_type": "ocr_invoice",
        "context_id": media_id, "created_at": now,
    }
    await db.media_files.insert_one(media)

    intake = await create_ocr_intake(
        org_id, media_id, user["id"],
        project_id=project_id, supplier_id=supplier_id,
        source_type="upload", file_name=file.filename,
    )
    return intake


@router.post("/ocr-invoice/from-media", status_code=201)
async def from_media(data: FromMedia, user: dict = Depends(get_current_user)):
    media = await db.media_files.find_one({"id": data.media_id, "org_id": user["org_id"]})
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")

    intake = await create_ocr_intake(
        user["org_id"], data.media_id, user["id"],
        project_id=data.project_id, supplier_id=data.supplier_id,
        source_type="photo", file_name=media.get("filename", ""),
    )
    return intake


# ── List / Detail ──────────────────────────────────────────────────

@router.get("/ocr-invoice")
async def list_intakes(
    status: Optional[str] = None,
    project_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    query = {"org_id": user["org_id"]}
    if status:
        query["status"] = status
    if project_id:
        query["project_id"] = project_id
    items = await db.ocr_invoice_intake.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"items": items, "total": len(items)}


@router.get("/ocr-invoice/{intake_id}")
async def get_intake(intake_id: str, user: dict = Depends(get_current_user)):
    doc = await db.ocr_invoice_intake.find_one({"id": intake_id, "org_id": user["org_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Intake not found")
    return doc


@router.get("/ocr-invoice/{intake_id}/raw-text")
async def get_raw_text(intake_id: str, user: dict = Depends(get_current_user)):
    doc = await db.ocr_invoice_intake.find_one({"id": intake_id, "org_id": user["org_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Intake not found")
    return {"raw_text": (doc.get("detected_data") or {}).get("raw_text", "")}


# ── Review ─────────────────────────────────────────────────────────

@router.put("/ocr-invoice/{intake_id}/review")
async def review_intake(intake_id: str, data: ReviewData, user: dict = Depends(get_current_user)):
    doc = await db.ocr_invoice_intake.find_one({"id": intake_id, "org_id": user["org_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Intake not found")
    if doc["status"] in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="Already finalized")

    now = datetime.now(timezone.utc).isoformat()
    reviewed = {k: v for k, v in data.model_dump().items() if v is not None}
    await db.ocr_invoice_intake.update_one({"id": intake_id}, {"$set": {
        "reviewed_data": reviewed,
        "status": "reviewed",
        "reviewed_by": user["id"],
        "reviewed_at": now,
        "updated_at": now,
    }})
    return await db.ocr_invoice_intake.find_one({"id": intake_id}, {"_id": 0})


# ── Approve ────────────────────────────────────────────────────────

@router.put("/ocr-invoice/{intake_id}/approve")
async def approve_intake(intake_id: str, user: dict = Depends(get_current_user)):
    doc = await db.ocr_invoice_intake.find_one({"id": intake_id, "org_id": user["org_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Intake not found")
    if doc["status"] != "reviewed":
        raise HTTPException(status_code=400, detail="Must be reviewed before approval")

    now = datetime.now(timezone.utc).isoformat()
    reviewed = doc.get("reviewed_data") or doc.get("detected_data") or {}

    # Create pending expense from reviewed data
    expense = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "project_id": doc.get("project_id"),
        "submitted_by": doc.get("created_by"),
        "submitted_by_name": "",
        "submitted_at": now,
        "media_id": doc.get("media_id"),
        "media_url": "",
        "description": f"OCR: {reviewed.get('supplier_name', '')} #{reviewed.get('invoice_number', '')}",
        "amount": reviewed.get("total_amount") or 0,
        "currency": reviewed.get("currency", "BGN"),
        "status": "pending_approval",
        "approved_by": None,
        "approved_at": None,
        "rejection_reason": None,
        "expense_id": None,
        "created_at": now,
    }
    await db.pending_expenses.insert_one(expense)

    await db.ocr_invoice_intake.update_one({"id": intake_id}, {"$set": {
        "status": "approved",
        "approved_by": user["id"],
        "approved_at": now,
        "linked_expense_id": expense["id"],
        "updated_at": now,
    }})
    return await db.ocr_invoice_intake.find_one({"id": intake_id}, {"_id": 0})


# ── Reject ─────────────────────────────────────────────────────────

@router.put("/ocr-invoice/{intake_id}/reject")
async def reject_intake(intake_id: str, data: RejectBody, user: dict = Depends(get_current_user)):
    doc = await db.ocr_invoice_intake.find_one({"id": intake_id, "org_id": user["org_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Intake not found")

    now = datetime.now(timezone.utc).isoformat()
    warnings = doc.get("warnings", [])
    if data.reason:
        warnings.append(f"Отказано: {data.reason}")
    await db.ocr_invoice_intake.update_one({"id": intake_id}, {"$set": {
        "status": "rejected", "warnings": warnings, "updated_at": now,
    }})
    return await db.ocr_invoice_intake.find_one({"id": intake_id}, {"_id": 0})
