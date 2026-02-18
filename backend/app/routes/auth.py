"""
Authentication routes - /api/auth/*
"""
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timezone

from app.db import db
from app.deps.auth import (
    verify_password, create_token, get_current_user, hash_password
)
from app.models.core import LoginRequest

router = APIRouter(prefix="/auth", tags=["auth"])

async def log_audit(org_id: str, user_id: str, user_email: str, action: str, entity_type: str, entity_id: str = None, changes: dict = None):
    """Log an audit entry."""
    import uuid
    entry = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "user_id": user_id,
        "user_email": user_email,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "changes": changes,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await db.audit_logs.insert_one(entry)

@router.post("/login")
async def login(req: LoginRequest):
    user = await db.users.find_one({"email": req.email}, {"_id": 0})
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account disabled")
    token = create_token({"user_id": user["id"], "org_id": user["org_id"], "role": user["role"]})
    await log_audit(user["org_id"], user["id"], user["email"], "login", "auth")
    return {"token": token, "user": {k: v for k, v in user.items() if k != "password_hash"}}

@router.get("/me")
async def get_me(user: dict = Depends(get_current_user)):
    return {k: v for k, v in user.items() if k != "password_hash"}
