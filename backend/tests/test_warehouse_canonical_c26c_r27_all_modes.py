"""
5C-C26c — Р27 gives the same answer in off, shadow and enforce.

off / shadow decide from the legacy session role (W0-02; same pattern as
SEC-01 ``require_money_write``, #69) with the catalog's PROJECT_WRITEOFF_RULE
and the same in-date membership check; enforce decides from RoleAssignments.
Shadow also computes the RoleAssignment decision and only logs a mismatch.

The canonical ledger is written only in enforce (TASK 5C contract,
test_warehouse_canonical_mongo.test_service_refuses_without_enforce_mode):
in off / shadow an ALLOWED caller gets 503 CANONICAL_WRITES_REQUIRE_ENFORCE
(Р27 passed), a DENIED caller 403 R27_WRITE_OFF_NOT_ALLOWED — never mixed,
and nothing is written in either case.
"""
from __future__ import annotations

import logging

import pytest
from fastapi import HTTPException

from app.services.warehouse_movements.service import CommandService
from app.tenancy.guard import LegacyCompatContext
from tests.test_warehouse_canonical_c22_all_reports_cutover import ITEM, PROJECT, T
from tests.test_warehouse_canonical_c26a_writeoff_rights_values import (
    USER, _UserCtx, _assignment, _ledger_count, _member,
)
from tests.test_warehouse_canonical_c26b_project_writeoff_endpoint import _setup

pytest_plugins = ["tests.warehouse_canonical_conftest"]

# legacy session role, the matching RoleAssignment, membership, Р27 allows?
MATRIX = [
    ("Owner", "owner", None, True),
    ("Admin", "admin", None, True),
    ("Accountant", "accountant", None, True),
    ("Accountant", "accountant", {"to_date": "2021-01-01"}, True),
    ("Technician", "LEGACY_TECHNICIAN", {}, True),
    ("Technician", "LEGACY_TECHNICIAN", None, False),
    ("Technician", "LEGACY_TECHNICIAN", {"to_date": "2021-01-01"}, False),
    ("SiteManager", "site_manager", {}, True),
    ("SiteManager", "site_manager", None, False),
    ("SiteManager", "site_manager", {"to_date": "2021-01-01"}, False),
    ("Viewer", "LEGACY_VIEWER", {}, False),
    ("Driver", "driver", {}, False),
    ("Warehousekeeper", "warehouse", {}, False),
]


def _ids():
    return ["%s-%s" % (m[0], "member" if m[2] == {} else "none" if m[2] is None else "expired")
            for m in MATRIX]


async def _call(route, mode, legacy_role):
    user = {"id": USER, "org_id": T, "role": legacy_role, "email": "m@x"}
    ctx = _UserCtx() if mode == "enforce" else LegacyCompatContext(user, mode=mode)
    if mode == "enforce":
        ctx.mode = "enforce"
    body = route.ProjectWriteOffBody(
        project_id=PROJECT, item_id=ITEM, unit="bag", quantity="1",
        idempotency_key=f"c26c-{mode}-{legacy_role}", reason="брак", file_ids=["f"])
    return await route.post_project_writeoff(body, request=None, user=user, ctx=ctx)


@pytest.mark.parametrize("mode", ["off", "shadow", "enforce"])
@pytest.mark.parametrize("legacy_role,role_id,membership,allowed", MATRIX, ids=_ids())
async def test_r27_role_matrix_in_every_mode(
        canonical_mongo_db, allow_always_gate, monkeypatch,
        mode, legacy_role, role_id, membership, allowed):
    client, db = canonical_mongo_db
    route, audits = await _setup(client, allow_always_gate, db, monkeypatch,
                                 [_assignment(role_id)])
    if membership is not None:
        await _member(db, **membership)
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    before = await _ledger_count(db)
    if allowed and mode == "enforce":
        res = await _call(route, mode, legacy_role)
        assert res.envelope["action"] == "write_off"
        assert await _ledger_count(db) == before + 1
        return
    with pytest.raises(HTTPException) as exc:
        await _call(route, mode, legacy_role)
    if allowed:
        assert exc.value.status_code == 503
        assert exc.value.detail["error_code"] == "CANONICAL_WRITES_REQUIRE_ENFORCE"
    else:
        assert exc.value.status_code == 403
        assert exc.value.detail["context"]["reason_code"] == "R27_WRITE_OFF_NOT_ALLOWED"
    assert await _ledger_count(db) == before                     # nothing written
    # The denial AuditEvent is an enforce-only write (W0-02).
    assert len(audits) == (1 if (mode == "enforce" and not allowed) else 0)


async def test_shadow_logs_a_mismatch_but_the_legacy_role_decides(
        canonical_mongo_db, allow_always_gate, monkeypatch, caplog):
    """Legacy role Accountant (Р27 allows) but no RoleAssignment (enforce
    would deny): shadow keeps the legacy outcome and logs the mismatch."""
    client, db = canonical_mongo_db
    route, _ = await _setup(client, allow_always_gate, db, monkeypatch, [])
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "shadow")
    with caplog.at_level(logging.WARNING):
        with pytest.raises(HTTPException) as exc:
            await _call(route, "shadow", "Accountant")
    assert exc.value.detail["error_code"] == "CANONICAL_WRITES_REQUIRE_ENFORCE"
    assert "PERMISSION_SHADOW_MISMATCH action=warehouse.project_writeoff" in caplog.text
