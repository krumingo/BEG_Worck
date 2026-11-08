"""LIVE-OPS-01 / TASK 5C — 5C-C19: fixes for the bot findings on 639ca80.

Evidence: ``docs/evidence/BOT/5C-C18-639ca80/README.md`` (branch
``claude/bot-evidence``), package ``docs/architecture/tasks/5C-C19_BOT_FINDINGS.md``.

Each finding has at least one REAL-MONGO regression test (replica set,
transactions) that fails on 639ca80:

  * F-1  — the first canonical write on a tenant that already holds W0-04
           AuditEvents continues THAT sequence (one append-only chain), and a
           W0-04 event written between two canonical writes does not break the
           next canonical write;
  * F-1b — ``ensure_required_indexes`` is wired into application startup;
  * F-2  — a second inbound layer does not collide with the legacy unique
           ``warehouse_batches(org_id, batch_number)`` index — without any
           index change and without touching data;
  * F-3  — ``integrity_warnings`` runs on a real ``TenantCollection`` (the
           ``distinct()`` call takes driver kwargs, PR #56 ``**kw`` style);
  * F-4  — a dispatch to project/free is refused; every dispatch lands in
           in_transit/pending and the project gets nothing before acceptance;
  * F-5  — an identical consume resend returns the original result;
  * F-6  — the frontend copy of the warehouse rights equals the catalog (the
           UI route/visibility tests themselves are Jest tests).

Run (real Mongo, required):
    WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1 PERMISSION_SERVICE_MODE=enforce \\
    MONGO_URL='mongodb://127.0.0.1:27019/?replicaSet=rs0&directConnection=true' \\
    PYTHONPATH=. pytest -q tests/test_warehouse_canonical_c19_bot_findings.py
"""
from __future__ import annotations

import inspect
import json
import os
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from app.audit.envelope import ACTOR_HUMAN, RETENTION_R1_CRITICAL_BUSINESS, build_event
from app.audit.store import AUDIT_COLLECTION, record_event, verify_tenant_chain
from app.services.warehouse_movements import (
    CanonicalAction, LocationKey, LocationType, MovementState,
)
from app.services.warehouse_movements.errors import InvariantViolationError
from app.services.warehouse_movements.service import CommandInput, CommandService
from app.tenancy.data_access import TenantData


def _sec02_req(path="/api/sec02-direct-call"):
    """SEC-02-G (audit SEC71-M1): a real Request for a direct call of an R20-decorated
    handler — the role is the ``user=`` the test already passes (FastAPI injects this
    request in production; without one the decorator fails closed and strips money)."""
    from starlette.requests import Request
    return Request({"type": "http", "method": "GET", "path": path, "headers": [],
                    "query_string": b"", "root_path": "", "scheme": "http",
                    "server": ("testserver", 80), "client": ("testclient", 50000)})


pytest_plugins = ["tests.warehouse_canonical_conftest"]

T = "org_c19"
BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent


class _Ctx:
    def __init__(self, tenant_id: str = T):
        self.tenant_id = tenant_id
        self.org_id = tenant_id
        self.user_id = "u-c19"


def _enforce_env():
    os.environ["PERMISSION_SERVICE_MODE"] = "enforce"


def _inp(action, **kw):
    base = dict(
        action=action, tenant_id=T,
        actor_id=kw.pop("actor_id", "u-c19"),
        item_id=kw.pop("item_id", "item_c19"),
        unit=kw.pop("unit", "bag"),
        quantity=kw.pop("quantity", Decimal("10")),
        idempotency_key=kw.pop("idempotency_key", f"k-{uuid.uuid4().hex[:8]}"),
    )
    base.update(kw)
    return CommandInput(**base)


def _receive(qty="10", value="5", **kw):
    return _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER,
        source=LocationKey(LocationType.SUPPLIER, "sup_1"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_1"),
        quantity=Decimal(qty), unit_value=Decimal(value), **kw,
    )


def _w0_04_event(action="permission.role_assignment.granted"):
    """The kind of event W0-04 writes on user creation (bot step 0a)."""
    return build_event(
        tenant_id=T, actor_type=ACTOR_HUMAN, actor_id="admin-1",
        action=action, source_flow="FLOW-002",
        retention_class=RETENTION_R1_CRITICAL_BUSINESS,
        entity_type="role_assignment", entity_id=f"ra-{uuid.uuid4().hex[:6]}",
        reason="synthetic W0-04 event",
    )


async def _svc(client, gate):
    return CommandService(client, gate=gate)


