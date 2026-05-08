"""
Pytest configuration and shared fixtures for BEG_Work backend tests.

This module ensures tests are DB_NAME independent by seeding minimal
required data before any tests run.

IMPORTANT: Uses valid passwords that pass the password policy.
"""
import os
import pytest
import asyncio
from datetime import datetime, timezone, timedelta
import uuid

# Import test utilities for valid passwords
from tests.test_utils import (
    VALID_ADMIN_PASSWORD, 
    VALID_TECH_PASSWORD,
    reset_bootstrap_rate_limiter
)

# Set BASE_URL environment variable for all tests
def pytest_configure(config):
    """Set up environment variables before tests run."""
    # Try to read from frontend/.env if not already set
    if not os.environ.get('REACT_APP_BACKEND_URL'):
        frontend_env_path = os.path.join(os.path.dirname(__file__), '../../frontend/.env')
        if os.path.exists(frontend_env_path):
            with open(frontend_env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('REACT_APP_BACKEND_URL='):
                        value = line.split('=', 1)[1].strip()
                        os.environ['REACT_APP_BACKEND_URL'] = value
                        break
    
    # Fallback to localhost if still not set
    if not os.environ.get('REACT_APP_BACKEND_URL'):
        os.environ['REACT_APP_BACKEND_URL'] = 'http://localhost:8001'
    
    # Reset rate limiter at start of test session
    reset_bootstrap_rate_limiter()


@pytest.fixture(scope="session")
def base_url():
    """Provide the base URL for API tests."""
    return os.environ.get('REACT_APP_BACKEND_URL', 'http://localhost:8001').rstrip('/')


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE-INDEPENDENT SEED FIXTURE
# ══════════════════════════════════════════════════════════════════════════════

async def _ensure_test_seed_data():
    """
    Ensure minimal seed data exists for tests to run.
    This is idempotent - safe to call multiple times.
    
    IMPORTANT: Uses VALID_ADMIN_PASSWORD and VALID_TECH_PASSWORD which pass policy.
    """
    from motor.motor_asyncio import AsyncIOMotorClient
    from passlib.context import CryptContext
    from dotenv import load_dotenv
    
    load_dotenv()
    
    mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
    db_name = os.environ.get('DB_NAME', 'test_database')
    
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    
    # Module definitions
    MODULES = {
        "M0": {"name": "Base", "description": "Core features"},
        "M1": {"name": "Projects", "description": "Project management"},
        "M2": {"name": "Offers", "description": "Offers and quotes"},
        "M3": {"name": "HR", "description": "Human resources"},
        "M4": {"name": "Payroll", "description": "Payroll management"},
        "M5": {"name": "Finance", "description": "Financial management"},
        "M6": {"name": "Inventory", "description": "Inventory tracking"},
        "M7": {"name": "Assets", "description": "Asset management"},
        "M8": {"name": "Reports", "description": "Reporting"},
        "M9": {"name": "Advanced", "description": "Advanced features"},
        "M10": {"name": "Billing", "description": "Billing management"},
    }
    
    now = datetime.now(timezone.utc).isoformat()
    
    # Check if seed data already exists
    existing_admin = await db.users.find_one({"email": "admin@begwork.com"})
    
    if existing_admin:
        org_id = existing_admin.get("org_id")
        print(f"\n[conftest] Seed data exists, resetting passwords to valid values...")
        
        # ALWAYS reset admin password to valid value
        await db.users.update_one(
            {"email": "admin@begwork.com"},
            {"$set": {
                "password_hash": pwd_context.hash(VALID_ADMIN_PASSWORD),
                "is_platform_admin": True,
                "is_active": True
            }}
        )
        
        # Ensure tech users exist with valid passwords
        for tech_email in ["tech@begwork.com", "tech1@begwork.com", "tech2@begwork.com"]:
            existing_tech = await db.users.find_one({"email": tech_email})
            if not existing_tech:
                await db.users.insert_one({
                    "id": str(uuid.uuid4()),
                    "org_id": org_id,
                    "email": tech_email,
                    "password_hash": pwd_context.hash(VALID_TECH_PASSWORD),
                    "first_name": "Tech",
                    "last_name": tech_email.split("@")[0].capitalize(),
                    "role": "Technician",
                    "phone": "",
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                })
                print(f"[conftest] Created {tech_email}")
            else:
                # Update to valid password
                await db.users.update_one(
                    {"email": tech_email},
                    {"$set": {
                        "org_id": org_id,
                        "password_hash": pwd_context.hash(VALID_TECH_PASSWORD),
                        "is_active": True
                    }}
                )
        
        client.close()
        return
    
    print(f"\n[conftest] Seeding test data into {db_name}...")
    
    org_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    expires = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()
    
    # Create organization
    await db.organizations.insert_one({
        "id": org_id,
        "name": "BEG_Work Demo",
        "slug": "begwork-demo",
        "address": "",
        "phone": "",
        "email": "admin@begwork.com",
        "logo_url": "",
        "subscription_plan": "enterprise",
        "subscription_status": "active",
        "subscription_expires_at": expires,
        "created_at": now,
        "updated_at": now,
    })
    
    # Create admin user with VALID password
    await db.users.insert_one({
        "id": user_id,
        "org_id": org_id,
        "email": "admin@begwork.com",
        "password_hash": pwd_context.hash(VALID_ADMIN_PASSWORD),
        "first_name": "System",
        "last_name": "Admin",
        "role": "Admin",
        "phone": "",
        "is_active": True,
        "is_platform_admin": True,
        "created_at": now,
        "updated_at": now,
    })
    
    # Create technician users with VALID passwords
    for tech_email in ["tech@begwork.com", "tech1@begwork.com", "tech2@begwork.com"]:
        await db.users.insert_one({
            "id": str(uuid.uuid4()),
            "org_id": org_id,
            "email": tech_email,
            "password_hash": pwd_context.hash(VALID_TECH_PASSWORD),
            "first_name": "Tech",
            "last_name": tech_email.split("@")[0].capitalize(),
            "role": "Technician",
            "phone": "",
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        })
    
    # Create feature flags
    for code, info in MODULES.items():
        await db.feature_flags.insert_one({
            "id": str(uuid.uuid4()),
            "org_id": org_id,
            "module_code": code,
            "module_name": info["name"],
            "description": info["description"],
            "enabled": True,
            "updated_at": now,
            "updated_by": user_id,
        })
    
    # Create subscription
    await db.subscriptions.insert_one({
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "plan": "enterprise",
        "plan_id": "enterprise",
        "status": "active",
        "started_at": now,
        "expires_at": expires,
        "payment_method": "test_seed",
        "amount": 0,
        "currency": "EUR",
        "created_at": now,
    })
    
    print(f"[conftest] Seed data created with valid passwords in {db_name}")
    client.close()


@pytest.fixture(scope="session", autouse=True)
def ensure_seed_data():
    """
    Session-scoped fixture that ensures seed data exists before any tests run.
    This runs automatically (autouse=True) at the start of the test session.
    """
    asyncio.get_event_loop().run_until_complete(_ensure_test_seed_data())
    # Reset rate limiter after seed
    reset_bootstrap_rate_limiter()
