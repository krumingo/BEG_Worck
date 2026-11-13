"""
Routes - Media (Photos) Endpoints.
"""
from fastapi import APIRouter, Body, Depends, Header, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from datetime import datetime, timezone
import re
import uuid
from pathlib import Path

from app.db import db
from app.tenancy import project_team
from app.deps.auth import get_current_user
from app.deps.media_acl import enforce_media_access, enforce_context_access, MEDIA_CONTEXT_TYPES, check_media_access
from app.services import project_lifecycle as lifecycle

router = APIRouter(tags=["Media"])

# ── Constants ──────────────────────────────────────────────────────

ALLOWED_MEDIA_TYPES = ["image/jpeg", "image/png", "image/webp", "image/heic"]
MAX_MEDIA_SIZE_MB = 10
UPLOAD_DIR = Path("/app/backend/uploads")

# MEDIA-SEC-01 (FG-542): a media file is RETIRED, never deleted (CLAUDE.md §2 rule 9).
MEDIA_RETIRED = "retired"
# MEDIA-SEC-01 (FG-540): an avatar is a media row of the caller's tenant linked to a profile.
AVATAR_CONTEXT_TYPES = ("profile",)
# The only shape a stored file name has ever been written in (``{uuid4}.{ext}``, upload_media,
# ocr_invoice, technician): anything else — separators, "..", NUL, encoded tricks — is no
# avatar and gets the same 404 as an unknown name (no oracle).
_STORED_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}\.[A-Za-z0-9]{1,10}$")


# ── Pydantic Models ────────────────────────────────────────────────

from pydantic import BaseModel
from app.tenancy.data_access import TenantData


def _tenant(user: dict) -> TenantData:
    """The request's tenant — from the server-loaded session user only (W0-03E-A2C)."""
    return TenantData.for_user(db, user)

class MediaLinkRequest(BaseModel):
    media_id: str
    context_type: str
    context_id: str


# ── Routes ─────────────────────────────────────────────────────────

