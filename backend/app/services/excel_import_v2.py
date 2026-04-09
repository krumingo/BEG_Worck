"""
Service - Excel Import V2 (preview, templates, smart detection).
Additive layer on top of existing excel_import.py.
"""
import io
import uuid
from datetime import datetime, timezone
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from app.db import db
from app.services.excel_import import COLUMN_KEYWORDS, parse_float


def _match_header(val: str) -> str:
    """Match a header cell value to a known field."""
    v = val.lower().strip()
    for field, keywords in COLUMN_KEYWORDS.items():
        for kw in keywords:
            if kw in v:
                return field
    return ""


def detect_excel_structure(file_bytes: bytes, sheet_name: str = None) -> dict:
    """Detect structure without importing."""
    wb = load_workbook(io.BytesIO(file_bytes), data_only=True)
    sheet_names = wb.sheetnames
    ws = wb[sheet_name] if sheet_name and sheet_name in sheet_names else wb.active

    # Find header row
    best_row = 1
    best_score = 0
    for row_num in range(1, 8):
        score = 0
        for row in ws.iter_rows(min_row=row_num, max_row=row_num, values_only=True):
            for val in row:
                if val and _match_header(str(val)):
                    score += 1
        if score > best_score:
            best_score = score
            best_row = row_num

    # Detect columns from header
    detected = {}
    headers_raw = {}
    for row in ws.iter_rows(min_row=best_row, max_row=best_row, values_only=False):
        for cell in row:
            v = str(cell.value or "").strip()
            if not v:
                continue
            col = get_column_letter(cell.column)
            headers_raw[col] = v
            field = _match_header(v)
            if field and field not in detected:
                detected[field] = col

    # Confidence
    expected = {"smr_type", "qty", "unit"}
    found = set(detected.keys())
    confidence = round(len(found & expected) / max(len(expected), 1), 2)
    if "smr_type" in found:
        confidence = max(confidence, 0.5)
    if "total_price" in found or "labor_price" in found:
        confidence = min(confidence + 0.2, 1.0)

    # Preview rows
    data_start = best_row + 1
    preview = []
    warnings = []
    total_rows = 0

    for row in ws.iter_rows(min_row=data_start, values_only=True):
        if all(v is None for v in row):
            continue
        total_rows += 1
        if len(preview) < 10:
            row_dict = {}
            for field, col in detected.items():
                idx = ord(col.upper()) - ord('A')
                row_dict[field] = row[idx] if idx < len(row) else None
            # Also include raw positional
            row_dict["_raw"] = [str(v) if v is not None else "" for v in row[:8]]
            preview.append(row_dict)

    if "smr_type" not in detected:
        warnings.append("Не е намерена колона за описание/дейност")
    if "qty" not in detected:
        warnings.append("Не е намерена колона за количество")

    return {
        "sheet_names": sheet_names,
        "selected_sheet": ws.title,
        "header_row_guess": best_row,
        "detected_columns": detected,
        "headers_raw": headers_raw,
        "preview_rows": preview,
        "total_rows": total_rows,
        "warnings": warnings,
        "confidence": confidence,
    }


def normalize_with_mapping(file_bytes: bytes, column_mapping: dict, sheet_name: str = None) -> dict:
    """Normalize rows using explicit column mapping."""
    wb = load_workbook(io.BytesIO(file_bytes), data_only=True)
    ws = wb[sheet_name] if sheet_name and sheet_name in wb.sheetnames else wb.active

    # Find header row (skip it)
    best_row = 1
    for row_num in range(1, 8):
        score = 0
        for row in ws.iter_rows(min_row=row_num, max_row=row_num, values_only=True):
            for val in row:
                if val and _match_header(str(val)):
                    score += 1
        if score >= 2:
            best_row = row_num
            break

    data_start = best_row + 1
    rows = []
    warnings = []
    skipped = 0

    def _get(row_vals, field):
        col = column_mapping.get(field, "")
        if not col:
            return None
        idx = ord(col.upper()) - ord('A')
        return row_vals[idx] if idx < len(row_vals) else None

    for row in ws.iter_rows(min_row=data_start, values_only=True):
        if all(v is None for v in row):
            skipped += 1
            continue
        smr = _get(row, "smr_type")
        if not smr:
            skipped += 1
            continue
        rows.append({
            "smr_type": str(smr).strip(),
            "unit": str(_get(row, "unit") or "m2").strip(),
            "qty": parse_float(_get(row, "qty")),
            "material_price": parse_float(_get(row, "material_price")),
            "labor_price": parse_float(_get(row, "labor_price")),
            "total_price": parse_float(_get(row, "total_price")),
        })

    return {"rows": rows, "warnings": warnings, "skipped": skipped, "total": len(rows)}


async def save_import_template(org_id: str, name: str, import_type: str, column_mapping: dict, created_by: str, **kwargs) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "name": name,
        "import_type": import_type,
        "column_mapping": column_mapping,
        "sheet_name_default": kwargs.get("sheet_name_default"),
        "detected_headers": kwargs.get("detected_headers"),
        "notes": kwargs.get("notes"),
        "is_default": False,
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
    }
    await db.excel_import_templates.insert_one(doc)
    return {k: v for k, v in doc.items() if k != "_id"}


async def apply_template(org_id: str, template_id: str, file_bytes: bytes) -> dict:
    tpl = await db.excel_import_templates.find_one({"id": template_id, "org_id": org_id}, {"_id": 0})
    if not tpl:
        return {"error": "Template not found"}
    mapping = tpl.get("column_mapping", {})
    sheet = tpl.get("sheet_name_default")
    result = normalize_with_mapping(file_bytes, mapping, sheet)
    return {"template": tpl, **result}
