"""Static-shape tests for the canonical action vocabulary.

The vocabulary is frozen: every FLOW-009 movement has a canonical name,
a permission string and a role in Rule B. A diff to these assertions
should only happen with an owner decision + FLOW doc change.
"""
import pytest

from app.services.warehouse_movements import (
    ALL_ACTIONS, INBOUND_ACTIONS, OUTBOUND_ACTIONS, QUARANTINE_ACTIONS,
    CanonicalAction,
)
from app.services.warehouse_movements.actions import (
    EVIDENCE_REQUIRED_ACTIONS, PERMISSION_ACTION,
    RULE_B_COSTING_ACTIONS, RULE_B_ZERO_COST_ACTIONS,
    permission_action_for,
)


def test_vocabulary_covers_every_flow_009_movement():
    expected = {
        "receive_from_supplier",
        "receive_from_supplier_to_project",
        "reserve",
        "release_reservation",
        "dispatch_warehouse_to_project",
        "accept_project_delivery",
        "transfer_project_to_warehouse",
        "transfer_project_to_project",
        "transfer_warehouse_to_warehouse",
        "consume_to_smr",
        "return_to_supplier",
        "write_off",
        "revision_adjustment",
        "quarantine_entry",
        "quarantine_release",
    }
    actual = {a.value for a in ALL_ACTIONS}
    assert actual == expected, f"missing/added: {expected ^ actual}"


def test_every_action_has_a_permission_string():
    for a in CanonicalAction:
        assert permission_action_for(a).startswith("warehouse.")


def test_outbound_and_inbound_sets_do_not_overlap():
    assert OUTBOUND_ACTIONS.isdisjoint(INBOUND_ACTIONS)


def test_quarantine_actions_are_disjoint_from_rule_b_costing():
    assert QUARANTINE_ACTIONS.isdisjoint(RULE_B_COSTING_ACTIONS)
    assert QUARANTINE_ACTIONS.isdisjoint(RULE_B_ZERO_COST_ACTIONS)


def test_rule_b_zero_cost_covers_dispatch_only():
    assert CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT in RULE_B_ZERO_COST_ACTIONS
    assert CanonicalAction.ACCEPT_PROJECT_DELIVERY not in RULE_B_ZERO_COST_ACTIONS


def test_rule_b_costing_covers_acceptance_and_consume():
    assert CanonicalAction.ACCEPT_PROJECT_DELIVERY in RULE_B_COSTING_ACTIONS
    assert CanonicalAction.CONSUME_TO_SMR in RULE_B_COSTING_ACTIONS


def test_evidence_required_includes_revision_and_write_off_and_supplier_return():
    assert CanonicalAction.REVISION_ADJUSTMENT in EVIDENCE_REQUIRED_ACTIONS
    assert CanonicalAction.WRITE_OFF in EVIDENCE_REQUIRED_ACTIONS
    assert CanonicalAction.RETURN_TO_SUPPLIER in EVIDENCE_REQUIRED_ACTIONS
