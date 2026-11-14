"""
ASSET-REP-01 — FG-723: asset repair rights, two-phase custody, cost as an obligation,
warranty DQ signal, AuditEvent, idempotency, tenant isolation.

Canon: FLOW-011 (two-phase custody, repairs), FLOW-012 §9, FLOW-039 §9–§11, FLOW-006, R16, R20;
oracle docs/flow-guard/oracle/Q012_asset_repair_FG723.md (branch claude/flow-guard).
Code: app/routes/assets_repairs.py, app/permissions/catalog.py (ASSET_REPAIR_*_ACTIONS).

Every scenario runs in PERMISSION_SERVICE_MODE off / shadow / enforce against
``mongomock_motor`` always, and against a disposable LOCAL MongoDB replica set when
``W0_03_REAL_MONGO_URL`` is set (one database per test, dropped afterwards). Authentication is
real: a JWT the route verifies and a user ``get_current_user`` loads from the database; the
tenant is registered (registry + memberships + role assignments) so enforce resolves it.

    PYTHONPATH=. pytest tests/test_asset_rep_01_repairs.py -q --noconftest -p no:cacheprovider
    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' \\
        PYTHONPATH=. pytest tests/test_asset_rep_01_repairs.py -q --noconftest -p no:cacheprovider
"""
import asyncio
import inspect
import uuid
from datetime import date, timedelta

import pytest

ORG, ORG_B = "ORG-AR01", "ORG-AR01-B"
UNIT, UNIT_B = "U-AR01", "U-AR01-B"
WH = "WH-AR01"
MODES = ("off", "shadow", "enforce")
BUSINESS = ("asset_repairs", "asset_units", "asset_custody", "finance_payments",
            "payment_allocations", "invoices")
USERS = {
    "owner": "Owner", "admin": "Admin", "accountant": "Accountant",
    "sitemanager": "SiteManager", "warehouse": "Warehousekeeper",
    "technician": "Technician", "viewer": "Viewer", "driver": "Driver",
}


def _real_refusal():
    from tests.test_w0_03c_real_mongo import _refusal
    return _refusal()


@pytest.fixture(params=["mongomock", pytest.param("real", marks=pytest.mark.skipif(
    bool(_real_refusal()), reason=_real_refusal() or "ok"))])
def backend(request):
    return request.param


@pytest.fixture(params=MODES)
def mode(request):
    return request.param


# ═══════════════════════════════════════════════════════════════════ harness
async def _seed(op, sysdb):
    from app.permissions.catalog import LEGACY_ROLE_MAP
    purchase = (date.today() - timedelta(days=60)).isoformat()      # 24 months → in warranty
    for org in (ORG, ORG_B):
        await op.organizations.insert_one({"id": org, "name": org})
        await op.subscriptions.insert_one({"org_id": org, "plan_id": "pro", "status": "active"})
    await sysdb.tenant_registry.insert_one({"id": ORG, "legacy_org_id": ORG, "status": "active",
                                            "database_name": op.name})
    for uid, role in USERS.items():
        await op.users.insert_one({"id": uid, "org_id": ORG, "role": role, "is_active": True,
                                   "email": uid + "@ar01.test", "first_name": uid})
        await sysdb.tenant_memberships.insert_one({"id": "tm_%s" % uid, "user_id": uid,
                                                   "tenant_id": ORG, "status": "active"})
        await sysdb.tenant_role_assignments.insert_one({
            "id": "ra_%s" % uid, "user_id": uid, "tenant_id": ORG,
            "role_id": LEGACY_ROLE_MAP[role], "scope_type": "company", "scope_id": None,
            "module": None, "permissions": [], "status": "active", "sync_source": "users.role"})
    await op.users.insert_one({"id": "b-warehouse", "org_id": ORG_B, "role": "Warehousekeeper",
                               "is_active": True, "email": "bw@ar01.test"})
    await op.warehouses.insert_one({"id": WH, "org_id": ORG, "name": "Main"})
    await op.asset_units.insert_many([
        {"id": UNIT, "org_id": ORG, "item_id": "I1", "qr_id": "QR-1", "serial_no": "SN-1",
         "status": "available", "location_type": "warehouse", "location_id": WH,
         "purchase_date": purchase, "warranty_months": 24},
        {"id": UNIT_B, "org_id": ORG_B, "item_id": "I2", "qr_id": "QR-B", "serial_no": "SN-B",
         "status": "available", "location_type": "warehouse", "location_id": "WH-B",
         "purchase_date": purchase, "warranty_months": 24},
    ])
    await op.media_files.insert_many([
        {"id": "F-1", "org_id": ORG, "filename": "photo1.jpg"},
        {"id": "F-2", "org_id": ORG, "filename": "service.pdf"},
        {"id": "F-B", "org_id": ORG_B, "filename": "other.jpg"},
    ])
    # a repair of tenant B, already in repair (isolation target)
    await op.asset_repairs.insert_one({
        "id": "R-B", "org_id": ORG_B, "unit_id": UNIT_B, "status": "in_repair", "cost": None,
        "cost_versions": [], "handovers": [{"id": "ho_b", "kind": "send",
                                            "status": "PENDING_ACCEPTANCE",
                                            "to_user_id": "sitemanager"}]})
    await op.invoices.insert_one({"id": "INV-1", "org_id": ORG, "direction": "Received",
                                  "total": 500, "status": "Sent", "invoice_no": "S-1"})
    await op.invoices.insert_one({"id": "INV-OUT", "org_id": ORG, "direction": "Issued",
                                  "total": 900, "status": "Sent", "invoice_no": "I-1"})
    await op.audit_idempotency.create_index([("id", 1)], unique=True)


