"""
LIVE-OPS-01 / TASK 5A — the read-only Control Center projection.

What these tests hold onto (TASK 5A required evidence):

* warehouse display: the human-readable ``name`` is the label, ``code`` is
  secondary, a nameless warehouse never falls back to its code, and a legacy
  ``main`` warehouse is surfaced as an integrity warning;
* stale / incomplete / unreconciled data is never presented as trusted: the
  stock totals carry ``trust = "untrusted"`` with reasons, and the projection
  reads the COMPLETE ledger (> 1000 movements) while warning that the legacy
  ``/inventory`` screen under-counts;
* an accepted custodian and a pending handover are two separate fields;
* two tenants with colliding ids, stored in both orders: no read crosses;
* no write: every collection is byte-equal before and after the call, the
  module contains no write call, and the router exposes only ``GET``;
* direct URL access stays read-only: POST/PUT/PATCH/DELETE are refused;
* the REAL route dependency is exercised (no override): an expired trial is
  denied exactly like ``require_m2`` denies it, and nothing is persisted;
* one tenant path: a session whose ``active_tenant_id`` differs from its
  ``org_id`` is refused; enforce-mode audit is read only from the operational
  database;
* legacy parallel material writers are counted and warned about, never summed;
  a movement that cannot be projected makes the stock projection incomplete;
* the activity preview reads canonical ``audit_events`` only — a legacy
  ``audit_logs`` row is never shown — and says so when none exists.

Runs in-process against ``mongomock_motor`` (no MongoDB server). Authentication
is REAL: every call carries a JWT from ``/api/auth/login`` and the tenant is
whatever ``get_current_user`` loads server-side. A disposable real MongoDB is
used only when ``W0_03_REAL_MONGO_URL`` is set (never production).

    pytest tests/test_live_ops_a_read_only.py -v --noconftest
"""
import ast
import asyncio
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
MODULE = BACKEND / "app" / "routes" / "live_ops.py"

PASSWORD = "LiveOps-A-2026!"
BEG, TCB = "BEG", "TCB"
A_MARK, B_MARK = "BEGMARK-", "TCBMARK-"
URL = "/api/live-ops/control-center"
LEGACY_TXNS = 1205          # more than the legacy screen's to_list(1000)

YESTERDAY = (date.today() - timedelta(days=3)).isoformat()
TOMORROW = (date.today() + timedelta(days=5)).isoformat()

#: ids both tenants use — inserted in BOTH orders.
SHARED = {"wh": "W-SHARED", "proj": "P-SHARED", "item": "AI-SHARED",
          "unit_acc": "AU-ACC", "unit_pen": "AU-PEN", "unit_rep": "AU-REP",
          "req": "MR-SHARED", "user": "U-SHARED"}


def _refusal():
    from tests.test_w0_03c_real_mongo import _refusal as r
    return r()


# ═══════════════════════════════════════════════════════════════════ fixtures
def _user(org, mark, user_id, email, role="Owner"):
    from app.deps.auth import hash_password
    return {"id": user_id, "org_id": org, "email": email,
            "password_hash": hash_password(PASSWORD), "role": role,
            "first_name": mark + "OWNER", "last_name": "LO", "is_active": True}


