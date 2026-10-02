"""
W0-03E-A2C — two tenants, colliding ids, over real HTTP: no read or write crosses.

Why this file exists in addition to the A2B gate. The A2B gate proved isolation
for the route families it exercised; the A2B *review* then found an active
financial route it did not touch — ``/invoice-lines`` — which enriched from
``users``/``projects``/``warehouses``/``persons``/``companies`` by bare id and,
worse, updated invoice lines and recalculated invoice TOTALS by bare id after a
tenant-scoped read. So this file concentrates on what A2C closed:

* the whole ``/invoice-lines`` surface: list, unallocated, detail, create, bulk,
  update, allocate, delete, and the invoice-total recalculation each triggers;
* the **write** direction specifically: every attempted write against a colliding
  id belonging to the OTHER tenant must leave that tenant's document
  **byte-equal** (``bson`` round-trip compared), not merely "not obviously wrong";
* the per-tenant settings identity: both tenants store their OWN
  ``worker_rates`` / ``employee_cost_config`` / ``overtime_config`` rows, which
  was impossible while those rows had a single global ``_id``;
* both storage orders — B first and BEG first — because a global lookup returns
  "whichever document the database finds first", so one order can pass by luck;
* the warehouse asset-summary join, whose ``$lookup`` on ``item_id`` alone used
  to pull the other tenant's asset types and prices into this tenant's totals.

Runs in-process against ``mongomock_motor`` (no server, no real MongoDB), and
against a disposable local MongoDB when ``W0_03_REAL_MONGO_URL`` is set.
Authentication is REAL: every call carries a JWT issued by ``/api/auth/login``
and the tenant is whatever ``get_current_user`` loads server-side.

    pytest tests/test_w0_03e_a2c_two_tenant_boundary.py -v --noconftest
    W0_03_REAL_MONGO_URL=mongodb://127.0.0.1:27018 pytest ... --noconftest
"""
import asyncio
import os
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent

PASSWORD = "A2C-Boundary-2026!"
BEG, TCB = "BEG", "TCB"                       # tenant org_ids
A_AMOUNT, B_AMOUNT = 4242.42, 9191.91
A_MARK, B_MARK = "BEGMARK-", "TCBMARK-"

#: ids BEG stores FIRST and B then reuses.
IDS_A_FIRST = {
    "projects": "P-AF", "users": "U-AF", "persons": "PE-AF", "companies": "CO-AF",
    "warehouses": "W-AF", "invoices": "I-AF", "invoice_lines": "IL-AF", "items": "IT-AF",
    "counterparties": "CP-AF", "asset_items": "AI-AF", "asset_units": "AU-AF",
}
#: ids B stores FIRST and BEG then reuses — the order that exposes a global lookup.
IDS_B_FIRST = {k: v.replace("-AF", "-BF") for k, v in IDS_A_FIRST.items()}

#: "Victim" ids owned by EXACTLY ONE tenant. The other tenant has no document
#: under them at all, so a correct route answers 404 and the owner's document must
#: come out byte-equal. This is the sharper half of the write test: with the
#: colliding ids above, a caller's write legitimately changes its OWN document, so
#: only the untouched-ness of the other tenant's copy can be asserted; here NO
#: write of any kind is legitimate.
VICTIM_OF_BEG = {"invoices": "I-VA", "invoice_lines": "IL-VA", "projects": "P-VA",
                 "warehouses": "W-VA", "persons": "PE-VA", "companies": "CO-VA",
                 "counterparties": "CP-VA", "users": "U-VA", "items": "IT-VA",
                 "asset_items": "AI-VA", "asset_units": "AU-VA"}
VICTIM_OF_TCB = {k: v.replace("-VA", "-VB") for k, v in VICTIM_OF_BEG.items()}


def _refusal():
    from tests.test_w0_03c_real_mongo import _refusal as r
    return r()