# ═══════════════════════════════ F-1 ═══════════════════════════════

async def test_f1_first_canonical_write_continues_existing_w0_04_sequence(
        canonical_mongo_db, allow_always_gate):
    """639ca80: AUDIT_CHAIN_WRITE_FAILED — the service started its own chain
    at sequence 1 on top of the W0-04 event at sequence 1."""
    _enforce_env()
    client, db = canonical_mongo_db
    first = await record_event(db, _w0_04_event())
    assert first["sequence"] == 1

    svc = await _svc(client, allow_always_gate)
    res = await svc.execute(_Ctx(), db, TenantData.for_resolved_org(db, T).warehouse_transactions,
                            _receive())
    assert res.movement_id

    events = await db[AUDIT_COLLECTION].find({"tenant_id": T}, {"_id": 0}).sort(
        "sequence", 1).to_list(None)
    assert [e["sequence"] for e in events] == [1, 2]
    assert events[1]["previous_hash"] == first["integrity_hash"]
    ok, reason = await verify_tenant_chain(db, T)
    assert ok, reason
    # ONE chain: the head pivot follows the shared sequence, no second chain.
    head = await db["audit_chain_head"].find_one({"tenant_id": T})
    assert head["sequence"] == 2
    assert head["integrity_hash"] == events[1]["integrity_hash"]


async def test_f1_w0_04_event_between_canonical_writes_keeps_one_chain(
        canonical_mongo_db, allow_always_gate):
    """639ca80: the head stayed at the last canonical event, so the next
    canonical write reused the sequence a W0-04 writer had already taken."""
    _enforce_env()
    client, db = canonical_mongo_db
    coll = TenantData.for_resolved_org(db, T).warehouse_transactions
    svc = await _svc(client, allow_always_gate)

    await svc.execute(_Ctx(), db, coll, _receive())               # seq 1
    await record_event(db, _w0_04_event("master_data.item.created"))  # seq 2 (W0-04)
    await record_event(db, _w0_04_event())                         # seq 3 (W0-04)
    await svc.execute(_Ctx(), db, coll, _receive())               # seq 4
    await record_event(db, _w0_04_event())                         # seq 5 (W0-04)

    seqs = [e["sequence"] for e in await db[AUDIT_COLLECTION].find(
        {"tenant_id": T}, {"_id": 0, "sequence": 1}).sort("sequence", 1).to_list(None)]
    assert seqs == [1, 2, 3, 4, 5]
    ok, reason = await verify_tenant_chain(db, T)
    assert ok, reason
    assert await db["warehouse_transactions"].count_documents({"tenant_id": T}) == 2


# ═══════════════════════════════ F-1b ═══════════════════════════════

async def test_f1b_startup_hook_prepares_a_fresh_database_for_writes(
        canonical_mongo_db, allow_always_gate):
    """A database prepared ONLY by the startup hook accepts a canonical write
    (639ca80: no such hook — a fresh deploy answered 503 INDEX_MISSING)."""
    from app.services.warehouse_movements.indexes import (
        REQUIRED_INDEXES, ensure_required_indexes_at_startup, verify_required_indexes,
    )
    _enforce_env()
    client, _ = canonical_mongo_db
    fresh = client[f"begwork_c19_fresh_{uuid.uuid4().hex[:8]}"]
    try:
        out = await ensure_required_indexes_at_startup(fresh)
        assert out["ok"] is True
        assert sorted(out["created"]) == sorted(ri.name for ri in REQUIRED_INDEXES)
        await verify_required_indexes(fresh)
        again = await ensure_required_indexes_at_startup(fresh)   # idempotent
        assert again == {"ok": True, "created": [], "error": None}

        svc = await _svc(client, allow_always_gate)
        res = await svc.execute(_Ctx(), fresh,
                                TenantData.for_resolved_org(fresh, T).warehouse_transactions,
                                _receive())
        assert res.movement_id
    finally:
        await client.drop_database(fresh.name)


def test_f1b_server_startup_calls_the_hook_on_the_request_database():
    import server
    src = inspect.getsource(server.startup)
    assert "ensure_required_indexes_at_startup" in src
    assert "await ensure_warehouse_canonical_indexes(db)" in src


