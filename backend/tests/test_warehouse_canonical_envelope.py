"""Unit tests for the canonical movement envelope (§4.1).

Pure, DB-free. These assertions pin down the envelope's shape so an
accidental change to the schema is caught at test time.
"""
from decimal import Decimal

import pytest

from app.services.warehouse_movements import (
    LocationKey, LocationType, MovementState,
    build_envelope, envelope_fingerprint, validate_envelope,
    LayerAllocation,
)


def _warehouse():
    return LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_central_1")


def _project():
    return LocationKey(LocationType.PROJECT, "project_1")


def _common():
    return dict(
        tenant_id="org_1",
        action="receive_from_supplier",
        item_id="item_bag_25",
        unit="bag",
        quantity=Decimal("40"),
        actor_id="user_1",
        idempotency_key="supplier-receipt-2026-10-12-abc",
        unit_value=Decimal("12.50"),
    )


def test_envelope_builds_with_minimum_required_fields():
    env = build_envelope(
        **_common(),
        source=LocationKey(LocationType.SUPPLIER, "sup_1"),
        destination=_warehouse(),
    )
    validate_envelope(env)
    d = env.to_dict()
    assert d["item_id"] == "item_bag_25"
    assert d["unit"] == "bag"
    assert d["quantity"] == "40"
    assert d["source"]["location_type"] == "supplier"
    assert d["destination"]["location_type"] == "central_warehouse"
    # layer_allocations present (empty on inbound)
    assert d["layer_allocations"] == []


def test_envelope_rejects_missing_item_id():
    with pytest.raises(ValueError):
        env = build_envelope(
            **{**_common(), "item_id": ""},
            source=LocationKey(LocationType.SUPPLIER, "sup_1"),
            destination=_warehouse(),
        )
        validate_envelope(env)


def test_envelope_rejects_zero_or_negative_quantity():
    for bad in [Decimal("0"), Decimal("-1")]:
        with pytest.raises(ValueError):
            env = build_envelope(
                **{**_common(), "quantity": bad},
                source=LocationKey(LocationType.SUPPLIER, "sup_1"),
                destination=_warehouse(),
            )
            validate_envelope(env)


def test_envelope_requires_source_or_destination():
    with pytest.raises(ValueError):
        env = build_envelope(
            **_common(), source=None, destination=None,
        )
        validate_envelope(env)


def test_acceptance_requires_dispatch_movement_id_and_accepted_quantity():
    base = _common()
    base["action"] = "accept_project_delivery"
    env = build_envelope(**base, source=None, destination=_project())
    with pytest.raises(ValueError):
        validate_envelope(env)


def test_fingerprint_stable_across_rebuilds():
    base = _common()
    env1 = build_envelope(**base, source=LocationKey(LocationType.SUPPLIER, "sup_1"),
                          destination=_warehouse())
    env2 = build_envelope(**base, source=LocationKey(LocationType.SUPPLIER, "sup_1"),
                          destination=_warehouse())
    # recorded_at differs between builds; fingerprint should ignore it.
    fp1 = envelope_fingerprint(env1)
    fp2 = envelope_fingerprint(env2)
    assert fp1 == fp2
    assert len(fp1) == 64


def test_fingerprint_changes_when_payload_changes():
    env1 = build_envelope(**_common(), source=None, destination=_warehouse())
    env2 = build_envelope(**{**_common(), "quantity": Decimal("41")},
                          source=None, destination=_warehouse())
    assert envelope_fingerprint(env1) != envelope_fingerprint(env2)


def test_layer_allocation_roundtrip():
    la = LayerAllocation("mv_abc", 1, Decimal("10"), Decimal("12.50"))
    d = la.to_dict()
    la2 = LayerAllocation.from_dict(d)
    assert la2 == la
    assert la.total_value() == Decimal("125.0000")