@router.post("/media/upload")
async def upload_media(
    file: UploadFile = File(...),
    context_type: str = Form(None),
    context_id: str = Form(None),
    user: dict = Depends(get_current_user)
):
    """Upload a media file (photo)"""
    tenant = _tenant(user)
    org_id = user["org_id"]
    # MEDIA-SEC-01 (FG-575, R83(1), FG-587): the one upload guard, before anything is read;
    # the project is resolved from ANY context that belongs to a project
    from app.deps.upload_guard import require_uploader_for_context
    await require_uploader_for_context(user, context_type, context_id)
    
    # ── Validate context access BEFORE processing file ─────────────────
    # If context is provided, verify user has access to link to it
    if context_type and context_id:
        # Validate context_type
        if context_type not in MEDIA_CONTEXT_TYPES:
            raise HTTPException(status_code=400, detail={
                "error_code": "INVALID_CONTEXT_TYPE",
                "message": f"Invalid context type. Allowed: {MEDIA_CONTEXT_TYPES}",
            })
        # Verify user can access target context
        await enforce_context_access(user, context_type, context_id)
    elif context_type or context_id:
        # Partial context data - reject
        raise HTTPException(status_code=400, detail={
            "error_code": "INCOMPLETE_CONTEXT",
            "message": "Both context_type and context_id must be provided together",
        })
    
    # ── Validate file type ─────────────────────────────────────────────
    if file.content_type not in ALLOWED_MEDIA_TYPES:
        raise HTTPException(status_code=400, detail={
            "error_code": "INVALID_FILE_TYPE",
            "message": f"File type not allowed. Allowed: {ALLOWED_MEDIA_TYPES}",
        })
    
    # Read file content
    content = await file.read()
    file_size = len(content)
    
    # Validate file size
    if file_size > MAX_MEDIA_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail={
            "error_code": "FILE_TOO_LARGE",
            "message": f"File size exceeds {MAX_MEDIA_SIZE_MB}MB limit",
        })
    
    # Generate unique filename
    ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    media_id = str(uuid.uuid4())
    filename = f"{media_id}.{ext}"
    
    # Store file (for now, using local storage - in production, use S3/GCS)
    upload_dir = Path("/app/backend/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / filename
    
    # Write file to disk
    # Note: File is written AFTER all validations pass (context access, file type, size)
    with open(file_path, "wb") as f:
        f.write(content)
    
    # Generate URL (relative for local, absolute for cloud storage)
    file_url = f"/api/media/file/{filename}"
    
    now = datetime.now(timezone.utc).isoformat()
    
    media = {
        "id": media_id,
        "org_id": org_id,
        "owner_user_id": user["id"],
        "filename": file.filename,
        "stored_filename": filename,
        "url": file_url,
        "content_type": file.content_type,
        "file_size": file_size,
        "context_type": context_type,
        "context_id": context_id,
        "created_at": now,
    }
    
    if context_type in AVATAR_CONTEXT_TYPES:
        # MEDIA-SEC-01 / R83(3): only a FRESH profile upload can ever be an avatar
        media["avatar"] = True
    await tenant.media_files.insert_one(media)
    
    return {
        "id": media_id,
        "url": file_url,
        "filename": file.filename,
        "file_size": file_size,
        "context_type": context_type,
        "context_id": context_id,
    }


@router.post("/media/link")
async def link_media(data: MediaLinkRequest, user: dict = Depends(get_current_user)):
    """Link an existing media file to a context"""
    tenant = _tenant(user)
    org_id = user["org_id"]
    
    # Validate context type
    if data.context_type not in MEDIA_CONTEXT_TYPES:
        raise HTTPException(status_code=400, detail={
            "error_code": "INVALID_CONTEXT_TYPE",
            "message": f"Invalid context type. Allowed: {MEDIA_CONTEXT_TYPES}",
        })
    
    # MEDIA-SEC-01 (FG-587): linking a file to a record adds it there — the same upload
    # guard as POST /media/upload (a company or project Viewer → 403), nothing written
    from app.deps.upload_guard import require_uploader_for_context
    await require_uploader_for_context(user, data.context_type, data.context_id)

    # Find media file
    media = await tenant.media_files.find_one({"id": data.media_id, "org_id": org_id}, {"_id": 0})
    if not media:
        raise HTTPException(status_code=404, detail="Media file not found")
    
    # Check ownership or admin (user must own the media to link it)
    # Legacy safety: if owner_user_id is missing, only admin can link
    owner_user_id = media.get("owner_user_id")
    if not owner_user_id:
        if user["role"] not in ["Admin", "Owner"]:
            raise HTTPException(status_code=403, detail="Media has no owner; only admin can link")
    elif owner_user_id != user["id"] and user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Not authorized to link this media")

    # MEDIA-SEC-01 (FG-544): a file has ONE link; linking it again would silently move it
    # away from the first record. A linked or retired file is refused, nothing written.
    if media.get("status") == MEDIA_RETIRED:
        raise lifecycle.refuse(409, "MEDIA_RETIRED", "Файлът е скрит и не може да се свърже")
    if media.get("context_type") or media.get("context_id"):
        if (media.get("context_type"), media.get("context_id")) == (data.context_type, data.context_id):
            return {"id": data.media_id, "context_type": data.context_type,
                    "context_id": data.context_id, "linked": True}
        raise lifecycle.refuse(409, "MEDIA_ALREADY_LINKED",
                               "Файлът вече е свързан с друг запис",
                               context_type=media.get("context_type"))
    
    # ── TARGET CONTEXT ACCESS CHECK ────────────────────────────────────
    # Verify user has access to the target context before allowing link
    # This prevents linking media to contexts the user doesn't have access to
    await enforce_context_access(user, data.context_type, data.context_id)
    
    # Update media with context
    now = datetime.now(timezone.utc).isoformat()
    if data.context_type in AVATAR_CONTEXT_TYPES:
        # MEDIA-SEC-01 / R83(3): an existing file is never linked as a profile photo/avatar
        raise lifecycle.refuse(409, "AVATAR_LINK_REFUSED",
                               "Профилна снимка се качва наново, не се свързва")
    if media.get("retire_request_pending"):
        # FG-577: no new reference while a retire request waits for the Owner
        raise lifecycle.refuse(409, "RETIRE_REQUEST_PENDING", "За файла има чакаща заявка за премахване")
    from app.services.auth_tx import run_in_transaction

    async def _link(session):
        # compare-and-set: only a file that is STILL unlinked, not retired and with no
        # pending request gets the link; ref_version moves (FG-579) so a concurrent retire
        # cannot commit too. FG-544: the link is an AuditEvent.
        res = await tenant.media_files.update_one(
            {"id": data.media_id, "org_id": org_id, "status": {"$ne": MEDIA_RETIRED},
             "retire_request_pending": None,
             "$and": [{"$or": [{"context_type": None}, {"context_type": ""}]},
                      {"$or": [{"context_id": None}, {"context_id": ""}]}]},
            {"$set": {"context_type": data.context_type, "context_id": data.context_id,
                      "linked_at": now, "linked_by": user["id"]},
             "$inc": {"ref_version": 1}}, session=session)
        if res.matched_count != 1:
            raise lifecycle.refuse(409, "MEDIA_ALREADY_LINKED", "Файлът вече е свързан с друг запис")
        await lifecycle.audit(session, user, action="media.file.link", entity_type="media_file",
                              entity_id=data.media_id, reason="linked", key=None,
                              source_flow="FLOW-029",
                              diff={"before": {"context_type": None, "context_id": None},
                                    "after": {"context_type": data.context_type,
                                              "context_id": data.context_id}})
        return True

    await run_in_transaction(db, _link)
    
    return {
        "id": data.media_id,
        "context_type": data.context_type,
        "context_id": data.context_id,
        "linked": True,
    }


@router.get("/media/{media_id}")
async def get_media(media_id: str, user: dict = Depends(get_current_user)):
    """Get media file metadata"""
    tenant = _tenant(user)
    org_id = user["org_id"]
    
    media = await tenant.media_files.find_one({"id": media_id, "org_id": org_id}, {"_id": 0})
    if not media:
        raise HTTPException(status_code=404, detail="Media file not found")
    
    # ACL check: enforces org isolation, owner/admin access, and context-based rules
    await enforce_media_access(user, media, action="meta")

    if media.get("status") == MEDIA_RETIRED and user.get("role") not in ("Owner", "Admin"):
        # MEDIA-SEC-01 (FG-558): a retired file's metadata is for Owner/Admin only. R83(2):
        # a record that still points at it learns only THAT it was retired (410), nothing else.
        raise HTTPException(status_code=410, detail={"error_code": "MEDIA_RETIRED",
                                                     "media_id": media_id, "retired": True})
    
    # Enrich with owner name (handle legacy records with missing owner_user_id)
    owner_user_id = media.get("owner_user_id")
    if owner_user_id:
        owner = await tenant.users.find_one({"id": owner_user_id}, {"_id": 0, "first_name": 1, "last_name": 1})
        media["owner_user_name"] = f"{owner.get('first_name', '')} {owner.get('last_name', '')}".strip() if owner else ""
    else:
        media["owner_user_name"] = "(unknown)"
    
    return media


_optional_bearer = HTTPBearer(auto_error=False)


async def _logged_in_user(
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer)) -> dict:
    """The session user, or 401 — also when no Authorization header is sent at all
    (FastAPI 0.110's ``HTTPBearer`` would answer that case with 403)."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated",
                            headers={"WWW-Authenticate": "Bearer"})
    return await get_current_user(credentials)


@router.get("/media/avatar/{filename}")
async def serve_avatar(filename: str, user: dict = Depends(_logged_in_user)):
    """MEDIA-SEC-01 (FG-540; CLAUDE.md §3, §2 rule 11): an avatar for a LOGGED-IN user only.

    The file is resolved ONLY through a ``media_files`` row of the caller's tenant
    (server-side tenant from the session, never from the request) that is a profile picture
    (``context_type`` in AVATAR_CONTEXT_TYPES) and is not retired. The path on disk is built
    from that row's ``stored_filename`` — the raw request name is never mapped to a path.
    Any other file — another tenant's, a site photo, a receipt, an OCR invoice, a traversal
    attempt, an unknown name — is the same 404."""
    not_found = HTTPException(status_code=404, detail="Avatar not found")
    if not isinstance(filename, str) or not _STORED_NAME.fullmatch(filename):
        raise not_found
    tenant = _tenant(user)
    media = await tenant.media_files.find_one(
        {"stored_filename": filename, "org_id": user["org_id"],
         "context_type": {"$in": list(AVATAR_CONTEXT_TYPES)}, "avatar": True,
         "status": {"$ne": MEDIA_RETIRED}},
        {"_id": 0, "stored_filename": 1, "content_type": 1})
    stored = (media or {}).get("stored_filename")
    if not isinstance(stored, str) or not _STORED_NAME.fullmatch(stored):
        raise not_found
    root = UPLOAD_DIR.resolve()
    file_path = (root / stored).resolve()
    if file_path.parent != root or not file_path.is_file():
        raise not_found
    return FileResponse(file_path, media_type=media.get("content_type") or "image/jpeg")


@router.get("/media/file/{filename}")
async def serve_media_file(filename: str, user: dict = Depends(get_current_user)):
    """Serve media file content"""
    tenant = _tenant(user)
    # ── Path traversal protection ──────────────────────────────────────
    # Sanitize filename: only allow alphanumeric, dash, underscore, dot
    # Reject any path separators or suspicious patterns
    UPLOAD_DIR = Path("/app/backend/uploads")
    
    # Check for path traversal attempts
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    # Resolve path safely and verify it stays within upload directory
    file_path = (UPLOAD_DIR / filename).resolve()
    if not str(file_path).startswith(str(UPLOAD_DIR.resolve())):
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    # Check file exists
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    # ── ACL check ──────────────────────────────────────────────────────
    # Get media metadata to verify access
    media = await tenant.media_files.find_one({"stored_filename": filename, "org_id": user["org_id"]}, {"_id": 0})
    if not media:
        raise HTTPException(status_code=404, detail="Media not found or access denied")
    if media.get("status") == MEDIA_RETIRED and user.get("role") not in ("Owner", "Admin"):
        # MEDIA-SEC-01 (FG-542): a retired file is kept as evidence for Owner/Admin only
        raise HTTPException(status_code=404, detail="Media not found or access denied")
    
    # Enforce context-based ACL for download action
    await enforce_media_access(user, media, action="download")
    
    return FileResponse(file_path, media_type=media.get("content_type", "application/octet-stream"))


@router.get("/media")
async def list_media(
    context_type: Optional[str] = None,
    context_id: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    """List media files for the organization, optionally filtered by context"""
    tenant = _tenant(user)
    org_id = user["org_id"]
    user_id = user["id"]
    user_role = user["role"]
    
    # ── Build base query ───────────────────────────────────────────────
    query = {"org_id": org_id, "status": {"$ne": MEDIA_RETIRED}}   # FG-542: retired, not deleted
    
    # Apply context filters if provided
    if context_type:
        query["context_type"] = context_type
    if context_id:
        query["context_id"] = context_id
    
    # ── Role-based query optimization ──────────────────────────────────
    # Admin/Owner: see all media in org (no additional filter)
    # SiteManager: see own media + media linked to projects they manage
    # Others: see own media + media linked to contexts they have access to
    
    if user_role in ["Admin", "Owner"]:
        # Full access - no additional restrictions
        pass
    elif user_role == "SiteManager":
        # SiteManager sees: own media OR media linked to their projects
        # For efficiency, we'll fetch and post-filter
        pass
    else:
        # Technician/Driver/Accountant: fetch candidates and post-filter
        # If specific context_id is given, we'll verify access
        # Otherwise, restrict to own media by default
        if not context_id:
            query["owner_user_id"] = user_id
    
    # ── Fetch candidates ───────────────────────────────────────────────
    media_list = await tenant.media_files.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    
    # ── Post-filter for ACL compliance ─────────────────────────────────
    # Admin/Owner already have full access, skip filtering
    if user_role in ["Admin", "Owner"]:
        return media_list[:100]  # Limit response size
    
    # ══════════════════════════════════════════════════════════════════
    # OPTIMIZED: Batch prefetch context data to avoid N+1 queries
    # ══════════════════════════════════════════════════════════════════
    
    # Step 1: Collect unique context IDs by type
    context_ids_by_type = {}
    for media in media_list:
        ctx_type = media.get("context_type")
        ctx_id = media.get("context_id")
        if ctx_type and ctx_id:
            if ctx_type not in context_ids_by_type:
                context_ids_by_type[ctx_type] = set()
            context_ids_by_type[ctx_type].add(ctx_id)
    
    # Step 2: Batch fetch all needed context data
    prefetched = {}
    
    # Prefetch projects the user can access (via project_team)
    user_project_ids = set()
    # W0-03E-A2: one relation accessor; the tenant predicate is applied last.
    team_memberships = await project_team.user_rows(
        project_team.tenant_for_org(db, org_id), user_id, {"_id": 0, "project_id": 1},
        active_only=False, limit=500)
    for tm in team_memberships:
        user_project_ids.add(tm.get("project_id"))
    prefetched["user_project_ids"] = user_project_ids
    
    # Prefetch work reports (author + project_id)
    if "workReport" in context_ids_by_type:
        reports = await tenant.work_reports.find(
            {"id": {"$in": list(context_ids_by_type["workReport"])}, "org_id": org_id},
            {"_id": 0, "id": 1, "user_id": 1, "project_id": 1}
        ).to_list(500)
        prefetched["workReport"] = {r["id"]: r for r in reports}
    
    # Prefetch deliveries (driver + project_id)
    if "delivery" in context_ids_by_type:
        deliveries = await tenant.deliveries.find(
            {"id": {"$in": list(context_ids_by_type["delivery"])}, "org_id": org_id},
            {"_id": 0, "id": 1, "driver_user_id": 1, "project_id": 1}
        ).to_list(500)
        prefetched["delivery"] = {d["id"]: d for d in deliveries}
    
    # Prefetch attendance (user + project_id)
    if "attendance" in context_ids_by_type:
        entries = await tenant.attendance_entries.find(
            {"id": {"$in": list(context_ids_by_type["attendance"])}, "org_id": org_id},
            {"_id": 0, "id": 1, "user_id": 1, "project_id": 1}
        ).to_list(500)
        prefetched["attendance"] = {e["id"]: e for e in entries}
    
    # Prefetch machines (project_id)
    if "machine" in context_ids_by_type:
        machines = await tenant.machines.find(
            {"id": {"$in": list(context_ids_by_type["machine"])}, "org_id": org_id},
            {"_id": 0, "id": 1, "project_id": 1}
        ).to_list(500)
        prefetched["machine"] = {m["id"]: m for m in machines}
    
    # Step 3: Filter using prefetched data (no additional DB calls)
    def check_access_fast(media: dict) -> bool:
        """Fast ACL check using prefetched data."""
        owner_user_id = media.get("owner_user_id")
        ctx_type = media.get("context_type")
        ctx_id = media.get("context_id")
        
        # Owner always has access
        if owner_user_id == user_id:
            return True
        
        # No owner or corrupted record
        if not owner_user_id:
            return False
        
        # No context = only owner can access (already checked above)
        if not ctx_type or not ctx_id:
            return False
        
        # Context-based checks using prefetched data
        if ctx_type == "workReport":
            report = prefetched.get("workReport", {}).get(ctx_id)
            if not report:
                return False
            if report.get("user_id") == user_id:
                return True
            if report.get("project_id") in user_project_ids:
                return True
            return False
        
        elif ctx_type == "delivery":
            delivery = prefetched.get("delivery", {}).get(ctx_id)
            if not delivery:
                return False
            if delivery.get("driver_user_id") == user_id:
                return True
            if delivery.get("project_id") in user_project_ids:
                return True
            return False
        
        elif ctx_type == "attendance":
            entry = prefetched.get("attendance", {}).get(ctx_id)
            if not entry:
                return False
            if entry.get("user_id") == user_id:
                return True
            # SiteManager can see attendance for their projects
            if user_role == "SiteManager" and entry.get("project_id") in user_project_ids:
                return True
            return False
        
        elif ctx_type == "project":
            return ctx_id in user_project_ids
        
        elif ctx_type == "profile":
            return ctx_id == user_id
        
        elif ctx_type == "machine":
            machine = prefetched.get("machine", {}).get(ctx_id)
            if not machine:
                return False
            return machine.get("project_id") in user_project_ids
        
        elif ctx_type == "message":
            # Allow same org (simplified for now)
            return True
        
        return False
    
    # Apply fast filter
    filtered_list = []
    for media in media_list:
        if check_access_fast(media):
            filtered_list.append(media)
        if len(filtered_list) >= 100:
            break
    
    return filtered_list


async def _media_usages(tenant, org_id: str, media: dict, session=None) -> list:
    """MEDIA-SEC-01: every record that uses this file — the ONE registry
    (``app.services.file_holders``, FG-576). Empty → unused."""
    from app.services.file_holders import find_holders
    return await find_holders(tenant, org_id, media, session=session)


async def _enforce_retire_rights(user: dict, media: dict) -> None:
    """Who may retire an UNUSED file: its owner, Admin/Owner (``enforce_media_access``
    ``delete``) and — R83(3) — for an avatar, the user whose profile photo it is."""
    if (media.get("avatar") and media.get("context_type") in AVATAR_CONTEXT_TYPES
            and media.get("org_id") == user.get("org_id")
            and media.get("context_id") == user.get("id")):
        return
    await enforce_media_access(user, media, action="delete")


def _in_use(user: dict, media_id: str, uses: list) -> HTTPException:
    """409 MEDIA_IN_USE; WHICH records use the file only for Owner/Admin (pass 46)."""
    from app.services.file_holders import redact
    return lifecycle.refuse(409, "MEDIA_IN_USE", "Файлът се използва и не може да бъде премахнат",
                            request_path="/api/media/%s/retire-request" % media_id,
                            **redact(uses, user))


@router.delete("/media/{media_id}")
async def delete_media(media_id: str, body: Optional[dict] = Body(None),
                       reason: Optional[str] = None,
                       user: dict = Depends(get_current_user),
                       idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """MEDIA-SEC-01 (FG-542; CLAUDE.md §2 rule 9, §4): a media file is RETIRED, never deleted.

    * a file that any record holds (``app.services.file_holders``) → 409 ``MEDIA_IN_USE``,
      nothing written — the Owner-approved request is the only way (R83(2));
    * an unused file → the row stays with ``status="retired"``, the reason, who and when;
      the original file stays on disk; one transaction with the canonical AuditEvent
      ``media.file.retire``. The write is a CAS on ``ref_version`` (FG-579): a reference
      written meanwhile makes it 409 ``MEDIA_CHANGED``.

    Rights: the owner, Admin/Owner, the avatar's user; a reason and an Idempotency-Key."""
    tenant = _tenant(user)
    org_id = user["org_id"]
    key = lifecycle.require_key(idempotency_key)
    why = lifecycle.require_reason((body or {}).get("reason") if (body or {}).get("reason")
                                   is not None else reason)

    async def work(session):
        media = await tenant.media_files.find_one({"id": media_id, "org_id": org_id},
                                                  {"_id": 0}, session=session)
        if not media:
            raise HTTPException(status_code=404, detail="Media file not found")
        await _enforce_retire_rights(user, media)
        if media.get("status") == MEDIA_RETIRED:
            raise lifecycle.refuse(409, "MEDIA_ALREADY_RETIRED", "Файлът вече е скрит")
        uses = await _media_usages(tenant, org_id, media, session=session)
        if uses or media.get("retire_request_pending"):
            raise _in_use(user, media_id, uses)
        now = lifecycle.now_iso()
        res = await tenant.media_files.update_one(
            {"id": media_id, "org_id": org_id, "status": {"$ne": MEDIA_RETIRED},
             "retire_request_pending": None, "ref_version": media.get("ref_version"),
             "$and": [_NO_PENDING],    # FG-588 condition 2: no pending holder
             "context_type": media.get("context_type"), "context_id": media.get("context_id")},
            {"$set": {"status": MEDIA_RETIRED, "retired_reason": why, "retired_at": now,
                      "retired_by": user["id"]}}, session=session)
        if res.matched_count != 1:
            raise lifecycle.refuse(409, "MEDIA_CHANGED", "Файлът току-що се промени")
        await lifecycle.audit(session, user, action="media.file.retire",
                              entity_type="media_file", entity_id=media_id, reason=why,
                              key=key, source_flow="FLOW-029",
                              diff={"before": {"status": media.get("status") or "active"},
                                    "after": {"status": MEDIA_RETIRED},
                                    "stored_filename": media.get("stored_filename")})
        return {"ok": True, "retired": media_id}

    return await lifecycle.keyed_transaction(user, key, "media.file.retire",
                                             {"media_id": media_id, "reason": why}, work)