async def test_f1b_startup_hook_failure_is_logged_and_stays_fail_closed(
        canonical_mongo_db):
    """Data violating a required unique key: the hook reports, never raises,
    never deletes, and the service's verify keeps refusing writes."""
    from app.services.warehouse_movements.errors import IndexMissingError
    from app.services.warehouse_movements.indexes import (
        ensure_required_indexes_at_startup, verify_required_indexes,
    )
    client, _ = canonical_mongo_db
    bad = client[f"begwork_c19_bad_{uuid.uuid4().hex[:8]}"]
    try:
        await bad[AUDIT_COLLECTION].insert_many([
            {"tenant_id": T, "sequence": 1, "event_id": "e1"},
            {"tenant_id": T, "sequence": 1, "event_id": "e2"},
        ])
        out = await ensure_required_indexes_at_startup(bad)
        assert out["ok"] is False and out["error"]
        assert await bad[AUDIT_COLLECTION].count_documents({}) == 2
        with pytest.raises(IndexMissingError):
            await verify_required_indexes(bad)
    finally:
        await client.drop_database(bad.name)


# ═══════════════════════════════ F-2 ═══════════════════════════════

async def _legacy_fifo_indexes(db, monkeypatch):
    """Create the legacy `warehouse_batches` indexes with the REAL startup
    function (`fifo_service.ensure_indexes`) on the test database."""
    from app.services import fifo_service
    monkeypatch.setattr(fifo_service, "db", db)
    await fifo_service.ensure_indexes()
    info = await db["warehouse_batches"].index_information()
    assert any(v.get("unique") and [k for k, _ in v["key"]] == ["org_id", "batch_number"]
               for v in info.values())


