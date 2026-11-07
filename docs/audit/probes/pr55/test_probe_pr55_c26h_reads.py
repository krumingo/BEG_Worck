"""CLAUDE AUDIT probe — #55 C26h FG-60: a SiteManager (real company-scope grant) who is a member of P1 only
reads canonical history / balance unfiltered and filtered by P2 / by the warehouse. Expect only P1 rows; P2 or
warehouse filters → 403. Off and enforce. Uses the read handlers directly (production code, real Mongo)."""
from decimal import Decimal
import pytest
from fastapi import HTTPException
from app.services.warehouse_movements import CanonicalAction, LocationKey, LocationType
from tests.test_warehouse_canonical_c22_all_reports_cutover import ITEM, PROJECT, T, WH, _patch_dbs, _seed
from tests.test_warehouse_canonical_c25_cost_at_accept_transit import _Run
from tests.test_warehouse_canonical_c26a_writeoff_rights_values import OTHER_PROJECT, USER, _loader, _member
from tests.test_warehouse_canonical_c26e_r28_all_modes import _ctx
from tests.test_probe_pr55_c26e_real_assignments import REAL_SM

pytest_plugins = ["tests.warehouse_canonical_conftest"]


@pytest.mark.parametrize("mode", ["off", "enforce"])
async def test_sm_member_reads(canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    from app.permissions import service as perm
    from app.routes import warehouse_canonical_queries as Q
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db); await _seed(db)
    await db["projects"].insert_one({"id": OTHER_PROJECT, "org_id": T, "code": "PO", "name": "PO", "status": "Active"})
    run = _Run(client, allow_always_gate, db)
    await run.receive("20", "10")
    for p in (PROJECT, OTHER_PROJECT):
        d = await run.dispatch("5", project=p)
        await run.accept(d, "5", dest=LocationKey(LocationType.PROJECT, p), project=p)
    await _member(db)                                   # member of PROJECT only
    monkeypatch.setattr(perm, "_load_assignments", _loader(REAL_SM))
    monkeypatch.setattr(Q, "db", db, raising=False)
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    ctx = _ctx(mode, "SiteManager")
    if mode == "enforce":
        ctx.user = {"id": USER, "org_id": T, "role": "SiteManager"}
    out = {}
    import inspect
    async def call(fn, **kw):
        sig = inspect.signature(fn)
        base = dict(ctx=ctx, user={"id": USER, "org_id": T, "role": "SiteManager"}, item_id=ITEM,
                    location_type=None, location_id=None, project_id=None, since=None, until=None, limit=200,
                    cursor_after=None)
        base.update(kw)
        args = {k: v for k, v in base.items() if k in sig.parameters}
        for k, p in sig.parameters.items():
            if k not in args and p.default is not inspect.Parameter.empty:
                args[k] = p.default if not hasattr(p.default, "default") else p.default.default
        try:
            return await fn(**args)
        except HTTPException as e:
            return "HTTP %s" % e.status_code
    h = await call(Q.read_history)
    projs = set()
    if isinstance(h, dict):
        for r in h.get("rows", []):
            projs.add(r.get("project_id"))
    out["history unfiltered projects"] = sorted(p for p in projs if p) if isinstance(h, dict) else h
    out["history project=P2"] = (lambda r: r if isinstance(r, str) else "200 rows=%d" % len(r.get("rows", [])))(await call(Q.read_history, project_id=OTHER_PROJECT))
    out["history location=WH"] = (lambda r: r if isinstance(r, str) else "200 rows=%d" % len(r.get("rows", [])))(await call(Q.read_history, location_type=WH.location_type.value, location_id=WH.location_id))
    b = await call(Q.read_balance_by_location)
    out["balance locations"] = sorted({(r.get("location_type"), r.get("location_id")) for r in b.get("rows", b.get("locations", []))}) if isinstance(b, dict) else b
    print("\nRESULT mode=%s %s" % (mode, out))
    assert OTHER_PROJECT not in str(out["history unfiltered projects"]) and OTHER_PROJECT not in str(out["balance locations"])
    assert str(out["history project=P2"]).startswith("HTTP 403") and str(out["history location=WH"]).startswith("HTTP 403")