def _tenant_docs(org, mark, qty_scale):
    """One tenant's operational data; ids collide with the other tenant."""
    return {
        "warehouses": [
            {"id": SHARED["wh"], "org_id": org, "code": mark + "CODE",
             "name": mark + "Централен склад Хаджи Димитър", "type": "central", "active": True},
            {"id": "W-MAIN-" + org, "org_id": org, "code": None,
             "name": mark + "Основен склад", "type": "main", "active": True},
            {"id": "W-NONAME-" + org, "org_id": org, "code": mark + "ONLYCODE",
             "name": "", "type": "central", "active": True},
        ],
        "projects": [{"id": SHARED["proj"], "org_id": org, "code": mark + "P",
                      "name": mark + "Обект Витоша", "status": "Active"}],
        "users": [{"id": SHARED["user"], "org_id": org, "first_name": mark + "Иван",
                   "last_name": "Петров", "email": "u-%s@x.test" % org, "role": "Technician",
                   "is_active": True}],
        "asset_items": [{"id": SHARED["item"], "org_id": org, "name": mark + "Перфоратор",
                         "type": "tool", "purchase_price": 100 * qty_scale}],
        "asset_units": [
            {"id": SHARED["unit_acc"], "org_id": org, "item_id": SHARED["item"],
             "qr_id": mark + "QR1", "status": "in_use", "location_type": "employee",
             "location_id": SHARED["user"]},
            {"id": SHARED["unit_pen"], "org_id": org, "item_id": SHARED["item"],
             "qr_id": mark + "QR2", "status": "in_use", "location_type": "project",
             "location_id": SHARED["proj"]},
            {"id": SHARED["unit_rep"], "org_id": org, "item_id": SHARED["item"],
             "qr_id": mark + "QR3", "status": "repair", "location_type": "warehouse",
             "location_id": SHARED["wh"]},
        ],
        "asset_custody": [
            {"id": "C-ACC-" + org, "org_id": org, "unit_id": SHARED["unit_acc"],
             "custodian_user_id": SHARED["user"], "status": "accepted",
             "given_by_user_id": SHARED["user"], "given_at": "2026-10-01T08:00:00+00:00",
             "accepted_at": "2026-10-01T09:00:00+00:00"},
            {"id": "C-PEN-" + org, "org_id": org, "unit_id": SHARED["unit_pen"],
             "custodian_user_id": SHARED["user"], "status": "given",
             "given_by_user_id": SHARED["user"], "given_at": "2026-10-09T08:00:00+00:00",
             "accepted_at": None},
            {"id": "C-OLD-" + org, "org_id": org, "unit_id": SHARED["unit_pen"],
             "custodian_user_id": SHARED["user"], "status": "released",
             "given_by_user_id": SHARED["user"], "given_at": "2026-09-01T08:00:00+00:00"},
        ],
        "asset_repairs": [{"id": "R-" + org, "org_id": org, "unit_id": SHARED["unit_rep"],
                           "status": "in_repair", "service": mark + "Сервиз",
                           "issue": "мотор", "sent_at": "2026-10-05"}],
        "material_requests": [
            {"id": SHARED["req"], "org_id": org, "project_id": SHARED["proj"],
             "request_number": mark + "MR-0001", "status": "submitted",
             "needed_date": YESTERDAY, "created_at": "2026-10-01T00:00:00+00:00",
             "lines": [{"id": "L1", "material_name": mark + "Цимент", "qty_requested": 10,
                        "qty_fulfilled": 0, "unit": "торба"}]},
            {"id": "MR-DRAFT-" + org, "org_id": org, "project_id": SHARED["proj"],
             "request_number": mark + "MR-0002", "status": "draft",
             "needed_date": TOMORROW, "created_at": "2026-10-02T00:00:00+00:00", "lines": []},
            {"id": "MR-NODATE-" + org, "org_id": org, "project_id": SHARED["proj"],
             "request_number": mark + "MR-0003", "status": "draft",
             "created_at": "2026-10-03T00:00:00+00:00", "lines": []},
            {"id": "MR-FUL-" + org, "org_id": org, "project_id": SHARED["proj"],
             "request_number": mark + "MR-0004", "status": "fulfilled",
             "needed_date": YESTERDAY, "created_at": "2026-09-01T00:00:00+00:00", "lines": []},
        ],
        "warehouse_batches": [{"id": "B-" + org, "org_id": org, "warehouse_id": SHARED["wh"],
                               "item_id": "X", "qty": 1}],
        # Legacy parallel writers (contract §2.5.1) — the material name collides
        # with the ledger on purpose: if these were summed, the totals would move.
        "project_material_ops": [{"id": "PMO-%s-%d" % (org, i), "org_id": org,
                                  "project_id": SHARED["proj"], "material_name": mark + "Цимент",
                                  "unit": "торба", "qty": 999} for i in range(2)],
        "material_consumption_log": [{"id": "MCL-%s-%d" % (org, i), "org_id": org,
                                      "project_id": SHARED["proj"], "material_name": mark + "Цимент",
                                      "unit": "торба", "qty": 777} for i in range(3)],
        "audit_logs": [{"id": "AL-" + org, "org_id": org, "action": mark + "LEGACYAUDIT",
                        "entity_type": "warehouse_transaction"}],
    }


