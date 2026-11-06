"""CLAUDE AUDIT probe SEC-01-C02 (#69) FG-27 POST /api/subcontractor-payments, real server.app, mode off.

    cd <PR worktree>/backend && PYTHONPATH=. MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' python <this>
P1 identical POST twice (same body)     → how many finance_payments Outflow rows? (CLAUDE.md §14 idempotency)
P2 amount "nan" / "inf" / "-0"          → must be 400, no ledger row
P3 account_id of tenant B               → must be 404, no ledger row
P4 payment above certified_total        → status + payable (business rule, reported)
"""
import os, sys, uuid
from pathlib import Path
sfx = uuid.uuid4().hex[:10]
os.environ.update(DB_NAME="pm01_op_" + sfx, BEG_SYSTEM_DB="pm01_sys_" + sfx, ENV="test",
                  JWT_SECRET="probe-" + sfx, PERMISSION_SERVICE_MODE="off")
sys.path.insert(0, str(Path.cwd().parent / "ops" / "staging"))
import seed_synthetic as seed_mod  # noqa
import server  # noqa
from fastapi.testclient import TestClient  # noqa
from motor.motor_asyncio import AsyncIOMotorClient  # noqa
PW = "Probe-Synthetic-Pass-2026!"
app = server.app; app.router.on_startup.clear(); app.router.on_shutdown.clear()
fails = []
with TestClient(app, raise_server_exceptions=False) as tc:
    c = tc.portal.call(lambda: AsyncIOMotorClient(os.environ["MONGO_URL"]))
    op, sysdb = c[os.environ["DB_NAME"]], c[os.environ["BEG_SYSTEM_DB"]]
    rep = tc.portal.call(lambda: seed_mod.seed(op, sysdb, PW))
    T = {t["key"]: t for t in rep["tenants"]}; UA = {u["key"]: u for u in T["A"]["users"]}
    A, B = T["A"]["tenant_id"], T["B"]["tenant_id"]
    tc.portal.call(lambda: op["subcontractor_packages"].insert_one({
        "id": "pkg-1", "org_id": A, "project_id": T["A"]["project_id"], "subcontractor_id": "sub-1",
        "subcontractor_name": "Sub", "currency": "EUR", "certified_total": 1000.0, "contract_total": 1000.0}))
    tc.portal.call(lambda: op["financial_accounts"].insert_many([
        {"id": "acc-A", "org_id": A, "account_type": "Cash", "name": "Каса"},
        {"id": "acc-B", "org_id": B, "account_type": "Cash", "name": "Каса B"}]))
    h = {"Authorization": "Bearer " + tc.post("/api/auth/login", json={"email": UA["accountant"]["email"], "password": PW}).json()["token"]}
    ledger = lambda: tc.portal.call(lambda: op["finance_payments"].count_documents({"direction": "Outflow"}))
    body = {"package_id": "pkg-1", "amount": 100, "account_id": "acc-A", "payment_date": "2026-11-06", "notes": "same"}
    r1 = tc.post("/api/subcontractor-payments", json=body, headers=h).status_code
    r2 = tc.post("/api/subcontractor-payments", json=body, headers=h).status_code
    n = ledger()
    print("P1 identical POST x2 →", r1, r2, "ledger Outflow rows:", n)
    if n != 1: fails.append("P1 duplicate ledger rows=%d" % n)
    for amt in ("nan", "inf", "-0", "1e309"):
        before = ledger()
        r = tc.post("/api/subcontractor-payments", json=dict(body, amount=amt, notes=amt), headers=h)
        after = ledger()
        print("P2 amount=%-6s → %s  ledger +%d" % (amt, r.status_code, after - before))
        if r.status_code < 300 or after != before: fails.append("P2 %s" % amt)
    before = ledger()
    r = tc.post("/api/subcontractor-payments", json=dict(body, account_id="acc-B"), headers=h)
    print("P3 tenant-B account →", r.status_code, "ledger +%d" % (ledger() - before))
    if r.status_code < 300 or ledger() != before: fails.append("P3")
    r = tc.post("/api/subcontractor-payments", json=dict(body, amount=5000, notes="over"), headers=h)
    pkg = tc.portal.call(lambda: op["subcontractor_packages"].find_one({"id": "pkg-1"}))
    print("P4 over certified →", r.status_code, "payable now:", pkg.get("payable_amount", pkg.get("payable")))
    bad = tc.portal.call(lambda: op["finance_payments"].find({"amount": {"$not": {"$gt": 0}}}, {"_id": 0, "amount": 1}).to_list(None))
    print("ledger rows with non-positive / NaN amount:", bad)
    tc.portal.call(lambda: c.drop_database(os.environ["DB_NAME"])); tc.portal.call(lambda: c.drop_database(os.environ["BEG_SYSTEM_DB"]))
print("FAILS:", fails or "none")
sys.exit(1 if fails else 0)
