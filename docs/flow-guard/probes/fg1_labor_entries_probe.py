"""FLOW GUARD probe FG-1 (labor entries on main vs R16 / FLOW-002 / FLOW-037 §3.4).
Copy to backend/tests/_fg_probe_tmp.py, then from backend/: PYTHONPATH=. python -m pytest tests/_fg_probe_tmp.py -q -s --noconftest
Needs a MongoDB replica set at 127.0.0.1:27019 (rs0). Uses throwaway databases fg_main_*, dropped at the end.
Real MongoDB (fgmongo, db fg_main_*). Non-admin seeded users have NO project_team membership."""
import asyncio, json, os, uuid
import pytest
from tests.test_st_01_staging_fixtures import seed_mod, FIXTURE, PASSWORD, _app

URL = "mongodb://127.0.0.1:27019/?replicaSet=rs0&directConnection=true"

def test_labor_probe(monkeypatch):
    async def body():
        import httpx
        from motor.motor_asyncio import AsyncIOMotorClient
        from app.routes import labor_smr
        sfx = uuid.uuid4().hex[:6]
        cl = AsyncIOMotorClient(URL)
        op, sysdb = cl["fg_main_op_" + sfx], cl["fg_main_sys_" + sfx]
        await seed_mod.seed(op, sysdb, PASSWORD)
        app = _app(monkeypatch, op, sysdb)
        monkeypatch.setattr(labor_smr, "db", op)
        app.include_router(labor_smr.router, prefix="/api")
        t = FIXTURE["tenants"][0]
        pid = seed_mod.stable_id(t["key"], "project", t["project"]["code"])
        org = (await sysdb.tenant_registry.find_one({"fixture_key": t["key"]}))["id"]
        owner = await op.users.find_one({"email": seed_mod.user_email(t, {"key": "owner"})})
        await op.employee_profiles.insert_one({"org_id": org, "user_id": owner["id"], "hourly_rate": 37.5})
        out = {}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fg") as c:
            for role in ("viewer", "driver", "technician", "warehousekeeper"):
                r = await c.post("/api/auth/login", json={"email": seed_mod.user_email(t, {"key": role}), "password": PASSWORD})
                assert r.status_code == 200, (role, r.text)
                h = {"Authorization": "Bearer " + r.json()["token"]}
                w = await c.post("/api/labor-entries", headers=h, json={"project_id": pid, "employee_id": owner["id"], "hours": 8})
                g = await c.get("/api/labor-entries", headers=h, params={"project_id": pid})
                out[role] = {"POST": w.status_code, "POST_labor_cost": w.json().get("labor_cost") if w.status_code < 300 else None,
                             "GET": g.status_code, "GET_rates_seen": sorted({e.get("hourly_rate") for e in g.json()} - {None}) if g.status_code == 200 else None}
        members = await op.project_team.count_documents({"project_id": pid})
        audits = await op.audit_logs.count_documents({"entity_type": {"$regex": "labor"}}) + await op.audit_events.count_documents({"entity_type": {"$regex": "labor"}})
        out["_project_team_members"] = members
        out["_labor_audit_rows"] = audits
        out["_labor_rows"] = await op.labor_entries.count_documents({})
        print("FGRESULT " + json.dumps(out))
        await cl.drop_database(op.name); await cl.drop_database(sysdb.name)
    asyncio.run(body())
