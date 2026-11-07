"""
5C-C26 Addendum A — FG-21 → Р27 (write-off rights) and FG-23 → Р20 (money
only for finance roles) on the canonical warehouse.

Р27 (Крум 06.11.2026): a write-off („фира") from a project follows Р16 —
SiteManager / Technician only on projects where they are members with valid
dates; Owner / Admin / Accountant everywhere; project_manager only on their
own projects; every other role 403 and nothing is written.

Р20: /warehouse/canonical/stock and /history return quantities only to
roles without a finance right; Owner / Admin / Accountant see the values.

Real Mongo (replica set): the write-off runs through CommandService with the
production Р27 policy; only the RoleAssignment loader is a fixture.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.permissions.catalog import role_actions
from app.services.warehouse_movements import CanonicalAction
from app.services.warehouse_movements.errors import PermissionDeniedError
from app.services.warehouse_movements.service import CommandService, PermissionGate
from tests.test_warehouse_canonical_c22_all_reports_cutover import (
    PRJ, PROJECT, T, WH, _Ctx, _inp, _patch_dbs, _seed,
)
from tests.test_warehouse_canonical_c25_cost_at_accept_transit import _Run

pytest_plugins = ["tests.warehouse_canonical_conftest"]

USER = "u-c26a"
OTHER_PROJECT = "p-c26a-other"


def _assignment(role, scope_type="company", scope_id=None, valid_to=None, status="active"):
    return {"id": f"ra-{role}-{scope_type}", "status": status, "role_id": role,
            "module": None, "scope_type": scope_type, "scope_id": scope_id,
            "valid_from": "2020-01-01T00:00:00Z", "valid_to": valid_to}


def _loader(assignments):
    async def _load(user_id, tenant_id):
        return list(assignments) if user_id == USER and tenant_id == T else []
    return _load


class _UserCtx(_Ctx):
    def __init__(self):
        super().__init__(T)
        self.user_id = USER


async def _member(db, *, project=PROJECT, active=True, from_date="2020-01-01",
                  to_date=None, user=USER, role_in_project="SiteManager"):
    await db["project_team"].insert_one({
        "id": f"pt-{project}-{user}-{from_date}-{to_date}-{role_in_project}", "org_id": T,
        "project_id": project, "user_id": user, "role_in_project": role_in_project,
        "active": active, "from_date": from_date, "to_date": to_date})


async def _stock_on_project(client, gate, db):
    run = _Run(client, gate, db)
    await run.receive("10", "10")
    disp = await run.dispatch("10")
    await run.accept(disp, "10")
    return run


async def _write_off(client, db, assignments, project=PROJECT):
    svc = CommandService(client, gate=PermissionGate(assignments_loader=_loader(assignments)))
    run = _Run(client, None, db)
    from app.services.warehouse_movements import LocationKey, LocationType
    return await svc.execute(_UserCtx(), db, run.coll, _inp(
        CanonicalAction.WRITE_OFF, T,
        source=LocationKey(LocationType.PROJECT, project),
        quantity=Decimal("1"), reason="брак", file_ids=["f-c26a"]))


async def _ledger_count(db):
    return await db["warehouse_transactions"].count_documents(
        {"tenant_id": T, "action": "write_off"})


# role, assignments, membership kwargs (None = no row), allowed?
CASES = [
    # Owner / Admin / Accountant — everywhere, membership irrelevant.
    ("owner / non-member", [_assignment("owner")], None, True),
    ("admin / non-member", [_assignment("admin")], None, True),
    ("accountant / non-member", [_assignment("accountant")], None, True),
    # project_manager — own projects only.
    # Р30 (5C-C26e): own project = team row as manager (role_in_project
    # "SiteManager"), in date — a scope assignment alone or any other team
    # role is not enough.
    ("pm / team manager in date", [_assignment("project_manager", "project", OTHER_PROJECT)],
     {}, True),
    ("pm / scope assignment only (Р30)", [_assignment("project_manager", "project", PROJECT)],
     None, False),
    ("pm / team technician (Р30)", [_assignment("project_manager")],
     {"role_in_project": "Technician"}, False),
    ("pm / other project", [_assignment("project_manager", "project", OTHER_PROJECT)], None, False),
    ("pm / expired manager", [_assignment("project_manager", "project", OTHER_PROJECT)],
     {"to_date": "2021-01-01"}, False),
    # SiteManager / Technician — members with valid dates only.
    ("site_manager / member", [_assignment("site_manager")], {}, True),
    ("site_manager / non-member", [_assignment("site_manager")], None, False),
    ("site_manager / expired", [_assignment("site_manager")], {"to_date": "2021-01-01"}, False),
    ("site_manager / not started", [_assignment("site_manager")], {"from_date": "2099-01-01"}, False),
    ("site_manager / inactive row", [_assignment("site_manager")], {"active": False}, False),
    ("site_manager / other project row", [_assignment("site_manager")],
     {"project": OTHER_PROJECT}, False),
    ("technician / member", [_assignment("LEGACY_TECHNICIAN")], {}, True),
    ("technician / non-member", [_assignment("LEGACY_TECHNICIAN")], None, False),
    ("technician / expired", [_assignment("LEGACY_TECHNICIAN")], {"to_date": "2021-01-01"}, False),
    # Everyone else — 403 even as a member.
    ("warehouse / member", [_assignment("warehouse")], {}, False),
    ("procurement / member", [_assignment("procurement")], {}, False),
    ("viewer / member", [_assignment("LEGACY_VIEWER")], {}, False),
    ("driver / member", [_assignment("driver")], {}, False),
    ("worker / member", [_assignment("worker")], {}, False),
    # An expired / revoked finance assignment grants nothing.
    ("owner expired", [_assignment("owner", valid_to="2021-01-01T00:00:00Z")], None, False),
    ("owner revoked", [_assignment("owner", status="revoked")], None, False),
    ("no assignment", [], {}, False),
]


@pytest.mark.parametrize("label,assignments,membership,allowed", CASES,
                         ids=[c[0] for c in CASES])
async def test_r27_write_off_rights_role_x_membership(
        canonical_mongo_db, allow_always_gate, monkeypatch,
        label, assignments, membership, allowed):
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await db["projects"].insert_one({"id": OTHER_PROJECT, "org_id": T, "code": "PO",
                                     "name": "PO", "status": "Active"})
    await _stock_on_project(client, allow_always_gate, db)
    if membership is not None:
        await _member(db, **membership)
    before = await _ledger_count(db)
    if allowed:
        res = await _write_off(client, db, assignments)
        assert res.movement_id
        assert await _ledger_count(db) == before + 1
    else:
        with pytest.raises(PermissionDeniedError) as exc:
            await _write_off(client, db, assignments)
        assert exc.value.context["reason_code"] == "R27_WRITE_OFF_NOT_ALLOWED"
        assert await _ledger_count(db) == before          # nothing written


async def test_r27_membership_of_another_tenant_grants_nothing(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _stock_on_project(client, allow_always_gate, db)
    await db["project_team"].insert_one({
        "id": "pt-foreign", "org_id": "org_someone_else", "project_id": PROJECT,
        "user_id": USER, "role_in_project": "SiteManager", "active": True,
        "from_date": "2020-01-01", "to_date": None})
    with pytest.raises(PermissionDeniedError):
        await _write_off(client, db, [_assignment("site_manager")])


def test_r27_route_gate_is_unchanged_for_accountant_and_technician():
    """Known gap, recorded in HANDOFF 5C-C26: the coarse route gate
    (warehouse.write_command) still stops Accountant and Technician before
    the Р27 check — granting it changes the W0-02 catalog invariant
    (test_legacy_technician_reproduces_exact) and the C19 F-6 frontend copy,
    which needs Крум's decision. Fail-closed: they write nothing. This test
    pins the current catalog so the change cannot happen silently."""
    assert "warehouse.write_command" not in role_actions("accountant")
    assert "warehouse.write_command" not in role_actions("LEGACY_TECHNICIAN")


async def test_write_off_from_a_warehouse_keeps_the_generic_gate(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """Р27 is about a project („фира"). A warehouse write-off is still decided
    by the Permission Service grant: an accountant (no warehouse.write_off)
    is refused there."""
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    run = _Run(client, allow_always_gate, db)
    await run.receive("10", "10")
    from app.permissions import service as perm
    monkeypatch.setattr(perm, "_load_assignments", _loader([_assignment("accountant")]))
    svc = CommandService(client, gate=PermissionGate())
    with pytest.raises(PermissionDeniedError):
        await svc.execute(_UserCtx(), db, run.coll, _inp(
            CanonicalAction.WRITE_OFF, T, source=WH, quantity=Decimal("1"),
            reason="брак", file_ids=["f-c26a"]))


# ═══════════════════════ FG-23 — Р20: quantities only ═══════════════════════

async def _reads(db, monkeypatch, assignments):
    from app.permissions import service as perm
    from app.routes import warehouse_canonical_queries as q
    monkeypatch.setattr(q, "db", db)
    monkeypatch.setattr(perm, "_load_assignments", _loader(assignments))

    async def _ok(*a, **k):
        return None
    monkeypatch.setattr(q, "_authorize_resource_scope", _ok)
    stock = await q.read_stock("item_c22", location_type="central_warehouse",
                               location_id="wh_1", state="free", ctx=_UserCtx())
    hist = await q.read_history(item_id="item_c22", location_type=None, location_id=None,
                                project_id=None, since=None, until=None, limit=100,
                                cursor_after=None, ctx=_UserCtx())
    return stock, hist


def _has_value_key(obj) -> bool:
    from app.routes.warehouse_canonical_queries import VALUE_KEYS
    if isinstance(obj, dict):
        return any(k in VALUE_KEYS for k in obj) or any(_has_value_key(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_value_key(v) for v in obj)
    return False


# Р32 (5C-C26f): the warehousekeeper sees warehouse values (list below).
# 5C-C26h (F-16 / FG-60): Technician / Viewer / Driver may not read canonical
# stock at all (403), and a SiteManager reads only its member projects' buckets
# — there, quantities only (Р20).
async def test_fg23_site_manager_reads_its_project_as_quantities_only(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    from app.permissions import service as perm
    from app.routes import warehouse_canonical_queries as q
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    run = _Run(client, allow_always_gate, db)
    await run.receive("4", "1")
    await run.receive("6", "3")
    disp = await run.dispatch("10")
    await run.accept(disp, "10")
    await _member(db)
    monkeypatch.setattr(q, "db", db)
    monkeypatch.setattr(perm, "_load_assignments", _loader([_assignment("site_manager")]))
    stock = await q.read_stock("item_c22", location_type="project", location_id=PROJECT,
                               state="free", ctx=_UserCtx())
    hist = await q.read_history(item_id="item_c22", location_type=None, location_id=None,
                                project_id=PROJECT, since=None, until=None, limit=100,
                                cursor_after=None, ctx=_UserCtx())
    assert stock["values_hidden"] is True and hist["values_hidden"] is True
    assert not _has_value_key(stock) and not _has_value_key(hist)
    assert stock["quantity"] == "10"
    assert [l["quantity"] for l in stock["layers"]] == ["4", "6"]


@pytest.mark.parametrize("role", ["LEGACY_TECHNICIAN", "LEGACY_VIEWER", "driver"])
async def test_fg23_roles_without_read_rights_get_403(
        canonical_mongo_db, allow_always_gate, monkeypatch, role):
    from fastapi import HTTPException
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    run = _Run(client, allow_always_gate, db)
    await run.receive("4", "1")
    with pytest.raises(HTTPException) as exc:
        await _reads(db, monkeypatch, [_assignment(role)])
    assert exc.value.status_code == 403


# procurement: not in Р20 — unchanged (package 5C-C26 A), still sees values.
# warehouse: Р32 — sees the warehouse's unit prices / values.
@pytest.mark.parametrize("role", ["owner", "admin", "accountant", "procurement", "warehouse"])
async def test_fg23_finance_roles_see_values(
        canonical_mongo_db, allow_always_gate, monkeypatch, role):
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    run = _Run(client, allow_always_gate, db)
    await run.receive("4", "1")
    await run.receive("6", "3")
    stock, hist = await _reads(db, monkeypatch, [_assignment(role)])
    assert "values_hidden" not in stock and "values_hidden" not in hist
    assert Decimal(stock["total_value"]) == Decimal("22")
    assert all("unit_value" in r for r in hist["rows"])


async def test_fg23_expired_finance_assignment_hides_values(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    run = _Run(client, allow_always_gate, db)
    await run.receive("4", "1")
    # 5C-C26h: an expired assignment grants no read at all → 403 (no data,
    # so no values either).
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await _reads(db, monkeypatch,
                     [_assignment("accountant", valid_to="2021-01-01T00:00:00Z")])
    assert exc.value.status_code == 403
