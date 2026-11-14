"""SEC-03 e2e — seed one TEST tenant through the real API only (disposable local DB).

    python e2e_seed.py http://127.0.0.1:8080 > seed.json
"""
import json
import sys
import urllib.request

BASE = sys.argv[1].rstrip("/") + "/api"
PASSWORD = "SEC03-bot-test-only!"


def call(method, path, body=None, token=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


signup = call("POST", "/billing/signup", {"org_name": "SEC03 Test Firm", "owner_name": "Owner SEC03",
                                          "owner_email": "owner@sec03.test", "password": PASSWORD})
print(json.dumps({"org_id": signup["organization"]["id"], "owner_email": "owner@sec03.test"}, indent=2))
