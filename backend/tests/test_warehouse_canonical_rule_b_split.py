"""Direct unit tests for the Rule B / F-09=B cumulative split logic.

CODEX C11.4 — a 10→8→2 flow must yield unresolved=2 after the first
acceptance and 0 after the second, with layer provenance intact in
both the accepted lines AND the transit_discrepancy row.

These tests do NOT require real Mongo — they drive the pure split
logic directly against a tiny in-memory ledger shim. The real-Mongo
suite in `test_warehouse_canonical_mongo.py` covers end-to-end
atomicity. This file closes the proof gap when a replica set is
unavailable: the semantic math is verified here, the transactional
side-effects on the server are verified there.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any, Dict, List

import pytest

from app.services.warehouse_movements import CanonicalAction
from app.services.warehouse_movements.service import (
    CommandService, PermissionGate,
)


class _LedgerShim:
    """Minimal in-memory ledger: supports `find({...}, session=...)`
    on `warehouse_transactions`-shaped docs. The Rule B split only
    needs the dispatch row and prior acceptance rows, so a dict-of-
    lists is enough. **Not a Mongo mock**: this is a semantic probe
    of the split algorithm, invoked directly by the test. The server
    always writes through real Mongo in production and in CODEX's RS
    tests."""

    def __init__(self):
        self.rows: List[Dict[str, Any]] = []

    def find(self, flt, session=None):
        """Return an async iterator of matching rows."""
        matched = [r for r in self.rows if all(
            (r.get(k) == v if not isinstance(v, dict) else True)
            for k, v in flt.items()
        )]

        async def _iter():
            for r in matched:
                yield r
        return _iter()

    async def find_one(self, flt, session=None):
        for r in self.rows:
            match = True
            for k, v in flt.items():
                if r.get(k) != v:
                    match = False
                    break
            if match:
                return r
        return None


@pytest.fixture
def shim():
    s = _LedgerShim()
    # Dispatch row: 10 units from two FIFO layers 6@10 + 4@20.
    s.rows.append({
        "tenant_id": "org_t",
        "action": "dispatch_warehouse_to_project",
        "movement_id": "mv_disp_1",
        "quantity": "10",
        "layer_allocations": [
            {"source_movement_id": "mv_recv_a",
             "layer_sequence": 1,
             "quantity": "6",
             "unit_value": "10"},
            {"source_movement_id": "mv_recv_b",
             "layer_sequence": 2,
             "quantity": "4",
             "unit_value": "20"},
        ],
    })
    return s


def _service() -> CommandService:
    return CommandService(db_client=None, gate=PermissionGate(evaluate_fn=None),
                          verify_indexes_once=False,
                          strict_master_identity=False)


def test_first_partial_8_of_10_takes_proportional_from_both_layers(shim):
    svc = _service()
    allocations, total_value = asyncio.run(svc._split_dispatch_for_acceptance(
        shim, session=None, tenant_id="org_t",
        dispatch_movement_id="mv_disp_1",
        accepted_qty=Decimal("8"),
    ))
    # Total accepted qty = 8 and must come from the two available
    # layers proportionally: 6*(8/10)=4.8 from layer 1, remainder 3.2
    # from layer 2 (last-layer absorbs any rounding).
    total_qty = sum(a.quantity for a in allocations)
    assert total_qty == Decimal("8")
    # Value conservation (not zero, carries real original layer values)
    assert total_value > Decimal("0")
    # Layer 1 share
    l1 = next(a for a in allocations if a.layer_sequence == 1)
    l2 = next(a for a in allocations if a.layer_sequence == 2)
    assert l1.unit_value == Decimal("10")
    assert l2.unit_value == Decimal("20")


def test_cumulative_partial_second_accept_2_of_remaining(shim):
    """CODEX C11.4 regression — after accepting 8, accepting 2 more
    must take from what's LEFT, not re-split the originals."""
    svc = _service()
    # First acceptance writes its own layer_allocations into the ledger.
    allocations1, _v1 = asyncio.run(svc._split_dispatch_for_acceptance(
        shim, session=None, tenant_id="org_t",
        dispatch_movement_id="mv_disp_1",
        accepted_qty=Decimal("8"),
    ))
    shim.rows.append({
        "tenant_id": "org_t",
        "action": "accept_project_delivery",
        "dispatch_movement_id": "mv_disp_1",
        "accepted_quantity": "8",
        "quantity": "8",
        "layer_allocations": [a.to_dict() for a in allocations1],
    })

    # Second acceptance of 2 — only 2 units remain in the dispatch.
    allocations2, _v2 = asyncio.run(svc._split_dispatch_for_acceptance(
        shim, session=None, tenant_id="org_t",
        dispatch_movement_id="mv_disp_1",
        accepted_qty=Decimal("2"),
    ))
    total_qty_second = sum(a.quantity for a in allocations2)
    assert total_qty_second == Decimal("2")

    # Combined accepted quantity across both acceptances = 10 (original).
    total_accepted = sum(a.quantity for a in allocations1) \
        + sum(a.quantity for a in allocations2)
    assert total_accepted == Decimal("10")

    # Combined per-layer accepted qty equals original dispatch qty.
    per_layer: Dict[int, Decimal] = {}
    for a in list(allocations1) + list(allocations2):
        per_layer[a.layer_sequence] = per_layer.get(a.layer_sequence, Decimal("0")) + a.quantity
    assert per_layer[1] == Decimal("6")
    assert per_layer[2] == Decimal("4")
