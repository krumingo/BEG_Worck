"""
Routes - Excel Import V2 (preview, templates, smart detection).
Additive layer — does NOT replace old import endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel

from app.db import db
from app.deps.auth import get_current_user
from app.services.excel_import_v2 import (
    detect_excel_structure, normalize_with_mapping,
    save_import_template, apply_template,
)

router = APIRouter(tags=["Excel Import V2"])


class TemplateCreate(BaseModel):
    name: str
    import_type: str = "kss"
    column_mapping: dict
    sheet_name_default: Optional[str] = None
    detected_headers: Optional[dict] = None
    notes: Optional[str] = None


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    column_mapping: Optional[dict] = None
    sheet_name_default: Optional[str] = None
    notes: Optional[str] = None


# ── Preview ────────────────────────────────────────────────────────

@router.post("/excel-import/preview")
async def preview_excel(
    file: UploadFile = File(...),
    import_type: str = Form("kss"),
    sheet_name: str = Form(None),
    user: dict = Depends(get_current_user),
):
    content = await file.read()
    result = detect_excel_structure(content, sheet_name)
    return result


@router.post("/excel-import/preview-with-template")
async def preview_with_template(
    file: UploadFile = File(...),
    template_id: str = Form(...),
    sheet_name: str = Form(None),
    user: dict = Depends(get_current_user),
):
    content = await file.read()
    result = await apply_template(user["org_id"], template_id, content)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ── Templates CRUD ─────────────────────────────────────────────────

@router.post("/excel-import/templates", status_code=201)
async def create_template(data: TemplateCreate, user: dict = Depends(get_current_user)):
    return await save_import_template(
        user["org_id"], data.name, data.import_type, data.column_mapping,
        user["id"], sheet_name_default=data.sheet_name_default,
        detected_headers=data.detected_headers, notes=data.notes,
    )


@router.get("/excel-import/templates")
async def list_templates(import_type: Optional[str] = None, user: dict = Depends(get_current_user)):
    query = {"org_id": user["org_id"]}
    if import_type:
        query["import_type"] = import_type
    items = await db.excel_import_templates.find(query, {"_id": 0}).sort("created_at", -1).to_list(50)
    return {"items": items, "total": len(items)}


@router.get("/excel-import/templates/{template_id}")
async def get_template(template_id: str, user: dict = Depends(get_current_user)):
    doc = await db.excel_import_templates.find_one({"id": template_id, "org_id": user["org_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Template not found")
    return doc


@router.put("/excel-import/templates/{template_id}")
async def update_template(template_id: str, data: TemplateUpdate, user: dict = Depends(get_current_user)):
    doc = await db.excel_import_templates.find_one({"id": template_id, "org_id": user["org_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Template not found")
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.excel_import_templates.update_one({"id": template_id}, {"$set": update})
    return await db.excel_import_templates.find_one({"id": template_id}, {"_id": 0})


@router.delete("/excel-import/templates/{template_id}")
async def delete_template(template_id: str, user: dict = Depends(get_current_user)):
    await db.excel_import_templates.delete_one({"id": template_id, "org_id": user["org_id"]})
    return {"ok": True}


# ── Commit Bridge ──────────────────────────────────────────────────

@router.post("/excel-import/commit")
async def commit_import(
    file: UploadFile = File(...),
    project_id: str = Form(...),
    import_type: str = Form("kss"),
    template_id: str = Form(None),
    sheet_name: str = Form(None),
    name: str = Form(""),
    user: dict = Depends(get_current_user),
):
    """Bridge: v2 preview/mapping → old import engine."""
    content = await file.read()

    # Get mapping from template or auto-detect
    mapping = None
    if template_id:
        tpl = await db.excel_import_templates.find_one(
            {"id": template_id, "org_id": user["org_id"]}, {"_id": 0}
        )
        if tpl:
            mapping = tpl.get("column_mapping")
            if not sheet_name:
                sheet_name = tpl.get("sheet_name_default")

    # Use existing import engine
    from app.services.excel_import import import_kss_from_excel
    from app.routes.smr_analysis import calc_line, calc_totals
    import uuid as _uuid
    from datetime import datetime as _dt, timezone as _tz

    project = await db.projects.find_one({"id": project_id, "org_id": user["org_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    result = await import_kss_from_excel(
        content, user["org_id"], project_id, user["id"],
        project.get("name", ""), column_mapping=mapping, sheet_name=sheet_name,
    )

    if not result["lines"]:
        raise HTTPException(status_code=400, detail="No valid lines found")

    for ln in result["lines"]:
        calc_line(ln)

    now = _dt.now(_tz.utc).isoformat()
    last = await db.smr_analyses.find_one(
        {"org_id": user["org_id"], "project_id": project_id},
        {"_id": 0, "version": 1}, sort=[("version", -1)],
    )
    version = (last["version"] + 1) if last else 1

    analysis = {
        "id": str(_uuid.uuid4()),
        "org_id": user["org_id"],
        "project_id": project_id,
        "project_name": project.get("name", ""),
        "name": name or f"КСС Import V2 - {file.filename}",
        "version": version,
        "status": "draft",
        "analysis_type": "kss",
        "is_kss": True,
        "imported_from": "excel",
        "import_filename": file.filename,
        "lines": result["lines"],
        "totals": calc_totals(result["lines"]),
        "created_from": None,
        "created_from_type": None,
        "created_at": now,
        "updated_at": now,
        "created_by": user["id"],
        "approved_by": None,
        "approved_at": None,
    }
    await db.smr_analyses.insert_one(analysis)

    return {
        "analysis_id": analysis["id"],
        "lines_imported": result["lines_count"],
        "skipped": result["skipped_count"],
        "warnings": result["warnings"],
        "detected_columns": result.get("detected_columns", {}),
    }
