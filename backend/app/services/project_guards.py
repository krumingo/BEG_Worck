"""
Project status guards — shared enforcement for Completed/Archived projects.
Call check_project_writable() before any write that adds new operational/cost data.
"""
from fastapi import HTTPException
from app.db import db

BLOCKED_STATUSES = {"Completed", "Cancelled", "Archived"}

STATUS_BG = {
    "Completed": "Приключен",
    "Cancelled": "Отменен",
    "Archived": "Архивиран",
}


async def check_project_writable(project_id: str, org_id: str, action: str = "запис"):
    """
    Raises 400 if project is Completed/Cancelled/Archived.
    Call before any write that adds new operational data to a project.
    """
    if not project_id:
        return  # No project linked — allow
    project = await db.projects.find_one(
        {"id": project_id, "org_id": org_id},
        {"_id": 0, "status": 1, "name": 1},
    )
    if not project:
        return  # Project not found — let the caller handle
    status = project.get("status", "")
    if status in BLOCKED_STATUSES:
        name = project.get("name", project_id)
        status_bg = STATUS_BG.get(status, status)
        raise HTTPException(
            status_code=400,
            detail=f"Обектът \"{name}\" е {status_bg}. Не могат да се добавят нови {action}.",
        )
