"""
Service - OCR Invoice extraction (v1 rule-based).
Extracts structured fields from raw text using pattern matching.
"""
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from app.db import db


# ── Text extraction (v1: read uploaded file as text) ────────────────

async def extract_invoice_text(media_id: str = None, file_path: str = None) -> dict:
    """Extract raw text from an uploaded file. V1: basic text extraction."""
    raw_text = ""
    confidence = 0.0
    warnings = []

    # Try to read file content
    target_path = None
    if file_path:
        target_path = file_path
    elif media_id:
        media = await db.media_files.find_one({"id": media_id}, {"_id": 0, "stored_filename": 1})
        if media:
            target_path = f"/app/backend/uploads/{media['stored_filename']}"

    if target_path and Path(target_path).exists():
        try:
            # For text-based files
            content = Path(target_path).read_bytes()
            # Try UTF-8 decode
            try:
                raw_text = content.decode("utf-8")
                confidence = 0.6
            except UnicodeDecodeError:
                try:
                    raw_text = content.decode("cp1251")
                    confidence = 0.5
                except Exception:
                    raw_text = str(content[:2000])
                    confidence = 0.2
                    warnings.append("Файлът не може да бъде прочетен като текст")
        except Exception as e:
            warnings.append(f"Грешка при четене: {str(e)[:100]}")
            confidence = 0.1
    else:
        warnings.append("Файлът не е намерен")
        confidence = 0.0

    if not raw_text:
        warnings.append("Не е извлечен текст от файла. Моля въведете данните ръчно.")
        confidence = 0.0

    return {"raw_text": raw_text, "confidence": confidence, "warnings": warnings}


# ── Field parsing from raw text ─────────────────────────────────────

def parse_invoice_fields(raw_text: str) -> dict:
    """Parse structured fields from raw invoice text using regex patterns."""
    text = raw_text or ""
    fields = {
        "supplier_name": None, "invoice_number": None, "invoice_date": None,
        "due_date": None, "currency": "BGN", "total_amount": None,
        "vat_amount": None, "subtotal_amount": None, "items": [],
    }

    # Invoice number patterns
    for pattern in [
        r"(?:фактура|invoice|факт\.?)\s*(?:№|#|No\.?|номер)\s*[:.]?\s*([A-Z0-9/-]+\d+)",
        r"(?:№|#)\s*([A-Z0-9/-]+\d{4,})",
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            fields["invoice_number"] = m.group(1).strip()
            break

    # Date patterns (DD.MM.YYYY or DD/MM/YYYY)
    dates = re.findall(r"(\d{1,2}[./]\d{1,2}[./]\d{2,4})", text)
    if dates:
        fields["invoice_date"] = dates[0]
        if len(dates) > 1:
            fields["due_date"] = dates[-1]

    # Amount patterns
    for pattern in [
        r"(?:общо|total|сума|amount|всичко)\s*[:.]?\s*(\d[\d\s.,]+)\s*(?:лв|bgn|eur|€)?",
        r"(\d[\d\s.,]+)\s*(?:лв|bgn)\s*(?:с\s*ддс|incl)",
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            val = m.group(1).replace(" ", "").replace(",", ".")
            try:
                fields["total_amount"] = float(val)
            except ValueError:
                pass
            break

    # VAT
    m = re.search(r"(?:ддс|vat|дд[сc])\s*[:.]?\s*(\d[\d\s.,]+)", text, re.IGNORECASE)
    if m:
        val = m.group(1).replace(" ", "").replace(",", ".")
        try:
            fields["vat_amount"] = float(val)
        except ValueError:
            pass

    # Subtotal
    m = re.search(r"(?:без\s*ддс|subtotal|данъчна\s*основа)\s*[:.]?\s*(\d[\d\s.,]+)", text, re.IGNORECASE)
    if m:
        val = m.group(1).replace(" ", "").replace(",", ".")
        try:
            fields["subtotal_amount"] = float(val)
        except ValueError:
            pass

    # Supplier name (first line that looks like a company name)
    for line in text.split("\n")[:10]:
        line = line.strip()
        if len(line) > 5 and any(k in line.upper() for k in ["ЕООД", "ООД", "ЕТ", "АД", "LTD", "SRL", "GMBH"]):
            fields["supplier_name"] = line[:100]
            break

    # Currency
    if "eur" in text.lower() or "€" in text:
        fields["currency"] = "EUR"

    return fields


# ── Intake management ────────────────────────────────────────────────

async def create_ocr_intake(org_id: str, media_id: str, created_by: str,
                             project_id: str = None, supplier_id: str = None,
                             source_type: str = "upload", file_name: str = "") -> dict:
    """Create intake record and run extraction."""
    now = datetime.now(timezone.utc).isoformat()

    # Extract text
    extraction = await extract_invoice_text(media_id=media_id)
    raw_text = extraction["raw_text"]
    confidence = extraction["confidence"]
    warnings = extraction["warnings"]

    # Parse fields
    detected = parse_invoice_fields(raw_text)
    detected["raw_text"] = raw_text[:5000]

    doc = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "project_id": project_id,
        "supplier_id": supplier_id,
        "media_id": media_id,
        "source_type": source_type,
        "status": "processed" if confidence > 0 else "uploaded",
        "file_name": file_name,
        "detected_data": detected,
        "reviewed_data": None,
        "confidence_score": confidence,
        "warnings": warnings,
        "reviewed_by": None,
        "reviewed_at": None,
        "approved_by": None,
        "approved_at": None,
        "linked_expense_id": None,
        "linked_supplier_invoice_id": None,
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
    }
    await db.ocr_invoice_intake.insert_one(doc)
    return {k: v for k, v in doc.items() if k != "_id"}
