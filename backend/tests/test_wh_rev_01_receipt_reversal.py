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
    # FG-216: #81 made the route's Master identity strict — the item is a
    # confirmed md_item of the tenant (seeded once, idempotent).
    await wc.db["md_item"].update_one(
        {"id": ITEM}, {"$setOnInsert": {"id": ITEM, "tenant_id": T, "canonical_unit": "bag",
                                        "display_name": "Лепило"}}, upsert=True)
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


def _allocate_to(routes, project, reason="корекция след сторно"):
    # FG-195: after a reversal the reallocation is a correction — with a reason.
    from app.models.invoice_lines import InvoiceLineAllocationsUpdate
    return routes.allocate_invoice_line(IL, InvoiceLineAllocationsUpdate(
        allocations=[{"type": "project", "ref_id": project, "qty": 10}],
        correction_reason=reason), user=OWNER)


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
    # Р46 (Крум 08.11.2026, FG-194): Warehousekeeper, Accountant, Owner, Admin.
    "Owner": ("Owner", "owner", True, True),
    "Admin": ("Admin", "admin", True, True),
    "Warehousekeeper": ("Warehousekeeper", "warehouse", True, True),
    "Accountant": ("Accountant", "accountant", True, True),
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



@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("reason", ["   ", "\t\n", ""])
async def test_a_blank_reason_is_422_and_writes_nothing(canonical_mongo_db, allow_always_gate,
                                                       monkeypatch, mode, reason):
    """Audit note (#82): the reason is trimmed; blank → 422 REASON_REQUIRED,
    nothing written — at the route and in the service."""
    from app.services.warehouse_movements.errors import ReasonRequiredError
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate,
                                          monkeypatch, mode, allocations=ONLY_P)
    wc = _wc(monkeypatch, client, db)
    receipt = await _book(svc, mode, db, run, WH)
    before, audits = await _rows(db), await db["audit_events"].count_documents({})
    if reason:
        with pytest.raises(HTTPException) as exc:
            await _reverse(wc, mode, receipt, reason=reason)
        assert (exc.value.status_code, exc.value.detail["error_code"]) == (422, "REASON_REQUIRED")
    # the service refuses too (a direct caller cannot bypass the route)
    orig = await db["warehouse_transactions"].find_one({"movement_id": receipt})
    with pytest.raises(ReasonRequiredError):
        await svc.execute(_ctx(mode, "Owner"), db, run.coll, _inp(
            CanonicalAction.REVERSE_SUPPLIER_RECEIPT, T, source=WH,
            destination=LocationKey.from_dict(orig["source"]), quantity=Decimal("10"),
            reason=reason, reverses_movement_id=receipt))
    assert await _rows(db) == before
    assert await db["audit_events"].count_documents({}) == audits
    out = await _reverse(wc, mode, receipt, reason="  грешно засичане  ")
    assert out.envelope["reason"] == "грешно засичане"            # stored trimmed


# ═══════════════════ FG-195 — reallocation after a reversal is a correction ═══════════════════