def _ledger(org, mark, qty_scale):
    """> 1000 movements so a capped read would visibly under-count."""
    txns = []
    for i in range(LEGACY_TXNS):
        txns.append({"id": "T-%s-%d" % (org, i), "org_id": org, "warehouse_id": SHARED["wh"],
                     "type": "intake", "created_at": "2026-10-%02dT10:00:00+00:00" % (1 + i % 9),
                     "lines": [{"material_name": mark + "Цимент", "unit": "торба",
                                "qty_received": 1 * qty_scale, "total_price": 10 * qty_scale}]})
    txns.append({"id": "T-ISSUE-" + org, "org_id": org, "warehouse_id": SHARED["wh"],
                 "type": "issue", "created_at": "2026-10-09T12:00:00+00:00",
                 "lines": [{"material_name": mark + "Цимент", "unit": "торба",
                            "qty_issued": 5 * qty_scale, "total_price": 50 * qty_scale}]})
    txns.append({"id": "T-NEG-" + org, "org_id": org, "warehouse_id": "W-MAIN-" + org,
                 "type": "issue", "created_at": "2026-10-09T13:00:00+00:00",
                 "lines": [{"material_name": mark + "Лепило", "unit": "кг", "qty_issued": 3}]})
    txns.append({"id": "T-NOWH-" + org, "org_id": org, "warehouse_id": None,
                 "type": "return", "created_at": "2026-10-09T14:00:00+00:00",
                 "lines": [{"material_name": mark + "Цимент", "unit": "торба", "qty_returned": 1}]})
    txns.append({"id": "T-ODD-" + org, "org_id": org, "warehouse_id": SHARED["wh"],
                 "type": "legacy_adjust", "created_at": "2026-10-09T15:00:00+00:00",
                 "lines": [{"material_name": mark + "Цимент", "unit": "торба", "qty_received": 500}]})
    return txns


async def _seed(op, sysdb, order):
    for org, name in ((BEG, "BUILDING EXPRESS GROUP"), (TCB, "TEST COMPANY B")):
        await op.organizations.insert_one({"id": org, "name": name, "slug": org.lower()})
        await sysdb.tenant_registry.insert_one({"id": org, "database_name": op.name,
                                                "status": "active"})
        await op.subscriptions.insert_one({"org_id": org, "plan_id": "pro", "status": "active"})
    first, second = ((BEG, A_MARK, 1), (TCB, B_MARK, 7)) if order == "A" else \
        ((TCB, B_MARK, 7), (BEG, A_MARK, 1))
    for org, mark, scale in (first, second):
        for coll, docs in _tenant_docs(org, mark, scale).items():
            await op[coll].insert_many(docs)
        await op.warehouse_transactions.insert_many(_ledger(org, mark, scale))
    await op.users.insert_many([
        _user(BEG, A_MARK, "beg-owner", "owner@beg.test"),
        _user(TCB, B_MARK, "tcb-owner", "owner@tcb.test"),
        _user(BEG, A_MARK, "beg-tech", "tech@beg.test", role="Technician"),
    ])
    # One canonical LIVE-OPS event for BEG only (the TCB tenant must not see it).
    await op.audit_events.insert_one({
        "event_id": "EV-BEG-1", "tenant_id": BEG, "sequence": 1, "action": "asset_unit.viewed",
        "entity_type": "asset_unit", "entity_id": SHARED["unit_acc"], "actor_type": "human",
        "actor_id": "beg-owner", "occurred_at": "2026-10-09T15:00:00+00:00",
        "source_flow": "FLOW-011", "result": "success"})


