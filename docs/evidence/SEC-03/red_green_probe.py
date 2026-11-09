"""SEC-03 red/green probe: the same HTTP calls against a tree (main or the fix).

    cd <tree>/backend && PYTHONPATH=. python ../docs/evidence/SEC-03/red_green_probe.py

mongomock only, nothing configured (no INTERNAL_JOB_KEY, no AI key / model);
the reminder job body itself is replaced by a recorder so only the gate is measured.
"""
import asyncio
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from app.deps.auth import get_current_user
from app.routes import assets_ai_intake, attendance

db = AsyncMongoMockClient()["sec03_probe"]
asyncio.run(db["organizations"].insert_many([{"id": "org-a"}, {"id": "org-b"}]))
ran = []


async def _recorder(*a, **kw):
    ran.append("run")
attendance.db = db
for name in ("run_reminder_jobs", "run_reminder_jobs_for_org"):
    if hasattr(attendance, name):
        setattr(attendance, name, _recorder)

app = FastAPI()
app.include_router(attendance.router, prefix="/api")
app.include_router(assets_ai_intake.router, prefix="/api")


async def _admin():
    return {"id": "u1", "org_id": "org-a", "role": "Admin", "email": "a@x"}
app.dependency_overrides[get_current_user] = _admin
c = TestClient(app, raise_server_exceptions=False)

out = {}
r = c.post("/api/internal/run-reminder-jobs")
out["reminder_no_credentials"] = [r.status_code, "job ran" if ran else "job not run"]
ran.clear()
r = c.post("/api/internal/run-reminder-jobs", headers={"X-Internal-Job-Key": "guess"})
out["reminder_guessed_key"] = [r.status_code, "job ran" if ran else "job not run"]
r = c.post("/api/assets/ai-intake", json={"image_base64": "/9j/" + "A" * 300})
out["ai_intake_nothing_configured"] = [r.status_code, r.json().get("detail")]
print(json.dumps(out, ensure_ascii=False, indent=1))