@pytest.mark.parametrize("mode", MODES)
async def test_fg195_reallocation_after_a_reversal_on_a_paid_invoice_is_a_correction(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    """e9633aa: Paid invoice, linked receipt reversed, /allocate P → Q moved
    the cost silently (no reason, no version, no AuditEvent). Now: no reason
    → 409 ALLOCATION_CORRECTION_REQUIRED (#81's code), nothing written; with a reason → the change, a
    version snapshot of the line before it and a canonical AuditEvent, in
    one transaction. Costs follow (live + rebuild ×2)."""
    from app.models.invoice_lines import InvoiceLineAllocationsUpdate, InvoiceLineUpdate
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate,
                                          monkeypatch, mode, allocations=ONLY_P)
    routes, wc = _routes(monkeypatch, client, db), _wc(monkeypatch, client, db)
    await db["invoices"].update_one({"id": "inv-c26"}, {"$set": {"status": "Paid"}})
    receipt = await _book(svc, mode, db, run, PRJ)
    await _reverse(wc, mode, receipt)
    before = await db["invoice_lines"].find_one({"id": IL}, {"_id": 0})
    audits = await db["audit_events"].count_documents({"action": "finance.invoice_line.allocation_corrected"})
    to_q = [{"type": "project", "ref_id": Q, "qty": 10}]
    with pytest.raises(HTTPException) as exc:
        await routes.allocate_invoice_line(IL, InvoiceLineAllocationsUpdate(
            allocations=to_q, correction_reason="   "), user=OWNER)
    assert (exc.value.status_code, exc.value.detail["error_code"]) == (409, "ALLOCATION_CORRECTION_REQUIRED")
    # FG-213: on a Paid invoice #81's own check answers first — the same code.
    assert exc.value.detail["invoice_id"] == "inv-c26"
    with pytest.raises(HTTPException) as exc:          # PUT: a Paid invoice's lines stay
        await routes.update_invoice_line(IL, InvoiceLineUpdate(allocations=to_q),
                                         user=OWNER)
    assert exc.value.status_code == 400                # the Draft-only rule (unchanged)
    assert await db["invoice_lines"].find_one({"id": IL}, {"_id": 0}) == before
    assert await db["invoice_line_allocation_versions"].count_documents({"invoice_line_id": IL}) == 0
    assert await db["audit_events"].count_documents(
        {"action": "finance.invoice_line.allocation_corrected"}) == audits

    await routes.allocate_invoice_line(IL, InvoiceLineAllocationsUpdate(
        allocations=to_q, correction_reason="грешен обект при засичане"), user=OWNER)
    version = await db["invoice_line_allocation_versions"].find_one(
        {"invoice_line_id": IL}, {"_id": 0})                 # FG-213: #81's version store
    assert version["id"] == f"{IL}:v{int(before.get('allocation_version') or 0)}"
    assert version["allocations"] == before["allocations"]
    assert version["reason"] == "грешен обект при засичане"
    assert version["reversed_receipts"] == [receipt]
    events = await db["audit_events"].find(
        {"action": "finance.invoice_line.allocation_corrected", "entity_id": IL}).to_list(None)
    assert len(events) == 1
    diff = events[0]["structured_diff"]
    assert diff["allocations"]["before"][0]["ref_id"] == PROJECT
    assert diff["allocations"]["after"][0]["ref_id"] == Q
    assert diff["reversed_receipts"] == [receipt] and events[0]["reason"] == "грешен обект при засичане"

    async def check(i):
        assert await _costs(run) == (pytest.approx(0.0), pytest.approx(100.0)), i
    await _each_rebuild(db, check)


@pytest.mark.parametrize("mode", MODES)
async def test_fg195_a_never_linked_line_keeps_the_plain_rule(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    from app.models.invoice_lines import InvoiceLineAllocationsUpdate
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate,
                                          monkeypatch, mode, allocations=ONLY_P)
    routes = _routes(monkeypatch, client, db)
    await routes.allocate_invoice_line(IL, InvoiceLineAllocationsUpdate(
        allocations=[{"type": "project", "ref_id": Q, "qty": 10}]), user=OWNER)
    assert await db["invoice_line_allocation_versions"].count_documents({"invoice_line_id": IL}) == 0



@pytest.mark.parametrize("mode", MODES)
async def test_fg195_put_of_the_allocation_after_a_reversal_needs_a_reason(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    """The PUT path (Draft invoice): the same correction rule."""
    from app.models.invoice_lines import InvoiceLineUpdate
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate,
                                          monkeypatch, mode, allocations=ONLY_P)
    routes, wc = _routes(monkeypatch, client, db), _wc(monkeypatch, client, db)
    receipt = await _book(svc, mode, db, run, WH)
    await _reverse(wc, mode, receipt)
    to_q = [{"type": "project", "ref_id": Q, "qty": 10}]
    with pytest.raises(HTTPException) as exc:
        await routes.update_invoice_line(IL, InvoiceLineUpdate(allocations=to_q), user=OWNER)
    assert (exc.value.status_code, exc.value.detail["error_code"]) == (409, "ALLOCATION_CORRECTION_REQUIRED")
    assert await db["invoice_line_allocation_versions"].count_documents({"invoice_line_id": IL}) == 0
    out = await routes.update_invoice_line(
        IL, InvoiceLineUpdate(allocations=to_q, correction_reason="грешен обект"), user=OWNER)
    assert out["allocations"][0]["ref_id"] == Q and "reason" not in out
    assert await db["invoice_line_allocation_versions"].count_documents({"invoice_line_id": IL}) == 1
    assert await db["audit_events"].count_documents(
        {"action": "finance.invoice_line.allocation_corrected", "entity_id": IL}) == 1