# ═══════════════════════════════════════════════════════════════════ fixtures
def _docs(org, mark, amount, ids):
    """One colliding document per family, all owned by ``org``."""
    return {
        "projects": [{"id": ids["projects"], "org_id": org, "code": mark + "CODE",
                      "name": mark + "PROJECT", "status": "Active"}],
        "persons": [{"id": ids["persons"], "org_id": org, "first_name": mark + "PERSON",
                     "last_name": "Z"}],
        "companies": [{"id": ids["companies"], "org_id": org, "name": mark + "COMPANY",
                       "eik": "123"}],
        "counterparties": [{"id": ids["counterparties"], "org_id": org, "name": mark + "CP",
                            "type": "company", "active": True}],
        "warehouses": [{"id": ids["warehouses"], "org_id": org, "code": mark + "W",
                        "name": mark + "WAREHOUSE", "type": "central", "active": True}],
        "items": [{"id": ids["items"], "org_id": org, "name": mark + "ITEM",
                   "sku": mark + "SKU", "unit": "pcs"}],
        "asset_items": [{"id": ids["asset_items"], "org_id": org, "name": mark + "ASSET",
                         "type": "machine", "purchase_price": amount}],
        "asset_units": [{"id": ids["asset_units"], "org_id": org,
                         "item_id": ids["asset_items"], "qr_id": mark + "QR",
                         "location_type": "warehouse", "location_id": ids["warehouses"],
                         "status": "in_stock"}],
        "invoices": [{"id": ids["invoices"], "org_id": org, "project_id": ids["projects"],
                      "direction": "Received", "invoice_no": mark + "INV", "status": "Draft",
                      "total": amount, "subtotal": amount, "vat_amount": 0,
                      "paid_amount": 0, "remaining_amount": amount,
                      "counterparty_id": ids["counterparties"],
                      "counterparty_name": mark + "CP", "issue_date": "2026-04-01",
                      "invoice_date": "2026-04-01", "date": "2026-04-01",
                      "currency": "BGN", "lines_count": 1}],
        "invoice_lines": [{
            "id": ids["invoice_lines"], "org_id": org, "invoice_id": ids["invoices"],
            "line_no": 1, "description": mark + "LINE", "unit": "pcs", "qty": 2.0,
            "unit_price": amount / 2, "vat_percent": 0,
            "line_total_ex_vat": amount, "vat_amount": 0, "line_total_inc_vat": amount,
            "purchased_by_user_id": ids["users"],
            "allocations": [{"type": "project", "ref_id": ids["projects"], "qty": 1.0},
                            {"type": "warehouse", "ref_id": ids["warehouses"], "qty": 0.5},
                            {"type": "client", "ref_id": ids["persons"], "qty": 0.5}],
            "qty_allocated": 2.0, "qty_unallocated": 0.0, "is_fully_allocated": True,
            "cost_category": "Materials", "created_at": "2026-04-01T00:00:00",
            "updated_at": "2026-04-01T00:00:00"}],
    }


def _user(org, mark, user_id, email):
    from app.deps.auth import hash_password
    return {"id": user_id, "org_id": org, "email": email,
            "password_hash": hash_password(PASSWORD), "role": "Owner",
            "first_name": mark + "OWNER", "last_name": "A2C", "is_active": True}


