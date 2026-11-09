"""
Project status guards — shared enforcement for Completed/Archived projects.
Call check_project_writable() before any write that adds new operational/cost data.
"""
from fastapi import HTTPException
from app.db import db
from app.tenancy.data_access import TenantData

BLOCKED_STATUSES = {"Completed", "Cancelled", "Archived"}

STATUS_BG = {
    "Completed": "Приключен",
    "Cancelled": "Отменен",
    "Archived": "Архивиран",
}


PROJECT_DELETED = "PROJECT_DELETED"


async def refuse_if_deleted(tenant: TenantData, project_id) -> None:
    """PRJ-01 / D14: an empty Draft that was "deleted" stays as a tombstone (CLAUDE.md §2
    rule 9). A new record that names it is refused — 409 ``PROJECT_DELETED`` — by the
    shared project lookups writers use (this guard, ``money_input.project_in_tenant``,
    ``finance._require_tenant_project``)."""
    if project_id and await tenant.projects.tombstone(project_id, {"_id": 0, "id": 1}):
        raise HTTPException(status_code=409, detail={
            "error_code": PROJECT_DELETED,
            "message": "Обектът е изтрит (празна чернова) — не може да получава нови записи"})


async def check_project_writable(project_id: str, org_id: str, action: str = "запис"):
    """
    Raises 400 if project is Completed/Cancelled/Archived.
    Call before any write that adds new operational data to a project.
    """
    tenant = TenantData.for_resolved_org(db, org_id)
    if not project_id:
        return  # No project linked — allow
    project = await tenant.projects.find_one(
        {"id": project_id, "org_id": org_id},
        {"_id": 0, "status": 1, "name": 1},
    )
    if not project:
        # PRJ-01 / D14: a deleted (tombstoned) project takes no new record → 409
        await refuse_if_deleted(tenant, project_id)
        return  # Project not found — let the caller handle
    status = project.get("status", "")
    if status in BLOCKED_STATUSES:
        name = project.get("name", project_id)
        status_bg = STATUS_BG.get(status, status)
        raise HTTPException(
            status_code=400,
            detail=f"Обектът \"{name}\" е {status_bg}. Не могат да се добавят нови {action}.",
        )
