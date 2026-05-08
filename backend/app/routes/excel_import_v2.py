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


# ═══════════════════════════════════════════════════════════════════
# CONSTRUCTION BUDGET IMPORT (Фаза 2.2)
# ═══════════════════════════════════════════════════════════════════

@router.post("/excel-import/preview-budget")
async def preview_budget(
    file: UploadFile = File(...),
    sheet_name: str = Form(None),
    user: dict = Depends(get_current_user),
):
    """Preview a construction budget Excel template with man-hours formula."""
    from app.services.excel_import_v2 import parse_construction_budget
    content = await file.read()
    result = parse_construction_budget(content, sheet_name)
    # Add preview summary
    total_hours = round(sum(ln["planned_man_hours"] for ln in result["lines"]), 1)
    total_labor = round(sum(ln["labor_total"] for ln in result["lines"]), 2)
    total_materials = round(sum(ln["materials_total"] for ln in result["lines"]), 2)
    result["preview_summary"] = {
        "total_lines": result["lines_count"],
        "total_man_hours": total_hours,
        "total_labor_budget": total_labor,
        "total_materials_budget": total_materials,
        "mode_a_count": sum(1 for ln in result["lines"] if ln["import_mode"] == "A"),
        "mode_b_count": sum(1 for ln in result["lines"] if ln["import_mode"] == "B"),
    }
    # Limit preview to first 15 lines
    result["preview_rows"] = result["lines"][:15]
    return result


@router.post("/excel-import/commit-budget")
async def commit_budget_import(
    file: UploadFile = File(...),
    project_id: str = Form(...),
    sheet_name: str = Form(None),
    user: dict = Depends(get_current_user),
):
    """Import construction budget → creates activity_budgets with snapshot fields."""
    from app.services.excel_import_v2 import parse_construction_budget
    from app.routes.activity_budgets import compute_avg_daily_wage

    content = await file.read()
    org_id = user["org_id"]

    project = await db.projects.find_one({"id": project_id, "org_id": org_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    result = parse_construction_budget(content, sheet_name)
    if not result["lines"]:
        raise HTTPException(status_code=400, detail="No valid lines found")

    # Compute project avg_daily_wage for Mode B lines without wage
    project_wage = await compute_avg_daily_wage(org_id, project_id)

    now = datetime.now(timezone.utc).isoformat()
    import uuid as _uuid
    created = 0
    updated = 0

    for ln in result["lines"]:
        # Fill missing avg_daily_wage from project team
        avg_wage = ln["avg_daily_wage"] or project_wage
        hours_per_day = ln["hours_per_day"] or 8
        coefficient = ln["coefficient"] or 2

        # Recompute if Mode B and wage was missing
        if ln["import_mode"] == "B" and ln["avg_daily_wage"] is None and avg_wage > 0:
            akord = round(ln["labor_total"] / coefficient, 2) if coefficient > 0 else 0
            man_days = round(akord / avg_wage, 2) if avg_wage > 0 else 0
            man_hours = round(man_days * hours_per_day, 2)
        else:
            akord = ln["akord"]
            man_days = ln["planned_man_days"]
            man_hours = ln["planned_man_hours"]

        budget_type = ln["category"] or ln["activity_name"]
        budget_subtype = ln["activity_name"] if ln["category"] else ""

        # Upsert by type + subtype
        existing = await db.activity_budgets.find_one({
            "org_id": org_id, "project_id": project_id,
            "type": budget_type, "subtype": budget_subtype,
        })

        doc = {
            "labor_budget": ln["labor_total"],
            "materials_budget": ln["materials_total"],
            "coefficient": coefficient,
            "planned_man_hours": man_hours,
            "planned_man_days": man_days,
            "akord": akord,
            "avg_daily_wage_at_calc": avg_wage,
            "hours_per_day_at_calc": hours_per_day,
            "coefficient_at_calc": coefficient,
            "currency_at_calc": "EUR",
            "snapshot_calculated_at": now,
            "updated_at": now,
        }

        if existing:
            await db.activity_budgets.update_one({"id": existing["id"]}, {"$set": doc})
            updated += 1
        else:
            doc.update({
                "id": str(_uuid.uuid4()),
                "org_id": org_id,
                "project_id": project_id,
                "type": budget_type,
                "subtype": budget_subtype,
                "notes": f"Import: {ln['activity_name']} ({ln['unit']})",
                "planned_people_per_day": None,
                "planned_target_days": None,
                "created_at": now,
            })
            await db.activity_budgets.insert_one(doc)
            created += 1

    return {
        "ok": True,
        "created": created,
        "updated": updated,
        "total_lines": result["lines_count"],
        "warnings": result["warnings"],
        "avg_daily_wage_used": project_wage,
    }
