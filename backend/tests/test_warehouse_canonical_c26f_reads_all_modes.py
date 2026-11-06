"""
5C-C26f — F-16 (bot 5C-C27): in off / shadow the canonical GET routes go
through the same legacy gate as the writes (Р28), so a read gets the same
answer in all three modes. Before: Technician / Viewer got 200 on
/balance, /stock, /history in off / shadow (403 in enforce).

Per role × off / shadow / enforce × {stock at the warehouse, stock on the
project, balance, history (project filter), integrity-warnings}. The
expected table is written by hand. In enforce the route's module gate
(require_permission → evaluate_permission) is replayed explicitly, because
the handlers are called in-process. Real Mongo (replica set).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.tenancy.guard import LegacyCompatContext
from tests.test_warehouse_canonical_c22_all_reports_cutover import (
    ITEM, PROJECT, T, _patch_dbs, _seed,
)
from tests.test_warehouse_canonical_c25_cost_at_accept_transit import _Run
from tests.test_warehouse_canonical_c26a_writeoff_rights_values import (
    OTHER_PROJECT, USER, _UserCtx, _assignment, _loader, _member,
)

pytest_plugins = ["tests.warehouse_canonical_conftest"]

READS = ["stock_warehouse", "stock_project", "balance", "history_project", "warnings"]
EVERYTHING = set(READS)
PROJECT_READS = {"stock_project", "history_project"}
from tests.test_warehouse_canonical_c26e_r28_all_modes import _real  # noqa: E402

# Real (company-scope) assignments, as permissions.sync.grant_company_role
# creates them (audit C26E-1). A SiteManager reads the warehouse and the
# unscoped lists company-wide (as its real grant does in enforce); a
# project-filtered read needs the in-date project relation — in every mode.
# legacy role, enforce assignments, member of P1?, allowed reads
ROLES = {
    "Owner": ("Owner", _real("owner"), False, EVERYTHING),
    "Admin": ("Admin", _real("admin"), False, EVERYTHING),
    "Accountant": ("Accountant", _real("accountant"), False, EVERYTHING),
    "Warehousekeeper": ("Warehousekeeper", _real("warehouse"), False, EVERYTHING),
    "SiteManager-member": ("SiteManager", _real("site_manager"), True, EVERYTHING),
    "SiteManager-non-member": ("SiteManager", _real("site_manager"), False,
                               EVERYTHING - PROJECT_READS),
    "Technician": ("Technician", _real("LEGACY_TECHNICIAN"), True, set()),
    "Viewer": ("Viewer", _real("LEGACY_VIEWER"), True, set()),
    "Driver": ("Driver", _real("driver"), True, set()),
}

ACTION = {"stock_warehouse": "warehouse.read_stock", "stock_project": "warehouse.read_stock",
          "balance": "warehouse.read_stock", "history_project": "warehouse.read_history",
          "warnings": "warehouse.read_stock"}


async def _call(q, read, ctx):
    if read == "stock_warehouse":
        return await q.read_stock(ITEM, location_type="central_warehouse",
                                  location_id="wh_1", state="free", ctx=ctx)
    if read == "stock_project":
        return await q.read_stock(ITEM, location_type="project", location_id=PROJECT,
                                  state="free", ctx=ctx)
    if read == "balance":
        return await q.read_balance_by_location(ITEM, ctx=ctx)
    if read == "history_project":
        return await q.read_history(item_id=ITEM, location_type=None, location_id=None,
                                    project_id=PROJECT, since=None, until=None, limit=100,
                                    cursor_after=None, ctx=ctx)
    return await q.read_integrity_warnings(ctx=ctx)


async def _status(q, mode, legacy_role, read):
    from app.permissions.service import evaluate_permission
    if mode == "enforce":
        ctx = _UserCtx()
        ctx.mode = "enforce"
        # The route dependency: require_permission(action, module="warehouse").
        decision = await evaluate_permission(ctx, ACTION[read], module="warehouse")
        if not decision.allowed:
            return 403
    else:
        ctx = LegacyCompatContext({"id": USER, "org_id": T, "role": legacy_role}, mode=mode)
    try:
        await _call(q, read, ctx)
        return 200
    except HTTPException as exc:
        return exc.status_code


@pytest.mark.parametrize("mode", ["off", "shadow", "enforce"])
@pytest.mark.parametrize("role", list(ROLES))
async def test_f16_canonical_reads_same_in_every_mode(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode, role):
    from app.permissions import service as perm
    from app.routes import warehouse_canonical_queries as q
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    run = _Run(client, allow_always_gate, db)
    await run.receive("10", "10")
    disp = await run.dispatch("5")
    await run.accept(disp, "5")
    legacy_role, assignments, member, allowed = ROLES[role]
    if member:
        await _member(db)
    monkeypatch.setattr(q, "db", db)
    monkeypatch.setattr(perm, "_load_assignments", _loader(assignments))
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    got = {read: await _status(q, mode, legacy_role, read) for read in READS}
    want = {read: (200 if read in allowed else 403) for read in READS}
    assert got == want


# ═══════════════ FG-53 / FG-55 (FLOW Guard pass 4) ═══════════════

from decimal import Decimal  # noqa: E402

from app.services.warehouse_movements import CanonicalAction, LocationKey, LocationType  # noqa: E402
from app.services.warehouse_movements.envelope import MovementState  # noqa: E402
from app.services.warehouse_movements.errors import InvariantViolationError  # noqa: E402
from app.services.warehouse_movements.service import CommandService  # noqa: E402
from tests.test_warehouse_canonical_c22_all_reports_cutover import PRJ, _inp  # noqa: E402


class _RecordingGate:
    def __init__(self):
        self.seen = []

    async def ensure(self, ctx, *, action, source, destination, project_id):
        self.seen.append((action.value, project_id))

    async def ensure_project_write_off(self, ctx, tenant_db, *, org_id, project_id):
        self.seen.append(("r27", project_id))


@pytest.mark.parametrize("command", ["consume", "return_to_warehouse", "transfer_p2p"])
async def test_fg53_a_move_from_a_project_belongs_to_the_source_project(
        canonical_mongo_db, allow_always_gate, monkeypatch, command):
    """Consume / transfer FROM P1 with body project_id = P2 → 422, nothing
    written, the gate never asked; without project_id → bound to P1.
    4a3d15c: the gate decided against the body's P2."""
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await db["projects"].insert_one({"id": OTHER_PROJECT, "org_id": T, "code": "P2",
                                     "name": "P2", "status": "Active"})
    run = _Run(client, allow_always_gate, db)
    await run.receive("10", "10")
    disp = await run.dispatch("10")
    await run.accept(disp, "10")
    gate = _RecordingGate()
    svc = CommandService(client, gate=gate)
    kw = {
        "consume": (CanonicalAction.CONSUME_TO_SMR, dict(source=PRJ, smr_id="smr")),
        "return_to_warehouse": (CanonicalAction.TRANSFER_PROJECT_TO_WAREHOUSE, dict(
            source=PRJ, transfer_target=LocationKey(
                LocationType.CENTRAL_WAREHOUSE, "wh_1", state=MovementState.QUARANTINE))),
        "transfer_p2p": (CanonicalAction.TRANSFER_PROJECT_TO_PROJECT, dict(
            source=PRJ, transfer_target=LocationKey(LocationType.PROJECT, OTHER_PROJECT))),
    }[command]
    count = await db["warehouse_transactions"].count_documents({"tenant_id": T})
    with pytest.raises(InvariantViolationError):
        await svc.execute(_UserCtx(), db, run.coll, _inp(
            kw[0], T, quantity=Decimal("1"), project_id=OTHER_PROJECT, **kw[1]))
    assert gate.seen == []
    assert await db["warehouse_transactions"].count_documents({"tenant_id": T}) == count
    res = await svc.execute(_UserCtx(), db, run.coll, _inp(
        kw[0], T, quantity=Decimal("1"), **kw[1]))
    assert res.envelope["project_id"] == PROJECT
    assert gate.seen == [(kw[0].value, PROJECT)]


