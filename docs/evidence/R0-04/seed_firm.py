"""R0-04 bot test — seed one TEST firm through the real API only (POST /billing/signup).

Test data only; the password is a throwaway local value for a disposable local database.

    python seed_firm.py http://127.0.0.1:8001 > seed.json
"""
import json
import sys
import urllib.request

BASE = sys.argv[1].rstrip("/") + "/api"
PASSWORD = "R004-bot-old-pass!"


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


s = call("POST", "/billing/signup", {"org_name": "R004 Firm", "owner_name": "Owner R004",
                                     "owner_email": "owner@r004.test", "password": PASSWORD})
print(json.dumps({"org": s["organization"]["id"], "owner": {"id": s["user"]["id"],
                  "email": "owner@r004.test"}}, indent=2))
