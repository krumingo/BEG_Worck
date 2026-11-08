"""CLAUDE AUDIT probe — #81 WH-FIX-01 (de0698d). Copy into backend/tests/; real Mongo RS
(MONGO_URL with replicaSet, WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1). Reuses the PR's harness.
  X1a FG-157 TOCTOU, deterministic: PUT /supplier-invoices reads "no link", a canonical receipt
      naming the invoice commits, then the PUT writes → is a LINKED invoice's line price edited?
  X1b the same as a free race ×10: PUT lines ∥ linked receipt → never both.
  X2  FG-191: an invoice line with no unit_price (line_total 100 / qty 3) → linked direct
      delivery of 3 → stored unit_value digits; project cost exactly 100?
  X4  FG-159: the CURRENT frontend payload of MaterialWastePanel ({material_name, qty, unit,
      waste_type, notes}; no item_id / key / file_ids) → status (observation: UI regression).
"""
import asyncio
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.services.warehouse_movements.actions import CanonicalAction
from tests.test_wh_fix_01_post_55 import (  # noqa: F401
    PRJ, PROJECT, SUP, T, WH, _Run, _patch_all, _seed, _user)

pytest_plugins = ["tests.warehouse_canonical_conftest"]


async def _si(db):
    await db["supplier_invoices"].insert_one({
        "id": "si-x", "org_id": T, "status": "reviewed", "vat_percent": 20,
        "updated_at": "2026-11-01T00:00:00+00:00",
        "lines": [{"id": "sl-1", "material_name": "Лепило", "qty": 10, "unit_price": 10,
                   "total_price": 100}], "subtotal": 100, "total": 120})


async def test_x1a_put_after_its_link_check(canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    _patch_all(monkeypatch, db)
    await _si(db)
    run = _Run(client, allow_always_gate, db)
    from app.routes import procurement
    real = procurement._supplier_invoice_link
    box = {}

    async def paused(*a, **k):
        r = await real(*a, **k)                     # "no link" — then the receipt commits
        box["rc"] = await run(CanonicalAction.RECEIVE_FROM_SUPPLIER, source=SUP, destination=WH,
                              quantity=Decimal("10"), unit_value=Decimal("10"), invoice_id="si-x")
        return r
    monkeypatch.setattr(procurement, "_supplier_invoice_link", paused)
    try:
        await procurement.update_supplier_invoice("si-x", {"lines": [
            {"id": "sl-1", "material_name": "Лепило", "qty": 10, "unit_price": 7}]}, user=_user())
        put = "200"
    except HTTPException as exc:
        put = exc.status_code
    inv = await db["supplier_invoices"].find_one({"id": "si-x"})
    linked = await db["warehouse_transactions"].count_documents({"invoice_id": "si-x"})
    print("X1a: PUT %s | linked receipts %d | line unit_price now %s" % (
        put, linked, inv["lines"][0].get("unit_price")))
    assert not (linked and inv["lines"][0].get("unit_price") == 7), \
        "a linked supplier invoice was edited (link check outside the write's transaction)"


@pytest.mark.parametrize("rep", range(10))
async def test_x1b_free_race(canonical_mongo_db, allow_always_gate, monkeypatch, rep):
    client, db = canonical_mongo_db
    _patch_all(monkeypatch, db)
    await _si(db)
    run = _Run(client, allow_always_gate, db)
    from app.routes import procurement
    put, rc = await asyncio.gather(
        procurement.update_supplier_invoice("si-x", {"lines": [
            {"id": "sl-1", "material_name": "Лепило", "qty": 10, "unit_price": 7}]}, user=_user()),
        run(CanonicalAction.RECEIVE_FROM_SUPPLIER, source=SUP, destination=WH,
            quantity=Decimal("10"), unit_value=Decimal("10"), invoice_id="si-x"),
        return_exceptions=True)
    inv = await db["supplier_invoices"].find_one({"id": "si-x"})
    linked = await db["warehouse_transactions"].count_documents({"invoice_id": "si-x"})
    # commit order from the tenant audit chain: the receipt's AuditEvent vs the PUT's
    put_seq = [e["sequence"] async for e in db["audit_events"].find(
        {"action": "procurement.supplier_invoice.updated", "entity_id": "si-x"}, {"sequence": 1})]
    rc_seq = [] if isinstance(rc, Exception) else [e["sequence"] async for e in db["audit_events"].find(
        {"entity_id": rc.movement_id}, {"sequence": 1})]
    order = ("receipt-first" if put_seq and rc_seq and rc_seq[0] < put_seq[0]
             else "put-first" if put_seq and rc_seq else "-")
    print("X1b/%d: PUT %s receipt %s | linked %d price %s | order %s (seq put %s receipt %s)" % (
        rep, getattr(put, "status_code", "200") if isinstance(put, Exception) else "200",
        type(rc).__name__ if isinstance(rc, Exception) else "ok", linked, inv["lines"][0].get("unit_price"),
        order, put_seq, rc_seq))
    assert order != "receipt-first", "the PUT edited a linked invoice (receipt committed first)"


async def test_x2_line_price_from_total_over_qty(canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    _patch_all(monkeypatch, db)
    await _seed(db)
    await db["invoice_lines"].insert_one({
        "id": "line-x2", "org_id": T, "invoice_id": "inv-x2", "qty": 3, "unit": "bag",
        "line_total_ex_vat": 100, "allocations": [{"type": "project", "ref_id": PROJECT, "qty": 3}]})
    run = _Run(client, allow_always_gate, db)
    res = await run(CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT, source=SUP, destination=PRJ,
                    quantity=Decimal("3"), invoice_id="inv-x2", invoice_line_id="line-x2",
                    project_id=PROJECT)
    row = await db["warehouse_transactions"].find_one({"movement_id": res.movement_id})
    me = await db["material_entries"].find({"project_id": PROJECT}).to_list(None)
    cost = (await run.cost())
    print("X2: stored unit_value %r | material_entries total_value %s | total_cost %r" % (
        row.get("unit_value"), [m.get("total_value") for m in me], cost["total_cost"]))
    assert Decimal(str(row["unit_value"])) * 3 == Decimal("100") or True   # observation


async def test_x4_current_ui_waste_payload(canonical_mongo_db, monkeypatch):
    client, db = canonical_mongo_db
    _patch_all(monkeypatch, db)
    from app.routes import material_waste as mw
    body = mw.WasteEntryCreate(material_name="Лепило", qty=2.0, unit="бр", waste_type="damaged", notes="")
    try:
        await mw.create_waste_entry(PROJECT, body, None, user=_user(), idempotency_key_header=None)
        st = "201"
    except HTTPException as exc:
        st = (exc.status_code, (exc.detail or {}).get("error_code"))
    print("X4: MaterialWastePanel payload ->", st)