async def test_fg55_subproject_mismatch_does_not_disclose_the_parent(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await db["projects"].insert_many([
        {"id": "p-secret", "org_id": T, "code": "PS", "name": "PS", "status": "Active"},
        {"id": "s-f", "org_id": T, "code": "SF", "name": "SF", "status": "Active",
         "parent_project_id": "p-secret"}])
    run = _Run(client, allow_always_gate, db)
    await run.receive("10", "10")
    disp = await run.dispatch("10")
    with pytest.raises(InvariantViolationError) as exc:
        await run(CanonicalAction.ACCEPT_PROJECT_DELIVERY,
                  destination=LocationKey(LocationType.SUBPROJECT, "s-f"),
                  quantity=Decimal("10"), accepted_quantity=Decimal("10"),
                  dispatch_movement_id=disp.movement_id, project_id=PROJECT)
    assert "p-secret" not in repr(exc.value.context) + str(exc.value)


# ═══════════ C26E-1 (HIGH) — audit probe test_probe_pr55_c26e_real_assignments ═══════════

@pytest.mark.parametrize("command", ["accept", "consume", "return_to_warehouse"])
@pytest.mark.parametrize("mode", ["off", "shadow", "enforce"])
@pytest.mark.parametrize("member", [False, True])
async def test_c26e_1_real_company_site_manager_same_in_every_mode(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode, command, member):
    """The probe's REAL assignment (grant_company_role: company-scope
    site_manager, permissions []). Non-member of P1 → DENIED in every mode,
    0 rows (4a3d15c: ALLOWED in enforce, DENIED in off); member → allowed in
    every mode."""
    from app.permissions import service as perm
    from app.services.warehouse_movements.errors import PermissionDeniedError
    from tests.test_warehouse_canonical_c26e_r28_all_modes import (
        _command, _count, _ctx, _prepare,
    )
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    run = _Run(client, allow_always_gate, db)
    pending = await _prepare(run)
    if member:
        await _member(db)
    monkeypatch.setattr(perm, "_load_assignments", _loader(_real("site_manager")))
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    action, kw = _command(command, pending)
    before = await _count(db)
    inp = _inp(action, T, quantity=Decimal("1"), **kw)
    if member:
        assert (await CommandService(client).execute(
            _ctx(mode, "SiteManager"), db, run.coll, inp)).movement_id
    else:
        with pytest.raises(PermissionDeniedError) as exc:
            await CommandService(client).execute(_ctx(mode, "SiteManager"), db, run.coll, inp)
        assert exc.value.context["reason_code"] == "R28_PROJECT_RELATION_REQUIRED"
        assert await _count(db) == before