def _app(monkeypatch, op, sysdb):
    from fastapi import FastAPI

    import app.db as appdb
    from app.deps import auth as deps_auth
    from app.deps import modules as deps_modules
    from app.master_data.deps import ENV_MODE
    from app.tenancy import registry
    import server  # noqa: F401 — route modules import server constants
    from app.routes import auth, live_ops
    from app.utils import audit as utils_audit
    from app.services import audit as services_audit

    monkeypatch.setenv(ENV_MODE, "off")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")
    for module in (appdb, deps_auth, deps_modules, utils_audit, services_audit, auth, live_ops):
        monkeypatch.setattr(module, "db", op)
    monkeypatch.setattr(registry, "system_db", sysdb)
    for name in ("tenant_registry", "tenant_memberships", "tenant_role_assignments"):
        monkeypatch.setattr(registry, name, sysdb[name])

    app = FastAPI()
    app.include_router(auth.router, prefix="/api")
    app.include_router(live_ops.router, prefix="/api")

    # No dependency override: every call runs the route's REAL dependencies,
    # including its read-only M2 gate, so the byte-equal proof covers them.
    assert not app.dependency_overrides
    return app


async def _login(c, email):
    r = await c.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, (email, r.status_code, r.text[:300])
    return {"Authorization": "Bearer " + r.json()["token"]}


async def _snapshot(op):
    """Every document of every collection, BSON-encoded, for a byte-equal proof."""
    import bson
    out = {}
    for name in sorted(await op.list_collection_names()):
        docs = await op[name].find({}).to_list(None)
        out[name] = sorted(bson.BSON.encode({k: d[k] for k in sorted(d) if k != "_id"})
                           for d in docs)
    return out


def _foreign(tenant):
    return B_MARK if tenant == BEG else A_MARK


# ═══════════════════════════════════════════════════════════════════ scenario
async def scenario(op, sysdb, monkeypatch, order):
    import httpx

    await _seed(op, sysdb, order)
    # Login writes (last-login stamps etc.) happen BEFORE the snapshot.
    app = _app(monkeypatch, op, sysdb)
    ev = {}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://gate") as c:
        ha = await _login(c, "owner@beg.test")
        hb = await _login(c, "owner@tcb.test")
        ht = await _login(c, "tech@beg.test")

        before = await _snapshot(op)
        ra = await c.get(URL, headers=ha)
        rb = await c.get(URL, headers=hb)
        rt = await c.get(URL, headers=ht)
        after = await _snapshot(op)

        # ── no write: byte-equal database across three reads
        assert before == after, "the read-only projection changed stored data"
        ev["byte_equal"] = True

        # ── role guard
        assert rt.status_code == 403, rt.text[:200]

        # ── direct URL stays read-only
        for method in ("post", "put", "patch", "delete"):
            r = await getattr(c, method)(URL, headers=ha)
            assert r.status_code == 405, (method, r.status_code)
        ev["direct_url_refused"] = 4
        assert await _snapshot(op) == before

        assert ra.status_code == 200, ra.text[:300]
        assert rb.status_code == 200, rb.text[:300]
        a, b = ra.json(), rb.json()

        # ── tenant separation (colliding ids, both storage orders)
        for tenant, body in ((BEG, a), (TCB, b)):
            text = ra.text if tenant == BEG else rb.text
            assert _foreign(tenant) not in text, "%s saw the other tenant's data" % tenant
            assert "LEGACYAUDIT" not in text, "legacy audit_logs leaked into the preview"
        ev["tenant_clean"] = True
        ev["a"], ev["b"] = a, b
    return ev


def _run(monkeypatch, order):
    from mongomock_motor import AsyncMongoMockClient

    async def body():
        client = AsyncMongoMockClient()
        return await scenario(client["lo_a_op_" + order], client["lo_a_sys_" + order],
                              monkeypatch, order)
    return asyncio.run(body())