async def test_f2_second_inbound_layer_under_legacy_unique_batch_number(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """639ca80: the second receive died on E11000 `org_id_1_batch_number_1`
    (canonical layers had batch_number null)."""
    _enforce_env()
    client, db = canonical_mongo_db
    await _legacy_fifo_indexes(db, monkeypatch)
    before = await db["warehouse_batches"].index_information()
    coll = TenantData.for_resolved_org(db, T).warehouse_transactions
    svc = await _svc(client, allow_always_gate)

    r1 = await svc.execute(_Ctx(), db, coll, _receive("10", "5"))
    r2 = await svc.execute(_Ctx(), db, coll, _receive("4", "6"))
    disp = await svc.execute(_Ctx(), db, coll, _inp(
        CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT,
        source=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_1"),
        quantity=Decimal("12"), project_id="p1"))
    await svc.execute(_Ctx(), db, coll, _inp(
        CanonicalAction.ACCEPT_PROJECT_DELIVERY,
        destination=LocationKey(LocationType.PROJECT, "p1"),
        quantity=Decimal("12"), accepted_quantity=Decimal("12"),
        dispatch_movement_id=disp.movement_id, project_id="p1"))

    rows = await db["warehouse_batches"].find(
        {"tenant_id": T, "projection_source": "canonical_warehouse_service"},
        {"_id": 0, "batch_number": 1, "movement_id": 1}).to_list(None)
    numbers = [r["batch_number"] for r in rows]
    assert all(numbers) and len(set(numbers)) == len(numbers)
    assert {r1.movement_id, r2.movement_id} <= {r["movement_id"] for r in rows}
    # No index was changed by the fix.
    assert await db["warehouse_batches"].index_information() == before


async def test_f2_batch_number_is_deterministic_on_replay_and_rebuild(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    from app.services.warehouse_movements.projections import (
        canonical_batch_number, rebuild_from_ledger,
    )
    _enforce_env()
    client, db = canonical_mongo_db
    await _legacy_fifo_indexes(db, monkeypatch)
    coll = TenantData.for_resolved_org(db, T).warehouse_transactions
    svc = await _svc(client, allow_always_gate)
    inp = _receive("3", "2", idempotency_key="recv-f2")
    first = await svc.execute(_Ctx(), db, coll, inp)
    await svc.execute(_Ctx(), db, coll, _receive("3", "2", idempotency_key="recv-f2"))
    await svc.execute(_Ctx(), db, coll, _receive("1", "2"))

    def snapshot():
        return db["warehouse_batches"].find(
            {"tenant_id": T}, {"_id": 0, "movement_id": 1, "batch_number": 1}
        ).sort("batch_number", 1).to_list(None)

    before = await snapshot()
    assert canonical_batch_number(first.movement_id, 1) in {r["batch_number"] for r in before}
    assert len(before) == 2
    async with await client.start_session() as s:
        async with s.start_transaction():
            await rebuild_from_ledger(db, tenant_id=T, session=s)
    assert await snapshot() == before


# ═══════════════════════════════ F-3 ═══════════════════════════════

async def test_f3_integrity_warnings_on_a_real_tenant_collection(
        canonical_mongo_db, allow_always_gate):
    """639ca80: TypeError — TenantCollection.distinct() got an unexpected
    keyword argument 'session' (the route answered 500)."""
    from app.services.warehouse_movements.queries import integrity_warnings
    _enforce_env()
    client, db = canonical_mongo_db
    tenant = TenantData.for_resolved_org(db, T)
    svc = await _svc(client, allow_always_gate)
    await svc.execute(_Ctx(), db, tenant.warehouse_transactions, _receive())

    # Exactly as the route calls it (no session) ...
    data = await integrity_warnings(tenant.warehouse_transactions, tenant_id=T)
    assert isinstance(data["warnings"], list)
    # ... and inside a real session.
    async with await client.start_session() as s:
        data2 = await integrity_warnings(tenant.warehouse_transactions, tenant_id=T, session=s)
    assert isinstance(data2["warnings"], list)


async def test_f3_tenant_collection_distinct_and_count_take_session_and_stay_scoped(
        canonical_mongo_db):
    client, db = canonical_mongo_db
    await db["c19_probe"].insert_many([
        {"org_id": T, "k": "a"}, {"org_id": T, "k": "b"}, {"org_id": "other", "k": "z"},
    ])
    coll = TenantData.for_resolved_org(db, T).collection("c19_probe")
    async with await client.start_session() as s:
        assert sorted(await coll.distinct("k", {}, session=s)) == ["a", "b"]
        assert await coll.count_documents({}, session=s) == 2
        assert await coll.count({}, session=s) == 2
        assert (await coll.get(None, session=s)) is None


# ═══════════════════════════════ F-4 ═══════════════════════════════

async def test_f4_dispatch_to_project_free_is_refused(canonical_mongo_db, allow_always_gate):
    """639ca80: 200 and `project:free` credited before any acceptance."""
    _enforce_env()
    client, db = canonical_mongo_db
    coll = TenantData.for_resolved_org(db, T).warehouse_transactions
    svc = await _svc(client, allow_always_gate)
    await svc.execute(_Ctx(), db, coll, _receive())
    with pytest.raises(InvariantViolationError):
        await svc.execute(_Ctx(), db, coll, _inp(
            CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT,
            source=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_1"),
            destination=LocationKey(LocationType.PROJECT, "p1", state=MovementState.FREE),
            quantity=Decimal("10"), project_id="p1"))
    assert await db["warehouse_transactions"].count_documents(
        {"tenant_id": T, "action": "dispatch_warehouse_to_project"}) == 0
    assert await db["warehouse_transactions"].count_documents(
        {"tenant_id": T, "destination.location_type": "project"}) == 0


@pytest.mark.parametrize("destination", [
    None,
    LocationKey(LocationType.IN_TRANSIT, "pending", state=MovementState.FREE),
    LocationKey(LocationType.IN_TRANSIT, "client-made-id", state=MovementState.IN_TRANSIT),
])
async def test_f4_every_dispatch_lands_in_transit_pending(
        canonical_mongo_db, allow_always_gate, destination):
    from app.services.warehouse_movements.queries import item_balance_by_location
    _enforce_env()
    client, db = canonical_mongo_db
    coll = TenantData.for_resolved_org(db, T).warehouse_transactions
    svc = await _svc(client, allow_always_gate)
    await svc.execute(_Ctx(), db, coll, _receive())
    disp = await svc.execute(_Ctx(), db, coll, _inp(
        CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT,
        source=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_1"),
        destination=destination, quantity=Decimal("10"), project_id="p1"))
    row = await db["warehouse_transactions"].find_one({"movement_id": disp.movement_id})
    assert row["destination"] == {"location_type": "in_transit",
                                  "location_id": disp.movement_id,
                                  "state": "in_transit"}
    balances = await item_balance_by_location(coll, tenant_id=T, item_id="item_c19")
    assert not [b for b in balances if b["location_type"] == "project"
                and Decimal(b["quantity"]) != 0]
    # Acceptance is the one point where the project is credited.
    await svc.execute(_Ctx(), db, coll, _inp(
        CanonicalAction.ACCEPT_PROJECT_DELIVERY,
        destination=LocationKey(LocationType.PROJECT, "p1"),
        quantity=Decimal("10"), accepted_quantity=Decimal("10"),
        dispatch_movement_id=disp.movement_id, project_id="p1"))
    balances = await item_balance_by_location(coll, tenant_id=T, item_id="item_c19")
    proj = [b for b in balances if b["location_type"] == "project"]
    assert proj and Decimal(proj[0]["quantity"]) == Decimal("10")


# ═══════════════════════════════ F-5 ═══════════════════════════════

async def test_f5_identical_consume_resend_returns_the_original_result(
        canonical_mongo_db, allow_always_gate):
    """639ca80: 409 IDEMPOTENCY_CONFLICT ("different request payload") —
    the server-stamped `confirmed_at` entered the fingerprint."""
    import asyncio
    _enforce_env()
    client, db = canonical_mongo_db
    coll = TenantData.for_resolved_org(db, T).warehouse_transactions
    svc = await _svc(client, allow_always_gate)
    await svc.execute(_Ctx(), db, coll, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT,
        source=LocationKey(LocationType.SUPPLIER, "sup_1"),
        destination=LocationKey(LocationType.PROJECT, "p1"),
        quantity=Decimal("10"), unit_value=Decimal("5"), project_id="p1"))

    def consume():
        return _inp(CanonicalAction.CONSUME_TO_SMR,
                    source=LocationKey(LocationType.PROJECT, "p1"),
                    quantity=Decimal("3"), project_id="p1", smr_id="smr-1",
                    idempotency_key="consume-f5")

    first = await svc.execute(_Ctx(), db, coll, consume())
    await asyncio.sleep(0.01)   # a later wall-clock `confirmed_at`
    again = await svc.execute(_Ctx(), db, coll, consume())
    assert again.replay is True
    assert again.movement_id == first.movement_id
    assert again.audit_event_id == first.audit_event_id
    assert await db["warehouse_transactions"].count_documents(
        {"tenant_id": T, "action": "consume_to_smr"}) == 1
    assert await db["material_entries"].count_documents(
        {"tenant_id": T, "smr_id": "smr-1"}) == 1


async def test_f5_a_different_consume_under_the_same_key_still_conflicts(
        canonical_mongo_db, allow_always_gate):
    from app.services.warehouse_movements.errors import IdempotencyConflictError
    _enforce_env()
    client, db = canonical_mongo_db
    coll = TenantData.for_resolved_org(db, T).warehouse_transactions
    svc = await _svc(client, allow_always_gate)
    await svc.execute(_Ctx(), db, coll, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT,
        source=LocationKey(LocationType.SUPPLIER, "sup_1"),
        destination=LocationKey(LocationType.PROJECT, "p1"),
        quantity=Decimal("10"), unit_value=Decimal("5"), project_id="p1"))
    base = dict(source=LocationKey(LocationType.PROJECT, "p1"), project_id="p1",
                smr_id="smr-1", idempotency_key="consume-f5b")
    await svc.execute(_Ctx(), db, coll, _inp(CanonicalAction.CONSUME_TO_SMR,
                                             quantity=Decimal("3"), **base))
    with pytest.raises(IdempotencyConflictError):
        await svc.execute(_Ctx(), db, coll, _inp(CanonicalAction.CONSUME_TO_SMR,
                                                 quantity=Decimal("4"), **base))


