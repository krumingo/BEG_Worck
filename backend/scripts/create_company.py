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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load .env from backend root
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def create_company(name, admin_email, admin_password, db_url=None):
    client = AsyncIOMotorClient(db_url or os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db = client[os.environ.get("DB_NAME", "begwork")]
    system_db = client[os.environ.get("BEG_SYSTEM_DB", "begwork_system")]

    # 1-3. W0-03E-A2B: the canonical tenant onboarding path (organization, admin
    # user, Tenant Registry record, membership and assignment, one tenant id
    # generated server-side). The same path POST /billing/signup uses.
    from app.tenancy.onboarding import OnboardingRefused, onboard_tenant
    try:
        created = await onboard_tenant(
            db, system_db, org_name=name, owner_email=admin_email,
            owner_password_hash=pwd_context.hash(admin_password), owner_first_name="Admin",
            owner_last_name=name.split()[0], owner_role="Admin",
            organization_extra={"plan": "pro", "modules": {"m0": True, "m1": True, "m2": True,
                                                           "m3": True, "m4": True, "m5": True},
                                "max_users": 50, "max_projects": 100},
            plan="pro")
    except OnboardingRefused as exc:
        print(f"ГРЕШКА: {exc}")
        return False
    org_id = created["tenant"]["id"]
    user_id = created["owner"]["id"]
    now = datetime.now(timezone.utc).isoformat()

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
