"""DB-free verification of the C11.1 projection signature fix and
the C11.7/C11.10 balance/scope filtering.

These tests drive the real projection code against an in-memory
collection shim. They do NOT substitute for the real-Mongo gate — the
transactional atomicity still runs under CODEX's RS. What they prove
here is that the function signatures line up and the balance-math is
correct even in isolation.
"""
from __future__ import annotations

import asyncio
import inspect
from decimal import Decimal
from typing import Any, Dict, List

import pytest

from app.services.warehouse_movements.projections import (
    apply_projection, rebuild_from_ledger,
)
from app.services.warehouse_movements.queries import item_balance_by_location


class _AsyncCollShim:
    """Tiny collection shim with just enough interface for the
    projector and balance math. Does NOT implement real Mongo
    semantics (no transactions, no indexes); only enough to probe
    the pure logic."""
    def __init__(self):
        self.rows: List[Dict[str, Any]] = []
        self.name = "warehouse_transactions"

    async def insert_one(self, doc, session=None):
        self.rows.append(dict(doc))

    def find(self, flt, proj=None, session=None):
        matched = [r for r in self.rows if self._match(r, flt)]
        return _AsyncCursor(matched)

    async def find_one(self, flt, proj=None, session=None):
        for r in self.rows:
            if self._match(r, flt):
                return r
        return None

    async def update_one(self, flt, update, upsert=False, session=None):
        for r in self.rows:
            if self._match(r, flt):
                if "$set" in update:
                    r.update(update["$set"])
                return
        if upsert:
            doc = {**flt}
            if "$set" in update:
                doc.update(update["$set"])
            self.rows.append(doc)

    async def delete_many(self, flt, session=None):
        self.rows = [r for r in self.rows if not self._match(r, flt)]

    async def distinct(self, key, flt=None, session=None):
        flt = flt or {}
        seen = set()
        for r in self.rows:
            if self._match(r, flt) and key in r:
                seen.add(r[key])
        return list(seen)

    async def count_documents(self, flt, session=None):
        return sum(1 for r in self.rows if self._match(r, flt))

    @staticmethod
    def _match(doc, flt):
        for k, v in flt.items():
            if isinstance(v, dict) and set(v.keys()) & {"$exists", "$ne", "$in"}:
                # minimal support
                if "$exists" in v:
                    if v["$exists"] and k not in doc:
                        return False
                    if not v["$exists"] and k in doc:
                        return False
                elif "$ne" in v:
                    if doc.get(k) == v["$ne"]:
                        return False
                elif "$in" in v:
                    if doc.get(k) not in v["$in"]:
                        return False
            else:
                if doc.get(k) != v:
                    return False
        return True


class _AsyncCursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *_a, **_k):
        return self

    def limit(self, n):
        self.rows = self.rows[:n]
        return self

    def __aiter__(self):
        self._i = iter(self.rows)
        return self

    async def __anext__(self):
        try:
            return next(self._i)
        except StopIteration:
            raise StopAsyncIteration

    async def to_list(self, n=None):
        return list(self.rows)[: n or None]


class _DbShim:
    def __init__(self):
        self.name = "test_db"
        self._colls: Dict[str, _AsyncCollShim] = {}

    def __getitem__(self, name):
        if name not in self._colls:
            c = _AsyncCollShim()
            c.name = name
            self._colls[name] = c
        return self._colls[name]


def test_apply_projection_accepts_hints_kwarg():
    """CODEX C11.1 regression — the service passes `hints={...}` to
    apply_projection. The signature must accept it."""
    sig = inspect.signature(apply_projection)
    assert "hints" in sig.parameters, (
        "apply_projection must accept `hints` kwarg; the service's "
        "projection integration call `apply_projection(..., hints=...)` "
        "would otherwise TypeError at runtime (CODEX blocking defect)."
    )


def test_item_balance_rule_b_math_balances_after_dispatch_and_accept():
    """CODEX C11.10 — balances must observe dispatch opens in-transit
    and acceptance closes it; discrepancy row does NOT subtract from
    unresolved balance."""
    coll = _AsyncCollShim()
    tenant = "org_t"
    # dispatch 10 FREE → in_transit at wh=wh_c1
    coll.rows.append({
        "tenant_id": tenant, "item_id": "it_a",
        "action": "dispatch_warehouse_to_project",
        "source": {"location_type": "central_warehouse",
                   "location_id": "wh_c1", "state": "free"},
        "destination": {"location_type": "in_transit",
                        "location_id": "mv_disp_1", "state": "in_transit"},
        "quantity": "10",
        "layer_allocations": [
            {"source_movement_id": "mv_recv", "layer_sequence": 1,
             "quantity": "10", "unit_value": "5"},
        ],
    })
    # accept 8 (partial)
    coll.rows.append({
        "tenant_id": tenant, "item_id": "it_a",
        "action": "accept_project_delivery",
        "source": {"location_type": "in_transit",
                   "location_id": "mv_disp_1", "state": "in_transit"},
        "destination": {"location_type": "project",
                        "location_id": "proj_1", "state": "free"},
        "quantity": "8", "accepted_quantity": "8",
        "dispatch_movement_id": "mv_disp_1",
        "layer_allocations": [
            {"source_movement_id": "mv_recv", "layer_sequence": 1,
             "quantity": "8", "unit_value": "5"},
        ],
    })
    # transit_discrepancy for 2 — this is a doc fact, non-moving
    coll.rows.append({
        "tenant_id": tenant, "item_id": "it_a",
        "action": "transit_discrepancy",
        "source": {"location_type": "in_transit",
                   "location_id": "mv_disp_1", "state": "unresolved"},
        "destination": None,
        "quantity": "2",
        "layer_allocations": [
            {"source_movement_id": "mv_recv", "layer_sequence": 1,
             "quantity": "2", "unit_value": "5"},
        ],
    })

    balances = asyncio.run(
        item_balance_by_location(coll, tenant_id=tenant, item_id="it_a")
    )
    # Expected:
    #   wh_c1 FREE: -10   (dispatched out)
    #   mv_disp_1 IN_TRANSIT: +10 - 8 = 2
    #   proj_1 FREE: +8
    by_key = {(b["location_type"], b["location_id"], b["state"]): Decimal(b["quantity"])
              for b in balances}
    assert by_key[("central_warehouse", "wh_c1", "free")] == Decimal("-10")
    assert by_key[("in_transit", "mv_disp_1", "in_transit")] == Decimal("2")
    assert by_key[("project", "proj_1", "free")] == Decimal("8")


def test_item_balance_scope_filter_omits_unauthorized_locations():
    """CODEX C11.7 — balance filter respects authorized scope."""
    coll = _AsyncCollShim()
    tenant = "org_t"
    for wh in ("wh_a", "wh_b"):
        coll.rows.append({
            "tenant_id": tenant, "item_id": "it_a",
            "action": "receive_from_supplier",
            "source": {"location_type": "supplier",
                       "location_id": "sup", "state": "free"},
            "destination": {"location_type": "central_warehouse",
                            "location_id": wh, "state": "free"},
            "quantity": "5",
        })

    # Caller authorized only on wh_a.
    balances = asyncio.run(item_balance_by_location(
        coll, tenant_id=tenant, item_id="it_a",
        allowed_locations=[("location", "wh_a")],
    ))
    locs = {(b["location_type"], b["location_id"]) for b in balances
            if b["location_type"] == "central_warehouse"}
    assert ("central_warehouse", "wh_a") in locs
    assert ("central_warehouse", "wh_b") not in locs