def test_f5_fingerprint_unchanged_for_actions_without_confirmed_at():
    """Neutralizing `confirmed_at` keeps every pre-C19 fingerprint of an
    action that never had one (receive, dispatch, ...) byte-identical."""
    import hashlib
    from app.services.warehouse_movements.envelope import build_envelope, envelope_fingerprint
    env = build_envelope(
        tenant_id=T, action="receive_from_supplier", item_id="i", unit="bag",
        quantity=Decimal("1"), source=None,
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_1"),
        actor_id="u", idempotency_key="k", unit_value=Decimal("1"),
        currency="BGN", layer_allocations=[])
    payload = env.to_dict()
    for k in ("movement_id", "recorded_at", "occurred_at", "audit_event_id"):
        payload.pop(k, None)
    legacy = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                       default=str).encode()).hexdigest()
    assert payload.get("confirmed_at") is None
    assert envelope_fingerprint(env) == legacy


# ═══════════════════════════════ F-6 ═══════════════════════════════

FRONTEND_ACCESS = REPO / "frontend" / "src" / "lib" / "warehouseCanonicalAccess.json"


def test_f6_frontend_copy_of_the_warehouse_rights_is_the_catalog():
    from app.permissions import catalog
    from app.services.warehouse_movements.actions import PERMISSION_ACTION
    mirror = json.loads(FRONTEND_ACCESS.read_text(encoding="utf-8"))
    assert mirror["legacy_role_map"] == catalog.LEGACY_ROLE_MAP
    screen = {a for a in catalog.ACTIONS
              if a.startswith("warehouse.") and not a.startswith("warehouse.migration.")}
    expected = {}
    for role_id in list(catalog.CANONICAL_ROLES) + list(catalog.LEGACY_ROLES):
        granted = catalog.role_actions(role_id) & screen
        if granted:
            expected[role_id] = sorted(granted)
    assert {r: sorted(a) for r, a in mirror["role_actions"].items()} == expected
    assert mirror["permission_for_action"] == {a.value: p for a, p in PERMISSION_ACTION.items()}