@pytest.fixture(params=["A", "B"], ids=["BEG-first", "TCB-first"])
def ev(request, monkeypatch):
    return _run(monkeypatch, request.param)


# ═══════════════════════════════════════════════════════════════════ tests
def test_read_only_and_tenant_separated(ev):
    assert ev["byte_equal"] and ev["tenant_clean"] and ev["direct_url_refused"] == 4
    assert ev["a"]["read_only"] is True


def test_warehouse_name_is_the_primary_label(ev):
    whs = ev["a"]["warehouses"]["warehouses"]
    by_id = {w["id"]: w for w in whs}
    central = by_id[SHARED["wh"]]
    assert central["label"] == A_MARK + "Централен склад Хаджи Димитър"
    assert central["code"] == A_MARK + "CODE"          # still there, but secondary
    assert central["label"] != central["code"]
    nameless = by_id["W-NONAME-" + BEG]
    assert nameless["label"] == "Склад без име"         # never the code alone
    assert A_MARK + "ONLYCODE" not in nameless["label"]
    main = by_id["W-MAIN-" + BEG]
    assert main["is_legacy_main"] is True and main["code"] is None
    # Sorted by human name, not by code.
    labels = [w["label"] for w in whs]
    assert labels == sorted(labels, key=str.lower)
    codes = {w["code"] for w in ev["a"]["integrity"]}
    assert "LEGACY_MAIN_WAREHOUSE" in codes


def test_stock_reads_the_complete_ledger_and_is_not_trusted(ev):
    for body, scale in ((ev["a"], 1), (ev["b"], 7)):
        st = body["warehouses"]
        # Every movement was read, but two could not be projected (one without a
        # warehouse, one of an unknown type): the projection is NOT complete.
        assert st["movement_count"] == LEGACY_TXNS + 4
        assert st["complete"] is False and st["unprojectable_movements"] == 2
        assert st["trust"] == "untrusted" and st["trust_reasons"]
        central = next(w for w in st["warehouses"] if w["id"] == SHARED["wh"])
        cement = central["items"][0]
        # 1205 intakes − 5 issued, all counted (a to_list(1000) read gives 995).
        # The unknown-type movement (+500) and the legacy parallel stores
        # (999s and 777s) are NOT in the total: warehouse_transactions only.
        assert cement["qty"] == (LEGACY_TXNS - 5) * scale
        assert "value" not in cement and "value_unverified" in cement
        d = st["diagnostics"]
        assert d["movements_without_warehouse"] == 1
        assert d["negative_positions"] == 1
        assert d["batch_projection_rows"] == 1
        assert d["movements_unknown_type"] == 1 and d["unprojectable_movements"] == 2
        assert d["legacy_parallel_sources"] == {"project_material_ops": 2,
                                                "material_consumption_log": 3}
        assert any("Проекцията е непълна" in r for r in st["trust_reasons"])
        assert any("project_material_ops" in r for r in st["trust_reasons"])
        warn = {w["code"]: w for w in body["integrity"]}
        assert warn["STOCK_UNRECONCILED"]["count"] == 1 + 2
        assert warn["LEGACY_PARALLEL_STOCK_SOURCE"]["count"] == 5
        assert st["source"] and st["generated_at"] and st["last_movement_at"]
        codes = {w["code"] for w in body["integrity"]}
        assert {"STOCK_UNRECONCILED", "NEGATIVE_STOCK", "STOCK_VALUE_UNVERIFIED",
                "LEGACY_STOCK_TRUNCATED", "FREE_TEXT_MATERIAL",
                "LEGACY_PARALLEL_STOCK_SOURCE"} <= codes


