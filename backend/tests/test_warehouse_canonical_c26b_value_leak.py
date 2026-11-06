"""
5C-C26b — audit C26A-1 / C26A-2 (probe
docs/audit/probes/pr55/probe_pr55_c26a_value_leak.py @ claude/audit-log),
FG-23 / Р20: a non-finance role (Warehousekeeper, role_id ``warehouse``)
sees NO money on any canonical warehouse endpoint — GET stock / balance /
history / integrity-warnings (incl. the Path B warnings' counted_value /
covered_value / legacy_value) and the POST /movements and
/project-writeoff responses, the idempotent replay included. A finance role
still sees the values. The money scan is the probe's own rule.

Real Mongo (replica set); route handlers called in-process; only the
RoleAssignment loader and the route's Permission gate are fixtures.
"""
from __future__ import annotations

import re
from decimal import Decimal

import pytest

from app.services.warehouse_movements.service import CommandService
from tests.test_warehouse_canonical_c22_all_reports_cutover import (
    BEFORE, ITEM, PROJECT, T, _legacy_issue, _patch_dbs, _seed,
)
from tests.test_warehouse_canonical_c25_cost_at_accept_transit import _Run
from tests.test_warehouse_canonical_c26_one_path_per_lot import _invoice_line
from tests.test_warehouse_canonical_c26a_writeoff_rights_values import (
    USER, _UserCtx, _assignment, _loader, _member,
)

pytest_plugins = ["tests.warehouse_canonical_conftest"]

MONEY = re.compile(r"(value|cost|price|amount)", re.I)


def money_keys(obj, path=""):
    """The audit probe's scan (all list items, not only the first 3)."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if MONEY.search(k) and k != "values_hidden" and v not in (None, "", 0, "0"):
                out.append(path + "." + k)
            out += money_keys(v, path + "." + k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += money_keys(v, path + "[%d]" % i)
    return out


def _user():
    return {"id": USER, "org_id": T, "role": "Warehousekeeper", "email": "wk@x"}


async def _calls(client, gate, db, monkeypatch, role):
    from app.permissions import service as perm
    from app.routes import warehouse_canonical as cmd
    from app.routes import warehouse_canonical_queries as q
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    run = _Run(client, gate, db)
    await run.receive("10", "10")                       # admin-side setup
    # A Path B warning exists (legacy issue + invoice line, same material).
    await _legacy_issue(db, value=100.0, created_at=BEFORE, txn_id="legacy-leak")
    await _invoice_line(db)
    await _member(db)
    monkeypatch.setattr(q, "db", db)
    monkeypatch.setattr(cmd, "db", db)
    monkeypatch.setattr(perm, "_load_assignments", _loader([_assignment(role)]))

    async def _ok(*a, **k):
        return None
    monkeypatch.setattr(q, "_authorize_resource_scope", _ok)

    async def _all(ctx, user):
        return None
    monkeypatch.setattr(q, "_authorized_scope_locations", _all)
    # The per-action gate of /movements is not under test here.
    monkeypatch.setattr(cmd, "_service", lambda: CommandService(client, gate=gate))
    ctx = _UserCtx()
    dispatch = cmd.MovementCommandBody(
        action="dispatch_warehouse_to_project", item_id=ITEM, unit="bag", quantity="4",
        source={"location_type": "central_warehouse", "location_id": "wh_1"},
        destination={"location_type": "in_transit", "location_id": "pending",
                     "state": "in_transit"},
        project_id=PROJECT, idempotency_key="leak-dispatch")
    out = {
        "GET stock": await q.read_stock(ITEM, location_type="central_warehouse",
                                        location_id="wh_1", state="free", ctx=ctx),
        "GET balance": await q.read_balance_by_location(ITEM, ctx=ctx),
        "GET history": await q.read_history(item_id=ITEM, location_type=None,
                                            location_id=None, project_id=None, since=None,
                                            until=None, limit=100, cursor_after=None, ctx=ctx),
        "GET integrity-warnings": await q.read_integrity_warnings(ctx=ctx),
        "POST dispatch (response)": (await cmd.post_movement(
            dispatch, request=None, user=_user(), ctx=ctx)).dict(),
        "POST dispatch (replay)": (await cmd.post_movement(
            dispatch, request=None, user=_user(), ctx=ctx)).dict(),
    }
    return out


async def test_c26a_1_2_warehousekeeper_sees_no_money_anywhere(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """71c11da: POST dispatch envelope.unit_value + layer_allocations[*].unit_value;
    integrity-warnings counted_value / legacy_value."""
    client, db = canonical_mongo_db
    out = await _calls(client, allow_always_gate, db, monkeypatch, "warehouse")
    assert out["POST dispatch (replay)"]["replay"] is True
    leaks = {name: money_keys(body) for name, body in out.items() if money_keys(body)}
    assert leaks == {}, leaks
    codes = [w["code"] for w in out["GET integrity-warnings"]["warnings"]]
    assert "PATH_B_LEGACY_OVERLAP_UNPROVEN" in codes          # still shown, without money
    env = out["POST dispatch (response)"]["envelope"]
    assert env["values_hidden"] is True and env["quantity"] == "4"
    assert [a["quantity"] for a in env["layer_allocations"]] == ["4"]


async def test_finance_role_still_sees_the_values(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    out = await _calls(client, allow_always_gate, db, monkeypatch, "accountant")
    env = out["POST dispatch (response)"]["envelope"]
    assert Decimal(env["layer_allocations"][0]["unit_value"]) == Decimal("10")
    replay = out["POST dispatch (replay)"]["envelope"]
    assert replay["layer_allocations"] == env["layer_allocations"]
    assert "values_hidden" not in replay
    w = [w for w in out["GET integrity-warnings"]["warnings"]
         if w["code"] == "PATH_B_LEGACY_OVERLAP_UNPROVEN"][0]
    assert w["counted_value"] == pytest.approx(100.0)
    assert Decimal(out["GET stock"]["total_value"]) == Decimal("100")   # read before the dispatch


async def test_project_writeoff_response_has_no_money_for_a_member_site_manager(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    from app.permissions import audit_hooks, service as perm
    from app.routes import warehouse_canonical as cmd
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    run = _Run(client, allow_always_gate, db)
    await run.receive("10", "10")
    disp = await run.dispatch("10")
    await run.accept(disp, "10")
    await _member(db)
    monkeypatch.setattr(cmd, "db", db)
    monkeypatch.setattr(cmd, "_service", lambda: CommandService(client))
    monkeypatch.setattr(perm, "_load_assignments", _loader([_assignment("site_manager")]))

    async def _audit(*a, **k):
        return None
    monkeypatch.setattr(audit_hooks, "audit_permission_denied", _audit)
    body = cmd.ProjectWriteOffBody(project_id=PROJECT, item_id=ITEM, unit="bag",
                                   quantity="1", idempotency_key="leak-wo",
                                   reason="брак", file_ids=["f"])
    for _ in range(2):                                   # fresh + replay
        res = (await cmd.post_project_writeoff(body, request=None, user=_user(),
                                               ctx=_UserCtx())).dict()
        assert money_keys(res) == []
        assert res["envelope"]["values_hidden"] is True