def test_f6_bot_roles_get_what_the_api_gives_them():
    from app.permissions import catalog
    rights = lambda legacy: catalog.role_actions(catalog.LEGACY_ROLE_MAP[legacy])  # noqa: E731
    # Accountant: read-only — no write command at all.
    assert "warehouse.read_stock" in rights("Accountant")
    assert "warehouse.write_command" not in rights("Accountant")
    # Warehousekeeper: reads and receive/dispatch/accept — but not consume.
    wk = rights("Warehousekeeper")
    assert {"warehouse.read_stock", "warehouse.write_command",
            "warehouse.receive_from_supplier", "warehouse.dispatch_to_project",
            "warehouse.accept_delivery"} <= wk
    assert "warehouse.consume_smr" not in wk
    # Technician / Viewer: nothing on this screen.
    assert not {a for a in rights("Technician") if a.startswith("warehouse.")}
    assert not {a for a in rights("Viewer") if a.startswith("warehouse.")}


def test_f6_route_is_no_longer_admin_route():
    app_js = (REPO / "frontend" / "src" / "App.js").read_text(encoding="utf-8")
    line = next(l for l in app_js.splitlines() if 'path="/warehouse/canonical"' in l)
    assert "CanonicalWarehouseRoute" in line and "AdminRoute" not in line


# ═══════════════════════ F-7 / F-8 (C19 addendum) ═══════════════════════
#
# Internal audit of 639ca80 (docs/audit/AUDIT_LOG.md @ claude/audit-log
# ffd543c, probe test_probe_pr55_material_cost.py): project material cost
# was counted at ACCEPT and again at CONSUME (80 instead of 30), and seven
# `await [row async for ...]` sites in material_smr.py raised TypeError.

PROJECT = "p1"
PKG = "pkg-c19"


def _user(org=T):
    return {"id": "u-" + org, "org_id": org, "role": "Owner", "email": org + "@x"}


def _patch_route_dbs(monkeypatch, db):
    """Point every route module these readers touch at the test database."""
    import importlib
    for name in ("material_smr", "full_cost", "revenue_expense", "labor_smr",
                 "subcontractors"):
        mod = importlib.import_module(f"app.routes.{name}")
        monkeypatch.setattr(mod, "db", db)
    from tests.warehouse_canonical_conftest import sec02_owner_in_enforce
    sec02_owner_in_enforce(monkeypatch, T)            # SEC-02-G (SEC71-M1): R20 reads


async def _receive_accept5_consume3(client, gate, db):
    """receive 5 @10 → dispatch 5 → accept 5 → consume 3 (the audit flow)."""
    coll = TenantData.for_resolved_org(db, T).warehouse_transactions
    svc = await _svc(client, gate)
    await svc.execute(_Ctx(), db, coll, _receive("5", "10"))
    disp = await svc.execute(_Ctx(), db, coll, _inp(
        CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT,
        source=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_1"),
        quantity=Decimal("5"), project_id=PROJECT))
    await svc.execute(_Ctx(), db, coll, _inp(
        CanonicalAction.ACCEPT_PROJECT_DELIVERY,
        destination=LocationKey(LocationType.PROJECT, PROJECT),
        quantity=Decimal("5"), accepted_quantity=Decimal("5"),
        dispatch_movement_id=disp.movement_id, project_id=PROJECT))
    await svc.execute(_Ctx(), db, coll, _inp(
        CanonicalAction.CONSUME_TO_SMR,
        source=LocationKey(LocationType.PROJECT, PROJECT),
        quantity=Decimal("3"), project_id=PROJECT, smr_id="smr-1"))