def test_pending_handover_is_separate_from_accepted_custody(ev):
    assets = ev["a"]["assets"]
    units = {u["id"]: u for u in assets["items"]}
    acc, pen, rep = units[SHARED["unit_acc"]], units[SHARED["unit_pen"]], units[SHARED["unit_rep"]]
    assert acc["accepted_custodian"]["name"] == A_MARK + "Иван Петров"
    assert acc["pending_handover"] is None
    assert pen["pending_handover"]["to_name"] == A_MARK + "Иван Петров"
    assert pen["accepted_custodian"] is None            # pending is NOT responsibility
    assert assets["pending_handovers"] == 1 and assets["accepted_custody"] == 1
    # Human-readable locations, never raw ids.
    assert acc["location"]["name"] == A_MARK + "Иван Петров" and acc["indicator"] == "with_person"
    assert pen["location"]["name"] == A_MARK + "Обект Витоша" and pen["indicator"] == "on_project"
    assert rep["location"]["name"] == A_MARK + "Централен склад Хаджи Димитър"
    assert rep["indicator"] == "in_repair" and rep["repair"]["service"] == A_MARK + "Сервиз"
    assert assets["overdue"]["supported"] is False and assets["overdue"]["value"] is None
    # Pending handovers are listed first.
    assert assets["items"][0]["id"] == SHARED["unit_pen"]
    assert "PENDING_CUSTODY" in {w["code"] for w in ev["a"]["integrity"]}


def test_requests_counts_only_what_is_derivable(ev):
    rq = ev["a"]["requests"]
    c = rq["counts"]
    assert rq["total"] == 4
    assert c["open"] == 3 and c["pending"] == 1 and c["overdue"] == 1
    assert c["open_without_needed_date"] == 1 and c["fulfilled_legacy"] == 1
    assert rq["partial"]["derivable"] is False and rq["partial"]["value"] is None
    first = rq["items"][0]
    assert first["overdue"] is True and first["project_name"] == A_MARK + "Обект Витоша"
    assert first["link"] == "/procurement"
    assert all(i["status"] != "fulfilled" for i in rq["items"])
    codes = {w["code"] for w in ev["a"]["integrity"]}
    assert {"REQUEST_FULFILLED_BY_INVOICE", "FREE_TEXT_MATERIAL_REQUESTS"} <= codes


def test_audit_preview_is_canonical_only_and_tenant_scoped(ev):
    a, b = ev["a"]["audit"], ev["b"]["audit"]
    assert a["status"] == "available" and [e["event_id"] for e in a["events"]] == ["EV-BEG-1"]
    assert a["legacy_audit_used"] is False
    assert b["status"] == "unavailable" and b["events"] == []
    assert "Каноничен AuditEvent не е наличен" in b["message"]
    assert "AUDIT_READINESS" in {w["code"] for w in ev["b"]["integrity"]}
    assert "PERMISSION_READINESS" in {w["code"] for w in ev["a"]["integrity"]}


def test_a_failing_section_is_reported_not_hidden(monkeypatch):
    from app.routes import live_ops

    async def boom(*_a, **_k):
        raise RuntimeError("simulated read failure")
    monkeypatch.setattr(live_ops, "_assets_section", boom)
    body = _run(monkeypatch, "A")["a"]
    assert body["assets"]["status"] == "error" and "items" not in body["assets"]
    assert body["requests"]["status"] == "ok" and body["warehouses"]["status"] == "ok"
    assert "SECTION_UNAVAILABLE" in {w["code"] for w in body["integrity"]}


# ═══════════════════════════════════════════════════════ correction loop 1/2
def _with_app(monkeypatch, body, prepare=None):
    """Seed (BEG first), optionally adjust the data, log in, run ``body``."""
    import httpx
    from mongomock_motor import AsyncMongoMockClient

    async def run():
        client = AsyncMongoMockClient()
        op, sysdb = client["lo_c_op"], client["lo_c_sys"]
        await _seed(op, sysdb, "A")
        if prepare:
            await prepare(op, sysdb)
        app = _app(monkeypatch, op, sysdb)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://gate") as c:
            ha = await _login(c, "owner@beg.test")
            return await body(c, op, sysdb, ha)
    return asyncio.run(run())


