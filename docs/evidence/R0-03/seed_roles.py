"""R0-03 bot test — seed two TEST firms through the real API only.

Firm A: /billing/signup (Owner) → mock checkout to Enterprise (ENV=test, BILLING_PROVIDER=mock;
the employee screens need module M4) → the Owner creates an Admin and an Accountant (/users).
Firm B: /billing/signup (Owner) → mock Enterprise → the Owner creates a Viewer ``ivan@r003b.test``.
Test data only; the password is a throwaway local value for a disposable local database.

    python seed_roles.py http://127.0.0.1:8001 > seed.json
"""
import json
import sys
import urllib.request

BASE = sys.argv[1].rstrip("/") + "/api"
PASSWORD = "R003-bot-test-only!"


def call(method, path, body=None, token=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def firm(name, owner_email):
    s = call("POST", "/billing/signup", {"org_name": name, "owner_name": "Owner " + name,
                                         "owner_email": owner_email, "password": PASSWORD})
    call("POST", "/billing/create-checkout-session", {"plan_id": "enterprise", "origin_url": "http://127.0.0.1:3000"}, s["token"])
    return s["token"], s["organization"]["id"], s["user"]["id"]


tok_a, org_a, owner_a = firm("R003 Firm A", "owner@r003a.test")
admin_a = call("POST", "/users", {"email": "admin@r003a.test", "password": PASSWORD, "first_name": "Admin",
                                  "last_name": "R003", "role": "Admin"}, tok_a)
acct_a = call("POST", "/users", {"email": "acct@r003a.test", "password": PASSWORD, "first_name": "Accountant",
                                 "last_name": "R003", "role": "Accountant"}, tok_a)
tok_b, org_b, owner_b = firm("R003 Firm B", "owner@r003b.test")
ivan_b = call("POST", "/users", {"email": "ivan@r003b.test", "password": PASSWORD, "first_name": "Ivan",
                                 "last_name": "B", "role": "Viewer"}, tok_b)
print(json.dumps({"org_a": org_a, "org_b": org_b,
                  "owner_a": {"id": owner_a, "email": "owner@r003a.test"},
                  "admin_a": {"id": admin_a["id"], "email": "admin@r003a.test"},
                  "acct_a": {"id": acct_a["id"], "email": "acct@r003a.test"},
                  "owner_b": {"id": owner_b, "email": "owner@r003b.test"},
                  "ivan_b": {"id": ivan_b["id"], "email": "ivan@r003b.test"}}, indent=2))