def _h(who="owner", key="auto"):
    from app.deps.auth import create_token
    h = {"Authorization": "Bearer " + create_token(
        {"user_id": who, "org_id": ORG, "role": USERS[who]})}
    if key == "auto":
        key = "k-" + uuid.uuid4().hex
    if key is not None:
        h["Idempotency-Key"] = key
    return h


def _app(monkeypatch, op, sysdb, mode):
    from fastapi import FastAPI
    import app.db as appdb
    from app.deps import auth as deps_auth
    from app.master_data.deps import ENV_MODE
    from app.permissions import money_write
    from app.routes import assets_repairs, finance
    from app.tenancy import guard, registry, resolver
    from app.utils import audit as utils_audit

    monkeypatch.setenv(ENV_MODE, "off")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    for module in (appdb, deps_auth, utils_audit, assets_repairs, finance, money_write):
        monkeypatch.setattr(module, "db", op)
    monkeypatch.setattr(registry, "system_db", sysdb)
    for coll in ("tenant_registry", "tenant_memberships", "tenant_role_assignments"):
        monkeypatch.setattr(registry, coll, sysdb[coll])

    async def _get_db(tenant_id, require_operational=False):
        t = await registry.get_tenant(tenant_id)
        if not t:
            raise resolver.TenantNotFound(tenant_id)
        assert registry.resolve_database_name(t) == op.name
        return op
    monkeypatch.setattr(resolver, "get_tenant_db", _get_db)
    monkeypatch.setattr(guard, "get_tenant_db", _get_db)
    app = FastAPI()
    app.include_router(assets_repairs.router, prefix="/api")
    return app


class _Db:
    def __init__(self, backend):
        self.backend, self.client = backend, None
        suffix = uuid.uuid4().hex[:10]
        self.names = ("ar_01_" + suffix, "ar_01_sys_" + suffix)

    async def __aenter__(self):
        if self.backend == "real":
            from motor.motor_asyncio import AsyncIOMotorClient
            from tests.test_w0_03c_real_mongo import REAL_URL
            self.client = AsyncIOMotorClient(REAL_URL, serverSelectionTimeoutMS=5000)
        else:
            from mongomock_motor import AsyncMongoMockClient
            self.client = AsyncMongoMockClient()
        return self.client[self.names[0]], self.client[self.names[1]]

    async def __aexit__(self, *exc):
        if self.backend == "real":
            for name in self.names:
                await self.client.drop_database(name)
            self.client.close()