def test_expired_trial_is_denied_by_the_real_dependency_without_any_write(monkeypatch):
    """CODEX #1: the real route dependency, not an override."""
    async def expire(op, _sys):
        await op.subscriptions.update_one(
            {"org_id": BEG}, {"$set": {"status": "trialing", "plan_id": "pro",
                                       "trial_ends_at": "2026-01-01T00:00:00+00:00"}})

    async def body(c, op, _sys, ha):
        before = await _snapshot(op)
        r = await c.get(URL, headers=ha)
        assert r.status_code == 403, r.text[:300]
        # Same outcome and message as the shared require_m2 gate.
        assert r.json()["detail"] == "Subscription past_due. Please upgrade your plan."
        assert await _snapshot(op) == before, "the GET persisted the trial expiry"
        sub = await op.subscriptions.find_one({"org_id": BEG})
        assert sub["status"] == "trialing"

        # Contrast: the shared helper WOULD have written. This proves the test
        # can see the write the read-only gate avoids.
        from app.deps.modules import check_module_access_for_org
        allowed, _ = await check_module_access_for_org(BEG, "M2")
        assert allowed is False
        assert (await op.subscriptions.find_one({"org_id": BEG}))["status"] == "past_due"
        return True
    assert _with_app(monkeypatch, body, expire)


def test_read_only_gate_matches_require_m2_outcomes():
    """The pure evaluation gives the shared helper's allow/deny for each state."""
    from datetime import datetime, timezone
    from app.routes.live_ops import _m2_decision
    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    assert _m2_decision(None, now) == "No subscription"
    assert _m2_decision({"plan_id": "pro", "status": "active"}, now) is None
    assert _m2_decision({"plan_id": "free", "status": "active"}, now) == "Module not in your current plan"
    for st in ("canceled", "past_due", "incomplete"):
        assert _m2_decision({"plan_id": "pro", "status": st}, now) == \
            "Subscription %s. Please upgrade your plan." % st
    live_trial = {"plan_id": "pro", "status": "trialing", "trial_ends_at": "2026-12-01T00:00:00Z"}
    assert _m2_decision(live_trial, now) is None
    expired = {"plan_id": "pro", "status": "trialing", "trial_ends_at": "2026-10-01T00:00:00Z"}
    assert _m2_decision(expired, now) == "Subscription past_due. Please upgrade your plan."


def test_active_tenant_different_from_org_is_refused_and_never_mixed(monkeypatch):
    """CODEX #2: org_id = BEG, active_tenant_id = TCB (colliding ids everywhere)."""
    async def body(c, op, _sys, ha):
        # TCB also has a canonical LIVE-OPS event under a colliding entity id.
        await op.audit_events.insert_one({
            "event_id": "EV-TCB-1", "tenant_id": TCB, "sequence": 1, "action": "asset_unit.viewed",
            "entity_type": "asset_unit", "entity_id": SHARED["unit_acc"], "actor_type": "human",
            "actor_id": "tcb-owner", "occurred_at": "2026-10-09T15:00:00+00:00",
            "source_flow": "FLOW-011", "result": "success"})
        await op.users.update_one({"id": "beg-owner", "org_id": BEG},
                                  {"$set": {"active_tenant_id": TCB}})
        before = await _snapshot(op)
        r = await c.get(URL, headers=ha)
        assert r.status_code == 409, r.text[:300]
        assert r.json()["detail"]["error_code"] == "LIVE_OPS_TENANT_PATH_MISMATCH"
        for leak in (A_MARK, B_MARK, "EV-TCB-1", "EV-BEG-1"):
            assert leak not in r.text
        assert await _snapshot(op) == before

        # active_tenant_id == org_id: served, and audit is BEG's only.
        await op.users.update_one({"id": "beg-owner", "org_id": BEG},
                                  {"$set": {"active_tenant_id": BEG}})
        r = await c.get(URL, headers=ha)
        assert r.status_code == 200, r.text[:300]
        body_ = r.json()
        assert [e["event_id"] for e in body_["audit"]["events"]] == ["EV-BEG-1"]
        assert body_["audit"]["tenant_id"] == BEG
        assert B_MARK not in r.text and "EV-TCB-1" not in r.text
        return True
    assert _with_app(monkeypatch, body)


