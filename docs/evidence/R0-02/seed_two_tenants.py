"""R0-02 bot test — seed two TEST tenants through the real API only.

Each tenant: /billing/signup (Owner), the Owner creates one Admin (/users) and a
few items (/items). Test data only; the passwords below are throwaway local
test values, never used outside a disposable local database.

    python seed_two_tenants.py http://127.0.0.1:8001 > seed.json
"""
import json
import sys
import urllib.request

BASE = sys.argv[1].rstrip("/") + "/api"
PASSWORD = "R002-bot-test-only!"

TENANTS = {
    "A": {"org": "R002 Test Firm A", "items": [("A-CEM", "A Cement 25kg", "Materials", 12.5),
                                               ("A-DRL", "A Drill 18V", "Tools", 180.0),
                                               ("A-GLV", "A Gloves", "Consumables", 3.2)]},
    "B": {"org": "R002 Test Firm B", "items": [("B-BRK", "B Brick", "Materials", 0.9),
                                               ("B-SAW", "B Saw", "Tools", 95.0),
                                               ("B-TAP", "B Tape", "Consumables", 4.4),
                                               ("B-SCF", "B Scaffold", "Equipment", 1200.0)]},
}


def call(method, path, body=None, token=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


out = {}
for key, spec in TENANTS.items():
    low = key.lower()
    signup = call("POST", "/billing/signup", {"org_name": spec["org"], "owner_name": "Owner " + key,
                                              "owner_email": "owner-%s@r002.test" % low,
                                              "password": PASSWORD})
    owner = signup["token"]
    admin_email = "admin-%s@r002.test" % low
    call("POST", "/users", {"email": admin_email, "password": PASSWORD, "first_name": "Admin",
                            "last_name": key, "role": "Admin"}, owner)
    for sku, name, cat, price in spec["items"]:
        call("POST", "/items", {"sku": sku, "name": name, "category": cat,
                                "default_price": price}, owner)
    out[key] = {"org_id": signup["organization"]["id"], "admin_email": admin_email,
                "skus": [i[0] for i in spec["items"]]}
print(json.dumps(out, indent=2))
