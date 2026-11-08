"""LIVE-OPS-01 / TASK 5C — 5C-C18 audit corrections (PR #55).

Pins the decisions taken in 5C-C18 so they cannot drift back:

  * F-55-2 — the A2C/A1 tenant guards are clean without new exceptions
    (the guard tests themselves run in the W0 suite; here we pin the
    concrete warehouse sites that used to be raw/ownerless);
  * F-55-3 — ``audit_chain_head`` is a ``tenant_id``-keyed audit store
    (next to ``audit_events``/``audit_counters``), not an org_id-keyed
    warehouse collection, so the A2B backfill never treats it as ownerless;
  * F-55-4 — the dev warehouse reset refuses (409) only when CANONICAL
    ledger history exists (rows the command service appended carry the
    server-allocated ``ledger_sequence``); legacy-only history keeps the
    W0-03E/R0-07 behaviour from main;
  * the ledger counter can only be reached through the same server-resolved
    tenant that scopes the ledger collection.

Run (DB-free):
    PYTHONPATH=. pytest --noconftest -q tests/test_warehouse_canonical_c18_corrections.py
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from app.tenancy import ownership
from app.tenancy.data_access import TenantData

from tests.test_w0_03e_legacy_migration import ORG_A, ORG_B, new_db, run
from tests.test_w0_03e_legacy_routes import ADMIN, client_for, db_with
from app.routes import warehouses

BACKEND = Path(__file__).resolve().parent.parent


# ───────────────────────── F-55-3 classification ─────────────────────────

def test_audit_chain_head_is_a_tenant_id_keyed_audit_store():
    assert ownership.classify_collection("audit_chain_head") == ownership.CLASS_TENANT_ID
    assert "audit_chain_head" not in ownership.ORG_KEYED


def test_warehouse_counter_and_projections_stay_org_keyed():
    for coll in ("warehouse_ledger_counters", "warehouse_in_transit",
                 "warehouse_batches", "material_entries", "warehouse_transactions"):
        assert ownership.classify_collection(coll) == ownership.CLASS_ORG, coll


# ───────────────────────── F-55-2 guards ─────────────────────────

def test_warehouse_movements_are_clean_under_the_a2c_guard():
    """A2C applies its whole-tree rules to the named files (A1 is pinned by
    its own W0 test over the whole tree)."""
    files = sorted(str(p.relative_to(BACKEND)) for p in
                   (BACKEND / "app" / "services" / "warehouse_movements").glob("*.py"))
    files += ["app/routes/warehouses.py", "app/routes/warehouse_migration.py",
              "app/routes/warehouse_canonical.py"]
    r = subprocess.run([sys.executable,
                        str(BACKEND / "scripts" / "w0_03e_a2c_tenant_boundary_guard.py"), *files],
                       cwd=BACKEND, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr
    assert ", 0 violation(s)" in r.stdout


def test_no_raw_counter_or_chain_head_alias_remains():
    src = (BACKEND / "app/services/warehouse_movements/service.py").read_text()
    assert "_scope._db" not in src
    assert "chain_head_coll" not in src
    assert "tenant.warehouse_ledger_counters.find_one_and_update" in src


# ───────────────────────── ledger counter tenant ─────────────────────────

def test_ledger_counter_refuses_a_tenant_other_than_the_scoped_one():
    from app.services.warehouse_movements.errors import InvariantViolationError
    from app.services.warehouse_movements.service import CommandService

    svc = CommandService.__new__(CommandService)
    coll = TenantData.for_resolved_org(new_db(), ORG_A).warehouse_transactions
    with pytest.raises(InvariantViolationError):
        run(svc._next_ledger_sequence(coll, tenant_id=ORG_B, session=None))


def test_ledger_counter_document_carries_the_server_resolved_org_id():
    from app.services.warehouse_movements.service import CommandService

    db = new_db()
    svc = CommandService.__new__(CommandService)
    coll = TenantData.for_resolved_org(db, ORG_A).warehouse_transactions
    assert run(svc._next_ledger_sequence(coll, tenant_id=ORG_A, session=None)) == 1
    assert run(svc._next_ledger_sequence(coll, tenant_id=ORG_A, session=None)) == 2
    docs = run(db["warehouse_ledger_counters"].find({}, {"_id": 0}).to_list(None))
    assert docs == [{"tenant_id": ORG_A, "name": "ledger_sequence", "org_id": ORG_A, "value": 2}] \
        or docs == [{"org_id": ORG_A, "tenant_id": ORG_A, "name": "ledger_sequence", "value": 2}]


# ───────────────────────── migration readiness ─────────────────────────

def test_main_to_central_report_reads_only_the_tenants_warehouses():
    from app.services.warehouse_movements.migration_readiness import main_to_central_report

    db = new_db()

    async def seed():
        await db["warehouses"].insert_one({"id": "w1", "org_id": ORG_A, "type": "main",
                                           "code": "A1", "name": "A main"})
        await db["warehouses"].insert_one({"id": "w2", "org_id": ORG_A, "type": "central",
                                           "code": "A2", "name": "A central"})
        await db["warehouses"].insert_one({"id": "w1", "org_id": ORG_B, "type": "main",
                                           "code": "B1", "name": "B main"})
    run(seed())
    out = run(main_to_central_report(TenantData.for_resolved_org(db, ORG_A).warehouses,
                                     tenant_id=ORG_A))
    assert out["legacy_main_warehouses"] == [{"id": "w1", "code": "A1", "name": "A main"}]
    assert out["proposed_rename_count"] == 1 and out["dry_run"] is True


# ───────────────────────── F-55-4 dev reset ─────────────────────────

def test_dev_reset_refuses_when_canonical_ledger_history_exists(monkeypatch):
    monkeypatch.setenv("ENV", "test")
    db = db_with("warehouses", {"id": "w1", "org_id": ORG_A, "name": "A", "active": True})
    run(db["warehouse_transactions"].insert_one({
        "movement_id": "m1", "tenant_id": ORG_A, "org_id": ORG_A,
        "action": "receive_from_supplier", "ledger_sequence": 1,
    }))
    r = client_for(monkeypatch, warehouses, db, ADMIN).post("/api/dev/reset-warehouses")
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error_code"] == "CANONICAL_LEDGER_PRESENT"
    assert run(db["warehouses"].count_documents({"id": "w1", "org_id": ORG_A})) == 1
    assert run(db["warehouse_transactions"].count_documents({})) == 1


def test_dev_reset_ignores_another_tenants_canonical_ledger(monkeypatch):
    monkeypatch.setenv("ENV", "test")
    db = db_with("warehouses", {"id": "w1", "org_id": ORG_A, "name": "A", "active": True})
    run(db["warehouse_transactions"].insert_one({
        "movement_id": "m1", "tenant_id": ORG_B, "org_id": ORG_B,
        "action": "receive_from_supplier", "ledger_sequence": 1,
    }))
    r = client_for(monkeypatch, warehouses, db, ADMIN).post("/api/dev/reset-warehouses")
    assert r.status_code == 200, r.text
    assert r.json()["deleted_count"] == 1


def test_dev_reset_canonical_refusal_still_sits_behind_the_r0_07_gate(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    db = db_with("warehouses", {"id": "w1", "org_id": ORG_A, "name": "A", "active": True})
    r = client_for(monkeypatch, warehouses, db, ADMIN).post("/api/dev/reset-warehouses")
    assert r.status_code == 404
    assert run(db["warehouses"].count_documents({})) == 1
