"""
Routes - Technician Mobile View.
Aggregates data from existing modules for mobile-first daily reporting.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from typing import Optional, List
from datetime import datetime, timezone
from pydantic import BaseModel
import uuid

from app.db import db
from app.deps.auth import get_current_user

router = APIRouter(tags=["Technician"])


# ── Models ─────────────────────────────────────────────────────────

class DailyReportEntry(BaseModel):
    worker_id: Optional[str] = None
    worker_name: Optional[str] = None
    smr_type: str
    smr_subtype: Optional[str] = None
    hours: float
    notes: Optional[str] = None
    location_id: Optional[str] = None


class DailyReportSubmit(BaseModel):
    project_id: str
    date: Optional[str] = None
    entries: List[DailyReportEntry]
    general_notes: Optional[str] = None
    photos: List[str] = []


class QuickSMR(BaseModel):
    project_id: str
    smr_type: str
    description: Optional[str] = None
    qty: float = 1
    unit: str = "m2"
    location_id: Optional[str] = None
    photos: List[str] = []


class MaterialRequestItem(BaseModel):
    item_name: str
    qty: float
    unit: str = "бр"
    notes: Optional[str] = None


class MaterialRequestSubmit(BaseModel):
    project_id: str
    items: List[MaterialRequestItem]
    urgent: bool = False


class EquipmentRequest(BaseModel):
    project_id: str
    item_id: Optional[str] = None
    item_description: Optional[str] = None
    needed_from: str
    needed_to: Optional[str] = None
    notes: Optional[str] = None


# ── Helper: snapshot hourly rate ───────────────────────────────────

async def _get_hourly_rate(org_id: str, worker_id: str) -> float:
    profile = await db.employee_profiles.find_one(
        {"org_id": org_id, "user_id": worker_id}, {"_id": 0}
    )
    if not profile:
        return 0
    pay = (profile.get("pay_type") or "Monthly").strip()
    if pay == "Hourly":
        return float(profile.get("hourly_rate") or 0)
    elif pay == "Daily":
        return round(float(profile.get("daily_rate") or profile.get("base_salary") or 0) / 8, 2)
    else:
        ms = float(profile.get("monthly_salary") or profile.get("base_salary") or 0)
        days = int(profile.get("working_days_per_month") or 22)
        hours = int(profile.get("standard_hours_per_day") or 8)
        return round(ms / max(days * hours, 1), 2)


# ── My Sites ───────────────────────────────────────────────────────

@router.get("/technician/my-sites")
async def my_sites(user: dict = Depends(get_current_user)):
    org_id = user["org_id"]
    uid = user["id"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Get assigned projects
    if user["role"] in ["Admin", "Owner", "SiteManager"]:
        projects = await db.projects.find(
            {"org_id": org_id, "status": {"$in": ["Active", "Draft"]}},
            {"_id": 0, "id": 1, "name": 1, "code": 1, "address_text": 1, "owner_id": 1},
        ).to_list(50)
    else:
        memberships = await db.project_team.find(
            {"user_id": uid, "active": True}, {"_id": 0, "project_id": 1}
        ).to_list(50)
        pids = [m["project_id"] for m in memberships]
        projects = await db.projects.find(
            {"org_id": org_id, "id": {"$in": pids}},
            {"_id": 0, "id": 1, "name": 1, "code": 1, "address_text": 1},
        ).to_list(50)

    result = []
    for p in projects:
        pid = p["id"]

        # Today sessions
        sessions = await db.work_sessions.find(
            {"org_id": org_id, "site_id": pid, "started_at": {"$gte": f"{today}T00:00:00", "$lte": f"{today}T23:59:59"}},
            {"_id": 0, "worker_name": 1, "duration_hours": 1, "smr_type_id": 1},
        ).to_list(100)
        today_sessions = [{"worker_name": s.get("worker_name", ""), "hours": round(s.get("duration_hours") or 0, 1), "smr_type": s.get("smr_type_id", "")} for s in sessions]

        # Pending material requests
        pending_reqs = await db.material_requests.count_documents(
            {"org_id": org_id, "project_id": pid, "status": {"$in": ["draft", "submitted"]}}
        )

        # Has report today
        report = await db.employee_daily_reports.find_one(
            {"org_id": org_id, "project_id": pid, "date": today}
        )
        if not report:
            report = await db.work_reports.find_one(
                {"org_id": org_id, "project_id": pid, "date": today}
            )

        result.append({
            "project_id": pid,
            "name": p.get("name", ""),
            "code": p.get("code", ""),
            "address_text": p.get("address_text", ""),
            "today_sessions": today_sessions,
            "today_hours": round(sum(s.get("duration_hours") or 0 for s in sessions), 1),
            "today_workers": len(set(s.get("worker_name") for s in sessions)),
            "pending_requests": pending_reqs,
            "has_report_today": report is not None,
        })

    return {"sites": result, "total": len(result)}


# ── Site Tasks ─────────────────────────────────────────────────────

@router.get("/technician/site/{project_id}/tasks")
async def site_tasks(project_id: str, user: dict = Depends(get_current_user)):
    org_id = user["org_id"]

    tasks = []
    seen = set()

    def _add(smr_type, smr_subtype="", unit="m2", qty=0, source=""):
        key = smr_type.strip().lower()
        if not key or key in seen:
            return
        seen.add(key)
        tasks.append({
            "smr_type": smr_type.strip(), "smr_subtype": smr_subtype,
            "unit": unit, "qty_total": qty, "qty_completed": 0,
            "status": "active", "source": source,
        })

    # 1. Activity budgets
    budgets = await db.activity_budgets.find(
        {"org_id": org_id, "project_id": project_id},
        {"_id": 0, "type": 1, "subtype": 1},
    ).to_list(100)
    for b in budgets:
        _add(b["type"], b.get("subtype", ""), source="budget")

    # 2. Offer lines
    offers = await db.offers.find(
        {"org_id": org_id, "project_id": project_id, "status": {"$in": ["Accepted", "Sent", "Draft"]}},
        {"_id": 0, "lines": 1},
    ).to_list(50)
    for o in offers:
        for ln in o.get("lines", []):
            t = ln.get("activity_type") or ln.get("activity_name", "")
            if t:
                _add(t, ln.get("activity_subtype", ""), ln.get("unit", "m2"), ln.get("qty", 0), "offer")

    # 3. SMR analysis lines
    analyses = await db.smr_analyses.find(
        {"org_id": org_id, "project_id": project_id},
        {"_id": 0, "lines": 1},
    ).to_list(50)
    for a in analyses:
        for ln in a.get("lines", []):
            if ln.get("smr_type"):
                _add(ln["smr_type"], ln.get("smr_subtype", ""), ln.get("unit", "m2"), ln.get("qty", 0), "analysis")

    # 4. Missing SMR records
    missing = await db.missing_smr.find(
        {"org_id": org_id, "project_id": project_id, "status": {"$nin": ["closed", "rejected_by_client"]}},
        {"_id": 0, "smr_type": 1, "activity_type": 1, "unit": 1, "qty": 1},
    ).to_list(100)
    for m in missing:
        t = m.get("smr_type") or m.get("activity_type", "")
        if t:
            _add(t, "", m.get("unit", "m2"), m.get("qty", 0), "missing_smr")

    # 5. Past work_sessions SMR types (previously reported)
    distinct_types = await db.work_sessions.distinct(
        "smr_type_id", {"org_id": org_id, "site_id": project_id, "smr_type_id": {"$ne": None}}
    )
    for t in distinct_types:
        if t:
            _add(t, source="history")

    return {"tasks": tasks, "total": len(tasks)}


# ── Daily Report ───────────────────────────────────────────────────

@router.post("/technician/daily-report")
async def submit_daily_report(data: DailyReportSubmit, user: dict = Depends(get_current_user)):
    org_id = user["org_id"]
    today = data.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc).isoformat()

    project = await db.projects.find_one({"id": data.project_id, "org_id": org_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    sessions_created = 0
    missing_smr_created = []

    # Get known SMR types for this project
    known_types = set()
    budgets = await db.activity_budgets.find(
        {"org_id": org_id, "project_id": data.project_id}, {"_id": 0, "type": 1}
    ).to_list(100)
    for b in budgets:
        known_types.add(b["type"].lower())
    offers = await db.offers.find(
        {"org_id": org_id, "project_id": data.project_id}, {"_id": 0, "lines": 1}
    ).to_list(50)
    for o in offers:
        for ln in o.get("lines", []):
            t = ln.get("activity_type") or ln.get("activity_name", "")
            if t:
                known_types.add(t.lower())

    for entry in data.entries:
        wid = entry.worker_id or user["id"]
        rate = await _get_hourly_rate(org_id, wid)

        # Create work session
        session = {
            "id": str(uuid.uuid4()),
            "org_id": org_id,
            "worker_id": wid,
            "worker_name": entry.worker_name or f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
            "site_id": data.project_id,
            "site_name": project.get("name", ""),
            "smr_type_id": entry.smr_type,
            "started_at": f"{today}T08:00:00",
            "ended_at": f"{today}T{8 + int(entry.hours):02d}:{int((entry.hours % 1) * 60):02d}:00",
            "source_method": "MANUAL",
            "is_flagged": False,
            "flag_reason": None,
            "duration_hours": round(entry.hours, 2),
            "is_overtime": entry.hours > 8,
            "overtime_type": "over_8h" if entry.hours > 8 else None,
            "overtime_coefficient": 1.0,
            "hourly_rate_at_date": rate,
            "labor_cost": round(entry.hours * rate, 2),
            "notes": entry.notes,
            "created_at": now,
            "updated_at": now,
        }
        await db.work_sessions.insert_one(session)
        sessions_created += 1

        # Check if SMR type is known
        if entry.smr_type.lower() not in known_types:
            ms = {
                "id": str(uuid.uuid4()),
                "org_id": org_id,
                "project_id": data.project_id,
                "project_name": project.get("name", ""),
                "smr_type": entry.smr_type,
                "activity_type": entry.smr_type,
                "activity_subtype": entry.smr_subtype or "",
                "qty": entry.hours,
                "unit": "часа",
                "source": "mobile",
                "status": "reported",
                "urgency_type": "emergency",
                "emergency_reason": "Въведено от терена",
                "notes": entry.notes,
                "created_at": now,
                "updated_at": now,
                "created_by": user["id"],
                "created_by_name": session["worker_name"],
                "attachments": [],
                "client_approval": None,
                "ai_estimated_price": None,
                "ai_price_breakdown": None,
                "offer_line_ids": [],
                "linked_extra_work_id": None,
                "linked_offer_id": None,
                "linked_change_order_id": None,
            }
            await db.missing_smr.insert_one(ms)
            missing_smr_created.append(ms["id"])

    # Create daily report record
    report = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "project_id": data.project_id,
        "user_id": user["id"],
        "date": today,
        "submitted_by": user["id"],
        "submitted_at": now,
        "entries_count": len(data.entries),
        "total_hours": round(sum(e.hours for e in data.entries), 2),
        "general_notes": data.general_notes,
        "photos": data.photos,
        "source": "technician_mobile",
        "status": "Submitted",
    }
    # Upsert to avoid duplicate key
    existing_report = await db.work_reports.find_one(
        {"org_id": org_id, "project_id": data.project_id, "user_id": user["id"], "date": today}
    )
    if existing_report:
        await db.work_reports.update_one({"id": existing_report["id"]}, {"$set": {
            "entries_count": report["entries_count"], "total_hours": report["total_hours"],
            "general_notes": report["general_notes"], "photos": report["photos"],
            "submitted_at": now, "status": "Submitted",
        }})
        report["id"] = existing_report["id"]
    else:
        await db.work_reports.insert_one(report)

    return {
        "report_id": report["id"],
        "sessions_created": sessions_created,
        "missing_smr_created": missing_smr_created,
        "total_hours": report["total_hours"],
    }


# ── Quick SMR ──────────────────────────────────────────────────────

@router.post("/technician/quick-smr", status_code=201)
async def quick_smr(data: QuickSMR, user: dict = Depends(get_current_user)):
    org_id = user["org_id"]
    project = await db.projects.find_one({"id": data.project_id, "org_id": org_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    now = datetime.now(timezone.utc).isoformat()
    ms = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "project_id": data.project_id,
        "project_name": project.get("name", ""),
        "smr_type": data.smr_type,
        "activity_type": data.smr_type,
        "notes": data.description,
        "qty": data.qty,
        "unit": data.unit,
        "source": "mobile",
        "status": "reported",
        "urgency_type": "emergency",
        "emergency_reason": "Ново от терена",
        "location_id": data.location_id,
        "attachments": [{"media_id": p, "url": f"/api/media/file/{p}", "filename": ""} for p in data.photos],
        "created_at": now,
        "updated_at": now,
        "created_by": user["id"],
        "created_by_name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
        "client_approval": None,
        "ai_estimated_price": None,
        "ai_price_breakdown": None,
        "offer_line_ids": [],
        "linked_extra_work_id": None,
        "linked_offer_id": None,
        "linked_change_order_id": None,
    }
    await db.missing_smr.insert_one(ms)
    return {"missing_smr_id": ms["id"]}


# ── Material Request ───────────────────────────────────────────────

@router.post("/technician/material-request", status_code=201)
async def material_request(data: MaterialRequestSubmit, user: dict = Depends(get_current_user)):
    org_id = user["org_id"]
    now = datetime.now(timezone.utc).isoformat()

    lines = [{"material_name": i.item_name, "qty_requested": i.qty, "unit": i.unit, "notes": i.notes or ""} for i in data.items]
    req = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "project_id": data.project_id,
        "requested_by": user["id"],
        "requested_at": now,
        "status": "submitted" if data.urgent else "draft",
        "is_urgent": data.urgent,
        "lines": lines,
        "notes": "Заявка от терена" if data.urgent else "",
        "created_at": now,
        "updated_at": now,
    }
    await db.material_requests.insert_one(req)
    return {"request_id": req["id"]}


# ── Photo Invoice ──────────────────────────────────────────────────

@router.post("/technician/photo-invoice", status_code=201)
async def photo_invoice(
    file: UploadFile = File(...),
    project_id: str = Form(...),
    description: str = Form(""),
    amount: float = Form(0),
    user: dict = Depends(get_current_user),
):
    org_id = user["org_id"]
    now = datetime.now(timezone.utc).isoformat()

    # Upload file
    content = await file.read()
    ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    media_id = str(uuid.uuid4())
    filename = f"{media_id}.{ext}"

    from pathlib import Path
    upload_dir = Path("/app/backend/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    with open(upload_dir / filename, "wb") as f:
        f.write(content)

    media = {
        "id": media_id, "org_id": org_id, "owner_user_id": user["id"],
        "filename": file.filename, "stored_filename": filename,
        "url": f"/api/media/file/{filename}", "content_type": file.content_type or "image/jpeg",
        "file_size": len(content), "context_type": "project", "context_id": project_id,
        "created_at": now,
    }
    await db.media_files.insert_one(media)

    # Create pending expense
    expense = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "project_id": project_id,
        "submitted_by": user["id"],
        "submitted_by_name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
        "submitted_at": now,
        "media_id": media_id,
        "media_url": media["url"],
        "description": description,
        "amount": amount,
        "currency": "BGN",
        "status": "pending_approval",
        "approved_by": None,
        "approved_at": None,
        "rejection_reason": None,
        "expense_id": None,
        "created_at": now,
    }
    await db.pending_expenses.insert_one(expense)
    return {"expense_id": expense["id"], "media_id": media_id}


# ── Pending Expenses (Admin) ───────────────────────────────────────

@router.get("/pending-expenses")
async def list_pending_expenses(status: str = "pending_approval", user: dict = Depends(get_current_user)):
    items = await db.pending_expenses.find(
        {"org_id": user["org_id"], "status": status}, {"_id": 0}
    ).sort("submitted_at", -1).to_list(200)
    return {"items": items, "total": len(items)}


@router.put("/pending-expenses/{expense_id}/approve")
async def approve_expense(expense_id: str, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    ex = await db.pending_expenses.find_one({"id": expense_id, "org_id": user["org_id"]})
    if not ex:
        raise HTTPException(status_code=404, detail="Expense not found")
    now = datetime.now(timezone.utc).isoformat()
    await db.pending_expenses.update_one({"id": expense_id}, {"$set": {
        "status": "approved", "approved_by": user["id"], "approved_at": now,
    }})
    return await db.pending_expenses.find_one({"id": expense_id}, {"_id": 0})


@router.put("/pending-expenses/{expense_id}/reject")
async def reject_expense(expense_id: str, reason: str = "", user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    ex = await db.pending_expenses.find_one({"id": expense_id, "org_id": user["org_id"]})
    if not ex:
        raise HTTPException(status_code=404, detail="Expense not found")
    now = datetime.now(timezone.utc).isoformat()
    await db.pending_expenses.update_one({"id": expense_id}, {"$set": {
        "status": "rejected", "approved_by": user["id"], "approved_at": now, "rejection_reason": reason,
    }})
    return await db.pending_expenses.find_one({"id": expense_id}, {"_id": 0})


# ── Equipment ──────────────────────────────────────────────────────

@router.get("/technician/my-equipment")
async def my_equipment(user: dict = Depends(get_current_user)):
    items = await db.equipment_assignments.find(
        {"org_id": user["org_id"], "assigned_to": user["id"], "status": "active"},
        {"_id": 0},
    ).to_list(100)
    return {"items": items, "total": len(items)}


@router.post("/technician/request-equipment", status_code=201)
async def request_equipment(data: EquipmentRequest, user: dict = Depends(get_current_user)):
    now = datetime.now(timezone.utc).isoformat()
    req = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "project_id": data.project_id,
        "requested_by": user["id"],
        "item_id": data.item_id,
        "item_description": data.item_description,
        "needed_from": data.needed_from,
        "needed_to": data.needed_to,
        "notes": data.notes,
        "status": "pending",
        "created_at": now,
    }
    await db.equipment_requests.insert_one(req)
    return {"request_id": req["id"]}
