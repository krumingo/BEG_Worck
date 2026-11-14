#!/usr/bin/env python3
"""LAB-02 bot scenario — seed a throw-away LOCAL database for the screen run.

Writes only into ``--db`` on a local MongoDB (refuses anything else and any
``begwork*`` name). Synthetic data: one tenant, Admin / Owner / Accountant /
SiteManager of project P / Technician-worker on akord, one SMR package "Шпакловка"
(м2) and one submitted+approved report line of the akord worker with 120 м2 entered.

    PYTHONPATH=backend python docs/evidence/LAB-02/bot/seed_lab02_bot.py \
        --mongo-url mongodb://127.0.0.1:27017 --db lab02_bot --password-env LAB02_BOT_PW
"""
import argparse
import asyncio
import os
import sys
from urllib.parse import urlparse

ORG = "ORG-LAB02-BOT"
DAY = "2026-11-02"


async def main(url: str, name: str, password: str):
    from motor.motor_asyncio import AsyncIOMotorClient
    from app.deps.auth import hash_password
    from app.tenancy import project_team
    from app.tenancy.data_access import TenantData

    client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=5000)
    await client.drop_database(name)
    db = client[name]
    pw = hash_password(password)
    await db.organizations.insert_one({"id": ORG, "name": "LAB-02 бот", "subscription_status": "active"})
    users = [("bot-admin", "Admin", "Админ"), ("bot-owner", "Owner", "Собственик"),
             ("bot-acct", "Accountant", "Счетоводител"), ("bot-sm", "SiteManager", "Ръководител"),
             ("bot-worker", "Technician", "Иван")]
    for uid, role, first in users:
        await db.users.insert_one({"id": uid, "org_id": ORG, "role": role, "is_active": True,
                                   "email": f"{uid}@lab02.example", "password_hash": pw,
                                   "first_name": first, "last_name": "Бот", "synthetic_fixture": "lab-02"})
    await db.employee_profiles.insert_one({"org_id": ORG, "user_id": "bot-worker", "pay_type": "Akord",
                                           "hourly_rate": 15})
    await db.projects.insert_one({"id": "P", "org_id": ORG, "name": "Обект Витоша", "code": "VIT",
                                  "status": "Active"})
    tenant = TenantData.for_resolved_org(db, ORG)
    await project_team.add_member(tenant, member_id="m-sm", project_id="P", user_id="bot-sm",
                                  role_in_project=project_team.ROLE_SITE_MANAGER)
    await project_team.add_member(tenant, member_id="m-w", project_id="P", user_id="bot-worker",
                                  role_in_project="Worker")
    await db.execution_packages.insert_one({"id": "pkg-sh", "org_id": ORG, "project_id": "P",
                                            "activity_name": "Шпакловка", "unit": "м2", "qty": 400})
    await db.employee_daily_reports.insert_one({
        "id": "R-AK", "org_id": ORG, "worker_id": "bot-worker", "worker_name": "Иван Бот",
        "submitted_by": "bot-worker", "date": DAY, "hours": 8, "project_id": "P",
        "smr_type": "Шпакловка", "status": "APPROVED", "quantity": 120, "payroll_status": "none",
        "created_at": DAY + "T17:00:00"})
    print(f"seeded {name}: users {[u[0] for u in users]}")
    client.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mongo-url", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--password-env", default="LAB02_BOT_PW")
    a = ap.parse_args()
    host = urlparse(a.mongo_url).hostname
    if not a.mongo_url.startswith("mongodb://") or host not in ("127.0.0.1", "localhost", "::1"):
        sys.exit("refused: only a local mongodb:// server")
    if a.db.lower().startswith("begwork"):
        sys.exit("refused: production-like database name")
    pw = os.environ.get(a.password_env)
    if not pw:
        sys.exit(f"refused: set ${a.password_env}")
    asyncio.run(main(a.mongo_url, a.db, pw))