def run(monkeypatch, backend, mode, scenario):
    import httpx

    async def body():
        async with _Db(backend) as (op, sysdb):
            await _seed(op, sysdb)
            app = _app(monkeypatch, op, sysdb, mode)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://ar01") as c:
                return await scenario(c, op)
    return asyncio.run(body())


async def _dump(op):
    """Every business row + every asset_repair AuditEvent, as bytes. An enforce-mode
    permission DENIAL event is a refusal record, not a business write (as PM-01)."""
    import bson
    out = {}
    for name in BUSINESS + ("audit_events",):
        flt = {"action": {"$regex": "^asset_repair\\."}} if name == "audit_events" else {}
        docs = await op[name].find(flt).to_list(None)
        docs.sort(key=lambda d: str(d.get("id") or d.get("event_id")))
        out[name] = [bson.BSON.encode({k: d[k] for k in sorted(d) if k != "_id"}) for d in docs]
    return out


async def _events(op, action=None):
    flt = {"action": action} if action else {"action": {"$regex": "^asset_repair\\."}}
    return await op.audit_events.find(flt, {"_id": 0}).sort("sequence", 1).to_list(None)


SEND = "/api/assets/units/%s/repair/send" % UNIT
RETURN = "/api/assets/units/%s/repair/return" % UNIT
LIST = "/api/assets/units/%s/repairs" % UNIT


def _send_body(receiver="warehouse"):
    return {"receiver_user_id": receiver, "service": "Сервиз Х", "issue": "не пали",
            "condition": "видими драскотини", "accessories": "куфар, зарядно",
            "file_ids": ["F-1"]}


async def _to_in_repair(c, op):
    """sitemanager (responsible) → warehouse (receiver) ; the receiver accepts."""
    r = await c.post(SEND, json=_send_body(), headers=_h("sitemanager"))
    assert r.status_code == 200, r.text
    rec = r.json()
    ho = rec["handovers"][0]["id"]
    r = await c.post("/api/assets/repairs/%s/handovers/%s/accept" % (rec["id"], ho),
                     json={"condition": "ok", "file_ids": ["F-2"]}, headers=_h("warehouse"))
    assert r.status_code == 200, r.text
    return r.json()


# ═══════════════════════════════════════════════════════════════════ FG-723 itself
def test_fg723_viewer_and_driver_never_write(monkeypatch, backend, mode):
    async def scenario(c, op):
        before = await _dump(op)
        for who in ("viewer", "driver"):
            r = await c.post(SEND, json=_send_body(), headers=_h(who))
            assert r.status_code == 403, (who, r.status_code, r.text)
            r = await c.post(RETURN, json={"receiver_user_id": "sitemanager", "cost": 500,
                                           "is_warranty": False}, headers=_h(who))
            assert r.status_code == 403, (who, r.status_code, r.text)
            r = await c.post("/api/assets/repairs/R-X/handovers/ho/accept", json={},
                             headers=_h(who))
            assert r.status_code == 403, (who, r.status_code, r.text)
        assert await _dump(op) == before                       # nothing written
    run(monkeypatch, backend, mode, scenario)


def test_fg723_the_exact_reproduction_is_refused(monkeypatch, backend, mode):
    """The FG-723 sequence: a Viewer sends an in-warranty unit and returns it with cost 500,
    is_warranty=false → 403 at each step; /repairs shows no paid that is not in the ledger."""
    async def scenario(c, op):
        r = await c.post(SEND, json={"service": "X", "issue": "x"}, headers=_h("viewer"))
        assert r.status_code == 403
        r = await c.post(RETURN, json={"cost": 500, "is_warranty": False}, headers=_h("viewer"))
        assert r.status_code == 403
        assert await op.asset_repairs.count_documents({"org_id": ORG}) == 0
        unit = await op.asset_units.find_one({"id": UNIT})
        assert unit["status"] == "available"
        r = await c.get(LIST, headers=_h("owner", key=None))
        assert r.status_code == 200
        body = r.json()
        assert "total_paid" not in body and body["paid"] == 0 and body["total_cost"] == 0
    run(monkeypatch, backend, mode, scenario)


