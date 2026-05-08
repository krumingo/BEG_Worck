"""
Create a new company (organization) in BEG_Work.

Usage:
  python scripts/create_company.py --name "Фирма ООД" --admin-email "admin@firma.bg" --admin-password "SecurePass123!"
"""
import asyncio
import argparse
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timezone
from passlib.context import CryptContext
import os
import uuid
import sys
from pathlib import Path

# Load .env from backend root
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def create_company(name, admin_email, admin_password, db_url=None):
    client = AsyncIOMotorClient(db_url or os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db = client[os.environ.get("DB_NAME", "begwork")]

    # 1. Check for duplicate email
    existing = await db.users.find_one({"email": admin_email})
    if existing:
        print(f"ГРЕШКА: Email {admin_email} вече съществува!")
        return False

    # 2. Create organization
    org_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    org = {
        "id": org_id,
        "name": name,
        "plan": "pro",
        "modules": {"m0": True, "m1": True, "m2": True, "m3": True, "m4": True, "m5": True},
        "max_users": 50,
        "max_projects": 100,
        "created_at": now,
    }
    await db.organizations.insert_one(org)

    # 3. Create admin user
    user_id = str(uuid.uuid4())
    user = {
        "id": user_id,
        "org_id": org_id,
        "email": admin_email,
        "password_hash": pwd_context.hash(admin_password),
        "first_name": "Admin",
        "last_name": name.split()[0],
        "role": "Admin",
        "is_active": True,
        "created_at": now,
    }
    await db.users.insert_one(user)

    # 4. Create employee profile
    profile = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "user_id": user_id,
        "position": "Управител",
        "pay_type": "Monthly",
        "active": True,
        "created_at": now,
    }
    await db.employee_profiles.insert_one(profile)

    # 5. Create default financial accounts
    for acc_name, acc_type in [("Каса", "cash"), ("Банкова сметка", "bank")]:
        await db.financial_accounts.insert_one({
            "id": str(uuid.uuid4()),
            "org_id": org_id,
            "name": acc_name,
            "type": acc_type,
            "currency": "EUR",
            "balance": 0,
            "active": True,
            "created_at": now,
        })

    print(f"Фирма '{name}' създадена успешно!")
    print(f"   Org ID: {org_id}")
    print(f"   Admin: {admin_email}")
    print(f"   Login URL: /login")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Създай нова фирма в BEG_Work")
    parser.add_argument("--name", required=True, help="Име на фирмата")
    parser.add_argument("--admin-email", required=True, help="Email на администратора")
    parser.add_argument("--admin-password", required=True, help="Парола на администратора")
    args = parser.parse_args()
    asyncio.run(create_company(args.name, args.admin_email, args.admin_password))