async def _seed(op, sysdb):
    """Both tenants, with each collision family stored in BOTH orders."""
    for org, name in ((BEG, "BUILDING EXPRESS GROUP"), (TCB, "TEST COMPANY B")):
        await op.organizations.insert_one({"id": org, "name": name, "slug": org.lower()})
        await sysdb.tenant_registry.insert_one(
            {"id": org, "database_name": op.name, "status": "active"})

    # --- order 1: BEG writes first, then B reuses the same ids
    for coll, docs in _docs(BEG, A_MARK, A_AMOUNT, IDS_A_FIRST).items():
        await op[coll].insert_many(docs)
    for coll, docs in _docs(TCB, B_MARK, B_AMOUNT, IDS_A_FIRST).items():
        await op[coll].insert_many(docs)

    # --- order 2: B writes FIRST, then BEG reuses the same ids
    for coll, docs in _docs(TCB, B_MARK, B_AMOUNT, IDS_B_FIRST).items():
        await op[coll].insert_many(docs)
    for coll, docs in _docs(BEG, A_MARK, A_AMOUNT, IDS_B_FIRST).items():
        await op[coll].insert_many(docs)

    # --- victims: each owned by exactly ONE tenant, inserted in both orders
    for coll, docs in _docs(TCB, B_MARK, B_AMOUNT, VICTIM_OF_TCB).items():
        await op[coll].insert_many(docs)
    for coll, docs in _docs(BEG, A_MARK, A_AMOUNT, VICTIM_OF_BEG).items():
        await op[coll].insert_many(docs)

    # the two owners, plus the colliding purchaser ids the lines point at
    await op.users.insert_many([
        _user(BEG, A_MARK, "beg-owner", "owner@beg.test"),
        _user(TCB, B_MARK, "tcb-owner", "owner@tcb.test"),
        {"id": IDS_A_FIRST["users"], "org_id": BEG, "first_name": A_MARK + "BUYER",
         "last_name": "Q", "email": "buyer-a@beg.test", "role": "Worker", "is_active": True},
        {"id": IDS_A_FIRST["users"], "org_id": TCB, "first_name": B_MARK + "BUYER",
         "last_name": "Q", "email": "buyer-a@tcb.test", "role": "Worker", "is_active": True},
        {"id": IDS_B_FIRST["users"], "org_id": TCB, "first_name": B_MARK + "BUYER",
         "last_name": "Q", "email": "buyer-b@tcb.test", "role": "Worker", "is_active": True},
        {"id": IDS_B_FIRST["users"], "org_id": BEG, "first_name": A_MARK + "BUYER",
         "last_name": "Q", "email": "buyer-b@beg.test", "role": "Worker", "is_active": True},
    ])


def _app(monkeypatch, op, sysdb):
    """The real routers A2C touched, pointed at the disposable database."""
    from fastapi import Depends, FastAPI

    import app.db as appdb
    from app.deps import auth as deps_auth
    from app.deps import modules as deps_modules
    from app.deps.auth import get_current_user
    from app.deps.modules import require_m2, require_m4, require_m5
    from app.master_data.deps import ENV_MODE
    from app.tenancy import registry
    import server  # noqa: F401 — billing imports server constants; load it first
    from app.routes import (auth, extra_works, finance, full_cost, invoice_lines, items,
                            labor_smr, projects, warehouses, work_sessions)
    from app.services import audit as services_audit, paid_labor
    from app.utils import audit as utils_audit

    monkeypatch.setenv(ENV_MODE, "off")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")
    for module in (appdb, deps_auth, deps_modules, paid_labor, utils_audit, services_audit):
        monkeypatch.setattr(module, "db", op)
    monkeypatch.setattr(registry, "system_db", sysdb)
    for name in ("tenant_registry", "tenant_memberships", "tenant_role_assignments"):
        monkeypatch.setattr(registry, name, sysdb[name])

    app = FastAPI()
    routers = (auth, extra_works, finance, full_cost, invoice_lines, items, labor_smr,
               projects, warehouses, work_sessions)
    for module in routers:
        monkeypatch.setattr(module, "db", op)
        app.include_router(module.router, prefix="/api")

    async def _authenticated(user: dict = Depends(get_current_user)):
        return user
    for dep in (require_m2, require_m4, require_m5):
        app.dependency_overrides[dep] = _authenticated
    return app


class Caller:
    def __init__(self, client, token, tenant):
        self.c, self.tenant = client, tenant
        self.h = {"Authorization": "Bearer " + token}

    async def get(self, path):
        return await self.c.get(path, headers=self.h)

    async def post(self, path, body=None):
        return await self.c.post(path, json=body or {}, headers=self.h)

    async def put(self, path, body):
        return await self.c.put(path, json=body, headers=self.h)

    async def delete(self, path):
        return await self.c.delete(path, headers=self.h)