@pytest.mark.parametrize("who", ["viewer", "driver", "technician", "sitemanager", "warehouse"])
def test_cost_is_finance_only_r20(monkeypatch, backend, mode, who):
    """Forbidden: a non-finance role writing a cost → 403 (enforce: the Permission Service;
    off/shadow: the legacy finance rule), nothing written — neither the PUT nor a return
    that carries a cost."""
    async def scenario(c, op):
        rec = await _to_in_repair(c, op)
        before = await _dump(op)
        r = await c.put("/api/assets/repairs/%s/cost" % rec["id"], json={"cost": 500},
                        headers=_h(who))
        assert r.status_code == 403, r.text
        if mode == "enforce":
            assert r.json()["detail"]["error_code"] == "PERMISSION_DENIED"
        r = await c.post(RETURN, json={"receiver_user_id": "sitemanager", "cost": 500},
                         headers=_h(who))
        assert r.status_code == 403, r.text
        assert await _dump(op) == before
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════════════ two-phase custody
def test_two_phase_send_and_return(monkeypatch, backend, mode):
    async def scenario(c, op):
        r = await c.post(SEND, json=_send_body(), headers=_h("sitemanager"))
        assert r.status_code == 200, r.text
        rec = r.json()
        ho = rec["handovers"][0]
        assert rec["status"] == "send_pending" and ho["status"] == "PENDING_ACCEPTANCE"
        # PENDING: unit and custody unchanged — the sender stays holder/responsible
        unit = await op.asset_units.find_one({"id": UNIT})
        assert unit["status"] == "available" and unit["location_id"] == WH
        assert await op.asset_custody.count_documents({}) == 0
        # only the named receiver decides
        url = "/api/assets/repairs/%s/handovers/%s" % (rec["id"], ho["id"])
        for other in ("owner", "sitemanager"):
            r = await c.post(url + "/accept", json={}, headers=_h(other))
            assert r.status_code == 403, (other, r.text)
            assert r.json()["detail"]["error_code"] == "NOT_THE_RECEIVER"
        r = await c.post(url + "/accept", json={"condition": "ok", "file_ids": ["F-2"]},
                         headers=_h("warehouse"))
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "in_repair"
        unit = await op.asset_units.find_one({"id": UNIT})
        assert unit["status"] == "repair"
        cust = await op.asset_custody.find_one({"status": "accepted"})
        assert cust["custodian_user_id"] == "warehouse" and cust["org_id"] == ORG
        # a second decision on the same handover → 409
        r = await c.post(url + "/accept", json={}, headers=_h("warehouse"))
        assert r.status_code == 409

        # return, initiated by the holder (warehouse), received by the sitemanager
        r = await c.post(RETURN, json={"receiver_user_id": "sitemanager", "work_done": "сменен акумулатор",
                                       "condition": "работи", "functional_test": "ok",
                                       "file_ids": ["F-1"]}, headers=_h("warehouse"))
        assert r.status_code == 200, r.text
        rec = r.json()
        assert rec["status"] == "return_pending" and rec["is_warranty"] is True
        unit = await op.asset_units.find_one({"id": UNIT})
        assert unit["status"] == "repair"                       # not yet accepted
        ret = rec["handovers"][-1]
        r = await c.post("/api/assets/repairs/%s/handovers/%s/accept" % (rec["id"], ret["id"]),
                         json={"condition": "ok"}, headers=_h("sitemanager"))
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "done"
        unit = await op.asset_units.find_one({"id": UNIT})
        assert unit["status"] == "available" and unit["location_type"] == "warehouse" \
            and unit["location_id"] == WH
        active = await op.asset_custody.find({"status": "accepted"}).to_list(None)
        assert [a["custodian_user_id"] for a in active] == ["sitemanager"]
        assert await op.asset_custody.count_documents({"status": "released"}) == 1  # kept

        # every transition is one canonical AuditEvent naming who / what / where / evidence
        evs = await _events(op)
        assert [e["action"] for e in evs] == [
            "asset_repair.send.created", "asset_repair.handover.accepted",
            "asset_repair.return.created", "asset_repair.handover.accepted"]
        for e in evs:
            d = e["structured_diff"]
            assert e["tenant_id"] == ORG and e["entity_type"] == "asset_repair"
            assert e["idempotency_key"] and e["result"] == "success"
            assert d["sender_user_id"] and d["receiver_user_id"]
            assert d["asset"]["unit_id"] == UNIT and d["asset"]["serial_no"] == "SN-1"
            assert "from_location" in d and "to_location" in d and "condition" in d
        assert evs[0]["structured_diff"]["sender_user_id"] == "sitemanager"
        assert evs[0]["structured_diff"]["receiver_user_id"] == "warehouse"
        assert evs[0]["related_file_ids"] == ["F-1"]
        assert set(evs[1]["related_file_ids"]) == {"F-1", "F-2"}
        assert evs[1]["structured_diff"]["custody_changed"] is True
        from app.audit.store import verify_tenant_chain
        assert (await verify_tenant_chain(op, ORG))[0]
    run(monkeypatch, backend, mode, scenario)