async def _seed_project(db, *, mapped: bool):
    await db["projects"].insert_one({"id": PROJECT, "org_id": T, "code": "P1", "name": "P1"})
    await db["execution_packages"].insert_one({
        "id": PKG, "org_id": T, "project_id": PROJECT, "activity_name": "Мазилка",
        "sale_total": 100.0, "material_budget_total": 25.0, "budget_total": 60.0})
    if mapped:
        await db["planned_materials"].insert_one({
            "id": "pm-1", "org_id": T, "project_id": PROJECT, "status": "active",
            "item_id": "item_c19", "material_name": "item_c19",
            "execution_package_id": PKG, "planned_total_cost": 25.0})


async def test_f7_sync_recognises_project_material_cost_once(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """639ca80: the accept row (+50) and the consume row (+30) were both cost → 80.
    5C-C25 (Р17, Крум 06.11.2026): the cost is the ACCEPTED lot (50), once;
    the consume row is an allocation (value 30 in movement_value, total 0)."""
    from app.routes import material_smr
    _enforce_env()
    client, db = canonical_mongo_db
    _patch_route_dbs(monkeypatch, db)
    await _seed_project(db, mapped=True)
    await _receive_accept5_consume3(client, allow_always_gate, db)
    out = await material_smr.sync_material_entries(PROJECT, user=_user())
    assert out["synced"] == 2                      # accept + consume rows (quantity trail)

    rows = await db["material_entries"].find(
        {"org_id": T, "project_id": PROJECT,
         "projection_source": "canonical_warehouse_service"}, {"_id": 0}).to_list(None)
    by_kind = {r["movement_kind"]: r for r in rows}
    assert set(by_kind) == {"accept", "consume"}
    # The audit probe's sum over every kind the readers used to count:
    probe_kinds = ["accept", "transfer_out", "write_off", "transfer", "consume"]
    total = sum(float(r["total_value"]) for r in rows
                if r["movement_kind"] in probe_kinds and r.get("total_value") is not None)
    # 5C-C25 (Р17): still counted ONCE (never 80) — now at acceptance.
    assert total == pytest.approx(50.0)
    assert by_kind["consume"]["cost_recognized"] is False
    assert float(by_kind["consume"]["total_value"]) == 0.0
    assert float(by_kind["consume"]["movement_value"]) == pytest.approx(30.0)
    assert by_kind["accept"]["cost_recognized"] is True
    assert float(by_kind["accept"]["total_value"]) == pytest.approx(50.0)
    assert float(by_kind["accept"]["movement_value"]) == pytest.approx(50.0)
    # Rebuild parity: a second sync gives the same rows.
    await material_smr.sync_material_entries(PROJECT, user=_user())
    again = await db["material_entries"].find(
        {"org_id": T, "project_id": PROJECT}, {"_id": 0}).sort("id", 1).to_list(None)
    assert again == sorted(rows, key=lambda r: r["id"])


async def test_f7_f8_every_report_shows_exactly_30(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """accept 5 + consume 3 @10 → project material cost 30 in every report,
    and every material_smr reader runs (639ca80: TypeError on the seven
    `await [async listcomp]` sites).
    5C-C25 (Р17, Крум 06.11.2026): the PROJECT cost is the accepted lot,
    50, in every project report; the PACKAGE reports show the consumption
    allocated to the package, 30 (allocation only, never a second cost);
    the other 20 is unallocated (on site)."""
    from app.routes import full_cost, material_smr, revenue_expense
    _enforce_env()
    client, db = canonical_mongo_db
    _patch_route_dbs(monkeypatch, db)
    await _seed_project(db, mapped=True)
    await _receive_accept5_consume3(client, allow_always_gate, db)
    await material_smr.sync_material_entries(PROJECT, user=_user())

    summary = await material_smr.get_material_summary_for_project(T, PROJECT)
    # 5C-C25 (Р17): project cost 50; 30 allocated to the package, 20 not.
    assert summary["total_cost"] == pytest.approx(50.0)
    assert summary["mapped_cost"] == pytest.approx(30.0)
    assert summary["unmapped_cost"] == pytest.approx(20.0)
    assert summary["budget_total"] == pytest.approx(25.0)
    assert summary["variance_value"] == pytest.approx(25.0)
    assert summary["has_data"] is True

    by_pkg = await material_smr.get_material_cost_by_exec_pkg(PKG, user=_user())
    assert by_pkg["material_actual_cost"] == pytest.approx(30.0)
    assert by_pkg["material_variance"] == pytest.approx(5.0)
    assert by_pkg["total_issued_qty"] == pytest.approx(5.0)
    assert by_pkg["by_material"][0]["consumed_qty"] == pytest.approx(3.0)
    assert by_pkg["by_material"][0]["net_cost"] == pytest.approx(30.0)

    rec = await material_smr.recompute_execution_package_material(PROJECT, user=_user())
    assert rec == {"ok": True, "updated": 1}
    pkg = await db["execution_packages"].find_one({"id": PKG})
    assert pkg["actual_material_cost"] == pytest.approx(30.0)
    assert pkg["material_variance_value"] == pytest.approx(5.0)

    fin = await material_smr.get_package_financial_summary(PKG, user=_user())
    assert fin["actual"]["material"] == pytest.approx(30.0)
    assert fin["actual"]["total"] == pytest.approx(30.0)
    assert fin["margin"]["gross_margin"] == pytest.approx(70.0)

    brk = await material_smr.get_project_package_breakdown(PROJECT, user=_user())
    assert [p["material_actual"] for p in brk["packages"]] == [pytest.approx(30.0)]
    assert brk["packages"][0]["gross_margin"] == pytest.approx(70.0)

    warn = await material_smr.get_material_warnings(PROJECT, user=_user(), _sec02_request=_sec02_req())
    assert warn["total_entries"] == 2 and warn["unmapped_entries"] == 0
    over = [w for w in warn["warnings"] if w["type"] == "over_material_budget"]
    assert len(over) == 1 and "30" in over[0]["message"]

    listed = await material_smr.list_material_entries(project_id=PROJECT, user=_user(), _sec02_request=_sec02_req())
    assert len(listed) == 2

    # 5C-C25 (Р17): project reports — the accepted lot, 50.
    net = await full_cost.get_project_net_profit(PROJECT, user=_user())
    assert net["costs"]["material"] == pytest.approx(50.0)

    profit = await revenue_expense.get_project_profit_summary(PROJECT, user=_user())
    assert profit["expenses"]["material"] == pytest.approx(50.0)



async def test_f7_unmapped_consumption_is_still_cost_once(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """No planned material → the rows are unmapped; still exactly 30.
    5C-C25 (Р17): exactly 50 (the accepted lot), all of it unallocated."""
    from app.routes import material_smr
    _enforce_env()
    client, db = canonical_mongo_db
    _patch_route_dbs(monkeypatch, db)
    await _seed_project(db, mapped=False)
    await _receive_accept5_consume3(client, allow_always_gate, db)
    await material_smr.sync_material_entries(PROJECT, user=_user())
    summary = await material_smr.get_material_summary_for_project(T, PROJECT)
    assert summary["total_cost"] == pytest.approx(50.0)
    assert summary["unmapped_cost"] == pytest.approx(50.0)
    warn = await material_smr.get_material_warnings(PROJECT, user=_user(), _sec02_request=_sec02_req())
    assert warn["unmapped_entries"] == 2


async def test_f7_projector_consumption_row_is_read_as_cost_without_a_sync(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """The command service's own projection (no sync run) is already the
    one cost row the readers count.
    5C-C25 (Р17): that row is the acceptance (50); the consume row beside
    it is an allocation row, not cost."""
    from app.routes import material_smr
    _enforce_env()
    client, db = canonical_mongo_db
    _patch_route_dbs(monkeypatch, db)
    await _seed_project(db, mapped=False)
    await _receive_accept5_consume3(client, allow_always_gate, db)
    rows = await db["material_entries"].find({"org_id": T}, {"_id": 0}).to_list(None)
    assert sorted(r["movement_kind"] for r in rows) == ["accept", "consume"]
    assert [r["movement_kind"] for r in rows if r["cost_recognized"]] == ["accept"]
    summary = await material_smr.get_material_summary_for_project(T, PROJECT)
    assert summary["total_cost"] == pytest.approx(50.0)


async def test_f7_sync_is_tenant_scoped(canonical_mongo_db, allow_always_gate, monkeypatch):
    from app.routes import material_smr
    _enforce_env()
    client, db = canonical_mongo_db
    _patch_route_dbs(monkeypatch, db)
    await _receive_accept5_consume3(client, allow_always_gate, db)
    out = await material_smr.sync_material_entries(PROJECT, user=_user("T2"))
    assert out["synced"] == 0
    assert await db["material_entries"].count_documents({"org_id": "T2"}) == 0
    assert (await material_smr.get_material_summary_for_project("T2", PROJECT))["total_cost"] == 0


def test_f8_no_await_on_an_async_list_comprehension():
    import re
    src = (BACKEND / "app" / "routes" / "material_smr.py").read_text(encoding="utf-8")
    assert re.search(r"await\s*\[[^\]]*async\s+for", src) is None
