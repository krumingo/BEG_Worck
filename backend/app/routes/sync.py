"""PWA-02 (R61) — offline queue sync API and the Owner/Admin console.

Everything here is behind the per-tenant feature flag ``offline_queue`` (off by default;
only the platform administrator switches it). See ``app/services/offline_sync.py``.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, Header, Request

from app.deps.auth import get_current_user, require_admin, require_platform_admin
from app.services import offline_sync as sync
from app.services import offline_sync_handlers  # noqa: F401 — registers the 3 offline types

router = APIRouter(prefix="/sync", tags=["offline-sync"])


def _require_key(header: Optional[str]) -> str:
    key = header.strip() if isinstance(header, str) else ""
    if not key or len(key) > 200:
        raise sync.refuse(428, "IDEMPOTENCY_KEY_REQUIRED",
                          "Липсва Idempotency-Key — заявката не е записана")
    return key


def _require_reason(value: Any) -> str:
    reason = value.strip() if isinstance(value, str) else ""
    if len(reason) < 3:
        raise sync.refuse(422, "REASON_REQUIRED", "Посочете причина")
    return reason[:500]


@router.get("/status")
async def sync_status(device_id: Optional[str] = None, user: dict = Depends(get_current_user)):
    """Is the offline queue on, is this phone blocked, and the server clock (the phone
    computes ``device_clock_offset_ms`` from it)."""
    enabled = await sync.is_enabled(user)
    revoked = False
    if enabled and device_id:
        device = await sync.get_device(user, sync.valid_device_id(device_id))
        revoked = bool(device and device.get("revoked_at"))
    return {"enabled": enabled, "revoked": revoked, "server_time": sync.iso(sync.now_utc()),
            "tenant_id": user["org_id"], "user_id": user["id"]}


@router.post("/devices/register")
async def register_device(request: Request, body: Dict[str, Any] = Body(...),
                          user: dict = Depends(get_current_user)):
    await sync.require_enabled(user)
    return await sync.register_device(user, body.get("device_id"), body.get("label") or "",
                                      request.headers.get("user-agent") or "")


@router.post("/batch")
async def sync_batch(body: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
    """Each item goes through the same domain path as its online endpoint; see the module
    docstring of ``offline_sync`` for the order of the checks."""
    await sync.require_enabled(user)
    return await sync.process_batch(user, body.get("device_id"), body.get("items"))


@router.get("/receipts")
async def my_receipts(device_id: str, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    await sync.require_enabled(user)
    return await sync.my_receipts(user, device_id)


@router.get("/console")
async def sync_console(user: dict = Depends(require_admin)):
    """Owner/Admin only (FLOW-037 §14): devices, conflicts, late records, quarantine."""
    return await sync.console(user)


@router.post("/devices/{device_id}/revoke")
async def revoke_device(device_id: str, body: Dict[str, Any] = Body(...),
                        idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
                        user: dict = Depends(require_admin)):
    """R61-6: block a lost or stolen phone (Owner/Admin, reason, AuditEvent)."""
    key = _require_key(idempotency_key)
    return await sync.revoke_device(user, device_id, _require_reason(body.get("reason")), key)


@router.post("/late/{late_id}/decide")
async def decide_late(late_id: str, body: Dict[str, Any] = Body(...),
                      idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
                      user: dict = Depends(require_admin)):
    """R61-3: Owner/Admin confirms, corrects or refuses a late record (reason + AuditEvent).
    The only path that writes with the captured date."""
    key = _require_key(idempotency_key)
    return await sync.decide_late(user, late_id, body.get("decision"), _require_reason(body.get("reason")),
                                  body.get("payload"), key)


@router.post("/conflicts/{conflict_id}/resolve")
async def resolve_conflict(conflict_id: str, body: Dict[str, Any] = Body(...),
                           idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
                           user: dict = Depends(require_admin)):
    """R61-2/4: keep the office version, accept the phone's, or correct (reason + AuditEvent);
    an approved / paid record only through correction or reversal."""
    key = _require_key(idempotency_key)
    return await sync.resolve_conflict(user, conflict_id, body.get("decision"),
                                       _require_reason(body.get("reason")), body.get("payload"), key)


@router.put("/flag")
async def set_flag(body: Dict[str, Any] = Body(...), user: dict = Depends(require_platform_admin)):
    """Switch the offline queue on/off for the tenant (platform administrator only, like the
    other feature flags). Switching it off stops the queue; nothing already sent is lost."""
    return await sync.set_enabled(user, body.get("enabled") is True)
