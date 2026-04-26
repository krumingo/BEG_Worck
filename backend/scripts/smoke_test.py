"""
BEG_Work Smoke Test — automated production readiness check.

Usage:
  python scripts/smoke_test.py
  
Exit code 0 = PASS, 1 = FAIL (critical issues found).
"""
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from motor.motor_asyncio import AsyncIOMotorClient


async def smoke_test():
    results = []
    db_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "begwork")
    client = AsyncIOMotorClient(db_url)
    db = client[db_name]

    # 1. ENV Variables
    jwt_secret = os.environ.get("JWT_SECRET", "")
    if jwt_secret and jwt_secret != "dev-secret-key-NOT-FOR-PRODUCTION":
        results.append(("pass", "JWT_SECRET", "Зададен правилно"))
    else:
        results.append(("fail", "JWT_SECRET", "Липсва или е dev fallback!"))

    env = os.environ.get("ENV", "development")
    results.append(("pass" if env == "production" else "warn", "ENV", f"={env}"))

    cors = os.environ.get("CORS_ORIGINS", "*")
    results.append(("pass" if cors != "*" else "warn", "CORS_ORIGINS", f"={cors}"))

    # 2. Database connectivity
    try:
        await db.command("ping")
        results.append(("pass", "MongoDB", f"Свързан: {db_url}/{db_name}"))
    except Exception as e:
        results.append(("fail", "MongoDB", f"Грешка: {e}"))

    # 3. Collections check
    collections = await db.list_collection_names()
    required = [
        "users", "organizations", "projects", "employee_profiles",
        "employee_daily_reports", "work_sessions", "pay_runs", "invoices",
        "offers", "financial_accounts",
    ]
    for col in required:
        if col in collections:
            count = await db[col].count_documents({})
            results.append(("pass", f"  {col}", f"{count} документа"))
        else:
            results.append(("fail", f"  {col}", "ЛИПСВА!"))

    # 4. Index check
    for col_name in ["users", "projects", "pay_runs"]:
        try:
            indexes = await db[col_name].index_information()
            idx_count = len(indexes) - 1  # minus _id
            results.append(("pass" if idx_count > 0 else "warn", f"  {col_name} indexes", f"{idx_count} индекса"))
        except Exception:
            results.append(("warn", f"  {col_name} indexes", "Не може да се провери"))

    # 5. Test accounts check
    test_users = await db.users.count_documents({"email": {"$regex": "^test_"}})
    results.append((
        "warn" if test_users > 0 else "pass",
        "Тестови акаунти",
        f"{test_users} намерени — изтрийте преди production!" if test_users > 0 else "Чисто",
    ))

    # 6. Active organizations
    org_count = await db.organizations.count_documents({})
    results.append(("pass", "Организации", f"{org_count} общо"))

    # Print results
    ICONS = {"pass": "+", "fail": "X", "warn": "!"}
    print()
    print("=" * 60)
    print("  BEG_Work SMOKE TEST")
    print("=" * 60)

    has_critical = False
    for level, label, detail in results:
        icon = ICONS.get(level, "?")
        print(f"  [{icon}]  {label:<30} {detail}")
        if level == "fail":
            has_critical = True

    print("=" * 60)
    if has_critical:
        print("  [X]  FAIL — има критични проблеми!")
    else:
        print("  [+]  PASS — системата е готова!")
    print()
    return not has_critical


if __name__ == "__main__":
    ok = asyncio.run(smoke_test())
    sys.exit(0 if ok else 1)
