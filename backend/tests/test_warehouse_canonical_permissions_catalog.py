"""Permission catalog shape tests for TASK 5C warehouse actions.

Owner / Admin inherit `_ALL`; every other role has an EXPLICIT list.
A role gaining a stock-writing action by accident (e.g. a copy-paste
leak into `driver`) must fail this test.
"""
import pytest

from app.permissions.catalog import (
    ACTIONS, CANONICAL_ROLES, PERMISSION_MATRIX, role_actions,
)
from app.services.warehouse_movements.actions import (
    PERMISSION_ACTION, CanonicalAction,
)


WAREHOUSE_ACTIONS = {
    "warehouse.write_command",
    "warehouse.receive_from_supplier",
    "warehouse.receive_from_supplier_to_project",
    "warehouse.reserve",
    "warehouse.release_reservation",
    "warehouse.dispatch_to_project",
    "warehouse.accept_delivery",
    "warehouse.transfer_project_to_warehouse",
    "warehouse.transfer_project_to_project",
    "warehouse.transfer_warehouse_to_warehouse",
    "warehouse.consume_smr",
    "warehouse.return_to_supplier",
    "warehouse.write_off",
    "warehouse.revision_adjustment",
    "warehouse.quarantine_entry",
    "warehouse.quarantine_release",
    "warehouse.read_stock",
    "warehouse.read_history",
    "warehouse.migration.readiness",
    "warehouse.migration.execute",
}


def test_every_warehouse_action_is_in_the_catalog():
    missing = WAREHOUSE_ACTIONS - ACTIONS
    assert not missing, f"catalog missing: {missing}"


def test_every_canonical_action_maps_to_a_catalog_action():
    for a in CanonicalAction:
        pname = PERMISSION_ACTION[a]
        assert pname in ACTIONS, f"{pname} not in ACTIONS"


def test_owner_and_admin_have_every_warehouse_action():
    for role in ("owner", "admin"):
        granted = CANONICAL_ROLES[role]["actions"]
        for a in WAREHOUSE_ACTIONS:
            assert a in granted, f"{role} missing {a}"


def test_driver_has_no_warehouse_actions():
    granted = CANONICAL_ROLES["driver"]["actions"]
    for a in WAREHOUSE_ACTIONS:
        assert a not in granted, f"driver gained {a}"


def test_worker_has_no_warehouse_writes():
    granted = CANONICAL_ROLES["worker"]["actions"]
    writes = WAREHOUSE_ACTIONS - {"warehouse.read_stock", "warehouse.read_history"}
    overlap = granted & writes
    assert not overlap, f"worker gained write permissions: {overlap}"


def test_ai_service_has_no_stock_actions():
    granted = CANONICAL_ROLES["ai_service"]["actions"]
    assert not (granted & WAREHOUSE_ACTIONS), "ai_service must not auto-grant"


def test_accountant_can_read_but_not_write():
    granted = CANONICAL_ROLES["accountant"]["actions"]
    assert "warehouse.read_stock" in granted
    assert "warehouse.read_history" in granted
    writes = WAREHOUSE_ACTIONS - {"warehouse.read_stock", "warehouse.read_history"}
    assert not (granted & writes), "accountant must not have warehouse writes"


def test_warehouse_role_cannot_consume_or_write_off_or_revise():
    """Warehouse operator cannot authorize SMR consumption, write-off or
    revision; those are PM/Admin/Owner actions."""
    granted = CANONICAL_ROLES["warehouse"]["actions"]
    forbidden = {
        "warehouse.consume_smr",
        "warehouse.write_off",
        "warehouse.revision_adjustment",
        "warehouse.return_to_supplier",
        "warehouse.receive_from_supplier_to_project",
    }
    overlap = granted & forbidden
    assert not overlap, f"warehouse role granted forbidden: {overlap}"


def test_procurement_can_receive_but_not_consume_or_revise():
    granted = CANONICAL_ROLES["procurement"]["actions"]
    assert "warehouse.receive_from_supplier" in granted
    assert "warehouse.return_to_supplier" in granted
    forbidden = {
        "warehouse.consume_smr",
        "warehouse.write_off",
        "warehouse.revision_adjustment",
    }
    overlap = granted & forbidden
    assert not overlap, f"procurement role granted forbidden: {overlap}"