def test_refuse_and_problem_change_no_custody(monkeypatch, backend, mode):
    async def scenario(c, op):
        r = await c.post(SEND, json=_send_body(), headers=_h("sitemanager"))
        rec = r.json()
        url = "/api/assets/repairs/%s/handovers/%s" % (rec["id"], rec["handovers"][0]["id"])
        r = await c.post(url + "/refuse", json={}, headers=_h("warehouse"))
        assert r.status_code == 422 and r.json()["detail"]["error_code"] == "REASON_REQUIRED"
        r = await c.post(url + "/refuse", json={"reason": "липсва зарядно", "file_ids": ["F-2"]},
                         headers=_h("warehouse"))
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "send_refused"
        unit = await op.asset_units.find_one({"id": UNIT})
        assert unit["status"] == "available" and await op.asset_custody.count_documents({}) == 0
        # the refused record stays (no delete) and a new send is possible
        assert await op.asset_repairs.count_documents({"id": rec["id"]}) == 1
        r = await c.post(SEND, json=_send_body(), headers=_h("sitemanager"))
        assert r.status_code == 200
        rec2 = r.json()
        url2 = "/api/assets/repairs/%s/handovers/%s" % (rec2["id"], rec2["handovers"][0]["id"])
        r = await c.post(url2 + "/problem", json={"reason": "счупен корпус"}, headers=_h("warehouse"))
        assert r.status_code == 200 and r.json()["status"] == "send_problem"
        acts = [e["action"] for e in await _events(op)]
        assert acts == ["asset_repair.send.created", "asset_repair.handover.refused",
                        "asset_repair.send.created", "asset_repair.handover.problem"]
        ev = (await _events(op, "asset_repair.handover.refused"))[0]
        assert ev["reason"] == "липсва зарядно" and "F-2" in ev["related_file_ids"]
    run(monkeypatch, backend, mode, scenario)


