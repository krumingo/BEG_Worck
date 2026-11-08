"""
WH-FIX-01 — residue after #55 (FLOW-009 re-sweep of main cd03324).

Every test here was RED on main cd03324 and is GREEN after the fix
(docs/evidence/WH-FIX-01/). Real Mongo replica set (warehouse canonical
conftest). Items: FG-193, FG-192, FG-191, FG-150, FG-154 (high);
FG-161, FG-157, FG-159, FG-163, FG-190, FG-164 (medium).
"""
from __future__ import annotations

import importlib
import os
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.services.warehouse_movements.actions import CanonicalAction
from app.services.warehouse_movements.envelope import LocationKey, LocationType
from app.services.warehouse_movements.errors import (
    MasterIdentityMissingError, WarehouseMovementError,
)
from app.services.warehouse_movements.service import CommandService
from app.tenancy.data_access import TenantData
from tests.test_warehouse_canonical_c22_all_reports_cutover import (
    ITEM, PRJ, PROJECT, T, WH, _Ctx, _inp, _patch_dbs, _seed,
)
from tests.test_warehouse_canonical_c25_cost_at_accept_transit import SUP, _Run

pytest_plugins = ["tests.warehouse_canonical_conftest"]

REPO = Path(__file__).resolve().parents[2]
MAIN = "cd03324"

_EXTRA_DB_MODULES = (
    "app.routes.projects", "app.routes.dashboard", "app.routes.warehouses",
    "app.routes.warehouse_batches", "app.services.fifo_service",
    "app.services.material_waste", "app.routes.material_waste",
    "app.routes.warehouse_canonical", "app.routes.warehouse_canonical_queries",
    "app.utils.audit",
)


def _patch_all(monkeypatch, db, client=None):
    _patch_dbs(monkeypatch, db)
    for name in _EXTRA_DB_MODULES:
        mod = importlib.import_module(name)
        if hasattr(mod, "db"):
            monkeypatch.setattr(mod, "db", db)
    if client is not None:
        from app.routes import warehouse_canonical as route
        monkeypatch.setattr(route, "mongo_client", client)


def _user(role="Owner"):
    return {"id": f"u-{role}", "org_id": T, "role": role, "email": f"{role}@x"}


async def _accepted(run, qty="10", price="10"):
    await run.receive(qty, price)
    disp = await run.dispatch(qty)
    return await run.accept(disp, qty)


async def _ledger(db):
    return [r async for r in db["warehouse_transactions"].find({}, {"_id": 0})]


# ═══════════════════════════ FG-193 (high) ═══════════════════════════

def _scan_tree(tmp_path, rel, text):
    from app.services.warehouse_movements.legacy_inventory import (
        scan_repository_for_legacy_writers,
    )
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return scan_repository_for_legacy_writers(tmp_path)


def test_fg193_scanner_catches_the_main_create_sub_project_rewrite(tmp_path):
    """main's projects.py rewrites `warehouse_transactions.project_id` through
    `coll = tenant.collection(coll_name); coll.update_many(...)` — the scanner
    of main did not see it."""
    text = subprocess.run(["git", "show", f"{MAIN}:backend/app/routes/projects.py"],
                          cwd=REPO, capture_output=True, text=True, check=True).stdout
    hits = _scan_tree(tmp_path, "backend/app/routes/projects.py", text)
    assert [h for h in hits["warehouse_transactions"] if "update_many" in h["snippet"]]


@pytest.mark.parametrize("snippet,coll", [
    ('db["warehouse_transactions"].update_one({"a": 1}, {"$set": {}})\n', "warehouse_transactions"),
    ('tenant.collection("material_entries").delete_many({})\n', "material_entries"),
    ('c = db["warehouse_batches"]\nawait c.replace_one({}, {})\n', "warehouse_batches"),
    ('NAME = "warehouse_in_transit"\nc = tenant.collection(NAME)\nc.update_many({}, {})\n',
     "warehouse_in_transit"),
])
def test_fg193_scanner_catches_indirect_handles(tmp_path, snippet, coll):
    hits = _scan_tree(tmp_path, "backend/app/routes/x_fixture.py", snippet)
    assert hits[coll], hits


