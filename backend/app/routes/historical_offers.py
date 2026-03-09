"""
Routes - Historical Offer Intelligence (BLOCK B).
Ingest, normalize, analyze historical offers for AI price base.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel
import uuid, io

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import require_m2
from app.utils.audit import log_audit

router = APIRouter(tags=["Historical Offer Intelligence"])

# ── Normalization Rules ────────────────────────────────────────────

NORMALIZATION_MAP = {
    # keyword → (activity_type, activity_subtype, preferred_unit)
    "мазилк": ("Мокри процеси", "Мазилка", "m2"),
    "шпакл": ("Довършителни", "Шпакловка", "m2"),
    "боядисв": ("Довършителни", "Боядисване", "m2"),
    "латекс": ("Довършителни", "Боядисване", "m2"),
    "боя": ("Довършителни", "Боядисване", "m2"),
    "плоч": ("Довършителни", "Облицовка", "m2"),
    "фаянс": ("Довършителни", "Облицовка", "m2"),
    "теракот": ("Довършителни", "Облицовка", "m2"),
    "облицов": ("Довършителни", "Облицовка", "m2"),
    "гипсокарт": ("Сухо строителство", "Гипсокартон", "m2"),
    "окач": ("Сухо строителство", "Окачен таван", "m2"),
    "ел.": ("Инсталации", "Електро", "pcs"),
    "електр": ("Инсталации", "Електро", "pcs"),
    "контакт": ("Инсталации", "Електро", "pcs"),
    "ключ": ("Инсталации", "Електро", "pcs"),
    "кабел": ("Инсталации", "Електро", "m"),
    "водопр": ("Инсталации", "ВиК", "pcs"),
    "канализ": ("Инсталации", "ВиК", "pcs"),
    "тръб": ("Инсталации", "ВиК", "m"),
    "сифон": ("Инсталации", "ВиК", "pcs"),
    "хидроизол": ("Изолации", "Хидроизолация", "m2"),
    "термоизол": ("Изолации", "Термоизолация", "m2"),
    "изолац": ("Изолации", "Изолация", "m2"),
    "стяжк": ("Мокри процеси", "Стяжка", "m2"),
    "замазк": ("Мокри процеси", "Замазка", "m2"),
    "ламин": ("Довършителни", "Настилка", "m2"),
    "паркет": ("Довършителни", "Настилка", "m2"),
    "настилк": ("Довършителни", "Настилка", "m2"),
    "под": ("Довършителни", "Настилка", "m2"),
    "врат": ("Довършителни", "Дограма", "pcs"),
    "прозор": ("Довършителни", "Дограма", "pcs"),
    "дограм": ("Довършителни", "Дограма", "pcs"),
    "демонт": ("Демонтаж", "Демонтаж", "m2"),
    "разруш": ("Демонтаж", "Разрушаване", "m3"),
    "кофраж": ("Груб строеж", "Кофраж", "m2"),
    "армир": ("Груб строеж", "Армировка", "kg"),
    "бетон": ("Груб строеж", "Бетон", "m3"),
    "зидар": ("Груб строеж", "Зидария", "m2"),
}

SECTION_KEYWORDS = {"раздел", "секция", "глава", "общо за", "всичко", "рекапитулация", "subtotal", "total", "забележк"}
UNIT_NORMALIZE = {"м2": "m2", "м.": "m", "м": "m", "бр": "pcs", "бр.": "pcs", "часа": "hours", "ч.": "hours",
                   "к-т": "lot", "кг": "kg", "кг.": "kg", "л": "l", "л.": "l", "м3": "m3"}


def normalize_smr(raw_text: str) -> dict:
    """Normalize a construction work description to type/subtype"""
    text_lower = raw_text.lower().strip()
    
    # Check if it's a section header (not a real price row)
    if any(kw in text_lower for kw in SECTION_KEYWORDS):
        return {"is_section": True, "activity_type": None, "activity_subtype": None, "confidence": 0}
    if len(text_lower) < 5 and not any(c.isdigit() for c in text_lower):
        return {"is_section": True, "activity_type": None, "activity_subtype": None, "confidence": 0}
    
    for keyword, (atype, asubtype, _) in NORMALIZATION_MAP.items():
        if keyword in text_lower:
            return {"is_section": False, "activity_type": atype, "activity_subtype": asubtype, "confidence": 0.85}
    
    return {"is_section": False, "activity_type": "Общо", "activity_subtype": "СМР", "confidence": 0.3}


def normalize_unit(raw_unit: str) -> str:
    if not raw_unit:
        return "pcs"
    return UNIT_NORMALIZE.get(raw_unit.lower().strip(), raw_unit.lower().strip())


# ── Historical Import ──────────────────────────────────────────────

@router.post("/historical/import-preview")
async def historical_import_preview(file: UploadFile = File(...), user: dict = Depends(require_m2)):
    """Parse historical offer XLSX and return preview with normalization"""
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Само .xlsx файлове")
    
    import openpyxl
    content = await file.read()
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise HTTPException(status_code=400, detail="Празен файл")
    
    # Find header
    known = {"описание", "вид", "смр", "мярка", "количество", "цена", "материал", "труд", "общо", "стойност"}
    header_row = None
    header_idx = 0
    for i, row in enumerate(rows[:10]):
        row_lower = [str(c).lower().strip() if c else "" for c in row]
        if sum(1 for h in row_lower if any(k in h for k in known)) >= 2:
            header_row = row
            header_idx = i
            break
    if not header_row:
        header_row = rows[0]
        header_idx = 0
    
    # Map columns
    col_map = {}
    for ci, cell in enumerate(header_row):
        h = str(cell).lower().strip() if cell else ""
        if any(k in h for k in ["описание", "вид смр", "наименование", "дейност", "позиция"]):
            col_map["description"] = ci
        elif any(k in h for k in ["мярка", "ед.", "unit"]):
            col_map["unit"] = ci
        elif any(k in h for k in ["количество", "к-во", "qty"]):
            col_map["qty"] = ci
        elif any(k in h for k in ["цена материал", "мат."]):
            col_map["material"] = ci
        elif any(k in h for k in ["цена труд", "труд"]):
            col_map["labor"] = ci
        elif any(k in h for k in ["обща цена", "общо", "стойност", "total"]):
            col_map["total"] = ci
    
    def sf(val):
        try: return float(val) if val else 0
        except: return 0
    
    lines = []
    warnings = []
    skipped_sections = 0
    
    for ri, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        if not row or all(c is None or str(c).strip() == "" for c in row):
            continue
        
        desc = str(row[col_map["description"]]).strip() if "description" in col_map and col_map["description"] < len(row) and row[col_map["description"]] else ""
        if not desc:
            continue
        
        norm = normalize_smr(desc)
        if norm["is_section"]:
            skipped_sections += 1
            continue
        
        unit_raw = str(row[col_map["unit"]]).strip() if "unit" in col_map and col_map["unit"] < len(row) and row[col_map["unit"]] else ""
        unit = normalize_unit(unit_raw)
        qty = sf(row[col_map["qty"]] if "qty" in col_map and col_map["qty"] < len(row) else 0)
        mat = sf(row[col_map["material"]] if "material" in col_map and col_map["material"] < len(row) else 0)
        lab = sf(row[col_map["labor"]] if "labor" in col_map and col_map["labor"] < len(row) else 0)
        total = sf(row[col_map["total"]] if "total" in col_map and col_map["total"] < len(row) else 0)
        
        if total > 0 and mat == 0 and lab == 0 and qty > 0:
            ppu = total / qty
            mat = round(ppu * 0.4, 2)
            lab = round(ppu * 0.6, 2)
        
        mat_per_unit = round(mat / qty, 2) if qty > 0 and mat > 0 else mat
        lab_per_unit = round(lab / qty, 2) if qty > 0 and lab > 0 else lab
        total_per_unit = round(mat_per_unit + lab_per_unit, 2)
        
        if qty == 0 and total == 0:
            warnings.append(f"Ред {ri}: без количество и цена за '{desc[:40]}'")
            continue
        
        lines.append({
            "row_number": ri,
            "raw_smr_text": desc,
            "normalized_activity_type": norm["activity_type"],
            "normalized_activity_subtype": norm["activity_subtype"],
            "normalization_confidence": norm["confidence"],
            "unit": unit,
            "qty": qty,
            "material_price_per_unit": mat_per_unit,
            "labor_price_per_unit": lab_per_unit,
            "total_price_per_unit": total_per_unit,
        })
    
    return {
        "file_name": file.filename,
        "total_rows": len(rows),
        "parsed_lines": len(lines),
        "skipped_sections": skipped_sections,
        "warnings": warnings,
        "lines": lines,
    }


@router.post("/historical/import-confirm", status_code=201)
async def historical_import_confirm(data: dict, user: dict = Depends(require_m2)):
    """Confirm and save historical offer data"""
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    
    lines = data.get("lines", [])
    if not lines:
        raise HTTPException(status_code=400, detail="No lines")
    
    now = datetime.now(timezone.utc).isoformat()
    batch_id = str(uuid.uuid4())
    source_file = data.get("file_name", "")
    source_project = data.get("source_project_name", "")
    source_date = data.get("source_date", "")
    city = data.get("city", "")
    
    saved = 0
    for line in lines:
        if not line.get("raw_smr_text"):
            continue
        record = {
            "id": str(uuid.uuid4()),
            "org_id": user["org_id"],
            "import_batch_id": batch_id,
            "source_file_name": source_file,
            "source_offer_name": data.get("source_offer_name", ""),
            "source_project_name": source_project,
            "source_date": source_date,
            "year": source_date[:4] if source_date and len(source_date) >= 4 else "",
            "city": city,
            "raw_smr_text": line["raw_smr_text"],
            "normalized_activity_type": line.get("normalized_activity_type", "Общо"),
            "normalized_activity_subtype": line.get("normalized_activity_subtype", "СМР"),
            "normalization_confidence": line.get("normalization_confidence", 0),
            "unit": line.get("unit", "pcs"),
            "qty": float(line.get("qty", 0)),
            "material_price_per_unit": float(line.get("material_price_per_unit", 0)),
            "labor_price_per_unit": float(line.get("labor_price_per_unit", 0)),
            "total_price_per_unit": float(line.get("total_price_per_unit", 0)),
            "notes": line.get("notes", ""),
            "created_at": now,
            "imported_by": user["id"],
        }
        await db.historical_offer_rows.insert_one(record)
        saved += 1
    
    # Save batch metadata
    await db.historical_import_batches.insert_one({
        "id": batch_id, "org_id": user["org_id"],
        "file_name": source_file, "source_project_name": source_project,
        "source_date": source_date, "city": city,
        "rows_imported": saved, "created_at": now, "imported_by": user["id"],
    })
    
    return {"ok": True, "batch_id": batch_id, "rows_imported": saved}


# ── Historical Analytics ───────────────────────────────────────────

@router.get("/historical/analytics")
async def get_historical_analytics(
    city: Optional[str] = None,
    activity_type: Optional[str] = None,
    user: dict = Depends(require_m2),
):
    """Get historical price analytics by category"""
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    
    match = {"org_id": user["org_id"], "total_price_per_unit": {"$gt": 0}}
    if city:
        match["city"] = city
    if activity_type:
        match["normalized_activity_type"] = activity_type
    
    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": {
                "type": "$normalized_activity_type",
                "subtype": "$normalized_activity_subtype",
                "unit": "$unit",
            },
            "sample_count": {"$sum": 1},
            "avg_material": {"$avg": "$material_price_per_unit"},
            "avg_labor": {"$avg": "$labor_price_per_unit"},
            "avg_total": {"$avg": "$total_price_per_unit"},
            "min_total": {"$min": "$total_price_per_unit"},
            "max_total": {"$max": "$total_price_per_unit"},
            "all_totals": {"$push": "$total_price_per_unit"},
            "all_materials": {"$push": "$material_price_per_unit"},
            "all_labors": {"$push": "$labor_price_per_unit"},
        }},
        {"$sort": {"sample_count": -1}},
    ]
    
    results = await db.historical_offer_rows.aggregate(pipeline).to_list(200)
    
    categories = []
    for r in results:
        # Compute medians
        totals = sorted([t for t in r.get("all_totals", []) if t > 0])
        mats = sorted([m for m in r.get("all_materials", []) if m > 0])
        labs = sorted([l for l in r.get("all_labors", []) if l > 0])
        
        median_total = totals[len(totals)//2] if totals else 0
        median_mat = mats[len(mats)//2] if mats else 0
        median_lab = labs[len(labs)//2] if labs else 0
        
        categories.append({
            "activity_type": r["_id"]["type"],
            "activity_subtype": r["_id"]["subtype"],
            "unit": r["_id"]["unit"],
            "sample_count": r["sample_count"],
            "avg_material": round(r["avg_material"] or 0, 2),
            "avg_labor": round(r["avg_labor"] or 0, 2),
            "avg_total": round(r["avg_total"] or 0, 2),
            "median_material": round(median_mat, 2),
            "median_labor": round(median_lab, 2),
            "median_total": round(median_total, 2),
            "min_total": round(r["min_total"] or 0, 2),
            "max_total": round(r["max_total"] or 0, 2),
        })
    
    total_rows = await db.historical_offer_rows.count_documents({"org_id": user["org_id"]})
    batches = await db.historical_import_batches.find(
        {"org_id": user["org_id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(50)
    
    unique_types = await db.historical_offer_rows.distinct("normalized_activity_type", {"org_id": user["org_id"]})
    unique_cities = await db.historical_offer_rows.distinct("city", {"org_id": user["org_id"]})
    
    return {
        "total_rows": total_rows,
        "total_batches": len(batches),
        "categories": categories,
        "batches": batches,
        "unique_types": [t for t in unique_types if t],
        "unique_cities": [c for c in unique_cities if c],
    }


# ── Internal Price Lookup (for AI merge) ───────────────────────────

async def get_internal_price_hint(org_id: str, activity_type: str, activity_subtype: str, unit: str = None, city: str = None) -> dict:
    """Lookup historical internal price for AI merge"""
    match = {
        "org_id": org_id,
        "normalized_activity_type": activity_type,
        "normalized_activity_subtype": activity_subtype,
        "total_price_per_unit": {"$gt": 0},
    }
    if city:
        match["city"] = city
    if unit:
        match["unit"] = unit
    
    rows = await db.historical_offer_rows.find(match, {"_id": 0, "material_price_per_unit": 1, "labor_price_per_unit": 1, "total_price_per_unit": 1}).to_list(200)
    
    if not rows:
        # Try without city
        if city:
            del match["city"]
            rows = await db.historical_offer_rows.find(match, {"_id": 0, "material_price_per_unit": 1, "labor_price_per_unit": 1, "total_price_per_unit": 1}).to_list(200)
    
    if not rows:
        return {"available": False, "sample_count": 0}
    
    totals = sorted([r["total_price_per_unit"] for r in rows if r["total_price_per_unit"] > 0])
    mats = sorted([r["material_price_per_unit"] for r in rows if r.get("material_price_per_unit", 0) > 0])
    labs = sorted([r["labor_price_per_unit"] for r in rows if r.get("labor_price_per_unit", 0) > 0])
    
    return {
        "available": True,
        "sample_count": len(totals),
        "median_total": round(totals[len(totals)//2], 2) if totals else 0,
        "median_material": round(mats[len(mats)//2], 2) if mats else 0,
        "median_labor": round(labs[len(labs)//2], 2) if labs else 0,
        "min_total": round(min(totals), 2) if totals else 0,
        "max_total": round(max(totals), 2) if totals else 0,
        "range_label": f"{round(min(totals), 2)}-{round(max(totals), 2)}" if totals else "",
    }