def test_only_holder_or_responsible_initiates(monkeypatch, backend, mode):
    """The Technician → 403 in every mode (the legacy Technician holds no repair action:
    W0-02 invariant, debt D-ASSETREP-01). Receiver rules: another active user of THIS
    tenant who may accept."""
    async def scenario(c, op):
        before = await _dump(op)
        r = await c.post(SEND, json=_send_body(), headers=_h("technician"))
        assert r.status_code == 403, r.text
        assert await _dump(op) == before
        r = await c.post(SEND, json=_send_body(receiver="sitemanager"), headers=_h("sitemanager"))
        assert r.status_code == 422 and r.json()["detail"]["error_code"] == "RECEIVER_IS_SENDER"
        r = await c.post(SEND, json=_send_body(receiver="viewer"), headers=_h("sitemanager"))
        assert r.status_code == 422 and r.json()["detail"]["error_code"] == "RECEIVER_CANNOT_ACCEPT"
        r = await c.post(SEND, json=_send_body(receiver="b-warehouse"), headers=_h("sitemanager"))
        assert r.status_code == 422 and r.json()["detail"]["error_code"] == "RECEIVER_NOT_FOUND"
        assert await _dump(op) == before
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════════════ warranty
def test_warranty_override_needs_a_reason_and_is_audited(monkeypatch, backend, mode):
    async def scenario(c, op):
        rec = await _to_in_repair(c, op)
        before = await _dump(op)
        body = {"receiver_user_id": "sitemanager", "is_warranty": False, "work_done": "x"}
        r = await c.post(RETURN, json=body, headers=_h("warehouse"))
        assert r.status_code == 422, r.text
        d = r.json()["detail"]
        assert d["error_code"] == "WARRANTY_REASON_REQUIRED"
        assert d["dq_signals"][0]["code"] == "ASSET_IN_WARRANTY_MARKED_NON_WARRANTY"
        assert await _dump(op) == before
        r = await c.post(RETURN, json={**body, "warranty_override_reason": "   "},
                         headers=_h("warehouse"))
        assert r.status_code == 422
        r = await c.post(RETURN, json={**body, "warranty_override_reason": "повреда от удар"},
                         headers=_h("warehouse"))
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["is_warranty"] is False
        assert out["warranty_override"]["reason"] == "повреда от удар"
        assert out["warranty_override"]["approval"] is None            # INTERIM: no Approval
        assert out["dq_signals_raised"][0]["code"] == "ASSET_IN_WARRANTY_MARKED_NON_WARRANTY"
        stored = await op.asset_repairs.find_one({"id": rec["id"]})
        assert stored["dq_signals"][0]["reason"] == "повреда от удар"
        ev = await _events(op, "asset_repair.warranty_override.recorded")
        assert len(ev) == 1 and ev[0]["reason"] == "повреда от удар"
        assert ev[0]["structured_diff"]["dq_signal"] == "ASSET_IN_WARRANTY_MARKED_NON_WARRANTY"
        assert ev[0]["retention_class"] == "R2" or ev[0]["retention_class"] == "R1"
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════════════ cost / ledger
def test_cost_is_an_obligation_and_paid_comes_only_from_the_ledger(monkeypatch, backend, mode):
    async def scenario(c, op):
        rec = await _to_in_repair(c, op)
        r = await c.put("/api/assets/repairs/%s/cost" % rec["id"],
                        json={"cost": 500, "invoice_id": "INV-1", "file_ids": ["F-2"]},
                        headers=_h("accountant"))
        assert r.status_code == 200, r.text
        assert await op.finance_payments.count_documents({}) == 0      # never a payment
        r = await c.get(LIST, headers=_h("owner", key=None))
        b = r.json()
        assert "total_paid" not in b
        assert (b["total_cost"], b["paid"], b["remaining"]) == (500, 0, 500)
        it = b["items"][0]
        assert (it["cost"], it["paid"], it["remaining"]) == (500, 0, 500)
        assert it["paid_source"] == "finance_payments"
        # a real payment in the ONE ledger, allocated to the linked invoice → paid 200
        await op.finance_payments.insert_many([
            {"id": "PAY-1", "org_id": ORG, "direction": "Outflow", "amount": 200},
            {"id": "PAY-R", "org_id": ORG, "direction": "Outflow", "amount": 100,
             "status": "reversed"}])
        await op.payment_allocations.insert_many([
            {"id": "AL-1", "org_id": ORG, "payment_id": "PAY-1", "invoice_id": "INV-1",
             "amount_allocated": 200},
            {"id": "AL-R", "org_id": ORG, "payment_id": "PAY-R", "invoice_id": "INV-1",
             "amount_allocated": 100},                                # reversed → not counted
            {"id": "AL-C", "org_id": ORG, "payment_id": "PAY-1", "invoice_id": "INV-1",
             "amount_allocated": 50, "status": "cancelled"},          # cancelled → not counted
            {"id": "AL-G", "org_id": ORG, "payment_id": "PAY-GHOST", "invoice_id": "INV-1",
             "amount_allocated": 70}])                                # no ledger row → 0
        b = (await c.get(LIST, headers=_h("accountant", key=None))).json()
        assert (b["total_cost"], b["paid"], b["remaining"]) == (500, 200, 300)
        # non-finance callers see no money (SEC-02, R20-5M) — statuses stay
        for who in ("viewer", "sitemanager", "technician"):
            v = (await c.get(LIST, headers=_h(who, key=None))).json()
            assert not ({"total_cost", "paid", "remaining"} & set(v)), (who, v)
            assert "cost" not in v["items"][0] and v["items"][0]["status"] == "in_repair"
        # an issued invoice is not a repair obligation link
        r = await c.put("/api/assets/repairs/%s/cost" % rec["id"],
                        json={"cost": 500, "reason": "x", "invoice_id": "INV-OUT"},
                        headers=_h("accountant"))
        assert r.status_code == 422
    run(monkeypatch, backend, mode, scenario)


