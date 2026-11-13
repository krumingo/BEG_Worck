"""
MEDIA-SEC-01 (FG-575, R83(1)) — ONE upload guard for EVERY upload entry point.

Krum, R83(1): a Viewer — by company role or by project role, member or not — only reads;
uploads are for Technician, SiteManager and office roles. FLOW Guard pass 46 found the rule
on one route only (project photos) while ``/media/upload`` and ``/technician/photo-invoice``
still took a Viewer's file. Every route that accepts a file calls :func:`require_uploader`
BEFORE it reads the file, so a refusal writes nothing.

The roles come from ``app.services.media_policy`` (one place to change the rule).
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException


def _deny() -> HTTPException:
    return HTTPException(status_code=403, detail={"error_code": "UPLOAD_NOT_ALLOWED",
                                                  "message": "Нямате право да качвате файлове"})


async def require_uploader(user: dict, project_id: Optional[str] = None) -> None:
    """403 ``UPLOAD_NOT_ALLOWED`` for a company role in ``UPLOAD_DENIED_ROLES``; with a
    ``project_id``, also for a non-member (Admin/Owner excepted) and for a member whose
    project role is in ``UPLOAD_DENIED_PROJECT_ROLES``."""
    from app.services.media_policy import UPLOAD_DENIED_PROJECT_ROLES, UPLOAD_DENIED_ROLES
    role = (user or {}).get("role")
    if not role or role in UPLOAD_DENIED_ROLES:
        raise _deny()
    if not project_id or role in ("Admin", "Owner"):
        return
    from app.db import db
    from app.deps.auth import can_access_project
    from app.tenancy import project_team
    if not await can_access_project(user, project_id):
        raise _deny()
    team = project_team.tenant_for(db, user)
    for prole in UPLOAD_DENIED_PROJECT_ROLES:
        if await project_team.is_member(team, user["id"], project_id, prole):
            raise _deny()
