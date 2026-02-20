"""
Test utilities and helpers for BEG_Work backend tests.

Provides:
- Valid password generation that passes policy
- Test data reset helpers
- Rate limiter reset for deterministic tests
"""
import os
import asyncio
import secrets
import string
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext
from dotenv import load_dotenv

load_dotenv()

# Password context for hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Standard test credentials that pass password policy
VALID_ADMIN_PASSWORD = "AdminTest123!Secure"
VALID_TECH_PASSWORD = "TechTest123!Secure"
VALID_STRONG_PASSWORD = "StrongNew456@Pass"


def generate_valid_password(length: int = 14) -> str:
    """
    Generate a password that passes the password policy:
    - At least 10 characters
    - At least 1 uppercase letter
    - At least 1 lowercase letter
    - At least 1 digit
    - At least 1 special character (!@#$%^&*()_+-=[]{}|;:,.<>?)
    """
    if length < 10:
        length = 10
    
    # Ensure at least one of each required type
    password_chars = [
        secrets.choice(string.ascii_uppercase),  # Uppercase
        secrets.choice(string.ascii_lowercase),  # Lowercase
        secrets.choice(string.digits),           # Digit
        secrets.choice("!@#$%^&*()_+-="),        # Special
    ]
    
    # Fill remaining with mix
    remaining = length - len(password_chars)
    all_chars = string.ascii_letters + string.digits + "!@#$%^&*()_+-="
    password_chars.extend(secrets.choice(all_chars) for _ in range(remaining))
    
    # Shuffle to avoid predictable pattern
    secrets.SystemRandom().shuffle(password_chars)
    
    return ''.join(password_chars)


async def reset_test_passwords():
    """
    Reset all test user passwords to known valid values.
    Call this before tests that depend on specific passwords.
    """
    mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
    db_name = os.environ.get('DB_NAME', 'begwork')
    
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    
    try:
        # Reset admin password
        admin_hash = pwd_context.hash(VALID_ADMIN_PASSWORD)
        await db.users.update_one(
            {"email": "admin@begwork.com"},
            {"$set": {"password_hash": admin_hash}}
        )
        
        # Reset tech users
        tech_hash = pwd_context.hash(VALID_TECH_PASSWORD)
        for email in ["tech@begwork.com", "tech1@begwork.com", "tech2@begwork.com"]:
            await db.users.update_one(
                {"email": email},
                {"$set": {"password_hash": tech_hash}}
            )
    finally:
        client.close()


def reset_test_passwords_sync():
    """Synchronous wrapper for reset_test_passwords()."""
    asyncio.get_event_loop().run_until_complete(reset_test_passwords())


def reset_bootstrap_rate_limiter():
    """
    Reset the platform bootstrap rate limiter.
    Import and call the limiter's reset method.
    """
    try:
        from app.routes.platform import bootstrap_rate_limiter
        bootstrap_rate_limiter.reset()
    except ImportError:
        pass  # Platform module not available


async def ensure_test_users_exist():
    """
    Ensure all required test users exist with correct passwords.
    Creates users if they don't exist.
    """
    mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
    db_name = os.environ.get('DB_NAME', 'begwork')
    
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    
    try:
        # Get admin's org_id
        admin = await db.users.find_one({"email": "admin@begwork.com"})
        if not admin:
            return  # No admin means no org to add users to
        
        org_id = admin.get("org_id")
        admin_hash = pwd_context.hash(VALID_ADMIN_PASSWORD)
        
        # Update admin password
        await db.users.update_one(
            {"email": "admin@begwork.com"},
            {"$set": {"password_hash": admin_hash}}
        )
        
        # Create/update tech users
        tech_hash = pwd_context.hash(VALID_TECH_PASSWORD)
        from datetime import datetime, timezone
        import uuid
        
        for email in ["tech@begwork.com", "tech1@begwork.com", "tech2@begwork.com"]:
            existing = await db.users.find_one({"email": email})
            if not existing:
                await db.users.insert_one({
                    "id": str(uuid.uuid4()),
                    "org_id": org_id,
                    "email": email,
                    "password_hash": tech_hash,
                    "first_name": "Tech",
                    "last_name": email.split("@")[0].replace("tech", "User"),
                    "role": "Technician",
                    "phone": "",
                    "is_active": True,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
            else:
                await db.users.update_one(
                    {"email": email},
                    {"$set": {
                        "password_hash": tech_hash,
                        "org_id": org_id,
                        "is_active": True
                    }}
                )
    finally:
        client.close()


def ensure_test_users_exist_sync():
    """Synchronous wrapper for ensure_test_users_exist()."""
    asyncio.get_event_loop().run_until_complete(ensure_test_users_exist())