def test_cost_correction_is_a_new_version_and_idempotent(monkeypatch, backend, mode):
    async def scenario(c, op):
        rec = await _to_in_repair(c, op)
        url = "/api/assets/repairs/%s/cost" % rec["id"]
        r = await c.put(url, json={"cost": 500}, headers=_h("accountant"))
        assert r.status_code == 200
        for bad in ("500", True, -1, 10.123, None):
            r = await c.put(url, json={"cost": bad, "reason": "x"}, headers=_h("accountant"))
            assert r.status_code == 422, (bad, r.text)
        r = await c.put(url, json={"cost": 450}, headers=_h("accountant"))
        assert r.status_code == 422
        assert r.json()["detail"]["error_code"] == "CORRECTION_REASON_REQUIRED"
        key = "k-corr-" + uuid.uuid4().hex
        body = {"cost": 450, "reason": "отстъпка по фактура"}
        r1 = await c.put(url, json=body, headers=_h("accountant", key=key))
        assert r1.status_code == 200, r1.text
        r2 = await c.put(url, json=body, headers=_h("accountant", key=key))     # replay
        assert r2.status_code == 200 and r2.json() == r1.json()
        r3 = await c.put(url, json={**body, "cost": 400}, headers=_h("accountant", key=key))
        assert r3.status_code == 409                                    # key reused
        stored = await op.asset_repairs.find_one({"id": rec["id"]})
        assert stored["cost"] == 450
        assert [v["cost"] for v in stored["cost_versions"]] == [500, 450]
        assert stored["cost_versions"][1]["previous_cost"] == 500
        assert stored["cost_versions"][1]["reason"] == "отстъпка по фактура"
        acts = [e["action"] for e in await _events(op) if e["action"].startswith("asset_repair.cost")]
        assert acts == ["asset_repair.cost.recorded", "asset_repair.cost.corrected"]
        ev = (await _events(op, "asset_repair.cost.corrected"))[0]
        assert ev["structured_diff"]["cost"] == {"before": 500, "after": 450}
        assert ev["structured_diff"]["payment"] is None and ev["retention_class"] == "R1"
        # a finance role may carry the cost on the return as well (R20)
        r = await c.post(RETURN, json={"receiver_user_id": "sitemanager", "cost": 470,
                                       "is_warranty": True}, headers=_h("owner"))
        assert r.status_code == 200, r.text
        stored = await op.asset_repairs.find_one({"id": rec["id"]})
        assert [v["cost"] for v in stored["cost_versions"]] == [500, 450, 470]
    run(monkeypatch, backend, mode, scenario)