def test_enforce_mode_audit_reads_only_the_operational_database(monkeypatch):
    """CODEX #2: enforce-mode resolution, without any Permission Service change."""
    async def body(c, op, sysdb, ha):
        monkeypatch.setenv("PERMISSION_SERVICE_MODE", "enforce")
        # Registry maps BEG to the operational database -> canonical events shown.
        r = await c.get(URL, headers=ha)
        assert r.status_code == 200, r.text[:300]
        assert [e["event_id"] for e in r.json()["audit"]["events"]] == ["EV-BEG-1"]

        # Registry maps BEG to ANOTHER database -> fail closed, nothing mixed.
        await sysdb.tenant_registry.update_one({"id": BEG},
                                               {"$set": {"database_name": "some_other_db"}})
        before = await _snapshot(op)
        r = await c.get(URL, headers=ha)
        assert r.status_code == 200, r.text[:300]
        audit = r.json()["audit"]
        assert audit["status"] == "unavailable" and audit["fail_closed"] is True
        assert audit["events"] == [] and "EV-BEG-1" not in r.text
        assert "AUDIT_READINESS" in {w["code"] for w in r.json()["integrity"]}
        assert await _snapshot(op) == before

        # Unknown tenant in the registry -> also fail closed.
        await sysdb.tenant_registry.delete_one({"id": BEG})
        r = await c.get(URL, headers=ha)
        assert r.json()["audit"]["status"] == "unavailable"
        return True
    assert _with_app(monkeypatch, body)


# ═══════════════════════════════════════════════════════════════════ static
WRITE_METHODS = {"insert_one", "insert_many", "update_one", "update_many", "replace_one",
                 "delete_one", "delete_many", "find_one_and_update", "find_one_and_delete",
                 "find_one_and_replace", "bulk_write", "create_index", "create_indexes",
                 "drop", "drop_index", "record_event", "begin_idempotent",
                 "complete_idempotent", "log_audit"}


def test_module_contains_no_write_call():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    calls = {n.func.attr for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    names = {n.func.id for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not (calls | names) & WRITE_METHODS, (calls | names) & WRITE_METHODS
    for stage in ("$out", "$merge"):
        assert stage not in MODULE.read_text(encoding="utf-8")


def test_router_exposes_only_get():
    from app.routes import live_ops
    methods = {m for r in live_ops.router.routes for m in r.methods}
    assert methods == {"GET"}, methods
    assert [r.path for r in live_ops.router.routes] == ["/live-ops/control-center"]


def test_module_passes_the_tenant_access_guard():
    import subprocess
    import sys
    r = subprocess.run([sys.executable, str(BACKEND / "scripts" / "w0_03e_a1_tenant_access_guard.py"),
                        str(MODULE)], capture_output=True, text=True, cwd=str(BACKEND))
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.skipif(bool(_refusal()), reason=_refusal() or "ok")
def test_on_a_real_disposable_mongodb(monkeypatch):
    """Same scenario on a disposable local MongoDB (``W0_03_REAL_MONGO_URL``)."""
    from motor.motor_asyncio import AsyncIOMotorClient
    from tests.test_w0_03c_real_mongo import REAL_URL

    suffix = uuid.uuid4().hex[:10]
    op_name, sys_name = "lo_a_op_" + suffix, "lo_a_sys_" + suffix

    async def body():
        client = AsyncIOMotorClient(REAL_URL)
        try:
            return await scenario(client[op_name], client[sys_name], monkeypatch, "A")
        finally:
            await client.drop_database(op_name)
            await client.drop_database(sys_name)
            client.close()

    out = asyncio.run(body())
    assert out["byte_equal"] and out["tenant_clean"]
