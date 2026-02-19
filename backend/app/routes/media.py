"""
Routes - Media (Photos) Endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from typing import Optional
from datetime import datetime, timezone
import uuid
import os

from app.shared import db, get_current_user

router = APIRouter(tags=["Media"])

# ── Constants ──────────────────────────────────────────────────────

ALLOWED_MEDIA_TYPES = ["image/jpeg", "image/png", "image/webp", "image/heic"]
MAX_MEDIA_SIZE_MB = 10
MEDIA_CONTEXT_TYPES = ["workReport", "delivery", "machine", "attendance", "profile", "message"]


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
    
    # Validate file type
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
    upload_dir = "/app/backend/uploads"
    os.makedirs(upload_dir, exist_ok=True)
    file_path = f"{upload_dir}/{filename}"
    
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
    
    # Check ownership or admin
    if media["owner_user_id"] != user["id"] and user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Not authorized to link this media")
    
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
    
    # Check access: owner, admin, or context-based access
    is_owner = media["owner_user_id"] == user["id"]
    is_admin = user["role"] in ["Admin", "Owner"]
    
    # TODO: Add context-based access check (e.g., if user has access to the work report)
    has_context_access = True  # Placeholder
    
    if not (is_owner or is_admin or has_context_access):
        raise HTTPException(status_code=403, detail="Not authorized to view this media")
    
    # Enrich with owner name
    owner = await db.users.find_one({"id": media["owner_user_id"]}, {"_id": 0, "first_name": 1, "last_name": 1})
    media["owner_user_name"] = f"{owner.get('first_name', '')} {owner.get('last_name', '')}".strip() if owner else ""
    
    return media


@router.get("/media/file/{filename}")
async def serve_media_file(filename: str, user: dict = Depends(get_current_user)):
    """Serve media file content"""
    file_path = f"/app/backend/uploads/{filename}"
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    # Get media metadata to check access
    media = await db.media_files.find_one({"stored_filename": filename, "org_id": user["org_id"]}, {"_id": 0})
    if not media:
        raise HTTPException(status_code=404, detail="Media not found or access denied")
    
    return FileResponse(file_path, media_type=media.get("content_type", "application/octet-stream"))


@router.get("/media")
async def list_media(
    context_type: Optional[str] = None,
    context_id: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    """List media files for the organization, optionally filtered by context"""
    org_id = user["org_id"]
    
    query = {"org_id": org_id}
    if context_type:
        query["context_type"] = context_type
    if context_id:
        query["context_id"] = context_id
    
    # Non-admin users only see their own media unless filtering by context
    if user["role"] not in ["Admin", "Owner", "SiteManager"] and not (context_type and context_id):
        query["owner_user_id"] = user["id"]
    
    media_list = await db.media_files.find(query, {"_id": 0}).sort("created_at", -1).to_list(100)
    
    return media_list