def test_idempotent_send_and_key_required(monkeypatch, backend, mode):
    async def scenario(c, op):
        before = await _dump(op)
        r = await c.post(SEND, json=_send_body(), headers=_h("sitemanager", key=None))
        assert r.status_code == 428
        assert await _dump(op) == before
        key = "k-send-" + uuid.uuid4().hex
        r1 = await c.post(SEND, json=_send_body(), headers=_h("sitemanager", key=key))
        r2 = await c.post(SEND, json=_send_body(), headers=_h("sitemanager", key=key))
        assert r1.status_code == r2.status_code == 200 and r1.json() == r2.json()
        assert await op.asset_repairs.count_documents({"org_id": ORG}) == 1
        assert len(await _events(op, "asset_repair.send.created")) == 1
        r3 = await c.post(SEND, json=_send_body(), headers=_h("sitemanager"))
        assert r3.status_code == 409                                    # one open repair
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════════════ tenant isolation
def test_tenant_isolation(monkeypatch, backend, mode):
    async def scenario(c, op):
        before = await _dump(op)
        r = await c.post("/api/assets/units/%s/repair/send" % UNIT_B, json=_send_body(),
                         headers=_h("sitemanager"))
        assert r.status_code == 404, r.text
        r = await c.post("/api/assets/repairs/R-B/handovers/ho_b/accept", json={},
                         headers=_h("sitemanager"))
        assert r.status_code == 404, r.text
        r = await c.put("/api/assets/repairs/R-B/cost", json={"cost": 1},
                        headers=_h("accountant"))
        assert r.status_code == 404, r.text
        r = await c.get("/api/assets/units/%s/repairs" % UNIT_B, headers=_h("owner", key=None))
        assert r.status_code == 200 and r.json()["items"] == []
        # another tenant's evidence file is "missing"
        r = await c.post(SEND, json={**_send_body(), "file_ids": ["F-B"]}, headers=_h("sitemanager"))
        assert r.status_code == 422
        assert r.json()["detail"]["error_code"] == "EVIDENCE_FILE_NOT_FOUND"
        assert await _dump(op) == before
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════════════ static
def test_every_write_route_has_its_permission_first_and_the_catalog_grants():
    from app.routes import assets_repairs as ar
    from app.permissions.catalog import PERMISSION_MATRIX, role_actions
    want = {
        ("POST", "/assets/units/{unit_id}/repair/send"): ar.SEND_ACTION,
        ("POST", "/assets/units/{unit_id}/repair/return"): ar.RETURN_ACTION,
        ("POST", "/assets/repairs/{repair_id}/handovers/{handover_id}/accept"): ar.HANDOVER_ACTION,
        ("POST", "/assets/repairs/{repair_id}/handovers/{handover_id}/refuse"): ar.HANDOVER_ACTION,
        ("POST", "/assets/repairs/{repair_id}/handovers/{handover_id}/problem"): ar.HANDOVER_ACTION,
        ("PUT", "/assets/repairs/{repair_id}/cost"): ar.COST_ACTION,
    }
    seen = {}
    for route in ar.router.routes:
        for m in route.methods - {"HEAD"}:
            if m == "GET":
                continue
            deps = [d.call for d in route.dependant.dependencies]
            first = deps[0]
            seen[(m, route.path)] = getattr(first, "asset_rep_action", None)
            params = list(inspect.signature(route.endpoint).parameters)
            assert "idempotency_key" in params, route.path
    assert seen == want
    custody = {ar.SEND_ACTION, ar.RETURN_ACTION, ar.HANDOVER_ACTION}
    for rid, acts in PERMISSION_MATRIX.items():
        has_cost = ar.COST_ACTION in acts
        assert has_cost == (rid in {"owner", "admin", "accountant"}), rid
        has_custody = custody <= acts
        assert has_custody == (rid in {"owner", "admin", "site_manager", "project_manager",
                                       "warehouse", "worker"}), rid
        assert not (custody & acts) or has_custody, rid
    for never in ("driver", "LEGACY_VIEWER", "LEGACY_TECHNICIAN"):
        assert not ({ar.COST_ACTION} | custody) & role_actions(never)
    assert role_actions("LEGACY_TECHNICIAN") == {"asset_intake.submit"}


def test_no_total_paid_and_the_read_strips_money():
    from app.routes import assets_repairs as ar
    src = inspect.getsource(ar)
    assert "total_paid\"" not in src.replace('r.pop("total_paid", None)', "")
    assert getattr(ar.list_repairs, "sec02_strips_money", False)
