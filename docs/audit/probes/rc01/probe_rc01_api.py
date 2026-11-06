"""CLAUDE AUDIT probe RC-01/P2-P5 — /api/version on the REAL server app (all middleware).

    cd <PR worktree>/backend && PYTHONPATH=. MONGO_URL=mongodb://127.0.0.1:27019 DB_NAME=probe_rc01 \
        python <this file>
P2 unauthenticated GET /api/version on server.app → 200 (not 401/403 from a global guard)
P3 BUILD_INFO.json with extra/secret keys → response keys stay exactly the allowlist
P4 odd ENV values (" production", "Production", "production\\n", "prod") → "unknown"
P5 uppercase / short / 41-char BUILD_SHA → ignored → "unknown"
"""
import json, os, sys, tempfile
os.environ.setdefault("JWT_SECRET", "probe-secret")
from fastapi.testclient import TestClient
import server
from app.core import build_info as bi

c = TestClient(server.app)
fails = []
ALLOW = set(bi.RESPONSE_KEYS)

for k in ("BUILD_SHA", "BUILD_TIME", "ENV"):
    os.environ.pop(k, None)
r = c.get("/api/version")
print("P2 status", r.status_code, r.text[:200])
if r.status_code != 200: fails.append("P2")

d = tempfile.mkdtemp(); p = os.path.join(d, "BUILD_INFO.json")
json.dump({"schema": "beg.build-info/v1", "build_sha": "a" * 40, "build_time": "2026-01-01T00:00:00Z",
           "source": "git-objects", "secret": "SENTINEL", "path": "/srv/x"}, open(p, "w"))
orig = bi.BUILD_INFO_FILE; bi.BUILD_INFO_FILE = p
body = c.get("/api/version").json(); bi.BUILD_INFO_FILE = orig
print("P3", body)
if set(body) != ALLOW or "SENTINEL" in json.dumps(body): fails.append("P3")

for v in (" production", "Production", "production\n", "prod", "PRODUCTION", ""):
    os.environ["ENV"] = v
    lab = c.get("/api/version").json()["environment_label"]
    if lab != "unknown": fails.append("P4:%r->%s" % (v, lab))
os.environ.pop("ENV")
for v in ("A" * 40, "a" * 39, "a" * 41, " " + "a" * 40, "g" * 40):
    os.environ["BUILD_SHA"] = v
    sha = c.get("/api/version").json()["build_sha"]
    if sha != "unknown": fails.append("P5:%r->%s" % (v, sha))
os.environ.pop("BUILD_SHA")
print("FAILS:", fails or "none")
sys.exit(1 if fails else 0)