# ══════════════════════════════════════════════════════════════════════════════
# R83(2) — retiring a file that is USED by a record: request → Owner approves
# ══════════════════════════════════════════════════════════════════════════════
# INTERIM (FLOW Guard pass 46): there is no canonical Approval runtime yet. This minimal
# flow is debt to W0-07 and must not become a second Approval source of truth — when
# W0-07 lands, ``media_retire_requests`` moves into it. Who files / approves is
# ``app.services.media_policy`` (interim: an Admin files, an Owner approves).
#   POST /api/media/{id}/retire-request            RETIRE_REQUEST_ROLES
#   POST /api/media/retire-requests/{rid}/approve  RETIRE_APPROVER_ROLES, never the requester
#   POST /api/media/retire-requests/{rid}/reject   RETIRE_APPROVER_ROLES
#   GET  /api/media-retire-requests                Owner / Admin
# FG-577 (CLAUDE.md §8 exact version): the request stores the holders, their version and
# the file's ``ref_version``; while it is pending no writer may add a reference
# (``file_holders.claim`` → 409); the approval re-reads the holders and refuses
# 409 ``RETIRE_REQUEST_STALE`` when they are not the ones the request named.
REQ_PENDING, REQ_APPROVED, REQ_REJECTED = "pending", "approved", "rejected"
from app.services.file_holders import NO_PENDING as _NO_PENDING   # FG-588 condition 2


