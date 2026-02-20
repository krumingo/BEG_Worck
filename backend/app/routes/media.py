"""
Routes - Media (Photos) Endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from typing import Optional
from datetime import datetime, timezone
import uuid
from pathlib import Path

from app.db import db
from app.deps.auth import get_current_user
from app.deps.media_acl import enforce_media_access, enforce_context_access, MEDIA_CONTEXT_TYPES, check_media_access

router = APIRouter(tags=["Media"])

# ── Constants ──────────────────────────────────────────────────────

ALLOWED_MEDIA_TYPES = ["image/jpeg", "image/png", "image/webp", "image/heic"]
MAX_MEDIA_SIZE_MB = 10


# ── Pydantic Models ────────────────────────────────────────────────

from pydantic import BaseModel

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
    org_id = user["org_id"]
    
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
    
    await db.media_files.insert_one(media)
    
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
    org_id = user["org_id"]
    
    # Validate context type
    if data.context_type not in MEDIA_CONTEXT_TYPES:
        raise HTTPException(status_code=400, detail={
            "error_code": "INVALID_CONTEXT_TYPE",
            "message": f"Invalid context type. Allowed: {MEDIA_CONTEXT_TYPES}",
        })
    
    # Find media file
    media = await db.media_files.find_one({"id": data.media_id, "org_id": org_id}, {"_id": 0})
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
    
    # ── TARGET CONTEXT ACCESS CHECK ────────────────────────────────────
    # Verify user has access to the target context before allowing link
    # This prevents linking media to contexts the user doesn't have access to
    await enforce_context_access(user, data.context_type, data.context_id)
    
    # Update media with context
    now = datetime.now(timezone.utc).isoformat()
    await db.media_files.update_one(
        {"id": data.media_id},
        {"$set": {
            "context_type": data.context_type,
            "context_id": data.context_id,
            "linked_at": now,
        }}
    )
    
    return {
        "id": data.media_id,
        "context_type": data.context_type,
        "context_id": data.context_id,
        "linked": True,
    }


@router.get("/media/{media_id}")
async def get_media(media_id: str, user: dict = Depends(get_current_user)):
    """Get media file metadata"""
    org_id = user["org_id"]
    
    media = await db.media_files.find_one({"id": media_id, "org_id": org_id}, {"_id": 0})
    if not media:
        raise HTTPException(status_code=404, detail="Media file not found")
    
    # ACL check: enforces org isolation, owner/admin access, and context-based rules
    await enforce_media_access(user, media, action="meta")
    
    # Enrich with owner name (handle legacy records with missing owner_user_id)
    owner_user_id = media.get("owner_user_id")
    if owner_user_id:
        owner = await db.users.find_one({"id": owner_user_id}, {"_id": 0, "first_name": 1, "last_name": 1})
        media["owner_user_name"] = f"{owner.get('first_name', '')} {owner.get('last_name', '')}".strip() if owner else ""
    else:
        media["owner_user_name"] = "(unknown)"
    
    return media


@router.get("/media/file/{filename}")
async def serve_media_file(filename: str, user: dict = Depends(get_current_user)):
    """Serve media file content"""
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
    media = await db.media_files.find_one({"stored_filename": filename, "org_id": user["org_id"]}, {"_id": 0})
    if not media:
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
    from app.shared import check_media_access
    
    org_id = user["org_id"]
    user_id = user["id"]
    user_role = user["role"]
    
    # ── Build base query ───────────────────────────────────────────────
    query = {"org_id": org_id}
    
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
    media_list = await db.media_files.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    
    # ── Post-filter for ACL compliance ─────────────────────────────────
    # Admin/Owner already have full access, skip filtering
    if user_role in ["Admin", "Owner"]:
        return media_list[:100]  # Limit response size
    
    # For other roles, verify access to each media item
    filtered_list = []
    for media in media_list:
        allowed, _ = await check_media_access(user, media, action="meta")
        if allowed:
            filtered_list.append(media)
        # Stop at 100 results for performance
        if len(filtered_list) >= 100:
            break
    
    return filtered_list


@router.delete("/media/{media_id}")
async def delete_media(media_id: str, user: dict = Depends(get_current_user)):
    """
    Delete a media file.
    
    ACL Rules:
    - Must be in same org
    - Only owner or Admin/Owner can delete
    """
    org_id = user["org_id"]
    
    # Find media with org_id check (prevents cross-org access)
    media = await db.media_files.find_one({"id": media_id, "org_id": org_id}, {"_id": 0})
    if not media:
        raise HTTPException(status_code=404, detail="Media file not found")
    
    # ACL check for delete action
    await enforce_media_access(user, media, action="delete")
    
    # Delete the actual file
    stored_filename = media.get("stored_filename")
    if stored_filename:
        file_path = Path("/app/backend/uploads") / stored_filename
        if file_path.exists():
            try:
                file_path.unlink()
            except OSError:
                pass  # File may have been deleted externally
    
    # Delete from database
    await db.media_files.delete_one({"id": media_id})
    
    return {"ok": True, "deleted": media_id}