async def test_r46_procurement_no_longer_reverses(canonical_mongo_db, allow_always_gate,
                                                  monkeypatch):
    """Р46: procurement books receipts but does not reverse them (enforce —
    procurement has no legacy session role)."""
    from app.permissions import service as perm
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate,
                                          monkeypatch, "enforce", allocations=ONLY_P)
    wc = _wc(monkeypatch, client, db)
    receipt = await _book(svc, "enforce", db, run, WH)
    monkeypatch.setattr(perm, "_load_assignments", _loader(_real("procurement")))
    before = await _rows(db)
    with pytest.raises(HTTPException) as exc:
        await _reverse(wc, "enforce", receipt)
    assert exc.value.status_code == 403
    assert await _rows(db) == before


# ═══════════════ Р47 — after a reversal the invoice awaits a credit note ═══════════════

async def _sent_invoice(canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    from tests.test_warehouse_canonical_c26l_n_invoice_status import _invoice
    db, lines, finance = await _invoice(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    await db["invoices"].update_one({"id": "inv-c26"}, {"$set": {"status": "Sent"}})
    return db, finance


def _pay(finance, amount, key):
    return finance.add_invoice_payment("inv-c26", {"amount": amount, "method": "BankTransfer",
                                                   "account_id": "acc-c26"},
                                       user=OWNER, idempotency_key=key)


@pytest.mark.parametrize("mode", MODES)
async def test_r47_reversal_makes_the_invoice_await_a_credit_note(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    """L 10 @10 (+20 % VAT = 120). 4 received (linked) and reversed: the
    invoice awaits a credit of 48; the Accountant's DQ task is listed; paying
    72 works, 1 more → 409 INVOICE_AWAITS_CREDIT_NOTE (quick-pay AND
    allocate), nothing written. A replay of the reversal adds no 2nd record."""
    from app.models.finance import AllocatePaymentRequest, PaymentCreate
    db, finance = await _sent_invoice(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    client = db.client
    from tests.test_warehouse_canonical_c25_cost_at_accept_transit import _Run
    run = _Run(client, allow_always_gate, db)
    from app.services.warehouse_movements.service import CommandService
    svc = CommandService(client)
    wc = _wc(monkeypatch, client, db)
    receipt = await _book(svc, mode, db, run, WH, qty="4")
    await _reverse(wc, mode, receipt)
    await _reverse(wc, mode, receipt)                                    # replay
    credits = await finance.list_expected_credit_notes(user=OWNER)
    assert len(credits) == 1
    c = credits[0]
    assert (c["invoice_id"], c["amount"], c["receipt_movement_id"]) == ("inv-c26", 48.0, receipt)
    assert "dq_task" not in c                    # FG-214: the expectation only
    issues = await db["dq_issues"].find({"type": "INVOICE_AWAITS_CREDIT_NOTE"},
                                        {"_id": 0}).to_list(None)
    assert len(issues) == 1
    assert (issues[0]["entity_id"], issues[0]["owner_role"], issues[0]["title"],
            issues[0]["status"], issues[0]["awaited_credit"]) == (
        "inv-c26", "accountant", "очаква кредитно известие", "open", 48.0)
    assert await db["alarm_events"].count_documents(
        {"rule_id": "INVOICE_AWAITS_CREDIT_NOTE", "status": "active"}) == 1
    assert await db["audit_events"].count_documents({"action": "dq.credit_note.opened"}) == 1
    assert (await db["invoices"].find_one({"id": "inv-c26"}))["awaiting_credit_note"] is True

    await _pay(finance, 72.0, "k-pay-1")
    allocs = await db["payment_allocations"].count_documents({})
    with pytest.raises(HTTPException) as exc:
        await _pay(finance, 1.0, "k-pay-2")
    assert (exc.value.status_code, exc.value.detail["error_code"]) == (
        409, "INVOICE_AWAITS_CREDIT_NOTE")
    assert exc.value.detail["awaited_credit"] == 48.0
    pay = await finance.create_payment(PaymentCreate(
        direction="Outflow", amount=1.0, date="2026-11-08", method="BankTransfer",
        account_id="acc-c26"), user=OWNER, idempotency_key="k-pay-3")
    with pytest.raises(HTTPException) as exc:
        await finance.allocate_payment(pay["id"], AllocatePaymentRequest(
            allocations=[{"invoice_id": "inv-c26", "amount": 1.0}]),
            user=OWNER, idempotency_key="k-alloc-1")
    assert (exc.value.status_code, exc.value.detail["error_code"]) == (
        409, "INVOICE_AWAITS_CREDIT_NOTE")
    assert await db["payment_allocations"].count_documents({}) == allocs   # nothing written


@pytest.mark.parametrize("mode", MODES)
async def test_r47_a_reversal_while_the_invoice_is_being_paid_is_409(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    """The PAY-01 row lock is held: the reversal is refused (409
    INVOICE_BUSY), nothing written; released → it goes through."""
    from datetime import datetime, timezone
    from app.services.invoice_state import ROW_LOCK_FIELD
    db, finance = await _sent_invoice(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    client = db.client
    from tests.test_warehouse_canonical_c25_cost_at_accept_transit import _Run
    from app.services.warehouse_movements.service import CommandService
    run, svc, wc = _Run(client, allow_always_gate, db), CommandService(client), \
        _wc(monkeypatch, client, db)
    receipt = await _book(svc, mode, db, run, WH, qty="4")
    await db["invoices"].update_one({"id": "inv-c26"}, {"$set": {ROW_LOCK_FIELD: {
        "token": "t", "at": datetime.now(timezone.utc).isoformat()}}})
    before = await _rows(db)
    with pytest.raises(HTTPException) as exc:
        await _reverse(wc, mode, receipt)
    assert (exc.value.status_code, exc.value.detail["error_code"]) == (409, "INVOICE_BUSY")
    assert await _rows(db) == before
    assert await db["expected_credit_notes"].count_documents({}) == 0
    await db["invoices"].update_one({"id": "inv-c26"}, {"$unset": {ROW_LOCK_FIELD: ""}})
    await _reverse(wc, mode, receipt)
    assert await db["expected_credit_notes"].count_documents({}) == 1


# ═══════════ WHREV82-M1 — a reversed receipt unlocks the supplier invoice ═══════════

@pytest.mark.parametrize("mode", MODES)
async def test_whrev82_m1_reversed_receipt_unlocks_the_supplier_invoice(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    """AUDIT-2 probe (claude/audit-log, test_probe_whrev01_silock.py): #81's
    FG-157 lock refuses an edit of a supplier invoice whose line a canonical
    receipt names (409 SUPPLIER_INVOICE_LINKED). After the receipt is
    REVERSED, neither it nor the reversal row locks the invoice — the edit
    passes. A second, live receipt locks it again."""
    from tests.test_wh_fix_01_post_55 import _patch_all, _user
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate,
                                          monkeypatch, mode, allocations=ONLY_P)
    wc = _wc(monkeypatch, client, db)
    _patch_all(monkeypatch, db)
    await db["supplier_invoices"].insert_one({
        "id": "si-rev", "org_id": T, "status": "reviewed", "vat_percent": 20,
        "updated_at": "2026-11-01T00:00:00+00:00",
        "lines": [{"id": IL, "material_name": "Лепило", "qty": 10, "unit_price": 10,
                   "total_price": 100}], "subtotal": 100, "total": 120})
    from app.routes import procurement

    async def edit(price):
        try:
            await procurement.update_supplier_invoice("si-rev", {"lines": [
                {"id": IL, "material_name": "Лепило", "qty": 10, "unit_price": price}]},
                user=_user())
            return 200, None
        except HTTPException as exc:
            d = exc.detail
            return exc.status_code, d.get("error_code") if isinstance(d, dict) else d

    receipt = await _book(svc, mode, db, run, WH)
    assert await edit(7) == (409, "SUPPLIER_INVOICE_LINKED")
    await _reverse(wc, mode, receipt)
    assert await edit(8) == (200, None)
    inv = await db["supplier_invoices"].find_one({"id": "si-rev"}, {"_id": 0})
    assert inv["lines"][0]["unit_price"] == 8
    await _book(svc, mode, db, run, WH, key="k-book-2")             # a live receipt again
    assert await edit(9) == (409, "SUPPLIER_INVOICE_LINKED")
