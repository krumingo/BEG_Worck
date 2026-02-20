"""
Authentication and authorization dependencies.
"""
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from passlib.context import CryptContext
from datetime import datetime, timezone, timedelta
from typing import List
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment
_root = Path(__file__).parent.parent
load_dotenv(_root / '.env')

from app.db import db

JWT_SECRET = os.environ.get('JWT_SECRET', 'dev-secret-key')
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

def hash_password(pw: str) -> str:
    return pwd_context.hash(pw)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_token(data: dict) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS)
    return jwt.encode({**data, "exp": expire}, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        user = await db.users.find_one({"id": user_id}, {"_id": 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        if not user.get("is_active", True):
            raise HTTPException(status_code=403, detail="Account disabled")
        return user
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def require_admin(user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

async def get_user_project_ids(user_id: str) -> List[str]:
    members = await db.project_team.find({"user_id": user_id, "active": True}, {"_id": 0, "project_id": 1}).to_list(1000)
    return [m["project_id"] for m in members]

async def can_access_project(user: dict, project_id: str) -> bool:
    if user["role"] in ["Admin", "Owner"]:
        return True
    member = await db.project_team.find_one({"project_id": project_id, "user_id": user["id"], "active": True})
    return member is not None

async def can_manage_project(user: dict, project_id: str) -> bool:
    if user["role"] in ["Admin", "Owner"]:
        return True
    if user["role"] == "SiteManager":
        member = await db.project_team.find_one({"project_id": project_id, "user_id": user["id"], "active": True, "role_in_project": "SiteManager"})
        return member is not None
    return False


async def require_platform_admin(user: dict = Depends(get_current_user)):
    """
    Require platform admin access for system management routes.
    
    Platform admins can access:
    - /api/billing/* (except public endpoints)
    - /api/mobile-settings/*
    - /api/modules/*
    - /api/audit-logs
    
    Regular org Admin/Owner users do NOT have platform admin access by default.
    The is_platform_admin flag must be explicitly set to True.
    """
    if not user.get("is_platform_admin", False):
        raise HTTPException(
            status_code=403, 
            detail={
                "error_code": "PLATFORM_ADMIN_REQUIRED",
                "message": "Platform administrator access required"
            }
        )
    return user
