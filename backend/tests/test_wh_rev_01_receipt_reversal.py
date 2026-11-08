"""
WH-REV-01 — reversal (сторно) of a supplier receipt (debt from #55: FG-109 /
F-55-C26-03). After the first linked movement the invoice line's allocation
is locked (409) and main had NO canonical reversal of a receipt: a booking
error could not be corrected at all.

Canon: FLOW-009 (correction by a reverse movement), FLOW-043 D-04 (one cost
path), CLAUDE §2.9 (no hard delete), §7 (reversal, not edit), §14.

POST /api/warehouse/canonical/receipts/{movement_id}/reverse writes ONE new
ledger row (reverse_supplier_receipt[_to_project]) that takes exactly the
receipt's own lot back to the supplier at its own value; the receipt row
stays. It unlocks the invoice line (covered quantity drops in the same
per-line-lock transaction). Real Mongo (replica set), off / shadow / enforce.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.services.warehouse_movements import CanonicalAction, LocationKey, LocationType
from app.services.warehouse_movements.errors import NegativeStockError
from app.services.warehouse_movements.fifo import free_balance
from app.services.warehouse_movements.projections import rebuild_from_ledger
from tests.test_warehouse_canonical_c22_all_reports_cutover import (
    ITEM, PRJ, PROJECT, T, WH, _inp,
)
from tests.test_warehouse_canonical_c26_one_path_per_lot import IL
from tests.test_warehouse_canonical_c26a_writeoff_rights_values import USER, _loader
from tests.test_warehouse_canonical_c26e_r28_all_modes import _ctx, _real
from tests.test_warehouse_canonical_c26l_cross_project_link import Q
from tests.test_warehouse_canonical_c26l_l_all_paths_lock import (
    MODES, OWNER, _prepare, _receipt, _routes, _staff,
)

pytest_plugins = ["tests.warehouse_canonical_conftest"]

Q_LOC = LocationKey(LocationType.PROJECT, Q)
from tests.test_warehouse_canonical_c25_cost_at_accept_transit import SUP as _SUP  # noqa: E402
ONLY_P = [{"type": "project", "ref_id": PROJECT, "qty": 10}]


def _wc(monkeypatch, client, db):
    from app.routes import warehouse_canonical as wc
    monkeypatch.setattr(wc, "db", db)
    monkeypatch.setattr(wc, "mongo_client", client)
    return wc


async def _reverse(wc, mode, movement_id, *, key="k-rev", reason="грешно засичане",
                   role="Owner"):
    user = {"id": USER, "org_id": T, "role": role, "email": "e@x"}
    return await wc.post_receipt_reversal(
        movement_id, wc.ReceiptReversalBody(reason=reason), None,
        user=user, ctx=_ctx(mode, role), idempotency_key=key)


async def _book(svc, mode, db, run, dest, qty="10", key=None):
    res = await svc.execute(_ctx(mode, "Owner"), db, run.coll, _receipt(dest, qty, key))
    return res.movement_id


async def _rows(db, **flt):
    return await db["warehouse_transactions"].count_documents({"tenant_id": T, **flt})


async def _costs(run):
    return ((await run.cost(PROJECT))["total_cost"], (await run.cost(Q))["total_cost"])


async def _each_rebuild(db, check):
    for i in range(3):
        if i:
            await rebuild_from_ledger(db, tenant_id=T)
        await check(i)


def _allocate_to(routes, project):
    from app.models.invoice_lines import InvoiceLineAllocationsUpdate
    return routes.allocate_invoice_line(IL, InvoiceLineAllocationsUpdate(
        allocations=[{"type": "project", "ref_id": project, "qty": 10}]), user=OWNER)


# ═══════════════════════ the gap (fails on main) ═══════════════════════

@pytest.mark.parametrize("mode", MODES)
async def test_gap_a_locked_line_is_corrected_through_a_receipt_reversal(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    """main @ cd03324: the linked receipt locks L (409) and there is no
    reversal — the allocation can never be corrected. Now: reverse → 201,
    the line unlocks, the reallocation goes through."""
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate,
                                          monkeypatch, mode, allocations=ONLY_P)
    routes, wc = _routes(monkeypatch, client, db), _wc(monkeypatch, client, db)
    receipt = await _book(svc, mode, db, run, WH)
    with pytest.raises(HTTPException) as exc:
        await _allocate_to(routes, Q)
    assert exc.value.status_code == 409
    out = await _reverse(wc, mode, receipt)
    assert out.envelope["action"] == "reverse_supplier_receipt"
    assert out.envelope["reverses_movement_id"] == receipt
    await _allocate_to(routes, Q)                      # unlocked
    assert await _rows(db, movement_id=receipt) == 1    # the receipt stays


# ═══════════════════════ full flows, live + rebuild ×2 ═══════════════════════

@pytest.mark.parametrize("mode", MODES)
async def test_warehouse_receipt_reversed_reallocated_and_delivered_again(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate,
                                          monkeypatch, mode, allocations=ONLY_P)
    routes, wc = _routes(monkeypatch, client, db), _wc(monkeypatch, client, db)
    receipt = await _book(svc, mode, db, run, WH)
    await _reverse(wc, mode, receipt)
    assert await free_balance(run.coll, tenant_id=T, item_id=ITEM, location=WH) == 0
    await _allocate_to(routes, Q)
    await _book(svc, mode, db, run, Q_LOC, key="k-q")

    async def check(i):
        assert await _costs(run) == (pytest.approx(0.0), pytest.approx(100.0)), i
        assert await free_balance(run.coll, tenant_id=T, item_id=ITEM, location=WH) == 0
        batch = await db["warehouse_batches"].find_one({"movement_id": receipt})
        assert Decimal(batch["remaining_quantity"]) == 0, i
    await _each_rebuild(db, check)


@pytest.mark.parametrize("mode", MODES)
async def test_direct_delivery_reversed_the_project_cost_follows(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    """Direct 10 @10 into P (L allocated to P): P 100 (canon). Reversed: the
    canonical −100 row; L is P's Path B again (100, the invoice is still P's).
    Reallocated to Q: P 0 / Q 100; delivered into Q: Q 100 once. Live +
    rebuild ×2 at every stage."""
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate,
                                          monkeypatch, mode, allocations=ONLY_P)
    routes, wc = _routes(monkeypatch, client, db), _wc(monkeypatch, client, db)
    receipt = await _book(svc, mode, db, run, PRJ)
    await _reverse(wc, mode, receipt)
    p = await run.cost(PROJECT)
    assert p["canonical_cost"] == pytest.approx(0.0) and p["invoice_cost"] == pytest.approx(100.0)
    kinds = sorted(r["movement_kind"] for r in await db["material_entries"].find(
        {"org_id": T, "project_id": PROJECT}).to_list(None))
    assert kinds == ["accept", "receipt_reversal"]
    await _allocate_to(routes, Q)
    await _book(svc, mode, db, run, Q_LOC, key="k-q")

    async def check(i):
        assert await _costs(run) == (pytest.approx(0.0), pytest.approx(100.0)), i
        q = await run.cost(Q)
        assert (q["canonical_cost"], q["invoice_cost"]) == (pytest.approx(100.0), 0), i
    await _each_rebuild(db, check)


# ═══════════════════════ refusals (409 / 422 / 404 / 428) ═══════════════════════

@pytest.mark.parametrize("mode", MODES)
async def test_reversal_of_an_issued_lot_is_409_and_names_what_took_it(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate,
                                          monkeypatch, mode, allocations=ONLY_P)
    wc = _wc(monkeypatch, client, db)
    receipt = await _book(svc, mode, db, run, WH)
    dispatch = await _staff(mode, run.dispatch("4"))
    before = await _rows(db)
    with pytest.raises(HTTPException) as exc:
        await _reverse(wc, mode, receipt)
    assert exc.value.status_code == 409
    ctx = exc.value.detail["context"]
    assert ctx["code"] == "RECEIPT_ALREADY_ISSUED"
    assert [t["movement_id"] for t in ctx["taken_by"]] == [dispatch.movement_id]
    assert (ctx["received"], ctx["still_in_bucket"]) == ("10", "6")
    assert await _rows(db) == before                   # nothing written


@pytest.mark.parametrize("mode", MODES)
async def test_reversal_of_a_consumed_direct_delivery_is_409(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate,
                                          monkeypatch, mode, allocations=ONLY_P)
    wc = _wc(monkeypatch, client, db)
    receipt = await _book(svc, mode, db, run, PRJ)
    await _staff(mode, run.consume("3"))
    with pytest.raises(HTTPException) as exc:
        await _reverse(wc, mode, receipt)
    assert exc.value.status_code == 409
    assert exc.value.detail["context"]["code"] == "RECEIPT_ALREADY_ISSUED"
    assert await _rows(db, action="reverse_supplier_receipt_to_project") == 0


@pytest.mark.parametrize("mode", MODES)
async def test_double_reversal_wrong_kind_unknown_and_missing_key(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate,
                                          monkeypatch, mode, allocations=ONLY_P)
    wc = _wc(monkeypatch, client, db)
    receipt = await _book(svc, mode, db, run, WH)
    first = await _reverse(wc, mode, receipt)
    with pytest.raises(HTTPException) as exc:                     # a second reversal
        await _reverse(wc, mode, receipt, key="k-rev-2")
    assert (exc.value.status_code, exc.value.detail["context"]["code"]) == (
        409, "RECEIPT_ALREADY_REVERSED")
    with pytest.raises(HTTPException) as exc:                     # the reversal itself
        await _reverse(wc, mode, first.movement_id, key="k-rev-3")
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:                     # unknown / other tenant
        await _reverse(wc, mode, "mv_does_not_exist", key="k-rev-4")
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:                     # R29
        await _reverse(wc, mode, receipt, key="  ")
    assert exc.value.status_code == 428
    assert await _rows(db, action="reverse_supplier_receipt") == 1


async def test_movements_endpoint_refuses_a_reversal_action():
    from pydantic import ValidationError
    from app.routes.warehouse_canonical import MovementCommandBody
    with pytest.raises(ValidationError):
        MovementCommandBody(action="reverse_supplier_receipt", item_id="i", unit="u",
                            quantity="1", idempotency_key="k")


# ═══════════════════════ idempotency / crash ═══════════════════════

@pytest.mark.parametrize("mode", MODES)
async def test_same_key_is_one_reversal_and_a_crash_after_the_audit_event_writes_nothing(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    from app.services.warehouse_movements import projections
    from app.services.warehouse_movements.errors import AuditChainWriteError
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate,
                                          monkeypatch, mode, allocations=ONLY_P)
    wc = _wc(monkeypatch, client, db)
    receipt = await _book(svc, mode, db, run, WH)
    real = projections.apply_projection

    async def crash(*a, **k):                  # after the in-tx AuditEvent
        raise RuntimeError("crash after the AuditEvent")
    monkeypatch.setattr(projections, "apply_projection", crash)
    audits = await db["audit_events"].count_documents({})
    with pytest.raises((AuditChainWriteError, HTTPException)):
        await _reverse(wc, mode, receipt)
    assert await _rows(db, action="reverse_supplier_receipt") == 0
    assert await db["audit_events"].count_documents({}) == audits
    monkeypatch.setattr(projections, "apply_projection", real)
    first = await _reverse(wc, mode, receipt)
    again = await _reverse(wc, mode, receipt)
    assert again.replay is True and again.movement_id == first.movement_id
    assert await _rows(db, action="reverse_supplier_receipt") == 1
    events = await db["audit_events"].find(
        {"entity_id": first.movement_id}).to_list(None)
    assert len(events) == 1
    assert events[0]["structured_diff"]["reverses_movement_id"] == receipt
    with pytest.raises(HTTPException) as exc:             # same key, other payload
        await _reverse(wc, mode, receipt, reason="друга причина")
    assert exc.value.status_code == 409


# ═══════════════════════ concurrency ═══════════════════════

@pytest.mark.parametrize("rep", range(10))
@pytest.mark.parametrize("mode", MODES)
async def test_reversal_racing_an_issue(canonical_mongo_db, allow_always_gate, monkeypatch,
                                        mode, rep):
    """Concurrently: reverse the receipt of 10 ∥ dispatch 4 of it. Exactly
    one wins — never both, stock never negative (live + rebuild ×2)."""
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate,
                                          monkeypatch, mode, allocations=ONLY_P)
    wc = _wc(monkeypatch, client, db)
    receipt = await _book(svc, mode, db, run, WH)
    dispatch = _inp(CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT, T, source=WH,
                    quantity=Decimal("4"), project_id=PROJECT)
    rev, dis = await asyncio.gather(
        _reverse(wc, mode, receipt),
        svc.execute(_ctx(mode, "Owner"), db, run.coll, dispatch),
        return_exceptions=True)
    if isinstance(rev, Exception):
        assert isinstance(rev, HTTPException) and rev.status_code == 409, rev
        assert not isinstance(dis, Exception), dis
        want = Decimal("6")
    else:
        assert isinstance(dis, NegativeStockError), dis
        want = Decimal("0")

    async def check(i):
        assert await free_balance(run.coll, tenant_id=T, item_id=ITEM, location=WH) == want, i
    await _each_rebuild(db, check)


# ═══════════════════════ rights (R16 / R28), 3 modes ═══════════════════════

ROLE_CASES = {          # legacy role, catalog role, may reverse (warehouse, direct)
    "Owner": ("Owner", "owner", True, True),
    "Admin": ("Admin", "admin", True, True),
    "Warehousekeeper": ("Warehousekeeper", "warehouse", True, False),
    "Accountant": ("Accountant", "accountant", False, False),
    "SiteManager": ("SiteManager", "site_manager", False, False),
    "Technician": ("Technician", "LEGACY_TECHNICIAN", False, False),
    "Viewer": ("Viewer", "LEGACY_VIEWER", False, False),
    "Driver": ("Driver", "driver", False, False),
}


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("role", list(ROLE_CASES))
async def test_rights_are_the_rights_of_the_receipt(canonical_mongo_db, allow_always_gate,
                                                     monkeypatch, mode, role):
    from app.permissions import service as perm
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate,
                                          monkeypatch, mode, allocations=ONLY_P)
    wc = _wc(monkeypatch, client, db)
    to_wh = await _book(svc, mode, db, run, WH)
    direct = (await svc.execute(_ctx(mode, "Owner"), db, run.coll, _inp(   # unlinked lot
        CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT, T, source=_SUP, destination=PRJ,
        quantity=Decimal("5"), unit_value=Decimal("10"), project_id=PROJECT))).movement_id
    legacy, role_id, may_wh, may_direct = ROLE_CASES[role]
    monkeypatch.setattr(perm, "_load_assignments", _loader(_real(role_id)))
    for receipt, allowed, action in ((to_wh, may_wh, "reverse_supplier_receipt"),
                                     (direct, may_direct,
                                      "reverse_supplier_receipt_to_project")):
        before = await _rows(db)
        if allowed:
            out = await _reverse(wc, mode, receipt, key=f"k-{receipt}", role=legacy)
            assert out.envelope["action"] == action
        else:
            with pytest.raises(HTTPException) as exc:
                await _reverse(wc, mode, receipt, key=f"k-{receipt}", role=legacy)
            assert exc.value.status_code == 403, (role, action)
            assert await _rows(db) == before                     # nothing written
