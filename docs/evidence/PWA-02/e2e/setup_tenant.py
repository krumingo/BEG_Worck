"""PWA-02 evidence — a disposable tenant for the browser run (LOCAL replica set only).

Seeds the ST-01 synthetic tenants A and B into two fresh scratch databases, puts the
technician on project P1's team, switches the offline_queue flag ON for tenant A only and
writes the run's facts (database names, logins, project) as JSON.

    PYTHONPATH=backend python docs/evidence/PWA-02/e2e/setup_tenant.py \\
        --mongo-url 'mongodb://127.0.0.1:27019/?directConnection=true' --out run.json
"""
import argparse
import asyncio
import importlib.util
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
BACKEND = REPO / "backend"
PASSWORD = "PWA02-E2E-Pass-2026!"


def _pm01():
    spec = importlib.util.spec_from_file_location("pwa02_e2e_pm01", BACKEND / "tests" / "test_pm_01_permission_matrix.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


async def main(mongo_url: str, out: Path) -> None:
    pm = _pm01()
    pm._check_local(mongo_url)
    suffix = uuid.uuid4().hex[:10]
    op_name, sys_name = "pwa02e2e_op_" + suffix, "pwa02e2e_sys_" + suffix
    client = await pm._make_client(mongo_url)
    op_db, sys_db = client[op_name], client[sys_name]
    report = await pm._load_seed().seed(op_db, sys_db, PASSWORD)
    now = datetime.now(timezone.utc).isoformat()
    tenants = {t["key"]: t for t in report["tenants"]}
    A = tenants["A"]
    users = {u["key"]: u for u in A["users"]}
    tech = users["technician"]
    await op_db.projects.update_one({"id": A["project_id"]}, {"$set": {"status": "Active"}})
    await op_db.project_team.insert_one({
        "id": str(uuid.uuid4()), "org_id": A["tenant_id"], "project_id": A["project_id"],
        "user_id": tech["id"], "role_in_project": "Technician", "active": True,
        "created_at": now, "updated_at": now})
    await op_db.feature_flags.update_one(
        {"org_id": A["tenant_id"], "module_code": "offline_queue"},
        {"$set": {"enabled": True, "updated_at": now, "updated_by": "e2e-setup"}}, upsert=True)
    for name in ("audit_events", "audit_logs", "media_files"):
        if name not in await op_db.list_collection_names():
            await op_db.create_collection(name)
    out.write_text(json.dumps({
        "mongo_url": mongo_url, "db_name": op_name, "system_db": sys_name, "password": PASSWORD,
        "tenant_id": A["tenant_id"], "project_id": A["project_id"],
        "technician": {"email": tech["email"], "id": tech["id"]},
        "owner": {"email": users["owner"]["email"], "id": users["owner"]["id"]},
    }, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mongo-url", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    asyncio.run(main(a.mongo_url, Path(a.out)))