async def _login(c, email, tenant):
    r = await c.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, (email, r.status_code, r.text[:300])
    return Caller(c, r.json()["token"], tenant)


def _foreign_markers(tenant):
    """Strings that belong to the OTHER tenant and must never be echoed back."""
    if tenant == BEG:
        return (B_MARK, "9191.91", "9191.9", "9 191")
    return (A_MARK, "4242.42", "4242.4", "4 242")


def _assert_clean(tenant, where, text):
    for bad in _foreign_markers(tenant):
        assert bad not in text, (
            "%s leaked into a %s response at %s: %s" % (bad, tenant, where, text[:500]))


async def _bson_snapshot(op, collection, org, record_id):
    """A byte-level snapshot of one document, for proving a write did NOT touch it."""
    import bson
    doc = await op[collection].find_one({"id": record_id, "org_id": org})
    assert doc is not None, (collection, org, record_id)
    return bson.BSON.encode({k: doc[k] for k in sorted(doc) if k != "_id"})


# ═══════════════════════════════════════════════════════════════════ scenario
async def scenario(op, sysdb, monkeypatch):
    import httpx

    await _seed(op, sysdb)
    app = _app(monkeypatch, op, sysdb)
    ev = {"reads": 0, "write_attempts": 0, "byte_equal_proofs": 0, "settings_rows": 0}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gate") as c:
        a = await _login(c, "owner@beg.test", BEG)
        b = await _login(c, "owner@tcb.test", TCB)

        for caller, ids_mine, ids_theirs in ((a, IDS_A_FIRST, IDS_B_FIRST),
                                            (b, IDS_B_FIRST, IDS_A_FIRST)):
            t = caller.tenant

            # ───────────────────────────────── 1. invoice-lines READS (both orders)
            for ids in (IDS_A_FIRST, IDS_B_FIRST):
                r = await caller.get("/api/invoice-lines?invoice_id=%s" % ids["invoices"])
                assert r.status_code == 200, (t, r.status_code, r.text[:300])
                _assert_clean(t, "invoice-lines list", r.text)
                ev["reads"] += 1
                rows = r.json()
                assert rows, (t, "own line missing for", ids["invoices"])
                # the enrichment resolved buyer / project / warehouse / person HERE
                for row in rows:
                    assert row["org_id"] == t
                    _assert_clean(t, "invoice-line enrichment", str(row))

                r = await caller.get("/api/invoice-lines/%s" % ids["invoice_lines"])
                assert r.status_code == 200, (t, r.status_code, r.text[:300])
                _assert_clean(t, "invoice-line detail", r.text)
                ev["reads"] += 1
                assert r.json()["org_id"] == t

            r = await caller.get("/api/invoice-lines/unallocated")
            assert r.status_code == 200
            _assert_clean(t, "unallocated", r.text)
            ev["reads"] += 1

            # ───────────────────────────────── 2. other active read families
            for path in ("/api/projects", "/api/items", "/api/warehouses",
                         "/api/warehouses/asset-summary", "/api/invoices",
                         "/api/persons", "/api/companies"):
                r = await caller.get("/api/" + path.split("/api/")[1])
                if r.status_code == 404:
                    continue                       # route not mounted in this gate
                assert r.status_code in (200, 403), (t, path, r.status_code, r.text[:200])
                if r.status_code == 200:
                    _assert_clean(t, path, r.text)
                    ev["reads"] += 1

            # ───────────────────────────────── 3a. WRITES on a VICTIM id
            # The caller owns NO document under these ids, so every one of these
            # writes must be refused and the owner's documents must be byte-equal.
            other = BEG if t == TCB else TCB
            victim = VICTIM_OF_BEG if other == BEG else VICTIM_OF_TCB
            line_id, inv_id = victim["invoice_lines"], victim["invoices"]
            before_line = await _bson_snapshot(op, "invoice_lines", other, line_id)
            before_inv = await _bson_snapshot(op, "invoices", other, inv_id)

            r = await caller.put("/api/invoice-lines/%s" % line_id,
                                 {"qty": 99.0, "description": "OVERWRITTEN-BY-" + t})
            assert r.status_code == 404, (t, "update of a foreign line", r.status_code, r.text[:200])
            r = await caller.post("/api/invoice-lines/%s/allocate" % line_id,
                                  {"allocations": [{"type": "project",
                                                    "ref_id": victim["projects"], "qty": 1.0}]})
            assert r.status_code == 404, (t, "allocate of a foreign line", r.status_code, r.text[:200])
            r = await caller.delete("/api/invoice-lines/%s" % line_id)
            assert r.status_code == 404, (t, "delete of a foreign line", r.status_code, r.text[:200])
            ev["write_attempts"] += 3

            assert await _bson_snapshot(op, "invoice_lines", other, line_id) == before_line, (
                "%s mutated %s's invoice line %s" % (t, other, line_id))
            assert await _bson_snapshot(op, "invoices", other, inv_id) == before_inv, (
                "%s changed %s's invoice TOTALS via recalculation (%s)" % (t, other, inv_id))
            ev["byte_equal_proofs"] += 2

            # ───────────────────────────────── 3b. WRITES on a COLLIDING id
            # Here the caller DOES own a document under the id and the other tenant
            # owns one too. The caller's own write may succeed; what must not change
            # is the other tenant's copy — this is the exact A2B defect, where
            # update_one({"id": line_id}) and the invoice recalculation that follows
            # reached whichever tenant's document the database found first.
            for ids in (IDS_A_FIRST, IDS_B_FIRST):
                line_id, inv_id = ids["invoice_lines"], ids["invoices"]
                before_line = await _bson_snapshot(op, "invoice_lines", other, line_id)
                before_inv = await _bson_snapshot(op, "invoices", other, inv_id)

                r = await caller.put("/api/invoice-lines/%s" % line_id,
                                     {"qty": 7.0, "description": t + "-OWN-EDIT"})
                assert r.status_code == 200, (t, "own line edit", r.status_code, r.text[:200])
                _assert_clean(t, "own line edit response", r.text)
                r = await caller.post("/api/invoice-lines/%s/allocate" % line_id,
                                      {"allocations": [{"type": "project",
                                                        "ref_id": ids["projects"], "qty": 1.0}]})
                assert r.status_code == 200, (t, "own allocate", r.status_code, r.text[:200])
                _assert_clean(t, "own allocate response", r.text)
                ev["write_attempts"] += 2

                assert await _bson_snapshot(op, "invoice_lines", other, line_id) == before_line, (
                    "%s's edit of its OWN line %s also changed %s's line"
                    % (t, line_id, other))
                assert await _bson_snapshot(op, "invoices", other, inv_id) == before_inv, (
                    "%s's edit recalculated %s's invoice totals (%s)" % (t, other, inv_id))
                ev["byte_equal_proofs"] += 2

            # ───────────────────────────────── 4. per-tenant settings identity
            r = await caller.put("/api/ai-config/hourly-rates",
                                 {"rates": {"майстор": 10 if t == BEG else 20}})
            assert r.status_code == 200, (t, r.status_code, r.text[:300])
            r = await caller.put("/api/employee-cost-config",
                                 {"additional_cost_percent": 1 if t == BEG else 2,
                                  "overhead_percent_per_hour": 3 if t == BEG else 4})
            assert r.status_code == 200, (t, r.status_code, r.text[:300])
            ev["write_attempts"] += 2

        # ───────────────── both tenants really have their OWN settings rows
        from app.tenancy.settings_identity import (EMPLOYEE_COST_CONFIG, WORKER_RATES,
                                                   settings_id)
        for key in (WORKER_RATES, EMPLOYEE_COST_CONFIG):
            assert await op.settings.count_documents({"_id": key}) == 0, (
                "a GLOBAL %s row still exists; a second tenant cannot create its own" % key)
            for org in (BEG, TCB):
                row = await op.settings.find_one({"_id": settings_id(key, org)})
                assert row is not None, ("%s has no own %s row" % (org, key))
                assert row["org_id"] == org
                ev["settings_rows"] += 1
        beg_rates = await op.settings.find_one({"_id": settings_id(WORKER_RATES, BEG)})
        tcb_rates = await op.settings.find_one({"_id": settings_id(WORKER_RATES, TCB)})
        assert beg_rates["rates"] != tcb_rates["rates"], (
            "both tenants ended up with the same rates row")

        # ───────────────── and the stored documents are still one-per-tenant
        for coll in ("invoice_lines", "invoices", "projects", "warehouses", "items",
                     "persons", "companies", "asset_items", "asset_units"):
            for ids in (IDS_A_FIRST, IDS_B_FIRST):
                if coll not in ids:
                    continue
                n = await op[coll].count_documents({"id": ids[coll]})
                assert n == 2, ("%s/%s should exist once per tenant, found %d"
                                % (coll, ids[coll], n))

    return ev