async def test_fg193_create_sub_project_leaves_the_canonical_ledger_alone(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    _patch_all(monkeypatch, db)
    await _seed(db)
    run = _Run(client, allow_always_gate, db)
    await _accepted(run)
    before = await _ledger(db)
    cost_before = (await run.cost())["total_cost"]
    from app.routes import projects
    res = await projects.create_sub_project(
        PROJECT, projects.CreateSubProjectRequest(name="Б"), user=_user())
    after = await _ledger(db)
    assert after == before                       # not one canonical row rewritten
    assert all(r.get("project_id") in (PROJECT, None) for r in after)
    assert (await run.cost())["total_cost"] == cost_before == 100.0
    assert res is not None


# ═══════════════════════════ FG-192 (high) ═══════════════════════════

async def test_fg192_unknown_item_is_refused_by_default(strict_mongo_db, allow_always_gate,
                                                       monkeypatch):
    client, db = strict_mongo_db
    monkeypatch.setenv("WAREHOUSE_STRICT_MASTER_IDENTITY", "0")     # no escape hatch
    svc = CommandService(client, gate=allow_always_gate)
    coll = TenantData.for_resolved_org(db, T).warehouse_transactions
    with pytest.raises(MasterIdentityMissingError):
        await svc.execute(_Ctx(T), db, coll, _inp(
            CanonicalAction.RECEIVE_FROM_SUPPLIER, source=SUP, destination=WH,
            item_id="any free text", unit_value=Decimal("1")))
    assert await db["warehouse_transactions"].count_documents({}) == 0
    # A Master item of the tenant passes; its canonical unit is server-derived.
    await db["md_item"].insert_one({"id": ITEM, "tenant_id": T, "canonical_unit": "bag",
                                    "display_name": "Лепило"})
    res = await svc.execute(_Ctx(T), db, coll, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER, source=SUP, destination=WH,
        unit="kg", unit_value=Decimal("1")))
    assert res.envelope["unit"] == "bag"


def test_fg192_production_route_is_strict_even_if_the_default_is_lowered(monkeypatch):
    from app.routes import warehouse_canonical as route
    from app.services.warehouse_movements import service
    monkeypatch.setattr(service, "STRICT_MASTER_IDENTITY_DEFAULT", False, raising=False)
    monkeypatch.setenv("WAREHOUSE_STRICT_MASTER_IDENTITY", "0")
    assert route._service()._strict_master is True


# ═══════════════════════════ FG-191 (high) ═══════════════════════════

async def _line(db, price=12.5, qty=10):
    await db["invoice_lines"].insert_one({
        "id": "line-191", "org_id": T, "invoice_id": "inv-191", "qty": qty, "unit": "bag",
        "unit_price": price, "line_total_ex_vat": price * qty,
        "allocations": [{"type": "warehouse", "ref_id": "wh_1", "qty": qty}]})


