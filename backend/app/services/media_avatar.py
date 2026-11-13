"""
MEDIA-SEC-01 / R83(3) — what may be a user's avatar, and the audit of every change.

Krum, 10.11.2026 (R83): only a FRESHLY uploaded profile photo (``context_type="profile"``
at upload) can be an avatar; an existing file is never linked as one; every avatar change
is audited; an old avatar may be retired by its owner or an Admin.

* ``media_files.avatar = True`` is set by ``POST /media/upload`` with ``context_type="profile"``
  only (and, for legacy rows, by ``scripts/media_sec_01_avatar_backfill.py`` after Krum's
  "да"). ``POST /media/link`` refuses ``context_type="profile"``.
* ``users.avatar_url`` may be set only to ``/api/media/avatar/<stored_filename>`` of a
  non-retired avatar row of the SAME tenant whose profile is that user — or cleared.
* Every change of ``users.avatar_url`` writes the canonical AuditEvent ``user.avatar.change``.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from fastapi import HTTPException

AVATAR_URL_PREFIX = "/api/media/avatar/"
MEDIA_RETIRED = "retired"
_STORED_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}\.[A-Za-z0-9]{1,10}$")


def stored_name_of(url: Any) -> Optional[str]:
    """``/api/media/avatar/<name>`` -> ``<name>`` (strict shape), else None."""
    if not isinstance(url, str) or not url.startswith(AVATAR_URL_PREFIX):
        return None
    name = url[len(AVATAR_URL_PREFIX):]
    return name if _STORED_NAME.fullmatch(name) else None


def _refuse(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"error_code": "AVATAR_NOT_ALLOWED",
                                                  "message": message})


async def check_avatar_url(tenant, org_id: str, target_user_id: str, url: Any) -> Optional[str]:
    """The value to store for ``users.avatar_url``, or 400 ``AVATAR_NOT_ALLOWED``.

    An empty value clears the avatar (returns ""). Anything else must name a non-retired
    avatar row of this tenant whose profile is ``target_user_id``."""
    if url is None:
        return None
    if isinstance(url, str) and url.strip() == "":
        return ""
    name = stored_name_of(url)
    if not name:
        raise _refuse("Аватарът трябва да е нова профилна снимка (/api/media/avatar/...)")
    row = await tenant.media_files.find_one(
        {"stored_filename": name, "org_id": org_id, "avatar": True,
         "context_type": "profile", "context_id": target_user_id,
         "status": {"$ne": MEDIA_RETIRED}},
        {"_id": 0, "id": 1})
    if not row:
        raise _refuse("Файлът не е профилна снимка на този потребител")
    return url


async def audit_avatar_change(db_handle, actor: Dict[str, Any], *, target_user_id: str,
                              before: Any, after: Any, endpoint: str, session=None) -> None:
    """The canonical AuditEvent ``user.avatar.change`` (FLOW-002 user data, FLOW-029 file)."""
    if (before or "") == (after or ""):
        return
    from app.audit.envelope import ACTOR_HUMAN, RETENTION_R1_CRITICAL_BUSINESS, build_event
    from app.audit.store import record_event
    event = build_event(
        tenant_id=actor["org_id"], actor_type=ACTOR_HUMAN, actor_id=actor["id"],
        action="user.avatar.change", source_flow="FLOW-029",
        retention_class=RETENTION_R1_CRITICAL_BUSINESS, entity_type="user",
        entity_id=target_user_id, reason="avatar changed",
        structured_diff={"before": {"avatar_url": before or None},
                         "after": {"avatar_url": after or None}},
        effective_role_assignments=[actor.get("role") or ""],
        tool_or_endpoint=endpoint, source_channel="api")
    await record_event(db_handle, event, session=session)


async def write_user_with_avatar(db_handle, tenant, actor: Dict[str, Any], *, target_user_id: str,
                                 update: Dict[str, Any], before: Any, endpoint: str) -> None:
    """ONE transaction: the claim on the new avatar's file row (FG-579 — a concurrent retire
    and this new reference cannot both commit), the ``users`` write, and the canonical
    AuditEvent ``user.avatar.change`` (pass 46: the audit inside the transaction)."""
    from app.services.auth_tx import run_in_transaction
    from app.services.file_holders import claim

    async def body(session):
        after = update.get("avatar_url")
        if after:
            await claim(tenant, actor["org_id"], [after], session=session)
        res = await tenant.users.update_one({"id": target_user_id}, {"$set": update},
                                            session=session)
        if res.matched_count != 1:
            raise HTTPException(status_code=404, detail="User not found")
        await audit_avatar_change(db_handle, actor, target_user_id=target_user_id,
                                  before=before, after=after, endpoint=endpoint,
                                  session=session)
        return True

    await run_in_transaction(db_handle, body)