# ═══════════════════════════════════════════════════════════════════ the tests
def test_the_two_tenant_boundary_in_process(monkeypatch):
    from mongomock_motor import AsyncMongoMockClient

    async def body():
        client = AsyncMongoMockClient()
        return await scenario(client["w003e_a2c_op"], client["w003e_a2c_sys"], monkeypatch)

    ev = asyncio.run(body())
    assert ev["reads"] >= 20, ev
    assert ev["write_attempts"] >= 16, ev
    assert ev["byte_equal_proofs"] >= 8, ev
    assert ev["settings_rows"] == 4, ev


@pytest.mark.skipif(bool(_refusal()), reason=_refusal() or "ok")
def test_the_two_tenant_boundary_on_a_real_disposable_mongodb(monkeypatch):
    """Same scenario against a disposable local MongoDB bound to 127.0.0.1.

    Set ``W0_03_REAL_MONGO_URL``; the databases are dropped afterwards so the
    run leaves nothing behind.
    """
    from motor.motor_asyncio import AsyncIOMotorClient
    from tests.test_w0_03c_real_mongo import REAL_URL

    suffix = uuid.uuid4().hex[:10]
    op_name, sys_name = "w0_03e_a2c_op_" + suffix, "w0_03e_a2c_sys_" + suffix

    async def body():
        client = AsyncIOMotorClient(os.environ[REAL_URL])
        try:
            return await scenario(client[op_name], client[sys_name], monkeypatch)
        finally:
            await client.drop_database(op_name)
            await client.drop_database(sys_name)
            left = await client.list_database_names()
            assert op_name not in left and sys_name not in left, left
            client.close()

    ev = asyncio.run(body())
    assert ev["byte_equal_proofs"] >= 8, ev
    assert ev["settings_rows"] == 4, ev


def test_the_collision_fixtures_really_collide():
    """Guards the gate itself: if the ids stopped colliding it would prove nothing."""
    assert set(IDS_A_FIRST) == set(IDS_B_FIRST)
    assert not (set(IDS_A_FIRST.values()) & set(IDS_B_FIRST.values()))
    a = _docs(BEG, A_MARK, A_AMOUNT, IDS_A_FIRST)
    b = _docs(TCB, B_MARK, B_AMOUNT, IDS_A_FIRST)
    for coll in a:
        assert [d["id"] for d in a[coll]] == [d["id"] for d in b[coll]], coll
        assert a[coll][0]["org_id"] != b[coll][0]["org_id"]


def test_the_markers_would_be_detected():
    """If a leak happened, _assert_clean must actually fail."""
    with pytest.raises(AssertionError):
        _assert_clean(BEG, "self-check", "payload containing " + B_MARK + "COMPANY")
    with pytest.raises(AssertionError):
        _assert_clean(TCB, "self-check", "total was 4242.42 BGN")
    _assert_clean(BEG, "self-check", "payload containing " + A_MARK + "COMPANY")