async def test_fg191_linked_receipt_price_differs_from_the_line_422(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    _patch_all(monkeypatch, db)
    await _line(db)
    run = _Run(client, allow_always_gate, db)
    with pytest.raises(WarehouseMovementError) as exc:
        await run(CanonicalAction.RECEIVE_FROM_SUPPLIER, source=SUP, destination=WH,
                  quantity=Decimal("4"), unit_value=Decimal("10"),
                  invoice_id="inv-191", invoice_line_id="line-191")
    assert exc.value.error_code == "INVOICE_LINE_PRICE_MISMATCH"
    assert await db["warehouse_transactions"].count_documents({}) == 0


async def test_fg191_linked_receipt_takes_the_line_price(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    _patch_all(monkeypatch, db)
    await _line(db)
    run = _Run(client, allow_always_gate, db)
    res = await run(CanonicalAction.RECEIVE_FROM_SUPPLIER, source=SUP, destination=WH,
                    quantity=Decimal("4"), invoice_id="inv-191", invoice_line_id="line-191")
    assert Decimal(str(res.envelope["unit_value"])) == Decimal("12.5")
    same = await run(CanonicalAction.RECEIVE_FROM_SUPPLIER, source=SUP, destination=WH,
                     quantity=Decimal("2"), unit_value=Decimal("12.50"),
                     invoice_id="inv-191", invoice_line_id="line-191")
    assert Decimal(str(same.envelope["unit_value"])) == Decimal("12.5")


async def test_fg191_manual_price_without_line_is_data_quality(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    from app.services.warehouse_movements.queries import integrity_warnings
    client, db = canonical_mongo_db
    _patch_all(monkeypatch, db)
    run = _Run(client, allow_always_gate, db)
    res = await run.receive("3", "9")
    out = await integrity_warnings(run.coll, tenant_id=T)
    rows = out["warnings"] if isinstance(out, dict) else out
    [w] = [w for w in rows if w["code"] == "MANUAL_PRICE_WITHOUT_INVOICE_LINE"]
    assert res.movement_id in w["movement_ids"]


# ═══════════════════════════ FG-150 (high) ═══════════════════════════

async def test_fg150_project_dashboard_and_aggregate_show_the_canonical_cost(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    _patch_all(monkeypatch, db)
    await _seed(db)
    run = _Run(client, allow_always_gate, db)
    await _accepted(run)                                  # 10 @ 10 accepted = 100
    from app.routes import projects
    dash = await projects.get_project_dashboard(PROJECT, user=_user())
    assert dash["materials"]["total_ex_vat"] == 100.0
    await db["projects"].insert_one({"id": "p-child", "org_id": T, "code": "P22-А",
                                     "name": "child", "parent_project_id": PROJECT,
                                     "created_at": "2026-01-01"})
    agg = await projects.get_project_aggregate(PROJECT, user=_user())
    assert agg["materials"]["own"]["ex_vat"] == 100.0
    assert agg["materials"]["total"]["ex_vat"] == 100.0


# ═══════════════════════════ FG-154 (high) ═══════════════════════════

async def test_fg154_finance_by_project_splits_by_the_line_allocation(
        canonical_mongo_db, monkeypatch):
    _client, db = canonical_mongo_db
    _patch_all(monkeypatch, db)
    for pid in ("p-1", "p-2"):
        await db["projects"].insert_one({"id": pid, "org_id": T, "code": pid, "name": pid})
    await db["invoices"].insert_one({
        "id": "inv-154", "org_id": T, "direction": "Received", "total": 1200.0,
        "issue_date": "2026-11-01",
        "allocations": [{"type": "project", "ref_id": "p-1"},
                        {"type": "project", "ref_id": "p-2"}]})
    await db["invoice_lines"].insert_one({
        "id": "l-154", "org_id": T, "invoice_id": "inv-154", "qty": 10, "unit_price": 100,
        "vat_percent": 20, "line_total_ex_vat": 1000, "vat_amount": 200,
        "line_total_inc_vat": 1200,
        "allocations": [{"type": "project", "ref_id": "p-1", "qty": 4},
                        {"type": "project", "ref_id": "p-2", "qty": 6}]})
    from app.routes import dashboard
    out = await dashboard.get_finance_by_project(
        user=_user(), date_from="2026-10-01", date_to="2026-11-30", preset=None,
        page=1, page_size=20)
    by = {r["project_id"]: r["total_expenses"] for r in out["items"]}
    assert by == {"p-1": 480.0, "p-2": 720.0}
    assert sum(by.values()) == 1200.0                    # never 2 × the invoice


# ═══════════════════════════ FG-161 (medium) ═══════════════════════════

async def _issued_scene(client, gate, db, monkeypatch):
    _patch_all(monkeypatch, db)
    await _seed(db)
    await db["warehouses"].insert_one({"id": "wh_1", "org_id": T, "type": "central",
                                       "name": "Централен", "active": True})
    run = _Run(client, gate, db)
    await _accepted(run)
    return run


@pytest.mark.parametrize("role", ["Viewer", "Driver", "Technician", "SiteManager",
                                  "Warehousekeeper"])
async def test_fg161_warehouse_transactions_hide_money_on_project_rows(
        canonical_mongo_db, allow_always_gate, monkeypatch, role):
    client, db = canonical_mongo_db
    await _issued_scene(client, allow_always_gate, db, monkeypatch)
    from app.routes import procurement
    from app.routes.warehouse_canonical_queries import is_money_key
    rows = await procurement.list_warehouse_transactions(user=_user(role))
    project_rows = [r for r in rows if r.get("project_id")]
    assert project_rows
    for r in project_rows:                          # Р20 / Р34 / Р35
        assert not [k for k in r if is_money_key(k)], (role, r.get("action"))
        for a in r.get("layer_allocations") or []:
            assert not [k for k in a if is_money_key(k)]
    receipt = [r for r in rows if r.get("action") == "receive_from_supplier"][0]
    if role == "Warehousekeeper":                   # Р32: the warehouse price stays
        assert "unit_value" in receipt
    elif role in ("Viewer", "Driver"):
        assert "unit_value" not in receipt


async def test_fg161_owner_still_sees_every_value(canonical_mongo_db, allow_always_gate,
                                                   monkeypatch):
    client, db = canonical_mongo_db
    await _issued_scene(client, allow_always_gate, db, monkeypatch)
    from app.routes import procurement
    rows = await procurement.list_warehouse_transactions(user=_user("Owner"))
    assert all("unit_value" in r for r in rows if r.get("action"))


async def test_fg161_batches_and_stock_hide_money_from_a_viewer(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    await _issued_scene(client, allow_always_gate, db, monkeypatch)
    await _legacy_main_stock(db)
    from app.routes import procurement, warehouse_batches
    viewer = _user("Viewer")
    batches = await warehouse_batches.list_batches(user=viewer, item_id="", warehouse_id="",
                                                   status="", page=1, page_size=50)
    assert batches["items"] and all("unit_value" not in b for b in batches["items"])
    stock = await procurement.get_stock_balance(user=viewer)
    assert stock and all("value" not in s for s in stock)
    dash = await procurement.get_inventory_dashboard(user=viewer)
    assert "total_value" not in dash["overview"]
    assert all("value" not in s for s in dash["stock"])


async def _legacy_main_stock(db):
    await db["warehouses"].update_one({"id": "wh_main"}, {"$set": {
        "id": "wh_main", "org_id": T, "type": "main", "name": "Main"}}, upsert=True)
    await db["warehouse_transactions"].insert_one({
        "id": "legacy-intake-1", "org_id": T, "warehouse_id": "wh_main", "type": "intake",
        "movement_id": "legacy-intake-1", "tenant_id": "__legacy__",
        "lines": [{"material_name": "Пясък", "unit": "t", "qty_received": 5,
                   "total_price": 50}]})


# ═══════════════════════════ FG-157 (medium) ═══════════════════════════

async def _supplier_invoice(db, inv_id="si-157", status="reviewed"):
    await db["supplier_invoices"].insert_one({
        "id": inv_id, "org_id": T, "status": status, "vat_percent": 20,
        "updated_at": "2026-11-01T00:00:00+00:00",
        "lines": [{"id": "sl-1", "material_name": "Лепило", "qty": 10, "unit_price": 10,
                   "total_price": 100}], "subtotal": 100, "total": 120})


async def test_fg157_linked_invoice_lines_are_locked(canonical_mongo_db, allow_always_gate,
                                                     monkeypatch):
    client, db = canonical_mongo_db
    _patch_all(monkeypatch, db)
    await _supplier_invoice(db)
    run = _Run(client, allow_always_gate, db)
    await run(CanonicalAction.RECEIVE_FROM_SUPPLIER, source=SUP, destination=WH,
              quantity=Decimal("10"), unit_value=Decimal("10"), invoice_id="si-157")
    from app.routes import procurement
    with pytest.raises(HTTPException) as exc:
        await procurement.update_supplier_invoice("si-157", {"lines": [
            {"id": "sl-1", "material_name": "Лепило", "qty": 10, "unit_price": 7}]},
            user=_user())
    assert exc.value.status_code == 409
    assert exc.value.detail["error_code"] == "SUPPLIER_INVOICE_LINKED"
    inv = await db["supplier_invoices"].find_one({"id": "si-157"})
    assert inv["lines"][0]["unit_price"] == 10                  # nothing written


async def test_fg157_unlinked_edit_writes_an_audit_event(canonical_mongo_db, monkeypatch):
    from app.audit.store import AUDIT_COLLECTION
    _client, db = canonical_mongo_db
    _patch_all(monkeypatch, db)
    await _supplier_invoice(db)
    from app.routes import procurement
    out = await procurement.update_supplier_invoice("si-157", {"lines": [
        {"id": "sl-1", "material_name": "Лепило", "qty": 10, "unit_price": 8}]},
        user=_user())
    assert out["subtotal"] == 80
    [ev] = [e async for e in db[AUDIT_COLLECTION].find(
        {"action": "procurement.supplier_invoice.updated", "entity_id": "si-157"})]
    assert ev["actor_id"] == "u-Owner"


@pytest.mark.parametrize("payload,status,code", [
    ({"status": "paid"}, 422, "SUPPLIER_INVOICE_STATUS_NOT_EDITABLE"),
    ({"total": 1}, 409, "SUPPLIER_INVOICE_CORRECTION_ONLY"),
])
async def test_fg157_paid_or_status_jump_is_correction_only(canonical_mongo_db, monkeypatch,
                                                            payload, status, code):
    _client, db = canonical_mongo_db
    _patch_all(monkeypatch, db)
    await _supplier_invoice(db, status="paid")
    from app.routes import procurement
    with pytest.raises(HTTPException) as exc:
        await procurement.update_supplier_invoice("si-157", payload, user=_user())
    assert (exc.value.status_code, exc.value.detail["error_code"]) == (status, code)


# ═══════════════════════════ FG-159 (medium) ═══════════════════════════

async def _waste_scene(client, gate, db, monkeypatch):
    _patch_all(monkeypatch, db, client)
    await _seed(db)
    await db["md_item"].insert_one({"id": ITEM, "tenant_id": T, "canonical_unit": "bag",
                                    "display_name": "Лепило"})
    run = _Run(client, gate, db)
    await _accepted(run)
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")      # legacy role decides (Р28)
    from app.routes import material_waste
    return material_waste


async def _waste(mw, data, user, key):
    """Call the route with whatever signature it has (main: no request / key)."""
    import inspect
    kw = {"user": user}
    params = inspect.signature(mw.create_waste_entry).parameters
    if "request" in params:
        kw["request"] = None
    if "idempotency_key_header" in params:
        kw["idempotency_key_header"] = key
    return await mw.create_waste_entry(PROJECT, data, **kw)


def _enforce_owner(monkeypatch, mw):
    """enforce: Tenant Guard → RoleAssignments (registry = fixture loader)."""
    from app.permissions import service as perm
    from app.routes import warehouse_canonical as canon
    from tests.test_warehouse_canonical_c26a_writeoff_rights_values import (
        USER, _assignment, _loader, _UserCtx,
    )
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "enforce")
    monkeypatch.setattr(perm, "_load_assignments", _loader([_assignment("owner")]))

    async def _ctx(request, user):
        ctx = _UserCtx()
        ctx.mode = "enforce"
        return ctx
    monkeypatch.setattr(canon, "require_project_writeoff", _ctx)
    return {"id": USER, "org_id": T, "role": "Owner", "email": "o@x"}


@pytest.mark.parametrize("mode", ["off", "shadow", "enforce"])
async def test_fg159_material_waste_is_a_canonical_write_off(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    client, db = canonical_mongo_db
    mw = await _waste_scene(client, allow_always_gate, db, monkeypatch)
    user = _user("Owner")
    if mode == "enforce":
        user = _enforce_owner(monkeypatch, mw)
    else:
        monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    data = mw.WasteEntryCreate(material_name="Лепило", item_id=ITEM, qty=2, unit="bag",
                               reason="счупени", file_ids=["f-159"])
    res = await _waste(mw, data, user, "wf-159")
    row = await db["warehouse_transactions"].find_one({"movement_id": res.get("movement_id")})
    assert row is not None, "no canonical movement was written"
    assert row["action"] == "write_off" and row["project_id"] == PROJECT
    assert Decimal(str(row["unit_value"])) == Decimal("10")    # FIFO value, not client
    assert row.get("audit_event_id")
    assert await db["material_waste_entries"].count_documents({}) == 0
    again = await _waste(mw, data, user, "wf-159")
    assert again["replay"] is True and again["movement_id"] == res["movement_id"]


@pytest.mark.parametrize("role,item,key,status", [
    ("Viewer", ITEM, "k", 403),
    ("Owner", None, "k", 422),
    ("Owner", ITEM, None, 428),
])
async def test_fg159_material_waste_refusals(canonical_mongo_db, allow_always_gate,
                                             monkeypatch, role, item, key, status):
    client, db = canonical_mongo_db
    mw = await _waste_scene(client, allow_always_gate, db, monkeypatch)
    before = await db["warehouse_transactions"].count_documents({})
    data = mw.WasteEntryCreate(material_name="Лепило", item_id=item, qty=1, unit="bag",
                               reason="брак", file_ids=["f"])
    with pytest.raises(HTTPException) as exc:
        await _waste(mw, data, _user(role), key)
    assert exc.value.status_code == status
    assert await db["warehouse_transactions"].count_documents({}) == before
    assert await db["material_waste_entries"].count_documents({}) == 0


# ═══════════════════════════ FG-163 (medium) ═══════════════════════════

@pytest.mark.parametrize("change", [{"type": "project", "project_id": PROJECT},
                                    {"active": False}])
async def test_fg163_put_warehouse_with_stock_is_refused_like_delete(
        canonical_mongo_db, allow_always_gate, monkeypatch, change):
    client, db = canonical_mongo_db
    _patch_all(monkeypatch, db)
    await db["warehouses"].insert_one({"id": "wh_1", "org_id": T, "type": "central",
                                       "name": "Централен", "active": True})
    run = _Run(client, allow_always_gate, db)
    await run.receive("5", "10")
    from app.models.warehouse import WarehouseUpdate
    from app.routes import warehouses
    with pytest.raises(HTTPException) as exc:
        await warehouses.update_warehouse("wh_1", WarehouseUpdate(**change), user=_user())
    assert exc.value.status_code == 409
    wh = await db["warehouses"].find_one({"id": "wh_1"})
    assert wh["type"] == "central" and wh["active"] is True
    # a rename stays allowed
    out = await warehouses.update_warehouse("wh_1", WarehouseUpdate(name="Нов"), user=_user())
    assert out["name"] == "Нов"


# ═══════════════════════════ FG-190 (medium) ═══════════════════════════

async def test_fg190_quantity_reports_read_the_canonical_ledger(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    _patch_all(monkeypatch, db)
    await _seed(db)
    await db["planned_materials"].update_one({"id": "pm-c22"}, {"$set": {
        "planned_qty": 20, "planned_qty_with_waste": 20, "unit": "bag"}})
    run = _Run(client, allow_always_gate, db)
    await _accepted(run)                                  # 10 bags on the project
    await run.consume("3")
    from app.services.material_waste import build_material_waste_summary
    summary = await build_material_waste_summary(T, PROJECT)
    [m] = [m for m in summary["materials"] if m["material_name"] == "Лепило"]
    assert m["issued_qty"] == 10 and m["delivered_qty"] == 10
    from app.routes import materials_baseline
    cov = await materials_baseline.get_material_coverage(PROJECT, user=_user())
    [row] = [r for r in cov["rows"] if r["material_name"] == "Лепило"]
    assert row["issued_qty"] == 10 and row["consumed_qty"] == 3
    from app.routes import procurement
    dash = await procurement.get_inventory_dashboard(user=_user())
    assert dash["overview"]["recent_intakes"] >= 1
    assert dash["overview"]["recent_issues"] >= 1


async def test_fg190_procurement_alerts_count_canonical_issues(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    _patch_all(monkeypatch, db)
    await _seed(db)
    await db["planned_materials"].update_one({"id": "pm-c22"}, {"$set": {
        "planned_qty": 20, "planned_qty_with_waste": 20, "unit": "bag"}})
    await db["material_requests"].insert_one({"id": "r", "org_id": T, "project_id": PROJECT,
                                              "status": "submitted", "lines": [
                                                  {"material_name": "Лепило", "qty_requested": 20}]})
    await db["supplier_invoices"].insert_one({"id": "s", "org_id": T, "project_id": PROJECT,
                                              "status": "reviewed", "lines": [
                                                  {"material_name": "Лепило", "qty": 20}]})
    run = _Run(client, allow_always_gate, db)
    await _accepted(run)
    from app.routes import revenue_snapshot
    out = await revenue_snapshot.get_procurement_alerts(PROJECT, user=_user())
    assert not [a for a in out["alerts"] if a["type"] == "purchased_not_issued"]


# ═══════════════════════════ FG-164 (medium) ═══════════════════════════

async def test_fg164_stock_screen_shows_the_canonical_warehouses(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    _patch_all(monkeypatch, db)
    await db["warehouses"].insert_one({"id": "wh_1", "org_id": T, "type": "central",
                                       "name": "Централен", "active": True})
    await db["md_item"].insert_one({"id": ITEM, "tenant_id": T, "display_name": "Лепило"})
    run = _Run(client, allow_always_gate, db)
    await run.receive("10", "10")
    await run(CanonicalAction.RECEIVE_FROM_SUPPLIER, source=SUP,
              destination=LocationKey(LocationType.SMALL_WAREHOUSE, "wh_b"),
              quantity=Decimal("4"), unit_value=Decimal("5"))
    from app.routes import procurement
    stock = await procurement.get_stock_balance(user=_user())
    canon = {(s["location"]["location_id"], s["qty"], s["value"]) for s in stock
             if s.get("source") == "canonical"}
    assert canon == {("wh_1", 10.0, 100.0), ("wh_b", 4.0, 20.0)}
    assert {s["material_name"] for s in stock} == {"Лепило"}
    dash = await procurement.get_inventory_dashboard(user=_user())
    assert dash["overview"]["total_value"] == 120.0


# ═════════════════════ WHFIX81-01 — FG-157 lock is decided in the tx ═════════════════════

async def test_whfix81_01_receipt_committing_between_check_and_write_is_409(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """Deterministic: the linked receipt commits right after the PUT's pre-check
    (which saw no link) and before its write → the PUT must answer 409 and write
    nothing (before: 200 and the linked line price changed 10 → 7)."""
    client, db = canonical_mongo_db
    _patch_all(monkeypatch, db)
    await _supplier_invoice(db)
    run = _Run(client, allow_always_gate, db)
    from app.routes import procurement
    original = procurement._supplier_invoice_link
    calls = []

    async def _racing_link(tenant, org_id, inv, **kw):
        found = await original(tenant, org_id, inv, **kw)
        if not calls:                             # the pre-check: no link yet …
            await run(CanonicalAction.RECEIVE_FROM_SUPPLIER, source=SUP, destination=WH,
                      quantity=Decimal("10"), unit_value=Decimal("10"), invoice_id="si-157")
        calls.append(kw.get("session") is not None)
        return found
    monkeypatch.setattr(procurement, "_supplier_invoice_link", _racing_link)
    with pytest.raises(HTTPException) as exc:
        await procurement.update_supplier_invoice("si-157", {"lines": [
            {"id": "sl-1", "material_name": "Лепило", "qty": 10, "unit_price": 7}]},
            user=_user())
    assert exc.value.status_code == 409
    assert exc.value.detail["error_code"] == "SUPPLIER_INVOICE_LINKED"
    assert True in calls                          # decided inside the transaction
    inv = await db["supplier_invoices"].find_one({"id": "si-157"})
    assert inv["lines"][0]["unit_price"] == 10 and inv["subtotal"] == 100   # nothing written
    lock = await db["warehouse_ledger_counters"].find_one(
        {"_id": f"supplier_invoice_lock:{T}:si-157"})
    assert lock and lock["value"] >= 1            # the receipt wrote the shared lock


async def test_whfix81_01_receipt_linked_by_line_id_locks_the_invoice(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    _patch_all(monkeypatch, db)
    await _supplier_invoice(db)
    run = _Run(client, allow_always_gate, db)
    await run(CanonicalAction.RECEIVE_FROM_SUPPLIER, source=SUP, destination=WH,
              quantity=Decimal("10"), unit_value=Decimal("10"), invoice_line_id="sl-1")
    assert await db["warehouse_ledger_counters"].find_one(
        {"_id": f"supplier_invoice_lock:{T}:si-157"})
    from app.routes import procurement
    with pytest.raises(HTTPException) as exc:
        await procurement.update_supplier_invoice("si-157", {"total": 1}, user=_user())
    assert exc.value.status_code == 409


# ═════════════════ WHFIX81-02 — the UI payload goes through (probe) ═════════════════

async def test_whfix81_02_the_ui_payload_is_a_canonical_write_off(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """The exact body MaterialWastePanel.js now sends (see its jest test)."""
    client, db = canonical_mongo_db
    mw = await _waste_scene(client, allow_always_gate, db, monkeypatch)
    ui_body = {"item_id": ITEM, "material_name": "Лепило", "qty": 2.0, "unit": "bag",
               "waste_type": "damaged", "notes": "", "reason": "Повреден",
               "file_ids": ["media-1"]}
    res = await _waste(mw, mw.WasteEntryCreate(**ui_body), _user("Owner"), "ui-key-1")
    row = await db["warehouse_transactions"].find_one({"movement_id": res["movement_id"]})
    assert row["action"] == "write_off" and row["file_ids"] == ["media-1"]
    assert row["reason"] == "Повреден"


# ═══════════════════ FG-191 — the line price is stored with 4 decimals ═══════════════════

async def test_fg191_line_price_is_stored_quantized(canonical_mongo_db, allow_always_gate,
                                                    monkeypatch):
    client, db = canonical_mongo_db
    _patch_all(monkeypatch, db)
    await db["invoice_lines"].insert_one({
        "id": "line-q", "org_id": T, "invoice_id": "inv-q", "qty": 3, "unit": "bag",
        "line_total_ex_vat": 100.0,
        "allocations": [{"type": "warehouse", "ref_id": "wh_1", "qty": 3}]})
    run = _Run(client, allow_always_gate, db)
    res = await run(CanonicalAction.RECEIVE_FROM_SUPPLIER, source=SUP, destination=WH,
                    quantity=Decimal("3"), invoice_id="inv-q", invoice_line_id="line-q")
    assert str(res.envelope["unit_value"]) == "33.3333"


# ═══════════ WHFIX81-03 / A4 (Р45) — no invoice disappears; line is the unit ═══════════

async def test_whfix81_03_header_only_invoices_are_in_the_bucket_never_dropped(
        canonical_mongo_db, monkeypatch):
    """A4 #8/#12: a header allocation is not counted on a project (no
    provisional split); the invoice is listed in „фактури за разпределяне"."""
    _client, db = canonical_mongo_db
    _patch_all(monkeypatch, db)
    for pid in ("p-1", "p-2"):
        await db["projects"].insert_one({"id": pid, "org_id": T, "code": pid, "name": pid})

    async def _inv(inv_id, total, header):
        await db["invoices"].insert_one({
            "id": inv_id, "org_id": T, "invoice_no": inv_id, "direction": "Received",
            "total": total, "issue_date": "2026-11-01", "status": "Sent", "allocations": header})
        await db["invoice_lines"].insert_one({          # a line WITHOUT a project allocation
            "id": "l-" + inv_id, "org_id": T, "invoice_id": inv_id, "qty": 1,
            "unit_price": total, "line_total_ex_vat": total, "line_total_inc_vat": total,
            "allocations": []})
    await _inv("h-single", 100.0, [{"type": "project", "ref_id": "p-1"}])
    await _inv("h-percent", 90.0, [{"type": "project", "ref_id": "p-1", "percent": 30},
                                   {"type": "project", "ref_id": "p-2", "percent": 70}])
    await _inv("h-split", 50.0, [{"type": "project", "ref_id": "p-1"},
                                 {"type": "project", "ref_id": "p-2"}])
    from app.routes import dashboard

    async def _report():
        return await dashboard.get_finance_by_project(
            user=_user(), date_from="2026-10-01", date_to="2026-11-30", preset=None,
            page=1, page_size=20)
    out = await _report()
    assert out["items"] == []                           # nothing counted from a header
    bucket = {u["invoice_id"]: u for u in out["to_allocate"]}
    assert set(bucket) == {"h-single", "h-percent", "h-split"}
    assert bucket["h-single"]["header_destinations"][0]["project_name"] == "p-1"
    tenant = TenantData.for_resolved_org(db, T)
    from app.services.invoice_allocation import invoices_to_allocate, migrate_header_allocations
    assert {i["id"] for i in await invoices_to_allocate(tenant, T)} == set(bucket)
    # A4 #11: the migration — dry run writes nothing; apply writes the single one
    dry = await migrate_header_allocations(tenant, T, _user(), dry_run=True)
    assert [w["invoice_id"] for w in dry["written"]] == ["h-single"]
    assert sorted(dry["pending"]) == ["h-percent", "h-split"]
    assert (await db["invoice_lines"].find_one({"id": "l-h-single"}))["allocations"] == []
    done = await migrate_header_allocations(tenant, T, _user(), dry_run=False)
    assert done["written"] == [{"invoice_id": "h-single", "lines_written": 1}]
    line = await db["invoice_lines"].find_one({"id": "l-h-single"})
    assert [(a["type"], a["ref_id"], a["qty"]) for a in line["allocations"]] == [("project", "p-1", 1)]
    from app.audit.store import AUDIT_COLLECTION
    assert await db[AUDIT_COLLECTION].count_documents(
        {"action": "finance.invoice_line.allocation_corrected", "entity_id": "l-h-single"}) == 1
    again = await migrate_header_allocations(tenant, T, _user(), dry_run=False)   # idempotent
    assert again["written"] == [] and "h-single" in again["skipped"]
    assert await db[AUDIT_COLLECTION].count_documents(
        {"action": "finance.invoice_line.allocation_corrected", "entity_id": "l-h-single"}) == 1
    out = await _report()
    assert {r["project_id"]: r["total_expenses"] for r in out["items"]} == {"p-1": 100.0}
    assert {u["invoice_id"] for u in out["to_allocate"]} == {"h-percent", "h-split"}
    assert await db["dq_issues"].count_documents({"entity_id": "h-percent", "status": "open"}) == 1
