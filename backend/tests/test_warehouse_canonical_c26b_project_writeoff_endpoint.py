"""
5C-C26 Addendum B — Р27 completely: POST /warehouse/canonical/project-writeoff
is gated by its own catalog action `warehouse.project_writeoff`
(PROJECT_WRITEOFF_RULE), not by the coarse `warehouse.write_command`; P&L
input VAT follows the allocations[] field.

Real Mongo (replica set). The handler runs with the production command
service and the production Р27 policy; only the RoleAssignment loader (the
registry) and the denial-audit sink are fixtures.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.permissions.catalog import (
    PROJECT_WRITEOFF_ACTION, PROJECT_WRITEOFF_RULE, role_actions,
)
from app.services.warehouse_movements.service import CommandService
from tests.test_warehouse_canonical_c22_all_reports_cutover import (
    ITEM, PROJECT, T, _patch_dbs, _seed,
)
from tests.test_warehouse_canonical_c25_cost_at_accept_transit import _Run
from tests.test_warehouse_canonical_c26a_writeoff_rights_values import (
    OTHER_PROJECT, USER, _UserCtx, _assignment, _ledger_count, _loader, _member,
)

pytest_plugins = ["tests.warehouse_canonical_conftest"]


def _user():
    return {"id": USER, "org_id": T, "role": "x", "email": "c26b@x"}


async def _setup(client, gate, db, monkeypatch, assignments):
    from app.permissions import audit_hooks, service as perm
    from app.routes import warehouse_canonical as route
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await db["projects"].insert_one({"id": OTHER_PROJECT, "org_id": T, "code": "PO",
                                     "name": "PO", "status": "Active"})
    run = _Run(client, gate, db)
    await run.receive("10", "10")
    disp = await run.dispatch("10")
    await run.accept(disp, "10")
    monkeypatch.setattr(route, "db", db)
    monkeypatch.setattr(route, "_service", lambda: CommandService(client))
    monkeypatch.setattr(perm, "_load_assignments", _loader(assignments))
    audits = []

    async def _audit(ctx, action, **kw):
        audits.append((action, kw.get("scope_id"), kw["decision"].reason_code))
    monkeypatch.setattr(audit_hooks, "audit_permission_denied", _audit)
    return route, audits


async def _post(route, key="k", project=PROJECT):
    body = route.ProjectWriteOffBody(
        project_id=project, item_id=ITEM, unit="bag", quantity="1",
        idempotency_key=f"c26b-{key}", reason="брак", file_ids=["f-c26b"])
    ctx = _UserCtx()
    ctx.mode = "enforce"          # what require_project_writeoff sets in enforce
    return await route.post_project_writeoff(body, request=None, user=_user(), ctx=ctx)


# (label, assignments, membership kwargs or None, allowed)
CASES = [
    ("accountant / non-member", [_assignment("accountant")], None, True),
    ("accountant / expired member", [_assignment("accountant")], {"to_date": "2021-01-01"}, True),
    ("owner", [_assignment("owner")], None, True),
    ("admin", [_assignment("admin")], None, True),
    ("technician / member", [_assignment("LEGACY_TECHNICIAN")], {}, True),
    ("technician / non-member", [_assignment("LEGACY_TECHNICIAN")], None, False),
    ("technician / expired", [_assignment("LEGACY_TECHNICIAN")], {"to_date": "2021-01-01"}, False),
    ("site_manager / member", [_assignment("site_manager")], {}, True),
    ("site_manager / non-member", [_assignment("site_manager")], None, False),
    ("site_manager / expired", [_assignment("site_manager")], {"to_date": "2021-01-01"}, False),
    # Р30: own project = team row as manager.
    ("project_manager / own (team manager)", [_assignment("project_manager")], {}, True),
    ("project_manager / team technician", [_assignment("project_manager")],
     {"role_in_project": "Technician"}, False),
    ("project_manager / foreign", [_assignment("project_manager", "project", OTHER_PROJECT)],
     None, False),
    ("viewer / member", [_assignment("LEGACY_VIEWER")], {}, False),
    ("driver / member", [_assignment("driver")], {}, False),
    ("warehousekeeper / member", [_assignment("warehouse")], {}, False),
]


@pytest.mark.parametrize("label,assignments,membership,allowed", CASES,
                         ids=[c[0] for c in CASES])
async def test_project_writeoff_endpoint_r27(
        canonical_mongo_db, allow_always_gate, monkeypatch,
        label, assignments, membership, allowed):
    client, db = canonical_mongo_db
    route, audits = await _setup(client, allow_always_gate, db, monkeypatch, assignments)
    if membership is not None:
        await _member(db, **membership)
    before = await _ledger_count(db)
    if allowed:
        res = await _post(route)
        assert res.movement_id and res.envelope["action"] == "write_off"
        assert await _ledger_count(db) == before + 1
        assert audits == []
    else:
        with pytest.raises(HTTPException) as exc:
            await _post(route)
        assert exc.value.status_code == 403
        assert exc.value.detail["error_code"] == "PERMISSION_DENIED"
        assert await _ledger_count(db) == before                 # nothing written
        assert audits == [(PROJECT_WRITEOFF_ACTION, PROJECT, "R27_WRITE_OFF_NOT_ALLOWED")]


def test_endpoint_route_is_registered_with_201():
    from app.routes import warehouse_canonical as route
    [r] = [r for r in route.router.routes if r.path.endswith("/project-writeoff")]
    assert r.methods == {"POST"} and r.status_code == 201


@pytest.mark.parametrize("mode", ["off", "shadow"])
async def test_off_and_shadow_resolve_a_legacy_context(monkeypatch, mode):
    """5C-C26c: the gate no longer refuses off / shadow — Р27 decides there
    from the legacy role (test_warehouse_canonical_c26c_r27_all_modes.py)."""
    from app.routes import warehouse_canonical as route
    from app.tenancy.guard import LegacyCompatContext
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    ctx = await route.require_project_writeoff(request=None, user=_user())
    assert isinstance(ctx, LegacyCompatContext) and ctx.mode == mode


async def test_enforce_resolves_the_tenant_context(monkeypatch):
    from app.routes import warehouse_canonical as route
    from app.tenancy import guard
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "enforce")
    seen = []

    async def _ctx(request, user):
        seen.append(user["id"])
        return _UserCtx()
    monkeypatch.setattr(guard, "get_tenant_context", _ctx)
    ctx = await route.require_project_writeoff(request=None, user=_user())
    assert seen == [USER] and ctx.mode == "enforce"


def test_catalog_keeps_the_w0_and_c19_invariants():
    """The dedicated action — not a wider write_command."""
    assert role_actions("LEGACY_TECHNICIAN") == {"asset_intake.submit"}
    assert role_actions("LEGACY_VIEWER") == set()
    assert "warehouse.write_command" not in role_actions("accountant")
    assert PROJECT_WRITEOFF_ACTION in role_actions("accountant")
    assert PROJECT_WRITEOFF_ACTION in role_actions("site_manager")
    assert PROJECT_WRITEOFF_ACTION in role_actions("project_manager")
    for r in ("warehouse", "procurement", "office", "worker", "driver"):
        assert PROJECT_WRITEOFF_ACTION not in role_actions(r)
        assert r not in PROJECT_WRITEOFF_RULE
    assert PROJECT_WRITEOFF_RULE["LEGACY_TECHNICIAN"] == "member"


# ═══════════════════ P&L input VAT by the allocation field ═══════════════════

async def test_pnl_input_vat_follows_allocations(canonical_mongo_db, allow_always_gate,
                                                 monkeypatch):
    """Line A: allocations[] 6 to the project + 4 to a warehouse, VAT 20 → 12.
    Line B: deprecated single allocation, VAT 8 → 8. Line C: stale deprecated
    project field, allocations[] all to the warehouse, VAT 50 → 0.
    71c11da: 58 (B + C; A was not selected at all)."""
    from app.routes import project_pnl
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    base = {"org_id": T, "invoice_id": "inv-c26b", "unit": "bag", "qty": 10,
            "line_total_ex_vat": 100.0, "created_at": "2026-11-01T10:00:00+00:00"}
    await db["invoice_lines"].insert_many([
        dict(base, id="il-a", vat_amount=20.0, allocations=[
            {"type": "project", "ref_id": PROJECT, "qty": 6},
            {"type": "warehouse", "ref_id": "wh_1", "qty": 4}]),
        dict(base, id="il-b", vat_amount=8.0, allocations=[],
             allocation_type="project", allocation_ref_id=PROJECT),
        dict(base, id="il-c", vat_amount=50.0, allocation_type="project",
             allocation_ref_id=PROJECT,
             allocations=[{"type": "warehouse", "ref_id": "wh_1", "qty": 10}]),
    ])
    pnl = await project_pnl.get_project_pnl(PROJECT, user={"id": "u", "org_id": T,
                                                             "role": "Owner", "email": "o@x"})
    assert pnl["vat"]["input_vat"] == pytest.approx(20.0)
    # Cost follows the same selection: A 60 + B 100 (+ C 0).
    assert pnl["warehouse_cost_basis"]["invoice_cost"] == pytest.approx(160.0)
