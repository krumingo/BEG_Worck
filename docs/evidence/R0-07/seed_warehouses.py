"""R0-07 bot test — seed one TEST tenant through the real API only.

/billing/signup (Owner) → the Owner creates an Admin and a Warehousekeeper (/users)
and three warehouses (/warehouses). Test data only; the password is a throwaway
local test value for a disposable local database.

    python seed_warehouses.py http://127.0.0.1:8001 > seed.json
"""
import json
import sys
import urllib.request

BASE = sys.argv[1].rstrip("/") + "/api"
PASSWORD = "R007-bot-test-only!"


def call(method, path, body=None, token=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


signup = call("POST", "/billing/signup", {"org_name": "R007 Test Firm", "owner_name": "Owner R007",
                                          "owner_email": "owner@r007.test", "password": PASSWORD})
owner = signup["token"]
for first, role in (("Admin", "Admin"), ("Keeper", "Warehousekeeper")):
    call("POST", "/users", {"email": "%s@r007.test" % first.lower(), "password": PASSWORD,
                            "first_name": first, "last_name": "R007", "role": role}, owner)
whs = [call("POST", "/warehouses", {"code": "WH-%d" % i, "name": "Склад %d" % i, "type": "central"}, owner)
       for i in (1, 2, 3)]
print(json.dumps({"org_id": signup["organization"]["id"], "admin_email": "admin@r007.test",
                  "keeper_email": "keeper@r007.test",
                  "warehouses": [{"id": w["id"], "name": w["name"]} for w in whs]}, indent=2))