class RetireRequestBody(BaseModel):
    reason: Optional[str] = None


def _approver_only(user: dict) -> None:
    from app.services.media_policy import RETIRE_APPROVER_ROLES
    if user.get("role") not in RETIRE_APPROVER_ROLES:
        raise lifecycle.refuse(403, "OWNER_APPROVAL_REQUIRED",
                               "Само собственикът одобрява премахване на използван файл")


def _request_view(req: dict, user: dict) -> dict:
    from app.services.file_holders import redact
    out = {k: v for k, v in req.items() if k not in ("_id", "uses")}
    out.update(redact(req.get("uses") or [], user))
    return out


@router.post("/media/{media_id}/retire-request", status_code=201)
async def request_media_retire(media_id: str, data: RetireRequestBody,
                               user: dict = Depends(get_current_user),
                               idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    from app.services.file_holders import uses_version
    from app.services.media_policy import RETIRE_REQUEST_ROLES
    tenant = _tenant(user)
    org_id = user["org_id"]
    key = lifecycle.require_key(idempotency_key)
    why = lifecycle.require_reason(data.reason)
    if user.get("role") not in RETIRE_REQUEST_ROLES:
        raise lifecycle.refuse(403, "RETIRE_REQUEST_NOT_ALLOWED",
                               "Заявка за премахване на използван файл подава администратор")

    async def work(session):
        media = await tenant.media_files.find_one({"id": media_id, "org_id": org_id},
                                                  {"_id": 0}, session=session)
        if not media:
            raise HTTPException(status_code=404, detail="Media file not found")
        if media.get("status") == MEDIA_RETIRED:
            raise lifecycle.refuse(409, "MEDIA_ALREADY_RETIRED", "Файлът вече е скрит")
        uses = await _media_usages(tenant, org_id, media, session=session)
        if not uses:
            raise lifecycle.refuse(409, "MEDIA_NOT_IN_USE",
                                   "Файлът не се използва — премахва се директно (DELETE)")
        if media.get("pending_holders"):
            # FG-588: a movement is being written with this file — no request until it settles
            raise _in_use(user, media_id, uses)
        rid = str(uuid.uuid4())
        now = lifecycle.now_iso()
        res = await tenant.media_files.update_one(
            {"id": media_id, "org_id": org_id, "status": {"$ne": MEDIA_RETIRED},
             "retire_request_pending": None, "ref_version": media.get("ref_version"),
             "$and": [_NO_PENDING]},
            {"$set": {"retire_request_pending": rid}}, session=session)
        if res.matched_count != 1:
            raise lifecycle.refuse(409, "RETIRE_REQUEST_PENDING", "Вече има чакаща заявка")
        req = {"id": rid, "org_id": org_id, "media_id": media_id, "reason": why,
               "status": REQ_PENDING, "uses": uses, "uses_version": uses_version(uses),
               "ref_version": media.get("ref_version"), "requested_by": user["id"],
               "requested_at": now, "decided_by": None, "decided_at": None,
               "decision_reason": None, "interim_until": "W0-07"}
        await tenant.media_retire_requests.insert_one(dict(req), session=session)
        await lifecycle.audit(session, user, action="media.file.retire_request",
                              entity_type="media_file", entity_id=media_id, reason=why,
                              key=key, source_flow="FLOW-029",
                              diff={"request_id": rid, "uses": uses,
                                    "uses_version": req["uses_version"]})
        return _request_view(req, user)

    return await lifecycle.keyed_transaction(user, key, "media.file.retire_request",
                                             {"media_id": media_id, "reason": why}, work)


async def _decide(request_id: str, user: dict, approve: bool, reason: Optional[str],
                  idempotency_key: Optional[str]) -> dict:
    from app.services.file_holders import uses_version
    tenant = _tenant(user)
    org_id = user["org_id"]
    key = lifecycle.require_key(idempotency_key)
    _approver_only(user)
    why = lifecycle.require_reason(reason) if not approve or reason is not None else None
    action = "media.file.retire" if approve else "media.file.retire_request.reject"

    async def work(session):
        req = await tenant.media_retire_requests.find_one({"id": request_id, "org_id": org_id},
                                                          {"_id": 0}, session=session)
        if not req:
            raise HTTPException(status_code=404, detail="Retire request not found")
        if req.get("status") != REQ_PENDING:
            raise lifecycle.refuse(409, "RETIRE_REQUEST_DECIDED", "Заявката вече е решена")
        if approve and req.get("requested_by") == user["id"]:
            # the second-person check: whoever asked does not approve
            raise lifecycle.refuse(403, "SELF_APPROVAL_FORBIDDEN",
                                   "Заявителят не може да одобри собствената си заявка")
        media_id = req["media_id"]
        media = await tenant.media_files.find_one({"id": media_id, "org_id": org_id},
                                                  {"_id": 0}, session=session) or {}
        now = lifecycle.now_iso()
        uses = None
        if approve:
            # FG-577: the approval is for EXACTLY the holders the request named
            uses = await _media_usages(tenant, org_id, media, session=session)
            if (uses_version(uses) != req.get("uses_version")
                    or media.get("ref_version") != req.get("ref_version")):
                raise lifecycle.refuse(409, "RETIRE_REQUEST_STALE",
                                       "Записите, които ползват файла, се промениха след заявката")
        res = await tenant.media_retire_requests.update_one(
            {"id": request_id, "org_id": org_id, "status": REQ_PENDING},
            {"$set": {"status": REQ_APPROVED if approve else REQ_REJECTED,
                      "decided_by": user["id"], "decided_at": now, "decision_reason": why}},
            session=session)
        if res.matched_count != 1:
            raise lifecycle.refuse(409, "RETIRE_REQUEST_DECIDED", "Заявката вече е решена")
        if approve:
            res = await tenant.media_files.update_one(
                {"id": media_id, "org_id": org_id, "status": {"$ne": MEDIA_RETIRED},
                 "retire_request_pending": request_id, "ref_version": req.get("ref_version"),
                 "$and": [_NO_PENDING]},
                {"$set": {"status": MEDIA_RETIRED, "retired_reason": req.get("reason"),
                          "retired_at": now, "retired_by": req.get("requested_by"),
                          "retired_in_use": True, "retired_uses": uses,
                          "retire_request_id": request_id, "retire_approved_by": user["id"],
                          "retire_request_pending": None}}, session=session)
            if res.matched_count != 1:
                raise lifecycle.refuse(409, "MEDIA_CHANGED", "Файлът току-що се промени")
            diff = {"before": {"status": media.get("status") or "active"},
                    "after": {"status": MEDIA_RETIRED}, "in_use": True, "uses": uses,
                    "uses_version": req.get("uses_version"),
                    "request_id": request_id, "requested_by": req.get("requested_by"),
                    "approved_by": user["id"], "stored_filename": media.get("stored_filename")}
            reason_out = req.get("reason")
        else:
            await tenant.media_files.update_one(
                {"id": media_id, "org_id": org_id, "retire_request_pending": request_id},
                {"$set": {"retire_request_pending": None}}, session=session)
            diff = {"request_id": request_id, "requested_by": req.get("requested_by"),
                    "rejected_by": user["id"]}
            reason_out = why
        await lifecycle.audit(session, user, action=action, entity_type="media_file",
                              entity_id=media_id, reason=reason_out, key=key,
                              source_flow="FLOW-029", diff=diff)
        return {"ok": True, "request_id": request_id, "media_id": media_id,
                "status": REQ_APPROVED if approve else REQ_REJECTED}

    return await lifecycle.keyed_transaction(user, key, action,
                                             {"request_id": request_id, "approve": approve,
                                              "reason": why}, work)


@router.post("/media/retire-requests/{request_id}/approve")
async def approve_media_retire(request_id: str, data: RetireRequestBody = Body(None),
                               user: dict = Depends(get_current_user),
                               idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    return await _decide(request_id, user, True, (data.reason if data else None), idempotency_key)


@router.post("/media/retire-requests/{request_id}/reject")
async def reject_media_retire(request_id: str, data: RetireRequestBody = Body(None),
                              user: dict = Depends(get_current_user),
                              idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    return await _decide(request_id, user, False, (data.reason if data else None), idempotency_key)


@router.get("/media-retire-requests")
async def list_media_retire_requests(status: Optional[str] = REQ_PENDING,
                                     user: dict = Depends(get_current_user)):
    if user.get("role") not in ("Owner", "Admin"):
        raise HTTPException(status_code=403, detail="Access denied")
    flt = {"org_id": user["org_id"]}
    if status:
        flt["status"] = status
    rows = await _tenant(user).media_retire_requests.find(flt, {"_id": 0}).sort(
        "requested_at", -1).to_list(200)
    return [_request_view(r, user) for r in rows]


@router.post("/media/{media_id}/pending-holders/{marker_id}/release")
async def release_stale_pending_holder(media_id: str, marker_id: str,
                                       user: dict = Depends(get_current_user),
                                       idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """FG-588 condition 4: an Owner/Admin releases a pending-holder marker that no movement
    followed — only after ``media_policy.PENDING_HOLDER_MIN_AGE_SECONDS`` and a registry
    proof that nothing references the file. Never retires anything; AuditEvent
    ``media.file.pending_holder_release``."""
    from app.services.file_holders import release_stale
    from app.services.media_policy import PENDING_HOLDER_MIN_AGE_SECONDS
    if user.get("role") not in ("Owner", "Admin"):
        raise HTTPException(status_code=403, detail="Access denied")
    key = lifecycle.require_key(idempotency_key)          # FG-598
    return await release_stale(_tenant(user), user["org_id"], media_id, marker_id, actor=user,
                               min_age_seconds=PENDING_HOLDER_MIN_AGE_SECONDS, key=key)
